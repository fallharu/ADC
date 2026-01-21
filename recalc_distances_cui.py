
import sys
import os
import sqlite3
import json
import pandas as pd
import numpy as np
from datetime import datetime

# プロジェクトルートをsys.pathに追加
sys.path.append(os.getcwd())

from Source_code.modules.db_manager import MAIN_DB_PATH
from Source_code.modules.calibration_loader import load_calibration_json
from Source_code.modules.measure_points import compute_front_right_tire_points, _horizontal_distance_to_line
from Source_code.modules.lane_distance import _build_lane_polygon, _classify_lane_flag

TARGET_CSV_PATH = r"C:\Users\kurok\Downloads\G_ADC\ADC_08\uploads\manual_overtake_context_20251110_164013.csv"

def get_db_connection():
    return sqlite3.connect(MAIN_DB_PATH)

def fetch_directions(conn, run_id):
    """Runのすべての検出方向を取得し、(frame, group) -> direction にマッピングする。"""
    try:
        query = "SELECT frame_num, group_id, travel_direction FROM Detection WHERE run_id = ?"
        df = pd.read_sql_query(query, conn, params=(run_id,))
        # 辞書を作成: (frame, group) -> direction
        return dict(zip(zip(df['frame_num'], df['group_id']), df['travel_direction']))
    except Exception as e:
        print(f"  Error fetching directions for run {run_id}: {e}")
        return {}

def fetch_lane_lines_from_db(conn, run_id):
    """キャリブレーションjsonが見つからない場合のフォールバック"""
    query = "SELECT x1, y1, x2, y2, type FROM LaneLines WHERE run_id = ?"
    df = pd.read_sql_query(query, conn, params=(run_id,))
    left_lines = []
    right_lines = []
    for _, row in df.iterrows():
        line = [[row['x1'], row['y1']], [row['x2'], row['y2']]]
        if row['type'] == 'left':
            left_lines.append(line)
        elif row['type'] == 'right':
            right_lines.append(line)
    return left_lines, right_lines

def get_run_id_by_filename(conn, filename):
    """指定された動画ファイル名の最新のrun_idを検索する。"""
    # CSVにパスが含まれている場合は削除する（通常はファイル名のみ）
    filename = os.path.basename(filename)
    
    # ProcessLog (runs) は video_id を介して Video にリンクしている
    query = """
        SELECT p.run_id 
        FROM ProcessLog p
        JOIN Video v ON p.video_id = v.video_id
        WHERE v.filename = ? 
        ORDER BY p.run_id DESC 
        LIMIT 1
    """
    cursor = conn.cursor()
    cursor.execute(query, (filename,))
    row = cursor.fetchone()
    if row:
        return row[0]
    return None

def calculate_distance(row, direction_map, calibration_data, lane_polygon, scale_m_per_px):
    # IDの抽出
    frame = row['動画フレーム']
    
    overtaker_grp = row.get('追い越し側Group')
    overtaken_grp = row.get('追い越され側Group')
    
    # BBoxの取得
    ot_x1 = row.get('追い越し側BBOX x1')
    ot_y1 = row.get('追い越し側BBOX y1')
    ot_x2 = row.get('追い越し側BBOX x2')
    ot_y2 = row.get('追い越し側BBOX y2')
    
    on_x1 = row.get('追い越され側BBOX x1')
    on_y1 = row.get('追い越され側BBOX y1')
    on_x2 = row.get('追い越され側BBOX x2')
    on_y2 = row.get('追い越され側BBOX y2')
    
    if pd.isna(ot_x1) or pd.isna(on_x1):
        return None, None, None, None, None 
    
    ot_bbox = {'x1': ot_x1, 'y1': ot_y1, 'x2': ot_x2, 'y2': ot_y2}
    on_bbox = {'x1': on_x1, 'y1': on_y1, 'x2': on_x2, 'y2': on_y2}

    # 方向のフォールバック
    # ot_dir = direction_map.get((frame, overtaker_grp), "Left") 
    
    scale = scale_m_per_px if scale_m_per_px else 0.005
    
    # 単純なBBox水平距離（離隔）を計算
    # 自転車が左（Xが小さい）、車が右（Xが大きい）の場合: Clearance = Car.x1 - Bike.x2
    clearance_px = 0
    if on_x2 < ot_x1: 
        clearance_px = ot_x1 - on_x2
    elif ot_x2 < on_x1: 
        clearance_px = on_x1 - ot_x2
    else:
        clearance_px = 0 # 重なり
        
    clearance_m_recalc = clearance_px * scale
    
    # 白線距離
    line_dist_m = None
    right_line_dist_m = None
    right_line_dist_px = None
    
    lane_marks = calibration_data.get('lane_marks')
    lines_data = calibration_data.get('lines')
    
    # 左白線の解決
    target_left = None
    if calibration_data.get('db_left_line'): 
        target_left = calibration_data['db_left_line']
    elif lane_marks and isinstance(lane_marks, dict) and 'left' in lane_marks: 
        target_left = lane_marks['left']
    elif lines_data and isinstance(lines_data, dict) and 'left_white_line' in lines_data: 
        target_left = lines_data['left_white_line']
    
    # 右白線の解決
    target_right = None
    if calibration_data.get('db_right_line'): 
        target_right = calibration_data['db_right_line']
    elif lane_marks and isinstance(lane_marks, dict) and 'right' in lane_marks: 
        target_right = lane_marks['right']
    elif lines_data and isinstance(lines_data, dict) and 'right_white_line' in lines_data: 
        target_right = lines_data['right_white_line']
    
    # ラインX計算用のヘルパー
    def get_line_x(line_points, y):
        if not line_points or len(line_points) < 1: return None
        # フォーマットチェック
        is_segments = (len(line_points) > 0 and isinstance(line_points[0], list) and len(line_points[0]) > 0 and isinstance(line_points[0][0], list))
        
        lx = None
        # 追い越し側のBBoxの下部中央を、ライン交差の基準Yとして使用する
        y_center = ot_y2 # 接地点としてのBBox下部を想定
        
        if is_segments:
             for seg in line_points:
                 p1, p2 = seg[0], seg[1]
                 if (p1[1] <= y_center <= p2[1]) or (p2[1] <= y_center <= p1[1]):
                     dy = p2[1] - p1[1]
                     if dy != 0:
                         t = (y_center - p1[1]) / dy
                         lx = p1[0] + t * (p2[0] - p1[0])
                     break
        else:
             # ポリライン
             # Yでソート
             pts = sorted(line_points, key=lambda p: p[1])
             for i in range(len(pts)-1):
                 p1, p2 = pts[i], pts[i+1]
                 if (p1[1] <= y_center <= p2[1]) or (p2[1] <= y_center <= p1[1]):
                     dy = p2[1] - p1[1]
                     if dy != 0:
                         t = (y_center - p1[1]) / dy
                         lx = p1[0] + t * (p2[0] - p1[0])
                     break
        return lx

    # 左白線の距離計算
    if target_left:
        lx_at_y = get_line_x(target_left, ot_y2) # BBox下部を使用
        if lx_at_y is not None:
            dist_px = ot_x1 - lx_at_y # 左端 - ラインX（レーン内側/ライン右側なら正）
            line_dist_m = dist_px * scale
            
    # 右白線の距離計算
    if target_right:
        rx_at_y = get_line_x(target_right, ot_y2) # BBox下部を使用
        if rx_at_y is not None:
            # 右端 vs ラインX
            # ラインが1300、車右端が1200の場合: Dist = 1300 - 1200 = 100（内側なら正）
            right_dist_raw_px = rx_at_y - ot_x2
            right_line_dist_px = right_dist_raw_px
            right_line_dist_m = right_dist_raw_px * scale

    return clearance_m_recalc, line_dist_m, clearance_px, right_line_dist_m, right_line_dist_px

def main():
    if not os.path.exists(TARGET_CSV_PATH):
        print(f"File not found: {TARGET_CSV_PATH}")
        return

    print(f"Reading CSV: {TARGET_CSV_PATH}")
    try:
        df = pd.read_csv(TARGET_CSV_PATH)
    except Exception as e:
        print(f"Failed to read CSV: {e}")
        return

    print("Connecting to DB...")
    conn = get_db_connection()
    
    if '動画名' not in df.columns:
        print("Error: Column '動画名' (Video Name) not found in CSV.")
        return
    
    # '動画名'でグループ化
    grouped = df.groupby('動画名')
    
    # 統計リストの集計
    all_clearance_m = []
    all_left_line_dist_m = []
    all_right_line_dist_m = []
    video_count = 0
    
    for video_name, group_df in grouped:
        video_name_cleaned = str(video_name).strip()
        print(f"Processing Video: {video_name_cleaned} ({len(group_df)} rows)...")
        
        # 1. DBからRun IDを解決
        run_id = get_run_id_by_filename(conn, video_name_cleaned)
        
        if run_id is None:
            print(f"  Warning: No Run ID found for video '{video_name_cleaned}' in DB. Skipping.")
            continue
            
        print(f"  Matched Run ID: {run_id}")
        video_count += 1
        
        # 2. 方向の取得（オプションのコンテキスト）
        direction_map = fetch_directions(conn, run_id)
        
        # 3. キャリブレーションのロード
        calib_data = {}
        scale = 0.005208 
        calib_data = {}
        try:
            # video_name（ベース名と推定）はすでに持っている
            calib_data, path = load_calibration_json(run_id, None)
            
            extracted_scale = None
            if 'scale' in calib_data:
                extracted_scale = calib_data['scale']
            elif 'parameters' in calib_data and 'scale_m_per_px' in calib_data['parameters']:
                extracted_scale = calib_data['parameters']['scale_m_per_px']
            
            if isinstance(extracted_scale, (int, float)):
                scale = float(extracted_scale)
            
        except FileNotFoundError:
            print(f"  Warning: No calibration found for Run {run_id}, utilizing defaults.")
            scale = 1.0 / 192.0 
        
        print(f"  Scale: {scale:.6f} m/px")

        
        # 4. 行の処理
        for idx, row in group_df.iterrows():
            c_m, l_m, c_px, r_m, r_px = calculate_distance(row, direction_map, calib_data, None, scale)
            
            # 離隔距離指標の更新
            if c_m is not None:
                all_clearance_m.append(c_m)
                if '離隔距離(m)' in df.columns: df.at[idx, '離隔距離(m)'] = round(c_m, 4)
                if '離隔距離(cm)' in df.columns: df.at[idx, '離隔距離(cm)'] = round(c_m * 100, 2)
                if '離隔距離(px)' in df.columns: df.at[idx, '離隔距離(px)'] = round(c_px, 1)
                
            # 左白線指標の更新
            if l_m is not None:
                all_left_line_dist_m.append(abs(l_m))
                if '追い越し側 左白線距離(m)' in df.columns:
                    df.at[idx, '追い越し側 左白線距離(m)'] = round(l_m, 4)
                    df.at[idx, '追い越し側 左白線距離(cm)'] = round(l_m * 100, 2)
                    df.at[idx, '追い越し側 左白線距離(px)'] = round(l_m / scale, 1)
            
            # 右白線指標の更新
            if r_m is not None:
                all_right_line_dist_m.append(abs(r_m))
                if '追い越し側 右白線距離(m)' in df.columns:
                    df.at[idx, '追い越し側 右白線距離(m)'] = round(r_m, 4)
                    df.at[idx, '追い越し側 右白線距離(cm)'] = round(r_m * 100, 2)
                    df.at[idx, '追い越し側 右白線距離(px)'] = round(r_px, 1)

            # 一般的な「白線距離」（通常は左側、追い越し側）の更新
            if l_m is not None and '追い越し側 白線距離(m)' in df.columns:
                 df.at[idx, '追い越し側 白線距離(m)'] = round(abs(l_m), 4)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"manual_overtake_recalc_{timestamp}.csv"
    print(f"Saving to {output_path}...")
    df.to_csv(output_path, index=False, encoding='utf-8-sig') 
    
    print("-" * 40)
    print("RECALCULATION REPORT")
    print("-" * 40)
    print(f"Saved CSV Path: {os.path.abspath(output_path)}")
    print(f"Processed Videos: {video_count}")
    
    def print_stats(name, data):
        if data:
            s = pd.Series(data)
            print(f"\n[{name}] (m)")
            print(f"  Max:    {s.max():.4f}")
            print(f"  Mean:   {s.mean():.4f}")
            print(f"  Median: {s.median():.4f}")
        else:
            print(f"\n[{name}] No data.")

    print_stats("Clearance Distance (離隔距離)", all_clearance_m)
    print_stats("Left White Line Dist (左白線距離)", all_left_line_dist_m)
    print_stats("Right White Line Dist (右白線距離)", all_right_line_dist_m)

    print("-" * 40)
    print("Done.")

if __name__ == "__main__":
    main()
