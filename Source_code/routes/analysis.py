from flask import render_template, request, jsonify, current_app, send_file
import io
import pandas as pd
import sqlite3
import glob
import os
from . import main
from ..modules import db_manager as dbm
from ..modules.comparative_analysis import load_overtake_data, compute_statistics, run_tests, generate_plots
from ..modules.db_manager import (
    MAIN_DB_PATH,
    configure_connection,
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
        
        # テンプレートで使いやすいようにフラットなキーも追加
        counts['B_count'] = direction_counts.get('B', 0)
        counts['F_count'] = direction_counts.get('F', 0)
    except Exception as e:
        current_app.logger.exception("Failed to load comparative report options")
        years = []
        road_types = []
        counts = {}
        
    return render_template(
        "comparative_report.html", 
        title="Comparative Analysis Report",
        years=years,
        road_types=road_types,
        counts=counts
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
        
        if not collection_years or not road_types or not metrics:
            return jsonify({"success": False, "error": "必要なパラメータが不足しています"}), 400

        # データロード
        analyzer = ComparativeAnalyzer(MAIN_DB_PATH)
        analyzer.load_overtake_data(
            collection_years=collection_years,
            road_types=road_types,
            directions=directions
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
        
        if not collection_years or not road_types or not metrics:
            return jsonify({"success": False, "error": "必要なパラメータが不足しています"}), 400

        # データロードと生成
        analyzer = ComparativeAnalyzer(MAIN_DB_PATH)
        analyzer.load_overtake_data(
            collection_years=collection_years,
            road_types=road_types,
            directions=directions
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

@main.route("/statistics")
def statistics_view():
    """Statistics Page"""
    return render_template("statistics.html", title="Statistics")

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
            cursor = conn.execute("SELECT COUNT(*) FROM Detection WHERE model_name IN ('bicycle', 'cyclist')")
            row = cursor.fetchone()
            if row:
                stats["bicycles"] = row[0]

            # 3. Total Cars
            cursor = conn.execute("SELECT COUNT(*) FROM Detection WHERE model_name IN ('car', 'truck', 'bus')")
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
            opt_root = os.getenv("Opt_files") or "output"
            snapshots_pattern = os.path.join(opt_root, "*", "overtake_snapshots", "*.jpg")
            files = glob.glob(snapshots_pattern)
            files.sort(key=os.path.getmtime, reverse=True) # Sort by new
            
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


@main.route("/export_statistics", methods=["POST"])
def export_statistics():
    """統計情報をExcel形式でエクスポートする。"""
    try:
        from ..modules.statistics_exporter import export_statistics_workbook
        from ..modules.db_manager import list_detection_runs
        import flask
        
        # All runs
        runs = list_detection_runs()
        run_ids = [r["run_id"] for r in runs]
        
        output_file = export_statistics_workbook(run_ids=run_ids)
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
