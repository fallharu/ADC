# 役割: 進行方向、各種スケール、速度、加速度など、車両の運動に関する情報を計算する
import sqlite3
import pandas as pd
import numpy as np
import os
from tqdm import tqdm
from .db_manager import MAIN_DB_PATH, configure_connection
from .measure_points import attach_measure_points, compute_front_right_tire_points
from dotenv import load_dotenv
from .calibration_loader import load_calibration_json

def assign_kinematics(run_id: int):
    """
    進行方向、使用スケール、速度、加速度を計算し、DBに保存する。
    """
    # --- 1. 設定とデータの読み込み ---
    load_dotenv()
    REF_WIDTH_M = float(os.getenv("REFERENCE_VEHICLE_WIDTH_M", 1.8))
    ACCEL_THRESHOLD = float(os.getenv("ACCELERATION_THRESHOLD", 0.5))
    DECEL_THRESHOLD = float(os.getenv("DECELERATION_THRESHOLD", -0.5))

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="read")
        profile_sql = "SELECT calibration_profile FROM ProcessLog WHERE run_id = ?"
        result = conn.execute(profile_sql, (run_id,)).fetchone()
        if not result or not result[0]: raise ValueError(f"Run ID {run_id} にキャリブレーションプロファイルが適用されていません。")
        profile_name = result[0]
        
        fps_sql = "SELECT v.fps FROM Video v JOIN ProcessLog p ON v.video_id = p.video_id WHERE p.run_id = ?"
        fps_result = conn.execute(fps_sql, (run_id,)).fetchone()
        fps = fps_result[0] if fps_result and fps_result[0] else 30.0

        df = pd.read_sql_query("""
            SELECT auto_id, track_id, frame_num, group_id, x1, x2, y1, y2, model_name, travel_direction
            FROM Detection
            WHERE run_id = ? AND track_id IS NOT NULL
            ORDER BY track_id, frame_num
        """, conn, params=(run_id,))

    if df.empty:
        print(f"Run ID {run_id}: 運動学情報の計算対象データがありません。")
        return

    calib_data, _ = load_calibration_json(run_id, profile_name)
    left_line = None
    right_line = None
    if isinstance(calib_data, dict):
        lines = calib_data.get("lines")
        if isinstance(lines, dict):
            left_candidate = lines.get("left_white_line")
            right_candidate = lines.get("right_white_line")
            if isinstance(left_candidate, (list, tuple)):
                left_line = left_candidate
            if isinstance(right_candidate, (list, tuple)):
                right_line = right_candidate

    # --- 2. Y軸スケール（前後方向）の計算 ---
    scale_meta = calib_data.get("scale", {})
    raw_lines = scale_meta.get("y_axis_lines") or []
    y_scale_positions = []
    for raw_line in raw_lines:
        points = []
        if isinstance(raw_line, dict):
            for key in ("points", "coords", "coordinates"):
                if key in raw_line:
                    raw_line = raw_line[key]
                    break
            else:
                raw_line = raw_line.values()
        if not isinstance(raw_line, (list, tuple)):
            try:
                raw_line = list(raw_line)
            except TypeError:
                continue
        if not raw_line:
            continue
        first_point = raw_line[0]
        if isinstance(first_point, dict):
            y_value = first_point.get("y")
        elif isinstance(first_point, (list, tuple)) and len(first_point) >= 2:
            y_value = first_point[1]
        else:
            continue
        try:
            y_scale_positions.append(float(y_value))
        except (TypeError, ValueError):
            continue

    y_scale_positions.sort()
    y_ppm_intervals = []
    num_intervals = scale_meta.get("num_intervals", 0) or 0
    known_distance = scale_meta.get("known_distance_m", 0) or 0
    if (
        len(y_scale_positions) > 1
        and num_intervals > 0
        and known_distance
    ):
        meter_per_interval = known_distance / num_intervals if num_intervals else 0
        if meter_per_interval:
            for i in range(len(y_scale_positions) - 1):
                diff = abs(y_scale_positions[i + 1] - y_scale_positions[i])
                if diff:
                    y_ppm_intervals.append(diff / meter_per_interval)

    def get_y_scale(y):
        if not y_scale_positions or not y_ppm_intervals:
            return None
        for i in range(len(y_scale_positions) - 1):
            low = y_scale_positions[i]
            high = y_scale_positions[i + 1]
            if min(low, high) <= y <= max(low, high):
                return y_ppm_intervals[i]
        return None
    
    tyre_points = compute_front_right_tire_points(
        df[df['model_name'] == 'best'],
        left_line,
        right_line,
    )
    vehicles = df[df['model_name'] != 'best'].copy()
    if vehicles.empty:
        print(f"Run ID {run_id}: 車両データが見つかりませんでした。")
        return
    vehicles = attach_measure_points(
        vehicles,
        tyre_points,
        left_line=left_line,
        right_line=right_line,
    )

    y1_vals = vehicles['y1'].to_numpy(np.float64)
    y2_vals = vehicles['y2'].to_numpy(np.float64)
    fallback_measure_y = np.where(np.isfinite(y2_vals), y2_vals, (y1_vals + y2_vals) * 0.5)
    vehicles['measure_y'] = vehicles['measure_y'].astype(float)
    vehicles['measure_y'] = np.where(
        np.isfinite(vehicles['measure_y']),
        vehicles['measure_y'],
        fallback_measure_y,
    )

    vehicles['scale_pixels_per_meter'] = pd.to_numeric(vehicles['measure_y'].apply(get_y_scale), errors='coerce')

    # --- 3. X軸スケール（横方向）の計算 ---
    vehicles['x_pixels_per_meter'] = np.nan
    pixel_width = vehicles['x2'] - vehicles['x1']
    vehicles['x_pixels_per_meter'] = pixel_width / REF_WIDTH_M

    # --- 4. 進行方向、速度、加速度の計算 ---
    # group_idが欠損している場合はtrack_idで補完
    vehicles['group_id'] = vehicles['group_id'].fillna(vehicles['track_id'])

    # 時間順に並べ替え (Group単位で正しい始点・終点を判定するため)
    vehicles.sort_values(['group_id', 'frame_num'], inplace=True)

    # 進行方向をグループごとに統一して決定 (始点と終点のY座標差分)
    # 上(小) -> 下(大) = 正 = Front ('F')
    # 下(大) -> 上(小) = 負 = Back ('B')
    
    # 各グループの最初と最後のmeasure_yを取得
    grp_start_y = vehicles.groupby('group_id')['measure_y'].transform('first')
    grp_end_y = vehicles.groupby('group_id')['measure_y'].transform('last')
    
    # 全体差分
    vehicles['group_y_diff'] = grp_end_y - grp_start_y
    
    # 差分が正（Yが増加＝上から下）なら 'B' (Backward/Downward), 負（Yが減少＝下から上）なら 'F' (Forward/Upward)
    vehicles['travel_direction'] = np.where(vehicles['group_y_diff'] >= 0, 'B', 'F')

    # 瞬時速度計算用にはフレーム間差分を使用 (Track単位)
    # Note: グループ+時間でソート済みなので、Track内も時間順になっている
    vehicles['y_diff_speed'] = vehicles.groupby('track_id')['measure_y'].diff()
    vehicles['frame_diff'] = vehicles.groupby('track_id')['frame_num'].diff()
    vehicles['y_diff_speed'] = vehicles['y_diff_speed'].fillna(0)
    vehicles['frame_diff'] = vehicles['frame_diff'].fillna(0)

    distance_m = vehicles['y_diff_speed'].abs() / vehicles['scale_pixels_per_meter']
    time_s = vehicles['frame_diff'] / fps
    pixel_distance = vehicles['y_diff_speed'].abs()

    vehicles['speed_km_h'] = 0.0
    valid_indices = (time_s > 0) & (vehicles['scale_pixels_per_meter'].notna())
    vehicles.loc[valid_indices, 'speed_km_h'] = (distance_m[valid_indices] / time_s[valid_indices]) * 3.6

    vehicles['pixel_speed'] = 0.0
    positive_time = time_s > 0
    vehicles.loc[positive_time, 'pixel_speed'] = pixel_distance[positive_time] / time_s[positive_time]

    frame_window = int(fps)
    vehicles['speed_mps'] = vehicles['speed_km_h'] / 3.6
    vehicles['speed_diff'] = vehicles.groupby('track_id')['speed_mps'].diff(periods=frame_window)
    vehicles['time_diff_accel'] = vehicles.groupby('track_id')['frame_num'].diff(periods=frame_window) / fps
    vehicles['acceleration_m_s2'] = 0.0
    valid_accel_indices = vehicles['time_diff_accel'] > 0
    vehicles.loc[valid_accel_indices, 'acceleration_m_s2'] = vehicles['speed_diff'][valid_accel_indices] / vehicles['time_diff_accel'][valid_accel_indices]

    def set_accel_state(a):
        if a > ACCEL_THRESHOLD: return '加速'
        if a < DECEL_THRESHOLD: return '減速'
        return '等速'
    vehicles['acceleration_state'] = vehicles['acceleration_m_s2'].apply(set_accel_state)

    # --- 5. DB更新 ---
    # ★★★ バイトデータとして保存される問題を防ぐため、ここで型を明示的に変換 ★★★
    updates = []
    for _, row in vehicles.iterrows():
        updates.append((
            str(row['travel_direction']) if pd.notna(row['travel_direction']) else None,
            float(row['scale_pixels_per_meter']) if pd.notna(row['scale_pixels_per_meter']) else None,
            float(row['x_pixels_per_meter']) if pd.notna(row['x_pixels_per_meter']) else None,
            float(row['pixel_speed']) if pd.notna(row['pixel_speed']) else None,
            float(row['speed_km_h']),
            float(row['acceleration_m_s2']),
            str(row['acceleration_state']) if pd.notna(row['acceleration_state']) else None,
            int(row['auto_id'])
        ))

    if updates:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            configure_connection(conn, mode="write")
            conn.executemany(
                """
                UPDATE Detection
                SET travel_direction=?, scale_pixels_per_meter=?, x_pixels_per_meter=?,
                    pixel_speed=?, speed_km_h=?, acceleration_m_s2=?, acceleration_state=?
                WHERE auto_id=?
                """,
                updates,
            )
        print(f"Run ID {run_id}: 運動学情報を更新しました。")
