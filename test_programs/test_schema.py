import sqlite3

sql = """
            CREATE TABLE IF NOT EXISTS ManualOvertakeEvents (
                manual_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                frame_num INTEGER,
                video_time_s REAL,
                
                overtaker_group_id INTEGER,
                overtaker_track_id INTEGER,
                overtaker_class_name TEXT,
                overtaker_speed_km_h REAL,
                overtaker_pixel_speed REAL,
                overtaker_pixel_speed_frame REAL,
                
                overtaken_group_id INTEGER,
                overtaken_track_id INTEGER,
                overtaken_class_name TEXT,
                overtaken_speed_km_h REAL,
                overtaken_pixel_speed REAL,
                overtaken_pixel_speed_frame REAL,
                
                approach_distance_m REAL,
                approach_distance_px REAL,
                
                clearance_distance_m REAL,
                clearance_distance_cm REAL,
                clearance_distance_px REAL,
                clearance_distance_px_ratio REAL,
                
                overtaker_line_distance_m REAL,
                overtaker_line_distance_cm REAL,
                overtaker_line_distance_px REAL,
                overtaker_line_distance_px_ratio REAL,
                
                overtaken_line_distance_m REAL,
                overtaken_line_distance_cm REAL,
                overtaken_line_distance_px REAL,
                overtaken_line_distance_px_ratio REAL,
                
                overtaker_left_line_distance_m REAL,
                overtaker_left_line_distance_cm REAL,
                overtaker_left_line_distance_px REAL,
                
                overtaker_right_line_distance_m REAL,
                overtaker_right_line_distance_cm REAL,
                overtaker_right_line_distance_px REAL,
                
                overtaken_left_line_distance_m REAL,
                overtaken_left_line_distance_cm REAL,
                overtaken_left_line_distance_px REAL,
                
                overtaken_right_line_distance_m REAL,
                overtaken_right_line_distance_cm REAL,
                overtaken_right_line_distance_px REAL,
                
                overtaker_measure_x REAL,
                overtaker_measure_y REAL,
                overtaken_measure_x REAL,
                overtaken_measure_y REAL,
                
                overtaker_x1 REAL, overtaker_y1 REAL, overtaker_x2 REAL, overtaker_y2 REAL,
                overtaken_x1 REAL, overtaken_y1 REAL, overtaken_x2 REAL, overtaken_y2 REAL,
                
                lane_width_m REAL,
                lane_width_px_reference REAL,
                lane_width_cm_per_px REAL,
                
                context_frames TEXT, -- JSON storage for efficiency
                
                notes TEXT,
                created_at TEXT,
                updated_at TEXT,
                
                FOREIGN KEY(run_id) REFERENCES ProcessLog(run_id)
            )
"""
try:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ProcessLog (run_id INTEGER PRIMARY KEY)")
    conn.execute(sql)
    print("SUCCESS")
except Exception as e:
    print(f"FAILED: {e}")
    # print sql with line numbers
    for i, line in enumerate(sql.split('\n')):
        print(f"{i}: {line}")
