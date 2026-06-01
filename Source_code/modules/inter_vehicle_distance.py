# 役割: 全ての車両ペア間の距離を計算し、前方最近傍情報を保存する
import sqlite3
import pandas as pd
import numpy as np
from itertools import combinations
from tqdm import tqdm
from .db_manager import MAIN_DB_PATH, configure_connection
from dotenv import load_dotenv
from .calibration_loader import load_calibration_json
from .manual_metrics import LANE_WIDTH_METERS, lane_scale_at_point, load_white_lines

def get_local_scale_from_calib(y, calib_data):
    scale_meta = calib_data.get("scale", {})
    scale_lines = sorted(
        scale_meta.get("y_axis_lines") or scale_meta.get("lines") or [],
        key=lambda x: x[0][1],
    )
    scale_meta = calib_data.get("scale", {})
    if len(scale_lines) < 2 or scale_meta.get("num_intervals", 0) <= 0: return None
    meter_per_interval = scale_meta.get("known_distance_m", 8.0) / scale_meta["num_intervals"]
    ppm_intervals = [abs(scale_lines[i+1][0][1] - scale_lines[i][0][1]) / meter_per_interval for i in range(len(scale_lines) - 1)]
    for i in range(len(scale_lines) - 1):
        start_y = scale_lines[i][0][1]
        end_y = scale_lines[i+1][0][1]
        if min(start_y, end_y) <= y <= max(start_y, end_y):
            return ppm_intervals[i]
    return None


def _float_or_none(value):
    try:
        if value is None:
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric):
        return None
    return numeric


def _mean_positive(values):
    valid = [value for value in (_float_or_none(v) for v in values) if value and value > 0]
    return float(np.mean(valid)) if valid else None

def analyze_proximity(run_id: int):
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="read")
        profile_sql = "SELECT calibration_profile FROM ProcessLog WHERE run_id = ?"
        result = conn.execute(profile_sql, (run_id,)).fetchone()
        if not result or not result[0]: raise ValueError(f"Run ID {run_id} にキャリブレーション未適用")
        profile_name = result[0]
        
        df = pd.read_sql_query(
            """
            SELECT
                d.auto_id,
                d.frame_num,
                d.group_id,
                COALESCE(c.class_name, d.class_name) AS class_name,
                d.x1,
                d.x2,
                d.y1,
                d.y2,
                d.x_pixels_per_meter,
                d.scale_pixels_per_meter,
                d.travel_direction
            FROM Detection d
            LEFT JOIN ClassMaster c ON d.class_id = c.class_id
            WHERE d.run_id = ?
              AND d.group_id IS NOT NULL
              AND d.model_name != 'best'
            """,
            conn,
            params=(run_id,),
        )

    if df.empty or len(df['group_id'].unique()) < 2:
        print(f"Run ID {run_id}: 近接分析の対象車両が2台未満のためスキップします。")
        return

    load_dotenv()
    calib_data, _ = load_calibration_json(run_id, profile_name)
    lane_lines = load_white_lines(calib_data)
    lane_width_m = _float_or_none(calib_data.get("lane_width_m"))
    if lane_width_m is None:
        lane_width_m = _float_or_none(calib_data.get("scale", {}).get("lane_width_m"))
    lane_width_m = lane_width_m or LANE_WIDTH_METERS
    
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
            avg_x = (car_a['center_x_px'] + car_b['center_x_px']) / 2
            y_pixels_per_meter = get_local_scale_from_calib(avg_y, calib_data)
            x_pixels_per_meter = lane_scale_at_point(
                avg_x,
                avg_y,
                lane_lines.left,
                lane_lines.right,
                lane_lines.center,
                lane_lines.left_inner,
                lane_lines.right_inner,
                lane_width_m=lane_width_m,
            )
            if not x_pixels_per_meter:
                x_pixels_per_meter = _mean_positive((car_a.get('x_pixels_per_meter'), car_b.get('x_pixels_per_meter')))
            dx_px = abs(car_a.center_x_px - car_b.center_x_px)
            dy_px = abs(car_a.bottom_y_px - car_b.bottom_y_px)
            lateral_m = dx_px / x_pixels_per_meter if x_pixels_per_meter and x_pixels_per_meter > 0 else None
            longitudinal_m = dy_px / y_pixels_per_meter if y_pixels_per_meter and y_pixels_per_meter > 0 else None
            if lateral_m is not None and longitudinal_m is not None:
                direct_distance_m = float(np.hypot(lateral_m, longitudinal_m))
            elif lateral_m is not None:
                direct_distance_m = lateral_m
            elif longitudinal_m is not None:
                direct_distance_m = longitudinal_m
            else:
                continue
            proximity_records.append((run_id, frame_num, car_a.group_id, car_b.group_id, car_a.class_name, car_b.class_name,
                                      direct_distance_m, lateral_m, longitudinal_m))
        
        for _, car_a in frame_df.iterrows():
            min_lon_dist_m = float('inf')
            front_vehicle_id = None
            direction = str(car_a.get('travel_direction') or '').upper()
            if direction == 'B':
                forward_cars = frame_df[(frame_df.group_id != car_a.group_id) & (frame_df.bottom_y_px > car_a.bottom_y_px)]
            else:
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
        configure_connection(conn, mode="write")
        c = conn.cursor()
        c.execute("DELETE FROM ProximityData WHERE run_id = ?", (run_id,))
        if proximity_records: c.executemany("INSERT INTO ProximityData (run_id, frame_num, vehicle_a_id, vehicle_b_id, class_a, class_b, direct_distance_m, lateral_distance_m, longitudinal_distance_m) VALUES (?,?,?,?,?,?,?,?,?)", proximity_records)
        c.execute("UPDATE Detection SET front_distance_m = NULL, front_vehicle_id = NULL WHERE run_id = ?", (run_id,))
        if front_vehicle_updates:
            c.executemany("UPDATE Detection SET front_distance_m = ?, front_vehicle_id = ? WHERE auto_id = ?", front_vehicle_updates)
        print(f"Run ID {run_id}: 近接情報を更新しました。")
