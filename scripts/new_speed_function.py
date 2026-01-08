def assign_kinematics(run_id: int):
    load_dotenv()
    ACCEL_THRESHOLD = float(os.getenv("ACCELERATION_THRESHOLD", 0.5))
    DECEL_THRESHOLD = float(os.getenv("DECELERATION_THRESHOLD", -0.5))

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        profile_sql = "SELECT calibration_profile FROM ProcessLog WHERE run_id = ?"
        result = conn.execute(profile_sql, (run_id,)).fetchone()
        if not result or not result[0]:
            raise ValueError(f"Run ID {run_id} にキャリブレーションプロファイルが適用されていません。")
        profile_name = result[0]

        fps_sql = "SELECT v.fps FROM Video v JOIN ProcessLog p ON v.video_id = p.video_id WHERE p.run_id = ?"
        fps_result = conn.execute(fps_sql, (run_id,)).fetchone()
        fps = fps_result[0] if fps_result and fps_result[0] else 30.0

        df = pd.read_sql_query(f"""
            SELECT auto_id, track_id, frame_num, x1, x2, y1, y2
            FROM Detection
            WHERE run_id = {run_id} AND track_id IS NOT NULL AND model_name != 'best'
            ORDER BY track_id, frame_num
        """, conn)

    if df.empty:
        return

    opt_folder = os.getenv("Opt_files", "output")
    json_path = os.path.join(opt_folder, "calibrations", f"{profile_name}.json")
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"キャリブレーションファイルが見つかりません: {json_path}")
    with open(json_path, 'r', encoding='utf-8') as f:
        calib_data = json.load(f)

    scale_meta = calib_data.get("scale", {}) or {}
    scale_mode = (scale_meta.get("mode") or 'vertical').lower()

    df['center_x'] = (df['x1'] + df['x2']) / 2
    df['center_y'] = (df['y1'] + df['y2']) / 2
    df['frame_diff'] = df.groupby('track_id')['frame_num'].diff()
    df['speed_km_h'] = 0.0
    df['speed_mps'] = 0.0
    df['speed_diff'] = 0.0
    df['time_diff_accel'] = 0.0
    df['acceleration_m_s2'] = 0.0
    df['travel_direction'] = 'N'
    df['scale_pixels_per_meter'] = np.nan
    df['y_delta'] = np.nan

    frame_window = max(int(round(fps)), 1)
    time_s = df['frame_diff'] / fps

    vertical_lines = sorted(scale_meta.get('lines', []), key=lambda pts: pts[0][1] if pts else 0)
    vertical_intervals = float(scale_meta.get('num_intervals') or 0)
    known_distance = float(scale_meta.get('known_distance_m') or 0)

    vertical_ready = False
    vertical_ppm_series = pd.Series(np.nan, index=df.index)
    vertical_y_delta = pd.Series(np.nan, index=df.index)
    vertical_range_min = None
    vertical_range_max = None

    if len(vertical_lines) > 1 and vertical_intervals > 0 and known_distance > 0:
        meter_per_interval = known_distance / vertical_intervals
        if meter_per_interval > 0:
            ppm_list = []
            for i in range(len(vertical_lines) - 1):
                try:
                    start_y = vertical_lines[i][0][1]
                    end_y = vertical_lines[i + 1][0][1]
                except (IndexError, TypeError):
                    start_y = end_y = None
                if start_y is None or end_y is None:
                    continue
                diff = abs(end_y - start_y)
                if diff > 0:
                    ppm_list.append(diff / meter_per_interval)
            if ppm_list:
                def get_local_scale(y_val: float):
                    for idx in range(len(vertical_lines) - 1):
                        start = vertical_lines[idx]
                        end = vertical_lines[idx + 1]
                        if not start or not end:
                            continue
                        y_start = start[0][1]
                        y_end = end[0][1]
                        if y_start <= y_val <= y_end or y_end <= y_val <= y_start:
                            return ppm_list[idx]
                    if y_val > vertical_lines[-1][0][1]:
                        return ppm_list[-1]
                    return ppm_list[0]

                vertical_ppm_series = df['center_y'].apply(get_local_scale)
                vertical_y_delta = df.groupby('track_id')['center_y'].diff()
                all_y = [pt[1] for line in vertical_lines for pt in line if isinstance(pt, (list, tuple)) and len(pt) == 2]
                if all_y:
                    vertical_range_min = min(all_y)
                    vertical_range_max = max(all_y)
                vertical_ready = True

    def set_accel_state(a: float) -> str:
        if a > ACCEL_THRESHOLD:
            return '加速'
        if a < DECEL_THRESHOLD:
            return '減速'
        return '巡航'

    def apply_vertical() -> bool:
        if not vertical_ready:
            return False
        df['scale_pixels_per_meter'] = vertical_ppm_series
        df['y_delta'] = vertical_y_delta
        df['travel_direction'] = np.where(df['y_delta'].fillna(0) < 0, 'R', 'L')
        distance_pixels = df['y_delta'].abs()
        valid = (time_s > 0) & df['scale_pixels_per_meter'].notna()
        df.loc[valid, 'speed_mps'] = (distance_pixels[valid] / df['scale_pixels_per_meter'][valid]) / time_s[valid]
        df['speed_km_h'] = df['speed_mps'] * 3.6
        df['speed_diff'] = df.groupby('track_id')['speed_mps'].diff(periods=frame_window)
        df['time_diff_accel'] = df.groupby('track_id')['frame_num'].diff(periods=frame_window) / fps
        valid_accel = df['time_diff_accel'] > 0
        df.loc[valid_accel, 'acceleration_m_s2'] = df['speed_diff'][valid_accel] / df['time_diff_accel'][valid_accel]
        return True

    def apply_xy() -> bool:
        path_meta = scale_meta.get('path') or {}
        path_points = _coerce_path_points(path_meta.get('points'))
        total_distance = float(path_meta.get('total_distance_m') or 0)
        if len(path_points) < 2 or total_distance <= 0:
            return False

        path_points = np.array(path_points, dtype=float)

        def cum_distance(points):
            dist = [0.0]
            for i in range(1, len(points)):
                dist.append(dist[-1] + float(np.linalg.norm(points[i] - points[i - 1])))
            return dist

        cumulative = cum_distance(path_points)
        pixels_per_meter = cumulative[-1] / total_distance if cumulative[-1] > 0 else None
        if not pixels_per_meter:
            return False

        def project(point):
            best = None
            best_dist = float('inf')
            for i in range(len(path_points) - 1):
                p1, p2 = path_points[i], path_points[i + 1]
                v = p2 - p1
                if np.allclose(v, 0):
                    continue
                t = np.clip(np.dot(point - p1, v) / np.dot(v, v), 0, 1)
                proj = p1 + t * v
                dist = np.linalg.norm(point - proj)
                if dist < best_dist:
                    best_dist = dist
                    best = cumulative[i] + float(np.linalg.norm(proj - p1))
            return best

        centers = df[['center_x', 'center_y']].to_numpy(dtype=float)
        path_positions = []
        for pt in centers:
            projected = project(pt)
            path_positions.append(projected if projected is not None else np.nan)
        df['path_position_m'] = np.array(path_positions, dtype=float) / pixels_per_meter
        df['path_position_diff'] = df.groupby('track_id')['path_position_m'].diff()
        valid = (time_s > 0) & df['path_position_diff'].notna()
        df.loc[valid, 'speed_mps'] = df['path_position_diff'][valid].abs() / time_s[valid]
        df['speed_km_h'] = df['speed_mps'] * 3.6
        df['travel_direction'] = np.where(df['path_position_diff'].fillna(0) >= 0, 'F', 'B')
        df['scale_pixels_per_meter'] = pixels_per_meter
        df['speed_diff'] = df.groupby('track_id')['speed_mps'].diff(periods=frame_window)
        df['time_diff_accel'] = df.groupby('track_id')['frame_num'].diff(periods=frame_window) / fps
        valid_accel = df['time_diff_accel'] > 0
        df.loc[valid_accel, 'acceleration_m_s2'] = df['speed_diff'][valid_accel] / df['time_diff_accel'][valid_accel]
        return True

    def apply_homography() -> bool:
        homography_info = scale_meta.get('homography') or {}
        points = _coerce_homography_points(homography_info.get('image_points'))
        width_m = float(homography_info.get('width_m') or 0)
        length_m = float(homography_info.get('length_m') or 0)
        if len(points) != 4 or width_m <= 0 or length_m <= 0:
            return False
        image_points = np.array(points, dtype=np.float32)
        world_points = np.array([[0, 0], [width_m, 0], [width_m, length_m], [0, length_m]], dtype=np.float32)
        H, status = cv2.findHomography(image_points, world_points, 0)
        if H is None:
            return False
        bottom_points = np.vstack([
            df['center_x'].to_numpy(dtype=np.float32),
            df['y2'].to_numpy(dtype=np.float32),
            np.ones(len(df), dtype=np.float32)
        ]).T
        mapped = bottom_points @ H.T
        denom = mapped[:, 2]
        world_x = np.full(len(df), np.nan, dtype=float)
        world_y = std::full(len(df);)
