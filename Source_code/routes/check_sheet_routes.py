from flask import Blueprint, render_template, request, flash, current_app, redirect, url_for
import pandas as pd
import sqlite3
import os
import math
import threading
import cv2
import numpy as np
from Source_code.modules.db_manager import MAIN_DB_PATH, insert_manual_overtake_event, apply_manual_overtake_flags
from Source_code.modules.db_manager import MAIN_DB_PATH, insert_manual_overtake_event, apply_manual_overtake_flags
from Source_code.modules.inference import process_video
from typing import Dict, Any
import json
import time

# To store rerun progress and results
check_sheet_bp = Blueprint('check_sheet', __name__)
rerun_status_cache: Dict[str, Any] = {}
rerun_status_lock = threading.Lock()

def calculate_run_stats(run_id, conn):
    """Runの統計情報を計算する"""
    stats = {}
    try:
        # 1. 白線距離 (line_distance_m)
        # SQLite doesn't have MEDIAN, so we fetch and calculate in Python
        cursor = conn.execute("SELECT line_distance_m FROM Detection WHERE run_id = ? AND line_distance_m IS NOT NULL", (run_id,))
        distances = [r[0] for r in cursor.fetchall()]
        if distances:
            stats['line_dist_min'] = min(distances)
            stats['line_dist_max'] = max(distances)
            stats['line_dist_median'] = float(np.median(distances))
        else:
            stats['line_dist_min'] = None
            stats['line_dist_max'] = None
            stats['line_dist_median'] = None

        # 2. Track ID数
        cursor = conn.execute("SELECT COUNT(DISTINCT obj_id) FROM Detection WHERE run_id = ?", (run_id,))
        stats['track_count'] = cursor.fetchone()[0]

        # 3. グループIDの最大フレーム数
        # group_id ごとのレコード数をカウント
        cursor = conn.execute("SELECT MAX(cnt) FROM (SELECT COUNT(*) as cnt FROM Detection WHERE run_id = ? AND group_id IS NOT NULL GROUP BY group_id)", (run_id,))
        res = cursor.fetchone()
        stats['max_group_frames'] = res[0] if res and res[0] else 0

        # 4. 追い越し数
        cursor = conn.execute("SELECT COUNT(*) FROM OvertakeEvents WHERE run_id = ?", (run_id,))
        stats['overtake_count'] = cursor.fetchone()[0]
        
    except Exception as e:
        print(f"Error calculating stats for run {run_id}: {e}")
        stats = {
            'line_dist_min': None, 'line_dist_max': None, 'line_dist_median': None,
            'track_count': 0, 'max_group_frames': 0, 'overtake_count': 0
        }
    return stats

@check_sheet_bp.route('/rerun_monitor')
def rerun_monitor():
    return render_template('check_sheet_rerun_monitor.html')

@check_sheet_bp.route('/api/rerun_progress')
def api_rerun_progress():
    with rerun_status_lock:
        return current_app.response_class(
            json.dumps(rerun_status_cache, ensure_ascii=False),
            mimetype='application/json'
        )

@check_sheet_bp.route('/check_sheet', methods=['GET', 'POST'])
def import_check_sheet():
    results = []
    video_summary = []
    
    if request.method == 'POST':
        tsv_data = request.form.get('tsv_data', '')
        if not tsv_data.strip():
            flash('データが空です', 'warning')
        else:
            results = process_check_sheet(tsv_data)
            success_count = sum(1 for r in results if r['status'] == 'Registered')
            flash(f'処理完了: 登録 {success_count} 件', 'success')
            
            # 動画ごとのサマリーを生成
            video_summary = generate_video_summary(results)
            
    # Model listing for Re-run
    model_dir = os.path.abspath(os.getenv("MODEL_PATH", "models"))
    available_models = []
    if os.path.exists(model_dir):
        available_models = sorted([
            f for f in os.listdir(model_dir) 
            if f.lower().endswith(".pt") and os.path.isfile(os.path.join(model_dir, f))
        ])

    return render_template('check_sheet_view.html', results=results, video_summary=video_summary, available_models=available_models)


def generate_video_summary(results):
    """resultsから動画ごとのサマリーを生成"""
    from collections import defaultdict
    
    video_stats = defaultdict(lambda: {
        'registered': 0,
        'skipped': 0,
        'video_not_found': 0,
        'no_detection': 0,
        'error': 0,
        'overtake_applied': 0,
        'details': []
    })
    
    for r in results:
        video = r['video']
        st = r['status']
        
        if st == 'Registered':
            video_stats[video]['registered'] += 1
            if r.get('overtake_applied'):
                video_stats[video]['overtake_applied'] += 1
            video_stats[video]['details'].append(f"登録: {r['details']}")
        elif st == 'Skipped':
            video_stats[video]['skipped'] += 1
        elif st == 'VideoNotFound':
            video_stats[video]['video_not_found'] += 1
            video_stats[video]['details'].append(f"動画なし: {r['details']}")
        elif st == 'NoDetection':
            video_stats[video]['no_detection'] += 1
            video_stats[video]['details'].append(f"検出なし: {r['details']}")
        else:
            video_stats[video]['error'] += 1
            video_stats[video]['details'].append(f"エラー: {r['details']}")
    
    summary = []
    for video_name, stats in video_stats.items():
        # ステータス判定ロジック
        if stats['video_not_found'] > 0:
            status_icon = 'cross' # × (Red)
        elif stats['no_detection'] > 0:
            status_icon = 'star'  # ★ (Gold)
        elif stats['registered'] > 0:
            status_icon = 'circle' # ○ (Green)
        elif stats['skipped'] > 0:
            status_icon = 'triangle' # △ (Yellow)
        else:
            status_icon = 'cross' # × (Red)
        
        # サマリーテキスト
        parts = []
        if stats['registered'] > 0: parts.append(f"登録{stats['registered']}件")
        if stats['overtake_applied'] > 0: parts.append(f"追い越し判定付与{stats['overtake_applied']}件")
        if stats['skipped'] > 0: parts.append(f"重複{stats['skipped']}件")
        if stats['video_not_found'] > 0: parts.append("動画見つからず")
        if stats['no_detection'] > 0: parts.append("検出なし")
        if stats['error'] > 0: parts.append(f"エラー{stats['error']}件")
        
        summary.append({
            'name': video_name,
            'status_icon': status_icon,
            'stat_counts': stats,
            'summary': ', '.join(parts) if parts else '処理なし'
        })
    
    return summary


def calculate_distance(obj1, obj2):
    """2つのオブジェクト間のmeasure_point間の距離を計算"""
    mx1 = obj1.get('measure_x') or (obj1['x1'] + obj1['x2']) / 2
    my1 = obj1.get('measure_y') or obj1['y2']
    mx2 = obj2.get('measure_x') or (obj2['x1'] + obj2['x2']) / 2
    my2 = obj2.get('measure_y') or obj2['y2']
    return math.sqrt((mx1 - mx2) ** 2 + (my1 - my2) ** 2)


def process_check_sheet(text_data):
    """
    TSVデータを処理し、手動追い越しイベントとしてManualOvertakeEventsに登録する。
    
    データ形式: video_name\tframe\tclass (自転車と車両のペア)
    - 自転車 = 追い越され側 (overtaken)
    - 車両 (car/truck/bus) = 追い越し側 (overtaker)
    
    ロジック:
    1. VideoテーブルのfilenameでビデオIDを取得
    2. Detectionテーブルで該当フレーム付近の検出を取得
    3. 自転車ごとに最も近い車両とペアリング
    4. 複数自転車がある場合は複数のイベントを登録
    """
    results = []
    lines = text_data.strip().split('\n')
    
    # Parse lines into list of dicts
    parsed_rows = []
    for line in lines:
        # 空行をスキップ
        if not line.strip():
            continue
        parts = line.strip().split('\t')
        if len(parts) >= 3:
            video_name = parts[0].strip()
            video_name = video_name.replace('"', '').replace("'", "")
            try:
                frame = int(parts[1].strip())
                cls = parts[2].strip().lower()
                parsed_rows.append({'video': video_name, 'frame': frame, 'class': cls})
            except:
                continue

    if not parsed_rows:
        return []

    # Group by Video + Frame
    df = pd.DataFrame(parsed_rows)
    if df.empty:
        return []

    groups = df.groupby(['video', 'frame'])
    
    db_path = MAIN_DB_PATH
    
    with sqlite3.connect(db_path) as conn:
        for (video, frame), group_df in groups:
            classes = group_df['class'].tolist()
            
            res_entry = {
                'video': video,
                'frame': frame,
                'pair': ", ".join(classes),
                'status': 'Unknown',
                'details': '',
                'overtake_applied': False
            }
            
            # 1. VideoテーブルからビデオIDを取得
            vid_row = conn.execute(
                "SELECT video_id FROM Video WHERE filename = ?", 
                (video,)
            ).fetchone()
            
            if not vid_row:
                res_entry['status'] = 'VideoNotFound'
                res_entry['details'] = f'ビデオ "{video}" がVideoテーブルに見つかりません'
                results.append(res_entry)
                continue
            
            video_id = vid_row[0]
            
            # 2. ProcessLogからrun_idを取得 (最新の実行を使用)
            run_row = conn.execute(
                "SELECT run_id FROM ProcessLog WHERE video_id = ? ORDER BY run_id DESC", 
                (video_id,)
            ).fetchone()
            
            if not run_row:
                res_entry['status'] = 'VideoNotFound'
                res_entry['details'] = f'video_id={video_id} のProcessLogが見つかりません'
                results.append(res_entry)
                continue
            
            run_id = run_row[0]
            res_entry['run_id'] = run_id
            
            # 3. Check overlap - OvertakeEvents (自動検出)
            overlap_auto = conn.execute("""
                SELECT overtake_event_id FROM OvertakeEvents 
                WHERE run_id = ? 
                AND ABS(event_frame_num - ?) <= 60
            """, (run_id, frame)).fetchone()
            
            if overlap_auto:
                res_entry['status'] = 'Skipped'
                res_entry['details'] = f'自動追い越しイベント #{overlap_auto[0]} が近くに存在'
                results.append(res_entry)
                continue
            
            # 4. Check overlap - ManualOvertakeEvents (手動登録済み)
            overlap_manual = conn.execute("""
                SELECT manual_event_id FROM ManualOvertakeEvents 
                WHERE run_id = ? 
                AND ABS(frame_num - ?) <= 60
            """, (run_id, frame)).fetchone()
            
            if overlap_manual:
                res_entry['status'] = 'Skipped'
                res_entry['details'] = f'手動追い越しイベント #{overlap_manual[0]} が近くに存在'
                results.append(res_entry)
                continue
            
            # 5. Detectionテーブルから検出を取得 (ClassMasterとJOINしてclass_nameを取得)
            # フレーム付近±5で検索し、group_idを特定してから入力フレームに最も近い検出を使用
            cursor = conn.execute("""
                SELECT 
                    d.group_id, 
                    c.class_name, 
                    d.x1, d.y1, d.x2, d.y2, 
                    d.auto_id,
                    d.measure_x, d.measure_y,
                    d.frame_num
                FROM Detection d
                LEFT JOIN ClassMaster c ON d.class_id = c.class_id
                WHERE d.run_id = ? AND ABS(d.frame_num - ?) <= 5
                ORDER BY ABS(d.frame_num - ?) ASC
            """, (run_id, frame, frame))
            detections = cursor.fetchall()
            
            if not detections:
                res_entry['status'] = 'NoDetection'
                res_entry['details'] = f'フレーム {frame}±5 に検出がありません'
                results.append(res_entry)
                continue
                
            # Filter Candidates
            # Overtaker (Car/Bus/Truck) と Overtaken (Bicycle) を分類
            # group_id でユニーク化（入力フレームに最も近い検出を優先）
            bike_by_group = {}  # group_id -> 検出データ
            car_by_group = {}   # group_id -> 検出データ
            
            for d in detections:
                gid, d_cls, x1, y1, x2, y2, aid, measure_x, measure_y, det_frame = d
                if gid is None:
                    continue
                    
                d_cls_lower = str(d_cls).lower() if d_cls else ''
                
                obj = {
                    'group_id': gid, 
                    'auto_id': aid, 
                    'class_name': d_cls or 'unknown',
                    'x1': x1 or 0, 'y1': y1 or 0, 'x2': x2 or 0, 'y2': y2 or 0,
                    'measure_x': measure_x, 'measure_y': measure_y,
                    'frame_num': det_frame
                }
                
                # group_idでユニーク化（最初に見つかった＝入力フレームに最も近い）
                if 'bicycle' in d_cls_lower or 'bike' in d_cls_lower:
                    if gid not in bike_by_group:
                        bike_by_group[gid] = obj
                elif any(x in d_cls_lower for x in ['car', 'truck', 'bus', 'van']):
                    if gid not in car_by_group:
                        car_by_group[gid] = obj
            
            bike_candidates = list(bike_by_group.values())
            car_candidates = list(car_by_group.values())
            
            # Selection
            if not bike_candidates:
                res_entry['status'] = 'NoDetection'
                res_entry['details'] = '自転車の検出が見つかりません'
                results.append(res_entry)
                continue
                
            if not car_candidates:
                res_entry['status'] = 'NoDetection'
                res_entry['details'] = '車両の検出が見つかりません'
                results.append(res_entry)
                continue
            
            # 6. 各自転車に最も近い車をペアリングして登録（group_idがユニークなので重複なし）
            registered_count = 0
            registered_details = []
            
            for bike in bike_candidates:
                # 自転車に最も近い車を見つける
                if not car_candidates:
                    continue
                    
                closest_car = min(car_candidates, key=lambda car: calculate_distance(bike, car))
                
                # ManualOvertakeEvents へ登録（入力フレームを使用）
                try:
                    event_payload = {
                        'run_id': run_id,
                        'frame_num': frame,  # 入力フレームを使用
                        'overtaker_group_id': closest_car['group_id'],
                        'overtaker_class_name': closest_car['class_name'],
                        'overtaker_x1': closest_car['x1'],
                        'overtaker_y1': closest_car['y1'],
                        'overtaker_x2': closest_car['x2'],
                        'overtaker_y2': closest_car['y2'],
                        'overtaker_measure_x': closest_car.get('measure_x'),
                        'overtaker_measure_y': closest_car.get('measure_y'),
                        'overtaken_group_id': bike['group_id'],
                        'overtaken_class_name': bike['class_name'],
                        'overtaken_x1': bike['x1'],
                        'overtaken_y1': bike['y1'],
                        'overtaken_x2': bike['x2'],
                        'overtaken_y2': bike['y2'],
                        'overtaken_measure_x': bike.get('measure_x'),
                        'overtaken_measure_y': bike.get('measure_y'),
                        'notes': 'check_sheet_import'
                    }
                    
                    event_id = insert_manual_overtake_event(event_payload)
                    registered_count += 1
                    
                    # 追い越し判定フラグを適用
                    applied = apply_manual_overtake_flags(run_id, frame, closest_car['group_id'], bike['group_id'])
                    if applied:
                        res_entry['overtake_applied'] = True
                    
                    registered_details.append(f"#{event_id}(grp:{closest_car['group_id']} vs grp:{bike['group_id']})")
                except Exception as e:
                    res_entry['status'] = 'Error'
                    res_entry['details'] = str(e)
                    results.append(res_entry)
                    continue
            
            if registered_count > 0:
                res_entry['status'] = 'Registered'
                res_entry['details'] = f'{registered_count}件登録: ' + ', '.join(registered_details)
            
            # Make run_id available for template links
            res_entry['run_id'] = run_id
            
            results.append(res_entry)

    return results

    return results



def enhance_video(input_path, output_path, gamma=1.0, contrast=1.0, grayscale=False):
    """動画の補正（明るさ、コントラスト、白黒）を行い、新しいファイルに出力する。"""
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise IOError(f"Could not open video: {input_path}")

    # プロパティ取得
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v') # mp4 output

    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    
    # ガンマ補正用ルックアップテーブル作成
    inv_gamma = 1.0 / gamma
    table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in range(256)]).astype("uint8")

    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # 1. ガンマ補正
        if gamma != 1.0:
            frame = cv2.LUT(frame, table)
        
        # 2. 白黒化 (必要な場合)
        if grayscale:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # コントラスト適用などのためにBGRに戻す (YOLOは通常3ch入力を期待)
            # あるいはGrayscaleのまま処理できるかはモデル依存だが、OpenCVのVideoWriterはカラー期待かも?
            # ここでは安全のためBGRに戻す
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

        # 3. コントラスト強調 (Alpha blending)
        if contrast != 1.0:
            frame = cv2.convertScaleAbs(frame, alpha=contrast, beta=0)

        out.write(frame)
        frame_count += 1
        
    cap.release()
    out.release()
    return frame_count


@check_sheet_bp.route('/rerun_yolo_for_run', methods=['POST'])
def rerun_yolo_for_run():
    """指定されたRun ID(複数可)の動画に対して、指定されたモデルでYOLO推論を再実行する"""
    run_ids_str = request.form.get('run_ids') or request.form.get('run_id') # Support both plural and singular input
    
    vehicle_model = request.form.get('vehicle_model')
    tire_model = request.form.get('tire_model')
    
    do_enhance = request.form.get('enhance_video') == 'true'
    gamma_val = float(request.form.get('gamma_value', 1.5))
    contrast_val = float(request.form.get('contrast_value', 1.0))
    grayscale = request.form.get('grayscale') == 'true'
    
    if not run_ids_str:
        flash('Run IDが指定されていません', 'danger')
        return render_template('check_sheet_view.html', results=[], video_summary=[], available_models=[])

    try:
        # IDリストの解析
        run_ids = [int(rid.strip()) for rid in run_ids_str.split(',') if rid.strip()]
        if not run_ids:
            raise ValueError("No valid Run IDs")
            
        print(f"[Rerun] Requested batch run for IDs: {run_ids}")
        
        # Initialize status cache
        with rerun_status_lock:
            rerun_status_cache.clear()
            rerun_status_cache['status'] = 'running'
            rerun_status_cache['total_videos'] = len(run_ids)
            rerun_status_cache['processed_videos'] = 0
            rerun_status_cache['results'] = []
            rerun_status_cache['current_progress'] = 0
            rerun_status_cache['current_video'] = ""
        
        # バックグラウンドで順次実行
        def worker(r_ids, v_model, t_model):
            print(f"[Rerun Worker] Starting batch of {len(r_ids)} videos")
            
            for idx, current_run_id in enumerate(r_ids):
                temp_enhanced_path = None
                video_info_name = f"Run {current_run_id}"
                
                before_stats = {}
                after_stats = {}
                error_msg = None

                try:
                    print(f"[Rerun Worker] Processing Run ID: {current_run_id}...")
                    
                    # Update status
                    with rerun_status_lock:
                        rerun_status_cache['current_video'] = f"Run {current_run_id} (前処理中...)"
                        rerun_status_cache['current_progress'] = 0

                    # Run情報取得 & Before Stats
                    with sqlite3.connect(MAIN_DB_PATH) as conn:
                        query = """
                            SELECT v.source_path, v.video_id, p.process_year, p.location_id, v.road_type, p.folder_alias, p.is_folder_batch, p.calibration_profile, v.filename
                            FROM ProcessLog p
                            JOIN Video v ON p.video_id = v.video_id
                            WHERE p.run_id = ?
                        """
                        row = conn.execute(query, (current_run_id,)).fetchone()
                        
                        if not row:
                            print(f"[Rerun Worker] Skipped Run {current_run_id}: Not found")
                            continue

                        source_path, original_video_id, process_year, location_id, road_type, folder_alias, is_folder_batch_val, saved_profile, filename = row
                        is_folder_batch = bool(is_folder_batch_val)
                        video_info_name = filename

                        # Before Stats Calculation
                        before_stats = calculate_run_stats(current_run_id, conn)

                        # ManualOvertakeEventsのバックアップ
                        # Note: This backup logic is now duplicated in modules/inference.py but we keep it here just in case? 
                        # Actually modules/inference.py handles backup/restore internally now if overwrite=True.
                        # However, check_sheet_routes.py relies on explicit restore if needed?
                        # Wait, recent changes to inference.py handle backup/restore automatically inside process_video if overwrite=True.
                        # So explicit backup/restore here might be redundant or conflict.
                        # The implementation plan said "backup/restore logic in inference.py".
                        # So we can remove explicit backup/restore here to avoid double restore issues or just keep it to be safe (if logic differs).
                        # Let's trust inference.py for backup/restore. But we need to make sure inference.py was updated and correct.
                        # Yes, step 12 implemented it. So we REMOVE explicit backup/restore from here to rely on inference.py.
                        # BUT, calculation of stats must happen BEFORE process_video deletes data.

                    if not os.path.exists(source_path):
                        print(f"[Rerun Worker] Skipped Run {current_run_id}: Source file missing ({source_path})")
                        error_msg = "Source file missing"
                        # Fall through to update result

                    else:
                        target_video_path = source_path
                        force_vid = None
                        
                        # エフェクト適用
                        if do_enhance:
                            with rerun_status_lock:
                                rerun_status_cache['current_video'] = f"{filename} (補正処理中...)"

                            # 一時ファイル作成
                            opt_path = os.getenv("OPT_FILES_PATH", "output")
                            temp_dir = os.path.join(opt_path, "temp_processing")
                            os.makedirs(temp_dir, exist_ok=True)
                            
                            temp_filename = f"temp_enhance_{current_run_id}_{os.path.basename(source_path)}"
                            temp_enhanced_path = os.path.join(temp_dir, temp_filename)
                            
                            print(f"[Rerun Worker] Enhancing video for Run {current_run_id} (Gamma={gamma_val}, Contrast={contrast_val}, BW={grayscale})...")
                            enhance_video(source_path, temp_enhanced_path, gamma=gamma_val, contrast=contrast_val, grayscale=grayscale)
                            
                            target_video_path = temp_enhanced_path
                            # DB上は元のvideo_idとして扱いたい
                            force_vid = original_video_id
                            print(f"[Rerun Worker] Enhanced video created at {temp_enhanced_path}")

                        # Update status for YOLO
                        with rerun_status_lock:
                            rerun_status_cache['current_video'] = f"{filename} (YOLO推論中...)"

                        # custom callback to update progress
                        def progress_cb(current, total, status_text):
                            if total > 0:
                                pct = int((current / total) * 100)
                                with rerun_status_lock:
                                    rerun_status_cache['current_progress'] = pct
                        
                        # overwrite=True で再実行
                        # tire_model も渡す
                        # Note: inference.py modification handles backup/restore of profile/manual events automaticaly.
                        video_result = process_video(
                            target_video_path,
                            process_year=process_year,
                            location_id=location_id,
                            road_type=road_type,
                            vehicle_model=v_model,
                            tire_model=t_model,
                            overwrite=True,
                            folder_alias=folder_alias,
                            is_folder_batch=is_folder_batch,
                            force_video_id=force_vid,
                            progress_callback=progress_cb
                        )
                        
                        # After Stats (Wait for post process?)
                        # Post process is run after this.

                        # 自動後処理
                        with rerun_status_lock:
                            rerun_status_cache['current_video'] = f"{filename} (後処理中...)"
                            
                        print(f"[Rerun Worker] Starting post-process for Run ID {video_result.run_id}...")
                        from Source_code.modules.inference import run_postprocess_pipeline_sync
                        completed_steps, error_steps = run_postprocess_pipeline_sync(video_result.run_id)
                        
                        if error_steps:
                            print(f"[Rerun Worker] Post-process finished with errors: {error_steps}")
                            error_msg = f"Post-process errors: {error_steps}"
                        else:
                            print(f"[Rerun Worker] Post-process completed successfully.")

                        # Calculate stats for the NEW run
                        with sqlite3.connect(MAIN_DB_PATH) as conn:
                            after_stats = calculate_run_stats(video_result.run_id, conn)

                except Exception as e:
                    print(f"[Rerun Worker] Error processing Run {current_run_id}: {e}")
                    import traceback
                    traceback.print_exc()
                    error_msg = str(e)
                finally:
                    # 一時ファイル削除
                    if temp_enhanced_path and os.path.exists(temp_enhanced_path):
                        try:
                            os.remove(temp_enhanced_path)
                            print(f"[Rerun Worker] Deleted temp file: {temp_enhanced_path}")
                        except OSError:
                            pass
                    
                    # Update Result Cache
                    with rerun_status_lock:
                        rerun_status_cache['processed_videos'] += 1
                        rerun_status_cache['results'].append({
                            'video_name': video_info_name,
                            'run_id': current_run_id, # Old Run ID for reference
                            'before': before_stats,
                            'after': after_stats,
                            'error': error_msg
                        })

            print("[Rerun Worker] Batch processing completed.")
            with rerun_status_lock:
                rerun_status_cache['status'] = 'completed'
                rerun_status_cache['current_video'] = "完了"
                rerun_status_cache['current_progress'] = 100

        threading.Thread(target=worker, args=(run_ids, vehicle_model, tire_model), daemon=True).start()
        
        # モニタ画面へリダイレクト
        return redirect(url_for('check_sheet.rerun_monitor'))
        
    except ValueError:
        flash('無効なRun ID指定です', 'danger')
        return redirect(url_for('check_sheet.import_check_sheet'))
    except Exception as e:
        flash(f'エラーが発生しました: {e}', 'danger')
        current_app.logger.exception("Rerun failed")
        return redirect(url_for('check_sheet.import_check_sheet'))
