from flask import render_template, request, jsonify, redirect, url_for, flash, current_app
import os
import threading
import uuid
import time
import glob
import datetime
from typing import Dict, Any, Optional, List
from . import main

import queue

# Global progress state for post-processing
post_process_progress: Dict[str, Any] = {
    "current": 0, 
    "total": 0, 
    "percent": 0, 
    "message": None, 
    "status": "idle",
    "queue_size": 0
}

# Global Request Queue
task_queue = queue.Queue()

# Queue Registry for UI visibility
# format: { task_id: { "id": str, "description": str, "status": "queued"|"processing", "submitted_at": float } }
queue_registry: Dict[str, Dict] = {}
current_processing_task_id: Optional[str] = None

is_worker_running = False

def _postprocess_log_dir() -> str:
    log_dir = os.path.abspath(os.path.join(os.getcwd(), "log"))
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


POSTPROCESS_COLUMNS = [
    "group_id",
    "travel_direction",
    "scale_pixels_per_meter",
    "x_pixels_per_meter",
    "pixel_speed",
    "speed_km_h",
    "acceleration_m_s2",
    "acceleration_state",
    "measure_x",
    "measure_y",
    "l_line_distance",
    "l_line_distance_m",
    "l_line_distance_cm",
    "r_line_distance",
    "r_line_distance_m",
    "r_line_distance_cm",
    "line_distance",
    "line_distance_m",
    "line_distance_cm",
    "lane_position_flag",
    "l_line_cross_m",
    "r_line_cross_m",
    "center_line_overtake_status",
    "white_line_overtake_status",
    "overtake",
    "overtake_after",
    "overtake_by",
    "overtake_by_second",
    "overtake_window_offset",
    "approach_distance_px",
    "approach_distance_m",
    "approach_partner_group_id",
    "clearance_distance_px",
    "clearance_distance_m",
    "clearance_distance_cm",
    "oncoming_flag",
    "front_distance_m",
    "front_vehicle_id",
    "ttc_s",
    "xy_px_speedpx",
    "xy_px_karikm",
    "xy_px_changeable",
    "xy_px_changeable_name",
]


def _sanitize_log_label(label: str) -> str:
    if not label:
        return "batch"
    safe = []
    for ch in label:
        if ch.isalnum() or ch in ("-", "_"):
            safe.append(ch)
        else:
            safe.append("_")
    return "".join(safe).strip("_") or "batch"


def _write_bulk_summary_log(run_ids: List[int], label: str) -> Optional[str]:
    if not run_ids:
        return None
    from ..modules.db_manager import MAIN_DB_PATH, configure_connection
    from ..modules.xy_section_speed import collect_measurement_lengths
    import sqlite3

    run_ids = sorted(set(int(rid) for rid in run_ids))
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="read")
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS tmp_postprocess_run_ids")
        cur.execute("CREATE TEMP TABLE tmp_postprocess_run_ids (run_id INTEGER PRIMARY KEY)")
        cur.executemany(
            "INSERT INTO tmp_postprocess_run_ids(run_id) VALUES (?)",
            [(rid,) for rid in run_ids],
        )

        cur.execute(
            """
            SELECT COUNT(*)
            FROM OvertakeEvents oe
            JOIN tmp_postprocess_run_ids r ON oe.run_id = r.run_id
            """
        )
        overtake_events = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*)
            FROM Detection d
            JOIN tmp_postprocess_run_ids r ON d.run_id = r.run_id
            WHERE d.overtake_by IS NOT NULL
              AND TRIM(COALESCE(d.overtake_by, '')) != ''
            """
        )
        overtake_by_rows = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*)
            FROM Detection d
            JOIN tmp_postprocess_run_ids r ON d.run_id = r.run_id
            WHERE d.overtake_by_second IS NOT NULL
              AND TRIM(COALESCE(d.overtake_by_second, '')) != ''
            """
        )
        overtake_by_second_rows = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*)
            FROM Detection d
            JOIN tmp_postprocess_run_ids r ON d.run_id = r.run_id
            WHERE d.overtake = 1
            """
        )
        overtake_flag_rows = cur.fetchone()[0]

        measurement_lengths = collect_measurement_lengths(run_ids)

        cur.execute(
            """
            SELECT d.acceleration_state, COUNT(*)
            FROM Detection d
            JOIN tmp_postprocess_run_ids r ON d.run_id = r.run_id
            WHERE d.overtake = 1
            GROUP BY d.acceleration_state
            """
        )
        accel_state_rows = cur.fetchall()
        accel_state_counts = {
            (row[0] if row[0] is not None else ""): row[1] for row in accel_state_rows
        }
        accel_count = accel_state_counts.get("加速", 0) + accel_state_counts.get("accelerating", 0)
        decel_count = accel_state_counts.get("減速", 0) + accel_state_counts.get("decelerating", 0)
        steady_count = accel_state_counts.get("等速", 0) + accel_state_counts.get("steady", 0)
        unknown_count = max(
            overtake_flag_rows - (accel_count + decel_count + steady_count), 0
        )
        change_count = accel_count + decel_count
        change_rate = (change_count / overtake_flag_rows * 100) if overtake_flag_rows else 0.0

        traffic_counts = []
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='TrafficCount'"
        )
        has_traffic = cur.fetchone() is not None
        if has_traffic:
            cur.execute(
                """
                SELECT tc.object_type, tc.direction, SUM(tc.count)
                FROM TrafficCount tc
                JOIN tmp_postprocess_run_ids r ON tc.run_id = r.run_id
                GROUP BY tc.object_type, tc.direction
                ORDER BY tc.object_type, tc.direction
                """
            )
            traffic_counts = cur.fetchall()

        cur.execute(
            """
            SELECT COUNT(*)
            FROM Detection d
            JOIN tmp_postprocess_run_ids r ON d.run_id = r.run_id
            """
        )
        detection_total = cur.fetchone()[0]

        column_stats = []
        cur.execute("PRAGMA table_info(Detection)")
        columns_info = [(row[1], row[2] or "") for row in cur.fetchall()]
        detection_columns = [col for col, _ in columns_info]
        flag_columns = {"overtake", "overtake_after"}
        for col, col_type in columns_info:
            col_sql = f"\"{col}\""
            type_upper = col_type.upper()
            if col in flag_columns:
                where_clause = f"d.{col_sql} IS NOT NULL AND d.{col_sql} != 0"
            elif "CHAR" in type_upper or "TEXT" in type_upper or "CLOB" in type_upper:
                where_clause = f"d.{col_sql} IS NOT NULL AND TRIM(d.{col_sql}) != ''"
            else:
                where_clause = f"d.{col_sql} IS NOT NULL"

            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM Detection d
                JOIN tmp_postprocess_run_ids r ON d.run_id = r.run_id
                WHERE {where_clause}
                """
            )
            non_empty = cur.fetchone()[0]
            percent = (non_empty / detection_total * 100) if detection_total else 0.0
            column_stats.append((col, non_empty, percent))

        postprocess_set = {col for col in POSTPROCESS_COLUMNS if col in detection_columns}
        postprocess_stats = [
            stat for stat in column_stats if stat[0] in postprocess_set
        ]

    log_dir = _postprocess_log_dir()
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = _sanitize_log_label(label)
    log_path = os.path.join(log_dir, f"RAN_postprocess_summary_{safe_label}_{ts}.log")
    md_path = os.path.join(log_dir, f"RAN_postprocess_summary_{safe_label}_{ts}.md")

    measurement_lines = []
    measurement_md_lines = []
    if measurement_lengths:
        import numpy as np
        from collections import Counter

        lengths_sorted = sorted(measurement_lengths)
        median_len = float(np.median(lengths_sorted))
        min_len = float(lengths_sorted[0])
        max_len = float(lengths_sorted[-1])
        peak_counts = Counter(round(val, 1) for val in measurement_lengths)
        peaks = [item[0] for item in peak_counts.most_common(2)]
        peak_text = ", ".join(f"{val:.1f}px" for val in peaks) if peaks else "-"
        measurement_lines.extend([
            "-" * 60,
            "測定区間Y長さの統計:",
            f"  最小: {min_len:.1f}px",
            f"  最大: {max_len:.1f}px",
            f"  中央値: {median_len:.1f}px",
            f"  ピーク(上位2件): {peak_text}",
        ])
        measurement_md_lines.extend([
            "## 測定区間Y長さの統計",
            "",
            f"- 最小: {min_len:.1f}px",
            f"- 最大: {max_len:.1f}px",
            f"- 中央値: {median_len:.1f}px",
            f"- ピーク(上位2件): {peak_text}",
            "",
        ])
    else:
        measurement_lines.extend([
            "-" * 60,
            "測定区間Y長さの統計:",
            "  (測定区間データがありません)",
        ])
        measurement_md_lines.extend([
            "## 測定区間Y長さの統計",
            "",
            "(測定区間データがありません)",
            "",
        ])

    lines = [
        "RAN 後処理まとめログ",
        f"作成日時: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"ラベル: {label}",
        f"Run数: {len(run_ids)}",
        "-" * 60,
        "カウント線通過統計:",
    ]
    if not has_traffic:
        lines.append("  (TrafficCount テーブルが見つかりません)")
    elif not traffic_counts:
        lines.append("  (カウントデータがありません)")
    else:
        totals = {}
        normalized_totals = {"車": 0, "自転車": 0}
        for obj_type, direction, cnt in traffic_counts:
            lines.append(f"  {obj_type} / {direction}: {cnt}")
            totals[obj_type] = totals.get(obj_type, 0) + (cnt or 0)
            obj_text = str(obj_type or "").lower()
            if any(key in obj_text for key in ["bicycle", "bike", "自転"]):
                normalized_totals["自転車"] += cnt or 0
            else:
                normalized_totals["車"] += cnt or 0
        lines.append("  合計:")
        for obj_type, cnt in totals.items():
            lines.append(f"    {obj_type}: {cnt}")
        lines.append("  車種別合計:")
        lines.append(f"    車: {normalized_totals['車']}")
        lines.append(f"    自転車: {normalized_totals['自転車']}")

    if measurement_lines:
        lines.extend(measurement_lines)

    lines.extend([
        "-" * 60,
        f"OvertakeEvents 行数: {overtake_events}",
        f"overtake_by 行数: {overtake_by_rows}",
        f"overtake_by_second 行数: {overtake_by_second_rows}",
        f"overtake=1 行数: {overtake_flag_rows}",
        "追い越し時の速度変化:",
    ])
    if overtake_flag_rows:
        lines.append(
            f"  変化あり: {change_count} / {overtake_flag_rows} ({change_rate:.1f}%)"
        )
        lines.append(
            f"  内訳: 加速 {accel_count}, 減速 {decel_count}, 等速 {steady_count}, 不明 {unknown_count}"
        )
    else:
        lines.append("  (追い越しデータがありません)")

    lines.extend([
        "-" * 60,
        f"Detection 総行数: {detection_total}",
        "Detection カラム別 行数/割合:",
        "注記: overtake/overtake_after は 1 の行数を表示 (0は未検出扱い)",
    ])
    if detection_total and column_stats:
        max_len = max(len(str(name)) for name in detection_columns)
        header = f"  {'カラム名'.ljust(max_len)} | {'行数'.rjust(8)} | {'割合'.rjust(6)}"
        lines.append(header)
        lines.append("  " + "-" * len(header))
        for col, count, pct in column_stats:
            lines.append(
                f"  {str(col).ljust(max_len)} | {str(count).rjust(8)} | {pct:5.1f}%"
            )
    else:
        lines.append("  (対象データがありません)")

    lines.append("-" * 60)
    lines.append("後処理生成カラム 行数/割合:")
    if detection_total and postprocess_stats:
        max_len = max(len(str(name)) for name, _, _ in postprocess_stats)
        header = f"  {'カラム名'.ljust(max_len)} | {'行数'.rjust(8)} | {'割合'.rjust(6)}"
        lines.append(header)
        lines.append("  " + "-" * len(header))
        for col, count, pct in postprocess_stats:
            lines.append(
                f"  {str(col).ljust(max_len)} | {str(count).rjust(8)} | {pct:5.1f}%"
            )
    else:
        lines.append("  (対象データがありません)")

    lines.extend([
        "Run ID一覧 (先頭20件):",
        ", ".join(str(rid) for rid in run_ids[:20]),
    ])
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")

    md_lines = [
        "# RAN 後処理まとめログ",
        "",
        f"- 作成日時: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- ラベル: {label}",
        f"- Run数: {len(run_ids)}",
        "",
        "## カウント線通過統計",
        "",
    ]
    if not has_traffic:
        md_lines.append("(TrafficCount テーブルが見つかりません)")
    elif not traffic_counts:
        md_lines.append("(カウントデータがありません)")
    else:
        md_lines.append("|種別|方向|通過数|")
        md_lines.append("|---|---|---:|")
        totals = {}
        normalized_totals = {"車": 0, "自転車": 0}
        for obj_type, direction, cnt in traffic_counts:
            md_lines.append(f"|{obj_type}|{direction}|{cnt}|")
            totals[obj_type] = totals.get(obj_type, 0) + (cnt or 0)
            obj_text = str(obj_type or "").lower()
            if any(key in obj_text for key in ["bicycle", "bike", "自転"]):
                normalized_totals["自転車"] += cnt or 0
            else:
                normalized_totals["車"] += cnt or 0
        md_lines.append("")
        md_lines.append("合計:")
        for obj_type, cnt in totals.items():
            md_lines.append(f"- {obj_type}: {cnt}")
        md_lines.append("")
        md_lines.append("車種別合計:")
        md_lines.append(f"- 車: {normalized_totals['車']}")
        md_lines.append(f"- 自転車: {normalized_totals['自転車']}")

    if measurement_md_lines:
        md_lines.extend(measurement_md_lines)

    md_lines.extend([
        "## 追い越し集計",
        "",
        f"- OvertakeEvents 行数: {overtake_events}",
        f"- overtake_by 行数: {overtake_by_rows}",
        f"- overtake_by_second 行数: {overtake_by_second_rows}",
        f"- overtake=1 行数: {overtake_flag_rows}",
        "",
        "### 追い越し時の速度変化",
        "",
    ])
    if overtake_flag_rows:
        md_lines.append(
            f"- 変化あり: {change_count} / {overtake_flag_rows} ({change_rate:.1f}%)"
        )
        md_lines.append(
            f"- 内訳: 加速 {accel_count}, 減速 {decel_count}, 等速 {steady_count}, 不明 {unknown_count}"
        )
    else:
        md_lines.append("(追い越しデータがありません)")

    md_lines.extend([
        "",
        "## Detection カラム別 行数/割合",
        "",
        "> 注記: overtake/overtake_after は 1 の行数を表示 (0は未検出扱い)",
        "",
    ])
    if detection_total and column_stats:
        md_lines.append("|カラム名|行数|割合|")
        md_lines.append("|---|---:|---:|")
        for col, count, pct in column_stats:
            md_lines.append(f"|{col}|{count}|{pct:.1f}%|")
    else:
        md_lines.append("(対象データがありません)")

    md_lines.extend([
        "",
        "## 後処理生成カラム 行数/割合",
        "",
    ])
    if detection_total and postprocess_stats:
        md_lines.append("|カラム名|行数|割合|")
        md_lines.append("|---|---:|---:|")
        for col, count, pct in postprocess_stats:
            md_lines.append(f"|{col}|{count}|{pct:.1f}%|")
    else:
        md_lines.append("(対象データがありません)")

    md_lines.extend([
        "",
        "## Run ID一覧 (先頭20件)",
        "",
        ", ".join(str(rid) for rid in run_ids[:20]),
        "",
    ])

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    return log_path


def _cleanup_postprocess_logs() -> None:
    log_dir = _postprocess_log_dir()
    patterns = ("RAN_*.log", "RAN_report_*.txt", "RAN_*.md")
    for pattern in patterns:
        for path in glob.glob(os.path.join(log_dir, pattern)):
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    continue

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
    
    # Group logs by folder for UX (OptGroup)
    from collections import defaultdict
    grouped_logs = defaultdict(list)
    for log in logs:
        f_alias = log.get('folder_alias') or "未分類"
        f_count = log.get('folder_run_count', 0)
        
        # サブフォルダがある場合は、その名前でグルーピング
        sub_disp = log.get('subfolder_display')
        if sub_disp:
            # ラベル名: "Alias [Subfolder]"
            group_label = f"{f_alias} [{sub_disp}]"
            # ソートキー用にサブフォルダも含める
            key = (group_label, f_count, f_alias, sub_disp)
        else:
            group_label = f_alias
            key = (group_label, f_count, f_alias, "")
            
        grouped_logs[key].append(log)
    
    # Sort: Alias asc, then Subfolder asc
    folder_groups = sorted(grouped_logs.items(), key=lambda x: (x[0][2], x[0][3]))
    
    folder_batches = list_folder_batches()
    
    # --- Synthesize Parent Folders for Batch Selection ---
    # Allow selecting a parent folder to process all subfolders recursively
    existing_aliases = set(b['folder_alias'] for b in folder_batches)
    parents_map = {}
    
    for b in folder_batches:
        root = b.get('root_folder')
        alias = b.get('folder_alias')
        
        # If this batch is a subfolder (root != alias) and the root is NOT in the list
        if root and root != alias and root not in existing_aliases:
            if root not in parents_map:
                parents_map[root] = {
                    'folder_alias': root,
                    'root_folder': root,
                    'subfolder': None,
                    'section': None,
                    'subfolder_display': f"[一括] {root} (全サブフォルダ含む)",
                    'run_count': 0,
                    'missing_profiles': 0,
                    'folder_run_count': 0 # helper field
                }
            # Aggregate stats
            parents_map[root]['run_count'] += b.get('run_count', 0)
            parents_map[root]['folder_run_count'] += b.get('folder_run_count', 0)
            parents_map[root]['missing_profiles'] += b.get('missing_profiles', 0)
    
    if parents_map:
        folder_batches.extend(parents_map.values())
        folder_batches.sort(key=lambda x: x['folder_alias'])
    # -----------------------------------------------------
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
        folder_groups=folder_groups,
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
            # db_manager.get_all_process_logs returns:
            # run_id, video_id, video_filename, process_start, process_end, output_folder,
            # folder_alias, status, message, calibration_profile, is_folder_batch
            
            results.append({
                "run_id": log["run_id"],
                "filename": log.get("video_filename", "Unknown"), # Map video_filename to filename for JS
                "process_start": log.get("process_start"), # JS expects process_start
                "status": log.get("status", "unknown"),
                "folder_alias": log.get("folder_alias"),
                "calibration_profile": log.get("calibration_profile"),
                "is_folder_batch": log.get("is_folder_batch"),
                "message": log.get("message", "")
            })
            
        from ..modules.db_manager import list_folder_batches
        folders = list_folder_batches()
            
        return jsonify({
            "logs": results,
            "folders": folders
        })
    except Exception as e:
        current_app.logger.exception("Failed to fetch process logs")
        return jsonify({"data": []}) # Return empty list on error to not break table


@main.route("/post_process/status")
def post_process_status():
    """現在の後処理の進捗状況を返す。"""
    return jsonify(post_process_progress)


@main.route("/api/logs/list")
def api_list_logs():
    """ログファイル一覧を取得する (RAN_*.log, RAN_report_*.txt)"""
    try:
        log_dir = os.path.abspath(os.path.join(os.getcwd(), "log"))
        if not os.path.exists(log_dir):
            return jsonify({"logs": []})

        files = []
        # Error/Run/Summary Logs
        files.extend(glob.glob(os.path.join(log_dir, "RAN_*.log")))
        # Report Logs
        files.extend(glob.glob(os.path.join(log_dir, "RAN_report_*.txt")))
        # Markdown Summary Logs
        files.extend(glob.glob(os.path.join(log_dir, "RAN_*.md")))
        
        results = []
        for p in files:
            fname = os.path.basename(p)
            mtime = os.path.getmtime(p)
            size = os.path.getsize(p)
            dt_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            lower_name = fname.lower()

            if lower_name.startswith("ran_postprocess_summary_"):
                file_type = "summary"
                category = "summary"
            elif lower_name.startswith("ran_postprocess_run_"):
                file_type = "run"
                category = "file"
            elif lower_name.startswith("ran_report_"):
                file_type = "report"
                category = "file"
            elif "error" in lower_name:
                file_type = "error"
                category = "file"
            else:
                file_type = "log"
                category = "file"

            results.append({
                "filename": fname,
                "mtime": mtime,
                "datetime": dt_str,
                "size": size,
                "type": file_type,
                "category": category
            })
            
        # Sort by mtime desc
        results.sort(key=lambda x: x["mtime"], reverse=True)
        
        return jsonify({"logs": results})
    except Exception as e:
        current_app.logger.exception("Failed to list logs")
        return jsonify({"error": str(e)}), 500


@main.route("/api/logs/content")
def api_get_log_content():
    """ログファイルの内容を取得する"""
    filename = request.args.get("filename")
    if not filename:
        return jsonify({"error": "Filename required"}), 400
        
    # Security check: filename must be simple and exist in log dir
    safe_name = os.path.basename(filename)
    if safe_name != filename:
        return jsonify({"error": "Invalid filename"}), 400
        
    try:
        log_dir = os.path.abspath(os.path.join(os.getcwd(), "log"))
        path = os.path.join(log_dir, safe_name)
        
        if not os.path.exists(path):
            return jsonify({"error": "File not found"}), 404
            
        # Read content (limit size?)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
            
        return jsonify({"filename": safe_name, "content": content})
    except Exception as e:
        current_app.logger.exception(f"Failed to read log {filename}")
        return jsonify({"error": str(e)}), 500




@main.route("/api/post_process/preview", methods=["POST"])
def preview_post_process():
    print("!!! PREVIEW REQUEST RECEIVED !!!", flush=True)
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
        target_folders = data.get("folder_aliases") or [] # New List Support
        if target_folder and target_folder not in target_folders:
            target_folders.append(target_folder)
            
        profile_name = data.get("folder_profile_name")
        
        log_step(f"Request: mode={target_mode}, folders={target_folders}, run={target_run_id}, profile={profile_name}")

        # 1. Identify Target Runs
        from ..modules.db_manager import list_folder_batches, get_run_ids_by_folder, get_run_video_info
        
        run_ids = []
        try:
            if target_mode == "folder":
                for f_alias in target_folders:
                    ids = get_run_ids_by_folder(f_alias)
                    run_ids.extend(ids)
                # Ensure unique and sorted
                run_ids = sorted(list(set(run_ids)))
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
            upload_folder = current_app.config.get('UPLOAD_FOLDER', os.getenv("Upload_folder", "uploads"))
            repre_info = get_run_video_info(target_run_id, upload_base_folder=upload_folder)
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
        
        # 1-b. 明示的に指定されたRunプロファイル
        run_profile_name = data.get("run_profile_name")
        if target_mode == "run" and run_profile_name:
            effective_profile = run_profile_name
            log_step(f"Using explicit run profile: {run_profile_name}")
        
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
        
        if video_path:
            try:
                from ..modules.video_utils import load_video_frame
                frame = load_video_frame(video_path, 120) # Frame 120
                if frame is None:
                    log_step("Step 5 Warning: Frame 120 failed, trying Frame 0")
                    frame = load_video_frame(video_path, 0)
                
                if frame is None:
                    log_step("Step 5 Error: Failed to load frame 0 (cv2 read failed)")
                    img_error = "動画フレームの読み込みに失敗しました"
                else:
                    log_step("Step 5 OK: Frame loaded")
                    
                    # Draw Lines if profile exists
                    if effective_profile:
                        import json
                        calib_dir = os.path.join(os.getenv("Opt_files", "output"), "calibrations")
                        profile_path = os.path.join(calib_dir, f"{effective_profile}.json")
                        
                        if not os.path.exists(profile_path):
                            log_step(f"Step 4 Error: Profile json not found at {profile_path}")
                            img_error = f"プロファイルが見つかりません: {effective_profile}"
                        else:
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
                            except Exception as e_draw:
                                log_step(f"Step 6 Error (Drawing): {e_draw}")
                                img_error = f"描画エラー: {e_draw}"
                    else:
                        log_step("No profile selected, showing raw frame")
                    
                    # Encode (Always)
                    import cv2
                    _, buffer = cv2.imencode('.jpg', frame)
                    import base64
                    img_base64 = base64.b64encode(buffer).decode('utf-8')
                    log_step("Step 7 OK: Image encoded to base64")
                    
            except Exception as e_vid:
                log_step(f"Step 5 Error (Video Load): {e_vid}")
                img_error = f"動画読み込みエラー: {e_vid}"
        else:
             log_step("Warning: Video path is None, cannot generate preview")
             img_error = "動画ファイルが見つかりません"

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
    """Post Process Action with Queue Support"""
    global post_process_progress, is_worker_running
    
    # 1. Capture Request Data (Main Thread)
    # Handle JSON or Form Data
    if request.is_json:
        req_data = request.get_json()
    else:
        req_data = request.form

    action = req_data.get("action")
    target_date = req_data.get("target_date")
    
    # Pre-extract list data from request (Context Safety)
    input_folders = []
    if request.is_json:
        aliases = req_data.get("folder_aliases")
        if aliases and isinstance(aliases, list):
            input_folders = aliases
        elif req_data.get("folder_alias"):
            input_folders = [req_data.get("folder_alias")]
    else:
        input_folders = request.form.getlist("folder_alias")
        if not input_folders and req_data.get("folder_alias"):
            input_folders = [req_data.get("folder_alias")] 
            
    # Remove duplicates and clean
    cleaned_folders = sorted(list(set([f for f in input_folders if f])))

    # 2. Build Task Payload
    task_id = str(uuid.uuid4())
    
    # Register in global registry for UI
    queue_registry[task_id] = {
        "id": task_id,
        "description": f"{action} (folders: {len(cleaned_folders)})",
        "status": "queued",
        "submitted_at": time.time(),
        "details": {
            "req_data": req_data,
            "target_date": target_date
        }
    }

    task_payload = {
        "task_id": task_id,
        "req_data": req_data, # Contains scalars
        "action": action,
        "input_folders": cleaned_folders,
        # Preserve specific items extracted manually if needed
        "target_date": target_date
    }
    
    # 3. Add to Queue
    task_queue.put(task_payload)
    current_q_size = task_queue.qsize()
    
    # Update progress to show queue status immediately
    post_process_progress["queue_size"] = current_q_size

    # 4. Start Worker if not running
    if not is_worker_running:
        is_worker_running = True
        
        # Capture app context object for the thread
        app = current_app._get_current_object()

        def worker_loop():
            global is_worker_running, post_process_progress, queue_registry, current_processing_task_id
            
            # Imports inside worker to avoid circular dependency issues if any
            import threading
            import concurrent.futures
            import multiprocessing
            from ..modules.db_manager import list_folder_batches, get_run_ids_by_folder, batch_update_run_attributes, update_run_profiles, get_all_run_ids, get_run_ids_by_condition
            from ..modules.batch_processor import process_single_batch
            import datetime
            import os
            
            with app.app_context():
                while not task_queue.empty():
                    t_id = None
                    try:
                        # Fetch next task
                        task = task_queue.get()
                        
                        # Identify Task
                        t_id = task.get("task_id")
                        if t_id and t_id in queue_registry:
                             queue_registry[t_id]["status"] = "processing"
                             current_processing_task_id = t_id
                        
                        remaining = task_queue.qsize()
                        post_process_progress["queue_size"] = remaining
                        
                        # Unpack Task
                        t_req_data = task["req_data"]
                        t_action = task["action"]
                        t_input_folders = task["input_folders"]
                        t_target_date = task["target_date"]
                        
                        # --- Processing Logic Start ---
                        
                        # 1. Setup - Update Status
                        post_process_progress.update({
                            "status": "processing",
                            "current": 0,
                            "total": 0, 
                            "percent": 0,
                            "batch_percent": 0,
                            "message": f"処理を開始します... (残り予約: {remaining}件)",
                            "current_detail": "",
                            "details": [],
                            "logs": [],
                            "results": None
                        })

                        t_mode = t_req_data.get("target_mode", "run")
                        t_run_id = t_req_data.get("run_id")
                        
                        # Additional Options
                        t_profile_name = t_req_data.get("folder_profile_name")
                        t_profile_name = t_req_data.get("folder_profile_name")
                        t_profile_scope = t_req_data.get("folder_profile_scope")
                        
                        # ===== 設定のみ保存処理 =====
                        if t_action == "save_settings":
                            post_process_progress.update({
                                "message": f"設定を保存しています... (残り予約: {remaining}件)",
                                "percent": 50
                            })
                            
                            try:
                                # 1. Identify Target Runs
                                target_runs = []
                                if t_mode == "all":
                                    target_runs = get_all_run_ids()
                                elif t_mode == "folder":
                                    target_runs = []
                                    for folder in t_input_folders:
                                        target_runs.extend(get_run_ids_by_folder(folder))
                                    target_runs = sorted(list(set(target_runs)))
                                elif t_mode == "run" and t_run_id:
                                    target_runs = [int(t_run_id)]
                                elif t_mode == "condition":
                                    target_runs = get_run_ids_by_condition(
                                        road_type=t_req_data.get("condition_road_type"), 
                                        process_year=t_req_data.get("condition_year")
                                    )
                                
                                if not target_runs:
                                    raise ValueError("対象のデータが見つかりません")
                                
                                count_meta = 0
                                count_profile = 0
                                
                                # 2. Update Metadata (Year, RoadType)
                                t_year_val = t_req_data.get("collection_year")
                                t_road_val = t_req_data.get("road_type")
                                
                                # Convert empty strings to None
                                if t_year_val == "": t_year_val = None
                                if t_road_val == "": t_road_val = None
                                
                                if t_year_val is not None or t_road_val is not None:
                                    count_meta = batch_update_run_attributes(target_runs, collection_year=t_year_val, road_type=t_road_val)
                                
                                # 3. Update Profile
                                if t_profile_name:
                                    count_profile = update_run_profiles(target_runs, t_profile_name)
                                    
                                post_process_progress.update({
                                    "status": "complete",
                                    "percent": 100,
                                    "message": f"保存完了 (対象: {len(target_runs)}件, メタデータ更新: {count_meta}, プロファイル更新: {count_profile})",
                                    "results": {"run_ids": target_runs}
                                })
                                
                            except Exception as e:
                                post_process_progress.update({
                                    "status": "error",
                                    "message": f"保存に失敗しました: {str(e)}"
                                })
                                
                            task_queue.task_done()
                            continue

                        # ===== 動画生成処理 =====
                        if t_action == "generate_video":
                            from ..modules.video_generator import VideoGenerator, normalize_video_options
                            
                            if not t_run_id:
                                post_process_progress.update({
                                    "status": "error",
                                    "message": "Run IDが指定されていません。"
                                })
                                task_queue.task_done()
                                continue
                            
                            run_id = int(t_run_id)
                            
                            post_process_progress.update({
                                "message": f"Run ID {run_id} の動画を生成中... (残り予約: {remaining}件)",
                                "percent": 10
                            })
                            
                            # 動画オプションの取得
                            video_options = {}
                            
                            # 表示要素のチェックボックス
                            if t_req_data.get("video_options_submitted"):
                                video_options["show_vehicle_box"] = t_req_data.get("video_show_vehicle_box") is not None
                                video_options["show_tire_boxes"] = t_req_data.get("video_show_tire_boxes") is not None
                                video_options["show_trace"] = t_req_data.get("video_show_trace") is not None
                                video_options["show_measurement"] = t_req_data.get("video_show_measurement") is not None
                                video_options["show_approach_lines"] = t_req_data.get("video_show_approach_lines") is not None
                                video_options["show_lane_left"] = t_req_data.get("video_show_lane_left") is not None
                                video_options["show_lane_right"] = t_req_data.get("video_show_lane_right") is not None
                                video_options["show_lane_center"] = t_req_data.get("video_show_lane_center") is not None
                                video_options["show_homography_overlay"] = t_req_data.get("video_show_homography_overlay") is not None
                                video_options["show_homography_only"] = t_req_data.get("video_show_homography_only") is not None
                                
                                # ラベル項目
                                video_options["label_group_id"] = t_req_data.get("video_label_group") is not None
                                video_options["label_speed"] = t_req_data.get("video_label_speed") is not None
                                video_options["label_lane_distance"] = t_req_data.get("video_label_lane") is not None
                                video_options["label_approach"] = t_req_data.get("video_label_approach") is not None
                                video_options["label_clearance"] = t_req_data.get("video_label_clearance") is not None
                                video_options["label_direction"] = t_req_data.get("video_label_direction") is not None
                                video_options["label_overtake"] = t_req_data.get("video_label_overtake") is not None
                                video_options["label_acceleration"] = t_req_data.get("video_label_acceleration") is not None
                                
                                # フォント設定
                                font_path = t_req_data.get("video_font_path")
                                if font_path:
                                    video_options["font_path"] = font_path
                                
                                font_size = t_req_data.get("video_font_size")
                                if font_size:
                                    try:
                                        video_options["font_size"] = int(font_size)
                                    except (ValueError, TypeError):
                                        pass
                                
                                # 出力設定
                                output_format = t_req_data.get("video_output_format")
                                if output_format:
                                    video_options["output_format"] = output_format
                                
                                output_name_mode = t_req_data.get("video_output_name_mode")
                                if output_name_mode:
                                    video_options["output_name_mode"] = output_name_mode
                            
                            # VideoGeneratorで動画生成
                            try:
                                post_process_progress.update({
                                    "message": f"動画生成を開始しています... (残り予約: {remaining}件)",
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
                            
                            task_queue.task_done()
                            continue
                        
                        # ===== Export Targets (Bicycle / Overtaken) Logic =====
                        if t_action in ["export_targets_csv", "export_targets_excel"]:
                            # 1. Identify Target Runs based on t_mode
                            target_runs = []
                            from ..modules.db_manager import list_folder_batches, get_run_ids_by_folder, get_all_run_ids, get_run_ids_by_condition

                            if t_mode == "all" or t_action == "process_all":
                                target_runs = get_all_run_ids()
                            
                            elif t_mode == "folder":
                                target_runs = []
                                for folder in t_input_folders:
                                    target_runs.extend(get_run_ids_by_folder(folder))
                                target_runs = sorted(list(set(target_runs)))
                                
                            elif t_mode == "run" and t_run_id:
                                target_runs = [int(t_run_id)]
                                
                            elif t_mode == "condition":
                                t_road_type = t_req_data.get("condition_road_type")
                                t_year = t_req_data.get("condition_year")
                                target_runs = get_run_ids_by_condition(road_type=t_road_type, process_year=t_year)
                            
                            if not target_runs:
                                post_process_progress.update({
                                    "status": "error",
                                    "message": "対象のデータが見つかりません"
                                })
                                task_queue.task_done()
                                continue

                            # 2. Export Data
                            from ..modules.comparative_report import export_target_vehicles
                            fmt = "csv" if t_action == "export_targets_csv" else "excel"
                            file_bytes = export_target_vehicles(target_runs, output_format=fmt)
                            
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
                                    "download_url": f"/exports/{filename}",
                                    "filename": filename
                                }
                            })
                            task_queue.task_done()
                            continue

                        # ===== Export Overtake Pair Summary CSV =====
                        if t_action == "export_overtake_pairs_csv":
                            target_runs = []
                            from ..modules.db_manager import get_run_ids_by_folder, get_all_run_ids, get_run_ids_by_condition

                            if t_mode == "all" or t_action == "process_all":
                                target_runs = get_all_run_ids()
                            elif t_mode == "folder":
                                for folder in t_input_folders:
                                    target_runs.extend(get_run_ids_by_folder(folder))
                                target_runs = sorted(list(set(target_runs)))
                            elif t_mode == "run" and t_run_id:
                                target_runs = [int(t_run_id)]
                            elif t_mode == "condition":
                                t_road_type = t_req_data.get("condition_road_type")
                                t_year = t_req_data.get("condition_year")
                                target_runs = get_run_ids_by_condition(road_type=t_road_type, process_year=t_year)

                            if not target_runs:
                                post_process_progress.update({
                                    "status": "error",
                                    "message": "対象のチE�Eタが見つかりません"
                                })
                                task_queue.task_done()
                                continue

                            from ..modules.overtake_pair_export import generate_overtake_pair_csv
                            file_bytes = generate_overtake_pair_csv(run_ids=target_runs)

                            filename = f"overtake_pairs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                            export_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'exports')
                            os.makedirs(export_dir, exist_ok=True)
                            file_path = os.path.join(export_dir, filename)

                            with open(file_path, "wb") as f:
                                f.write(file_bytes)

                            post_process_progress.update({
                                "status": "complete",
                                "percent": 100,
                                "message": "追い越しペアCSVを出力しました",
                                "results": {
                                    "download_url": f"/exports/{filename}",
                                    "filename": filename
                                }
                            })
                            task_queue.task_done()
                            continue

                        # ===== 既存のバッチ処理 =====
                        if t_mode == "folder" and t_input_folders and t_profile_name:
                            from ..modules.db_manager import update_folder_profiles
                            total_count = 0
                            for folder in t_input_folders:
                                count = update_folder_profiles(folder, t_profile_name, t_profile_scope)
                                total_count += count
                                post_process_progress["details"].append(f"プロファイルを適用しました: {folder} ({count} Runs)")
                        
                        # --- Apply Profile Logic (Single Run) ---
                        t_run_profile_name = t_req_data.get("run_profile_name")
                        if t_mode == "run" and t_run_id and t_run_profile_name:
                            from ..modules.db_manager_helpers import apply_calibration_profile_to_runs
                            try:
                                rid_int = int(t_run_id)
                                apply_calibration_profile_to_runs([rid_int], t_run_profile_name)
                                post_process_progress["details"].append(f"プロファイルを適用しました: Run {rid_int} -> {t_run_profile_name}")
                            except Exception as e:
                                print(f"Failed to apply profile to run {t_run_id}: {e}")

                        # --- Filter Batches Logic ---
                        from ..modules.db_manager import list_folder_batches, get_run_ids_by_folder
                        
                        batches = list_folder_batches()
                        valid_batches = []
                        
                        if t_mode == "folder" and t_input_folders:
                            # Filter for multiple folders
                            for folder in t_input_folders:
                                runs = get_run_ids_by_folder(folder)
                                if runs:
                                    valid_batches.append((folder, runs))
                                
                        elif t_action == "process_all" or (t_action == "all_postprocess" and t_mode == "all"):
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
                            rid = int(t_run_id)
                            found = False
                            for b in batches:
                                runs = get_run_ids_by_folder(b["folder_alias"])
                                if rid in runs:
                                    valid_batches.append((b["folder_alias"], [rid]))
                                    found = True
                                    break
                            if not found:
                                    valid_batches.append(("SingleRun", [rid]))

                        elif t_mode == "condition":
                            t_road_type = t_req_data.get("condition_road_type")
                            t_year = t_req_data.get("condition_year")
                            from ..modules.db_manager import get_run_ids_by_condition
                            runs = get_run_ids_by_condition(road_type=t_road_type, process_year=t_year)
                            if runs:
                                valid_batches.append((f"ConditionMatch ({len(runs)} runs)", runs))

                        total_tasks = len(valid_batches)
                        post_process_progress["total"] = total_tasks
                        all_run_ids = sorted({rid for _, runs in valid_batches for rid in runs})
                        
                        if total_tasks == 0:
                            post_process_progress.update({
                                "status": "complete",
                                "percent": 100,
                                "message": "処理対象が選択されていません。"
                            })
                            task_queue.task_done()
                            continue

                        post_process_progress["message"] = f"並列処理を開始: {total_tasks} バッチ (残り予約: {remaining}件)"
                        
                        try:
                            _cleanup_postprocess_logs()
                        except Exception:
                            current_app.logger.exception("Failed to cleanup old logs")

                        # Setup Manager Queue for granular progress
                        manager = multiprocessing.Manager()
                        sub_queue = manager.Queue()
                        
                        def queue_listener_task(q):
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
                                                if len(logs) >= 100:
                                                    logs = logs[-99:]
                                                logs.append(m_text)
                                                post_process_progress["logs"] = logs
                                                
                                except Exception:
                                    break

                        listener = threading.Thread(target=queue_listener_task, args=(sub_queue,))
                        listener.daemon = True
                        listener.start()
                        
                        # 2. Parallel Execution
                        completed_count = 0
                        aggregated_results = {
                            "total_overtakes": 0,
                            "images": []
                        }

                        with concurrent.futures.ProcessPoolExecutor() as executor:
                            future_to_alias = {
                                executor.submit(process_single_batch, alias, run_ids, output_dir=None, progress_queue=sub_queue): alias 
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
                                    
                                except Exception as exc:
                                    current_app.logger.error(f"Batch {alias} generated an exception: {exc}")
                                
                                completed_count += 1
                                percent = int((completed_count / total_tasks) * 100)
                                post_process_progress.update({
                                    "current": completed_count,
                                    "percent": percent
                                })
                        
                        # Stop listener
                        sub_queue.put("DONE")
                        listener.join()

                        summary_log_path = None
                        if all_run_ids:
                            try:
                                if t_action == "process_all" or (t_action == "all_postprocess" and t_mode == "all"):
                                    log_label = "all"
                                elif t_mode == "folder":
                                    log_label = f"folders_{len(t_input_folders)}"
                                elif t_mode == "condition":
                                    log_label = "condition"
                                else:
                                    log_label = "batch"
                                summary_log_path = _write_bulk_summary_log(all_run_ids, log_label)
                                if summary_log_path:
                                    post_process_progress["details"].append(
                                        f"Summary log saved: {summary_log_path}"
                                    )
                            except Exception as e:
                                current_app.logger.exception("Failed to write summary log")
                                post_process_progress["details"].append(
                                    f"Summary log failed: {e}"
                                )

                        # 3. Completion
                        post_process_progress.update({
                            "status": "complete",
                            "percent": 100,
                            "message": f"すべての並列処理が完了しました。(残り予約: {remaining}件)",
                            "results": {
                                "total_overtakes": aggregated_results["total_overtakes"],
                                "images": sorted(aggregated_results["images"])
                            }
                        })
                        
                        # Mark task as done in queue
                        task_queue.task_done()
                        if t_id and t_id in queue_registry:
                             del queue_registry[t_id]
                            
                    except Exception as e:
                        current_app.logger.exception("Post process background job failed")
                        post_process_progress.update({
                            "status": "error",
                            "message": f"エラーが発生しました: {str(e)}"
                        })
                        # Ensure we mark done so queue doesn't stall indefinitely on error?
                        # Actually task_done() is mostly for join(). Flow continues.
                        if not task_queue.empty():
                              task_queue.task_done()
                        if t_id and t_id in queue_registry:
                              del queue_registry[t_id]

                # Loop End
                current_processing_task_id = None
                is_worker_running = False

        # Start the worker thread
        thread = threading.Thread(target=worker_loop)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "message": "処理を開始しました。",
            "status": "started",
            "queue_size": current_q_size
        })
    else:
        # Worker already running, just queued
        return jsonify({
            "message": f"処理を予約しました (現在の待ち: {current_q_size}件)",
            "status": "queued",
            "queue_size": current_q_size
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


@main.route("/post_process/queue_status")
def queue_status_api():
    """Returns current processing and queued tasks"""
    # Convert registry to list
    queued = [
        val for key, val in queue_registry.items() 
        if val["status"] == "queued"
    ]
    # Sort by timestamp
    queued.sort(key=lambda x: x["submitted_at"])
    
    current = None
    if current_processing_task_id and current_processing_task_id in queue_registry:
        current = queue_registry[current_processing_task_id]
        
    return jsonify({
        "current_task": current,
        "queued_tasks": queued,
        "queue_size": len(queued)
    })
