
import os
import logging
import sqlite3
from collections import Counter
from datetime import datetime
from typing import Dict, Any, List

# Configure logger suitable for multiprocessing
# (Note: Standard logging setup might need adjustment for MP, but basic console output works)
logger = logging.getLogger(__name__)

def _postprocess_log_dir() -> str:
    log_dir = os.path.abspath(os.path.join(os.getcwd(), "log"))
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def _write_postprocess_log(run_id: int, lines: List[str]) -> None:
    log_dir = _postprocess_log_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"RAN_postprocess_run_{run_id}_{ts}.log")
    header = [
        "RAN Postprocess Log",
        f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Run ID: {run_id}",
        "-" * 60,
    ]
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(header + lines))
        f.write("\n")


def _fetch_overtake_by_stats(run_id: int) -> Dict[str, int]:
    from .db_manager import MAIN_DB_PATH, configure_connection

    stats = {
        "overtake_by_rows": 0,
        "overtake_by_second_rows": 0,
        "overtake_flag_rows": 0,
        "overtake_event_rows": 0,
    }
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="read")
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*)
            FROM Detection
            WHERE run_id = ?
              AND overtake_by IS NOT NULL
              AND TRIM(COALESCE(overtake_by, '')) != ''
            """,
            (run_id,),
        )
        stats["overtake_by_rows"] = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*)
            FROM Detection
            WHERE run_id = ?
              AND overtake_by_second IS NOT NULL
              AND TRIM(COALESCE(overtake_by_second, '')) != ''
            """,
            (run_id,),
        )
        stats["overtake_by_second_rows"] = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM Detection WHERE run_id = ? AND overtake = 1",
            (run_id,),
        )
        stats["overtake_flag_rows"] = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM OvertakeEvents WHERE run_id = ?",
            (run_id,),
        )
        stats["overtake_event_rows"] = cur.fetchone()[0]
    return stats


def _fetch_output_folder(run_id: int) -> str:
    from .db_manager import MAIN_DB_PATH, configure_connection

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="read")
        cur = conn.cursor()
        cur.execute("SELECT output_folder FROM ProcessLog WHERE run_id = ?", (run_id,))
        row = cur.fetchone()
        return row[0] if row and row[0] else ""


def process_single_batch(
    folder_alias: str, 
    run_ids: List[int],
    output_dir: str = None,
    progress_queue: Any = None
) -> Dict[str, Any]:
    """
    Worker function to process a single folder batch.
    Designed to be run in a separate process.
    
    Args:
        folder_alias: The alias of the folder being processed.
        run_ids: List of run_ids belonging to this folder.
        output_dir: Optional explicit output directory.
        progress_queue: Optional multiprocessing.Queue for status updates.
        
    Returns:
        Dictionary containing status and message.
    """
    result = {
        "folder_alias": folder_alias,
        "success": False,
        "csv_path": None,
        "bundle_path": None,
        "message": "",
        "overtake_stats": {"total": 0, "images": []}
    }
    
    try:
        from .all_save import create_combined_detection_csv, create_csv_bundle
        from .traffic_counter import TrafficCounter
        from .overtake import summarize_run_overtakes

        total_steps = len(run_ids) * 2 + 1 # counting + pipeline + csv/bundle
        current_step_count = 0

        # 0. Run Traffic Counting
        counter = TrafficCounter()
        total_car = 0
        total_bicycle = 0
        
        for i, run_id in enumerate(run_ids):
            if progress_queue:
                progress_queue.put({
                    "type": "progress",
                    "percent": int((current_step_count / total_steps) * 100),
                    "message": f"Run {run_id}: 交通量カウント中...",
                    "current": i + 1,
                    "total": len(run_ids),
                    "phase": "Traffic Counting"
                })

            try:
                count_result = counter.count(run_id)
                total_car += count_result.get("car", 0)
                total_bicycle += count_result.get("bicycle", 0)
                
                # 結果をログに送信
                if progress_queue and (count_result.get("car", 0) > 0 or count_result.get("bicycle", 0) > 0):
                    progress_queue.put({
                        "type": "log",
                        "message": f"[Run {run_id}] 交通量: 車 {count_result.get('car', 0)}台, 自転車 {count_result.get('bicycle', 0)}台"
                    })
            except Exception as e:
                logger.error(f"Traffic counting failed for run_id {run_id}: {e}")
            current_step_count += 1
        
        # 交通量カウント完了後の集計報告
        if progress_queue and (total_car > 0 or total_bicycle > 0):
            progress_queue.put({
                "type": "log",
                "message": f"📊 交通量合計: 車 {total_car}台, 自転車 {total_bicycle}台"
            })
        
        # 1. Apply Calibration Profiles before Pipeline
        from .inference import run_postprocess_pipeline_sync, apply_calibration_profile
        from .db_manager import get_calibration_profile_for_run
        
        for run_id in run_ids:
            try:
                profile_name = get_calibration_profile_for_run(run_id)
                if profile_name:
                    if progress_queue:
                        progress_queue.put({
                            "type": "progress",
                            "percent": int((current_step_count / total_steps) * 100),
                            "message": f"Run {run_id}: キャリブレーション適用中 ({profile_name})...",
                            "phase": "Calibration"
                        })
                    apply_calibration_profile(run_id, profile_name)
                    logger.info(f"Applied calibration profile '{profile_name}' to run_id {run_id}")
            except Exception as e:
                logger.error(f"Failed to apply calibration for run_id {run_id}: {e}")
        
        # 2. Run Analysis Pipeline (Overtake, Kinematics, etc.)
        pipeline_details = []
        for i, run_id in enumerate(run_ids):
            if progress_queue:
                progress_queue.put({
                    "type": "progress",
                    "percent": int((current_step_count / total_steps) * 100),
                    "message": f"Run {run_id}: 詳細解析実行中...",
                    "current": i + 1,
                    "total": len(run_ids),
                    "phase": "Post-Process Pipeline"
                })

            try:
                completed_steps, step_errors, skip_logs = run_postprocess_pipeline_sync(run_id)
                if step_errors:
                    logger.error(f"Pipeline errors for run_id {run_id}: {step_errors}")
                
                # Check for overtake image count in completed steps
                overtake_info = next((s for s in completed_steps if "追い越し(" in s), None)
                if overtake_info:
                    pipeline_details.append(f"Run {run_id}: {overtake_info}")
                
                # ログメッセージを送信
                if progress_queue:
                    for step in completed_steps:
                        progress_queue.put({
                            "type": "log",
                            "message": f"[Run {run_id}] {step}"
                        })
                
                # Collect Overtake Stats
                ov_summary = summarize_run_overtakes(run_id)
                if ov_summary:
                    result["overtake_stats"]["total"] += ov_summary.get("total", 0)
                    result["overtake_stats"]["images"].extend(ov_summary.get("images", []))

                try:
                    log_lines = []
                    if completed_steps:
                        log_lines.append(f"処理ステップ: {' / '.join(completed_steps)}")
                    if step_errors:
                        log_lines.append(f"エラー: {'; '.join(step_errors)}")

                    try:
                        from .xy_section_speed import get_measurement_length_for_run
                        section_len = get_measurement_length_for_run(run_id)
                        if section_len is not None:
                            log_lines.append(f"測定区間Y長さ(px): {section_len:.1f}")
                    except Exception:
                        pass

                    stats = _fetch_overtake_by_stats(run_id)
                    log_lines.append(
                        "追い越しby行数: "
                        f"{stats['overtake_by_rows']} "
                        f"(overtake_by_second: {stats['overtake_by_second_rows']})"
                    )
                    log_lines.append(
                        "追い越しフラグ: "
                        f"overtake=1 {stats['overtake_flag_rows']}, "
                        f"OvertakeEvents {stats['overtake_event_rows']}"
                    )
                    if stats["overtake_by_rows"] == 0:
                        log_lines.append("警告: このRunのovertake_byが空です。")

                    if skip_logs:
                        reason_counts = Counter(
                            item.get("reason", "Unknown") for item in skip_logs
                        )
                        log_lines.append("スキップ理由(上位5件):")
                        for reason, count in reason_counts.most_common(5):
                            log_lines.append(f"  - {reason}: {count}")
                        output_folder = _fetch_output_folder(run_id)
                        skip_path = os.path.join(
                            output_folder or os.getcwd(), "overtake_skipped.csv"
                        )
                        log_lines.append(f"スキップログCSV: {skip_path}")

                    _write_postprocess_log(run_id, log_lines)
                except Exception as log_exc:
                    logger.error(
                        f"Failed to write postprocess log for run_id {run_id}: {log_exc}"
                    )

            except Exception as e:
                 logger.error(f"Pipeline failed for run_id {run_id}: {e}")
                 if progress_queue:
                     progress_queue.put({
                         "type": "log",
                         "message": f"[Run {run_id}] エラー: {str(e)}"
                     })
            current_step_count += 1

        # 2. Create Combined CSV
        if progress_queue:
            progress_queue.put({
                "type": "progress",
                "percent": 95,
                "message": "CSVファイルとバンドルを作成中...",
                "phase": "Finalizing"
            })

        csv_path = create_combined_detection_csv(
             run_ids, 
             folder_alias=folder_alias,
             output_dir=output_dir
        )
        
        if not csv_path:
            result["message"] = "No CSV generated (data might be missing)."
            return result
            
        result["csv_path"] = csv_path
        
        # 2. Create Bundle
        bundle_path = create_csv_bundle(
            [csv_path],
            folder_alias=folder_alias,
            bundle_dir=os.path.dirname(csv_path) # Save bundle in same dir
        )
        
        if bundle_path:
            result["success"] = True
            result["bundle_path"] = bundle_path
            
            base_msg = f"Processed {len(run_ids)} runs. Created bundle: {os.path.basename(bundle_path)}"
            if pipeline_details:
                result["message"] = f"{base_msg} | {' '.join(pipeline_details)}"
            else:
                result["message"] = base_msg
        else:
            result["message"] = "Failed to create zip bundle."
            
    except Exception as e:
        logger.error(f"Error processing batch {folder_alias}: {e}")
        result["message"] = f"Error: {str(e)}"
        
    return result
