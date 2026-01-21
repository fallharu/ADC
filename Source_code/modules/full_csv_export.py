import pandas as pd
import sqlite3
import numpy as np
import io
import json

def generate_full_csv(db_path: str) -> bytes:
    """
    Generate a full CSV export of all overtake events with detailed per-frame metrics.
    Columns: 56 Japanese headers as requested.
    """
    with sqlite3.connect(db_path) as conn:
        # 1. Fetch Overtake Events + Video/Process info
        # Using rowid as event_id for safety (as discovered in kanaoka_export fixes)
        events_query = """
            SELECT 
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
            ORDER BY o.run_id, o.event_frame_num
        """
        events_df = pd.read_sql_query(events_query, conn)
        
        if events_df.empty:
            return b"" # Or separate header-only CSV

        all_rows = []
        
        # Prepare header list
        headers = [
            "イベントID", "Run", "動画名", "オフセットフレーム", "動画フレーム", "動画時間(s)",
            "追い越し側Group", "追い越し側トラックID", "追い越し側検出ID", "追い越し側クラス",
            "追い越し側BBOX x1", "追い越し側BBOX y1", "追い越し側BBOX x2", "追い越し側BBOX y2",
            "追い越し側時速(km/h)", "追い越し側ピクセル速度(px/s)", "追い越し側ピクセル移動量(px/f)",
            "追い越し側測定X(px)", "追い越し側測定Y(px)",
            "追い越し側 白線距離(m)", "追い越し側 白線距離(cm)", "追い越し側 白線距離(px)",
            "追い越し側 左白線距離(m)", "追い越し側 左白線距離(cm)", "追い越し側 左白線距離(px)",
            "追い越し側 右白線距離(m)", "追い越し側 右白線距離(cm)", "追い越し側 右白線距離(px)",
            "追い越され側Group", "追い越され側トラックID", "追い越され側検出ID", "追い越され側クラス",
            "追い越され側BBOX x1", "追い越され側BBOX y1", "追い越され側BBOX x2", "追い越され側BBOX y2",
            "追い越され側時速(km/h)", "追い越され側ピクセル速度(px/s)", "追い越され側ピクセル移動量(px/f)",
            "追い越され側測定X(px)", "追い越され側測定Y(px)",
            "追い越され側 白線距離(m)", "追い越され側 白線距離(cm)", "追い越され側 白線距離(px)",
            "追い越され側 左白線距離(m)", "追い越され側 左白線距離(cm)", "追い越され側 左白線距離(px)",
            "追い越され側 右白線距離(m)", "追い越され側 右白線距離(cm)", "追い越され側 右白線距離(px)",
            "離隔距離(m)", "離隔距離(cm)", "離隔距離(px)",
            "追い越し側 中央線越え", "追い越し側 白線越え", 
            "追い越され側 中央線越え", "追い越され側 白線越え",
            "追い越し側 中央線越え", "追い越し側 白線越え",
            "追い越され側 中央線越え", "追い越され側 白線越え",
            "採取年度", "道種"
        ]

        # Cache detections per run to minimize queries if needed, but per-event query is safer for now
        # Actually per-event query might be slow. Optimization: Fetch needed runs' detections.
        # But let's stick to per-event logic for correctness first unless thousands of events.
        
        for _, event in events_df.iterrows():
            run_id = event['run_id']
            overtaker_gid = event['overtaker_group_id']
            overtaken_gid = event['overtaken_group_id']
            event_frame = event['event_frame']
            fps = float(event['fps']) if event['fps'] else 30.0
            
            # Fetch Detections for this pair
            det_query = """
                SELECT 
                    d.frame_num,
                    d.group_id,
                    d.track_id, 
                    d.auto_id,
                    c.class_name,
                    d.speed_km_h,
                    d.x1, d.y1, d.x2, d.y2,
                    d.l_line_distance_m, d.r_line_distance_m,
                    d.line_distance_m, d.line_distance,
                    d.travel_direction,
                    d.l_line_cross_m, d.r_line_cross_m,
                    d.clearance_distance_m, d.approach_distance_m,
                    d.lane_position_flag,
                    d.confidence -- just in case
                FROM Detection d
                LEFT JOIN Class c ON d.class_id = c.class_id
                WHERE d.run_id = ? 
                  AND d.group_id IN (?, ?)
                ORDER BY d.frame_num
            """
            detections = pd.read_sql_query(det_query, conn, params=(run_id, overtaker_gid, overtaken_gid))
            
            if detections.empty:
                continue
                
            frames = sorted(detections['frame_num'].unique())
            
            ot_det = detections[detections['group_id'] == overtaker_gid].set_index('frame_num')
            on_det = detections[detections['group_id'] == overtaken_gid].set_index('frame_num')
            
            # Helper for speed/pos
            def get_metrics(df_map, f):
                if f not in df_map.index:
                    return None
                rec = df_map.loc[f]
                if isinstance(rec, pd.DataFrame): rec = rec.iloc[0]
                return rec

            # Helper for pre-calc series
            def calc_motion(df_grp):
                if df_grp.empty: return {}, {}, {}, {}
                mx_series = (df_grp['x1'] + df_grp['x2']) / 2
                my_series = df_grp['y2']
                
                dx = mx_series.diff()
                dy = my_series.diff()
                dist_px = np.sqrt(dx**2 + dy**2)
                speed_px_s = dist_px * fps
                
                # Turn to dicts
                return mx_series.to_dict(), my_series.to_dict(), speed_px_s.to_dict(), dist_px.to_dict()

            ot_metrics = calc_motion(detections[detections['group_id'] == overtaker_gid].set_index('frame_num'))
            on_metrics = calc_motion(detections[detections['group_id'] == overtaken_gid].set_index('frame_num')) 
            
            # Iterate Frames
            for f in frames:
                # Need both? The user said "All data", implying overlap frames.
                # Usually we care about interaction. 
                # Let's output row if EITHER exists, but metrics are cleaner if overlap.
                # Logic: If overtaker exists or overtaken exists, logging the frame.
                
                ot_rec = ot_det.loc[f] if f in ot_det.index else None
                if isinstance(ot_rec, pd.DataFrame): ot_rec = ot_rec.iloc[0]
                
                on_rec = on_det.loc[f] if f in on_det.index else None
                if isinstance(on_rec, pd.DataFrame): on_rec = on_rec.iloc[0]
                
                # Common Data
                offset_frame = f - event_frame
                video_time_s = f / fps
                
                # --- Interaction ---
                # Clearance from DB record (usually on Overtaker or Overtaken row)
                # Check both
                clearance_m = None
                if ot_rec is not None and ot_rec.get('clearance_distance_m'):
                    clearance_m = ot_rec.get('clearance_distance_m')
                elif on_rec is not None and on_rec.get('clearance_distance_m'):
                     clearance_m = on_rec.get('clearance_distance_m')
                
                # Filter: Only rows with valid clearance distance
                if clearance_m is None:
                    continue

                clearance_cm = clearance_m * 100 if clearance_m else None
                clearance_px = None # calc if needed
                
                # Crossing Flags (Logic based on line distance)
                ot_center_cross = None
                ot_white_cross = None
                on_center_cross = None
                on_white_cross = None
                
                # Overtaker Crossing
                if ot_rec is not None:
                    rd = ot_rec.get('r_line_distance_m')
                    ld = ot_rec.get('l_line_distance_m')
                    if rd is not None and rd < 0: ot_center_cross = abs(rd)
                    if ld is not None and ld < 0: ot_white_cross = abs(ld)
                
                # Overtaken Crossing
                if on_rec is not None:
                    rd = on_rec.get('r_line_distance_m')
                    ld = on_rec.get('l_line_distance_m')
                    if rd is not None and rd < 0: on_center_cross = abs(rd)
                    if ld is not None and ld < 0: on_white_cross = abs(ld)

                row = [
                    event['event_id'], 
                    run_id, 
                    event['video_filename'], 
                    offset_frame, 
                    f, 
                    video_time_s
                ]
                
                # --- Overtaker Columns ---
                if ot_rec is not None:
                     mx = ot_metrics[0].get(f)
                     my = ot_metrics[1].get(f)
                     px_spd = ot_metrics[2].get(f)
                     px_mov = ot_metrics[3].get(f)
                     
                     row.extend([
                         overtaker_gid,
                         ot_rec.get('track_id'),
                         ot_rec.get('auto_id'),
                         ot_rec.get('class_name'),
                         ot_rec.get('x1'), ot_rec.get('y1'), ot_rec.get('x2'), ot_rec.get('y2'),
                         ot_rec.get('speed_km_h'),
                         px_spd, # px/s
                         px_mov, # px/f
                         mx, my,
                         ot_rec.get('line_distance_m'),
                         ot_rec.get('line_distance') * 100 if ot_rec.get('line_distance') else None, # cm approx
                         ot_rec.get('line_distance'), # px (from DB column 'line_distance')
                         ot_rec.get('l_line_distance_m'),
                         None, # l_cm
                         None, # l_px
                         ot_rec.get('r_line_distance_m'),
                         None, # r_cm
                         None  # r_px
                     ])
                else:
                    row.extend([None] * 22) # 22 spacer columns
                    
                # --- Overtaken Columns ---
                if on_rec is not None:
                     mx = on_metrics[0].get(f)
                     my = on_metrics[1].get(f)
                     px_spd = on_metrics[2].get(f)
                     px_mov = on_metrics[3].get(f)
                     
                     row.extend([
                         overtaken_gid,
                         on_rec.get('track_id'),
                         on_rec.get('auto_id'),
                         on_rec.get('class_name'),
                         on_rec.get('x1'), on_rec.get('y1'), on_rec.get('x2'), on_rec.get('y2'),
                         on_rec.get('speed_km_h'),
                         px_spd,
                         px_mov,
                         mx, my,
                         on_rec.get('line_distance_m'),
                         on_rec.get('line_distance') * 100 if on_rec.get('line_distance') else None,
                         on_rec.get('line_distance'),
                         on_rec.get('l_line_distance_m'),
                         None,
                         None,
                         on_rec.get('r_line_distance_m'),
                         None,
                         None
                     ])
                else:
                    row.extend([None] * 22)

                # --- Interaction ---
                # Clearance from DB record (usually on Overtaker or Overtaken row)
                # Check both
                clearance_m = None
                if ot_rec is not None and ot_rec.get('clearance_distance_m'):
                    clearance_m = ot_rec.get('clearance_distance_m')
                elif on_rec is not None and on_rec.get('clearance_distance_m'):
                     clearance_m = on_rec.get('clearance_distance_m')
                
                # Filter: Only rows with valid clearance distance
                if clearance_m is None:
                    continue

                clearance_cm = clearance_m * 100 if clearance_m else None
                clearance_px = None # calc if needed
                
                # Crossing Flags using DB columns
                ot_center_cross = None
                ot_white_cross = None
                on_center_cross = None
                on_white_cross = None
                
                if ot_rec is not None:
                    dir_ot = str(ot_rec.get('travel_direction', '')).strip().upper()
                    l_c = ot_rec.get('l_line_cross_m')
                    r_c = ot_rec.get('r_line_cross_m')
                    if dir_ot == 'F':
                        ot_white_cross = l_c
                        ot_center_cross = r_c
                    else:
                        ot_center_cross = l_c
                        ot_white_cross = r_c

                if on_rec is not None:
                    dir_on = str(on_rec.get('travel_direction', '')).strip().upper()
                    l_c = on_rec.get('l_line_cross_m')
                    r_c = on_rec.get('r_line_cross_m')
                    if dir_on == 'F':
                        on_white_cross = l_c
                        on_center_cross = r_c
                    else:
                        on_center_cross = l_c
                        on_white_cross = r_c

                def to_presence_flag(value):
                    if value is None:
                        return "なし"
                    try:
                        return "あり" if float(value) > 0 else "なし"
                    except (TypeError, ValueError):
                        return "なし"

                row.extend([
                    clearance_m,
                    clearance_cm,
                    clearance_px,
                    ot_center_cross,
                    ot_white_cross,
                    on_center_cross,
                    on_white_cross,
                    to_presence_flag(ot_center_cross),
                    to_presence_flag(ot_white_cross),
                    to_presence_flag(on_center_cross),
                    to_presence_flag(on_white_cross),
                    event['collection_year'],
                    event['road_type']
                ])
                
                all_rows.append(row)
                
    # Create DataFrame
    out_df = pd.DataFrame(all_rows, columns=headers)
    
    # Export CSV string
    # Using utf-8-sig for Excel compatibility in Japan/Global
    csv_buffer = io.BytesIO()
    out_df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
    return csv_buffer.getvalue()
