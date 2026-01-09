from flask import render_template, request, jsonify, redirect, url_for, flash, current_app
import os
from typing import Dict, Any, Optional
from . import main

# Global progress state for post-processing
post_process_progress: Dict[str, Any] = {
    "current": 0, 
    "total": 0, 
    "percent": 0, 
    "message": None, 
    "status": "idle"
}

@main.route("/post_process")
def post_process():
    """Post Process Page"""
    from ..modules.db_manager import get_all_process_logs, list_folder_batches
    from ..modules.video_generator import (
        DEFAULT_VIDEO_OPTIONS, 
        discover_font_files, 
        normalize_video_options
    )
    import glob
    import os
    
    # 1. Database Ready Check (simplified)
    # _ensure_database_ready logic omitted or assumed handled by db_manager calls
    
    # 2. Context Data
    opt_folder = os.getenv("Opt_files", "output")
    calib_dir = os.path.join(opt_folder, "calibrations")
    os.makedirs(calib_dir, exist_ok=True)
    
    available_profiles = sorted([
        os.path.basename(p).replace('.json', '') 
        for p in glob.glob(os.path.join(calib_dir, "*.json"))
        if not os.path.basename(p).startswith("calibration_")
    ])
    
    logs = get_all_process_logs()
    folder_batches = list_folder_batches()
    selected_run_id = request.args.get('selected_run_id', type=int)
    
    video_fonts = discover_font_files()
    normalized_defaults = normalize_video_options(
        DEFAULT_VIDEO_OPTIONS, 
        [entry['path'] for entry in video_fonts]
    )
    
    return render_template(
        "post_process.html",
        title="Post Process",
        logs=logs,
        folder_batches=folder_batches,
        available_profiles=available_profiles,
        selected_run_id=selected_run_id,
        progress=post_process_progress,
        video_fonts=video_fonts,
        video_option_defaults=normalized_defaults,
    )


@main.route("/api/process_logs")
def api_process_logs():
    """処理ログ一覧を取得する。"""
    try:
        from ..modules.db_manager import get_all_process_logs
        logs = get_all_process_logs()
        
        # Format for display
        results = []
        for log in logs:
            run_id = log["run_id"]
            video_name = log.get("video_filename", "Unknown")
            start_dt = log.get("start_datetime", "")
            end_dt = log.get("end_datetime", "")
            status = log.get("status", "unknown")
            output_folder = log.get("output_folder", "")
            
            results.append({
                "run_id": run_id,
                "video_name": video_name,
                "start_time": start_dt,
                "end_time": end_dt,
                "status": status,
                "output_folder": output_folder,
                "message": log.get("message", "")
            })
            
        return jsonify({"data": results})
    except Exception as e:
        current_app.logger.exception("Failed to fetch process logs")
        return jsonify({"data": []}) # Return empty list on error to not break table


@main.route("/post_process/status")
def post_process_status():
    """現在の後処理の進捗状況を返す。"""
    return jsonify(post_process_progress)



@main.route("/api/post_process/preview", methods=["POST"])
def preview_post_process():
    """後処理実行前の確認用データを返す。
    エラー発生時はどの段階で失敗したかを明確に返す。
    Steps:
    1. 対象Runの特定 (DB Lookup)
    2. 動画パスの特定 (Path Resolution)
    3. 動画フレームの読み込み (Video Read)
    4. キャリブレーション読み込み (Profile Load)
    5. 描画と保存 (Draw & Encode)
    """
    debug_steps = []
    
    def log_step(message):
        """ログをdebug_stepsとターミナルの両方に出力"""
        debug_steps.append(message)
        print(f"[PREVIEW] {message}")
    
    try:
        data = request.get_json() or {}
        
        target_mode = data.get("target_mode")
        target_run_id = data.get("run_id")
        target_folder = data.get("folder_alias")
        profile_name = data.get("folder_profile_name")
        
        log_step(f"Request: mode={target_mode}, folder={target_folder}, run={target_run_id}, profile={profile_name}")

        # 1. Identify Target Runs
        from ..modules.db_manager import list_folder_batches, get_run_ids_by_folder, get_run_video_info
        
        run_ids = []
        try:
            if target_mode == "folder" and target_folder:
                run_ids = get_run_ids_by_folder(target_folder)
            elif target_mode == "run" and target_run_id:
                 run_ids = [int(target_run_id)]
            log_step(f"Step 1 OK: Found {len(run_ids)} runs")
        except Exception as e:
            log_step(f"Step 1 Failed (DB Lookup): {e}")
            return jsonify({"error": f"Step 1 Failed (DB Lookup): {e}", "debug": debug_steps}), 500
             
        if not run_ids:
             log_step("Error: No target runs found")
             return jsonify({"error": "処理対象が見つかりません。", "debug": debug_steps}), 404
             
        # Determine index
        preview_index = int(data.get("preview_index", 0))
        if preview_index < 0: preview_index = 0
        if preview_index >= len(run_ids): preview_index = len(run_ids) - 1
        
        target_run_id = run_ids[preview_index]
        
        # 2. Get Metadata & Video Path
        try:
            repre_info = get_run_video_info(target_run_id)
            log_step(f"Step 2 OK: Metadata for run {target_run_id} (Index {preview_index}) retrieved")
        except Exception as e:
            log_step(f"Step 2 Failed (Metadata Fetch): {e}")
            return jsonify({"error": f"Step 2 Failed (Metadata Fetch): {e}", "debug": debug_steps}), 500

        # Determine Profile - サブフォルダプロファイルも考慮
        effective_profile = None
        
        # 1. 明示的に指定されたプロファイル
        if target_mode == "folder" and profile_name:
            effective_profile = profile_name
            log_step(f"Using explicit folder profile: {profile_name}")
        
        # 2. サブフォルダプロファイル設定を確認
        if not effective_profile:
            folder_alias_for_run = repre_info.get("folder_alias", "")
            if folder_alias_for_run:
                try:
                    from ..modules.folder_config import load_folder_settings
                    upload_folder = os.getenv("Upload_folder", "uploads")
                    
                    # 階層の深いパスを分解してルートフォルダを特定
                    alias_parts = folder_alias_for_run.replace("\\", "/").split("/")
                    if len(alias_parts) >= 2:
                        # ルートフォルダ（例: new_x）の設定を読み込む
                        root_alias = alias_parts[0]
                        root_folder_path = os.path.join(upload_folder, root_alias)
                        if os.path.isdir(root_folder_path):
                            settings = load_folder_settings(root_folder_path)
                            subfolders_config = settings.get("subfolders", {})
                            # サブフォルダ名（例: 1_250803）のプロファイルを取得
                            subfolder_name = alias_parts[1]
                            if subfolder_name in subfolders_config:
                                effective_profile = subfolders_config[subfolder_name]
                                log_step(f"Using subfolder profile: {subfolder_name} -> {effective_profile}")
                            elif folder_alias_for_run in subfolders_config:
                                effective_profile = subfolders_config[folder_alias_for_run]
                                log_step(f"Using full alias profile: {folder_alias_for_run} -> {effective_profile}")
                except Exception as e:
                    log_step(f"Subfolder profile lookup error: {e}")
        
        # 3. Runに保存されたプロファイル
        if not effective_profile:
            effective_profile = repre_info.get("calibration_profile")
            if effective_profile:
                log_step(f"Using run's saved profile: {effective_profile}")
        
        log_step(f"Effective profile: {effective_profile}")
        
        # 3. Resolve Video Path
        video_path = repre_info.get("source_path")
        if not video_path:
             log_step("Step 3 Warning: source_path is empty in DB")
        elif not os.path.exists(video_path):
             log_step(f"Step 3 Error: File not found at {video_path}")
             video_path = None # Invalid
        else:
             log_step(f"Step 3 OK: Video file exists at {video_path}")

        # 4. Generate Preview Image
        img_base64 = None
        img_error = None
        
        if effective_profile:
             # Load Calibration Profile
            import json
            calib_dir = os.path.join(os.getenv("Opt_files", "output"), "calibrations")
            profile_path = os.path.join(calib_dir, f"{effective_profile}.json")
            
            if not os.path.exists(profile_path):
                log_step(f"Step 4 Error: Profile json not found at {profile_path}")
                img_error = f"プロファイルが見つかりません: {effective_profile}"
            else:
                log_step(f"Step 4 OK: Profile found: {effective_profile}")
                
                if video_path:
                    try:
                        from ..modules.video_utils import load_video_frame
                        frame = load_video_frame(video_path, 0) # Frame 0
                        
                        if frame is None:
                            log_step("Step 5 Error: Failed to load frame 0 (cv2 read failed)")
                            img_error = "動画フレームの読み込みに失敗しました"
                        else:
                            log_step("Step 5 OK: Frame loaded")
                            
                            # Draw Lines using shared function
                            try:
                                with open(profile_path, 'r', encoding='utf-8') as f:
                                    p_data = json.load(f)
                                
                                import cv2
                                from .calibration import draw_calibration_lines
                                lines = p_data.get("lines", {})
                                drew_lines = any(lines.get(k) for k in ["left_white_line", "right_white_line", "center_line", "left_mid_line", "right_mid_line"])
                                
                                if drew_lines:
                                    draw_calibration_lines(frame, lines)
                                
                                log_step(f"Step 6 OK: Drew lines (found={drew_lines})")
                                
                                # Encode
                                _, buffer = cv2.imencode('.jpg', frame)
                                import base64
                                img_base64 = base64.b64encode(buffer).decode('utf-8')
                                log_step("Step 7 OK: Image encoded to base64")
                                
                            except Exception as e_draw:
                                log_step(f"Step 6 Error (Drawing): {e_draw}")
                                img_error = f"描画エラー: {e_draw}"
                                
                    except Exception as e_vid:
                        log_step(f"Step 5 Error (Video Load): {e_vid}")
                        img_error = f"動画読み込みエラー: {e_vid}"
                else:
                    log_step("Warning: Video path is None, cannot generate preview")
                    img_error = "動画ファイルが見つかりません"
        else:
            log_step("Warning: No effective profile, skipping preview generation")

        log_step("Preview generation completed")
        
        return jsonify({
            "count": len(run_ids),
            "total_runs_count": len(run_ids),
            "preview_index": preview_index,
            "run_ids_sample": run_ids[:5],
            "total_runs": run_ids,
            "year": repre_info.get("collection_year"),
            "road_type": repre_info.get("road_type"),
            "profile": effective_profile,
            "image": img_base64,
            "image_error": img_error,
            "debug_log": debug_steps,
            "current_run_id": target_run_id
        })
            
    except Exception as e:
        log_step(f"Critical Failure: {str(e)}")
        current_app.logger.exception("Preview critical failure")
        return jsonify({"error": f"Critical Failure: {str(e)}", "debug": debug_steps}), 500


@main.route("/post_process/action", methods=["POST"])
def post_process_action():
    """詳細集計・CSVバンドル作成のバックグラウンド処理を開始する。"""
    print("[DEBUG] Terminal Output: Execute Button Pressed! (Backend Reached)")
    global post_process_progress
    
    if post_process_progress["status"] == "processing":
         return jsonify({"error": "現在、他の処理が実行中です。"}), 400

    # Handle JSON or Form Data
    if request.is_json:
        req_data = request.get_json()
    else:
        req_data = request.form

    action = req_data.get("action")
    target_date = req_data.get("target_date") 
    
    # Background Thread
    import threading
    import concurrent.futures
    from ..modules.db_manager import list_folder_batches, get_run_ids_by_folder
    # Import the new worker module
    from ..modules.batch_processor import process_single_batch
    
    def worker():
        try:
            import multiprocessing

            # 1. Setup - 進捗を完全にリセット
            post_process_progress.update({
                "status": "processing",
                "current": 0,
                "total": 0, 
                "percent": 0,
                "batch_percent": 0,
                "message": "初期化中...",
                "current_detail": "",
                "details": [],
                "logs": [],
                "results": None
            })

            # Retrieve form data
            
            t_mode = req_data.get("target_mode", "run")
            t_run_id = req_data.get("run_id")
            t_folder = req_data.get("folder_alias")
            
            # Additional Options
            t_profile_name = req_data.get("folder_profile_name")
            t_profile_scope = req_data.get("folder_profile_scope")
            
            # ===== 動画生成処理 =====
            if action == "generate_video":
                from ..modules.video_generator import VideoGenerator, normalize_video_options
                
                # Run IDの取得
                if not t_run_id:
                    post_process_progress.update({
                        "status": "error",
                        "message": "Run IDが指定されていません。"
                    })
                    return
                
                run_id = int(t_run_id)
                
                post_process_progress.update({
                    "message": f"Run ID {run_id} の動画を生成中...",
                    "percent": 10
                })
                
                # 動画オプションの取得
                video_options = {}
                
                # 表示要素のチェックボックス
                if req_data.get("video_options_submitted"):
                    video_options["show_vehicle_box"] = req_data.get("video_show_vehicle_box") is not None
                    video_options["show_tire_boxes"] = req_data.get("video_show_tire_boxes") is not None
                    video_options["show_trace"] = req_data.get("video_show_trace") is not None
                    video_options["show_measurement"] = req_data.get("video_show_measurement") is not None
                    video_options["show_approach_lines"] = req_data.get("video_show_approach_lines") is not None
                    video_options["show_lane_left"] = req_data.get("video_show_lane_left") is not None
                    video_options["show_lane_right"] = req_data.get("video_show_lane_right") is not None
                    video_options["show_lane_center"] = req_data.get("video_show_lane_center") is not None
                    video_options["show_homography_overlay"] = req_data.get("video_show_homography_overlay") is not None
                    video_options["show_homography_only"] = req_data.get("video_show_homography_only") is not None
                    
                    # ラベル項目
                    video_options["label_group_id"] = req_data.get("video_label_group") is not None
                    video_options["label_speed"] = req_data.get("video_label_speed") is not None
                    video_options["label_lane_distance"] = req_data.get("video_label_lane") is not None
                    video_options["label_approach"] = req_data.get("video_label_approach") is not None
                    video_options["label_clearance"] = req_data.get("video_label_clearance") is not None
                    video_options["label_direction"] = req_data.get("video_label_direction") is not None
                    video_options["label_overtake"] = req_data.get("video_label_overtake") is not None
                    video_options["label_acceleration"] = req_data.get("video_label_acceleration") is not None
                    
                    # フォント設定
                    font_path = req_data.get("video_font_path")
                    if font_path:
                        video_options["font_path"] = font_path
                    
                    font_size = req_data.get("video_font_size")
                    if font_size:
                        try:
                            video_options["font_size"] = int(font_size)
                        except (ValueError, TypeError):
                            pass
                    
                    # 出力設定
                    output_format = req_data.get("video_output_format")
                    if output_format:
                        video_options["output_format"] = output_format
                    
                    output_name_mode = req_data.get("video_output_name_mode")
                    if output_name_mode:
                        video_options["output_name_mode"] = output_name_mode
                
                # VideoGeneratorで動画生成
                try:
                    post_process_progress.update({
                        "message": f"動画生成を開始しています...",
                        "percent": 20
                    })
                    
                    generator = VideoGenerator(run_id, options=video_options)
                    output_path = generator.run()
                    
                    post_process_progress.update({
                        "status": "complete",
                        "percent": 100,
                        "message": f"動画生成が完了しました: {output_path}",
                        "results": {
                            "output_path": output_path,
                            "run_id": run_id
                        }
                    })
                    
                except Exception as e:
                    current_app.logger.exception(f"Video generation failed for run {run_id}")
                    post_process_progress.update({
                        "status": "error",
                        "message": f"動画生成に失敗しました: {str(e)}"
                    })
                
                return
            
                return
            
            # ===== Export Targets (Bicycle / Overtaken) Logic =====
            if action in ["export_targets_csv", "export_targets_excel"]:
                # 1. Identify Target Runs based on t_mode
                target_runs = []
                from ..modules.db_manager import list_folder_batches, get_run_ids_by_folder, get_all_run_ids, get_run_ids_by_condition

                if t_mode == "all" or action == "process_all": # Though action check handles intent, keep t_mode consistency
                    target_runs = get_all_run_ids()
                
                elif t_mode == "folder" and t_folder:
                    target_runs = get_run_ids_by_folder(t_folder)
                    
                elif t_mode == "run" and t_run_id:
                    target_runs = [int(t_run_id)]
                    
                elif t_mode == "condition":
                    t_road_type = req_data.get("condition_road_type")
                    t_year = req_data.get("condition_year")
                    target_runs = get_run_ids_by_condition(road_type=t_road_type, process_year=t_year)
                
                if not target_runs:
                     return jsonify({"status": "error", "message": "対象のデータが見つかりません"}), 404

                # 2. Export Data
                from ..modules.comparative_report import export_target_vehicles
                fmt = "csv" if action == "export_targets_csv" else "excel"
                file_bytes = export_target_vehicles(target_runs, output_format=fmt)
                
                # 3. Create temp file for download (since this is async worker, we need a way to pass it back... 
                # actually, post_process_action is defined as start_background_task. 
                # This route is NOT returning a file directly, it returns JSON status.
                # So we must save the file and return the path in 'results'.
                
                # ...Wait, the user wants a button that downloads the file.
                # If I use the existing async worker structure, the user will have to wait for the progress bar to finish?
                # Exporting might be fast enough to be synchronous, OR I should save it to 'outputs' and provide a link.
                
                # Let's save to a temp file in 'outputs/exports' and return the path.
                
                filename = f"targets_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.{'csv' if fmt == 'csv' else 'xlsx'}"
                export_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'exports')
                os.makedirs(export_dir, exist_ok=True)
                file_path = os.path.join(export_dir, filename)
                
                with open(file_path, "wb") as f:
                    f.write(file_bytes)
                    
                # Update progress to complete immediately
                post_process_progress.update({
                    "status": "complete",
                    "percent": 100,
                    "message": "エクスポートが完了しました。",
                    "results": {
                        "download_url": f"/exports/{filename}", # Need a route to serve this? or static?
                        # Usually 'uploads' is static? Let's check. 
                        # If 'exports' is in UPLOAD_FOLDER, typically accessible via route if configured.
                        # Assuming I need to verify how to serve. 
                        # For now, let's assume I can serve it or I'll add a simple download route.
                        "filename": filename
                    }
                })
                return

            # ===== 既存のバッチ処理 =====
            # --- Apply Profile Logic ---
            if t_mode == "folder" and t_folder and t_profile_name:
                from ..modules.db_manager import update_folder_profiles
                count = update_folder_profiles(t_folder, t_profile_name, t_profile_scope)
                post_process_progress["details"].append(f"プロファイルを適用しました: {t_folder} ({count} Runs)")

            # --- Filter Batches Logic ---
            from ..modules.db_manager import list_folder_batches, get_run_ids_by_folder
            
            batches = list_folder_batches()
            valid_batches = []
            
            if t_mode == "folder" and t_folder:
                # Filter for single folder
                runs = get_run_ids_by_folder(t_folder)
                if runs:
                    valid_batches.append((t_folder, runs))
                    
            elif action == "process_all" or (action == "all_postprocess" and t_mode == "all"):
                # 全てのフォルダバッチを対象にする（フォルダ単位でまとめる）
                # さらに、フォルダに属さないRun（orphan）も拾う
                from ..modules.db_manager import get_all_run_ids
                
                # 1. 既存のフォルダバッチを追加
                processed_run_ids = set()
                for b in batches:
                    runs = get_run_ids_by_folder(b["folder_alias"])
                    if runs:
                        valid_batches.append((b["folder_alias"], runs))
                        processed_run_ids.update(runs)
                
                # 2. フォルダに属さないRun（Orphan）を追加
                all_ids = get_all_run_ids()
                orphan_runs = [rid for rid in all_ids if rid not in processed_run_ids]
                
                if orphan_runs:
                    valid_batches.append(("Uncategorized (Orphan)", orphan_runs))
            
            elif t_mode == "run" and t_run_id:
                # Filter for single run
                # access run_id, check which folder it belongs to (or just process as ad-hoc batch)
                rid = int(t_run_id)
                found = False
                # We need to find the folder alias for this run to keep batch structure, or just use dummy
                # Iterate batches to find where this run lives
                for b in batches:
                    runs = get_run_ids_by_folder(b["folder_alias"])
                    if rid in runs:
                        valid_batches.append((b["folder_alias"], [rid]))
                        found = True
                        break
                if not found:
                     valid_batches.append(("SingleRun", [rid]))

            elif t_mode == "condition":
                # Filter by condition (road_type, year)
                t_road_type = req_data.get("condition_road_type")
                t_year = req_data.get("condition_year")
                
                from ..modules.db_manager import get_run_ids_by_condition
                # road_typeやyearが 'all' の場合は db_manager側で全件扱いになるよう調整済み、
                # またはここでパラメータ変換を行う
                
                # UIからは 'all', 'widened', 'non_widened', 'undefined' などが来る想定
                runs = get_run_ids_by_condition(road_type=t_road_type, process_year=t_year)
                
                if runs:
                    # バッチとしては1つの塊として扱うか、フォルダごとに分けるか。
                    # ここではシンプルに「ConditionBatch」として1つにまとめる
                    valid_batches.append((f"ConditionMatch ({len(runs)} runs)", runs))

            else:
                 # Legacy fall-back: Process EVERYTHING (or nothing?)
                 # If no target specified, maybe process nothing or all folders?
                 # UI defaults to Run mode. If submitted empty, do nothing.
                 pass

            total_tasks = len(valid_batches)
            post_process_progress["total"] = total_tasks
            
            if total_tasks == 0:
                post_process_progress.update({
                    "status": "complete",
                    "percent": 100,
                    "message": "処理対象が選択されていません。"
                })
                return

            post_process_progress["message"] = f"並列処理を開始: {total_tasks} バッチ"
            
            # Setup Manager Queue for granular progress
            manager = multiprocessing.Manager()
            queue = manager.Queue()
            
            def queue_listener(q):
                while True:
                    try:
                        msg = q.get()
                        if msg == "DONE":
                            break
                        if isinstance(msg, dict):
                            msg_type = msg.get("type", "")
                            m_text = msg.get("message", "")
                            
                            if msg_type == "progress":
                                # バッチ内進捗の更新
                                m_percent = msg.get("percent", 0)
                                if m_text:
                                    post_process_progress["message"] = m_text
                                    post_process_progress["current_detail"] = m_text
                                post_process_progress["batch_percent"] = m_percent
                                
                            elif msg_type == "log":
                                # ターミナル出力をログに追加
                                if m_text:
                                    logs = post_process_progress.get("logs", [])
                                    # 最大100件に制限
                                    if len(logs) >= 100:
                                        logs = logs[-99:]
                                    logs.append(m_text)
                                    post_process_progress["logs"] = logs
                                    
                    except Exception:
                        break

            listener = threading.Thread(target=queue_listener, args=(queue,))
            listener.daemon = True
            listener.start()
            
            # 2. Parallel Execution
            completed_count = 0
            aggregated_results = {
                "total_overtakes": 0,
                "images": []
            }

            # Use max_workers=None (defaults to num_cpus) or set explicitly if needed
            with concurrent.futures.ProcessPoolExecutor() as executor:
                # Submit all tasks
                future_to_alias = {
                    executor.submit(process_single_batch, alias, run_ids, output_dir=None, progress_queue=queue): alias 
                    for alias, run_ids in valid_batches
                }
                
                for future in concurrent.futures.as_completed(future_to_alias):
                    alias = future_to_alias[future]
                    try:
                        result = future.result()
                        msg = result.get("message", "")
                        
                        # Collect stats
                        ov = result.get("overtake_stats", {})
                        aggregated_results["total_overtakes"] += ov.get("total", 0)
                        aggregated_results["images"].extend(ov.get("images", []))
                        
                        # Log success/failure in details
                        # post_process_progress.setdefault("details", []).append(f"{alias}: {msg}")
                        
                    except Exception as exc:
                        current_app.logger.error(f"Batch {alias} generated an exception: {exc}")
                    
                    completed_count += 1
                    percent = int((completed_count / total_tasks) * 100)
                    # Note: Queue listener might also be updating message, but that's fine (last wins)
                    post_process_progress.update({
                        "current": completed_count,
                        "percent": percent
                    })
            
            # Stop listener
            queue.put("DONE")
            listener.join()

            # 3. Completion
            post_process_progress.update({
                "status": "complete",
                "percent": 100,
                "message": "すべての並列処理が完了しました。",
                "results": {
                    "total_overtakes": aggregated_results["total_overtakes"],
                    "images": sorted(aggregated_results["images"])
                }
            })
                
        except Exception as e:
            current_app.logger.exception("Post process background job failed")
            post_process_progress.update({
                "status": "error",
                "message": f"エラーが発生しました: {str(e)}"
            })
    

    
    # Capture the real app object to pass to the thread
    app = current_app._get_current_object()

    def worker_wrapper():
        """Worker wrapper to ensure application context"""
        with app.app_context():
            worker()

    thread = threading.Thread(target=worker_wrapper)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        "message": "処理を開始しました。",
        "progress": post_process_progress
    })


@main.route("/post_process/folder_runs/<path:folder_alias>")
def folder_runs_api(folder_alias):
    """指定フォルダ（エイリアス）内のRunとサブフォルダ構造を返すAPI"""
    try:
        from ..modules.db_manager_helpers import get_folder_details_for_ui
        data = get_folder_details_for_ui(folder_alias)
        return jsonify(data)
    except Exception as e:
        current_app.logger.exception(f"Failed to fetch folder runs for {folder_alias}")
        return jsonify({"status": "error", "message": str(e)}), 500


@main.route("/post_process/apply_scope_profile", methods=["POST"])
def apply_scope_profile_api():
    """サブフォルダ単位でのプロファイル適用API"""
    try:
        data = request.json
        # folder_alias = data.get("folder_alias") # Not strictly needed if helpers handle logic, but good for validation
        
        # Sigle scope update (legacy/simple mode)
        if "scope" in data:
            items = [{
                "scope": data["scope"],
                "profile": data.get("profile"),
                "display": data.get("scope") # fallback
            }]
        # Bulk scope update
        elif "scope_profiles" in data:
             items = data["scope_profiles"]
        else:
            return jsonify({"status": "error", "message": "No scope specified"}), 400

        from ..modules.db_manager_helpers import apply_calibration_scope_bulk
        result = apply_calibration_scope_bulk(items)
        
        return jsonify({
            "status": "ok",
            "updated_scopes": result["updated_scopes"],
            "unmatched_scopes": result["unmatched_scopes"]
        })
        
    except Exception as e:
        current_app.logger.exception("Failed to apply scope profile")
        return jsonify({"status": "error", "message": str(e)}), 500


@main.route("/post_process/apply_run_profiles", methods=["POST"])
def apply_run_profiles_api():
    """選択されたRun IDへのプロファイル一括適用API"""
    try:
        payload = request.json
        run_ids = payload.get("run_ids", [])
        profile = payload.get("profile")
        
        if not run_ids:
             return jsonify({"status": "error", "message": "No run_ids provided"}), 400
             
        from ..modules.db_manager_helpers import apply_calibration_profile_to_runs
        count = apply_calibration_profile_to_runs(run_ids, profile)
        
        return jsonify({
            "status": "ok",
            "updated_run_ids": run_ids,
            "count": count,
            "applied_profile": profile
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@main.route("/api/video/set_metadata", methods=["POST"])
def api_video_set_metadata():
    """Videoのメタデータ（road_type, collection_year）を更新する。"""
    try:
        data = request.json
        run_ids = data.get("run_ids", [])
        
        # Check presence of keys to distinguish between None (unset) and Not Provided (no change)
        kwargs = {}
        if "road_type" in data:
            kwargs["road_type"] = data["road_type"]
        if "collection_year" in data:
            kwargs["collection_year"] = data["collection_year"]
            
        if not run_ids:
             return jsonify({"success": False, "error": "No run_ids provided"}), 400
             
        from ..modules.db_manager_helpers import update_video_metadata
        count = update_video_metadata(run_ids, **kwargs)

        folder_alias = data.get("folder_alias")
        if folder_alias:
            from ..modules.folder_config import update_folder_settings
            upload_folder = current_app.config['UPLOAD_FOLDER']
            alias_dir = os.path.join(upload_folder, folder_alias)
            
            settings_update = {}
            if "road_type" in kwargs:
                settings_update["road_type"] = kwargs["road_type"]
            if "collection_year" in kwargs:
                settings_update["process_year"] = kwargs["collection_year"]
                
            if settings_update:
                update_folder_settings(alias_dir, settings_update)
        
        return jsonify({
            "success": True,
            "updated_videos": count
        })
    except Exception as e:
        current_app.logger.exception("Failed to update video metadata")
        return jsonify({"success": False, "error": str(e)}), 500


@main.route("/post_process/calibration_preview/<int:run_id>")
def calibration_preview_api(run_id):
    """Run単位のキャリブレーションプレビュー画像を返す簡易API"""
    try:
        from ..modules.db_manager import get_run_video_info
        
        # 1. Get info
        info = get_run_video_info(run_id)
        if not info:
             return jsonify({"status": "error", "message": f"Run ID {run_id}が見つかりません"}), 404
             
        video_path = info.get("source_path")
        profile = info.get("calibration_profile")
        
        result = {
            "status": "ok",
            "run_id": run_id,
            "profile": profile,
            "type": "unknown", # Will update if loaded
            "frame": 0,
            "total_frames": info.get("total_frames", 0)
        }

        if not video_path or not os.path.exists(video_path):
             return jsonify({"status": "error", "message": "動画ファイルが見つかりません"}), 404

        # 2. Load Frame
        from ..modules.video_utils import load_video_frame
        frame = load_video_frame(video_path, 0)
        if frame is None:
             return jsonify({"status": "error", "message": "動画フレームの読み込みに失敗しました"}), 500
             
        # 3. Draw Lines if profile exists
        if profile:
             calib_dir = os.path.join(os.getenv("Opt_files", "output"), "calibrations")
             profile_path = os.path.join(calib_dir, f"{profile}.json")
             if os.path.exists(profile_path):
                 import json
                 with open(profile_path, 'r', encoding='utf-8') as f:
                     p_data = json.load(f)
                 
                 from .calibration import draw_calibration_lines
                 draw_calibration_lines(frame, p_data.get("lines", {}))
                 
                 result["type"] = p_data.get("calibration_type", "manual")
        
        # 4. Encode
        import cv2
        import base64
        _, buffer = cv2.imencode('.jpg', frame)
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        
        # Return data URI or base64 (Frontend expects src to be set directly? 
        # User JS: `calibPreviewImage.src = imageUrl;` 
        # If I return base64, I should prefix it or let frontend handle it.
        # User JS example: `const imageUrl = data.image_url || ...`
        # Let's return a data URI for simplicity.
        result["image_url"] = f"data:image/jpeg;base64,{img_base64}"
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.exception(f"Preview API failed for run {run_id}")
        return jsonify({"status": "error", "message": str(e)}), 500


@main.route("/api/traffic_count/<int:run_id>")
def api_traffic_count(run_id):
    """指定Run IDのカウント線通過車両集計結果を取得"""
    try:
        import sqlite3
        from ..modules.db_manager import MAIN_DB_PATH, configure_connection
        
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            configure_connection(conn)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            
            # TrafficCountテーブルからデータを取得
            c.execute("""
                SELECT 
                    line_name,
                    object_type,
                    direction,
                    count,
                    created_at
                FROM TrafficCount
                WHERE run_id = ?
                ORDER BY line_name, object_type, direction
            """, (run_id,))
            
            rows = c.fetchall()
            
            if not rows:
                return jsonify({
                    "status": "ok",
                    "run_id": run_id,
                    "has_data": False,
                    "message": "カウントデータが見つかりません",
                    "data": []
                })
            
            # データを整形
            results = []
            for row in rows:
                results.append({
                    "line_name": row["line_name"],
                    "object_type": row["object_type"],
                    "direction": row["direction"],
                    "count": row["count"],
                    "created_at": row["created_at"]
                })
            
            return jsonify({
                "status": "ok",
                "run_id": run_id,
                "has_data": True,
                "data": results
            })
            
    except Exception as e:
        current_app.logger.exception(f"Traffic count API failed for run {run_id}")
        return jsonify({"status": "error", "message": str(e)}), 500
