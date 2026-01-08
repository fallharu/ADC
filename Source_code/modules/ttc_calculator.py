# 役割: TTC（衝突余裕時間）を計算する
import sqlite3
import pandas as pd
from tqdm import tqdm
from .db_manager import MAIN_DB_PATH

def assign_ttc(run_id: int):
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        # ★修正: auto_id, frame_num, front_vehicle_id を使用
        df = pd.read_sql_query(f"""
            SELECT auto_id, group_id, speed_km_h, front_distance_m, front_vehicle_id
            FROM Detection 
            WHERE run_id = {run_id} AND group_id IS NOT NULL AND speed_km_h IS NOT NULL AND front_vehicle_id IS NOT NULL
        """, conn)

    if df.empty:
        print(f"Run ID {run_id}: TTC計算の対象データがありません。")
        return

    # group_idをキーにした速度辞書を作成
    speed_map = df.set_index('group_id')['speed_km_h'].to_dict()
    updates = []

    for _, row in tqdm(df.iterrows(), total=len(df), desc="TTC計算中"):
        # 自身の速度
        speed_a_mps = row['speed_km_h'] / 3.6
        # 前方車両の速度を取得
        speed_b_mps = speed_map.get(row['front_vehicle_id'], 0) / 3.6
        
        relative_speed_mps = speed_a_mps - speed_b_mps

        # 接近している場合のみ（相対速度が正）TTCを計算
        if relative_speed_mps > 0.1: # わずかな速度差は無視
            # front_distance_m を使用
            if pd.notna(row['front_distance_m']):
                ttc = row['front_distance_m'] / relative_speed_mps
                updates.append((ttc, row['auto_id']))

    if updates:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            # 既存のTTCデータを一旦クリア
            conn.execute(f"UPDATE Detection SET ttc_s = NULL WHERE run_id = {run_id}")
            # ★修正: auto_id を使用
            conn.executemany("UPDATE Detection SET ttc_s = ? WHERE auto_id = ?", updates)
            print(f"Run ID {run_id}: {len(updates)} 件のTTCを計算しました。")