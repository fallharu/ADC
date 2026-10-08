
import sqlite3
import pandas as pd
import numpy as np
import io
import os
import re
from datetime import datetime
from .db_manager import MAIN_DB_PATH

def generate_kanaoka_excel(db_path: str = MAIN_DB_PATH) -> bytes:
    """Generate Excel bytes for Kanaoka Export"""
    df = _generate_kanaoka_df(db_path)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="Kanaoka_Output")
        
        # Auto-adjust column width
        worksheet = writer.sheets["Kanaoka_Output"]
        for column_cells in worksheet.columns:
            length = max(len(str(cell.value) or "") for cell in column_cells)
            worksheet.column_dimensions[column_cells[0].column_letter].width = min(length + 2, 50)
            
    return output.getvalue()

def generate_kanaoka_csv(db_path: str = MAIN_DB_PATH) -> bytes:
    """Generate CSV bytes for Kanaoka Export (UTF-8-SIG)"""
    df = _generate_kanaoka_df(db_path)
    # Return as bytes with UTF-8 BOM for Excel compatibility
    return df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')

def _generate_kanaoka_df(db_path: str) -> pd.DataFrame:
    """
    Kanaoka Data Generator (Shared Logic)
    Returns: pd.DataFrame
    """
    
    # Helper to extract year from filename
    def extract_year(filename):
        if not filename: return None
        # Pattern: YYYYMMDD or YYYY-MM-DD
        match = re.search(r'(20\d{2})', filename)
        if match:
            return match.group(1)
        return None

    def _calc_x_at_y(line, py):
        """Calculate X on the polyline at specific Y."""
        if not line or py is None: return None
        
        for i in range(len(line) - 1):
            try:
                x1, y1 = float(line[i][0]), float(line[i][1])
                x2, y2 = float(line[i+1][0]), float(line[i+1][1])
                
                y_min, y_max = min(y1, y2), max(y1, y2)
                if py < y_min or py > y_max: continue
                if y1 == y2: continue # Horizontal line
                
                # Intersect
                t = (py - y1) / (y2 - y1)
                x_cross = x1 + t * (x2 - x1)
                return x_cross
            except: continue
        return None
        
    # Helper for safe float conversion
    def _float_or_none(val):
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    with sqlite3.connect(db_path) as conn:
        # 1. Fetch Auto Overtake Events
        auto_events_df = pd.read_sql_query("""
            SELECT 
                'Auto' as source_type,
                o.rowid as event_id,
                o.run_id,
                o.event_frame_num as event_frame,
                o.overtaker_group_id,
                o.overtaken_group_id,
                o.overtaker_auto_id,
                o.overtaken_auto_id,
                p.process_end as created_at,
                v.filename as video_filename,
                v.fps,
                v.road_type,
                v.collection_year
            FROM OvertakeEvents o
            JOIN ProcessLog p ON o.run_id = p.run_id
            JOIN Video v ON p.video_id = v.video_id
        """, conn)

        # 2. Fetch Manual Overtake Events (if table exists)
        try:
            manual_events_df = pd.read_sql_query("""
                SELECT 
                    'Manual' as source_type,
                    m.manual_event_id as event_id,
                    m.run_id,
                    m.frame_num as event_frame,
                    m.overtaker_group_id,
                    m.overtaken_group_id,
                    m.overtaker_track_id as overtaker_auto_id,
                    m.overtaken_track_id as overtaken_auto_id,
                    m.created_at,
                    v.filename as video_filename,
                    v.fps,
                    v.road_type,
                    v.collection_year
                FROM ManualOvertakeEvents m
                JOIN ProcessLog p ON m.run_id = p.run_id
                JOIN Video v ON p.video_id = v.video_id
            """, conn)
            # Adjust Manual columns if necessary or merge
            all_events = pd.concat([auto_events_df, manual_events_df], ignore_index=True)
        except Exception:
            all_events = auto_events_df

    if all_events.empty:
        return pd.DataFrame()

    final_rows = []
    calibration_cache = {}

    def get_lane_lines(run_id_val):
        """Cache and retrieve lane lines and lane_width_m for a run."""
        if run_id_val in calibration_cache:
            return calibration_cache[run_id_val]
        
        try:
            with sqlite3.connect(db_path) as c_conn:
                row = c_conn.execute("SELECT calibration_profile FROM ProcessLog WHERE run_id = ?", (run_id_val,)).fetchone()
                profile = row[0] if row else None
            
            from .calibration_loader import load_calibration_json
            from .manual_metrics import load_white_lines, LANE_WIDTH_METERS
            
            calib, _ = load_calibration_json(run_id_val, profile)
            lane_lines = load_white_lines(calib)
            
            # Extract verified lane width
            width_m = LANE_WIDTH_METERS
            if calib:
                val = _float_or_none(calib.get("lane_width_m"))
                if val is not None and val > 0:
                    width_m = val
            
            # stored as (lane_lines_obj, lane_width_m)
            calibration_cache[run_id_val] = (lane_lines, width_m)
            return lane_lines, width_m
        except Exception as e:
            # print(f"Calibration load failed for Run {run_id_val}: {e}")
            calibration_cache[run_id_val] = (None, 3.5)
            return None, 3.5

    # Iterate over each event
    with sqlite3.connect(db_path) as conn:
        for idx, event in all_events.iterrows():
            run_id = event['run_id']
            overtaker_gid = event['overtaker_group_id']
            overtaken_gid = event['overtaken_group_id']
            try:
                overtaker_gid = int(overtaker_gid)
                overtaken_gid = int(overtaken_gid)
                run_id = int(run_id)
            except:
                continue

            # Load lines for this run
            lane_lines, lane_width_m = get_lane_lines(run_id)
            left_line = lane_lines.left if lane_lines else None
            right_line = lane_lines.right if lane_lines else None

            # Fetch Detections
            det_query = """
                SELECT 
                    d.frame_num,
                    d.group_id,
                    c.class_name,
                    d.speed_km_h,
                    d.x1, d.y1, d.x2, d.y2,
                    d.l_line_distance_m,
                    d.r_line_distance_m,
                    d.line_distance_m,
                    d.line_distance,
                    d.travel_direction,
                    d.clearance_distance_m,
                    d.approach_distance_m,
                    d.l_line_cross_m,
                    d.r_line_cross_m
                FROM Detection d
                LEFT JOIN Class c ON d.class_id = c.class_id
                WHERE d.run_id = ? 
                  AND d.group_id IN (?, ?)
                ORDER BY d.frame_num
            """
            detections = pd.read_sql_query(det_query, conn, params=(run_id, overtaker_gid, overtaken_gid))

            if detections.empty:
                continue
            
            frames = detections['frame_num'].unique()
            frames.sort()
            
            fps = float(event['fps']) if event['fps'] else 30.0
            
            ot_det = detections[detections['group_id'] == overtaker_gid]
            # Filter overtaker for cars (exclude ghosts)
            ot_det = ot_det[ot_det['class_name'].astype(str).str.lower().isin(['car', 'bus', 'truck'])]
            # Remove duplicates if any remain
            ot_det = ot_det.drop_duplicates(subset=['frame_num'])
            ot_det = ot_det.set_index('frame_num')
            
            on_det = detections[detections['group_id'] == overtaken_gid]
            # Filter overtaken for bikes (exclude ghosts)
            on_det = on_det[on_det['class_name'].astype(str).str.lower().isin(['bicycle', 'bike', 'cyclist'])]
            # Remove duplicates if any remain
            on_det = on_det.drop_duplicates(subset=['frame_num'])
            on_det = on_det.set_index('frame_num')
            
            def calc_pixel_speed_series(df_grp):
                if df_grp.empty: return pd.Series(dtype=float)
                # measure_x/y removed from DB query, calculate directly
                mx = (df_grp['x1'] + df_grp['x2']) / 2
                my = df_grp['y2']
                dx = mx.diff()
                dy = my.diff()
                dist = np.sqrt(dx**2 + dy**2)
                return dist * fps

            ot_px_speed = calc_pixel_speed_series(ot_det)
            on_px_speed = calc_pixel_speed_series(on_det)

            # Measurement Year (Prioritize DB, fallback to Filename)
            measurement_year = event.get('collection_year')
            if not measurement_year or pd.isna(measurement_year):
                measurement_year = extract_year(event['video_filename'])

            # Build rows
            for frame in frames:
                frame_val = int(frame)
                video_time_s = frame_val / fps
                
                row = {
                    "ID": event['event_id'],
                    "Run": f"Run{event['run_id']}",
                    "測定年度": measurement_year,
                    "道路種別": event.get('road_type') or '',
                    "動画名": event['video_filename'],
                    "フレーム": frame_val,
                    "動画時間(s)": round(video_time_s, 2),
                    "登録日時": event['created_at'],
                    "メモ": f"{event['source_type']} Event: {event['overtaker_group_id']} vs {event['overtaken_group_id']}"
                }
                
                def _process_entity(rec, prefix):
                    row[f"{prefix}Group"] = int(rec['group_id'])
                    row[f"{prefix}クラス"] = rec['class_name']
                    row[f"{prefix}時速(km/h)"] = round(rec['speed_km_h'], 2) if pd.notnull(rec['speed_km_h']) else None
                    # Keep legacy column or remove? User asked for new columns.
                    # row[f"{prefix} 白線距離(m)"] = round(rec['line_distance_m'], 2) if pd.notnull(rec['line_distance_m']) else None
                    
                    # Direction
                    direction = str(rec['travel_direction']).strip() if pd.notnull(rec['travel_direction']) else 'B'
                    
                    # Scale (m/px) - User Reqeust: Use VERIFIED lane_width_m
                    scale_m_per_px = 0.05 
                    if pd.notnull(rec.get('line_distance')) and rec['line_distance'] > 0:
                        # Use verified lane_width_m / pixel width
                        scale_m_per_px = lane_width_m / rec['line_distance']
                    elif pd.notnull(rec.get('line_distance_m')) and pd.notnull(rec.get('line_distance')) and rec['line_distance'] > 0:
                        # Fallback to DB value logic
                        scale_m_per_px = rec['line_distance_m'] / rec['line_distance']
                    
                    # --- Center/White logic using database crossing columns ---
                    l_cross = rec.get('l_line_cross_m')
                    r_cross = rec.get('r_line_cross_m')
                    
                    if direction == 'F':
                        # F: Left=White, Right=Center
                        white_cross_m = l_cross
                        center_cross_m = r_cross
                    else:
                        # B: Left=Center, Right=White
                        center_cross_m = l_cross
                        white_cross_m = r_cross
                    
                    # Filtering based on class (User Request: White=Bike only, Center=Car only)
                    class_name_lower = str(rec.get('class_name', '')).lower()
                    is_bike = any(x in class_name_lower for x in ['bicycle', 'bike', 'cyclist'])
                    
                    if not is_bike:
                        # Cars/Others: Suppress White Line Crossing
                        white_cross_m = None
                    else:
                        # Bikes: Suppress Center Line Crossing
                        center_cross_m = None

                    # For distances, we still have the existing columns in Det table
                    # but kanaoka_export calculates them or uses them.
                    # Looking at Step 97, kanaoka_export had a lot of code for distances.
                    # I will keep the column mapping but use the DB values where possible.
                    # Actually, kanaoka_export was using it's own calculation for "dist_m" 
                    # based on scale_m_per_px. 
                    # To minimize change impact, I'll just replace the crossing logic.
                    
                    # White distance mapping (positive values in Det table)
                    if direction == 'F':
                        white_dist_m = rec.get('l_line_distance_m')
                        center_dist_m = rec.get('r_line_distance_m')
                    else:
                        center_dist_m = rec.get('l_line_distance_m')
                        white_dist_m = rec.get('l_line_distance_m') # WAIT, B line: Left=Center, Right=White. So White=R.
                        white_dist_m = rec.get('r_line_distance_m')

                    # Measurement coordinates
                    meas_y = float(rec['measure_y']) if pd.notnull(rec.get('measure_y')) else float(rec['y2'])
                    white_meas_x = None
                    center_meas_x = None
                    
                    x1 = float(rec['x1']) if pd.notnull(rec['x1']) else None
                    x2 = float(rec['x2']) if pd.notnull(rec['x2']) else None
                    
                    if x1 is not None and x2 is not None:
                        if direction == 'F':
                            white_meas_x = x1
                            center_meas_x = x2
                        else:
                            center_meas_x = x1
                            white_meas_x = x2

                    # Store Calculated Columns
                    row[f"{prefix}中央線距離(m)"] = round(center_dist_m, 2) if center_dist_m is not None else None
                    row[f"{prefix}中央線越え(m)"] = round(center_cross_m, 2) if center_cross_m is not None else None
                    row[f"{prefix}白線距離(m)"] = round(white_dist_m, 2) if white_dist_m is not None else None
                    row[f"{prefix}白線越え(m)"] = round(white_cross_m, 2) if white_cross_m is not None else None
                    
                    # Measurement Points
                    row[f"{prefix}測定点Y(px)"] = round(meas_y, 1) if meas_y is not None else None
                    row[f"{prefix}白線測定点X(px)"] = round(white_meas_x, 1) if white_meas_x is not None else None
                    row[f"{prefix}中央線測定点X(px)"] = round(center_meas_x, 1) if center_meas_x is not None else None

                ot_frame_rec = ot_det.loc[frame] if frame in ot_det.index else None
                on_frame_rec = on_det.loc[frame] if frame in on_det.index else None
                
                # Check duplicates in index (rare but possible in Detection table glitches)
                if ot_frame_rec is not None and getattr(ot_frame_rec, "ndim", 0) > 1: 
                    ot_frame_rec = ot_frame_rec.iloc[0]
                if on_frame_rec is not None and getattr(on_frame_rec, "ndim", 0) > 1: 
                    on_frame_rec = on_frame_rec.iloc[0]

                if ot_frame_rec is not None:
                    _process_entity(ot_frame_rec, "追い越し側")
                    px_s = ot_px_speed.get(frame_val)
                    if getattr(px_s, "ndim", 0) > 0: px_s = px_s.iloc[0] # Handle duplicate index
                    row["追い越し側ピクセル速度(px/s)"] = round(px_s, 1) if pd.notnull(px_s) else None
                else:
                    # Fill blanks for overtaker
                    for k in ["追い越し側Group", "追い越し側クラス", "追い越し側中央線距離(m)", "追い越し側中央線越え(m)", "追い越し側白線距離(m)", "追い越し側白線越え(m)",
                              "追い越し側測定点Y(px)", "追い越し側白線測定点X(px)", "追い越し側中央線測定点X(px)", "追い越し側ピクセル速度(px/s)"]:
                         row[k] = None

                if on_frame_rec is not None:
                    _process_entity(on_frame_rec, "追い越され側")
                    px_s = on_px_speed.get(frame_val)
                    if getattr(px_s, "ndim", 0) > 0: px_s = px_s.iloc[0] # Handle duplicate index
                    row["追い越され側ピクセル速度(px/s)"] = round(px_s, 1) if pd.notnull(px_s) else None
                else:
                    # Fill blanks for overtaken
                    for k in ["追い越され側Group", "追い越され側クラス", "追い越され側中央線距離(m)", "追い越され側中央線越え(m)", "追い越され側白線距離(m)", "追い越され側白線越え(m)",
                              "追い越され側測定点Y(px)", "追い越され側白線測定点X(px)", "追い越され側中央線測定点X(px)", "追い越され側ピクセル速度(px/s)"]:
                        row[k] = None

                # Clearance/Approach
                c_clearance_m = None
                c_approach_m = None
                
                if (frame in ot_det.index) and (frame in on_det.index):
                     # Already fetched above as ot_frame_rec / on_frame_rec
                     # But need to be sure they are not None
                     if ot_frame_rec is not None and on_frame_rec is not None:
                         # Calculate Scale from Overtaken entity (closest to camera/stable)
                         scale_val = 0.05
                         # Ensure on_frame_rec is Series
                         if getattr(on_frame_rec, "ndim", 0) > 1: on_frame_rec = on_frame_rec.iloc[0]

                         if pd.notnull(on_frame_rec.get('line_distance_m')) and pd.notnull(on_frame_rec.get('line_distance')) and on_frame_rec['line_distance'] > 0:
                             scale_val = on_frame_rec['line_distance_m'] / on_frame_rec['line_distance']
                         
                         # User Request: Clearance IS Approach Distance
                         # Use Approach Distance from Overtaker record (they should be identical or close)
                         # Ensure ot_frame_rec is Series
                         if getattr(ot_frame_rec, "ndim", 0) > 1: ot_frame_rec = ot_frame_rec.iloc[0]
                         
                         db_approach = ot_frame_rec.get('approach_distance_m')
                         if pd.notnull(db_approach):
                             c_clearance_m = db_approach
                             c_approach_m = db_approach
                
                row["離隔距離(m)"] = round(c_clearance_m, 2) if c_clearance_m is not None else None
                row["離隔距離(cm)"] = round(c_clearance_m * 100, 0) if c_clearance_m is not None else None
                row["接近距離(m)"] = round(c_approach_m, 2) if c_approach_m is not None else None
                
                final_rows.append(row)

    # Convert to DataFrame
    export_df = pd.DataFrame(final_rows)
    
    # Reorder columns
    desired_columns = [
        "ID", "Run", "測定年度", "道路種別", "動画名", "フレーム", "動画時間(s)", 
        "追い越し側Group", "追い越し側クラス", "追い越し側時速(km/h)", "追い越し側ピクセル速度(px/s)",
        "追い越し側中央線距離(m)", "追い越し側中央線越え(m)", "追い越し側中央線測定点X(px)",
        "追い越し側白線距離(m)", "追い越し側白線越え(m)", "追い越し側白線測定点X(px)",
        "追い越し側測定点Y(px)",
        "追い越され側Group", "追い越され側クラス", "追い越され側時速(km/h)", "追い越され側ピクセル速度(px/s)",
        "追い越され側中央線距離(m)", "追い越され側中央線越え(m)", "追い越され側中央線測定点X(px)",
        "追い越され側白線距離(m)", "追い越され側白線越え(m)", "追い越され側白線測定点X(px)",
        "追い越され側測定点Y(px)",
        "接近距離(m)", "離隔距離(cm)", "離隔距離(m)", 
        "登録日時", "メモ"
    ]
    
    # Ensure all columns exist
    for col in desired_columns:
        if col not in export_df.columns:
            export_df[col] = None
            
    export_df = export_df[desired_columns]
    return export_df
