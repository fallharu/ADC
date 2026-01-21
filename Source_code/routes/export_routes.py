from flask import Blueprint, jsonify, request, send_file, render_template
import pandas as pd
import io
import json
import os
from pathlib import Path
import sqlite3

from ..modules.db_manager import get_db_connection, MAIN_DB_PATH
from . import main

def ensure_calibration_dir():
    opt_files = os.getenv("Opt_files", "./output")
    opt_files = opt_files.strip('"').strip("'")
    calib_dir = os.path.join(opt_files, 'calibrations')
    os.makedirs(calib_dir, exist_ok=True)
    return calib_dir

def get_calibration_data(profile_name):
    if not profile_name:
        return None
    calib_dir = ensure_calibration_dir()
    path = os.path.join(calib_dir, f"{profile_name}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return None

@main.route("/api/export/overtake_tracks")
def export_overtake_tracks():
    """
    Export all track data for groups involved in overtake events.
    (ADC_08 Version)
    """
    try:
        # 1. Get all overtake events
        # Note: ADC_08 OvertakeEvents uses group_id
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query_events = """
                SELECT 
                    e.overtake_event_id as event_id, 
                    e.run_id, 
                    e.event_frame_num,
                    e.overtaker_group_id, 
                    e.overtaken_group_id,
                    p.output_folder,
                    p.calibration_profile,
                    v.filename as video_filename,
                    v.collection_year,
                    v.road_type
                FROM OvertakeEvents e
                LEFT JOIN ProcessLog p ON e.run_id = p.run_id
                LEFT JOIN Video v ON p.video_id = v.video_id
            """
            events = cursor.execute(query_events).fetchall()
            
            if not events:
                return "No overtake events found", 404

            all_rows = []

            # 2. Process each event
            for event in events:
                run_id = event['run_id']
                ot_gid = event['overtaker_group_id']
                on_gid = event['overtaken_group_id']
                
                # 3. Fetch all frames for these groups from Detection table
                # ADC_08 uses Detection table with group_id column
                # Join with ClassMaster to get class_name
                query_tracks = """
                    SELECT d.*, c.class_name 
                    FROM Detection d
                    LEFT JOIN ClassMaster c ON d.class_id = c.class_id
                    WHERE d.run_id = ? AND d.group_id IN (?, ?)
                    ORDER BY d.frame_num ASC
                """
                tracks = cursor.execute(query_tracks, [run_id, ot_gid, on_gid]).fetchall()
                
                for trk in tracks:
                    group_id = trk['group_id']
                    
                    # Determine Role
                    if group_id == ot_gid:
                        role = "Overtaking" # 追い越し
                        partner_id = on_gid
                    else:
                        role = "Overtaken" # 追い越され
                        partner_id = ot_gid
                    
                    # Use existing metrics in DB if available
                    dist_l_m = trk['l_line_distance_m'] if 'l_line_distance_m' in trk.keys() else trk['distance_m'] # fallback?
                    dist_r_m = trk['r_line_distance_m'] if 'r_line_distance_m' in trk.keys() else None
                    line_dist_m = trk['line_distance_m'] 
                    
                    # Row Data
                    offset_frame = None
                    try:
                        offset_frame = int(trk['frame_num']) - int(event['event_frame_num'])
                    except (TypeError, ValueError):
                        offset_frame = None
                    row = {
                        "イベントID": event['event_id'],
                        "Run": run_id,
                        "動画名": event['video_filename'],
                        "動画フレーム": trk['frame_num'],
                        "オフセットフレーム": offset_frame,
                        "役割": role,
                        "Group ID": group_id,
                        "相手Group": partner_id,
                        "トラックID": trk['track_id'],
                        "クラス": trk['class_name'],
                        "BBOX x1": trk['x1'] if 'x1' in trk.keys() else None,
                        "BBOX y1": trk['y1'] if 'y1' in trk.keys() else None,
                        "BBOX x2": trk['x2'] if 'x2' in trk.keys() else None,
                        "BBOX y2": trk['y2'] if 'y2' in trk.keys() else None,
                        # Metrics found in DB
                        "白線距離(m)": line_dist_m,
                        "左白線距離(m)": dist_l_m,
                        "右白線距離(m)": dist_r_m,
                        "離隔距離(m)": trk['clearance_distance_m'] if 'clearance_distance_m' in trk.keys() else None,
                        "速度(km/h)": trk['speed_km_h'],
                        "加速度(m/s2)": trk['acceleration_m_s2'] if 'acceleration_m_s2' in trk.keys() else None
                    }
                    all_rows.append(row)

        # 4. Convert to DF & Export
        if not all_rows:
             return "No track data found for events", 404

        df = pd.DataFrame(all_rows)
        
        # --- Save to Server Disk (New) ---
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        export_dir = os.path.abspath("output/exports")
        os.makedirs(export_dir, exist_ok=True)
        filename = f"overtake_tracks_adc08_{timestamp}.csv"
        save_path = os.path.join(export_dir, filename)
        
        df.to_csv(save_path, index=False, encoding='utf-8-sig')
        print(f"\n==============================================", flush=True)
        print(f"📊 追い越し軌跡データを保存しました: {save_path}", flush=True)
        print(f"==============================================\n", flush=True)
        
        return send_file(
            save_path,
            mimetype='text/csv',
            as_attachment=True,
            download_name='overtake_tracks_export.csv'
        )

    except Exception as e:
        print(f"Export Error: {e}")
        return jsonify({"error": str(e)}), 500

@main.route("/export_page")
def export_page():
    return render_template("export_page.html")
