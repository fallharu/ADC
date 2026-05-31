from flask import render_template, request, jsonify, current_app, send_file, flash, redirect, url_for
import io
import pandas as pd
import sqlite3
import glob
import os
import re
import statistics
from . import main
from ..modules import db_manager as dbm
from ..modules.comparative_analysis import load_overtake_data, compute_statistics, run_tests, generate_plots
from ..modules.calibration_loader import load_calibration_json
from ..modules.manual_metrics import load_white_lines
from ..modules.white_line import get_line_x_at_y
from ..modules.db_manager import (
    MAIN_DB_PATH,
    configure_connection,
    list_detection_runs,
    resolve_output_root,
)
from ..modules.statistics_exporter import (
    generate_statistics_preview,
    export_statistics_workbook,
)

# Reuse checking logic if needed
def _ensure_database_ready():
    if not os.path.exists(MAIN_DB_PATH):
         return jsonify({"error": "Database not found"}), 503
    return None

@main.route("/analysis")
@main.route("/comparative_report")
def comparative_report_view():
    """Comparative Analysis Report Page"""
    try:
        from ..modules.comparative_report import get_available_years_and_road_types
        data = get_available_years_and_road_types()
        years = data.get("years", [])
        road_types = data.get("road_types", [])
        counts = data.get("counts", {})
        direction_counts = data.get("direction_counts", {})
        auto_count = data.get("auto_count", 0)
        manual_count = data.get("manual_count", 0)
        total_count = data.get("total_count", 0)
        
        # テンプレートで使いやすいようにフラットなキーも追加
        counts['B_count'] = direction_counts.get('B', 0)
        counts['F_count'] = direction_counts.get('F', 0)
    except Exception as e:
        current_app.logger.exception("Failed to load comparative report options")
        years = []
        road_types = []
        counts = {}
        auto_count = 0
        manual_count = 0
        total_count = 0
        
    return render_template(
        "comparative_report.html", 
        title="Comparative Analysis Report",
        years=years,
        road_types=road_types,
        counts=counts,
        auto_count=auto_count,
        manual_count=manual_count,
        total_count=total_count,
    )


@main.route("/api/comparative_report/generate", methods=["POST"])
def generate_comparative_report():
    """比較分析レポートを生成してJSONで返す"""
    try:
        from ..modules.comparative_report import (
            ComparativeAnalyzer, 
            compare_two_groups, 
            compare_multiple_groups
        )
        from dataclasses import asdict
        
        # リクエストデータの取得
        req_data = request.json
        collection_years = req_data.get("collection_years", [])
        road_types = req_data.get("road_types", [])
        directions = req_data.get("directions", [])
        metrics = req_data.get("metrics", [])
        exclude_outliers = bool(req_data.get("exclude_outliers", False))
        include_manual = req_data.get("include_manual", "both")  # "auto", "manual", or "both"
        
        if not collection_years or not road_types or not metrics:
            return jsonify({"success": False, "error": "必要なパラメータが不足しています"}), 400

        # データロード
        analyzer = ComparativeAnalyzer(MAIN_DB_PATH)
        analyzer.load_overtake_data(
            collection_years=collection_years,
            road_types=road_types,
            directions=directions,
            include_manual=include_manual,
        )
        
        # サマリー取得
        summary = analyzer.get_summary()

        # ヘルパー関数をインポート（トップレベルインポートが望ましいが、ここでも可）
        from ..modules.comparative_report import remove_outliers
        
        # 統計量計算
        statistics = {}
        for metric in metrics:
            # exclude_outliers フラグを渡す
            group_stats = analyzer.compute_statistics(metric, exclude_outliers=exclude_outliers)
            # dataclass to dict
            statistics[metric] = {
                k: asdict(v) if v else None 
                for k, v in group_stats.items()
            }
            # キーを文字列化 (jsで扱いやすくするため "widened_2024" 形式に変換)
            str_key_stats = {}
            for (rt, yr), val in group_stats.items():
                str_key_stats[f"{rt}_{yr}"] = asdict(val) if val else None
            statistics[metric] = str_key_stats

        # 統計検定
        tests = {}
        for metric in metrics:
            # グループごとのデータを抽出
            groups_data = {}
            for (rt, yr), metrics_obj in analyzer.data.items():
                val = getattr(metrics_obj, metric, [])
                if exclude_outliers:
                     val = remove_outliers(val)
                if val:
                    groups_data[f"{rt}_{yr}"] = val
            
            if len(groups_data) >= 2:
                result = None
                if len(groups_data) == 2:
                    keys = list(groups_data.keys())
                    result = compare_two_groups(
                        groups_data[keys[0]], 
                        groups_data[keys[1]], 
                        keys[0], 
                        keys[1]
                    )
                else:
                    result = compare_multiple_groups(groups_data)
                
                if result:
                    tests[metric] = asdict(result)

        return jsonify({
            "success": True,
            "summary": summary,
            "statistics": statistics,
            "tests": tests
        })

    except Exception as e:
        current_app.logger.exception("Report generation failed")
        return jsonify({"success": False, "error": str(e)}), 500



@main.route("/api/comparative_report/download", methods=["POST"])
def download_comparative_report():
    """比較分析レポート(Excel)をダウンロード"""
    try:
        from ..modules.comparative_report import ComparativeAnalyzer
        
        # リクエストデータの取得
        req_data = request.json
        collection_years = req_data.get("collection_years", [])
        road_types = req_data.get("road_types", [])
        directions = req_data.get("directions", [])
        metrics = req_data.get("metrics", [])
        include_manual = req_data.get("include_manual", "both")
        
        if not collection_years or not road_types or not metrics:
            return jsonify({"success": False, "error": "必要なパラメータが不足しています"}), 400

        # データロードと生成
        analyzer = ComparativeAnalyzer(MAIN_DB_PATH)
        analyzer.load_overtake_data(
            collection_years=collection_years,
            road_types=road_types,
            directions=directions,
            include_manual=include_manual,
        )
        
        excel_bytes = analyzer.generate_excel_bytes(metrics)
        
        return send_file(
            io.BytesIO(excel_bytes),
            as_attachment=True,
            download_name="comparative_report.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        current_app.logger.exception("Excel export failed")
        return jsonify({"success": False, "error": str(e)}), 500


@main.route("/api/comparative_report/ai_analysis", methods=["POST"])
def comparative_report_ai_analysis():
    """Generates AI insight for the comparative report."""
    try:
        from ..modules.ai_insight import generate_report_insight
        
        report_data = request.json
        if not report_data:
            return jsonify({"success": False, "error": "No report data provided"}), 400
            
        insight_text = generate_report_insight(report_data)
        
        return jsonify({
            "success": True, 
            "insight": insight_text
        })
    except Exception as e:
        current_app.logger.exception("AI Analysis failed")
        return jsonify({"success": False, "error": str(e)}), 500


@main.route("/global_summary")
def global_summary_view():
    """全Runの統計情報のサマリーページを表示する。"""
    return render_template("global_summary.html", title="Global Stats Summary")

@main.route("/statistics", methods=["GET", "POST"])
def statistics_view():
    """Statistics Page"""
    runs = []
    try:
        runs = list_detection_runs()
    except Exception as e:
        current_app.logger.error(f"Failed to list detection runs: {e}")

    preview = None
    selected_run_ids = []
    selected_mode = "lane"
    downward_only = False
    chart_json = None

    if request.method == "POST":
        # Form values are strings
        raw_ids = request.form.getlist("stats_run_ids")
        selected_run_ids = raw_ids # Keep as strings for template matching or convert
        
        selected_mode = request.form.get("stats_mode", "lane")
        downward_only = True if request.form.get("stats_downward_only") else False

        if raw_ids:
            try:
                # generate_statistics_preview accepts strings/ints for run_ids
                preview = generate_statistics_preview(
                    raw_ids,
                    mode=selected_mode,
                    downward_only=downward_only
                )
                if preview and preview.get("chart_configs"):
                    import json
                    chart_json = json.dumps({"charts": preview["chart_configs"]})
            except Exception as e:
                current_app.logger.exception(f"Statistics preview error: {e}")
                # Ideally flash a message
    
    return render_template(
        "statistics.html", 
        title="Statistics",
        runs=runs,
        preview=preview,
        selected_run_ids=selected_run_ids,
        selected_mode=selected_mode,
        downward_only=downward_only,
        chart_json=chart_json
    )

@main.route("/api/global_stats", methods=["GET"])
def global_stats_api():
    """全Runの統計情報（総追い越し数、自転車数、自動車数、平均速度等）を返すAPI。"""
    if not os.path.exists(MAIN_DB_PATH):
         return jsonify({"error": "Database not initialized"}), 503

    stats = {
        "overtakes": 0,
        "bicycles": 0,
        "cars": 0,
        "avg_overtakes_per_file": 0.0,
        "avg_speed_kmh": 0.0,
        "avg_overtake_speed_kmh": 0.0,
        "inner_ratio": 0.0,
        "outer_ratio": 0.0,
        "images": []
    }

    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            configure_connection(conn, mode="read")
            
            # 1. Total Overtakes
            cursor = conn.execute("SELECT COUNT(*) FROM OvertakeEvents")
            row = cursor.fetchone()
            if row:
                stats["overtakes"] = row[0]

            # 2. Total Bicycles
            cursor = conn.execute("SELECT COUNT(*) FROM Detection d LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id WHERE cm.class_name IN ('bicycle', 'cyclist')")
            row = cursor.fetchone()
            if row:
                stats["bicycles"] = row[0]

            # 3. Total Cars
            cursor = conn.execute("SELECT COUNT(*) FROM Detection d LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id WHERE cm.class_name IN ('car', 'truck', 'bus')")
            row = cursor.fetchone()
            if row:
                stats["cars"] = row[0]

            # 4. Avg Overtakes per File
            cursor = conn.execute("SELECT COUNT(*) FROM ProcessLog")
            row = cursor.fetchone()
            total_runs = row[0] if row else 0
            if total_runs > 0:
                stats["avg_overtakes_per_file"] = round(stats["overtakes"] / total_runs, 2)

            # 5. Avg Speed (All Detections)
            cursor = conn.execute("SELECT AVG(speed_km_h) FROM Detection WHERE speed_km_h > 0")
            row = cursor.fetchone()
            if row and row[0] is not None:
                stats["avg_speed_kmh"] = round(row[0], 2)

            # 6. Avg Overtake Speed
            query_overtake_speed = """
                SELECT AVG(d.speed_km_h) 
                FROM OvertakeEvents o
                JOIN Detection d ON o.run_id = d.run_id 
                    AND o.event_frame_num = d.frame_num 
                    AND o.overtaker_auto_id = d.auto_id
                WHERE d.speed_km_h > 0
            """
            cursor = conn.execute(query_overtake_speed)
            row = cursor.fetchone()
            if row and row[0] is not None:
                stats["avg_overtake_speed_kmh"] = round(row[0], 2)

            # Inner/Outer Counts
            query_lane_flag = """
                SELECT d.lane_position_flag, COUNT(*)
                FROM OvertakeEvents o
                JOIN Detection d ON o.run_id = d.run_id 
                    AND o.event_frame_num = d.frame_num 
                    AND o.overtaker_auto_id = d.auto_id
                GROUP BY d.lane_position_flag
            """
            cursor = conn.execute(query_lane_flag)
            rows = cursor.fetchall()
            inner_count = 0
            outer_count = 0
            for flag, count in rows:
                if flag == "+":
                    inner_count += count
                elif flag == "-":
                    outer_count += count
            
            total_classified = inner_count + outer_count
            if total_classified > 0:
                stats["inner_ratio"] = round((inner_count / total_classified) * 100, 1)
                stats["outer_ratio"] = round((outer_count / total_classified) * 100, 1)

            # 7. Collect all overtake snapshots
            opt_root = resolve_output_root(conn)
            # Support both .jpg and .png (recursive search)
            snapshots_jpg = glob.glob(os.path.join(opt_root, "**", "overtake_snapshots", "*.jpg"), recursive=True)
            snapshots_png = glob.glob(os.path.join(opt_root, "**", "overtake_snapshots", "*.png"), recursive=True)
            files = snapshots_jpg + snapshots_png
            
            # Sort by filename (which starts with overtake_000000...) ensures frame order
            files.sort(key=lambda x: os.path.basename(x))
            
            abs_opt = os.path.abspath(opt_root)
            image_list = []
            for f in files:
                abs_f = os.path.abspath(f)
                if abs_f.startswith(abs_opt):
                    rel = os.path.relpath(abs_f, abs_opt).replace(os.path.sep, '/')
                    image_list.append(rel)
            stats["images"] = image_list

    except Exception as e:
        current_app.logger.exception("Failed to fetch global stats")
        return jsonify({"error": str(e)}), 500

    return jsonify(stats)


@main.route("/overtake_gallery")
def overtake_gallery():
    """追い越し写真ギャラリーページを表示する。"""
    opt_root = resolve_output_root()
    
    # ソートパラメータ取得
    sort_by = request.args.get("sort", "name")  # name, time
    sort_order = request.args.get("order", "asc")  # asc, desc
    
    # Collect all overtake snapshots (recursive search)
    snapshots_jpg = glob.glob(os.path.join(opt_root, "**", "overtake_snapshots", "*.jpg"), recursive=True)
    snapshots_png = glob.glob(os.path.join(opt_root, "**", "overtake_snapshots", "*.png"), recursive=True)
    files = snapshots_jpg + snapshots_png
    
    # ソート処理
    if sort_by == "time":
        # 作成時間でソート
        files.sort(key=lambda x: os.path.getmtime(x), reverse=(sort_order == "desc"))
    else:
        # 名前でソート（デフォルト）
        files.sort(key=lambda x: os.path.basename(x), reverse=(sort_order == "desc"))
    
    abs_opt = os.path.abspath(opt_root)
    image_list = []
    for f in files:
        abs_f = os.path.abspath(f)
        if abs_f.startswith(abs_opt):
            rel = os.path.relpath(abs_f, abs_opt).replace(os.path.sep, '/')
            image_list.append(rel)
    
    # Get overtake event count from database
    overtake_event_count = 0
    manual_event_count = 0
    overtake_stats = {
        "widened": {
            "count": 0,
            "center_ratio": None,
            "white_ratio": None,
            "clearance": {"min": None, "median": None, "max": None},
            "line": {"min": None, "median": None, "max": None},
        },
        "unwidened": {
            "count": 0,
            "center_ratio": None,
            "white_ratio": None,
            "clearance": {"min": None, "median": None, "max": None},
            "line": {"min": None, "median": None, "max": None},
        },
    }
    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            configure_connection(conn, mode="read")
            # OvertakeEvents count (automatic detection)
            cursor = conn.execute("SELECT COUNT(*) FROM OvertakeEvents")
            row = cursor.fetchone()
            if row:
                overtake_event_count = row[0]
            # ManualOvertakeEvents count (manual annotation)
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM ManualOvertakeEvents")
                row = cursor.fetchone()
                if row:
                    manual_event_count = row[0]
            except sqlite3.OperationalError:
                pass  # Table may not exist

            conn.row_factory = sqlite3.Row
            stats_query = """
                SELECT
                    v.road_type,
                    o.clearance_distance_m AS event_clearance_m,
                    o.line_distance_m AS event_line_m,
                    car.clearance_distance_m AS car_clearance_m,
                    bike.clearance_distance_m AS bike_clearance_m,
                    car.line_distance_m AS car_line_m,
                    bike.line_distance_m AS bike_line_m,
                    car.center_line_overtake_status AS car_center_status,
                    bike.white_line_overtake_status AS bike_white_status,
                    COALESCE(car.travel_direction, bike.travel_direction) AS travel_direction,
                    car.l_line_cross_m AS car_l_cross_m,
                    car.r_line_cross_m AS car_r_cross_m,
                    bike.l_line_cross_m AS bike_l_cross_m,
                    bike.r_line_cross_m AS bike_r_cross_m
                FROM OvertakeEvents o
                JOIN ProcessLog p ON o.run_id = p.run_id
                JOIN Video v ON p.video_id = v.video_id
                LEFT JOIN Detection car ON o.overtaker_auto_id = car.auto_id
                LEFT JOIN Detection bike ON o.overtaken_auto_id = bike.auto_id
            """
            rows = conn.execute(stats_query).fetchall()

            widened_center = 0
            widened_white = 0
            unwidened_center = 0
            unwidened_white = 0
            widened_clearance = []
            widened_line = []
            unwidened_clearance = []
            unwidened_line = []

            for row in rows:
                road_type = (row["road_type"] or "").strip()
                if road_type not in ("拡幅", "未拡幅"):
                    continue

                bucket = "widened" if road_type == "拡幅" else "unwidened"
                overtake_stats[bucket]["count"] += 1

                direction = str(row["travel_direction"] or "").strip().upper()
                if direction == "F":
                    center_cross = row["car_r_cross_m"]
                    white_cross = row["bike_l_cross_m"]
                else:
                    center_cross = row["car_l_cross_m"]
                    white_cross = row["bike_r_cross_m"]

                center_status = (row["car_center_status"] or "").strip()
                white_status = (row["bike_white_status"] or "").strip()

                center_hit = False
                white_hit = False
                if center_status:
                    center_hit = center_status == "中央線越え"
                elif center_cross is not None and center_cross > 0:
                    center_hit = True

                if white_status:
                    white_hit = white_status == "白線越え"
                elif white_cross is not None and white_cross > 0:
                    white_hit = True

                if center_hit:
                    if bucket == "widened":
                        widened_center += 1
                    else:
                        unwidened_center += 1
                if white_hit:
                    if bucket == "widened":
                        widened_white += 1
                    else:
                        unwidened_white += 1

                clearance_val = row["event_clearance_m"]
                if clearance_val is None:
                    clearance_val = row["car_clearance_m"]
                if clearance_val is None:
                    clearance_val = row["bike_clearance_m"]

                line_val = row["event_line_m"]
                if line_val is None:
                    line_val = row["bike_line_m"]
                if line_val is None:
                    line_val = row["car_line_m"]

                if bucket == "widened":
                    if clearance_val is not None:
                        widened_clearance.append(clearance_val)
                    if line_val is not None:
                        widened_line.append(line_val)
                else:
                    if clearance_val is not None:
                        unwidened_clearance.append(clearance_val)
                    if line_val is not None:
                        unwidened_line.append(line_val)

            def _ratio(count: int, total: int):
                if total <= 0:
                    return None
                return round((count / total) * 100, 1)

            overtake_stats["widened"]["center_ratio"] = _ratio(
                widened_center, overtake_stats["widened"]["count"]
            )
            overtake_stats["widened"]["white_ratio"] = _ratio(
                widened_white, overtake_stats["widened"]["count"]
            )
            overtake_stats["unwidened"]["center_ratio"] = _ratio(
                unwidened_center, overtake_stats["unwidened"]["count"]
            )
            overtake_stats["unwidened"]["white_ratio"] = _ratio(
                unwidened_white, overtake_stats["unwidened"]["count"]
            )

            if widened_clearance:
                overtake_stats["widened"]["clearance"] = {
                    "min": min(widened_clearance),
                    "median": statistics.median(widened_clearance),
                    "max": max(widened_clearance),
                }

            if widened_line:
                overtake_stats["widened"]["line"] = {
                    "min": min(widened_line),
                    "median": statistics.median(widened_line),
                    "max": max(widened_line),
                }

            if unwidened_clearance:
                overtake_stats["unwidened"]["clearance"] = {
                    "min": min(unwidened_clearance),
                    "median": statistics.median(unwidened_clearance),
                    "max": max(unwidened_clearance),
                }

            if unwidened_line:
                overtake_stats["unwidened"]["line"] = {
                    "min": min(unwidened_line),
                    "median": statistics.median(unwidened_line),
                    "max": max(unwidened_line),
                }
    except Exception as e:
        current_app.logger.exception("Failed to fetch overtake event counts")
    
    return render_template(
        "overtake_gallery.html",
        images=image_list,
        total_count=len(image_list),
        overtake_event_count=overtake_event_count,
        manual_event_count=manual_event_count,
        overtake_stats=overtake_stats,
        output_root=opt_root,
        current_sort=sort_by,
        current_order=sort_order,
    )


@main.route("/reset_overtake_photos", methods=["POST"])
def reset_overtake_photos():
    """追い越し写真を全て削除する。"""
    import shutil
    
    opt_root = resolve_output_root()
    deleted_count = 0
    
    # Find all overtake_snapshots directories recursively
    snapshot_dirs = glob.glob(os.path.join(opt_root, "**", "overtake_snapshots"), recursive=True)
    
    for snapshot_dir in snapshot_dirs:
        if os.path.isdir(snapshot_dir):
            try:
                # Delete all files in the directory
                for f in os.listdir(snapshot_dir):
                    file_path = os.path.join(snapshot_dir, f)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        deleted_count += 1
            except Exception as e:
                current_app.logger.exception(f"Failed to delete files in {snapshot_dir}")
    
    flash(f"{deleted_count} 枚の追い越し写真を削除しました。", "success")
    return redirect(url_for("main.overtake_gallery"))


@main.route("/regenerate_overtake_photos", methods=["POST"])
def regenerate_overtake_photos():
    """追い越し写真をDBのイベントから再生成する。"""
    from ..modules.overtake import _export_overtake_snapshots
    
    # Get source parameter (auto, manual, or both)
    source = request.form.get("source", "both")
    
    total_generated = 0
    auto_generated = 0
    manual_generated = 0
    errors = []
    
    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            configure_connection(conn, mode="read")
            
            # Process automatic overtake events
            if source in ("auto", "both"):
                run_ids_query = """
                    SELECT DISTINCT o.run_id, p.output_folder, v.filename, v.source_path, 
                           p.folder_alias, p.calibration_profile
                    FROM OvertakeEvents o
                    JOIN ProcessLog p ON o.run_id = p.run_id
                    JOIN Video v ON p.video_id = v.video_id
                """
                runs = conn.execute(run_ids_query).fetchall()
                
                for run_row in runs:
                    run_id, output_folder, video_filename, source_path, folder_alias, calibration_profile = run_row
                    
                    events_query = """
                        SELECT o.event_frame_num, o.overtaker_group_id, o.overtaken_group_id,
                               o.overtaker_auto_id, o.overtaken_auto_id,
                               o.clearance_distance_cm, o.clearance_distance_m,
                               o.approach_distance_m
                        FROM OvertakeEvents o
                        WHERE o.run_id = ?
                    """
                    events = conn.execute(events_query, (run_id,)).fetchall()
                    
                    if not events:
                        continue
                    
                    snapshot_requests = []
                    for event in events:
                        frame_num, overtaker_gid, overtaken_gid, overtaker_aid, overtaken_aid, \
                            clearance_cm, clearance_m, approach_m = event
                        
                        car_box = None
                        bike_box = None
                        car_measure = None
                        bike_measure = None
                        
                        for (auto_id, role) in [(overtaker_aid, "car"), (overtaken_aid, "bike")]:
                            if auto_id:
                                det_query = """
                                    SELECT x1, y1, x2, y2, measure_x, measure_y
                                    FROM Detection WHERE auto_id = ?
                                """
                                det_row = conn.execute(det_query, (auto_id,)).fetchone()
                                if det_row:
                                    x1, y1, x2, y2, mx, my = det_row
                                    if all(v is not None for v in (x1, y1, x2, y2)):
                                        if role == "car":
                                            car_box = (float(x1), float(y1), float(x2), float(y2))
                                        else:
                                            bike_box = (float(x1), float(y1), float(x2), float(y2))
                                    if mx is not None and my is not None:
                                        if role == "car":
                                            car_measure = (float(mx), float(my))
                                        else:
                                            bike_measure = (float(mx), float(my))
                        
                        snapshot_requests.append({
                            "frame": frame_num,
                            "car_group": overtaker_gid,
                            "bike_group": overtaken_gid,
                            "car_box": car_box,
                            "bike_box": bike_box,
                            "car_measure": car_measure,
                            "bike_measure": bike_measure,
                            "clearance_cm": clearance_cm,
                            "clearance_m": clearance_m,
                            "approach_m": approach_m,
                        })
                    
                    if snapshot_requests:
                        try:
                            generated = _export_overtake_snapshots(
                                run_id=run_id,
                                snapshot_requests=snapshot_requests,
                                output_folder=output_folder,
                                video_filename=video_filename,
                                source_path=source_path,
                                folder_alias=folder_alias,
                                calibration_profile=calibration_profile,
                            )
                            auto_generated += generated or 0
                            
                            # Create JSON file with event data
                            if generated and generated > 0:
                                import json as json_module
                                snapshot_dir = os.path.join(output_folder, "overtake_snapshots")
                                os.makedirs(snapshot_dir, exist_ok=True)
                                json_path = os.path.join(snapshot_dir, f"overtake_events_run{run_id}.json")
                                json_data = {
                                    "run_id": run_id,
                                    "video_filename": video_filename,
                                    "source_type": "auto",
                                    "generated_count": generated,
                                    "events": [
                                        {
                                            "frame": req["frame"],
                                            "car_group_id": req["car_group"],
                                            "bike_group_id": req["bike_group"],
                                            "clearance_cm": req.get("clearance_cm"),
                                            "clearance_m": req.get("clearance_m"),
                                            "approach_m": req.get("approach_m"),
                                        }
                                        for req in snapshot_requests
                                    ]
                                }
                                with open(json_path, "w", encoding="utf-8") as jf:
                                    json_module.dump(json_data, jf, ensure_ascii=False, indent=2)
                        except Exception as e:
                            errors.append(f"Auto Run {run_id}: {str(e)}")
                            current_app.logger.exception(f"Failed to regenerate snapshots for run {run_id}")
            
            # Process manual overtake events
            if source in ("manual", "both"):
                try:
                    manual_runs_query = """
                        SELECT DISTINCT m.run_id, p.output_folder, v.filename, v.source_path, 
                               p.folder_alias, p.calibration_profile
                        FROM ManualOvertakeEvents m
                        JOIN ProcessLog p ON m.run_id = p.run_id
                        JOIN Video v ON p.video_id = v.video_id
                    """
                    manual_runs = conn.execute(manual_runs_query).fetchall()
                    
                    for run_row in manual_runs:
                        run_id, output_folder, video_filename, source_path, folder_alias, calibration_profile = run_row
                        
                        events_query = """
                            SELECT m.frame_num, m.overtaker_group_id, m.overtaken_group_id,
                                   m.clearance_distance_cm, m.clearance_distance_m,
                                   m.approach_distance_m,
                                   m.overtaker_x1, m.overtaker_y1, m.overtaker_x2, m.overtaker_y2,
                                   m.overtaken_x1, m.overtaken_y1, m.overtaken_x2, m.overtaken_y2,
                                   m.overtaker_measure_x, m.overtaker_measure_y,
                                   m.overtaken_measure_x, m.overtaken_measure_y
                            FROM ManualOvertakeEvents m
                            WHERE m.run_id = ?
                        """
                        events = conn.execute(events_query, (run_id,)).fetchall()
                        
                        if not events:
                            continue
                        
                        snapshot_requests = []
                        for event in events:
                            (frame_num, overtaker_gid, overtaken_gid,
                             clearance_cm, clearance_m, approach_m,
                             ot_x1, ot_y1, ot_x2, ot_y2,
                             on_x1, on_y1, on_x2, on_y2,
                             ot_mx, ot_my, on_mx, on_my) = event
                            
                            car_box = None
                            bike_box = None
                            car_measure = None
                            bike_measure = None
                            
                            if all(v is not None for v in (ot_x1, ot_y1, ot_x2, ot_y2)):
                                car_box = (float(ot_x1), float(ot_y1), float(ot_x2), float(ot_y2))
                            if all(v is not None for v in (on_x1, on_y1, on_x2, on_y2)):
                                bike_box = (float(on_x1), float(on_y1), float(on_x2), float(on_y2))
                            if ot_mx is not None and ot_my is not None:
                                car_measure = (float(ot_mx), float(ot_my))
                            if on_mx is not None and on_my is not None:
                                bike_measure = (float(on_mx), float(on_my))
                            
                            snapshot_requests.append({
                                "frame": frame_num,
                                "car_group": overtaker_gid,
                                "bike_group": overtaken_gid,
                                "car_box": car_box,
                                "bike_box": bike_box,
                                "car_measure": car_measure,
                                "bike_measure": bike_measure,
                                "clearance_cm": clearance_cm,
                                "clearance_m": clearance_m,
                                "approach_m": approach_m,
                            })
                        
                        if snapshot_requests:
                            try:
                                generated = _export_overtake_snapshots(
                                    run_id=run_id,
                                    snapshot_requests=snapshot_requests,
                                    output_folder=output_folder,
                                    video_filename=video_filename,
                                    source_path=source_path,
                                    folder_alias=folder_alias,
                                    calibration_profile=calibration_profile,
                                )
                                manual_generated += generated or 0
                                
                                # Create JSON file with event data for manual events
                                if generated and generated > 0:
                                    import json as json_module
                                    snapshot_dir = os.path.join(output_folder, "overtake_snapshots")
                                    os.makedirs(snapshot_dir, exist_ok=True)
                                    json_path = os.path.join(snapshot_dir, f"manual_overtake_events_run{run_id}.json")
                                    json_data = {
                                        "run_id": run_id,
                                        "video_filename": video_filename,
                                        "source_type": "manual",
                                        "generated_count": generated,
                                        "events": [
                                            {
                                                "frame": req["frame"],
                                                "car_group_id": req["car_group"],
                                                "bike_group_id": req["bike_group"],
                                                "clearance_cm": req.get("clearance_cm"),
                                                "clearance_m": req.get("clearance_m"),
                                                "approach_m": req.get("approach_m"),
                                            }
                                            for req in snapshot_requests
                                        ]
                                    }
                                    with open(json_path, "w", encoding="utf-8") as jf:
                                        json_module.dump(json_data, jf, ensure_ascii=False, indent=2)
                            except Exception as e:
                                errors.append(f"Manual Run {run_id}: {str(e)}")
                                current_app.logger.exception(f"Failed to regenerate manual snapshots for run {run_id}")
                except sqlite3.OperationalError:
                    # ManualOvertakeEvents table may not exist
                    pass
    
    except Exception as e:
        current_app.logger.exception("Failed to regenerate overtake photos")
        flash(f"再生成に失敗しました: {e}", "danger")
        return redirect(url_for("main.overtake_gallery"))
    
    total_generated = auto_generated + manual_generated
    
    # Build result message
    msg_parts = []
    if source in ("auto", "both") and auto_generated > 0:
        msg_parts.append(f"自動検出: {auto_generated}枚")
    if source in ("manual", "both") and manual_generated > 0:
        msg_parts.append(f"手動追加: {manual_generated}枚")
    
    if total_generated > 0:
        msg = f"追い越し写真を再生成しました（{', '.join(msg_parts)}）"
        if errors:
            flash(f"{msg}。エラー: {len(errors)}件", "warning")
        else:
            flash(msg, "success")
    else:
        flash("再生成対象のイベントがありませんでした。", "info")
    
    return redirect(url_for("main.overtake_gallery"))


@main.route("/export_statistics", methods=["POST"])
def export_statistics():
    """統計情報をExcel形式でエクスポートする。"""
    try:
        import flask
        
        # Form values
        raw_ids = request.form.getlist("stats_run_ids")
        if not raw_ids:
            # Fallback to all runs if nothing selected (or should we error?)
            # Existing behavior was "all", but context suggests selection.
            # Let's default to all only if explicitly requested or if list is empty?
            # Actually, if the form is empty, it means user selected nothing.
            # But strictly speaking, the user might want "export all".
            # For now, if empty, we grab all.
             runs = list_detection_runs()
             run_ids = [r["run_id"] for r in runs]
        else:
            run_ids = raw_ids

        mode = request.form.get("stats_mode", "lane")
        downward_only = True if request.form.get("stats_downward_only") else False
        
        output_file = export_statistics_workbook(
            run_ids=run_ids,
            downward_only=downward_only,
            mode=mode
        )
        filename = os.path.basename(output_file)
        
        return flask.send_file(
            output_file, 
            as_attachment=True, 
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        current_app.logger.exception("Export failed")
        flash(f"エクスポートに失敗しました: {e}", "danger")
        if request.referrer:
            return redirect(request.referrer)

@main.route("/comparative_analysis")
def comparative_analysis_view():
    """Render a simple page to run comparative analysis and specify source/output folders."""
    return render_template("comparative_analysis.html")
        

# ---------------------------------------------------------------------------
# Kanaoka Export API
# ---------------------------------------------------------------------------
@main.route("/api/export_kanaoka", methods=["POST"])
@main.route("/export_kanaoka", methods=["POST"])
def export_kanaoka():
    """金岡出力 (Overtake Time-Series Export)"""
    try:
        from ..modules.kanaoka_export import generate_kanaoka_excel
        from datetime import datetime
        
        excel_bytes = generate_kanaoka_excel(MAIN_DB_PATH)
        filename = f"kanaoka_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return send_file(
            io.BytesIO(excel_bytes),
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        current_app.logger.error(f"Kanaoka Export failed: {e}", exc_info=True)
@main.route("/export_kanaoka_csv", methods=["POST"])
def export_kanaoka_csv():
    """金岡出力 (CSV)"""
    try:
        from ..modules.kanaoka_export import generate_kanaoka_csv
        from datetime import datetime
        
        csv_bytes = generate_kanaoka_csv(MAIN_DB_PATH)
        filename = f"kanaoka_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return send_file(
            io.BytesIO(csv_bytes),
            as_attachment=True,
            download_name=filename,
            mimetype="text/csv"
        )
    except Exception as e:
        current_app.logger.error(f"Kanaoka CSV Export failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

@main.route("/export_overtake_summary_csv", methods=["POST"])
def export_overtake_summary_csv():
    """追い越し有まとめ (CSV)"""
    try:
        from ..modules.summary_csv_export import generate_summary_csv
        from datetime import datetime
        
        csv_bytes = generate_summary_csv(MAIN_DB_PATH)
        filename = f"overtake_summary_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return send_file(
            io.BytesIO(csv_bytes),
            as_attachment=True,
            download_name=filename,
            mimetype="text/csv"
        )
    except Exception as e:
        current_app.logger.error(f"Overtake Summary CSV Export failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

@main.route("/export_overtake_pairs_csv", methods=["POST"])
def export_overtake_pairs_csv():
    """追い越し/追い越されペアの1行CSV"""
    try:
        from ..modules.overtake_pair_export import generate_overtake_pair_csv
        from datetime import datetime

        csv_bytes = generate_overtake_pair_csv(MAIN_DB_PATH)
        filename = f"overtake_pairs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return send_file(
            io.BytesIO(csv_bytes),
            as_attachment=True,
            download_name=filename,
            mimetype="text/csv"
        )
    except Exception as e:
        current_app.logger.error(f"Overtake Pair CSV Export failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

@main.route("/export_full_data", methods=["POST"])
def export_full_data():
    """全データ出力 (Full Data CSV Export)"""
    try:
        from ..modules.full_csv_export import generate_full_csv
        from datetime import datetime
        
        csv_bytes = generate_full_csv(MAIN_DB_PATH)
        filename = f"overtake_full_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return send_file(
            io.BytesIO(csv_bytes),
            as_attachment=True,
            download_name=filename,
            mimetype="text/csv"
        )
    except Exception as e:
        current_app.logger.error(f"Full CSV Export failed: {e}", exc_info=True)
        # Using jsonify for consistent error response instead of missing response_error
        return jsonify({"success": False, "error": str(e)}), 500

# ---------------------------------------------------------------------------
# Comparative Analysis Execution API
@main.route("/api/comparative_analysis/run", methods=["POST"])
def comparative_analysis_run():
    """Run comparative analysis on source data folder and output results to a folder.
    Expected JSON payload:
    {
        "source_folder": "<absolute path>",
        "output_folder": "<absolute path>"
    }
    """
    try:
        data = request.json
        source_folder = data.get("source_folder")
        output_folder = data.get("output_folder")
        if not source_folder or not output_folder:
            return jsonify({"ok": False, "error": "source_folder and output_folder are required"}), 400

        # Load data
        df = load_overtake_data(source_folder)

        # Compute summary statistics
        summary_df = compute_statistics(df)

        # Run statistical tests
        tests = run_tests(df)

        # Generate plots
        generate_plots(df, output_folder)

        # Save summary and tests to Excel
        excel_path = os.path.join(output_folder, "analysis_report.xlsx")
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="Summary", index=False)
            # Convert tests dict to DataFrame for Excel
            if tests:
                tests_df = pd.DataFrame.from_dict(tests, orient="index")
                tests_df.to_excel(writer, sheet_name="Statistical_Tests")

        return jsonify({"ok": True, "message": "Comparative analysis completed", "excel_path": excel_path})
    except Exception as e:
        current_app.logger.exception("Comparative analysis failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@main.route("/api/folder_summary")
def folder_summary_api():
    """フォルダごとの交通量・追い越し数の集計を返すAPI。"""
    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            configure_connection(conn)
            
            # フォルダ一覧を取得
            folders_query = """
                SELECT DISTINCT folder_alias 
                FROM ProcessLog 
                WHERE folder_alias IS NOT NULL AND folder_alias != ''
                ORDER BY folder_alias
            """
            folders = [row[0] for row in conn.execute(folders_query).fetchall()]
            
            results = []
            for folder in folders:
                # 該当フォルダのrun_ids取得
                run_ids_query = """
                    SELECT run_id FROM ProcessLog WHERE folder_alias = ?
                """
                run_ids = [row[0] for row in conn.execute(run_ids_query, (folder,)).fetchall()]
                
                if not run_ids:
                    continue
                
                placeholders = ",".join("?" * len(run_ids))
                
                # 交通量カウント集計
                traffic_query = f"""
                    SELECT object_type, SUM(count) as total
                    FROM TrafficCount
                    WHERE run_id IN ({placeholders})
                    GROUP BY object_type
                """
                traffic_counts = {"車": 0, "自転車": 0}
                for row in conn.execute(traffic_query, run_ids).fetchall():
                    traffic_counts[row[0]] = row[1]
                
                # 追い越し数集計
                overtake_query = f"""
                    SELECT COUNT(*) FROM OvertakeEvents
                    WHERE run_id IN ({placeholders})
                """
                overtake_count = conn.execute(overtake_query, run_ids).fetchone()[0] or 0
                
                results.append({
                    "folder": folder,
                    "run_count": len(run_ids),
                    "car_count": traffic_counts.get("車", 0),
                    "bicycle_count": traffic_counts.get("自転車", 0),
                    "overtake_count": overtake_count,
                })
            
            return jsonify({"ok": True, "data": results})
    except Exception as e:
        current_app.logger.exception("Folder summary API failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@main.route("/api/overtake_photo/detail")
def overtake_photo_detail():
    """追い越し写真のファイル名から関連DBデータを取得するAPI"""
    filename = request.args.get("filename", "")
    
    if not filename:
        return jsonify({"ok": False, "error": "ファイル名が指定されていません"}), 400
    
    # ファイル名パターン: overtake_{frame:06d}_car{car_group}_bike{bike_group}_{index:02d}.png
    # 例: overtake_000380_car35_bike11_01.png
    pattern = r"overtake_(\d+)_car(\d+)_bike(\d+)_\d+\.png"
    match = re.match(pattern, os.path.basename(filename))
    
    if not match:
        return jsonify({"ok": False, "error": "ファイル名の形式が不正です"}), 400
    
    frame_num = int(match.group(1))
    car_group_id = int(match.group(2))
    bike_group_id = int(match.group(3))
    
    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            configure_connection(conn, mode="read")

            detection_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(Detection)").fetchall()
            }
            has_center_status = "center_line_overtake_status" in detection_columns
            has_white_status = "white_line_overtake_status" in detection_columns
            
            run_id = None
            abs_file = filename
            opt_root = resolve_output_root(conn)
            if not os.path.isabs(abs_file):
                abs_file = os.path.abspath(os.path.join(opt_root, filename))
            else:
                abs_file = os.path.abspath(abs_file)

            output_rows = conn.execute(
                "SELECT run_id, output_folder FROM ProcessLog "
                "WHERE output_folder IS NOT NULL AND output_folder != ''"
            ).fetchall()
            best_match = None
            for row in output_rows:
                output_folder = os.path.abspath(row["output_folder"])
                if abs_file.startswith(output_folder):
                    if best_match is None or len(output_folder) > best_match[0]:
                        best_match = (len(output_folder), row["run_id"])
            if best_match:
                run_id = best_match[1]

            if run_id is None:
                path_parts = filename.replace("\\", "/").split("/")
                if "overtake_snapshots" in path_parts:
                    idx = path_parts.index("overtake_snapshots")
                    if idx > 0:
                        find_run_sql = """
                            SELECT run_id FROM ProcessLog
                            WHERE output_folder LIKE ?
                            ORDER BY run_id DESC LIMIT 1
                        """
                        run_row = conn.execute(find_run_sql, (f"%{path_parts[idx-1]}%",)).fetchone()
                        if run_row:
                            run_id = run_row["run_id"]
            
            # OvertakeEventsからイベントデータを取得
            event_data = None
            event_sql = """
                SELECT 
                    run_id, event_frame_num,
                    overtaker_group_id, overtaken_group_id,
                    overtaker_auto_id, overtaken_auto_id,
                    approach_distance_m, clearance_distance_m, clearance_distance_cm,
                    l_line_distance_m, r_line_distance_m, line_distance_m
                FROM OvertakeEvents
                WHERE event_frame_num = ? 
                  AND overtaker_group_id = ? 
                  AND overtaken_group_id = ?
            """
            event_row = conn.execute(event_sql, (frame_num, car_group_id, bike_group_id)).fetchone()
            
            if event_row:
                event_data = dict(event_row)
                run_id = event_row["run_id"]
            else:
                event_data = {
                    "run_id": run_id,
                    "event_frame_num": frame_num,
                    "overtaker_group_id": car_group_id,
                    "overtaken_group_id": bike_group_id,
                    "overtaker_auto_id": None,
                    "overtaken_auto_id": None,
                    "approach_distance_m": None,
                    "clearance_distance_m": None,
                    "clearance_distance_cm": None,
                    "line_distance_m": None,
                }

            check_sheet_event = None
            manual_event = None
            if run_id is not None:
                manual_sql = """
                    SELECT
                        manual_event_id,
                        notes,
                        clearance_distance_m,
                        clearance_distance_cm,
                        approach_distance_m,
                        overtaker_line_distance_m,
                        overtaken_line_distance_m
                    FROM ManualOvertakeEvents
                    WHERE run_id = ?
                      AND frame_num = ?
                      AND overtaker_group_id = ?
                      AND overtaken_group_id = ?
                    ORDER BY manual_event_id DESC
                """
                for row in conn.execute(
                    manual_sql, (run_id, frame_num, car_group_id, bike_group_id)
                ).fetchall():
                    payload = dict(row)
                    notes = (payload.get("notes") or "").strip()
                    if notes == "check_sheet_import":
                        if check_sheet_event is None:
                            check_sheet_event = payload
                    else:
                        if manual_event is None:
                            manual_event = payload

            class_name_map = {
                0: "person",
                1: "bicycle",
                2: "car",
                3: "motorcycle",
                5: "bus",
                7: "truck",
            }

            # 追い越し車（車）のDetectionデータを取得
            car_detection = None
            if event_row and event_row["overtaker_auto_id"]:
                car_center_col = (
                    "d.center_line_overtake_status"
                    if has_center_status
                    else "NULL AS center_line_overtake_status"
                )
                car_white_col = (
                    "d.white_line_overtake_status"
                    if has_white_status
                    else "NULL AS white_line_overtake_status"
                )
                car_sql = """
                    SELECT 
                        d.auto_id, d.frame_num, d.group_id, d.class_id,
                        d.x1, d.y1, d.x2, d.y2, d.measure_x, d.measure_y,
                        cm.class_name, d.speed_km_h, d.confidence,
                        d.front_distance_m, d.approach_distance_m,
                        d.clearance_distance_m, d.clearance_distance_cm,
                        d.line_distance_m, d.travel_direction, d.lane_position_flag,
                        d.l_line_cross_m, d.r_line_cross_m,
                        {center_col}, {white_col}
                    FROM Detection d
                    LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
                    WHERE d.auto_id = ?
                """
                car_row = conn.execute(
                    car_sql.format(center_col=car_center_col, white_col=car_white_col),
                    (event_row["overtaker_auto_id"],),
                ).fetchone()
                if car_row:
                    car_detection = dict(car_row)
                    if not car_detection.get("class_name"):
                        cid = car_detection.get("class_id")
                        car_detection["class_name"] = class_name_map.get(cid)
            elif run_id is not None:
                car_center_col = (
                    "d.center_line_overtake_status"
                    if has_center_status
                    else "NULL AS center_line_overtake_status"
                )
                car_white_col = (
                    "d.white_line_overtake_status"
                    if has_white_status
                    else "NULL AS white_line_overtake_status"
                )
                car_sql = """
                    SELECT 
                        d.auto_id, d.frame_num, d.group_id, d.class_id,
                        d.x1, d.y1, d.x2, d.y2, d.measure_x, d.measure_y,
                        cm.class_name, d.speed_km_h, d.confidence,
                        d.front_distance_m, d.approach_distance_m,
                        d.clearance_distance_m, d.clearance_distance_cm,
                        d.line_distance_m, d.travel_direction, d.lane_position_flag,
                        d.l_line_cross_m, d.r_line_cross_m,
                        {center_col}, {white_col}
                    FROM Detection d
                    LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
                    WHERE d.run_id = ?
                      AND d.frame_num = ?
                      AND d.group_id = ?
                    ORDER BY d.auto_id DESC
                    LIMIT 1
                """
                car_row = conn.execute(
                    car_sql.format(center_col=car_center_col, white_col=car_white_col),
                    (run_id, frame_num, car_group_id),
                ).fetchone()
                if car_row:
                    car_detection = dict(car_row)
                    if not car_detection.get("class_name"):
                        cid = car_detection.get("class_id")
                        car_detection["class_name"] = class_name_map.get(cid)

            # 被追い越し車（自転車）のDetectionデータを取得
            bike_detection = None
            if event_row and event_row["overtaken_auto_id"]:
                bike_center_col = (
                    "d.center_line_overtake_status"
                    if has_center_status
                    else "NULL AS center_line_overtake_status"
                )
                bike_white_col = (
                    "d.white_line_overtake_status"
                    if has_white_status
                    else "NULL AS white_line_overtake_status"
                )
                bike_sql = """
                    SELECT 
                        d.auto_id, d.frame_num, d.group_id, d.class_id,
                        d.x1, d.y1, d.x2, d.y2, d.measure_x, d.measure_y,
                        cm.class_name, d.speed_km_h, d.confidence,
                        d.front_distance_m, d.approach_distance_m,
                        d.clearance_distance_m, d.clearance_distance_cm,
                        d.line_distance_m, d.travel_direction, d.lane_position_flag,
                        d.l_line_cross_m, d.r_line_cross_m,
                        {center_col}, {white_col}
                    FROM Detection d
                    LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
                    WHERE d.auto_id = ?
                """
                bike_row = conn.execute(
                    bike_sql.format(center_col=bike_center_col, white_col=bike_white_col),
                    (event_row["overtaken_auto_id"],),
                ).fetchone()
                if bike_row:
                    bike_detection = dict(bike_row)
                    if not bike_detection.get("class_name"):
                        cid = bike_detection.get("class_id")
                        bike_detection["class_name"] = class_name_map.get(cid)
            elif run_id is not None:
                bike_center_col = (
                    "d.center_line_overtake_status"
                    if has_center_status
                    else "NULL AS center_line_overtake_status"
                )
                bike_white_col = (
                    "d.white_line_overtake_status"
                    if has_white_status
                    else "NULL AS white_line_overtake_status"
                )
                bike_sql = """
                    SELECT 
                        d.auto_id, d.frame_num, d.group_id, d.class_id,
                        d.x1, d.y1, d.x2, d.y2, d.measure_x, d.measure_y,
                        cm.class_name, d.speed_km_h, d.confidence,
                        d.front_distance_m, d.approach_distance_m,
                        d.clearance_distance_m, d.clearance_distance_cm,
                        d.line_distance_m, d.travel_direction, d.lane_position_flag,
                        d.l_line_cross_m, d.r_line_cross_m,
                        {center_col}, {white_col}
                    FROM Detection d
                    LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
                    WHERE d.run_id = ?
                      AND d.frame_num = ?
                      AND d.group_id = ?
                    ORDER BY d.auto_id DESC
                    LIMIT 1
                """
                bike_row = conn.execute(
                    bike_sql.format(center_col=bike_center_col, white_col=bike_white_col),
                    (run_id, frame_num, bike_group_id),
                ).fetchone()
                if bike_row:
                    bike_detection = dict(bike_row)
                    if not bike_detection.get("class_name"):
                        cid = bike_detection.get("class_id")
                        bike_detection["class_name"] = class_name_map.get(cid)

            calibration_data = None
            overlay_data = None
            if run_id:
                calib_row = conn.execute(
                    "SELECT calibration_profile FROM ProcessLog WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                profile_name = calib_row[0] if calib_row else None
                try:
                    calib_payload, _ = load_calibration_json(run_id, profile_name)
                    lines = load_white_lines(calib_payload)
                    calibration_data = {
                        "left_line": lines.left,
                        "right_line": lines.right,
                        "center_line": lines.center,
                    }
                except Exception:
                    calibration_data = None

            if calibration_data:
                center_line = calibration_data.get("center_line")
                left_line = calibration_data.get("left_line")
                car_point = None
                bike_point = None
                car_measure_point = None
                bike_measure_point = None
                car_line_point = None
                bike_line_point = None

                car_source = "bbox_fallback"
                if car_detection:
                    c_mx = car_detection.get("measure_x")
                    c_my = car_detection.get("measure_y")
                    if c_mx is not None and c_my is not None:
                        car_measure_point = {"x": c_mx, "y": c_my}
                        car_source = "detection"
                    elif car_detection.get("x1") is not None and car_detection.get("y2") is not None:
                        car_measure_point = {"x": car_detection.get("x1"), "y": car_detection.get("y2")}

                if car_detection and car_detection.get("x1") is not None and car_detection.get("y2") is not None:
                    car_point = {"x": car_detection.get("x1"), "y": car_detection.get("y2")}
                    if center_line:
                        # Use measure point Y if available for line intersection, else bottom Y
                        use_y = car_measure_point["y"] if car_measure_point else car_detection.get("y2")
                        cx = get_line_x_at_y(use_y, center_line)
                        if cx is not None:
                            car_line_point = {"x": cx, "y": use_y}

                bike_source = "bbox_fallback"
                if bike_detection:
                    b_mx = bike_detection.get("measure_x")
                    b_my = bike_detection.get("measure_y")
                    if b_mx is not None and b_my is not None:
                        bike_measure_point = {"x": b_mx, "y": b_my}
                        bike_source = "detection"
                    elif bike_detection.get("measure_x") is not None and bike_detection.get("measure_y") is not None:
                         # Fallback to existing measure fields if above check fails
                        bike_measure_point = {"x": bike_detection.get("measure_x"), "y": bike_detection.get("measure_y")}
                        bike_source = "detection"
                    elif bike_detection.get("x1") is not None and bike_detection.get("y2") is not None:
                         # Fallback to bbox
                         bike_measure_point = {"x": bike_detection.get("x1"), "y": bike_detection.get("y2")}

                if bike_detection and bike_detection.get("x1") is not None: # Ensure bike exists
                    bike_point = {"x": bike_detection.get("measure_x") or bike_detection.get("x1"),
                                  "y": bike_detection.get("measure_y") or bike_detection.get("y2")}

                    if calibration_data.get("right_line"):
                        use_y = bike_measure_point["y"] if bike_measure_point else bike_detection.get("y2")
                        bx = get_line_x_at_y(use_y, calibration_data.get("right_line"))
                        if bx is not None:
                            bike_line_point = {"x": bx, "y": use_y}

                overlay_data = {
                    "car_point": car_point,
                    "bike_point": bike_point,
                    "car_measure_point": car_measure_point,
                    "bike_measure_point": bike_measure_point,
                    "car_center_line_point": car_line_point,
                    "bike_white_line_point": bike_line_point,
                    "car_source": car_source,
                    "bike_source": bike_source,
                }

            if event_data:
                def _first_value(*values):
                    for value in values:
                        if value is not None:
                            return value
                    return None

                if event_data.get("clearance_distance_m") is None:
                    event_data["clearance_distance_m"] = _first_value(
                        (car_detection or {}).get("clearance_distance_m"),
                        (bike_detection or {}).get("clearance_distance_m"),
                    )
                if event_data.get("clearance_distance_cm") is None:
                    event_data["clearance_distance_cm"] = _first_value(
                        (car_detection or {}).get("clearance_distance_cm"),
                        (bike_detection or {}).get("clearance_distance_cm"),
                    )
                    if (
                        event_data.get("clearance_distance_cm") is None
                        and event_data.get("clearance_distance_m") is not None
                    ):
                        event_data["clearance_distance_cm"] = event_data["clearance_distance_m"] * 100.0
                if event_data.get("approach_distance_m") is None:
                    event_data["approach_distance_m"] = _first_value(
                        (car_detection or {}).get("approach_distance_m"),
                        (bike_detection or {}).get("approach_distance_m"),
                    )
                if event_data.get("line_distance_m") is None:
                    event_data["line_distance_m"] = _first_value(
                        (bike_detection or {}).get("line_distance_m"),
                        (car_detection or {}).get("line_distance_m"),
                    )
            
            # フレーム内の全Detectionを取得 (選択変更用)
            all_detections = []
            if run_id is not None:
                all_det_sql = "SELECT d.auto_id, d.group_id, d.track_id, d.class_id, cm.class_name, d.confidence, d.x1, d.y1, d.x2, d.y2, d.measure_x, d.measure_y, d.speed_km_h, d.line_distance_m, d.lane_position_flag FROM Detection d LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id WHERE d.run_id = ? AND d.frame_num = ? ORDER BY d.auto_id"
                all_rows = conn.execute(all_det_sql, (run_id, frame_num)).fetchall()
                for r in all_rows:
                    det = dict(r)
                    if not det.get("class_name"):
                        det["class_name"] = class_name_map.get(det["class_id"], "unknown")
                    all_detections.append(det)

            # run_idから動画ファイル名も取得
            video_filename = None
            if run_id:
                video_sql = """
                    SELECT v.filename 
                    FROM ProcessLog p 
                    JOIN Video v ON p.video_id = v.video_id 
                    WHERE p.run_id = ?
                """
                video_row = conn.execute(video_sql, (run_id,)).fetchone()
                if video_row:
                    video_filename = video_row["filename"]
            
            return jsonify({
                "ok": True,
                "frame_num": frame_num,
                "car_group_id": car_group_id,
                "bike_group_id": bike_group_id,
                "run_id": run_id,
                "video_filename": video_filename,
                "event": event_data,
                "car_detection": car_detection,
                "bike_detection": bike_detection,
                "all_detections": all_detections,
                "outputs": {
                    "auto": bool(event_row),
                    "rerun": check_sheet_event is not None,
                    "manual": manual_event is not None,
                },
                "check_sheet_event": check_sheet_event,
                "manual_event": manual_event,
                "calibration": calibration_data,
                "overlay": overlay_data,
            })
    
    except Exception as e:
        current_app.logger.exception("Overtake photo detail API failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@main.route("/api/overtake_photo/group_data")
def overtake_photo_group_data():
    """指定グループIDの全Detectionデータを取得するAPI"""
    run_id = request.args.get("run_id", type=int)
    group_id = request.args.get("group_id", type=int)
    
    if run_id is None or group_id is None:
        return jsonify({"ok": False, "error": "run_idとgroup_idが必要です"}), 400
    
    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            configure_connection(conn, mode="read")

            detection_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(Detection)").fetchall()
            }
            center_col = (
                "d.center_line_overtake_status"
                if "center_line_overtake_status" in detection_columns
                else "NULL AS center_line_overtake_status"
            )
            white_col = (
                "d.white_line_overtake_status"
                if "white_line_overtake_status" in detection_columns
                else "NULL AS white_line_overtake_status"
            )
            
            sql = """
                SELECT 
                    d.auto_id, d.frame_num, d.group_id,
                    cm.class_name, d.speed_km_h, d.confidence,
                    d.front_distance_m, d.clearance_distance_m, d.approach_distance_m,
                    d.line_distance_m, d.l_line_distance_m, d.r_line_distance_m,
                    d.travel_direction, d.acceleration_state, d.acceleration_m_s2,
                    d.x1, d.y1, d.x2, d.y2,
                    {center_col}, {white_col},
                    d.overtake, d.overtake_after
                FROM Detection d
                LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
                WHERE d.run_id = ? AND d.group_id = ?
                ORDER BY d.frame_num ASC
            """
            rows = conn.execute(
                sql.format(center_col=center_col, white_col=white_col),
                (run_id, group_id),
            ).fetchall()
            
            detections = [dict(row) for row in rows]
            
            return jsonify({
                "ok": True,
                "run_id": run_id,
                "group_id": group_id,
                "count": len(detections),
                "detections": detections,
            })
    
    except Exception as e:
        current_app.logger.exception("Overtake photo group data API failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@main.route("/api/overtake_photo/delete", methods=["POST"])
def overtake_photo_delete():
    """追い越し写真と対応する追い越しイベントを削除するAPI"""
    payload = request.get_json(silent=True) or {}
    filename = payload.get("filename", "")

    if not filename:
        return jsonify({"ok": False, "error": "ファイル名が指定されていません"}), 400

    pattern = r"overtake_(\d+)_car(\d+)_bike(\d+)_\d+\.png"
    match = re.match(pattern, os.path.basename(filename))
    if not match:
        return jsonify({"ok": False, "error": "ファイル名の形式が不正です"}), 400

    frame_num = int(match.group(1))
    car_group_id = int(match.group(2))
    bike_group_id = int(match.group(3))

    deleted_event = False
    deleted_file = False
    event_run_id = None

    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            configure_connection(conn, mode="read")
            event_row = conn.execute(
                """
                SELECT overtake_event_id, run_id, overtaker_auto_id
                FROM OvertakeEvents
                WHERE event_frame_num = ?
                  AND overtaker_group_id = ?
                  AND overtaken_group_id = ?
                """,
                (frame_num, car_group_id, bike_group_id),
            ).fetchone()

            if event_row:
                overtake_event_id, event_run_id, overtaker_auto_id = event_row
                conn.execute("DELETE FROM OvertakeEvents WHERE overtake_event_id = ?", (overtake_event_id,))
                if overtaker_auto_id:
                    conn.execute(
                        """
                        UPDATE Detection
                        SET overtake = 0,
                            overtake_after = 0,
                            overtake_by = NULL,
                            overtake_by_second = NULL
                        WHERE auto_id = ?
                        """,
                        (overtaker_auto_id,),
                    )
                conn.commit()
                deleted_event = True
    except Exception as e:
        current_app.logger.exception("Overtake photo delete API failed")
        return jsonify({"ok": False, "error": str(e)}), 500

    opt_root = resolve_output_root()
    abs_opt = os.path.abspath(opt_root)
    abs_path = os.path.abspath(os.path.join(abs_opt, filename))
    if abs_path.startswith(abs_opt) and os.path.isfile(abs_path):
        try:
            os.remove(abs_path)
            deleted_file = True
        except Exception as e:
            current_app.logger.exception("Failed to delete overtake snapshot file")
            return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify(
        {
            "ok": True,
            "deleted_event": deleted_event,
            "deleted_file": deleted_file,
            "run_id": event_run_id,
        }
    )


@main.route("/api/overtake_photo/update_line_status", methods=["POST"])
def overtake_photo_update_line_status():
    """追い越し詳細画面から中央線/白線判定を更新するAPI"""
    payload = request.get_json(silent=True) or {}
    car_auto_id = payload.get("car_auto_id")
    bike_auto_id = payload.get("bike_auto_id")
    car_center_status = (payload.get("car_center_status") or "").strip()
    bike_white_status = (payload.get("bike_white_status") or "").strip()

    if not car_auto_id and not bike_auto_id:
        return jsonify({"ok": False, "error": "auto_idが指定されていません"}), 400

    valid_center = {"中央線越え", "中央線内側"}
    valid_white = {"白線越え", "白線内側"}

    if car_center_status and car_center_status not in valid_center:
        return jsonify({"ok": False, "error": "中央線判定が不正です"}), 400
    if bike_white_status and bike_white_status not in valid_white:
        return jsonify({"ok": False, "error": "白線判定が不正です"}), 400

    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            configure_connection(conn, mode="write")
            if car_auto_id:
                conn.execute(
                    "UPDATE Detection SET center_line_overtake_status = ? WHERE auto_id = ?",
                    (car_center_status or None, car_auto_id),
                )
            if bike_auto_id:
                conn.execute(
                    "UPDATE Detection SET white_line_overtake_status = ? WHERE auto_id = ?",
                    (bike_white_status or None, bike_auto_id),
                )
            conn.commit()
    except Exception as e:
        current_app.logger.exception("Failed to update line status")
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True})


@main.route("/api/overtake_events/all_group_ids")
def overtake_events_all_group_ids():
    """全追い越しイベントの車・自転車グループIDを一覧で取得するAPI"""
    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            configure_connection(conn, mode="read")
            
            sql = """
                SELECT 
                    o.run_id,
                    o.event_frame_num,
                    o.overtaker_group_id,
                    o.overtaken_group_id,
                    v.filename as video_filename
                FROM OvertakeEvents o
                LEFT JOIN ProcessLog p ON o.run_id = p.run_id
                LEFT JOIN Video v ON p.video_id = v.video_id
                ORDER BY o.run_id, o.event_frame_num
            """
            rows = conn.execute(sql).fetchall()
            
            events = [dict(row) for row in rows]
            
            return jsonify({
                "ok": True,
                "count": len(events),
                "events": events,
            })
    
    except Exception as e:
        current_app.logger.exception("Overtake events all group IDs API failed")
        return jsonify({"ok": False, "error": str(e)}), 500
