# 役割: TTC（衝突余裕時間）を計算する
import sqlite3
import pandas as pd
from tqdm import tqdm
from .db_manager import MAIN_DB_PATH, configure_connection

def assign_ttc(run_id: int):
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="read")
        df = pd.read_sql_query("""
            SELECT auto_id, frame_num, group_id, speed_km_h, front_distance_m, front_vehicle_id
            FROM Detection 
            WHERE run_id = ? AND group_id IS NOT NULL AND speed_km_h IS NOT NULL
        """, conn, params=(run_id,))

    if df.empty:
        print(f"Run ID {run_id}: TTC計算の対象データがありません。")
        return

    speed_map = df.set_index(['frame_num', 'group_id'])['speed_km_h'].to_dict()
    candidate_df = df[df['front_vehicle_id'].notna()]
    updates = []

    for _, row in tqdm(candidate_df.iterrows(), total=len(candidate_df), desc="TTC計算中"):
        speed_a_mps = row['speed_km_h'] / 3.6
        speed_b = speed_map.get((row['frame_num'], row['front_vehicle_id']))
        if pd.isna(speed_b):
            continue
        speed_b_mps = speed_b / 3.6
        
        relative_speed_mps = speed_a_mps - speed_b_mps

        if relative_speed_mps > 0.1:
            if pd.notna(row['front_distance_m']):
                ttc = row['front_distance_m'] / relative_speed_mps
                updates.append((ttc, row['auto_id']))

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="write")
        conn.execute("UPDATE Detection SET ttc_s = NULL WHERE run_id = ?", (run_id,))
        if updates:
            conn.executemany("UPDATE Detection SET ttc_s = ? WHERE auto_id = ?", updates)
    print(f"Run ID {run_id}: {len(updates)} 件のTTCを計算しました。")
