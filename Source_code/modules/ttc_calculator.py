# 役割: TTC（衝突余裕時間）を計算する
import sqlite3
from contextlib import closing

import pandas as pd
from tqdm import tqdm
from .db_manager import MAIN_DB_PATH, configure_connection


def _int_or_none(value):
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if len(raw) in (1, 2, 4, 8):
            return int.from_bytes(raw, byteorder="little", signed=True)
        try:
            return int(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def assign_ttc(run_id: int):
    with closing(sqlite3.connect(MAIN_DB_PATH)) as conn:
        configure_connection(conn, mode="read")
        df = pd.read_sql_query("""
            SELECT auto_id, frame_num, group_id, speed_km_h, front_distance_m, front_vehicle_id
            FROM Detection 
            WHERE run_id = ? AND group_id IS NOT NULL AND speed_km_h IS NOT NULL
        """, conn, params=(run_id,))

    if df.empty:
        print(f"Run ID {run_id}: TTC計算の対象データがありません。")
        return

    df['frame_key'] = df['frame_num'].apply(_int_or_none)
    df['group_key'] = df['group_id'].apply(_int_or_none)
    df['front_vehicle_key'] = df['front_vehicle_id'].apply(_int_or_none)
    speed_map = (
        df[df['frame_key'].notna() & df['group_key'].notna()]
        .set_index(['frame_key', 'group_key'])['speed_km_h']
        .to_dict()
    )
    candidate_df = df[df['front_vehicle_key'].notna()]
    updates = []

    for _, row in tqdm(candidate_df.iterrows(), total=len(candidate_df), desc="TTC計算中"):
        speed_a_mps = row['speed_km_h'] / 3.6
        speed_b = speed_map.get((row['frame_key'], row['front_vehicle_key']))
        if pd.isna(speed_b):
            continue
        speed_b_mps = speed_b / 3.6
        
        relative_speed_mps = speed_a_mps - speed_b_mps

        if relative_speed_mps > 0.1:
            if pd.notna(row['front_distance_m']):
                ttc = row['front_distance_m'] / relative_speed_mps
                auto_id = _int_or_none(row['auto_id'])
                if auto_id is not None:
                    updates.append((float(ttc), auto_id))

    with closing(sqlite3.connect(MAIN_DB_PATH)) as conn:
        configure_connection(conn, mode="write")
        conn.execute("UPDATE Detection SET ttc_s = NULL WHERE run_id = ?", (run_id,))
        if updates:
            conn.executemany("UPDATE Detection SET ttc_s = ? WHERE auto_id = ?", updates)
        conn.commit()
    print(f"Run ID {run_id}: {len(updates)} 件のTTCを計算しました。")
