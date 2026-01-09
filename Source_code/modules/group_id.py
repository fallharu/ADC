# 役割: 車両とタイヤを紐付け、共通のgroup_idを割り当てる
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
        except Exception:  # noqa: BLE001
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

    track_int = int(round(value))
    if track_int < 0:
        return None
    return track_int


def assign_group_ids(run_id: int):
    start_time = time.time()
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE Detection SET group_id = NULL WHERE run_id = ?", (run_id,))
        conn.commit()

        df_tracks = pd.read_sql_query(
            """
            SELECT auto_id, track_id
            FROM Detection
            WHERE run_id = ? AND LOWER(model_name) != 'best'
            """,
            conn,
            params=(run_id,),
        )

    if df_tracks.empty:
        print(
            f"Run ID {run_id}: モデル 'best' 以外の検出が見つからなかったため、グループ割当をスキップします。"
        )
        return time.time() - start_time

    df_tracks['track_key'] = df_tracks['track_id'].apply(_normalize_track_id)
    if not df_tracks['track_key'].notna().any():
        print(
            f"Run ID {run_id}: 有効な track_id を持つ車両検出がありません。"
            " すべての車両検出へ個別の group_id を割り当てます。"
        )

    track_to_group: Dict[int, int] = {}
    next_group_id = 1

    def allocate_group_id(track_value: Optional[int]) -> int:
        nonlocal next_group_id

        if track_value is not None:
            if track_value not in track_to_group:
                track_to_group[track_value] = next_group_id
                next_group_id += 1
            return track_to_group[track_value]

        generated_id = next_group_id
        next_group_id += 1
        return generated_id

    df_tracks['group_id'] = df_tracks['track_key'].apply(allocate_group_id).astype(int)
    vehicle_updates = df_tracks[['group_id', 'auto_id']].values.tolist()
    missing_track_rows = int(df_tracks['track_key'].isna().sum())
    unique_track_groups = len(track_to_group)
    total_vehicle_rows = len(df_tracks)

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        c = conn.cursor()
        c.executemany("UPDATE Detection SET group_id = ? WHERE auto_id = ?", vehicle_updates)
        conn.commit()
        print(
            f"Run ID {run_id}: {unique_track_groups} 件の track_id から "
            f"{total_vehicle_rows} 件の車両検出へ group_id を割り当てました。"
        )
        if missing_track_rows:
            print(
                f"Run ID {run_id}: track_id が欠落している車両検出が {missing_track_rows} 件あり、"
                "個別の group_id を新規採番しました。"
            )

        # --- 途切れたトラックの再接続ロジック ---
        RECONNECT_FRAME_GAP = 10  # フレーム以内なら再接続を試みる
        RECONNECT_DISTANCE_PX = 150  # ピクセル以内なら同一物体とみなす

        df_for_reconnect = pd.read_sql_query(
            """
            SELECT d.auto_id, d.frame_num, d.group_id,
                   d.x1, d.y1, d.x2, d.y2,
                   c.class_name
            FROM Detection d
            JOIN Class c ON d.class_id = c.class_id
            WHERE d.run_id = ? AND d.group_id IS NOT NULL AND LOWER(d.model_name) != 'best'
            ORDER BY d.frame_num
            """,
            conn,
            params=(run_id,),
        )

        if not df_for_reconnect.empty:
            df_for_reconnect['center_x'] = (df_for_reconnect['x1'] + df_for_reconnect['x2']) / 2
            df_for_reconnect['center_y'] = (df_for_reconnect['y1'] + df_for_reconnect['y2']) / 2
            df_for_reconnect['class_lower'] = df_for_reconnect['class_name'].str.lower()

            # グループごとの最終フレーム情報を取得
            group_last_frame: Dict[int, dict] = {}
            group_merge_map: Dict[int, int] = {}  # old_group_id -> new_group_id

            for _, row in df_for_reconnect.iterrows():
                gid = int(row['group_id'])
                frame = int(row['frame_num'])
                cx, cy = row['center_x'], row['center_y']
                cls = row['class_lower']

                # このグループの最終情報を更新
                if gid not in group_last_frame:
                    group_last_frame[gid] = {
                        'last_frame': frame,
                        'center_x': cx,
                        'center_y': cy,
                        'class': cls,
                    }
                else:
                    group_last_frame[gid]['last_frame'] = frame
                    group_last_frame[gid]['center_x'] = cx
                    group_last_frame[gid]['center_y'] = cy

            # 2回目のパス: 再接続候補を探す
            for _, row in df_for_reconnect.iterrows():
                gid = int(row['group_id'])
                frame = int(row['frame_num'])
                cx, cy = row['center_x'], row['center_y']
                cls = row['class_lower']

                # 現在のグループがマージ対象なら実際のグループIDを取得
                actual_gid = group_merge_map.get(gid, gid)

                # 他のグループの「最終フレーム」と比較
                for other_gid, info in group_last_frame.items():
                    if other_gid == actual_gid:
                        continue
                    actual_other_gid = group_merge_map.get(other_gid, other_gid)
                    if actual_other_gid == actual_gid:
                        continue

                    # クラスが一致するか
                    if info['class'] != cls:
                        continue

                    # フレーム差がしきい値以内か
                    frame_gap = frame - info['last_frame']
                    if frame_gap <= 0 or frame_gap > RECONNECT_FRAME_GAP:
                        continue

                    # 位置が近いか
                    dist = math.sqrt((cx - info['center_x'])**2 + (cy - info['center_y'])**2)
                    if dist > RECONNECT_DISTANCE_PX:
                        continue

                    # 再接続: 古いグループを新しいグループにマージ
                    # gid を other_gid にマージ
                    group_merge_map[gid] = actual_other_gid
                    break

            # マージマップを適用
            if group_merge_map:
                # 推移的なマージを解決
                def resolve_merge(gid: int) -> int:
                    visited = set()
                    while gid in group_merge_map and gid not in visited:
                        visited.add(gid)
                        gid = group_merge_map[gid]
                    return gid

                reconnect_updates: List[Tuple[int, int]] = []
                for _, row in df_for_reconnect.iterrows():
                    old_gid = int(row['group_id'])
                    new_gid = resolve_merge(old_gid)
                    if new_gid != old_gid:
                        reconnect_updates.append((new_gid, int(row['auto_id'])))

                if reconnect_updates:
                    c.executemany("UPDATE Detection SET group_id = ? WHERE auto_id = ?", reconnect_updates)
                    conn.commit()
                    merged_count = len(set(group_merge_map.keys()))
                    print(f"Run ID {run_id}: {merged_count} 個のグループを再接続（マージ）しました。")

        df_vehicles = pd.read_sql_query(
            """
            SELECT auto_id, frame_num, x1, y1, x2, y2, group_id
            FROM Detection
            WHERE run_id = ? AND group_id IS NOT NULL AND model_name != 'best'
            """,
            conn,
            params=(run_id,),
        )
        df_tires = pd.read_sql_query(
            """
            SELECT auto_id, frame_num, x1, y1, x2, y2
            FROM Detection
            WHERE run_id = ? AND LOWER(model_name) = 'best'
            """,
            conn,
            params=(run_id,),
        )

    if df_tires.empty:
        return time.time() - start_time

    vehicles_by_frame: Dict[int, List[dict]] = {
        int(frame): group.to_dict('records') for frame, group in df_vehicles.groupby('frame_num')
    }
    tires_by_frame: Dict[int, List[dict]] = {
        int(frame): group.to_dict('records') for frame, group in df_tires.groupby('frame_num')
    }
    frame_items: List[Tuple[int, List[dict]]] = list(tires_by_frame.items())

    def match_frame(item: Tuple[int, List[dict]]) -> List[Tuple[int, int]]:
        frame_num, tires = item
        vehicles_in_frame = vehicles_by_frame.get(frame_num)
        if not vehicles_in_frame:
            return []
        updates: List[Tuple[int, int]] = []
        for tire in tires:
            tire_center_x = (tire['x1'] + tire['x2']) / 2
            tire_center_y = (tire['y1'] + tire['y2']) / 2
            for vehicle in vehicles_in_frame:
                if (
                    vehicle['x1'] <= tire_center_x <= vehicle['x2']
                    and vehicle['y1'] <= tire_center_y <= vehicle['y2']
                ):
                    updates.append((vehicle['group_id'], tire['auto_id']))
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
