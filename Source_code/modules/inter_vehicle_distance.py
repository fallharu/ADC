# 役割: 全ての車両ペア間の距離を計算し、前方最近傍情報を保存する
import sqlite3
import pandas as pd
import numpy as np
from itertools import combinations
from tqdm import tqdm
from .db_manager import MAIN_DB_PATH
from dotenv import load_dotenv
from .calibration_loader import load_calibration_json

def get_local_scale_from_calib(y, calib_data):
    scale_lines = sorted(calib_data.get("scale", {}).get("lines", []), key=lambda x: x[0][1])
    scale_meta = calib_data.get("scale", {})
    if len(scale_lines) < 2 or scale_meta.get("num_intervals", 0) <= 0: return None
    meter_per_interval = scale_meta.get("known_distance_m", 8.0) / scale_meta["num_intervals"]
    ppm_intervals = [abs(scale_lines[i+1][0][1] - scale_lines[i][0][1]) / meter_per_interval for i in range(len(scale_lines) - 1)]
    for i in range(len(scale_lines) - 1):
        if scale_lines[i][0][1] <= y <= scale_lines[i+1][0][1]: return ppm_intervals[i]
    return ppm_intervals[-1] if y > scale_lines[-1][0][1] else ppm_intervals[0]

def analyze_proximity(run_id: int):
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        profile_sql = "SELECT calibration_profile FROM ProcessLog WHERE run_id = ?"
        result = conn.execute(profile_sql, (run_id,)).fetchone()
        if not result or not result[0]: raise ValueError(f"Run ID {run_id} にキャリブレーション未適用")
        profile_name = result[0]
        
        # ★修正: auto_id, frame_num を使用
        df = pd.read_sql_query(f"SELECT auto_id, frame_num, group_id, class_name, x1, x2, y1, y2 FROM Detection d JOIN Class c ON d.class_id=c.class_id WHERE run_id = {run_id} AND group_id IS NOT NULL AND model_name != 'best'", conn)

    if df.empty or len(df['group_id'].unique()) < 2:
        print(f"Run ID {run_id}: 近接分析の対象車両が2台未満のためスキップします。")
        return

    load_dotenv()
    calib_data, _ = load_calibration_json(run_id, profile_name)
    
    df['center_x_px'] = (df['x1'] + df['x2']) / 2
    df['bottom_y_px'] = df['y2']

    df_grouped = df.groupby('frame_num')
    proximity_records = []
    front_vehicle_updates = []

    for frame_num, frame_df in tqdm(df_grouped, desc="車両間距離計算中"):
        if len(frame_df) < 2: continue
        
        for i, j in combinations(frame_df.index, 2):
            car_a, car_b = frame_df.loc[i], frame_df.loc[j]
            avg_y = (car_a['bottom_y_px'] + car_b['bottom_y_px']) / 2
            pixels_per_meter = get_local_scale_from_calib(avg_y, calib_data)
            if pixels_per_meter is None or pixels_per_meter == 0: continue
            direct_dist_px = np.linalg.norm([car_a.center_x_px - car_b.center_x_px, car_a.bottom_y_px - car_b.bottom_y_px])
            proximity_records.append((run_id, frame_num, car_a.group_id, car_b.group_id, car_a.class_name, car_b.class_name,
                                      direct_dist_px / pixels_per_meter, abs(car_a.center_x_px - car_b.center_x_px) / pixels_per_meter,
                                      abs(car_a.bottom_y_px - car_b.bottom_y_px) / pixels_per_meter))
        
        for _, car_a in frame_df.iterrows():
            min_lon_dist_m = float('inf')
            front_vehicle_id = None
            forward_cars = frame_df[(frame_df.group_id != car_a.group_id) & (frame_df.bottom_y_px < car_a.bottom_y_px)]
            if not forward_cars.empty:
                pixels_per_meter_a = get_local_scale_from_calib(car_a.bottom_y_px, calib_data)
                if pixels_per_meter_a and pixels_per_meter_a > 0:
                    lon_distances_m = abs(car_a.bottom_y_px - forward_cars.bottom_y_px) / pixels_per_meter_a
                    min_lon_dist_m = lon_distances_m.min()
                    front_vehicle_id = forward_cars.loc[lon_distances_m.idxmin()].group_id
            
            if front_vehicle_id is not None:
                # ★修正: auto_id を使用
                front_vehicle_updates.append((min_lon_dist_m, front_vehicle_id, car_a.auto_id))

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        c = conn.cursor()
        c.execute(f"DELETE FROM ProximityData WHERE run_id = {run_id}")
        if proximity_records: c.executemany("INSERT INTO ProximityData (run_id, frame_num, vehicle_a_id, vehicle_b_id, class_a, class_b, direct_distance_m, lateral_distance_m, longitudinal_distance_m) VALUES (?,?,?,?,?,?,?,?,?)", proximity_records)
        c.execute(f"UPDATE Detection SET front_distance_m = NULL, front_vehicle_id = NULL WHERE run_id = {run_id}")
        if front_vehicle_updates:
             # ★修正: auto_id を使用
            c.executemany("UPDATE Detection SET front_distance_m = ?, front_vehicle_id = ? WHERE auto_id = ?", front_vehicle_updates)
        print(f"Run ID {run_id}: 近接情報を更新しました。")