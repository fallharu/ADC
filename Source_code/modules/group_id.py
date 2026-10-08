import math
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

import pandas as pd
import time
from tqdm import tqdm

from .db_manager import MAIN_DB_PATH
from .perf_utils import resolve_worker_count


def _normalize_track_id(raw: object) -> Optional[int]:
    """トラックIDを正規化して整数に変換する。無効値は None を返す。"""
    if raw is None:
        return None

    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode()
        except Exception:
            return None

    if isinstance(raw, str):
        candidate = raw.strip()
        if not candidate:
            return None
        raw = candidate

    if isinstance(raw, (list, tuple)):
        if not raw:
            return None
        raw = raw[0]

    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None

    if math.isnan(value) or math.isinf(value):
        return None

    # ここ重要: 端数がある値を round で別IDに化けさせない
    track_int = int(round(value))
    if abs(value - track_int) > 1e-6:
        return None

    if track_int < 0:
        return None
    return track_int


def assign_group_ids(run_id: int):
    start_time = time.time()

    # 1) まず run の group_id を全消去
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE Detection SET group_id = NULL WHERE run_id = ?", (run_id,))
        conn.commit()

        # ★変更点: 最初の採番は best(タイヤ) を除外（＝車両側だけ）
        df_tracks = pd.read_sql_query(
            """
            SELECT auto_id, track_id, frame_num, x1, y1, x2, y2, class_id
            FROM Detection
            WHERE run_id = ?
              AND LOWER(model_name) != 'best'
            ORDER BY frame_num
            """,
            conn,
            params=(run_id,),
        )

    if df_tracks.empty:
        print(f"Run ID {run_id}: 検出データがないため、グループ割当をスキップします。")
        return time.time() - start_time

    df_tracks["track_key"] = df_tracks["track_id"].apply(_normalize_track_id)

    # track_id が一切取れていない場合、今のやり方だと「全行=別グループ」で爆発するので止める
    if not df_tracks["track_key"].notna().any():
        print(
            f"Run ID {run_id}: 有効な track_id がありません。"
            " 追跡IDがDBに保存されているか、推論側でtrack_idの書き込みを確認してください。"
        )
        # この場合は group_id を入れない方が安全（爆発回避）
        return time.time() - start_time

    # 2) track_id があるものは track_id -> group_id で確定
    track_vals = sorted(pd.unique(df_tracks.loc[df_tracks["track_key"].notna(), "track_key"]))
    track_to_group: Dict[int, int] = {int(tv): i + 1 for i, tv in enumerate(track_vals)}
    next_group_id = len(track_to_group) + 1

    df_tracks["group_id"] = df_tracks["track_key"].map(track_to_group)

    # 3) track_id が欠落した行は「近傍の最近グループ」へ吸収（なければ新規）
    #    ※これで「欠落1行ごとに増殖」をかなり抑えられます
    RECONNECT_FRAME_GAP = 10
    RECONNECT_DISTANCE_PX = 150

    df_tracks["center_x"] = (df_tracks["x1"] + df_tracks["x2"]) / 2
    df_tracks["center_y"] = (df_tracks["y1"] + df_tracks["y2"]) / 2

    # class_id -> {gid: (last_frame, cx, cy)}
    last_seen: Dict[int, Dict[int, Tuple[int, float, float]]] = {}

    for i, row in df_tracks.iterrows():
        frame = int(row["frame_num"])
        cls = int(row["class_id"])
        cx = float(row["center_x"])
        cy = float(row["center_y"])

        cls_map = last_seen.setdefault(cls, {})

        # 古い候補を掃除
        cutoff = frame - RECONNECT_FRAME_GAP
        for gid in list(cls_map.keys()):
            if cls_map[gid][0] < cutoff:
                del cls_map[gid]

        gid = row["group_id"]
        if pd.isna(gid):
            best_gid = None
            best_dist = None
            for cand_gid, (lf, lx, ly) in cls_map.items():
                gap = frame - lf
                if gap <= 0 or gap > RECONNECT_FRAME_GAP:
                    continue
                dist = math.hypot(cx - lx, cy - ly)
                if dist <= RECONNECT_DISTANCE_PX and (best_dist is None or dist < best_dist):
                    best_dist = dist
                    best_gid = cand_gid

            if best_gid is not None:
                gid = best_gid
            else:
                gid = next_group_id
                next_group_id += 1

            df_tracks.at[i, "group_id"] = int(gid)

        gid_int = int(gid)
        cls_map[gid_int] = (frame, cx, cy)

    df_tracks["group_id"] = df_tracks["group_id"].astype(int)

    # 4) DBへ反映（車両側だけ）
    vehicle_updates = df_tracks[["group_id", "auto_id"]].values.tolist()
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        c = conn.cursor()
        c.executemany("UPDATE Detection SET group_id = ? WHERE auto_id = ?", vehicle_updates)
        conn.commit()

        unique_groups = int(df_tracks["group_id"].nunique())
        print(f"Run ID {run_id}: 車両側へ group_id を割り当てました（ユニーク {unique_groups}）。")

        # ★重要: タイヤ側(best)はここでは group_id を付けない（増殖の元を断つ）
        c.execute(
            "UPDATE Detection SET group_id = NULL WHERE run_id = ? AND LOWER(model_name) = 'best'",
            (run_id,),
        )
        conn.commit()

    # 5) タイヤ→車両 紐付け（ここで初めてタイヤに group_id を入れる）
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        df_vehicles = pd.read_sql_query(
            """
            SELECT auto_id, frame_num, x1, y1, x2, y2, group_id
            FROM Detection
            WHERE run_id = ?
              AND group_id IS NOT NULL
              AND LOWER(model_name) != 'best'
            """,
            conn,
            params=(run_id,),
        )
        df_tires = pd.read_sql_query(
            """
            SELECT auto_id, frame_num, x1, y1, x2, y2
            FROM Detection
            WHERE run_id = ?
              AND LOWER(model_name) = 'best'
            """,
            conn,
            params=(run_id,),
        )

    if df_tires.empty or df_vehicles.empty:
        return time.time() - start_time

    vehicles_by_frame: Dict[int, List[dict]] = {
        int(frame): group.to_dict("records") for frame, group in df_vehicles.groupby("frame_num")
    }
    tires_by_frame: Dict[int, List[dict]] = {
        int(frame): group.to_dict("records") for frame, group in df_tires.groupby("frame_num")
    }
    frame_items: List[Tuple[int, List[dict]]] = list(tires_by_frame.items())

    def match_frame(item: Tuple[int, List[dict]]) -> List[Tuple[int, int]]:
        frame_num, tires = item
        vehicles_in_frame = vehicles_by_frame.get(frame_num)
        if not vehicles_in_frame:
            return []
        updates: List[Tuple[int, int]] = []
        for tire in tires:
            tx = (tire["x1"] + tire["x2"]) / 2
            ty = (tire["y1"] + tire["y2"]) / 2
            for vehicle in vehicles_in_frame:
                if vehicle["x1"] <= tx <= vehicle["x2"] and vehicle["y1"] <= ty <= vehicle["y2"]:
                    updates.append((int(vehicle["group_id"]), int(tire["auto_id"])))
                    break
        return updates

    tire_updates: List[Tuple[int, int]] = []
    worker_count = resolve_worker_count(
        "POST_PROCESS_MATCH_WORKERS",
        fallback=min(8, (os.cpu_count() or 2)),
        max_workers=16,
    )

    if worker_count > 1 and len(frame_items) > 1:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            for updates in tqdm(
                executor.map(match_frame, frame_items),
                total=len(frame_items),
                desc="タイヤと車両の紐付け中",
            ):
                if updates:
                    tire_updates.extend(updates)
    else:
        for item in tqdm(frame_items, desc="タイヤと車両の紐付け中"):
            updates = match_frame(item)
            if updates:
                tire_updates.extend(updates)

    if tire_updates:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            c = conn.cursor()
            c.executemany("UPDATE Detection SET group_id = ? WHERE auto_id = ?", tire_updates)
            conn.commit()
            print(f"Run ID {run_id}: {len(tire_updates)} 個のタイヤを車両に紐付けしました。")

    return time.time() - start_time
