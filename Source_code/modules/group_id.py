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
