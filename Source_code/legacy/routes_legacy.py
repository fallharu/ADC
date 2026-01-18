# Source_code/routes.py
import os
import math
import statistics
import threading
import time
import glob
import json
import itertools
import re
import sqlite3
import csv
import io
import zipfile
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from dataclasses import dataclass, field
from collections import deque, OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Iterable

import cv2
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    current_app,
    Response,
    send_from_directory,
    send_file,
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# --- 必要なモジュールをインポート ---
from .modules import db_manager as dbm
from .modules.db_manager import (
    BASE_FILES,
    MAIN_DB_PATH,
    configure_connection,
    init_db,
    DatabaseInitializationError,
    get_database_sidecar_files,
    diagnose_sqlite_database,
    replace_main_database,
    create_new_main_database,
    show_recent_detections,
    get_all_process_logs,
    list_detection_runs,
    list_folder_batches,
    get_run_ids_in_range,
    get_run_ids_by_folder,
    reset_run_records,
    get_detection_search_fields,
    summarize_detection_columns,
    fetch_detections_for_frame,
    fetch_detection_for_group,
    fetch_detection_for_track,
    fetch_tire_detections_for_group,
    fetch_best_group_bbox,
    get_detection_frame_offset,
    get_first_detection_frame,
    get_first_bicycle_detection_frame,
    get_first_detection_frame_for_group,
    get_next_detection_frame_for_group,
    get_bicycle_orientation_counts,
    get_bicycle_class_aliases,
    convert_video_frame_to_detection_frame,
    convert_detection_frame_to_video_frame,
    insert_manual_overtake_event,
    list_manual_overtake_events,
    fetch_manual_overtake_event,
    fetch_manual_overtake_event_core,
    replace_manual_overtake_context_frames,
    update_manual_overtake_event,
    update_manual_lane_width,
    summarize_manual_overtake_events,
    apply_manual_overtake_flags,
    delete_manual_overtake_event,
    list_manual_overtake_event_cores,
    count_manual_overtake_events,
    record_manual_overtake_timeline_entry,
    list_manual_overtake_timeline_entries,
    mark_manual_overtake_timeline_processed,
    mark_manual_overtake_timeline_event_deleted,
    reset_manual_overtake_for_runs,
    clear_manual_run_progress,
    touch_manual_run_progress,
    enqueue_manual_context_backlog,
    list_manual_context_backlog,
    mark_manual_context_backlog_processed,
    count_manual_context_backlog,
    summarize_manual_context_backlog_by_status,
    ensure_manual_context_backlog_for_runs,
    MANUAL_OVERTAKE_CONTEXT_WINDOW,
    MANUAL_OVERTAKE_CONTEXT_COLUMNS,
    ensure_manual_annotation_schema,
    add_location,
    list_locations,
    get_location,
)
from .modules.class_filters import vehicle_allowed_classes
from .modules.inference import (
    apply_calibration_profile,
    process_video,
    process_video_folder,
    FolderProcessingResult,
    collect_video_files,
    FOLDER_VIDEO_EXTENSIONS,
    ResolvedFolderSettings,
    VideoProcessResult,
)
from .modules.group_id import assign_group_ids
from .modules.speed import assign_kinematics
from .modules.approach_distance import assign_approach_and_clearance
from .modules.overtake import assign_overtake, summarize_run_overtakes
from .modules.inter_vehicle_distance import analyze_proximity
from .modules.ttc_calculator import assign_ttc
from .modules.lane_distance import assign_lane_distance
from .modules.video_generator import (
    create_annotated_video,
    DEFAULT_VIDEO_OPTIONS,
    discover_font_files,
    normalize_video_options,
)
from .modules.video_buffer import manual_frame_buffer
from .modules.manual_metrics import (
    compute_clearance,
    compute_lane_distance,
    lane_scale_details_at_y,
    LANE_WIDTH_METERS,
    LANE_CONFIRMATION_HALF_SPAN_PX,
    restrict_lane_lines_vertical,
    select_bicycle_tire_measure_point,
    select_measure_point_from_candidates,
)

MANUAL_CONTEXT_WINDOW_FRAMES = MANUAL_OVERTAKE_CONTEXT_WINDOW
MANUAL_CONTEXT_CAPTURE_WINDOW = 0
MANUAL_LEGACY_CONTEXT_WINDOW = 150
from .modules.resource_monitor import capture_system_metrics, SystemMetrics
from .modules.all_save import (
    create_all_save,
    create_combined_detection_csv,
    create_csv_bundle,
)
from .modules.excel_exporter import (
    create_detection_excel,
    create_excel_bundle,
)
from .modules.folder_config import (
    load_folder_settings,
    save_folder_settings,
)
from .modules.statistics_exporter import (
    DEFAULT_STATISTICS_MODE,
    export_statistics_workbook,
    generate_statistics_preview,
)
from .modules.comparative_report import (
    ComparativeAnalyzer,
    StatisticalTestResult,
    compare_two_groups,
    compare_multiple_groups,
    get_available_years_and_road_types,
)
from .calibration_tool import (
    sanitize_profile_name,
    ensure_calibration_dir,
    get_run_video_info,
    load_calibration_payload,
    prepare_save_payload,
    prepare_lane_test_lines,
    calculate_lane_test_distances,
    save_calibration_payload,
    update_run_calibration_profile,
    delete_calibration_profile,
    probe_video,
    load_video_frame,
)

load_dotenv()
main = Blueprint("main", __name__)

ALLOWED_EXTENSIONS = {"mp4", "avi", "mov"}
PATH_LINK_FILENAME = ".pathlink"


class ManualOvertakeComputationError(Exception):
    """手動追い越しイベント計算時のエラーを表す。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ManualOvertakeComputation:
    """手動追い越しイベント計算結果を保持する。"""

    payload: dict[str, Any]
    context_frames: list[dict[str, Any]]
    detection_frame_num: int
    notices: list[str] = field(default_factory=list)


def _to_positive_float(value: Optional[float]) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric <= 0:
        return None
    return numeric


def _resolve_lane_width_m(value: object, *, default: float = LANE_WIDTH_METERS) -> float:
    resolved = _to_positive_float(value)
    if resolved is None:
        return default
    return resolved


def _harmonize_manual_distance_units(
    distance_map: Dict[str, Dict[str, Optional[float]]],
    *,
    lane_width_px: Optional[float] = None,
    cm_per_px: Optional[float] = None,
    lane_width_m: float = LANE_WIDTH_METERS,
    overtaker_px: Optional[float] = None,
) -> Optional[float]:
    """距離(cm)の整合性を保つために共通スケールを適用する。"""

    lane_width_px_val = _to_positive_float(lane_width_px)
    cm_per_px_val = _to_positive_float(cm_per_px)
    overtaker_entry = distance_map.get("overtaker")
    overtaker_px_val = _to_positive_float(overtaker_px) if overtaker_px is not None else None

    if lane_width_px_val and overtaker_entry:
        if overtaker_px_val is None:
            overtaker_px_val = _to_positive_float(overtaker_entry.get("px"))

        if overtaker_px_val is not None:
            overtaker_px_val = min(overtaker_px_val, lane_width_px_val)
            ratio = cm_per_px_val
            if ratio is None:
                lane_width_cm = lane_width_m * 100.0 if lane_width_m else None
                if lane_width_cm:
                    ratio = lane_width_cm / lane_width_px_val

            if ratio and ratio > 0:
                base_cm = overtaker_px_val * ratio
                overtaker_entry["px"] = overtaker_px_val
                overtaker_entry["cm"] = base_cm
                overtaker_entry["m"] = base_cm / 100.0
                
                raw_ratio = (overtaker_px_val / lane_width_px_val) * 100.0
                is_inner = overtaker_entry.get("is_inner", True)
                if not is_inner:
                    # 外側の場合は100%以上にする (表示ロジックで "-" になるように)
                    overtaker_entry["px_ratio"] = 100.0 + raw_ratio
                else:
                    overtaker_entry["px_ratio"] = raw_ratio

                remaining_px = lane_width_px_val - overtaker_px_val
                remaining_px = max(remaining_px, 0.0)
                overtaken_entry = distance_map.get("overtaken")
                if overtaken_entry is not None:
                    overtaken_entry["px"] = remaining_px
                    overtaken_entry["cm"] = remaining_px * ratio
                    overtaken_entry["m"] = overtaken_entry["cm"] / 100.0
                    
                    ov_raw_ratio = (remaining_px / lane_width_px_val) * 100.0 if lane_width_px_val else None
                    ov_is_inner = overtaken_entry.get("is_inner", True)
                    if not ov_is_inner and ov_raw_ratio is not None:
                        overtaken_entry["px_ratio"] = 100.0 + ov_raw_ratio
                    else:
                        overtaken_entry["px_ratio"] = ov_raw_ratio

                clearance_entry = distance_map.get("clearance")
                if clearance_entry is not None:
                    clearance_px = _to_positive_float(clearance_entry.get("px"))
                    if clearance_px is not None:
                        clearance_entry["cm"] = clearance_px * ratio
                        clearance_entry["m"] = clearance_entry["cm"] / 100.0
                        clearance_entry["px_ratio"] = (
                            (clearance_px / lane_width_px_val) * 100.0
                        )
                    else:
                        clearance_entry["px_ratio"] = None

                return ratio

    base_entry = overtaker_entry
    base_px = _to_positive_float(base_entry.get("px")) if base_entry else None
    base_cm = _to_positive_float(base_entry.get("cm")) if base_entry else None
    base_ratio: Optional[float] = None

    if base_px and base_cm:
        base_ratio = base_cm / base_px

    best_px = base_px or 0.0
    if base_ratio is None or base_ratio <= 0:
        for entry in distance_map.values():
            px_val = _to_positive_float(entry.get("px"))
            cm_val = _to_positive_float(entry.get("cm"))
            if px_val is None or cm_val is None:
                continue
            ratio = cm_val / px_val if px_val else None
            if ratio and ratio > 0 and px_val >= best_px:
                best_px = px_val
                base_ratio = ratio
                base_px = px_val

    if base_ratio is None or base_ratio <= 0:
        # 比率を導出できない場合は比率情報のみリセットする
        for entry in distance_map.values():
            entry["px_ratio"] = None
        return None

    if base_entry is not None:
        if base_px and base_px > 0:
            is_inner = base_entry.get("is_inner", True)
            base_entry["px_ratio"] = 100.0 if is_inner else 200.0 # Force outer if base
        else:
            base_entry["px_ratio"] = None

    for key, entry in distance_map.items():
        px_val = _to_positive_float(entry.get("px"))
        if px_val is None:
            entry["px_ratio"] = None
            continue
        cm_val = px_val * base_ratio
        entry["cm"] = cm_val
        entry["m"] = cm_val / 100.0
        if base_px and base_px > 0:
            entry["px_ratio"] = (px_val / base_px) * 100.0
        elif key == "overtaker":
            entry["px_ratio"] = 100.0
        else:
            entry["px_ratio"] = None

    return base_ratio


def _select_core_context_frame(
    frames: Sequence[Mapping[str, Any]]
) -> Optional[dict[str, Any]]:
    """offset=0 のコンテキスト行を抽出する。"""

    for frame in frames:
        if not isinstance(frame, Mapping):
            continue
        offset_value = frame.get("offset_frames")
        try:
            offset_int = int(offset_value)
        except (TypeError, ValueError):
            continue
        if offset_int == 0:
            return dict(frame)
    return None


def _build_manual_context_from_event(
    event_payload: Mapping[str, Any],
    frame_num: int,
) -> Optional[dict[str, Any]]:
    """イベント本体から最小限のコンテキスト行を生成する。"""

    if not event_payload:
        return None

    context_row: dict[str, Any] = {}
    for column in MANUAL_OVERTAKE_CONTEXT_COLUMNS:
        if column in {"context_id", "manual_event_id", "created_at"}:
            continue
        if column == "offset_frames":
            context_row[column] = 0
            continue
        if column == "frame_num":
            context_row[column] = event_payload.get("frame_num", frame_num)
            continue
        if column in event_payload:
            context_row[column] = event_payload.get(column)

    context_row.setdefault("frame_num", frame_num)
    context_row.setdefault("video_time_s", event_payload.get("video_time_s"))
    context_row.setdefault("overtaker_group_id", event_payload.get("overtaker_group_id"))
    context_row.setdefault("overtaken_group_id", event_payload.get("overtaken_group_id"))

    if (
        context_row.get("overtaker_group_id") is None
        or context_row.get("overtaken_group_id") is None
    ):
        return None

    return context_row


def _save_manual_overtake_context_frames(
    manual_event_id: int,
    frames: Sequence[Mapping[str, Any]],
    event_payload: Mapping[str, Any],
    frame_num: int,
    *,
    label: Optional[str] = None,
) -> tuple[bool, list[str]]:
    """コンテキスト行を保存し、失敗時は追い越しフレームのみを残す。"""

    label_text = label or f"イベントID {manual_event_id}"
    warnings: list[str] = []
    normalized_frames: list[dict[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, Mapping):
            continue
        frame_copy = dict(frame)
        offset_raw = frame_copy.get("offset_frames")
        try:
            offset_val = int(offset_raw) if offset_raw is not None else 0
        except (TypeError, ValueError):
            offset_val = 0
        frame_copy["offset_frames"] = offset_val
        normalized_frames.append(frame_copy)

    if not normalized_frames:
        fallback_row = _build_manual_context_from_event(event_payload, frame_num)
        if fallback_row is None:
            warnings.append(
                f"{label_text}: 追い越しフレームを生成できなかったため、保存対象がありません。"
            )
            return False, warnings
        normalized_frames = [fallback_row]
        warnings.append(
            f"{label_text}: コンテキストが見つからなかったため、追い越しフレームのみ保存しました。"
        )

    try:
        replace_manual_overtake_context_frames(manual_event_id, normalized_frames)
        return True, warnings
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to save manual overtake context frames")
        warnings.append(
            f"{label_text}: 前後フレーム情報の保存に失敗しました ({exc})"
        )

    fallback_row = _select_core_context_frame(normalized_frames)
    if fallback_row is None:
        fallback_row = _build_manual_context_from_event(event_payload, frame_num)

    if fallback_row is None:
        warnings.append(
            f"{label_text}: 追い越しフレームの保存対象を生成できませんでした。"
        )
        return False, warnings

    try:
        replace_manual_overtake_context_frames(manual_event_id, [fallback_row])
    except Exception as fallback_exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception(
            "Failed to save fallback manual overtake context frame"
        )
        warnings.append(
            f"{label_text}: 追い越しフレームの保存にも失敗しました ({fallback_exc})"
        )
        return False, warnings

    warnings.append(f"{label_text}: 追い越しフレームのみ保存しました。")
    return True, warnings


def _backup_manual_overtake_timing(
    run_id: int,
    event_id: int,
    event_payload: Mapping[str, Any],
) -> Optional[str]:
    """動画単位で手動追い越しタイミングをCSVバックアップする。"""

    upload_folder = current_app.config.get("UPLOAD_FOLDER", "uploads")
    run_info = get_run_video_info(run_id, upload_folder)
    if not run_info:
        return "動画情報を取得できずCSVバックアップをスキップしました。"

    filename = run_info.get("filename") or f"run_{run_id}"
    stem = Path(filename).stem or f"run_{run_id}"
    backup_dir = Path("log") / "manual_overtake"
    backup_dir.mkdir(parents=True, exist_ok=True)
    csv_path = backup_dir / f"{stem}_manual_overtake.csv"

    frame_value = event_payload.get("frame_num")
    video_time = event_payload.get("video_time_s")
    overtaker_gid = event_payload.get("overtaker_group_id")
    overtaken_gid = event_payload.get("overtaken_group_id")
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        is_new = not csv_path.exists() or csv_path.stat().st_size == 0
        with csv_path.open("a", encoding="utf-8", newline="") as csv_file:
            writer = csv.writer(csv_file)
            if is_new:
                writer.writerow(
                    [
                        "event_id",
                        "run_id",
                        "frame_num",
                        "video_time_s",
                        "overtaker_group_id",
                        "overtaken_group_id",
                        "created_at_utc",
                    ]
                )
            writer.writerow(
                [
                    event_id,
                    run_id,
                    frame_value,
                    video_time,
                    overtaker_gid,
                    overtaken_gid,
                    timestamp,
                ]
            )
    except Exception as exc:  # pragma: no cover - safety net
        current_app.logger.exception("Failed to back up manual overtake CSV")
        return f"CSVバックアップに失敗しました ({exc})"

    return None


def _process_manual_context_backlog(
    run_ids: Optional[Sequence[int]] = None,
    *,
    limit: Optional[int] = None,
    group_presence_context: bool = False,
) -> tuple[int, list[str], dict[int, int]]:
    """追い越しフレーム後処理キューを処理する。"""

    backlog_entries = list_manual_context_backlog(run_ids, limit=limit)
    processed = 0
    notices: list[str] = []

    if not backlog_entries:
        remaining = count_manual_context_backlog(run_ids)
        return processed, notices, remaining

    app = current_app._get_current_object()
    logger = app.logger

    def _distance_in_meters(entry: Mapping[str, Any], prefix: str) -> Optional[float]:
        meter_value = _float_or_none(entry.get(f"{prefix}_line_distance_m"))
        if meter_value is not None:
            return meter_value

        cm_value = _float_or_none(entry.get(f"{prefix}_line_distance_cm"))
        if cm_value is not None:
            return cm_value / 100

        px_value = _float_or_none(entry.get(f"{prefix}_line_distance_px"))
        ratio_value = _float_or_none(entry.get("lane_width_cm_per_px"))
        if px_value is not None and ratio_value is not None:
            return (px_value * ratio_value) / 100
        return None

    def _clearance_in_meters(entry: Mapping[str, Any]) -> Optional[float]:
        meter_value = _float_or_none(entry.get("clearance_distance_m"))
        if meter_value is not None:
            return meter_value

        cm_value = _float_or_none(entry.get("clearance_distance_cm"))
        if cm_value is not None:
            return cm_value / 100

        px_value = _float_or_none(entry.get("clearance_distance_px"))
        ratio_value = _float_or_none(entry.get("lane_width_cm_per_px"))
        if px_value is not None and ratio_value is not None:
            return (px_value * ratio_value) / 100
        return None

    def _format_summary(label: str, values: Sequence[float]) -> Optional[str]:
        if not values:
            return None
        median_val = statistics.median(values)
        return (
            f"{label} 中央値 {median_val:.2f} m / 最大 {max(values):.2f} m / 最小 {min(values):.2f} m"
        )

    def _build_distance_summary(frames: Sequence[Mapping[str, Any]]) -> Optional[str]:
        if not frames:
            return None
        lane_values: list[float] = []
        clearance_values: list[float] = []

        for frame in frames:
            lane_candidates = (
                _distance_in_meters(frame, "overtaker"),
                _distance_in_meters(frame, "overtaken"),
            )
            for candidate in lane_candidates:
                if candidate is not None:
                    lane_values.append(candidate)

            clearance_val = _clearance_in_meters(frame)
            if clearance_val is not None:
                clearance_values.append(clearance_val)

        lane_summary = _format_summary("白線距離", lane_values)
        clearance_summary = _format_summary("離隔距離", clearance_values)

        summary_parts = [part for part in (lane_summary, clearance_summary) if part]
        if not summary_parts:
            return None

        return " / ".join(summary_parts)

    def _entry_label(entry: Mapping[str, Any]) -> str:
        manual_event_id = entry.get("manual_event_id")
        return f"イベントID {manual_event_id}" if manual_event_id else "イベント"

    def _handle_entry(entry: Mapping[str, Any]) -> tuple[Mapping[str, Any], bool, list[str], Optional[str]]:
        manual_event_id = entry.get("manual_event_id")
        frame_num = entry.get("frame_num")
        event_payload = entry.get("event_payload") or {}
        context_frames = entry.get("context_frames") or []
        label = _entry_label(entry)

        run_value = entry.get("run_id")
        try:
            run_int = int(run_value)
            frame_int = int(frame_num)
        except (TypeError, ValueError):
            run_int = None
            frame_int = None

        recompute_messages: list[str] = []
        detection_frame_num: Optional[int] = None

        try:
            overtaker_int = int(event_payload.get("overtaker_group_id"))
            overtaken_int = int(event_payload.get("overtaken_group_id"))
        except (TypeError, ValueError):
            overtaker_int = None
            overtaken_int = None

        if None in (run_int, frame_int, overtaker_int, overtaken_int):
            notice = f"{label}: Run/Frame/Group情報が不足しているため後処理できませんでした。"
            return entry, False, [notice], notice

        actions_taken, warnings, fatal = _prepare_manual_overtake_dependencies(run_int)
        if actions_taken:
            recompute_messages.append(
                f"{label}: 前提計算を実行しました ({', '.join(actions_taken)})"
            )
        recompute_messages.extend(warnings)
        if fatal:
            notice = f"{label}: 後処理に必要な検出が不足しています。"
            return entry, False, recompute_messages + [notice], notice

        try:
            recomputation = _compute_manual_overtake_event_data(
                run_int,
                frame_int,
                overtaker_int,
                overtaken_int,
                notes=event_payload.get("notes"),
                context_window=0,
                compute_lane_metrics=True,
                lane_width_m=event_payload.get("lane_width_m"),
                group_presence_context=group_presence_context,
            )
            detection_frame_num = recomputation.detection_frame_num
        except ManualOvertakeComputationError as exc:
            recompute_messages.append(
                f"{label}: 追い越しフレームの再計算に失敗しました ({exc})"
            )
            recomputation = None
        except Exception as exc:  # pragma: no cover - safety net
            logger.exception("Failed to recompute manual overtake frame")
            recompute_messages.append(
                f"{label}: 追い越しフレーム再計算中にエラーが発生しました ({exc})"
            )
            recomputation = None

        if recomputation:
            if recomputation.context_frames:
                context_frames = recomputation.context_frames
            event_payload = recomputation.payload
            if recomputation.notices:
                recompute_messages.extend(
                    notice for notice in recomputation.notices if notice
                )

        distance_summary = _build_distance_summary(context_frames)
        if distance_summary:
            recompute_messages.append(
                f"{label}: {distance_summary} (対象 {len(context_frames)} フレーム)"
            )
        else:
            recompute_messages.append(
                f"{label}: 追い越しフレームを再計算するためのRun/グループ情報が不足しています。"
            )

        if manual_event_id:
            try:
                update_manual_overtake_event(int(manual_event_id), event_payload)
            except Exception as exc:  # pragma: no cover - safety net
                recompute_messages.append(
                    f"{label}: イベント本体の更新に失敗しました ({exc})"
                )
        else:
            notice = f"{label}: manual_event_id が不明なため保存できませんでした。"
            return entry, False, recompute_messages + [notice], notice

        try:
            context_saved, context_notices = _save_manual_overtake_context_frames(
                manual_event_id,
                context_frames,
                event_payload,
                frame_num,
                label=label,
            )
        except Exception as exc:  # pragma: no cover - safety net
            logger.exception("Failed to process manual context backlog")
            context_saved = False
            context_notices = [f"{label}: 後処理中にエラーが発生しました ({exc})"]

        if manual_event_id is not None:
            try:
                record_manual_overtake_timeline_entry(
                    run_int,
                    frame_int,
                    overtaker_int,
                    overtaken_int,
                    notes=event_payload.get("notes"),
                    last_event_id=int(manual_event_id),
                )
            except Exception as exc:  # pragma: no cover - safety net
                logger.exception("Failed to update manual timeline during context processing")
                recompute_messages.append(
                    f"{label}: タイムラインの更新に失敗しました ({exc})"
                )

        if detection_frame_num is not None:
            try:
                flags_applied = apply_manual_overtake_flags(
                    run_int,
                    detection_frame_num,
                    overtaker_int,
                    overtaken_int,
                )
                if not flags_applied:
                    recompute_messages.append(
                        f"{label}: 指定フレームの検出に追い越しフラグを設定できませんでした。"
                    )
            except Exception as exc:  # pragma: no cover - safety net
                logger.exception("Failed to update detection manual overtake flags during context processing")
                recompute_messages.append(
                    f"{label}: 追い越しフラグの更新に失敗しました ({exc})"
                )

        if manual_event_id is not None:
            try:
                _backup_manual_overtake_timing(run_int, int(manual_event_id), event_payload)
            except Exception as exc:  # pragma: no cover - safety net
                logger.exception("Failed to back up manual overtake timing during context processing")
                recompute_messages.append(
                    f"{label}: CSVバックアップに失敗しました ({exc})"
                )

        try:
            touch_manual_run_progress(run_int, annotation=True)
        except Exception:  # pragma: no cover - logging only
            logger.exception("Failed to update manual run annotation timestamp during context processing")

        if recompute_messages:
            context_notices = list(context_notices or []) + recompute_messages

        error_message = None
        if context_notices and not context_saved:
            error_message = "\n".join(context_notices)

        return entry, context_saved, list(context_notices or []), error_message

    def _handle_failure(entry: Mapping[str, Any], exc: BaseException) -> tuple[Mapping[str, Any], bool, list[str], str]:
        label = _entry_label(entry)
        logger.exception("Failed to process manual context backlog")
        message = f"{label}: 後処理中にエラーが発生しました ({exc})"
        return entry, False, [message], message

    def _resolve_worker_count(entry_count: int) -> int:
        configured = app.config.get("MANUAL_CONTEXT_BACKLOG_WORKERS")
        worker_limit: Optional[int] = None
        if configured is not None:
            try:
                worker_limit = int(configured)
            except (TypeError, ValueError):
                worker_limit = None
        if worker_limit is not None and worker_limit > 0:
            return max(1, min(entry_count, worker_limit))
        cpu_count = os.cpu_count() or 1
        default_workers = min(4, max(1, cpu_count))
        return max(1, min(entry_count, default_workers))

    entry_results: list[tuple[Mapping[str, Any], bool, list[str], Optional[str]]] = []
    entry_count = len(backlog_entries)
    worker_count = _resolve_worker_count(entry_count)

    if entry_count > 1 and worker_count > 1:
        def _run_with_context(entry: Mapping[str, Any]) -> tuple[Mapping[str, Any], bool, list[str], Optional[str]]:
            with app.app_context():
                return _handle_entry(entry)

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {executor.submit(_run_with_context, entry): entry for entry in backlog_entries}
            for future in as_completed(future_map):
                entry = future_map[future]
                try:
                    entry_results.append(future.result())
                except Exception as exc:  # pragma: no cover - safety net
                    entry_results.append(_handle_failure(entry, exc))
    else:
        for entry in backlog_entries:
            entry_results.append(_handle_entry(entry))

    for entry, context_saved, context_notices, error_message in entry_results:
        if context_notices:
            notices.extend(context_notices)
        try:
            mark_manual_context_backlog_processed(
                entry.get("backlog_id"),
                success=context_saved,
                error_message=error_message,
            )
        except Exception:  # pragma: no cover - logging only
            logger.exception("Failed to update context backlog status")
        if context_saved:
            processed += 1

    remaining = count_manual_context_backlog(run_ids)
    return processed, notices, remaining


def _execute_manual_context_processing(
    run_ids: Sequence[int],
    *,
    limit: Optional[int] = None,
    ensure_missing: bool = True,
) -> dict[str, Any]:
    """追い越しフレーム後処理を実行し、結果サマリーを返す。"""

    normalized_runs = _normalize_run_ids(list(run_ids))

    limit_value: Optional[int] = None
    if limit is not None:
        try:
            candidate = int(limit)
        except (TypeError, ValueError):
            candidate = None
        else:
            if candidate > 0:
                limit_value = candidate

    result: dict[str, Any] = {
        "run_ids": normalized_runs,
        "batch_limit": limit_value,
        "ensure_missing": bool(ensure_missing),
        "enqueued": 0,
        "enqueued_event_ids": [],
        "ensure_error": None,
        "pending_before": 0,
        "processed": 0,
        "remaining": {},
        "remaining_total": 0,
        "notices": [],
        "warnings": [],
    }

    if not normalized_runs:
        return result

    logger = getattr(current_app, "logger", None)

    if ensure_missing:
        try:
            enqueued, enqueued_ids = ensure_manual_context_backlog_for_runs(
                normalized_runs, force_requeue=True
            )
        except Exception as exc:  # pragma: no cover - runtime safeguard
            if logger is not None:
                logger.exception("Failed to enqueue manual context backlog before manual process")
            result["ensure_error"] = str(exc)
            enqueued = 0
            enqueued_ids = []
        result["enqueued"] = int(enqueued or 0)
        normalized_enqueued: list[int] = []
        for candidate in list(enqueued_ids or [])[:50]:
            try:
                normalized_enqueued.append(int(candidate))
            except (TypeError, ValueError):
                continue
        result["enqueued_event_ids"] = normalized_enqueued

    summary_before = count_manual_context_backlog(normalized_runs or None)
    pending_before = sum(int(value or 0) for value in summary_before.values())
    result["pending_before"] = pending_before

    if pending_before > 0:
        processed, notices, remaining = _process_manual_context_backlog(
            normalized_runs,
            limit=limit_value,
            group_presence_context=True,
        )
        result["processed"] = int(processed or 0)
        result["notices"] = [str(notice) for notice in (notices or []) if notice]
        normalized_remaining: dict[int, int] = {}
        for key, value in (remaining or {}).items():
            try:
                normalized_key = int(key)
            except (TypeError, ValueError):
                continue
            try:
                normalized_value = int(value or 0)
            except (TypeError, ValueError):
                normalized_value = 0
            normalized_remaining[normalized_key] = normalized_value
        result["remaining"] = normalized_remaining
    else:
        normalized_summary: dict[int, int] = {}
        for key, value in (summary_before or {}).items():
            try:
                normalized_key = int(key)
            except (TypeError, ValueError):
                continue
            try:
                normalized_value = int(value or 0)
            except (TypeError, ValueError):
                normalized_value = 0
            normalized_summary[normalized_key] = normalized_value
        result["remaining"] = normalized_summary

    result["remaining_total"] = sum(int(value or 0) for value in result["remaining"].values())

    if result["ensure_error"]:
        result["warnings"].append(
            f"後処理対象イベントの確認に失敗しました: {result['ensure_error']}"
        )

    return result


def _apply_manual_distance_ratios(target: Dict[str, Any]) -> None:
    """白線距離・離隔距離のcm換算と比率情報を整備する。"""

    distance_map = {
        "overtaker": {
            "px": target.get("overtaker_line_distance_px"),
            "cm": target.get("overtaker_line_distance_cm"),
            "m": target.get("overtaker_line_distance_m"),
        },
        "overtaken": {
            "px": target.get("overtaken_line_distance_px"),
            "cm": target.get("overtaken_line_distance_cm"),
            "m": target.get("overtaken_line_distance_m"),
        },
        "clearance": {
            "px": target.get("clearance_distance_px"),
            "cm": target.get("clearance_distance_cm"),
            "m": target.get("clearance_distance_m"),
        },
    }

    lane_width_px_reference = target.get("lane_width_px_reference")
    cm_per_px_reference = target.get("lane_width_cm_per_px")
    overtaker_px_value = target.get("overtaker_line_distance_px")

    ratio = _harmonize_manual_distance_units(
        distance_map,
        lane_width_px=lane_width_px_reference,
        cm_per_px=cm_per_px_reference,
        overtaker_px=overtaker_px_value,
    )

    if ratio and ratio > 0:
        target["lane_width_cm_per_px"] = ratio
        lane_width_px_val = _to_positive_float(lane_width_px_reference)
        if lane_width_px_val is not None:
            target["lane_width_cm_reference"] = lane_width_px_val * ratio

    overtaker_entry = distance_map.get("overtaker", {})
    target["overtaker_line_distance_cm"] = overtaker_entry.get("cm")
    target["overtaker_line_distance_m"] = overtaker_entry.get("m")
    target["overtaker_line_distance_px_ratio"] = overtaker_entry.get("px_ratio")

    overtaken_entry = distance_map.get("overtaken", {})
    target["overtaken_line_distance_cm"] = overtaken_entry.get("cm")
    target["overtaken_line_distance_m"] = overtaken_entry.get("m")
    target["overtaken_line_distance_px_ratio"] = overtaken_entry.get("px_ratio")

    clearance_entry = distance_map.get("clearance", {})
    target["clearance_distance_cm"] = clearance_entry.get("cm")
    target["clearance_distance_m"] = clearance_entry.get("m")
    target["clearance_distance_px_ratio"] = clearance_entry.get("px_ratio")


def _prepare_manual_events(events: Sequence[dict[str, Any]]) -> None:
    """取得済み手動追い越しイベントへ比率情報を適用する。"""

    for event in events:
        if not isinstance(event, dict):
            continue
        _apply_manual_distance_ratios(event)
        contexts = event.get("context_frames")
        if isinstance(contexts, list):
            for context in contexts:
                if isinstance(context, dict):
                    _apply_manual_distance_ratios(context)


POST_PROCESS_SUMMARY_COLUMNS: list[tuple[str, str]] = [
    ("group_id", "Group ID"),
    ("travel_direction", "進行方向"),
    ("pixel_speed", "ピクセル速度"),
    ("pixel_speed_frame", "ピクセル移動量(px/f)"),
    ("speed_km_h", "速度(km/h)"),
    ("acceleration_m_s2", "加速度(m/s²)"),
    ("acceleration_state", "加減速状態"),
    ("approach_partner_group_id", "接近相手Group"),
    ("approach_distance_m", "接近距離(m)"),
    ("approach_distance_px", "接近距離(px)"),
    ("clearance_distance_m", "離隔距離(m)"),
    ("clearance_distance_cm", "離隔距離(cm)"),
    ("clearance_distance_px", "離隔距離(px)"),
    ("overtake", "追い越しフラグ"),
    ("overtake_by", "追い越した車両Group"),
    ("overtake_by_second", "追い越された自転車Group"),
    ("overtake_window_offset", "追い越し±30fオフセット"),
    ("oncoming_flag", "対向車フラグ"),
    ("l_line_distance", "左白線距離(px)"),
    ("l_line_distance_m", "左白線距離(m)"),
    ("l_line_distance_cm", "左白線距離(cm)"),
    ("r_line_distance", "右白線距離(px)"),
    ("r_line_distance_m", "右白線距離(m)"),
    ("r_line_distance_cm", "右白線距離(cm)"),
    ("line_distance", "最短白線距離(px)"),
    ("line_distance_m", "最短白線距離(m)"),
    ("line_distance_cm", "最短白線距離(cm)"),
    ("lane_position_flag", "白線内外判定"),
    ("front_distance_m", "前方距離(m)"),
    ("front_vehicle_id", "前方車Group"),
    ("scale_pixels_per_meter", "スケール(px/m)"),
    ("x_pixels_per_meter", "横方向スケール(px/m)"),
    ("ttc_s", "TTC(秒)"),
]

MANUAL_OVERTAKE_EXPORT_COLUMNS: list[tuple[str, str]] = [
    ("manual_event_id", "ID"),
    ("run_id", "Run"),
    ("video_filename", "動画名"),
    ("frame_num", "フレーム"),
    ("video_time_s", "動画時間(s)"),
    ("overtaker_group_id", "追い越し側Group"),
    ("overtaker_track_id", "追い越し側トラックID"),
    ("overtaker_class_name", "追い越し側クラス"),
    ("overtaker_x1", "追い越し側BBOX x1"),
    ("overtaker_y1", "追い越し側BBOX y1"),
    ("overtaker_x2", "追い越し側BBOX x2"),
    ("overtaker_y2", "追い越し側BBOX y2"),
    ("overtaker_speed_km_h", "追い越し側時速(km/h)"),
    ("overtaker_pixel_speed", "追い越し側ピクセル速度(px/s)"),
    ("overtaker_pixel_speed_frame", "追い越し側ピクセル移動量(px/f)"),
    ("overtaker_measure_x", "追い越し側測定X(px)"),
    ("overtaker_measure_y", "追い越し側測定Y(px)"),
    ("overtaker_line_distance_m", "追い越し側 白線距離(m)"),
    ("overtaker_line_distance_cm", "追い越し側 白線距離(cm)"),
    ("overtaker_line_distance_px", "追い越し側 白線距離(px)"),
    ("overtaker_line_distance_px_ratio", "追い越し側 白線距離比率(%)"),
    ("overtaker_line_distance_px_ratio", "追い越し側 白線距離比率(%)"),
    ("overtaker_left_line_distance_m", "追い越し側 左白線距離(m)"),
    ("overtaker_left_line_distance_cm", "追い越し側 左白線距離(cm)"),
    ("overtaker_left_line_distance_px", "追い越し側 左白線距離(px)"),
    ("overtaker_right_line_distance_m", "追い越し側 右白線距離(m)"),
    ("overtaker_right_line_distance_cm", "追い越し側 右白線距離(cm)"),
    ("overtaker_right_line_distance_px", "追い越し側 右白線距離(px)"),
    ("overtaken_group_id", "追い越され側Group"),
    ("overtaken_track_id", "追い越され側トラックID"),
    ("overtaken_class_name", "追い越され側クラス"),
    ("overtaken_x1", "追い越され側BBOX x1"),
    ("overtaken_y1", "追い越され側BBOX y1"),
    ("overtaken_x2", "追い越され側BBOX x2"),
    ("overtaken_y2", "追い越され側BBOX y2"),
    ("overtaken_speed_km_h", "追い越され側時速(km/h)"),
    ("overtaken_pixel_speed", "追い越され側ピクセル速度(px/s)"),
    ("overtaken_pixel_speed_frame", "追い越され側ピクセル移動量(px/f)"),
    ("overtaken_measure_x", "追い越され側測定X(px)"),
    ("overtaken_measure_y", "追い越され側測定Y(px)"),
    ("overtaken_line_distance_m", "追い越され側 白線距離(m)"),
    ("overtaken_line_distance_cm", "追い越され側 白線距離(cm)"),
    ("overtaken_line_distance_px", "追い越され側 白線距離(px)"),
    ("overtaken_line_distance_px_ratio", "追い越され側 白線距離比率(%)"),
    ("overtaken_line_distance_px_ratio", "追い越され側 白線距離比率(%)"),
    ("overtaken_left_line_distance_m", "追い越され側 左白線距離(m)"),
    ("overtaken_left_line_distance_cm", "追い越され側 左白線距離(cm)"),
    ("overtaken_left_line_distance_px", "追い越され側 左白線距離(px)"),
    ("overtaken_right_line_distance_m", "追い越され側 右白線距離(m)"),
    ("overtaken_right_line_distance_cm", "追い越され側 右白線距離(cm)"),
    ("overtaken_right_line_distance_px", "追い越され側 右白線距離(px)"),
    ("approach_distance_m", "接近距離(m)"),
    ("approach_distance_px", "接近距離(px)"),
    ("clearance_distance_cm", "離隔距離(cm)"),
    ("clearance_distance_m", "離隔距離(m)"),
    ("clearance_distance_px", "離隔距離(px)"),
    ("clearance_distance_px_ratio", "離隔距離比率(%)"),
    ("created_at", "登録日時"),
    ("notes", "メモ"),
]

MANUAL_OVERTAKE_FLOAT_FORMATS: dict[str, str] = {
    "video_time_s": "0.00",
    "overtaker_speed_km_h": "0.0",
    "overtaker_x1": "0.0",
    "overtaker_y1": "0.0",
    "overtaker_x2": "0.0",
    "overtaker_y2": "0.0",
    "overtaker_pixel_speed_frame": "0.0",
    "overtaker_pixel_speed": "0.0",
    "overtaker_measure_x": "0.0",
    "overtaker_measure_y": "0.0",
    "overtaker_line_distance_m": "0.00",
    "overtaker_line_distance_cm": "0",
    "overtaker_line_distance_px": "0.0",
    "overtaker_line_distance_px_ratio": "0.0",
    "overtaker_left_line_distance_m": "0.00",
    "overtaker_left_line_distance_cm": "0",
    "overtaker_left_line_distance_px": "0.0",
    "overtaker_right_line_distance_m": "0.00",
    "overtaker_right_line_distance_cm": "0",
    "overtaker_right_line_distance_px": "0.0",
    "overtaken_speed_km_h": "0.0",
    "overtaken_x1": "0.0",
    "overtaken_y1": "0.0",
    "overtaken_x2": "0.0",
    "overtaken_y2": "0.0",
    "overtaken_pixel_speed_frame": "0.0",
    "overtaken_pixel_speed": "0.0",
    "overtaken_measure_x": "0.0",
    "overtaken_measure_y": "0.0",
    "overtaken_line_distance_m": "0.00",
    "overtaken_line_distance_cm": "0",
    "overtaken_line_distance_px": "0.0",
    "overtaken_left_line_distance_m": "0.00",
    "overtaken_left_line_distance_cm": "0",
    "overtaken_left_line_distance_px": "0.0",
    "overtaken_right_line_distance_m": "0.00",
    "overtaken_right_line_distance_cm": "0",
    "overtaken_right_line_distance_px": "0.0",
    "approach_distance_m": "0.00",
    "approach_distance_px": "0.0",
    "clearance_distance_cm": "0",
    "clearance_distance_m": "0.00",
    "clearance_distance_px": "0.0",
}

MANUAL_OVERTAKE_CSV_FORMATS: dict[str, str] = {
    "video_time_s": "{:.2f}",
    "overtaker_speed_km_h": "{:.1f}",
    "overtaker_x1": "{:.1f}",
    "overtaker_y1": "{:.1f}",
    "overtaker_x2": "{:.1f}",
    "overtaker_y2": "{:.1f}",
    "overtaker_pixel_speed": "{:.1f}",
    "overtaker_pixel_speed_frame": "{:.1f}",
    "overtaker_measure_x": "{:.1f}",
    "overtaker_measure_y": "{:.1f}",
    "overtaker_line_distance_m": "{:.2f}",
    "overtaker_line_distance_cm": "{:.0f}",
    "overtaker_line_distance_px": "{:.0f}",
    "overtaker_line_distance_px_ratio": "{:.1f}",
    "overtaker_left_line_distance_m": "{:.2f}",
    "overtaker_left_line_distance_cm": "{:.0f}",
    "overtaker_left_line_distance_px": "{:.0f}",
    "overtaker_right_line_distance_m": "{:.2f}",
    "overtaker_right_line_distance_cm": "{:.0f}",
    "overtaker_right_line_distance_px": "{:.0f}",
    "overtaken_speed_km_h": "{:.1f}",
    "overtaken_x1": "{:.1f}",
    "overtaken_y1": "{:.1f}",
    "overtaken_x2": "{:.1f}",
    "overtaken_y2": "{:.1f}",
    "overtaken_pixel_speed": "{:.1f}",
    "overtaken_pixel_speed_frame": "{:.1f}",
    "overtaken_measure_x": "{:.1f}",
    "overtaken_measure_y": "{:.1f}",
    "overtaken_line_distance_m": "{:.2f}",
    "overtaken_line_distance_cm": "{:.0f}",
    "overtaken_line_distance_px": "{:.0f}",
    "overtaken_line_distance_px_ratio": "{:.1f}",
    "overtaken_left_line_distance_m": "{:.2f}",
    "overtaken_left_line_distance_cm": "{:.0f}",
    "overtaken_left_line_distance_px": "{:.0f}",
    "overtaken_right_line_distance_m": "{:.2f}",
    "overtaken_right_line_distance_cm": "{:.0f}",
    "overtaken_right_line_distance_px": "{:.0f}",
    "approach_distance_m": "{:.2f}",
    "approach_distance_px": "{:.0f}",
    "clearance_distance_cm": "{:.0f}",
    "clearance_distance_m": "{:.2f}",
    "clearance_distance_px": "{:.0f}",
    "clearance_distance_px_ratio": "{:.1f}",
}

MANUAL_OVERTAKE_CONTEXT_EXPORT_COLUMNS: list[tuple[str, str]] = [
    ("manual_event_id", "イベントID"),
    ("run_id", "Run"),
    ("video_filename", "動画名"),
    ("offset_frames", "オフセットフレーム"),
    ("frame_num", "動画フレーム"),
    ("video_time_s", "動画時間(s)"),
    ("overtaker_group_id", "追い越し側Group"),
    ("overtaker_track_id", "追い越し側トラックID"),
    ("overtaker_auto_id", "追い越し側検出ID"),
    ("overtaker_class_name", "追い越し側クラス"),
    ("overtaker_x1", "追い越し側BBOX x1"),
    ("overtaker_y1", "追い越し側BBOX y1"),
    ("overtaker_x2", "追い越し側BBOX x2"),
    ("overtaker_y2", "追い越し側BBOX y2"),
    ("overtaker_speed_km_h", "追い越し側時速(km/h)"),
    ("overtaker_pixel_speed", "追い越し側ピクセル速度(px/s)"),
    ("overtaker_pixel_speed_frame", "追い越し側ピクセル移動量(px/f)"),
    ("overtaker_measure_x", "追い越し側測定X(px)"),
    ("overtaker_measure_y", "追い越し側測定Y(px)"),
    ("overtaker_line_distance_m", "追い越し側 白線距離(m)"),
    ("overtaker_line_distance_cm", "追い越し側 白線距離(cm)"),
    ("overtaker_line_distance_px", "追い越し側 白線距離(px)"),
    ("overtaker_left_line_distance_m", "追い越し側 左白線距離(m)"),
    ("overtaker_left_line_distance_cm", "追い越し側 左白線距離(cm)"),
    ("overtaker_left_line_distance_px", "追い越し側 左白線距離(px)"),
    ("overtaker_right_line_distance_m", "追い越し側 右白線距離(m)"),
    ("overtaker_right_line_distance_cm", "追い越し側 右白線距離(cm)"),
    ("overtaker_right_line_distance_px", "追い越し側 右白線距離(px)"),
    ("overtaken_group_id", "追い越され側Group"),
    ("overtaken_track_id", "追い越され側トラックID"),
    ("overtaken_auto_id", "追い越され側検出ID"),
    ("overtaken_class_name", "追い越され側クラス"),
    ("overtaken_x1", "追い越され側BBOX x1"),
    ("overtaken_y1", "追い越され側BBOX y1"),
    ("overtaken_x2", "追い越され側BBOX x2"),
    ("overtaken_y2", "追い越され側BBOX y2"),
    ("overtaken_speed_km_h", "追い越され側時速(km/h)"),
    ("overtaken_pixel_speed", "追い越され側ピクセル速度(px/s)"),
    ("overtaken_pixel_speed_frame", "追い越され側ピクセル移動量(px/f)"),
    ("overtaken_measure_x", "追い越され側測定X(px)"),
    ("overtaken_measure_y", "追い越され側測定Y(px)"),
    ("overtaken_line_distance_m", "追い越され側 白線距離(m)"),
    ("overtaken_line_distance_cm", "追い越され側 白線距離(cm)"),
    ("overtaken_line_distance_px", "追い越され側 白線距離(px)"),
    ("overtaken_left_line_distance_m", "追い越され側 左白線距離(m)"),
    ("overtaken_left_line_distance_cm", "追い越され側 左白線距離(cm)"),
    ("overtaken_left_line_distance_px", "追い越され側 左白線距離(px)"),
    ("overtaken_right_line_distance_m", "追い越され側 右白線距離(m)"),
    ("overtaken_right_line_distance_cm", "追い越され側 右白線距離(cm)"),
    ("overtaken_right_line_distance_px", "追い越され側 右白線距離(px)"),
    ("clearance_distance_m", "離隔距離(m)"),
    ("clearance_distance_cm", "離隔距離(cm)"),
    ("clearance_distance_px", "離隔距離(px)"),
    ("clearance_distance_px_ratio", "離隔距離比率(%)"),
]

MANUAL_OVERTAKE_GROUP_EXPORT_COLUMNS: list[tuple[str, str]] = [
    ("manual_event_id", "イベントID"),
    ("run_id", "Run"),
    ("video_filename", "動画名"),
    ("offset_frames", "オフセットフレーム"),
    ("frame_num", "動画フレーム"),
    ("video_time_s", "動画時間(s)"),
    ("role", "役割"),
    ("group_id", "Group ID"),
    ("partner_group_id", "相手Group"),
    ("track_id", "トラックID"),
    ("class_name", "クラス"),
    ("bbox_x1", "BBOX x1"),
    ("bbox_y1", "BBOX y1"),
    ("bbox_x2", "BBOX x2"),
    ("bbox_y2", "BBOX y2"),
    ("measure_x", "測定X(px)"),
    ("measure_y", "測定Y(px)"),
    ("line_distance_m", "白線距離(m)"),
    ("line_distance_cm", "白線距離(cm)"),
    ("line_distance_px", "白線距離(px)"),
    ("line_distance_px_ratio", "白線距離比率(%)"),
    ("lane_position_flag", "白線内外判定"),
    ("left_line_distance_m", "左白線距離(m)"),
    ("left_line_distance_cm", "左白線距離(cm)"),
    ("left_line_distance_px", "左白線距離(px)"),
    ("right_line_distance_m", "右白線距離(m)"),
    ("right_line_distance_cm", "右白線距離(cm)"),
    ("right_line_distance_px", "右白線距離(px)"),
    ("clearance_distance_m", "離隔距離(m)"),
    ("clearance_distance_cm", "離隔距離(cm)"),
    ("clearance_distance_px", "離隔距離(px)"),
    ("lane_width_m", "道幅(m)"),
]

MANUAL_OVERTAKE_GROUP_FIXED_EXPORT_COLUMNS: list[tuple[str, str]] = [
    ("manual_event_id", "イベントID"),
    ("run_id", "Run"),
    ("video_filename", "動画名"),
    ("offset_frames", "オフセットフレーム"),
    ("frame_num", "動画フレーム"),
    ("video_time_s", "動画時間(s)"),
    ("role", "役割"),
    ("group_id", "Group ID"),
    ("partner_group_id", "相手Group"),
    ("track_id", "トラックID"),
    ("class_name", "クラス"),
    ("bbox_x1", "BBOX x1"),
    ("bbox_y1", "BBOX y1"),
    ("bbox_x2", "BBOX x2"),
    ("bbox_y2", "BBOX y2"),
    ("measure_x", "測定X(px)"),
    ("measure_y", "測定Y(px)"),
    ("line_distance_m", "白線距離(m)"),
    ("line_distance_cm", "白線距離(cm)"),
    ("line_distance_px", "白線距離(px)"),
    ("line_distance_px_ratio", "白線距離比率(%)"),
    ("lane_position_flag", "白線内外判定"),
    ("right_line_distance_m", "右白線距離(m)"),
    ("right_line_distance_cm", "右白線距離(cm)"),
    ("right_line_distance_px", "右白線距離(px)"),
    ("bicycle_over_white_line", "自転車白線超過"),
    ("crossed_center_line", "中央線越え"),
    ("clearance_distance_m", "離隔距離(m)"),
    ("clearance_distance_cm", "離隔距離(cm)"),
    ("clearance_distance_px", "離隔距離(px)"),
    ("lane_width_m", "道幅(m)"),
]

MANUAL_OVERTAKE_CONTEXT_FLOAT_FORMATS: dict[str, str] = {
    "video_time_s": "0.00",
    "overtaker_speed_km_h": "0.0",
    "overtaker_x1": "0.0",
    "overtaker_y1": "0.0",
    "overtaker_x2": "0.0",
    "overtaker_y2": "0.0",
    "overtaker_pixel_speed": "0.0",
    "overtaker_pixel_speed_frame": "0.0",
    "overtaker_measure_x": "0.0",
    "overtaker_measure_y": "0.0",
    "overtaker_line_distance_m": "0.00",
    "overtaker_line_distance_cm": "0",
    "overtaker_line_distance_px": "0.0",
    "overtaker_left_line_distance_m": "0.00",
    "overtaker_left_line_distance_cm": "0",
    "overtaker_left_line_distance_px": "0.0",
    "overtaker_right_line_distance_m": "0.00",
    "overtaker_right_line_distance_cm": "0",
    "overtaker_right_line_distance_px": "0.0",
    "overtaken_speed_km_h": "0.0",
    "overtaken_x1": "0.0",
    "overtaken_y1": "0.0",
    "overtaken_x2": "0.0",
    "overtaken_y2": "0.0",
    "overtaken_pixel_speed": "0.0",
    "overtaken_pixel_speed_frame": "0.0",
    "overtaken_measure_x": "0.0",
    "overtaken_measure_y": "0.0",
    "overtaken_line_distance_m": "0.00",
    "overtaken_line_distance_cm": "0",
    "overtaken_line_distance_px": "0.0",
    "overtaken_line_distance_px_ratio": "0.0",
    "overtaken_left_line_distance_m": "0.00",
    "overtaken_left_line_distance_cm": "0",
    "overtaken_left_line_distance_px": "0.0",
    "overtaken_right_line_distance_m": "0.00",
    "overtaken_right_line_distance_cm": "0",
    "overtaken_right_line_distance_px": "0.0",
    "clearance_distance_m": "0.00",
    "clearance_distance_cm": "0",
    "clearance_distance_px": "0.0",
    "clearance_distance_px_ratio": "0.0",
    "line_distance_m": "0.00",
    "line_distance_cm": "0",
    "line_distance_px": "0.0",
    "line_distance_px_ratio": "0.0",
    "left_line_distance_m": "0.00",
    "left_line_distance_cm": "0",
    "left_line_distance_px": "0.0",
    "right_line_distance_m": "0.00",
    "right_line_distance_cm": "0",
    "right_line_distance_px": "0.0",
    "lane_width_m": "0.0",
}

MANUAL_OVERTAKE_GROUP_FLOAT_FORMATS: dict[str, str] = {
    "offset_frames": "0",
    "frame_num": "0",
    "video_time_s": "0.00",
    "bbox_x1": "0.0",
    "bbox_y1": "0.0",
    "bbox_x2": "0.0",
    "bbox_y2": "0.0",
    "measure_x": "0.0",
    "measure_y": "0.0",
    "line_distance_m": "0.00",
    "line_distance_cm": "0",
    "line_distance_px": "0.0",
    "line_distance_px_ratio": "0.0",
    "left_line_distance_m": "0.00",
    "left_line_distance_cm": "0",
    "left_line_distance_px": "0.0",
    "right_line_distance_m": "0.00",
    "right_line_distance_cm": "0",
    "right_line_distance_px": "0.0",
    "clearance_distance_m": "0.00",
    "clearance_distance_cm": "0",
    "clearance_distance_px": "0.0",
    "lane_width_m": "0.0",
}

MANUAL_OVERTAKE_CONTEXT_CSV_FORMATS: dict[str, str] = {
    "video_time_s": "{:.2f}",
    "overtaker_speed_km_h": "{:.1f}",
    "overtaker_x1": "{:.1f}",
    "overtaker_y1": "{:.1f}",
    "overtaker_x2": "{:.1f}",
    "overtaker_y2": "{:.1f}",
    "overtaker_pixel_speed": "{:.1f}",
    "overtaker_pixel_speed_frame": "{:.1f}",
    "overtaker_measure_x": "{:.1f}",
    "overtaker_measure_y": "{:.1f}",
    "overtaker_line_distance_m": "{:.2f}",
    "overtaker_line_distance_cm": "{:.0f}",
    "overtaker_line_distance_px": "{:.0f}",
    "overtaker_line_distance_px_ratio": "{:.1f}",
    "overtaker_left_line_distance_m": "{:.2f}",
    "overtaker_left_line_distance_cm": "{:.0f}",
    "overtaker_left_line_distance_px": "{:.0f}",
    "overtaker_right_line_distance_m": "{:.2f}",
    "overtaker_right_line_distance_cm": "{:.0f}",
    "overtaker_right_line_distance_px": "{:.0f}",
    "overtaken_speed_km_h": "{:.1f}",
    "overtaken_x1": "{:.1f}",
    "overtaken_y1": "{:.1f}",
    "overtaken_x2": "{:.1f}",
    "overtaken_y2": "{:.1f}",
    "overtaken_pixel_speed": "{:.1f}",
    "overtaken_pixel_speed_frame": "{:.1f}",
    "overtaken_measure_x": "{:.1f}",
    "overtaken_measure_y": "{:.1f}",
    "overtaken_line_distance_m": "{:.2f}",
    "overtaken_line_distance_cm": "{:.0f}",
    "overtaken_line_distance_px": "{:.0f}",
    "overtaken_line_distance_px_ratio": "{:.1f}",
    "overtaken_left_line_distance_m": "{:.2f}",
    "overtaken_left_line_distance_cm": "{:.0f}",
    "overtaken_left_line_distance_px": "{:.0f}",
    "overtaken_right_line_distance_m": "{:.2f}",
    "overtaken_right_line_distance_cm": "{:.0f}",
    "overtaken_right_line_distance_px": "{:.0f}",
    "clearance_distance_m": "{:.2f}",
    "clearance_distance_cm": "{:.0f}",
    "clearance_distance_px": "{:.0f}",
    "clearance_distance_px_ratio": "{:.1f}",
    "line_distance_m": "{:.2f}",
    "line_distance_cm": "{:.0f}",
    "line_distance_px": "{:.0f}",
    "line_distance_px_ratio": "{:.1f}",
    "left_line_distance_m": "{:.2f}",
    "left_line_distance_cm": "{:.0f}",
    "left_line_distance_px": "{:.0f}",
    "right_line_distance_m": "{:.2f}",
    "right_line_distance_cm": "{:.0f}",
    "right_line_distance_px": "{:.0f}",
    "lane_width_m": "{:.1f}",
}

DEFAULT_CLASS_CANDIDATES: list[str] = [
    "bicycle",
    "bike",
    "cyclist",
    "自転車",
    "car",
    "automobile",
    "車",
    "bus",
    "バス",
    "truck",
    "トラック",
    "バストラック",
]


def allowed_file(filename: str):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def sanitize_folder_alias(name: str) -> str:
    """アップロードフォルダに作成する登録名を安全な形式へ整形する。"""
    if not name:
        return ""
    # Windows の禁止文字やパス区切りを避けつつ、前後のスペースとピリオドを除去する
    sanitized = re.sub(r"[\\/:*?\"<>|]+", "_", name).strip()
    sanitized = sanitized.strip(".")
    if sanitized in {"", ".", ".."}:
        return ""
    return sanitized


def normalize_existing_folder_alias(name: str) -> str:
    """既存のフォルダエイリアス入力を正規化する。"""

    if not name:
        return ""
    normalized = name.strip()
    normalized = normalized.replace("\\", "/")
    normalized = re.sub(r"/+", "/", normalized)
    normalized = normalized.strip("/")
    if normalized in {"", ".", ".."}:
        return ""
    return normalized


def _extract_profile_name_candidate(value: Optional[str]) -> list[str]:
    """パスやエイリアスからプロファイル名の候補となるセグメントを抽出する。"""

    if not value:
        return []

    text = str(value).strip()
    if not text:
        return []

    normalized = text.replace("\\", "/").strip("/")
    if not normalized:
        return []

    segments = [segment for segment in normalized.split("/") if segment]
    if not segments:
        return []

    ignored = {"uploads", "upload", "videos", "video", "output", "outputs"}
    candidates: list[str] = []
    for segment in reversed(segments):
        lowered = segment.lower()
        if lowered in ignored:
            continue
        safe = sanitize_profile_name(segment)
        if safe:
            candidates.append(safe)
    return candidates


def _derive_default_profile_name(info: Dict[str, Any]) -> str:
    """キャリブレーションの既定プロファイル名をRun情報から推定する。"""

    candidates: list[str] = []

    for key in ("folder_alias", "output_folder", "source_path"):
        candidates.extend(_extract_profile_name_candidate(info.get(key)))

    filename = (info.get("filename") or "").strip()
    if filename:
        stem = os.path.splitext(filename)[0]
        safe_stem = sanitize_profile_name(stem)
        if safe_stem:
            candidates.append(safe_stem)

    for candidate in candidates:
        if candidate:
            return candidate

    return ""


def _canonicalize_folder_alias(alias: str, filename: str = "") -> str:
    """推論結果の出力先などに含まれる余分なセグメントを取り除いたフォルダ別名を返す。"""

    if not alias:
        return ""

    normalized = alias.replace("\\", "/").strip("/")
    if not normalized:
        return ""

    segments = [segment for segment in normalized.split("/") if segment]
    if not segments:
        return ""

    last_segment = segments[-1]
    _, ext = os.path.splitext(last_segment)
    if ext.lower() in FOLDER_VIDEO_EXTENSIONS:
        segments.pop()
    else:
        stem = os.path.splitext(filename)[0].strip().lower() if filename else ""
        last_lower = last_segment.lower()
        if stem and last_lower.startswith(stem):
            remainder = last_lower[len(stem) :]
            if remainder and remainder[0] in {"_", "-"} and any(ch.isdigit() for ch in remainder[1:]):
                segments.pop()

    return "/".join(segments)


def _split_profile_scope_entries(raw: str) -> list[str]:
    """サブフォルダ／動画指定の入力を正規化しつつ分割する。"""

    if not raw:
        return []

    entries: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[\r\n,;]+", raw):
        normalized = normalize_existing_folder_alias(part)
        if normalized and normalized not in seen:
            entries.append(normalized)
            seen.add(normalized)
    return entries


def _normalize_path_fragment(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("\\", "/")
    normalized = re.sub(r"/+", "/", normalized)
    normalized = normalized.strip("/")
    if not normalized:
        return None
    return normalized.lower()


def _relative_alias_from_path(
    raw_path: Optional[str],
    root_alias: str,
    filename: str,
) -> str:
    """パス情報からルート配下の相対エイリアスを推定する。"""

    if not raw_path:
        return ""

    normalized_path = str(raw_path).replace("\\", "/")
    segments = [segment for segment in normalized_path.split("/") if segment]
    if not segments:
        return ""

    filename_lower = (filename or "").strip().lower()
    if filename_lower and segments and segments[-1].lower() == filename_lower:
        segments = segments[:-1]
    if not segments:
        return ""

    root_segments = [segment for segment in (root_alias or "").split("/") if segment]
    if not root_segments:
        return ""

    lower_segments = [segment.lower() for segment in segments]
    lower_root = [segment.lower() for segment in root_segments]
    root_len = len(lower_root)
    if root_len == 0 or len(lower_segments) < root_len:
        return ""

    for idx in range(len(lower_segments) - root_len + 1):
        if lower_segments[idx : idx + root_len] == lower_root:
            remainder = segments[idx + root_len :]
            if remainder:
                return "/".join(remainder)
            return ""

    return ""


def _match_runs_to_scopes(
    run_ids: Sequence[int],
    scopes: Sequence[str],
    upload_folder: str,
) -> Tuple[list[int], dict[str, list[int]], list[str]]:
    """フォルダ／動画指定に一致するRun IDを抽出する。"""

    if not scopes:
        return list(run_ids), {}, []

    scope_info: list[tuple[str, str, bool]] = []
    video_exts = {ext.lower() for ext in FOLDER_VIDEO_EXTENSIONS}
    for scope in scopes:
        lowered = scope.lower()
        suffix = os.path.splitext(scope)[1].lower()
        is_file = bool(suffix and suffix in video_exts)
        scope_info.append((scope, lowered, is_file))

    match_map: dict[str, list[int]] = {scope: [] for scope in scopes}
    matched_set: set[int] = set()

    upload_root = upload_folder or ""

    for run_id in run_ids:
        try:
            info = get_run_video_info(run_id, upload_root)
        except Exception:
            info = None
        if not info:
            continue

        filename = (info.get("filename") or "").strip()
        filename_lower = filename.lower()

        alias_raw = info.get("folder_alias") or ""
        alias_norm = normalize_existing_folder_alias(alias_raw)
        alias_canonical = normalize_existing_folder_alias(
            _canonicalize_folder_alias(alias_raw, filename)
        )
        alias_lower = alias_norm.lower() if alias_norm else ""
        alias_canonical_lower = alias_canonical.lower() if alias_canonical else ""

        candidates: set[str] = set()
        if alias_lower:
            candidates.add(alias_lower)
        if alias_canonical_lower:
            candidates.add(alias_canonical_lower)
        if filename_lower:
            candidates.add(filename_lower)
            if alias_lower:
                candidates.add(f"{alias_lower}/{filename_lower}")
            if alias_canonical_lower:
                candidates.add(f"{alias_canonical_lower}/{filename_lower}")

        for key in ("source_path", "path"):
            normalized = _normalize_path_fragment(info.get(key))
            if normalized:
                candidates.add(normalized)
                if upload_root:
                    try:
                        rel = os.path.relpath(info.get(key), upload_root)
                    except (TypeError, ValueError):
                        rel = None
                    if rel:
                        rel_normalized = _normalize_path_fragment(rel)
                        if rel_normalized:
                            candidates.add(rel_normalized)

        for scope_original, scope_lower, is_file in scope_info:
            matched = False
            if is_file:
                if scope_lower in candidates:
                    matched = True
            else:
                if alias_lower and (
                    alias_lower == scope_lower or alias_lower.startswith(f"{scope_lower}/")
                ):
                    matched = True
                if (
                    not matched
                    and alias_canonical_lower
                    and (
                        alias_canonical_lower == scope_lower
                        or alias_canonical_lower.startswith(f"{scope_lower}/")
                    )
                ):
                    matched = True
                if not matched:
                    for candidate in candidates:
                        if candidate == scope_lower or candidate.startswith(f"{scope_lower}/"):
                            matched = True
                            break

            if matched:
                match_map[scope_original].append(run_id)
                matched_set.add(run_id)

    matched_runs = [rid for rid in run_ids if rid in matched_set]
    unmatched_scopes = [scope for scope, hits in match_map.items() if not hits]
    return matched_runs, match_map, unmatched_scopes


def _build_folder_profile_overview(
    folder_alias: str,
    run_ids: Sequence[int],
) -> Dict[str, Any]:
    """フォルダ配下のRun情報とサブフォルダ集計を生成する。"""

    upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
    normalized_root = normalize_existing_folder_alias(folder_alias)

    runs: list[dict[str, Any]] = []
    subfolder_map: dict[str, dict[str, Any]] = {}

    for run_id in run_ids:
        info = None
        try:
            info = get_run_video_info(run_id, upload_folder)
        except Exception as e:
            print(f"[DEBUG] get_run_video_info failed for run_id={run_id}: {e}")
            info = None
        if not info:
            print(f"[DEBUG] info is None for run_id={run_id}")
            continue

        filename = (info.get('filename') or '').strip()
        if not filename:
            continue

        raw_alias_input = info.get('folder_alias') or ''
        raw_alias = normalize_existing_folder_alias(raw_alias_input)
        canonical_alias = normalize_existing_folder_alias(
            _canonicalize_folder_alias(raw_alias_input, filename)
        )
        effective_alias = canonical_alias or raw_alias or normalized_root or ''

        relative_alias = ''
        if effective_alias:
            if normalized_root and effective_alias.startswith(f"{normalized_root}/"):
                relative_alias = effective_alias[len(normalized_root) + 1 :]
            elif effective_alias == normalized_root:
                relative_alias = ''
            else:
                relative_alias = effective_alias

        relative_alias = relative_alias.strip('/') if relative_alias else ''
        if relative_alias and '/' in relative_alias:
            relative_alias = re.sub(r"/+", "/", relative_alias)

        if not relative_alias and normalized_root:
            for key in ("path", "source_path", "output_folder"):
                candidate_rel = _relative_alias_from_path(info.get(key), normalized_root, filename)
                if candidate_rel:
                    relative_alias = re.sub(r"/+", "/", candidate_rel.strip('/'))
                    break

        scope_folder = normalized_root or effective_alias or ''
        if relative_alias:
            scope_folder = f"{normalized_root}/{relative_alias}" if normalized_root else relative_alias
        video_scope = f"{scope_folder}/{filename}" if scope_folder else filename
        relative_path = f"{relative_alias}/{filename}" if relative_alias else filename

        run_entry = {
            'run_id': run_id,
            'filename': filename,
            'profile': (info.get('profile_name') or '').strip(),
            'folder_alias': effective_alias or normalized_root,
            'original_alias': raw_alias,
            'canonical_alias': canonical_alias,
            'relative_alias': relative_alias,
            'relative_path': relative_path,
            'scope': video_scope,
            'road_type': info.get('road_type'),
            'collection_year': info.get('collection_year'),
        }
        runs.append(run_entry)

        profile_value = run_entry['profile']

        prefixes: list[tuple[str, str, int, str]] = []
        if normalized_root:
            prefixes.append((normalized_root, '', 0, relative_path))
        relative_parts = [part for part in (relative_alias or '').split('/') if part]
        if not relative_parts and not normalized_root:
            prefixes.append(('', '', 0, relative_path))
        for level, end in enumerate(range(1, len(relative_parts) + 1), start=1):
            rel_prefix = '/'.join(relative_parts[:end])
            scope_path = f"{normalized_root}/{rel_prefix}" if normalized_root else rel_prefix
            remaining = relative_path
            prefix_with_sep = f"{rel_prefix}/"
            if rel_prefix and relative_path.startswith(prefix_with_sep):
                remaining = relative_path[len(prefix_with_sep) :]
            prefixes.append((scope_path, rel_prefix, level, remaining))

        seen_scopes: set[str] = set()
        for scope_path, display_name, level, example_hint in prefixes:
            if not scope_path:
                continue
            if scope_path in seen_scopes:
                continue
            seen_scopes.add(scope_path)
            entry = subfolder_map.setdefault(
                scope_path,
                {
                    'scope': scope_path,
                    'display_name': display_name or 'ルート直下',
                    'level': level,
                    'run_count': 0,
                    'profiles': set(),
                    'road_types': set(),
                    'collection_years': set(),
                    'example_video': None,
                    'example_run_id': None,
                },
            )
            entry['run_count'] += 1
            if profile_value:
                entry['profiles'].add(profile_value)
            
            # Collect metadata
            rt = run_entry.get('road_type')
            if rt:
                entry['road_types'].add(rt)
            cy = run_entry.get('collection_year')
            if cy:
                entry['collection_years'].add(cy)
            
            if not entry.get('example_run_id'):
                entry['example_run_id'] = run_id
            if not entry.get('example_video') and example_hint:
                entry['example_video'] = example_hint

    runs.sort(key=lambda item: (item.get('relative_path') or '', item.get('run_id') or 0))

    subfolders: list[dict[str, Any]] = []
    for key, entry in sorted(
        subfolder_map.items(),
        key=lambda item: (item[1].get('level', 0), item[0]),
    ):
        profiles = sorted(entry['profiles']) if entry.get('profiles') else []
        level = int(entry.get('level') or 0)
        base_label_raw = entry.get('display_name') or ''
        leaf_label = base_label_raw.split('/')[-1] if '/' in base_label_raw else base_label_raw
        label_text = leaf_label or base_label_raw or 'ルート直下'
        indent = '　' * max(level - 1, 0)
        scope_value = entry.get('scope') or ''
        is_root_scope = bool(normalized_root and scope_value == normalized_root)
        display_label = label_text if level == 0 else f"{indent}{label_text}"
        if is_root_scope and scope_value:
            display_label = f"{label_text or 'ルート直下'}（{scope_value}）"
        example = entry.get('example_video')
        path_hint = ''
        if base_label_raw and base_label_raw != leaf_label:
            path_hint = base_label_raw
        
        # Convert metadata sets to single values or lists
        road_types_list = list(entry.get('road_types', set()))
        collection_years_list = sorted(list(entry.get('collection_years', set())))
        
        # Use single value if all runs have the same metadata, otherwise None (mixed)
        road_type_value = road_types_list[0] if len(road_types_list) == 1 else None
        collection_year_value = collection_years_list[0] if len(collection_years_list) == 1 else None
        
        subfolders.append(
            {
                'scope': entry['scope'],
                'display_name': label_text,
                'display_label': display_label,
                'run_count': entry['run_count'],
                'profiles': profiles,
                'road_type': road_type_value,
                'collection_year': collection_year_value,
                'road_types_mixed': len(road_types_list) > 1,
                'collection_years_mixed': len(collection_years_list) > 1,
                'example_video': f"例: {example}" if example else None,
                'is_root': is_root_scope,
                'path_label': path_hint,
                'scope_label': scope_value,
                'label_segment': label_text,
                'example_run_id': entry.get('example_run_id'),
                'has_profile': bool(profiles),
            }
        )

    return {
        'folder_alias': normalized_root,
        'total_runs': len(runs),
        'runs': runs,
        'subfolders': subfolders,
    }


def resolve_registered_folder(upload_root: str, folder_name: str) -> tuple[str, bool, bool, str]:
    """登録済みフォルダの実体パスと状態を返す。"""
    folder_dir = os.path.join(upload_root, folder_name)
    link_file = os.path.join(folder_dir, PATH_LINK_FILENAME)
    if os.path.isfile(link_file):
        raw_target = ""
        try:
            with open(link_file, "r", encoding="utf-8") as handle:
                raw_target = handle.read().strip()
        except OSError:
            raw_target = ""
        resolved = os.path.abspath(raw_target) if raw_target else raw_target
        exists = bool(resolved and os.path.isdir(resolved))
        return resolved or raw_target, True, exists, raw_target or resolved
    exists = os.path.isdir(folder_dir)
    return folder_dir, False, exists, folder_dir


def _format_relative_path(target_path: str, base_path: str) -> str:
    """ベースフォルダを基準にした相対パスを表示用に整形する。"""
    if not target_path:
        return ""
    try:
        rel = os.path.relpath(target_path, base_path)
    except ValueError:
        return os.path.basename(target_path)

    if rel in (".", "") or rel.startswith(".."):
        return os.path.basename(target_path)

    return rel.replace(os.sep, "/")


def _coerce_checkbox(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_process_year(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        year = int(text)
    except (TypeError, ValueError):
        return None
    if year < 0:
        return None
    return year


def _parse_location_id(value: Optional[str], *, allowed_ids: set[int]) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        location_id = int(text)
    except (TypeError, ValueError):
        return None
    if location_id <= 0:
        return None
    if allowed_ids:
        if location_id not in allowed_ids:
            return None
    else:
        return None
    return location_id


def _default_yolo_progress() -> Dict[str, Optional[Any]]:
    return {"current": 0, "total": 0, "status": "waiting", "message": None}


def _default_post_process_progress() -> Dict[str, Any]:
    return {
        "status": "idle",
        "message": "待機中",
        "percent": 0,
        "task": None,
        "run_id": None,
        "payload": None,
        "queue": [],
        "current_task": None,
        "last_result": None,
    }


def _default_batch_status() -> Dict[str, Any]:
    return {
        "status": "idle",
        "message": None,
        "results": [],
        "folder": None,
        "current": 0,
        "total": 0,
        "current_video": None,
        "csv_bundle": None,
    }


yolo_progress = _default_yolo_progress()
post_process_progress = _default_post_process_progress()


def _summarize_model_counts(model_counts: Optional[Dict[str, int]]) -> Dict[str, Any]:
    counts = model_counts or {}
    yolo_total = 0
    best_total = 0
    yolo_breakdown: list[str] = []
    best_breakdown: list[str] = []
    for name, value in counts.items():
        if not value:
            continue
        label = str(name)
        lower = label.lower()
        if "best" in lower:
            best_total += value
            best_breakdown.append(f"{label}: {value}件")
        else:
            yolo_total += value
            yolo_breakdown.append(f"{label}: {value}件")
    return {
        "yolo_total": yolo_total,
        "best_total": best_total,
        "yolo_breakdown": yolo_breakdown,
        "best_breakdown": best_breakdown,
    }


def _format_yolo_completion_message(result: VideoProcessResult) -> str:
    summary = _summarize_model_counts(result.model_counts)
    details: list[str] = [
        f"YOLO処理が完了しました。Run ID: {result.run_id}",
        f"合計検出数: {result.total_detections} 件",
    ]

    yolo_line = f"<strong>YOLO完了:</strong> {summary['yolo_total']} 件"
    if summary["yolo_breakdown"]:
        yolo_line += "（" + " / ".join(summary["yolo_breakdown"]) + "）"
    details.append(yolo_line)

    best_line = f"<strong>best完了:</strong> {summary['best_total']} 件"
    if summary["best_breakdown"]:
        best_line += "（" + " / ".join(summary["best_breakdown"]) + "）"
    details.append(best_line)

    if result.models_used:
        model_label = " / ".join(result.models_used)
        details.append(f"<strong>使用モデル:</strong> {model_label}")

    return "<br>".join(details)


def _format_detection_summary_text(model_counts: Optional[Dict[str, int]]) -> str:
    summary = _summarize_model_counts(model_counts)
    if summary["yolo_total"] == 0 and summary["best_total"] == 0:
        return "-"
    yolo_label = (
        f"YOLO: {summary['yolo_total']}件"
        + (
            f"（{' / '.join(summary['yolo_breakdown'])}）"
            if summary["yolo_breakdown"]
            else ""
        )
    )
    best_label = (
        f"best: {summary['best_total']}件"
        + (
            f"（{' / '.join(summary['best_breakdown'])}）"
            if summary["best_breakdown"]
            else ""
        )
    )
    return f"{yolo_label} / {best_label}"


def _serialize_metrics(metrics: Optional[SystemMetrics]) -> Dict[str, Optional[float]]:
    if metrics is None:
        return {
            "cpu_util_percent": None,
            "ram_available_mb": None,
            "ram_total_mb": None,
            "ram_used_mb": None,
            "ram_used_percent": None,
            "gpu_util_percent": None,
            "gpu_mem_total_mb": None,
            "gpu_mem_free_mb": None,
            "gpu_mem_used_mb": None,
            "gpu_mem_used_percent": None,
            "timestamp": None,
        }

    ram_used_mb: Optional[float] = None
    ram_used_percent: Optional[float] = None
    if metrics.ram_total_mb is not None and metrics.ram_available_mb is not None:
        ram_used_mb = max(0.0, metrics.ram_total_mb - metrics.ram_available_mb)
        if metrics.ram_total_mb > 0:
            ram_used_percent = (ram_used_mb / metrics.ram_total_mb) * 100.0

    gpu_mem_used_mb: Optional[float] = None
    gpu_mem_used_percent: Optional[float] = None
    if metrics.gpu_mem_total_mb is not None and metrics.gpu_mem_free_mb is not None:
        gpu_mem_used_mb = max(0.0, metrics.gpu_mem_total_mb - metrics.gpu_mem_free_mb)
        if metrics.gpu_mem_total_mb > 0:
            gpu_mem_used_percent = (gpu_mem_used_mb / metrics.gpu_mem_total_mb) * 100.0

    return {
        "cpu_util_percent": metrics.cpu_util_percent,
        "ram_available_mb": metrics.ram_available_mb,
        "ram_total_mb": metrics.ram_total_mb,
        "ram_used_mb": ram_used_mb,
        "ram_used_percent": ram_used_percent,
        "gpu_util_percent": metrics.gpu_util_percent,
        "gpu_mem_total_mb": metrics.gpu_mem_total_mb,
        "gpu_mem_free_mb": metrics.gpu_mem_free_mb,
        "gpu_mem_used_mb": gpu_mem_used_mb,
        "gpu_mem_used_percent": gpu_mem_used_percent,
        "timestamp": metrics.timestamp,
    }


@dataclass
class PostProcessTask:
    run_id: Optional[int]
    action: str
    task_type: str
    options: Optional[dict] = None
    folder_alias: Optional[str] = None
    run_ids: Optional[List[int]] = None
    task_id: int = field(default_factory=lambda: next(_task_id_counter))

    def target_runs(self) -> List[int]:
        if self.run_ids:
            return list(self.run_ids)
        return [self.run_id] if self.run_id is not None else []

    def primary_run_id(self) -> Optional[int]:
        runs = self.target_runs()
        return runs[0] if runs else None


_task_id_counter = itertools.count(1)
post_process_queue: deque[PostProcessTask] = deque()
post_process_queue_lock = threading.Lock()
current_post_process_task: Optional[PostProcessTask] = None

ACTION_TASK_TYPES = {
    "all_postprocess": "pipeline",
    "run_range_postprocess": "pipeline",
    "generate_video": "video",
    "all_save": "export",
    "export_excel": "excel",
}


def _serialize_task(task: Optional[PostProcessTask]) -> Optional[Dict[str, Any]]:
    if not task:
        return None
    return {
        "task_id": task.task_id,
        "run_id": task.primary_run_id(),
        "action": task.action,
        "task": task.task_type,
        "folder_alias": task.folder_alias,
        "run_ids": task.target_runs(),
    }


def _sync_progress_context() -> None:
    with post_process_queue_lock:
        current = _serialize_task(current_post_process_task)
        queue_snapshot = [_serialize_task(item) for item in list(post_process_queue)]
    post_process_progress["current_task"] = current
    post_process_progress["queue"] = queue_snapshot


def _launch_task_thread(task: PostProcessTask) -> None:
    app = current_app._get_current_object()

    def _runner() -> None:
        with app.app_context():
            _execute_post_process_task(task)

    thread = threading.Thread(
        target=_runner,
        daemon=True,
    )
    thread.start()


def enqueue_post_process_task(task: PostProcessTask) -> tuple[bool, int]:
    global current_post_process_task
    should_start = False
    waiting_ahead = 0
    with post_process_queue_lock:
        if current_post_process_task is None:
            current_post_process_task = task
            should_start = True
        else:
            waiting_ahead = len(post_process_queue) + 1
            post_process_queue.append(task)
    _sync_progress_context()
    if should_start:
        _launch_task_thread(task)
    return should_start, waiting_ahead


def finalize_current_task(
    status: str,
    message: str,
    task_type: str,
    run_id: Optional[int],
    *,
    payload: Optional[Dict[str, Any]] = None,
    percent: Optional[int] = None,
) -> None:
    if percent is None:
        percent = 100 if status == "complete" else post_process_progress.get("percent", 0)
    update_post_process_progress(
        status,
        message,
        percent=percent,
        task=task_type,
        run_id=run_id,
        payload=payload,
    )
    next_task: Optional[PostProcessTask] = None
    with post_process_queue_lock:
        post_process_progress["last_result"] = {
            "status": status,
            "message": message,
            "task": task_type,
            "run_id": run_id,
            "payload": payload,
        }
        global current_post_process_task
        current_post_process_task = None
        if post_process_queue:
            next_task = post_process_queue.popleft()
            current_post_process_task = next_task
    _sync_progress_context()
    if next_task is not None:
        _launch_task_thread(next_task)


def _run_pipeline_task(task: PostProcessTask) -> None:
    run_ids = task.target_runs()
    if not run_ids:
        finalize_current_task(
            "error",
            "後処理対象のRunが見つかりません。",
            "pipeline",
            None,
            percent=0,
        )
        return

    total_steps_per_run = 7
    steps = [
        ("1/7: グループID割当（車両とタイヤの紐付け）...", assign_group_ids),
        ("2/7: 運動学情報（速度など）計算中...", assign_kinematics),
        ("3/7: 追い越し判定中...", assign_overtake),
        ("4/7: 接近/離隔距離計算中...", assign_approach_and_clearance),
        ("5/7: 白線距離計算中...", assign_lane_distance),
        ("6/7: 車両間距離計算中...", analyze_proximity),
        ("7/7: TTC計算中...", assign_ttc),
    ]

    summary_columns = [column for column, _label in POST_PROCESS_SUMMARY_COLUMNS]
    aggregated_counts: dict[str, int] = {column: 0 for column in summary_columns}
    aggregated_total_rows = 0
    aggregated_overtakes: dict[str, Any] = {"total": 0, "inner": 0, "outer": 0, "images": []}
    per_run_summaries: list[Dict[str, Any]] = []

    def build_column_summary() -> Optional[Dict[str, Any]]:
        if not per_run_summaries:
            return None

        totals_columns = [
            {
                "key": column,
                "label": label,
                "count": int(aggregated_counts.get(column, 0) or 0),
            }
            for column, label in POST_PROCESS_SUMMARY_COLUMNS
        ]

        per_run_payload: list[Dict[str, Any]] = []
        for entry in per_run_summaries:
            per_run_payload.append(
                {
                    "run_id": entry.get("run_id"),
                    "total_rows": entry.get("total_rows", 0),
                    "columns": [
                        {
                            "key": column_entry.get("key"),
                            "label": column_entry.get("label"),
                            "count": int(column_entry.get("count", 0)),
                        }
                        for column_entry in entry.get("columns", [])
                    ],
                }
            )

        return {
            "totals": {
                "total_rows": int(aggregated_total_rows),
                "columns": totals_columns,
            },
            "per_run": per_run_payload,
        }

    total_steps = total_steps_per_run * len(run_ids)
    completed_steps = 0
    processed_runs = 0
    successful_runs = 0
    error_entries: list[Dict[str, Any]] = []

    def build_error_payload(errors: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        return [
            {
                "run_id": entry.get("run_id"),
                "message": entry.get("message"),
                "step": entry.get("step"),
            }
            for entry in errors
        ]

    def build_payload(completed_runs: int) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "completed_runs": completed_runs,
            "total_runs": len(run_ids),
            "successful_runs": successful_runs,
            "failed_runs": len(error_entries),
        }
        if task.folder_alias:
            payload["folder_alias"] = task.folder_alias
        column_summary = build_column_summary()
        if column_summary:
            payload["column_counts"] = column_summary
            payload["errors"] = build_error_payload(error_entries)
        if aggregated_overtakes["total"] > 0:
            payload["overtakes"] = aggregated_overtakes
        return payload

    try:
        update_post_process_progress(
            "processing",
            "後処理を開始します...",
            percent=0,
            task="pipeline",
            run_id=run_ids[0],
            payload=build_payload(processed_runs),
        )
        for run_index, run_id in enumerate(run_ids, start=1):
            run_failed = False
            for step_index, (message, handler) in enumerate(steps, start=1):
                percent = int((completed_steps / total_steps) * 100) if total_steps else 0
                decorated_message = message
                if len(run_ids) > 1:
                    decorated_message = f"[{run_index}/{len(run_ids)}] {message}"
                update_post_process_progress(
                    "processing",
                    decorated_message,
                    percent=percent,
                    task="pipeline",
                    run_id=run_id,
                    payload=build_payload(processed_runs),
                )
                try:
                    handler(run_id)
                    completed_steps += 1
                except Exception as step_exc:  # pragma: no cover - runtime safeguard
                    current_app.logger.exception(
                        "Post-process step failed for Run %s (step: %s)",
                        run_id,
                        message,
                    )
                    run_failed = True
                    completed_steps = min(total_steps, run_index * total_steps_per_run)
                    error_entries.append(
                        {
                            "run_id": run_id,
                            "step": message,
                            "message": str(step_exc),
                        }
                    )
                    percent = int((completed_steps / total_steps) * 100) if total_steps else 0
                    update_post_process_progress(
                        "processing",
                        f"Run ID {run_id}: {decorated_message} でエラーが発生しました。次のRunへ進みます。",
                        percent=percent,
                        task="pipeline",
                        run_id=run_id,
                        payload=build_payload(processed_runs + 1),
                    )
                    break

            processed_runs += 1
            if run_failed:
                continue

            run_summary = summarize_detection_columns([run_id], summary_columns)
            run_total_rows = int(run_summary.get("total_rows", 0)) if run_summary else 0
            aggregated_total_rows += run_total_rows
            per_run_columns: list[Dict[str, Any]] = []
            for column, label in POST_PROCESS_SUMMARY_COLUMNS:
                count_value = int(run_summary.get(column, 0)) if run_summary else 0
                aggregated_counts[column] = aggregated_counts.get(column, 0) + count_value
                per_run_columns.append(
                    {
                        "key": column,
                        "label": label,
                        "count": count_value,
                    }
                )
            per_run_summaries.append(
                {
                    "run_id": run_id,
                    "total_rows": run_total_rows,
                    "columns": per_run_columns,
                }
            )
            successful_runs += 1

            try:
                ov_stats = summarize_run_overtakes(run_id)
                aggregated_overtakes["total"] += ov_stats["total"]
                aggregated_overtakes["inner"] += ov_stats["inner"]
                aggregated_overtakes["outer"] += ov_stats["outer"]
                if ov_stats["images"]:
                    aggregated_overtakes["images"].extend(ov_stats["images"])
            except Exception as e:
                current_app.logger.error(f"Failed to summarize overtakes for run {run_id}: {e}")

        final_payload = build_payload(processed_runs)
        
        # Calculate Batch Statistics
        try:
            batch_stats = {
                "avg_overtakes_per_file": 0.0,
                "avg_speed": 0.0,
                "avg_overtake_speed": 0.0,
                "inner_ratio": 0.0,
                "outer_ratio": 0.0,
            }
            
            # 1. Avg Overtakes per File
            total_ov = aggregated_overtakes["total"]
            if len(run_ids) > 0:
                batch_stats["avg_overtakes_per_file"] = round(total_ov / len(run_ids), 2)

            # 2. Inner/Outer Ratios
            inner_ov = aggregated_overtakes["inner"]
            outer_ov = aggregated_overtakes["outer"]
            total_classified = inner_ov + outer_ov
            if total_classified > 0:
                batch_stats["inner_ratio"] = round((inner_ov / total_classified) * 100, 1)
                batch_stats["outer_ratio"] = round((outer_ov / total_classified) * 100, 1)

            # 3. Avg Speeds (SQL)
            with sqlite3.connect(MAIN_DB_PATH) as conn:
                configure_connection(conn, mode="read")
                placeholders = ",".join("?" * len(run_ids))
                
                # Avg Speed (All detections)
                cur = conn.execute(f"SELECT AVG(speed_km_h) FROM Detection WHERE run_id IN ({placeholders}) AND speed_km_h > 0", run_ids)
                row = cur.fetchone()
                if row and row[0]:
                    batch_stats["avg_speed"] = round(row[0], 2)
                
                # Avg Overtake Speed
                query_ov_speed = f"""
                    SELECT AVG(d.speed_km_h) 
                    FROM OvertakeEvents o
                    JOIN Detection d ON o.run_id = d.run_id 
                        AND o.event_frame_num = d.frame_num 
                        AND o.overtaker_auto_id = d.auto_id
                    WHERE o.run_id IN ({placeholders}) AND d.speed_km_h > 0
                """
                cur = conn.execute(query_ov_speed, run_ids)
                row = cur.fetchone()
                if row and row[0]:
                    batch_stats["avg_overtake_speed"] = round(row[0], 2)

            final_payload["batch_summary"] = batch_stats

        except Exception as e:
            current_app.logger.warning(f"Failed to calculate batch stats: {e}")

        error_count = len(error_entries)
        success_count = successful_runs
        if len(run_ids) > 1 and task.folder_alias:
            base_message = f"フォルダ '{task.folder_alias}' 内の {len(run_ids)} 件を処理しました。"
        elif len(run_ids) > 1:
            base_message = f"{len(run_ids)} 件のRunを処理しました。"
        else:
            base_message = f"Run ID {run_ids[0]}: 後処理を実行しました。"

        if error_count and success_count:
            error_preview = " / ".join(
                [
                    f"Run #{entry['run_id']}: {entry['message']}"
                    for entry in error_entries[:3]
                ]
            )
            if error_count > 3:
                error_preview += f" ... ほか {error_count - 3} 件"
            final_message = f"{base_message} ただし {error_count} 件でエラーが発生しました。{error_preview}"
            final_status = "complete"
        elif error_count and not success_count:
            error_preview = " / ".join(
                [
                    f"Run #{entry['run_id']}: {entry['message']}"
                    for entry in error_entries[:3]
                ]
            )
            if error_count > 3:
                error_preview += f" ... ほか {error_count - 3} 件"
            final_message = f"{base_message} すべてのRunでエラーが発生しました。{error_preview}"
            final_status = "error"
        else:
            final_message = base_message
            final_status = "complete"

        finalize_current_task(
            final_status,
            final_message,
            "pipeline",
            run_ids[-1],
            payload=final_payload,
        )
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Unhandled error while running post-process pipeline")
        current_run_index = min(len(run_ids) - 1, processed_runs)
        current_run = run_ids[current_run_index]
        error_payload = build_payload(processed_runs)
        finalize_current_task(
            "error",
            f"後処理中に予期しないエラーが発生しました: {exc}",
            "pipeline",
            current_run,
            percent=post_process_progress.get("percent", 0),
            payload=error_payload,
        )


def _run_video_task(task: PostProcessTask) -> None:
    run_id = task.primary_run_id()
    if run_id is None:
        finalize_current_task(
            "error",
            "動画生成の対象Runが指定されていません。",
            "video",
            None,
            percent=0,
        )
        return
    try:
        update_post_process_progress(
            "processing",
            "動画生成を開始しています...",
            percent=0,
            task="video",
            run_id=run_id,
            payload=None,
        )
        video_path = create_annotated_video(run_id, task.options)
        resolved_video_path = Path(video_path).resolve()
        current_app.logger.info("Annotated video saved: %s", resolved_video_path)
        finalize_current_task(
            "complete",
            f"Run ID {run_id}: アノテーション動画を生成しました。",
            "video",
            run_id,
            payload={"video_path": video_path},
        )
    except Exception as exc:
        finalize_current_task(
            "error",
            f"動画生成中にエラーが発生しました: {exc}",
            "video",
            run_id,
            percent=100,
        )


def _run_export_task(task: PostProcessTask) -> None:
    run_ids = task.target_runs()
    if not run_ids:
        finalize_current_task(
            "error",
            "CSV出力の対象Runが見つかりません。",
            "export",
            None,
            percent=0,
        )
        return

    total_runs = len(run_ids)

    def build_payload(completed: int, last_path: Optional[str]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "completed_runs": completed,
            "total_runs": total_runs,
        }
        if task.folder_alias:
            payload["folder_alias"] = task.folder_alias
        if last_path:
            payload["last_csv_path"] = last_path
        return payload

    created_paths: List[str] = []
    combined_csv_path: Optional[str] = None

    try:
        for index, run_id in enumerate(run_ids, start=1):
            percent = int(((index - 1) / total_runs) * 100) if total_runs else 0
            update_post_process_progress(
                "processing",
                f"[{index}/{total_runs}] Run ID {run_id} のCSVを出力中...",
                percent=percent,
                task="export",
                run_id=run_id,
                payload=build_payload(index - 1, created_paths[-1] if created_paths else None),
            )
            csv_path = create_all_save(run_id)
            created_paths.append(csv_path)
            update_post_process_progress(
                "processing",
                f"[{index}/{total_runs}] Run ID {run_id} のCSV出力を完了しました。",
                percent=int((index / total_runs) * 100),
                task="export",
                run_id=run_id,
                payload=build_payload(index, csv_path),
            )

        try:
            combined_csv_path = create_combined_detection_csv(
                run_ids,
                folder_alias=task.folder_alias,
            )
        except Exception as combine_exc:  # pragma: no cover - 失敗しても主要処理は継続
            current_app.logger.warning(
                "Failed to create combined CSV: %s", combine_exc
            )

        bundle_path: Optional[str] = None
        if len(created_paths) > 1:
            bundle_path = create_csv_bundle(created_paths, folder_alias=task.folder_alias)

        summary_payload = build_payload(total_runs, created_paths[-1] if created_paths else None)
        summary_payload["csv_paths"] = created_paths
        if bundle_path:
            summary_payload["bundle_path"] = bundle_path
        if combined_csv_path:
            summary_payload["combined_csv_path"] = combined_csv_path

        if len(created_paths) > 1:
            if task.folder_alias:
                message = f"フォルダ '{task.folder_alias}' 内の {len(created_paths)} 件のCSVを出力しました。"
            else:
                message = f"{len(created_paths)} 件のRunのCSV出力を完了しました。"
        else:
            message = f"Run ID {run_ids[0]}: CSV出力を完了しました。"

        if combined_csv_path:
            message += f" まとめCSV: {os.path.relpath(combined_csv_path, os.getcwd())}"

        finalize_current_task(
            "complete",
            message,
            "export",
            run_ids[-1],
            payload=summary_payload,
        )
    except Exception as exc:
        completed = len(created_paths)
        current_index = min(completed, len(run_ids) - 1) if run_ids else None
        current_run = run_ids[current_index] if current_index is not None else None
        error_payload = build_payload(completed, created_paths[-1] if created_paths else None)
        if created_paths:
            error_payload["csv_paths"] = created_paths
        if combined_csv_path:
            error_payload["combined_csv_path"] = combined_csv_path
        finalize_current_task(
            "error",
            f"CSV出力中にエラーが発生しました: {exc}",
            "export",
            current_run,
            percent=post_process_progress.get("percent", 0),
            payload=error_payload,
        )


def _run_excel_export_task(task: PostProcessTask) -> None:
    run_ids = task.target_runs()
    if not run_ids:
        finalize_current_task(
            "error",
            "Excel出力の対象Runが見つかりません。",
            "excel",
            None,
            percent=0,
        )
        return

    total_runs = len(run_ids)

    def build_payload(completed: int, last_path: Optional[str]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "completed_runs": completed,
            "total_runs": total_runs,
        }
        if task.folder_alias:
            payload["folder_alias"] = task.folder_alias
        if last_path:
            payload["last_excel_path"] = last_path
        return payload

    created_paths: List[str] = []
    bundle_path: Optional[str] = None

    try:
        for index, run_id in enumerate(run_ids, start=1):
            percent = int(((index - 1) / total_runs) * 100) if total_runs else 0
            update_post_process_progress(
                "processing",
                f"[{index}/{total_runs}] Run ID {run_id} のExcelを出力中...",
                percent=percent,
                task="excel",
                run_id=run_id,
                payload=build_payload(index - 1, created_paths[-1] if created_paths else None),
            )
            excel_path = create_detection_excel(run_id)
            resolved_excel_path = Path(excel_path).resolve()
            current_app.logger.info("Excel export saved: %s", resolved_excel_path)
            created_paths.append(excel_path)
            update_post_process_progress(
                "processing",
                f"[{index}/{total_runs}] Run ID {run_id} のExcel出力を完了しました。",
                percent=int((index / total_runs) * 100),
                task="excel",
                run_id=run_id,
                payload=build_payload(index, excel_path),
            )

        if len(created_paths) > 1:
            try:
                bundle_path = create_excel_bundle(
                    created_paths,
                    folder_alias=task.folder_alias,
                )
                resolved_bundle_path = Path(bundle_path).resolve()
                current_app.logger.info("Excel bundle saved: %s", resolved_bundle_path)
            except Exception as bundle_exc:  # pragma: no cover - bundling best effort
                current_app.logger.warning("Failed to bundle Excel exports: %s", bundle_exc)

        summary_payload = build_payload(total_runs, created_paths[-1] if created_paths else None)
        summary_payload["excel_paths"] = created_paths
        if bundle_path:
            summary_payload["bundle_path"] = bundle_path

        if len(created_paths) > 1:
            if task.folder_alias:
                message = f"フォルダ '{task.folder_alias}' 内の {len(created_paths)} 件のExcelを出力しました。"
            else:
                message = f"{len(created_paths)} 件のRunのExcel出力を完了しました。"
        else:
            message = f"Run ID {run_ids[0]}: Excel出力を完了しました。"

        if bundle_path:
            message += f" ZIP: {os.path.relpath(bundle_path, os.getcwd())}"

        finalize_current_task(
            "complete",
            message,
            "excel",
            run_ids[-1],
            payload=summary_payload,
        )
    except Exception as exc:
        completed = len(created_paths)
        current_index = min(completed, len(run_ids) - 1) if run_ids else None
        current_run = run_ids[current_index] if current_index is not None else None
        error_payload = build_payload(completed, created_paths[-1] if created_paths else None)
        if created_paths:
            error_payload["excel_paths"] = created_paths
        finalize_current_task(
            "error",
            f"Excel出力中にエラーが発生しました: {exc}",
            "excel",
            current_run,
            percent=post_process_progress.get("percent", 0),
            payload=error_payload,
        )


def _execute_post_process_task(task: PostProcessTask) -> None:
    try:
        if task.task_type == "pipeline":
            _run_pipeline_task(task)
        elif task.task_type == "video":
            _run_video_task(task)
        elif task.task_type == "export":
            _run_export_task(task)
        elif task.task_type == "excel":
            _run_excel_export_task(task)
        else:
            finalize_current_task(
                "error",
                f"未知のタスク種別: {task.task_type}",
                task.task_type,
                task.primary_run_id(),
            )
    except Exception as exc:
        finalize_current_task(
            "error",
            f"タスク実行中に未処理の例外が発生しました: {exc}",
            task.task_type,
            task.primary_run_id(),
        )

BATCH_VIDEO_EXTENSIONS = set(FOLDER_VIDEO_EXTENSIONS)


batch_status = _default_batch_status()

CSV_COLUMN_GUIDE_NAME = "csv_output_columns_description.csv"
CSV_COLUMN_GUIDE_PATH = os.path.join(BASE_FILES, CSV_COLUMN_GUIDE_NAME)

def update_yolo_progress(current, total, status="processing", message=None):
    global yolo_progress
    yolo_progress.update({"current": current, "total": total, "status": status, "message": message})

def update_post_process_progress(status, message, *, percent=None, task=None, run_id=None, payload=None):
    """後処理や動画生成の進捗を更新するヘルパー"""
    global post_process_progress
    post_process_progress.update(
        {
            "status": status,
            "message": message,
            "percent": percent if percent is not None else post_process_progress.get("percent"),
            "task": task if task is not None else post_process_progress.get("task"),
            "run_id": run_id if run_id is not None else post_process_progress.get("run_id"),
            "payload": payload,
        }
    )
    if status == "idle":
        post_process_progress.update({
            "percent": 0,
            "task": None,
            "run_id": None,
            "payload": None,
        })
    _sync_progress_context()

def _summarize_runs(logs: List[Dict[str, Any]]) -> Dict[str, int]:
    total = len(logs)
    completed = 0
    processing = 0
    errors = 0
    waiting = 0
    for item in logs:
        status = (item.get("status") or "").strip().lower()
        if status == "completed":
            completed += 1
        elif status == "processing":
            processing += 1
        elif status == "error":
            errors += 1
        else:
            waiting += 1
    return {
        "total": total,
        "completed": completed,
        "processing": processing,
        "errors": errors,
        "waiting": waiting,
    }


def _reset_progress_states() -> None:
    global current_post_process_task
    yolo_progress.clear()
    yolo_progress.update(_default_yolo_progress())

    post_process_progress.clear()
    post_process_progress.update(_default_post_process_progress())

    batch_status.clear()
    batch_status.update(_default_batch_status())

    with post_process_queue_lock:
        post_process_queue.clear()
        current_post_process_task = None

    _sync_progress_context()


def _format_bytes(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _format_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _list_database_candidates() -> List[Dict[str, str]]:
    candidates: List[Dict[str, str]] = []
    db_dir = Path(BASE_FILES)
    if not db_dir.exists():
        return candidates

    for entry in sorted(db_dir.glob("*.db")):
        try:
            stats = entry.stat()
        except OSError:
            continue
        candidates.append(
            {
                "name": entry.name,
                "full_path": str(entry.resolve()),
                "size_label": _format_bytes(stats.st_size),
                "modified_label": _format_timestamp(stats.st_mtime),
            }
        )
    return candidates


def _build_database_error_context(exc: Exception, stack_trace: str) -> Dict[str, Any]:
    sidecars = [str(Path(path).resolve()) for path in get_database_sidecar_files(MAIN_DB_PATH)]
    diagnostics = diagnose_sqlite_database(MAIN_DB_PATH)
    diagnosis_summary: Optional[str] = None

    if diagnostics.get("open_error"):
        diagnosis_summary = "DB診断に失敗しました。詳細は下記をご確認ください。"
    else:
        quick_check = diagnostics.get("quick_check", {})
        quick_status = quick_check.get("status")
        if quick_check.get("error"):
            diagnosis_summary = "PRAGMA quick_check の実行に失敗しました。"
        elif quick_status == "issues":
            diagnosis_summary = "PRAGMA quick_check で問題が検出されました。"
        elif quick_status == "ok":
            diagnosis_summary = "quick_check の結果は OK でしたが、追加情報を以下に記載します。"

    context: Dict[str, Any] = {
        "error_type": exc.__class__.__name__,
        "error_message": str(exc),
        "original_error_message": str(exc),
        "traceback_text": stack_trace,
        "db_path": str(Path(MAIN_DB_PATH).resolve()),
        "db_directory": str(Path(BASE_FILES).resolve()),
        "candidate_databases": _list_database_candidates(),
        "sidecar_files": sidecars,
        "recovery_attempted": False,
        "quarantine_successful": None,
        "backup_path": None,
        "db_selection_note": (
            "以下の候補から「このDBを使用する」を選ぶと、"
            "指定したファイルを my_app_data.db としてコピーします。"
        ),
        "selection_enabled": True,
        "selection_action": url_for("main.select_database"),
        "creation_enabled": True,
        "creation_action": url_for("main.create_new_database"),
        "creation_note": (
            "緊急措置として新しい空のDBを作成し直すこともできます。",
            "既存ファイルはバックアップを作成した上で削除します。",
        ),
        "diagnostics": diagnostics,
        "diagnosis_summary": diagnosis_summary,
    }

    if isinstance(exc, DatabaseInitializationError):
        context["original_error_message"] = str(exc.original_exception)
        context["recovery_attempted"] = exc.recovery_attempted
        context["quarantine_successful"] = exc.quarantine_successful
        context["backup_path"] = (
            str(Path(exc.backup_path).resolve()) if exc.backup_path else None
        )

    return context


def _render_database_error(exc: Exception):
    stack_trace = traceback.format_exc()
    context = _build_database_error_context(exc, stack_trace)
    return render_template("db_error.html", **context), 500


def _ensure_database_ready():
    try:
        init_db()
    except DatabaseInitializationError as exc:
        current_app.logger.exception("Failed to initialize database with recovery")
        return _render_database_error(exc)
    except sqlite3.DatabaseError as exc:
        current_app.logger.exception("SQLite error while initializing database")
        return _render_database_error(exc)
    return None


@main.route("/db/select", methods=["POST"])
def select_database():
    database_path = (request.form.get("database_path") or "").strip()
    if not database_path:
        flash("切り替えるDBファイルが指定されていません。", "danger")
        return redirect(url_for("main.index"))

    try:
        resolved_path = Path(database_path).resolve()
    except OSError:
        flash("指定したパスを解決できませんでした。", "danger")
        return redirect(url_for("main.index"))

    try:
        _, backup_path = replace_main_database(str(resolved_path))
    except FileNotFoundError:
        flash("指定したDBファイルが見つかりません。", "danger")
        return redirect(url_for("main.index"))
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.index"))
    except RuntimeError as exc:
        current_app.logger.exception("Failed to replace database")
        flash(f"DBの切り替えに失敗しました: {exc}", "danger")
        return redirect(url_for("main.index"))
    except Exception as exc:  # pragma: no cover - 予期しない例外の保険
        current_app.logger.exception("Unexpected error while replacing database")
        flash(f"予期しないエラーによりDBの切り替えに失敗しました: {exc}", "danger")
        return redirect(url_for("main.index"))

    try:
        init_db()
    except DatabaseInitializationError as exc:
        current_app.logger.exception(
            "Database initialization failed after manual selection"
        )
        if backup_path:
            flash(
                f"DBを切り替えましたが初期化に失敗しました。バックアップ: {backup_path}",
                "danger",
            )
        else:
            flash("DBを切り替えましたが初期化に失敗しました。", "danger")
        return _render_database_error(exc)
    except sqlite3.DatabaseError as exc:
        current_app.logger.exception("SQLite error after manual database selection")
        flash("DBを切り替えましたがSQLiteエラーが発生しました。", "danger")
        return _render_database_error(exc)
    except Exception as exc:  # pragma: no cover - 予期しない例外の保険
        current_app.logger.exception("Unexpected error while validating database")
        flash(f"DB切り替え後の検証でエラーが発生しました: {exc}", "danger")
        return redirect(url_for("main.index"))

    selected_name = resolved_path.name
    if backup_path:
        flash(
            f"{selected_name} を使用するよう切り替えました。旧DBは {backup_path} にバックアップされています。",
            "success",
        )
    else:
        flash(f"{selected_name} を使用するよう切り替えました。", "success")

    return redirect(url_for("main.index"))


@main.route("/db/create_new", methods=["POST"])
def create_new_database():
    try:
        _, backup_path, locked_paths = create_new_main_database()
    except RuntimeError as exc:
        current_app.logger.exception("Failed to create fresh database")
        flash(f"新しいDBの作成に失敗しました: {exc}", "danger")
        return redirect(url_for("main.index"))
    except Exception as exc:  # pragma: no cover - 予期しない例外の保険
        current_app.logger.exception("Unexpected error while creating fresh database")
        flash(f"予期しないエラーにより新しいDBを作成できませんでした: {exc}", "danger")
        return redirect(url_for("main.index"))

    try:
        init_db()
    except DatabaseInitializationError as exc:
        current_app.logger.exception("Database initialization failed after creating fresh database")
        flash("新しいDBを作成しましたが初期化に失敗しました。", "danger")
        return _render_database_error(exc)
    except sqlite3.DatabaseError as exc:
        current_app.logger.exception("SQLite error while validating fresh database")
        flash("新しいDBを作成しましたがSQLiteエラーが発生しました。", "danger")
        return _render_database_error(exc)
    except Exception as exc:  # pragma: no cover - 予期しない例外の保険
        current_app.logger.exception("Unexpected error while validating fresh database")
        flash(f"新しいDBの検証中にエラーが発生しました: {exc}", "danger")
        return redirect(url_for("main.index"))

    if backup_path:
        flash(
            "新しい空のDBを作成しました。旧DBは {0} にバックアップしました。".format(
                backup_path
            ),
            "success",
        )
    else:
        flash("新しい空のDBを作成しました。", "success")

    if locked_paths:
        joined = "\n".join(locked_paths)
        flash(
            "一部のファイルは削除できなかったため、次の場所へ移動しました:\n{0}".format(
                joined
            ),
            "warning",
        )

    return redirect(url_for("main.index"))


@main.route("/ensure_default_classes", methods=["POST"])
def ensure_default_classes():
    error_response = _ensure_database_ready()
    if error_response is not None:
        return error_response
    added: list[str] = []
    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            configure_connection(conn, mode="write")
            cursor = conn.cursor()
            cursor.execute("SELECT class_name FROM Class")
            existing_raw = [str(row[0]) for row in cursor.fetchall() if row and row[0] is not None]
            existing_exact = set(existing_raw)
            existing_lower = {name.lower() for name in existing_raw}
            for class_name in DEFAULT_CLASS_CANDIDATES:
                lower_name = class_name.lower()
                if class_name in existing_exact or lower_name in existing_lower:
                    continue
                cursor.execute("INSERT INTO Class (class_name) VALUES (?)", (class_name,))
                added.append(class_name)
                existing_exact.add(class_name)
                existing_lower.add(lower_name)
            cursor.close()
            conn.commit()
    except Exception as exc:  # pragma: no cover - UI経由の予期せぬ例外の保険
        current_app.logger.exception("Failed to add default classes")
        flash(f"クラスの追加に失敗しました: {exc}", "danger")
    else:
        if added:
            joined = ", ".join(added)
            flash(f"{len(added)}件のクラスを追加しました: {joined}", "success")
        else:
            flash("指定されたクラスは既に登録済みです。", "info")
    return redirect(url_for("main.index"))


@main.route("/")
def index():
    error_response = _ensure_database_ready()
    if error_response is not None:
        return error_response
    logs = get_all_process_logs()
    run_summary = _summarize_runs(logs)
    recent_runs = logs[:5]
    folder_summaries = list_folder_batches()[:4]
    return render_template(
        "index.html",
        run_summary=run_summary,
        recent_runs=recent_runs,
        folder_summaries=folder_summaries,
        yolo_progress=yolo_progress,
        post_process_progress=post_process_progress,
        batch_status=batch_status,
    )


@main.route("/reset_runs", methods=["POST"])
def reset_runs():
    error_response = _ensure_database_ready()
    if error_response is not None:
        return error_response
    if str(yolo_progress.get("status")).lower() == "processing":
        flash("YOLO推論が進行中のためリセットできません。完了するまでお待ちください。", "warning")
        return redirect(url_for("main.index"))
    if str(post_process_progress.get("status")).lower() == "processing":
        flash("後処理が実行中のためリセットできません。処理完了後に再試行してください。", "warning")
        return redirect(url_for("main.index"))
    if str(batch_status.get("status")).lower() == "processing":
        flash("フォルダ一括処理が進行中です。完了後にリセットしてください。", "warning")
        return redirect(url_for("main.index"))

    try:
        reset_run_records()
    except Exception as exc:  # pragma: no cover - 予期しない例外の保険
        current_app.logger.exception("Failed to reset run records")
        flash(f"Runデータのリセットに失敗しました: {exc}", "danger")
        return redirect(url_for("main.index"))

    _reset_progress_states()
    flash("すべてのRunデータと進行状況を初期化しました。", "success")
    return redirect(url_for("main.index"))


def _gather_folder_summaries(upload_root: str, folder_names: List[str]) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for folder in folder_names:
        alias_dir = os.path.join(upload_root, folder)
        resolved_path, is_link, exists, source_path = resolve_registered_folder(upload_root, folder)
        video_paths: List[str] = []
        if exists:
            video_paths = collect_video_files(resolved_path, include_subdirectories=True)

        video_count = len(video_paths)
        total_bytes = 0
        sample_files: List[str] = []
        subdir_candidates: set[str] = set()
        for path in video_paths:
            display = _format_relative_path(path, resolved_path)
            if display and len(sample_files) < 5:
                sample_files.append(display)
            parent = os.path.dirname(display)
            if parent and parent not in {"", "."}:
                subdir_candidates.add(parent)
            try:
                total_bytes += os.path.getsize(path)
            except OSError:
                pass

        subdir_samples = sorted(subdir_candidates)[:5]

        settings = load_folder_settings(alias_dir)

        summaries.append(
            {
                "name": folder,
                "count": video_count,
                "size_mb": (total_bytes / (1024 * 1024)) if total_bytes else 0.0,
                "samples": sample_files,
                "subdir_count": len(subdir_candidates),
                "subdir_samples": subdir_samples,
                "is_link": is_link,
                "exists": exists,
                "source_path": source_path or resolved_path,
                "settings": settings,
            }
        )

    return summaries

@main.route("/upload", methods=["GET", "POST"])
def upload_video():
    upload_folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_folder, exist_ok=True)

    if request.method == "POST":
        mode = request.form.get("mode", "upload")

        if mode == "link":
            folder_path = (request.form.get("folder_path") or "").strip()
            alias_input = (request.form.get("folder_alias") or "").strip()
            if not folder_path:
                flash("フォルダパスを入力してください。", "danger")
                return redirect(request.url)

            abs_path = os.path.abspath(folder_path)
            if not os.path.isdir(abs_path):
                flash("指定したフォルダが見つかりません。", "danger")
                return redirect(request.url)

            alias_source = alias_input or os.path.basename(abs_path)
            sanitized_alias = sanitize_folder_alias(alias_source)
            if not sanitized_alias:
                flash("登録名を正しく入力してください。", "danger")
                return redirect(request.url)

            target_dir = os.path.join(upload_folder, sanitized_alias)
            if os.path.exists(target_dir):
                link_file = os.path.join(target_dir, PATH_LINK_FILENAME)
                if os.path.isfile(link_file):
                    try:
                        with open(link_file, "r", encoding="utf-8") as existing_link:
                            existing_path = existing_link.read().strip()
                    except OSError:
                        existing_path = ""
                    if existing_path and os.path.abspath(existing_path) == abs_path:
                        flash("指定したフォルダは既に登録されています。", "info")
                        return redirect(url_for("main.detect"))
                flash("同名のフォルダが既に存在します。別名を指定してください。", "danger")
                return redirect(request.url)

            try:
                os.makedirs(target_dir, exist_ok=True)
            except OSError as exc:
                flash(f"フォルダ登録用のディレクトリ作成に失敗しました: {exc}", "danger")
                return redirect(request.url)

            link_file = os.path.join(target_dir, PATH_LINK_FILENAME)
            try:
                with open(link_file, "w", encoding="utf-8") as handle:
                    handle.write(abs_path)
            except OSError as exc:
                flash(f"フォルダ登録に失敗しました: {exc}", "danger")
                try:
                    if os.path.isfile(link_file):
                        os.remove(link_file)
                    if os.path.isdir(target_dir) and not os.listdir(target_dir):
                        os.rmdir(target_dir)
                except OSError:
                    pass
                return redirect(request.url)

            flash(f"フォルダを登録しました: {sanitized_alias}", "success")
            return redirect(url_for("main.detect"))

        file = request.files.get("file")
        if not file or file.filename == "":
            flash("動画ファイルを選択してください。", "danger")
            return redirect(request.url)
        if allowed_file(file.filename):
            filename = secure_filename(file.filename)
            save_path = os.path.join(upload_folder, filename)
            file.save(save_path)
            flash(f"アップロード完了: {filename}", "success")
            return redirect(url_for("main.index"))
        flash("対応していないファイル形式です。", "danger")
        return redirect(request.url)

    return render_template("upload.html")


@main.route("/locations", methods=["POST"])
def register_location():
    name = (request.form.get("location_name") or "").strip()
    setting_mode = (request.form.get("location_mode") or "").strip()
    if not name:
        flash("場所名を入力してください。", "danger")
        return redirect(url_for("main.detect"))

    try:
        entry = add_location(name, setting_mode or None)
    except sqlite3.IntegrityError:
        flash("同名の場所が既に登録されています。", "warning")
    except Exception as exc:  # noqa: BLE001
        flash(f"場所の登録に失敗しました: {exc}", "danger")
    else:
        label = entry.get("location_name") or name
        if entry.get("setting_mode"):
            label = f"{label} ({entry['setting_mode']})"
        flash(f"場所を登録しました: {label} [ID: {entry['location_id']}]", "success")
    return redirect(url_for("main.detect"))

@main.route("/detect", methods=["GET", "POST"])
def detect():
    global batch_status
    upload_folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_folder, exist_ok=True)
    uploaded_files = [f for f in os.listdir(upload_folder) if allowed_file(f)]
    available_folders = sorted([name for name in os.listdir(upload_folder) if os.path.isdir(os.path.join(upload_folder, name))])
    folder_summaries = _gather_folder_summaries(upload_folder, available_folders)
    metrics_snapshot = capture_system_metrics()
    locations = list_locations()
    location_ids: set[int] = set()
    for loc in locations:
        try:
            candidate = int(loc.get("location_id"))  # type: ignore[arg-type]
        except (TypeError, ValueError, AttributeError):
            continue
        if candidate > 0:
            location_ids.add(candidate)

    if request.method == "POST":
        if request.form.get('batch_process'):
            folder_name = request.form.get('selected_folder')
            if not folder_name:
                flash('フォルダを選択してください。', 'danger')
                return redirect(url_for('main.detect'))
            alias_dir = os.path.join(upload_folder, folder_name)
            profile_input = (request.form.get('batch_profile') or '').strip()
            auto_postprocess = _coerce_checkbox(request.form.get('batch_auto_postprocess'))
            auto_csv = _coerce_checkbox(request.form.get('batch_csv'))
            process_year = _parse_process_year(request.form.get('batch_year'))
            process_location_id = _parse_location_id(
                request.form.get('batch_location_id'), allowed_ids=location_ids
            )
            if request.form.get('batch_location_id') and process_location_id is None:
                flash('選択した場所IDが無効です。', 'danger')
                return redirect(url_for('main.detect'))

            updated_settings = save_folder_settings(
                alias_dir,
                {
                    "profile": profile_input,
                    "auto_postprocess": auto_postprocess,
                    "auto_csv": auto_csv,
                    "process_year": process_year,
                    "location_id": process_location_id,
                },
            )

            profile_name = updated_settings.get('profile') or None
            export_csv = bool(updated_settings.get('auto_csv'))
            auto_postprocess_enabled = bool(updated_settings.get('auto_postprocess'))
            folder_path, is_link, exists, source_path = resolve_registered_folder(upload_folder, folder_name)
            if not exists:
                missing_hint = source_path or folder_path
                flash(f"指定したフォルダが見つかりません: {missing_hint}", 'danger')
                return redirect(url_for('main.detect'))

            summary_lookup = {item["name"]: item for item in folder_summaries}
            planned_total = summary_lookup.get(folder_name, {}).get("count", 0)

            def folder_worker():
                global batch_status
                batch_status.update(
                    status='processing',
                    message=f"{folder_name} 内の動画を準備中です...",
                    results=[],
                    folder=folder_name,
                    current=0,
                    total=planned_total,
                    current_video=None,
                    csv_bundle=None,
                )

                def normalize_result(item: Optional[Dict[str, Optional[str]]]) -> Dict[str, Optional[str]]:
                    record: Dict[str, Optional[str]] = dict(item or {})
                    display_override = record.pop('video_display', None)
                    raw_video = record.get('video')
                    if display_override:
                        record['video'] = display_override
                    elif raw_video:
                        formatted = _format_relative_path(str(raw_video), folder_path)
                        record['video'] = formatted or os.path.basename(str(raw_video))
                    if record.get('csv_path'):
                        try:
                            record['csv_path'] = os.path.relpath(record['csv_path'], os.getcwd())
                        except ValueError:
                            pass
                    if 'postprocess' not in record:
                        record['postprocess'] = None
                    elif record['postprocess'] is not None:
                        record['postprocess'] = str(record['postprocess'])
                    counts_raw = record.get('detection_counts')
                    if isinstance(counts_raw, dict):
                        converted: Dict[str, int] = {}
                        for key, value in counts_raw.items():
                            if value is None:
                                continue
                            try:
                                converted[str(key)] = int(value)
                            except (TypeError, ValueError):
                                continue
                        record['detection_summary'] = _format_detection_summary_text(converted)
                    else:
                        record['detection_summary'] = record.get('detection_summary') or '-'
                    return record

                def folder_callback(
                    phase: str,
                    index: int,
                    total: int,
                    video_name: Optional[str],
                    result: Optional[Dict[str, Optional[str]]],
                ) -> None:
                    nonlocal planned_total
                    if total != planned_total:
                        planned_total = total
                    current_results = list(batch_status.get('results', []))

                    if phase == 'start':
                        status_message = (
                            f"{folder_name} 内に対象動画が {total} 本見つかりました。"
                            if total
                            else f"{folder_name} 内に対象動画が見つかりません。"
                        )
                        batch_status.update(
                            message=status_message,
                            total=total,
                            current=0,
                            current_video=None,
                        )
                        return

                    if phase == 'video_start':
                        indicator = f"{index}/{total}" if total else f"{index}件目"
                        batch_status.update(
                            message=f"{folder_name} 内の {indicator} を処理中: {video_name}",
                            current=max(0, index - 1),
                            total=total,
                            current_video=video_name,
                        )
                        return

                    if phase == 'video_done' and result is not None:
                        normalized = normalize_result(result)
                        current_results.append(normalized)
                        complete_message = f"{folder_name} 内の {index}/{total} 本を処理済み。"
                        if normalized.get('error'):
                            complete_message = f"{folder_name} 内の {index}/{total} 本目でエラーが発生しました。"
                        batch_status.update(
                            message=complete_message,
                            current=min(index, total),
                            total=total,
                            current_video=None,
                            results=current_results,
                        )
                        return

                try:
                    def postprocess_handler(
                        run_id: int,
                        settings: ResolvedFolderSettings,
                    ) -> Optional[str]:
                        if not settings.auto_postprocess:
                            return None
                        try:
                            task = PostProcessTask(
                                run_id=run_id,
                                action='all_postprocess',
                                task_type=ACTION_TASK_TYPES['all_postprocess'],
                            )
                            started_now, waiting_ahead = enqueue_post_process_task(task)
                            if started_now:
                                return "後処理を即時開始"
                            if waiting_ahead:
                                return f"後処理キュー登録 ({waiting_ahead}件待ち)"
                            return "後処理キュー登録"
                        except Exception as exc:  # noqa: BLE001
                            return f"後処理登録エラー: {exc}"

                    folder_result = process_video_folder(
                        folder_path,
                        profile_name or None,
                        export_csv,
                        progress_callback=update_yolo_progress,
                        frame_parallelism=None,
                        folder_callback=folder_callback,
                        folder_alias=folder_name,
                        postprocess_handler=postprocess_handler,
                        include_subdirectories=True,
                        default_auto_postprocess=auto_postprocess_enabled,
                        folder_settings_root=alias_dir,
                        default_process_year=updated_settings.get("process_year"),
                        default_location_id=updated_settings.get("location_id"),
                    )
                    current_results = list(batch_status.get('results', []))
                    has_error = any(entry.get('error') for entry in current_results)
                    bundle_display: Optional[str] = None
                    if isinstance(folder_result, FolderProcessingResult) and folder_result.csv_bundle_path:
                        try:
                            bundle_display = os.path.relpath(folder_result.csv_bundle_path, os.getcwd())
                        except ValueError:
                            bundle_display = folder_result.csv_bundle_path
                    if not current_results and planned_total == 0:
                        message = '対象となる動画ファイルが見つかりませんでした。'
                        status = 'idle'
                    elif has_error:
                        message = '一部の動画でエラーが発生しました。'
                        status = 'error'
                    else:
                        message = f"{folder_name} 内の {len(current_results)} 本の処理が完了しました。"
                        status = 'complete'
                    batch_status.update(status=status, message=message, csv_bundle=bundle_display)
                except Exception as exc:
                    batch_status.update(
                        status='error',
                        message=str(exc),
                        results=[],
                        folder=folder_name,
                        current=0,
                        total=planned_total,
                        current_video=None,
                        csv_bundle=None,
                    )

            threading.Thread(target=folder_worker, daemon=True).start()
            return redirect(url_for('main.detect'))
        else:
            video_name = request.form.get("selected_video")
            if not video_name:
                flash("動画が選択されていません。", "danger")
                return redirect(url_for('main.detect'))
            video_path = os.path.join(upload_folder, video_name)
            profile_raw = request.form.get("single_profile") or ""
            profile_stripped = profile_raw.strip()
            profile_candidate = sanitize_profile_name(profile_stripped) if profile_stripped else ""
            if profile_stripped and not profile_candidate:
                flash("キャリブレーション名には英数字・ハイフン・アンダースコアのみ使用できます。", "danger")
                return redirect(url_for('main.detect'))
            process_year = _parse_process_year(request.form.get("single_year"))
            process_location_id = _parse_location_id(
                request.form.get("single_location_id"), allowed_ids=location_ids
            )
            if request.form.get("single_location_id") and process_location_id is None:
                flash("選択した場所IDが無効です。", "danger")
                return redirect(url_for('main.detect'))
            update_yolo_progress(0, 0, "processing")

            def worker():
                try:
                    video_result = process_video(
                        video_path,
                        progress_callback=update_yolo_progress,
                        frame_parallelism=None,
                        process_year=process_year,
                        location_id=process_location_id,
                    )
                    message = _format_yolo_completion_message(video_result)
                    if profile_candidate:
                        try:
                            applied_profile = apply_calibration_profile(video_result.run_id, profile_candidate)
                            message += f"<br>キャリブレーション '{applied_profile}' を適用しました。"
                        except Exception as exc:  # noqa: BLE001
                            error_message = f"キャリブレーション適用に失敗しました: {exc}"
                            print(f"[detect] {error_message}")
                            message += f"<br>{error_message}"
                    update_yolo_progress(0, 0, "complete", message)
                except Exception as e:
                    update_yolo_progress(0, 0, "error", f"YOLO処理中にエラーが発生しました: {e}")

            threading.Thread(target=worker, daemon=True).start()
            return redirect(url_for('main.detect'))

    batch_status_for_view = dict(batch_status)
    display_results: list[Dict[str, Optional[str]]] = []
    for entry in batch_status.get("results", []):
        record = dict(entry)
        counts_raw = record.get("detection_counts")
        if isinstance(counts_raw, dict):
            converted: Dict[str, int] = {}
            for key, value in counts_raw.items():
                if value is None:
                    continue
                try:
                    converted[str(key)] = int(value)
                except (TypeError, ValueError):
                    continue
            record["detection_summary"] = _format_detection_summary_text(converted)
        else:
            record["detection_summary"] = record.get("detection_summary") or "-"
        models_raw = record.get("models_used")
        if isinstance(models_raw, (list, tuple)):
            labels = [str(item) for item in models_raw if item]
            record["models_label"] = " / ".join(labels) if labels else "-"
        elif isinstance(models_raw, str) and models_raw.strip():
            record["models_label"] = models_raw.strip()
        else:
            record["models_label"] = "-"
        display_results.append(record)
    batch_status_for_view["results"] = display_results

    calib_dir = ensure_calibration_dir()
    available_profiles = [
        os.path.basename(p).replace(".json", "") for p in glob.glob(os.path.join(calib_dir, "*.json"))
    ]

    return render_template(
        "detect.html",
        uploaded_files=uploaded_files,
        available_folders=available_folders,
        progress=yolo_progress,
        batch_status=batch_status_for_view,
        folder_summaries=folder_summaries,
        system_metrics=_serialize_metrics(metrics_snapshot),
        available_profiles=available_profiles,
        locations=locations,
    )


@main.route("/api/system_metrics")
def system_metrics_api():
    metrics_snapshot = capture_system_metrics()
    return jsonify(_serialize_metrics(metrics_snapshot))


@main.route("/progress")
def progress():
    return jsonify(yolo_progress)


@main.route("/api/batch_status")
def batch_status_api():
    return jsonify(batch_status)

@main.route("/calibrate", methods=["POST"])
def calibrate():
    run_id_raw = request.form.get('run_id')
    profile_name_raw = request.form.get('profile_name')
    if not run_id_raw or not profile_name_raw:
        flash("Run IDとプロファイル名を入力してください。", "danger")
        return redirect(url_for('main.post_process'))
    try:
        run_id = int(run_id_raw)
    except ValueError:
        flash("Run IDの形式が正しくありません。", "danger")
        return redirect(url_for('main.post_process'))
    safe_profile = sanitize_profile_name(profile_name_raw)
    if not safe_profile:
        flash("プロファイル名には英数字・ハイフン・アンダースコアのみ使用できます。", "danger")
        return redirect(url_for('main.post_process'))
    flash("Web版キャリブレーションツールを新しいタブで開きます。完了後に保存ボタンを押してください。", "info")
    return redirect(url_for('main.calibration_page', run_id=run_id, profile_name=safe_profile))

@main.route("/calibration", methods=["GET"])
def calibration_page():
    run_id = request.args.get('run_id', type=int)
    raw_profile = request.args.get('profile_name', '')
    path_hints = [value for value in request.args.getlist('path_hint') if value]
    context = {
        'run_id': run_id,
        'profile_name': sanitize_profile_name(raw_profile),
        'video_filename': None,
        'error': None,
        'candidate_paths': None,
        'path_hints': path_hints,
    }
    if not run_id:
        context['error'] = "Run IDが指定されていません。"
        return render_template("calibration.html", **context)

    upload_folder = current_app.config['UPLOAD_FOLDER']
    info = get_run_video_info(run_id, upload_folder, path_hints=path_hints)
    if not info:
        context['error'] = f"Run ID {run_id} に対応するデータが見つかりません。"
        return render_template("calibration.html", **context)
    if not os.path.exists(info['path']):
        context['error'] = f"動画ファイルが見つかりません: {info['path']}"
        context['candidate_paths'] = info.get('candidates')
        return render_template("calibration.html", **context)

    if not context['profile_name']:
        fallback_name = sanitize_profile_name(info.get('profile_name') or '')
        if not fallback_name:
            fallback_name = _derive_default_profile_name(info)
        context['profile_name'] = fallback_name
    context['video_filename'] = info['filename']
    context['candidate_paths'] = info.get('candidates')
    return render_template("calibration.html", **context)

@main.route("/api/calibration/<int:run_id>/metadata")
def calibration_metadata(run_id):
    upload_folder = current_app.config['UPLOAD_FOLDER']
    path_hints = [value for value in request.args.getlist('path_hint') if value]
    info = get_run_video_info(run_id, upload_folder, path_hints=path_hints)
    if not info:
        return jsonify({"error": "対象のRunが見つかりません。"}), 404
    if not os.path.exists(info['path']):
        return jsonify({
            "error": "動画ファイルが見つかりません。",
            "candidates": info.get('candidates', []),
        }), 404
    try:
        stats = probe_video(info['path'])
    except FileNotFoundError:
        return jsonify({"error": "動画ファイルが見つかりません。"}), 404
    except Exception:
        return jsonify({"error": "動画を読み込めませんでした。"}), 500
    return jsonify({
        "run_id": run_id,
        "frame_count": stats['frame_count'],
        "width": stats['width'],
        "height": stats['height'],
        "fps": info['fps'],
        "video_filename": info['filename'],
        "current_profile": info['profile_name'],
    })

@main.route("/api/calibration/<int:run_id>/frame")
def calibration_frame(run_id):
    upload_folder = current_app.config['UPLOAD_FOLDER']
    path_hints = [value for value in request.args.getlist('path_hint') if value]
    info = get_run_video_info(run_id, upload_folder, path_hints=path_hints)
    if not info or not os.path.exists(info['path']):
        return Response(status=404)
    frame_idx = request.args.get('frame', default=0, type=int)
    requested_width = request.args.get('width', type=int)
    frame = load_video_frame(info['path'], frame_idx, requested_width)
    if frame is None:
        return Response(status=404)
    ok, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        return Response(status=500)
    resp = Response(buffer.tobytes(), mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'no-store, max-age=0'
    return resp

@main.route("/api/calibration/<int:run_id>/data")
def calibration_data(run_id):
    upload_folder = current_app.config['UPLOAD_FOLDER']
    path_hints = [value for value in request.args.getlist('path_hint') if value]
    info = get_run_video_info(run_id, upload_folder, path_hints=path_hints)
    if not info:
        return jsonify({"data": None, "profile_name": None})
    requested = sanitize_profile_name(request.args.get('profile_name', ''))
    fallback = sanitize_profile_name(info.get('profile_name') or '')
    payload = load_calibration_payload(run_id, requested or fallback)
    return jsonify({
        "data": payload,
        "profile_name": requested or fallback
    })


@main.route("/api/calibration/<int:run_id>/lane_test", methods=["POST"])
def calibration_lane_test(run_id):
    upload_folder = current_app.config['UPLOAD_FOLDER']
    path_hints = [value for value in request.args.getlist('path_hint') if value]
    info = get_run_video_info(run_id, upload_folder, path_hints=path_hints)
    if not info:
        return jsonify({"error": "対象のRunが見つかりません。"}), 404

    raw_payload = request.get_json(silent=True) or {}
    lane_lines = None
    error_message: Optional[str] = None

    if isinstance(raw_payload, Mapping):
        candidate_lines = raw_payload.get("lines")
        has_drawn_lines = False
        if isinstance(candidate_lines, Mapping):
            has_drawn_lines = bool(candidate_lines.get("left_white_line")) or bool(
                candidate_lines.get("right_white_line")
            )
        if has_drawn_lines:
            lane_lines, error_message = prepare_lane_test_lines(raw_payload)
            if error_message:
                return jsonify({"error": error_message}), 400

    if lane_lines is None:
        requested_profile = ""
        if isinstance(raw_payload, Mapping):
            requested_profile = sanitize_profile_name(raw_payload.get("profile_name"))
        if not requested_profile:
            requested_profile = sanitize_profile_name(request.args.get("profile_name", ""))
        fallback_profile = sanitize_profile_name(info.get("profile_name") or "")
        calibration_payload = load_calibration_payload(
            run_id,
            requested_profile or fallback_profile,
        )
        if calibration_payload:
            lane_lines, error_message = prepare_lane_test_lines(calibration_payload)

    if lane_lines is None or not lane_lines.left or not lane_lines.right:
        message = error_message or "白線情報が不足しているため距離を計算できません。"
        return jsonify({"error": message}), 400

    points = raw_payload.get("points") if isinstance(raw_payload, Mapping) else None
    if not isinstance(points, Sequence) or not points:
        return jsonify({"results": []})

    results = calculate_lane_test_distances(lane_lines, points)
    return jsonify({"results": results})


@main.route("/api/calibration/<int:run_id>/save", methods=["POST"])
def calibration_save(run_id):
    upload_folder = current_app.config['UPLOAD_FOLDER']
    path_hints = [value for value in request.args.getlist('path_hint') if value]
    info = get_run_video_info(run_id, upload_folder, path_hints=path_hints)
    if not info:
        return jsonify({"error": "対象のRunが見つかりません。"}), 404
    if not os.path.exists(info['path']):
        return jsonify({
            "error": "動画ファイルが見つかりません。",
            "candidates": info.get('candidates', []),
        }), 404

    raw_payload = request.get_json(silent=True) or {}
    profile_name, prepared_payload, error_message = prepare_save_payload(run_id, raw_payload)
    if error_message:
        return jsonify({"error": error_message}), 400
    if not profile_name or not prepared_payload:
        return jsonify({"error": "保存するデータが無効です。"}), 400

    calib_dir = ensure_calibration_dir()
    try:
        save_path = save_calibration_payload(profile_name, run_id, prepared_payload, calib_dir)
        update_run_calibration_profile(run_id, profile_name)
    except Exception as exc:
        return jsonify({"error": f"保存中にエラーが発生しました: {exc}"}), 500

    return jsonify({
        "status": "ok",
        "profile_name": profile_name,
        "save_path": save_path,
    })

@main.route("/apply_calibration", methods=["POST"])
def apply_calibration():
    run_id_raw = request.form.get('run_id')
    profile_raw = request.form.get('profile_name')
    try:
        run_id = int(run_id_raw)
    except (TypeError, ValueError):
        flash("Run IDの形式が正しくありません。", "danger")
        return redirect(url_for('main.post_process'))
    profile_name = sanitize_profile_name(profile_raw)
    try:
        update_run_calibration_profile(run_id, profile_name)
        flash(f"Run ID {run_id} にプロファイル '{profile_name}' を適用しました。", "success")
    except Exception as e:
        flash(f"プロファイルの適用中にエラーが発生しました: {e}", "danger")
    return redirect(url_for('main.post_process'))


@main.route("/delete_profile", methods=["POST"])
def delete_profile():
    wants_json = "application/json" in (request.headers.get("Accept") or "")
    profile_raw = request.form.get("profile_name")
    if not profile_raw and request.is_json:
        payload = request.get_json(silent=True) or {}
        profile_raw = payload.get("profile_name")

    safe_name = sanitize_profile_name(profile_raw)
    if not safe_name:
        message = "削除するプロファイル名を選択してください。"
        if wants_json:
            return jsonify({"status": "error", "message": message}), 400
        flash(message, "danger")
        return redirect(url_for('main.post_process'))

    try:
        cleared_runs, removed_path = delete_calibration_profile(safe_name)
    except FileNotFoundError:
        message = f"プロファイル '{safe_name}' は既に存在しません。"
        if wants_json:
            return jsonify({"status": "error", "message": message}), 404
        flash(message, "warning")
        return redirect(url_for('main.post_process'))
    except ValueError as exc:
        message = str(exc)
        if wants_json:
            return jsonify({"status": "error", "message": message}), 400
        flash(message, "danger")
        return redirect(url_for('main.post_process'))
    except OSError as exc:
        message = f"プロファイルの削除に失敗しました: {exc}"
        if wants_json:
            return jsonify({"status": "error", "message": message}), 500
        flash(message, "danger")
        return redirect(url_for('main.post_process'))

    cleared_count = len(cleared_runs)
    if cleared_count:
        message = f"プロファイル '{safe_name}' を削除し、{cleared_count} 件のRunから設定をクリアしました。"
    else:
        message = f"プロファイル '{safe_name}' を削除しました。"

    if wants_json:
        return jsonify(
            {
                "status": "ok",
                "message": message,
                "profile_name": safe_name,
                "removed_path": removed_path,
                "cleared_run_ids": cleared_runs,
            }
        )

    flash(message, "success")
    return redirect(url_for('main.post_process'))


@main.route("/post_process")
def post_process():
    error_response = _ensure_database_ready()
    if error_response is not None:
        return error_response
    opt_folder = os.getenv("Opt_files", "output")
    calib_dir = os.path.join(opt_folder, "calibrations")
    os.makedirs(calib_dir, exist_ok=True)
    available_profiles = [os.path.basename(p).replace('.json', '') for p in glob.glob(os.path.join(calib_dir, "*.json"))]
    logs = get_all_process_logs()
    folder_batches = list_folder_batches()
    selected_run_id = request.args.get('selected_run_id', type=int)
    video_fonts = discover_font_files()
    normalized_defaults = normalize_video_options(DEFAULT_VIDEO_OPTIONS, [entry['path'] for entry in video_fonts])
    return render_template(
        "post_process.html",
        logs=logs,
        folder_batches=folder_batches,
        available_profiles=available_profiles,
        selected_run_id=selected_run_id,
        progress=post_process_progress,
        video_fonts=video_fonts,
        video_option_defaults=normalized_defaults,
    )

@main.route("/post_process_action", methods=["POST"])
def post_process_action():
    error_response = _ensure_database_ready()
    if error_response is not None:
        return error_response
    target_mode_raw = (request.form.get("target_mode") or "run").strip().lower()
    target_mode = "folder" if target_mode_raw == "folder" else "run"
    action = request.form.get("action")
    wants_json = "application/json" in (request.headers.get("Accept") or "")

    folder_alias: Optional[str] = None
    run_ids: List[int] = []
    requested_range_start: Optional[int] = None
    requested_range_end: Optional[int] = None

    if action == "run_range_postprocess":
        target_mode = "range"
        start_raw = (request.form.get("run_range_start") or "").strip()
        end_raw = (request.form.get("run_range_end") or "").strip()
        if not start_raw and not end_raw:
            message = "Run ID範囲を入力してください。"
            if wants_json:
                return jsonify({"status": "error", "message": message}), 400
            flash(message, "danger")
            return redirect(url_for('main.post_process'))
        try:
            requested_start = int(start_raw) if start_raw else None
        except (TypeError, ValueError):
            requested_start = None
        try:
            requested_end = int(end_raw) if end_raw else None
        except (TypeError, ValueError):
            requested_end = None
        if requested_start is None and requested_end is None:
            message = "Run ID範囲の値が正しくありません。"
            if wants_json:
                return jsonify({"status": "error", "message": message}), 400
            flash(message, "danger")
            return redirect(url_for('main.post_process'))
        if requested_start is None:
            requested_start = requested_end
        if requested_end is None:
            requested_end = requested_start
        if requested_start is None or requested_end is None or requested_start <= 0 and requested_end <= 0:
            message = "Run ID範囲には正の整数を指定してください。"
            if wants_json:
                return jsonify({"status": "error", "message": message}), 400
            flash(message, "danger")
            return redirect(url_for('main.post_process'))
        if requested_start <= 0:
            requested_start = requested_end
        if requested_end <= 0:
            requested_end = requested_start
        if requested_start > requested_end:
            requested_start, requested_end = requested_end, requested_start
        requested_range_start = requested_start
        requested_range_end = requested_end
        run_ids = get_run_ids_in_range(requested_start, requested_end)
        if not run_ids:
            message = "指定範囲内に後処理可能なRunが見つかりません。"
            if wants_json:
                return jsonify({
                    "status": "error",
                    "message": message,
                    "run_range": {
                        "start": requested_start,
                        "end": requested_end,
                    },
                }), 404
            flash(message, "danger")
            return redirect(url_for('main.post_process'))
        run_id = run_ids[0]
    elif target_mode == "folder":
        folder_alias_raw = request.form.get("folder_alias") or ""
        folder_alias = normalize_existing_folder_alias(folder_alias_raw)
        if not folder_alias:
            message = "フォルダ名を選択してください。"
            if wants_json:
                return jsonify({"status": "error", "message": message}), 400
            flash(message, "danger")
            return redirect(url_for('main.post_process'))
        run_ids = get_run_ids_by_folder(folder_alias)
        if not run_ids:
            message = "指定フォルダに紐付くRunが見つかりません。"
            if wants_json:
                return jsonify({"status": "error", "message": message}), 404
            flash(message, "danger")
            return redirect(url_for('main.post_process'))
        run_id = run_ids[0]
    else:
        run_id_raw = request.form.get("run_id")
        if not run_id_raw:
            message = "Runを選択してください。"
            if wants_json:
                return jsonify({"status": "error", "message": message}), 400
            flash(message, "danger")
            return redirect(url_for('main.post_process'))
        try:
            run_id = int(run_id_raw)
        except (TypeError, ValueError):
            message = "Run IDの形式が正しくありません。"
            if wants_json:
                return jsonify({"status": "error", "message": message}), 400
            flash(message, "danger")
            return redirect(url_for('main.post_process'))
        run_ids = [run_id]

    task_type = ACTION_TASK_TYPES.get(action or "")
    if not task_type:
        message = "不明なアクションが指定されました。"
        if wants_json:
            return jsonify({"status": "error", "message": message}), 400
        flash(message, "danger")
        return redirect(url_for('main.post_process', selected_run_id=run_id))

    if target_mode == "folder" and task_type == "video":
        message = "フォルダ処理では動画生成を利用できません。"
        if wants_json:
            return jsonify({"status": "error", "message": message}), 400
        flash(message, "danger")
        return redirect(url_for('main.post_process'))

    video_options_payload = None
    if task_type == "video" and target_mode == "run":
        font_entries = discover_font_files()
        available_font_paths = [entry['path'] for entry in font_entries]
        bool_fields = {
            'show_vehicle_box': 'video_show_vehicle_box',
            'show_tire_boxes': 'video_show_tire_boxes',
            'show_trace': 'video_show_trace',
            'show_measurement': 'video_show_measurement',
            'show_approach_lines': 'video_show_approach_lines',
            'show_lane_left': 'video_show_lane_left',
            'show_lane_right': 'video_show_lane_right',
            'show_lane_center': 'video_show_lane_center',
            'show_homography_overlay': 'video_show_homography_overlay',
            'show_homography_only': 'video_show_homography_only',
            'label_group_id': 'video_label_group',
            'label_speed': 'video_label_speed',
            'label_lane_distance': 'video_label_lane',
            'label_approach': 'video_label_approach',
            'label_clearance': 'video_label_clearance',
            'label_direction': 'video_label_direction',
            'label_overtake': 'video_label_overtake',
            'label_acceleration': 'video_label_acceleration',
        }
        has_any_option = any(name in request.form for name in bool_fields.values())
        explicit_flag = (request.form.get('video_options_submitted') or '').strip() == '1'
        raw_options = {}
        for key, field_name in bool_fields.items():
            if explicit_flag or has_any_option:
                raw_options[key] = field_name in request.form
            else:
                raw_options[key] = DEFAULT_VIDEO_OPTIONS.get(key)
        raw_options['font_size'] = request.form.get('video_font_size') or DEFAULT_VIDEO_OPTIONS['font_size']
        raw_options['font_path'] = request.form.get('video_font_path')
        raw_options['output_format'] = request.form.get('video_output_format') or DEFAULT_VIDEO_OPTIONS['output_format']
        raw_options['output_name_mode'] = request.form.get('video_output_name_mode') or DEFAULT_VIDEO_OPTIONS['output_name_mode']
        video_options_payload = normalize_video_options(raw_options, available_font_paths)

    applied_profile: Optional[str] = None
    applied_profile_runs: list[int] = []
    applied_profile_scopes: list[str] = []
    applied_profile_scope_matches: dict[str, list[int]] = {}
    unmatched_profile_scopes: list[str] = []
    if target_mode == "folder":
        folder_profile_raw = request.form.get('folder_profile_name') or ""
        sanitized_profile = sanitize_profile_name(folder_profile_raw)
        if sanitized_profile:
            scope_raw = request.form.get('folder_profile_scope') or ""
            scope_entries = _split_profile_scope_entries(scope_raw)
            target_runs = run_ids
            if scope_entries:
                upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
                matched_runs, scope_hits, unmatched_scopes = _match_runs_to_scopes(
                    run_ids,
                    scope_entries,
                    upload_folder,
                )
                if not matched_runs:
                    message = "指定したサブフォルダや動画に一致するRunが見つかりません。"
                    if wants_json:
                        return (
                            jsonify(
                                {
                                    "status": "error",
                                    "message": message,
                                    "profile_scope": scope_entries,
                                }
                            ),
                            404,
                        )
                    flash(message, "danger")
                    return redirect(url_for('main.post_process'))
                target_runs = matched_runs
                applied_profile_scopes = scope_entries
                applied_profile_scope_matches = scope_hits
                unmatched_profile_scopes = unmatched_scopes
            for target_run in target_runs:
                update_run_calibration_profile(target_run, sanitized_profile)
            applied_profile = sanitized_profile
            applied_profile_runs = target_runs

    task = PostProcessTask(
        run_id=run_id,
        action=action,
        task_type=task_type,
        options=video_options_payload,
        folder_alias=folder_alias,
        run_ids=run_ids,
    )
    started_now, waiting_ahead = enqueue_post_process_task(task)

    response_payload = {
        "status": "accepted",
        "progress": post_process_progress,
        "run_id": run_id,
        "run_ids": run_ids,
        "task_id": task.task_id,
        "task_type": task.task_type,
        "queue_position": waiting_ahead,
        "started": started_now,
    }
    if action == "run_range_postprocess":
        response_payload["run_range"] = {
            "start": requested_range_start,
            "end": requested_range_end,
            "resolved_run_ids": run_ids,
        }
    if video_options_payload is not None:
        response_payload['video_options'] = video_options_payload
    if folder_alias:
        response_payload['folder_alias'] = folder_alias
    if applied_profile:
        response_payload['applied_profile'] = applied_profile
    if applied_profile_runs:
        response_payload['applied_profile_runs'] = applied_profile_runs
    if applied_profile_scope_matches:
        response_payload['applied_profile_scope_matches'] = applied_profile_scope_matches
    if applied_profile_scopes:
        response_payload['applied_profile_scope'] = applied_profile_scopes
    if unmatched_profile_scopes:
        response_payload['unmatched_profile_scope'] = unmatched_profile_scopes
    if wants_json:
        return jsonify(response_payload)

    if applied_profile_runs:
        if applied_profile_scopes:
            scope_label = ", ".join(applied_profile_scopes)
            flash(
                f"プロファイル '{applied_profile}' を {len(applied_profile_runs)} 件のRunに適用しました（対象: {scope_label}）。",
                "success",
            )
        else:
            flash(
                f"プロファイル '{applied_profile}' を {len(applied_profile_runs)} 件のRunに適用しました。",
                "success",
            )
    if unmatched_profile_scopes:
        missing_label = ", ".join(unmatched_profile_scopes)
        flash(
            f"次の指定には一致するRunが見つかりませんでした: {missing_label}",
            "warning",
        )

    if started_now:
        if action == "run_range_postprocess":
            if len(run_ids) > 1:
                flash(
                    f"Run ID {run_ids[0]}～{run_ids[-1]} の後処理を開始しました。対象 {len(run_ids)} 件。進捗欄をご確認ください。",
                    "info",
                )
            else:
                flash(
                    f"Run ID {run_ids[0]} の後処理を開始しました。進捗欄をご確認ください。",
                    "info",
                )
        elif folder_alias and len(run_ids) > 1:
            flash(f"フォルダ '{folder_alias}' の後処理を開始しました。進捗欄をご確認ください。", "info")
        else:
            flash("処理を開始しました。進捗欄をご確認ください。", "info")
    else:
        flash(f"処理を予約しました。前に {waiting_ahead} 件のタスクがあります。", "info")
    return redirect(url_for('main.post_process', selected_run_id=run_id))


@main.route("/post_process/folder_runs/<path:folder_alias>", methods=["GET"])
def post_process_folder_runs(folder_alias: str):
    normalized = normalize_existing_folder_alias(folder_alias)
    if not normalized:
        return jsonify({"status": "error", "message": "フォルダ名が不正です。"}), 400

    run_ids = get_run_ids_by_folder(normalized)
    if not run_ids:
        return jsonify({"status": "error", "message": "指定したフォルダのRunが見つかりません。"}), 404

    overview = _build_folder_profile_overview(normalized, run_ids)
    overview['status'] = 'ok'
    overview['run_count'] = overview.get('total_runs', len(run_ids))
    return jsonify(overview)


@main.route("/post_process/apply_scope_profile", methods=["POST"])
def apply_scope_profile():
    payload = request.get_json(silent=True) or {}
    folder_alias_raw = payload.get('folder_alias') or ''
    normalized_alias = normalize_existing_folder_alias(folder_alias_raw)
    if not normalized_alias:
        return jsonify({"status": "error", "message": "フォルダ名が不正です。"}), 400

    run_ids = get_run_ids_by_folder(normalized_alias)
    if not run_ids:
        return jsonify({"status": "error", "message": "指定したフォルダのRunが見つかりません。"}), 404

    upload_folder = current_app.config.get('UPLOAD_FOLDER', '')

    scope_profiles_payload = payload.get('scope_profiles')
    if isinstance(scope_profiles_payload, list):
        scope_changes: dict[str, dict[str, Any]] = {}
        for item in scope_profiles_payload:
            if not isinstance(item, dict):
                continue
            scope_value_raw = item.get('scope') or ''
            scope_normalized = normalize_existing_folder_alias(scope_value_raw)
            if not scope_normalized:
                continue
            profile_token = item.get('profile')
            if profile_token is None:
                continue
            profile_text = str(profile_token)
            if profile_text == '__CLEAR__':
                profile_value_item = ""
            else:
                profile_stripped = profile_text.strip()
                if not profile_stripped:
                    continue
                sanitized_profile = sanitize_profile_name(profile_stripped)
                if not sanitized_profile:
                    return jsonify(
                        {
                            "status": "error",
                            "message": f"サブフォルダ '{scope_value_raw}' のプロファイル名が不正です。",
                        }
                    ), 400
                profile_value_item = sanitized_profile

            scope_changes[scope_normalized] = {
                'profile': profile_value_item,
                'display': item.get('display') or '',
            }

        if not scope_changes:
            return jsonify({"status": "error", "message": "適用するサブフォルダが選択されていません。"}), 400

        scopes = list(scope_changes.keys())
        matched_runs, scope_hits, unmatched = _match_runs_to_scopes(run_ids, scopes, upload_folder)

        updated_summaries: list[dict[str, Any]] = []
        total_updated = 0
        for scope_value in scopes:
            target_runs = scope_hits.get(scope_value, [])
            if not target_runs:
                continue
            unique_targets = sorted(set(target_runs))
            profile_value_item = scope_changes[scope_value]['profile']
            for run_id in unique_targets:
                update_run_calibration_profile(run_id, profile_value_item)
            total_updated += len(unique_targets)
            updated_summaries.append(
                {
                    'scope': scope_value,
                    'applied_profile': profile_value_item,
                    'updated_run_ids': unique_targets,
                    'run_count': len(unique_targets),
                    'display': scope_changes[scope_value].get('display') or scope_value,
                }
            )

        response_payload: dict[str, Any] = {
            'status': 'ok',
            'folder_alias': normalized_alias,
            'updated_scopes': updated_summaries,
            'unmatched_scopes': unmatched,
            'run_count': total_updated,
        }
        return jsonify(response_payload)

    if payload.get('run_id') is not None:
        return jsonify({"status": "error", "message": "Run単位での変更はサポートされていません。サブフォルダを指定してください。"}), 400

    scope_raw = payload.get('scope') or ''
    scope_normalized = normalize_existing_folder_alias(scope_raw)
    if not scope_normalized:
        return jsonify({"status": "error", "message": "サブフォルダの指定が無効です。"}), 400
    last_segment = scope_normalized.rsplit("/", 1)[-1]
    _, scope_ext = os.path.splitext(last_segment)
    if scope_ext.lower() in FOLDER_VIDEO_EXTENSIONS:
        return jsonify({"status": "error", "message": "動画ファイル単位ではプロファイルを変更できません。サブフォルダを指定してください。"}), 400

    profile_raw = (payload.get('profile') or '')
    profile_stripped = profile_raw.strip()
    if profile_stripped:
        sanitized_profile = sanitize_profile_name(profile_stripped)
        if not sanitized_profile:
            return jsonify({"status": "error", "message": "プロファイル名には英数字・ハイフン・アンダースコアのみ使用できます。"}), 400
        profile_value = sanitized_profile
    else:
        profile_value = ""

    matched_runs, scope_hits, unmatched = _match_runs_to_scopes(
        run_ids,
        [scope_normalized],
        upload_folder,
    )
    if unmatched:
        return jsonify({"status": "error", "message": "指定したサブフォルダに一致するRunが見つかりません。"}), 404
    target_runs = scope_hits.get(scope_normalized, matched_runs)
    if not target_runs:
        return jsonify({"status": "error", "message": "指定したサブフォルダに一致するRunが見つかりません。"}), 404

    updated_run_ids = []
    for run_id in target_runs:
        update_run_calibration_profile(run_id, profile_value)
        updated_run_ids.append(run_id)

    updated_run_ids.sort()
    response = {
        "status": "ok",
        "folder_alias": normalized_alias,
        "applied_profile": profile_value,
        "updated_run_ids": updated_run_ids,
        "run_count": len(updated_run_ids),
    }
    response['scope'] = scope_normalized
    return jsonify(response)


@main.route("/post_process/apply_run_profiles", methods=["POST"])
def apply_run_profiles():
    payload = request.get_json(silent=True) or {}
    folder_alias_raw = payload.get('folder_alias') or ''
    normalized_alias = normalize_existing_folder_alias(folder_alias_raw)
    if not normalized_alias:
        return jsonify({"status": "error", "message": "フォルダ名が不正です。"}), 400

    run_id_values = payload.get('run_ids')
    if not isinstance(run_id_values, (list, tuple)):
        return jsonify({"status": "error", "message": "動画の指定が不正です。"}), 400

    normalized_run_ids: list[int] = []
    for value in run_id_values:
        try:
            candidate = int(value)
        except (TypeError, ValueError):
            continue
        if candidate > 0:
            normalized_run_ids.append(candidate)

    unique_run_ids = sorted(set(normalized_run_ids))
    if not unique_run_ids:
        return jsonify({"status": "error", "message": "動画が指定されていません。"}), 400

    folder_run_ids = set(get_run_ids_by_folder(normalized_alias))
    if not folder_run_ids:
        return jsonify({"status": "error", "message": "指定したフォルダのRunが見つかりません。"}), 404

    missing = [rid for rid in unique_run_ids if rid not in folder_run_ids]
    if missing:
        return jsonify(
            {
                "status": "error",
                "message": "指定した動画がフォルダ内に見つかりません。",
                "invalid_run_ids": missing,
            }
        ), 404

    profile_raw = (payload.get('profile') or '').strip()
    profile_value = ""
    if profile_raw and profile_raw != "__CLEAR__":
        sanitized = sanitize_profile_name(profile_raw)
        if not sanitized:
            return jsonify({"status": "error", "message": "プロファイル名には英数字・ハイフン・アンダースコアのみ使用できます。"}), 400
        profile_value = sanitized

    for run_id in unique_run_ids:
        update_run_calibration_profile(run_id, profile_value)

    return jsonify(
        {
            "status": "ok",
            "folder_alias": normalized_alias,
            "applied_profile": profile_value,
            "updated_run_ids": unique_run_ids,
            "run_count": len(unique_run_ids),
        }
    )


@main.route("/statistics", methods=["GET", "POST"])
def statistics_view():
    runs = list_detection_runs()
    selected_run_ids: list[str] = []
    downward_only = False
    selected_mode = DEFAULT_STATISTICS_MODE
    preview: Optional[Dict[str, Any]] = None
    chart_json: Optional[str] = None

    if request.method == "POST":
        selected_run_ids = request.form.getlist("stats_run_ids")
        downward_only = _coerce_checkbox(request.form.get("stats_downward_only"))
        selected_mode = request.form.get("stats_mode", DEFAULT_STATISTICS_MODE)
        if not selected_run_ids:
            flash("集計対象のRunを選択してください。", "warning")
        else:
            try:
                preview = generate_statistics_preview(
                    selected_run_ids,
                    downward_only=downward_only,
                    mode=selected_mode,
                )
                chart_data = preview.get("chart", {}) if preview else {}
                if chart_data.get("available"):
                    chart_json = json.dumps(chart_data.get("config"), ensure_ascii=False)
                selected_run_ids = [str(rid) for rid in preview.get("run_ids", [])]
                selected_mode = preview.get("mode", selected_mode)
            except ValueError as exc:
                flash(str(exc), "warning")
            except Exception as exc:  # pragma: no cover - runtime safeguard
                current_app.logger.exception("Failed to build statistics preview")
                flash(f"集計の生成に失敗しました: {exc}", "danger")

    return render_template(
        "statistics.html",
        runs=runs,
        preview=preview,
        selected_run_ids=selected_run_ids,
        downward_only=downward_only,
        selected_mode=selected_mode,
        chart_json=chart_json,
    )


@main.route("/export_statistics", methods=["POST"])
def export_statistics():
    run_ids = request.form.getlist("stats_run_ids")
    downward_only = _coerce_checkbox(request.form.get("stats_downward_only"))
    mode = request.form.get("stats_mode", DEFAULT_STATISTICS_MODE)
    if not run_ids:
        flash("統計に含めるRunを選択してください。", "warning")
        return redirect(url_for("main.post_process"))

    try:
        excel_path, _meta = export_statistics_workbook(
            run_ids,
            downward_only=downward_only,
            mode=mode,
        )
        resolved_excel_path = Path(excel_path).resolve()
        current_app.logger.info("Statistics Excel exported: %s", resolved_excel_path)
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("main.post_process"))
    except Exception as exc:
        current_app.logger.exception("Failed to export statistics")
        flash(f"統計データの出力に失敗しました: {exc}", "danger")
        return redirect(url_for("main.post_process"))

    return send_file(
        excel_path,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=os.path.basename(excel_path),
    )


@main.route("/post_process_progress")
def post_process_status():
    return jsonify(post_process_progress)


@main.route("/api/process_logs")
def api_process_logs():
    logs = get_all_process_logs()
    folders = list_folder_batches()
    return jsonify({"logs": logs, "folders": folders})


def _normalize_run_ids(raw_values: list[Any]) -> list[int]:
    normalized: list[int] = []
    for raw in raw_values:
        if raw is None or raw == "":
            continue
        try:
            normalized.append(int(raw))
        except (TypeError, ValueError):
            continue
    return normalized


def _format_manual_event_for_csv(key: str, value: Any) -> str:
    if value is None:
        return ""
    fmt = MANUAL_OVERTAKE_CSV_FORMATS.get(key)
    if fmt:
        try:
            return fmt.format(float(value))
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _format_manual_context_for_csv(key: str, value: Any) -> str:
    if value is None:
        return ""
    fmt = MANUAL_OVERTAKE_CONTEXT_CSV_FORMATS.get(key)
    if fmt:
        try:
            return fmt.format(float(value))
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _build_manual_context_rows(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        contexts = event.get("context_frames")
        if not contexts:
            continue
        event_id = event.get("manual_event_id")
        run_id = event.get("run_id")
        video_name = event.get("video_filename")
        for context in contexts:
            if not isinstance(context, dict):
                continue
            row = dict(context)
            row.setdefault("manual_event_id", event_id)
            row.setdefault("run_id", run_id)
            row.setdefault("video_filename", video_name)
            rows.append(row)
    return rows


def _filter_context_rows_by_window(
    context_rows: Sequence[Mapping[str, Any]], window: Optional[int]
) -> list[dict[str, Any]]:
    if window is None:
        return list(context_rows)

    filtered: list[dict[str, Any]] = []
    for row in context_rows:
        try:
            offset_val = int(row.get("offset_frames") or 0)
        except (TypeError, ValueError, AttributeError):
            offset_val = 0
        if abs(offset_val) <= window:
            filtered.append(dict(row))
    return filtered


def _build_manual_group_rows(
    context_rows: Sequence[Mapping[str, Any]],
    *,
    include_left: bool = True,
    include_flags: bool = False,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    bicycle_aliases = {alias.lower() for alias in get_bicycle_class_aliases()}

    for ctx in context_rows:
        base = {
            "manual_event_id": ctx.get("manual_event_id"),
            "run_id": ctx.get("run_id"),
            "video_filename": ctx.get("video_filename"),
            "offset_frames": ctx.get("offset_frames"),
            "frame_num": ctx.get("frame_num"),
            "video_time_s": ctx.get("video_time_s"),
            "clearance_distance_m": ctx.get("clearance_distance_m"),
            "clearance_distance_cm": ctx.get("clearance_distance_cm"),
            "clearance_distance_px": ctx.get("clearance_distance_px"),
            "lane_width_m": ctx.get("lane_width_m"),
        }

        lane_width_m = _float_or_none(ctx.get("lane_width_m")) or LANE_WIDTH_METERS

        for role, label in (("overtaker", "追い越し側"), ("overtaken", "追い越され側")):
            record = dict(base)
            record["role"] = label
            record["group_id"] = ctx.get(f"{role}_group_id")
            record["partner_group_id"] = ctx.get(
                "overtaken_group_id" if role == "overtaker" else "overtaker_group_id"
            )
            record["track_id"] = ctx.get(f"{role}_track_id")
            record["class_name"] = ctx.get(f"{role}_class_name")
            record["bbox_x1"] = ctx.get(f"{role}_x1")
            record["bbox_y1"] = ctx.get(f"{role}_y1")
            record["bbox_x2"] = ctx.get(f"{role}_x2")
            record["bbox_y2"] = ctx.get(f"{role}_y2")
            record["measure_x"] = ctx.get(f"{role}_measure_x")
            record["measure_y"] = ctx.get(f"{role}_measure_y")
            record["line_distance_m"] = ctx.get(f"{role}_line_distance_m")
            record["line_distance_cm"] = ctx.get(f"{role}_line_distance_cm")
            record["line_distance_px"] = ctx.get(f"{role}_line_distance_px")
            record["line_distance_px_ratio"] = ctx.get(
                f"{role}_line_distance_px_ratio"
            )

            ratio_val = _float_or_none(record.get("line_distance_px_ratio"))
            if ratio_val is None:
                lane_flag: Optional[str] = None
            else:
                lane_flag = "+" if ratio_val < 100 else "-"
            record["lane_position_flag"] = lane_flag

            left_m = _float_or_none(ctx.get(f"{role}_left_line_distance_m"))
            right_m = _float_or_none(ctx.get(f"{role}_right_line_distance_m"))

            if include_left:
                record["left_line_distance_m"] = left_m
                record["left_line_distance_cm"] = ctx.get(
                    f"{role}_left_line_distance_cm"
                )
                record["left_line_distance_px"] = ctx.get(
                    f"{role}_left_line_distance_px"
                )

            record["right_line_distance_m"] = right_m
            record["right_line_distance_cm"] = ctx.get(
                f"{role}_right_line_distance_cm"
            )
            record["right_line_distance_px"] = ctx.get(
                f"{role}_right_line_distance_px"
            )

            if include_flags:
                is_bicycle = str(record.get("class_name") or "").lower() in bicycle_aliases

                ratio_val = _float_or_none(record.get("line_distance_px_ratio"))
                record["bicycle_over_white_line"] = bool(
                    is_bicycle and ratio_val is not None and ratio_val >= 100
                )

                if left_m is not None and right_m is not None and lane_width_m:
                    record["crossed_center_line"] = bool(left_m > (lane_width_m / 2.0))
                else:
                    record["crossed_center_line"] = None

            results.append(record)

    return results


def _manual_export_filename(prefix: str, extension: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}.{extension}"


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric):
        return None
    return numeric


def _collect_event_measurement_y_values(event: Mapping[str, Any]) -> list[float]:
    if not isinstance(event, Mapping):
        return []
    values: list[float] = []
    for prefix in ("overtaker", "overtaken"):
        for suffix in ("measure_y", "manual_measure_y", "y2"):
            key = f"{prefix}_{suffix}"
            numeric = _float_or_none(event.get(key))
            if numeric is not None:
                values.append(numeric)
    return values


def _point_to_int_tuple(value: Any) -> Optional[tuple[int, int]]:
    if isinstance(value, Mapping):
        x_val = _float_or_none(value.get("x"))
        y_val = _float_or_none(value.get("y"))
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        x_val = _float_or_none(value[0])
        y_val = _float_or_none(value[1])
    else:
        return None

    if x_val is None or y_val is None:
        return None
    return int(round(x_val)), int(round(y_val))


def _bbox_from_mapping(det: Mapping[str, Any]) -> Optional[tuple[int, int, int, int]]:
    x1 = _float_or_none(det.get("x1"))
    y1 = _float_or_none(det.get("y1"))
    x2 = _float_or_none(det.get("x2"))
    y2 = _float_or_none(det.get("y2"))
    if None in (x1, y1, x2, y2):
        return None
    return (int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))


def _manual_event_detection_from_prefix(
    event: Mapping[str, Any], prefix: str
) -> dict[str, Any]:
    return {
        "measure_x": event.get(f"{prefix}_measure_x"),
        "measure_y": event.get(f"{prefix}_measure_y"),
        "manual_measure_x": event.get(f"{prefix}_measure_x"),
        "manual_measure_y": event.get(f"{prefix}_measure_y"),
        "x1": event.get(f"{prefix}_x1"),
        "y1": event.get(f"{prefix}_y1"),
        "x2": event.get(f"{prefix}_x2"),
        "y2": event.get(f"{prefix}_y2"),
        "scale_pixels_per_meter": event.get("scale_pixels_per_meter"),
        "x_pixels_per_meter": event.get("x_pixels_per_meter"),
    }


def _collect_tire_bboxes(event: Mapping[str, Any]) -> dict[str, list[tuple[int, int, int, int]]]:
    run_id = event.get("run_id")
    frame_num = event.get("frame_num")
    try:
        frame_value = int(frame_num) if frame_num is not None else None
    except (TypeError, ValueError):
        frame_value = None

    if run_id is None or frame_value is None:
        return {}

    bboxes: dict[str, list[tuple[int, int, int, int]]] = {}
    for prefix, key in (("overtaker", "overtaker_group_id"), ("overtaken", "overtaken_group_id")):
        try:
            group_value = int(event.get(key))
        except (TypeError, ValueError):
            continue
        candidates = fetch_tire_detections_for_group(run_id, frame_value, group_value)
        boxes: list[tuple[int, int, int, int]] = []
        for det in candidates:
            if not isinstance(det, Mapping):
                continue
            bbox = _bbox_from_mapping(det)
            if bbox:
                boxes.append(bbox)
        if boxes:
            bboxes[prefix] = boxes
    return bboxes


def _manual_scale_analysis(
    event: Mapping[str, Any],
    left_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
    center_line: Optional[Sequence[Sequence[object]]],
    left_inner_line: Optional[Sequence[Sequence[object]]] = None,
    right_inner_line: Optional[Sequence[Sequence[object]]] = None,
    *,
    lane_width_m: float = LANE_WIDTH_METERS,
    tire_bboxes: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    role_defs = (
        ("overtaker", "Overtaking"),
        ("overtaken", "Overtaken"),
    )
    role_details: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    seen_y: set[float] = set()

    for prefix, label in role_defs:
        detection = _manual_event_detection_from_prefix(event, prefix)
        lane_result = compute_lane_distance(
            detection,
            left_line,
            right_line,
            center_line,
            left_inner_line,
            right_inner_line,
            lane_width_m=lane_width_m,
        )
        lane_scale = lane_scale_details_at_y(
            lane_result.measure_y,
            left_line,
            right_line,
            center_line=center_line,
            left_inner_line=left_inner_line,
            right_inner_line=right_inner_line,
            lane_width_m=lane_width_m,
        )
        lane_scale_dict = lane_scale.to_dict()

        stored_px = _float_or_none(event.get(f"{prefix}_line_distance_px"))
        stored_m = _float_or_none(event.get(f"{prefix}_line_distance_m"))
        stored_cm = _float_or_none(event.get(f"{prefix}_line_distance_cm"))

        detail_entry: dict[str, Any] = {
            "role": prefix,
            "label": label,
            "measure_x": _float_or_none(lane_result.measure_x),
            "measure_y": _float_or_none(lane_result.measure_y),
            "distance_px": _float_or_none(lane_result.distance_px),
            "distance_m": _float_or_none(lane_result.distance_m),
            "distance_cm": _float_or_none(
                lane_result.distance_m * 100.0
                if lane_result.distance_m is not None
                else None
            ),
            "stored_distance_px": stored_px,
            "stored_distance_m": stored_m,
            "stored_distance_cm": stored_cm,
            "left_distance_px": _float_or_none(lane_result.left_distance_px),
            "left_distance_m": _float_or_none(lane_result.left_distance_m),
            "left_distance_cm": _float_or_none(
                lane_result.left_distance_m * 100.0
                if lane_result.left_distance_m is not None
                else None
            ),
            "right_distance_px": _float_or_none(lane_result.right_distance_px),
            "right_distance_m": _float_or_none(lane_result.right_distance_m),
            "right_distance_cm": _float_or_none(
                lane_result.right_distance_m * 100.0
                if lane_result.right_distance_m is not None
                else None
            ),
            "stored_left_distance_px": _float_or_none(
                event.get(f"{prefix}_left_line_distance_px")
            ),
            "stored_left_distance_cm": _float_or_none(
                event.get(f"{prefix}_left_line_distance_cm")
            ),
            "stored_right_distance_px": _float_or_none(
                event.get(f"{prefix}_right_line_distance_px")
            ),
            "stored_right_distance_cm": _float_or_none(
                event.get(f"{prefix}_right_line_distance_cm")
            ),
            "lane_scale": lane_scale_dict,
        }
        bbox = _bbox_from_mapping(detection)
        if bbox:
            detail_entry["bbox"] = bbox
        if tire_bboxes:
            boxes_for_role: list[tuple[int, int, int, int]] = []
            for det in tire_bboxes.get(prefix, ()):  # type: ignore[arg-type]
                if not isinstance(det, Mapping):
                    continue
                box = _bbox_from_mapping(det)
                if box:
                    boxes_for_role.append(box)
            if boxes_for_role:
                detail_entry["tire_bboxes"] = boxes_for_role
        role_details.append(detail_entry)

        if lane_scale.is_available and lane_scale.y is not None:
            key = round(lane_scale.y, 3)
            if key not in seen_y:
                seen_y.add(key)
                segments.append(
                    {
                        "y": lane_scale_dict.get("y"),
                        "lane_width_px": lane_scale_dict.get("lane_width_px"),
                        "pixels_per_meter": lane_scale_dict.get("pixels_per_meter"),
                        "centimeters_per_pixel": lane_scale_dict.get(
                            "centimeters_per_pixel"
                        ),
                        "left_point": lane_scale_dict.get("left_point"),
                        "right_point": lane_scale_dict.get("right_point"),
                    }
                )

    return role_details, segments


def _collect_manual_scale_preview(
    run_id: int,
    frame_num: int,
    overtaker_group_id: int,
    overtaken_group_id: int,
) -> tuple[Optional[dict[str, Any]], Optional[tuple[str, int]]]:
    """手動追い越しのスケール確認に必要な情報を取得する。"""

    actions_taken, notices, fatal = _prepare_manual_overtake_dependencies(run_id)
    combined_notices = list(notices)
    if fatal:
        message = combined_notices[-1] if combined_notices else "手動追い越しに必要な検出が不足しています。"
        return (
            {
                "actions": actions_taken,
                "notices": combined_notices,
            },
            (message, 400),
        )

    try:
        computation = _compute_manual_overtake_event_data(
            run_id,
            frame_num,
            overtaker_group_id,
            overtaken_group_id,
            context_window=0,
            compute_lane_metrics=True,
        )
    except ManualOvertakeComputationError as exc:
        combined_notices.append(str(exc))
        return (
            {
                "actions": actions_taken,
                "notices": combined_notices,
            },
            (str(exc), exc.status_code),
        )

    event_payload = dict(computation.payload)
    event_payload["run_id"] = run_id
    event_payload["frame_num"] = frame_num
    event_payload.setdefault("manual_event_id", None)

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    video_info = get_run_video_info(run_id, upload_folder)
    if not video_info:
        return (
            {
                "actions": actions_taken,
                "notices": combined_notices + computation.notices,
            },
            ("Run情報を取得できませんでした。", 404),
        )

    event_payload.setdefault("video_filename", video_info.get("filename"))

    calibration_profile = video_info.get("profile_name")
    calibration = load_calibration_payload(run_id, calibration_profile)
    lane_lines = load_white_lines(calibration)
    left_line, right_line, center_line = lane_lines
    left_inner_line = lane_lines.left_inner
    right_inner_line = lane_lines.right_inner

    measure_values = _collect_event_measurement_y_values(event_payload)
    if measure_values:
        center_y = sum(measure_values) / len(measure_values)
        half_span = LANE_CONFIRMATION_HALF_SPAN_PX or 15.0
        y_min = center_y - half_span
        y_max = center_y + half_span
        trimmed_lines = restrict_lane_lines_vertical(lane_lines, y_min, y_max)
        left_line = trimmed_lines.left
        right_line = trimmed_lines.right
        center_line = trimmed_lines.center
        left_inner_line = trimmed_lines.left_inner
        right_inner_line = trimmed_lines.right_inner

    preview_payload: dict[str, Any] = {
        "event": event_payload,
        "video_info": video_info,
        "left_line": left_line,
        "right_line": right_line,
        "calibration_profile": calibration_profile,
        "actions": actions_taken,
        "notices": combined_notices + computation.notices,
    }
    if center_line:
        preview_payload["center_line"] = center_line
    if left_inner_line:
        preview_payload["left_inner_line"] = left_inner_line
    if right_inner_line:
        preview_payload["right_inner_line"] = right_inner_line

    return preview_payload, None


def _format_distance_label(
    value_cm: Optional[float],
    value_m: Optional[float],
    value_px: Optional[float],
) -> str:
    if value_cm is not None:
        return f"{value_cm:.1f} cm"
    if value_m is not None:
        return f"{value_m:.2f} m"
    if value_px is not None:
        return f"{value_px:.0f} px"
    return "-"


def _draw_scale_overlay(
    frame: "np.ndarray",
    event: Mapping[str, Any],
    role_details: Sequence[Mapping[str, Any]],
    scale_segments: Sequence[Mapping[str, Any]],
    *,
    show_lane_distance: bool = False,
    show_clearance: bool = False,
) -> "np.ndarray":
    image = frame.copy()
    lane_width_m = _resolve_lane_width_m(event.get("lane_width_m"))

    def _draw_text(
        img: "np.ndarray",
        text: str,
        origin: tuple[int, int],
        color: tuple[int, int, int],
        *,
        font_scale: float = 0.6,
        thickness: int = 1,
    ) -> None:
        cv2.putText(
            img,
            text,
            origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (0, 0, 0),
            thickness + 2,
            cv2.LINE_AA,
        )
        cv2.putText(
            img,
            text,
            origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color,
            thickness,
            cv2.LINE_AA,
        )

    scale_colors = [(0, 255, 0), (0, 165, 255), (255, 0, 0)]
    for idx, segment in enumerate(scale_segments):
        left_point = _point_to_int_tuple(segment.get("left_point"))
        right_point = _point_to_int_tuple(segment.get("right_point"))
        if not left_point or not right_point:
            continue
        color = scale_colors[idx % len(scale_colors)]
        cv2.line(image, left_point, right_point, color, 2, cv2.LINE_AA)
        cv2.circle(image, left_point, 6, color, -1, cv2.LINE_AA)
        cv2.circle(image, right_point, 6, color, -1, cv2.LINE_AA)
        lane_width_px = segment.get("lane_width_px")
        if lane_width_px is not None:
            lane_width_px_val = float(lane_width_px)
            cm_per_px = _float_or_none(segment.get("centimeters_per_pixel"))
            lane_width_cm = lane_width_m * 100.0
            base_y = max(left_point[1], right_point[1]) + 20
            text_x = min(left_point[0], right_point[0])
            label_primary = (
                f"{lane_width_m:.1f}m = {lane_width_px_val:.1f}px ({lane_width_cm:.0f}cm)"
            )
            _draw_text(image, label_primary, (text_x, base_y), color)
            if cm_per_px is not None:
                label_secondary = f"Scale {cm_per_px:.2f} cm/px"
                _draw_text(image, label_secondary, (text_x, base_y + 20), color)

    marker_colors = {
        "overtaker": (0, 0, 255),
        "overtaken": (255, 0, 0),
    }
    measurement_points: dict[str, tuple[int, int]] = {}
    for detail in role_details:
        mx = _float_or_none(detail.get("measure_x"))
        my = _float_or_none(detail.get("measure_y"))
        role_name = detail.get("role") or ""
        if mx is None or my is None:
            continue
        point = (int(round(mx)), int(round(my)))
        measurement_points[role_name] = point
        color = marker_colors.get(role_name, (200, 200, 200))
        cv2.drawMarker(
            image,
            point,
            color,
            markerType=cv2.MARKER_CROSS,
            markerSize=16,
            thickness=2,
            line_type=cv2.LINE_AA,
        )
        label = detail.get("label") or role_name
        if label:
            _draw_text(
                image,
                str(label),
                (point[0] + 8, point[1] - 8),
                color,
                font_scale=0.5,
            )

        stored_distance_cm = _float_or_none(detail.get("stored_distance_cm"))
        computed_distance_cm = _float_or_none(detail.get("distance_cm"))
        distance_cm = stored_distance_cm or computed_distance_cm
        stored_distance_m = _float_or_none(detail.get("stored_distance_m"))
        computed_distance_m = _float_or_none(detail.get("distance_m"))
        distance_m = stored_distance_m or computed_distance_m
        stored_distance_px = _float_or_none(detail.get("stored_distance_px"))
        computed_distance_px = _float_or_none(detail.get("distance_px"))
        distance_px = stored_distance_px or computed_distance_px
        lane_scale = detail.get("lane_scale")
        lane_width_px = None
        cm_per_px = None
        if isinstance(lane_scale, Mapping):
            lane_width_px = _float_or_none(lane_scale.get("lane_width_px"))
            cm_per_px = _float_or_none(lane_scale.get("centimeters_per_pixel"))

        if show_lane_distance and lane_scale:
            left_point = _point_to_int_tuple(lane_scale.get("left_point"))
            right_point = _point_to_int_tuple(lane_scale.get("right_point"))
            left_distance_px = _float_or_none(detail.get("left_distance_px"))
            right_distance_px = _float_or_none(detail.get("right_distance_px"))
            target_point: Optional[tuple[int, int]] = None
            if left_point and right_point:
                if left_distance_px is not None and right_distance_px is not None:
                    target_point = left_point if left_distance_px <= right_distance_px else right_point
                elif left_distance_px is not None:
                    target_point = left_point
                elif right_distance_px is not None:
                    target_point = right_point
                else:
                    target_point = (
                        left_point
                        if abs(point[0] - left_point[0]) <= abs(point[0] - right_point[0])
                        else right_point
                    )
            else:
                target_point = left_point or right_point

            if target_point:
                cv2.line(image, point, target_point, color, 2, cv2.LINE_AA)
                label_text = _format_distance_label(distance_cm, distance_m, distance_px)
                if label_text != "-":
                    mid_x = int(round((point[0] + target_point[0]) / 2.0))
                    mid_y = int(round((point[1] + target_point[1]) / 2.0)) - 6
                    _draw_text(
                        image,
                        f"Lane distance {label_text}",
                        (mid_x, mid_y),
                        color,
                        font_scale=0.5,
                    )

        info_lines: list[str] = []
        if distance_cm is not None:
            info_lines.append(f"Lane distance {distance_cm:.1f}cm")
        if lane_width_px is not None:
            base_text = f"{lane_width_m:.1f}m = {lane_width_px:.1f}px"
            if cm_per_px is not None:
                base_text += f" ({cm_per_px:.2f}cm/px)"
            info_lines.append(base_text)

        for idx, text in enumerate(info_lines):
            offset_y = point[1] + 20 + idx * 20
            _draw_text(
                image,
                text,
                (point[0] + 10, offset_y),
                color,
                font_scale=0.5,
            )

        bbox = detail.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            cv2.rectangle(
                image,
                (int(bbox[0]), int(bbox[1])),
                (int(bbox[2]), int(bbox[3])),
                color,
                2,
                cv2.LINE_AA,
            )
            _draw_text(
                image,
                "Group bbox",
                (int(bbox[0]), int(bbox[1]) - 6),
                color,
                font_scale=0.45,
            )

        tire_boxes = detail.get("tire_bboxes")
        if isinstance(tire_boxes, Iterable):
            for tire_box in tire_boxes:
                if not (
                    isinstance(tire_box, (list, tuple))
                    and len(tire_box) == 4
                ):
                    continue
                cv2.rectangle(
                    image,
                    (int(tire_box[0]), int(tire_box[1])),
                    (int(tire_box[2]), int(tire_box[3])),
                    color,
                    1,
                    cv2.LINE_AA,
                )
                _draw_text(
                    image,
                    "Tire bbox",
                    (int(tire_box[0]), int(tire_box[1]) - 6),
                    color,
                    font_scale=0.45,
                )

    if show_clearance and {
        "overtaker",
        "overtaken",
    }.issubset(measurement_points.keys()):
        overtaker_point = measurement_points.get("overtaker")
        overtaken_point = measurement_points.get("overtaken")
        if overtaker_point and overtaken_point:
            clearance_color = (0, 215, 255)
            cv2.line(
                image,
                overtaker_point,
                overtaken_point,
                clearance_color,
                2,
                cv2.LINE_AA,
            )
            cv2.circle(image, overtaker_point, 5, clearance_color, -1, cv2.LINE_AA)
            cv2.circle(image, overtaken_point, 5, clearance_color, -1, cv2.LINE_AA)
            clearance_label = _format_distance_label(
                _float_or_none(event.get("clearance_distance_cm")),
                _float_or_none(event.get("clearance_distance_m")),
                _float_or_none(event.get("clearance_distance_px")),
            )
            if clearance_label != "-":
                mid_x = int(round((overtaker_point[0] + overtaken_point[0]) / 2.0))
                mid_y = int(round((overtaker_point[1] + overtaken_point[1]) / 2.0)) - 8
                _draw_text(
                    image,
                    f"Clearance {clearance_label}",
                    (mid_x, mid_y),
                    clearance_color,
                    font_scale=0.55,
                    thickness=2,
                )

    summary_lines: list[str] = []
    run_id = event.get("run_id")
    frame_num = event.get("frame_num")
    video_time = _float_or_none(event.get("video_time_s"))
    summary_lines.append(f"Run {run_id} / Frame {frame_num}")
    summary_lines.append(f"Lane width {lane_width_m:.1f} m")
    if video_time is not None:
        summary_lines.append(f"Timestamp {video_time:.2f}s")
    for detail in role_details:
        label = detail.get("label") or detail.get("role") or ""
        stored_distance_cm = _float_or_none(detail.get("stored_distance_cm"))
        computed_distance_cm = _float_or_none(detail.get("distance_cm"))
        distance_cm = stored_distance_cm or computed_distance_cm
        if distance_cm is not None and label:
            summary_lines.append(f"{label}: lane distance {distance_cm:.1f}cm")
    for segment in scale_segments:
        y_val = _float_or_none(segment.get("y"))
        lane_width_px = _float_or_none(segment.get("lane_width_px"))
        cm_per_px = _float_or_none(segment.get("centimeters_per_pixel"))
        if y_val is None or lane_width_px is None:
            continue
        text = f"Y={y_val:.1f}px: {lane_width_m:.1f}m={lane_width_px:.1f}px"
        if cm_per_px is not None:
            text += f" ({cm_per_px:.2f} cm/px)"
        summary_lines.append(text)

    x0, y0 = 12, 24
    for idx, line in enumerate(summary_lines):
        if not line:
            continue
        y = y0 + idx * 22
        _draw_text(image, line, (x0, y), (255, 255, 255))

    return image


def _prepare_manual_overtake_dependencies(run_id: int) -> tuple[list[str], list[str], bool]:
    """手動追い越しで必要となる派生データを可能な範囲で事前計算する。"""

    actions: list[str] = []
    warnings: list[str] = []
    allowed_classes = vehicle_allowed_classes()
    if allowed_classes:
        placeholders = ", ".join("?" for _ in allowed_classes)
        class_filter_sql = f" AND LOWER(c.class_name) IN ({placeholders})"
        class_params: tuple[str, ...] = tuple(allowed_classes)
    else:
        class_filter_sql = ""
        class_params = ()

    def _vehicle_counts() -> tuple[int, int]:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            cursor = conn.cursor()
            for model_filter in dbm._model_filter_attempts():
                cursor.execute(
                    f"""
                    SELECT COUNT(*),
                           SUM(CASE WHEN d.group_id IS NULL THEN 1 ELSE 0 END)
                    FROM Detection d
                    LEFT JOIN Class c ON d.class_id = c.class_id
                    WHERE d.run_id = ?
                      {model_filter}
                      {class_filter_sql}
                    """,
                    (run_id, *class_params),
                )
                row = cursor.fetchone()
                total = int(row[0]) if row and row[0] is not None else 0
                missing = int(row[1]) if row and row[1] is not None else 0
                if total > 0 or not model_filter:
                    return total, missing
        return 0, 0

    def _has_records(condition: str) -> bool:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            cursor = conn.cursor()
            for model_filter in dbm._model_filter_attempts():
                query = (
                    "SELECT 1 FROM Detection d "
                    "LEFT JOIN Class c ON d.class_id = c.class_id "
                    "WHERE d.run_id = ? "
                    f"{model_filter} "
                    f"{class_filter_sql} AND ({condition}) LIMIT 1"
                )
                cursor.execute(query, (run_id, *class_params))
                if cursor.fetchone() is not None:
                    return True
        return False

    total, missing = _vehicle_counts()
    if total == 0:
        warnings.append(
            f"Run ID {run_id}: 車両検出が存在しません。YOLO推論を確認してください。"
        )
        return actions, warnings, True

    if missing:
        try:
            assign_group_ids(run_id)
            actions.append("assign_group_ids")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"グループIDの再計算に失敗しました: {exc}")

    total_after, missing_after = _vehicle_counts()
    grouped = total_after - missing_after
    if grouped <= 0:
        warnings.append(
            f"Run ID {run_id}: group_id を付与できる検出が見つかりません。YOLO推論結果を確認してください。"
        )
        return actions, warnings, True

    needs_kinematics = not _has_records(
        "pixel_speed_frame IS NOT NULL AND travel_direction NOT IN ('', 'N')"
    )
    if needs_kinematics:
        try:
            assign_kinematics(run_id)
            actions.append("assign_kinematics")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"速度情報の計算に失敗しました: {exc}")

    needs_lane = not _has_records(
        "l_line_distance_m IS NOT NULL OR r_line_distance_m IS NOT NULL OR line_distance_m IS NOT NULL"
    )
    if needs_lane:
        try:
            assign_lane_distance(run_id)
            actions.append("assign_lane_distance")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"白線距離の計算に失敗しました: {exc}")

    needs_approach = not _has_records("approach_distance_px IS NOT NULL")
    if needs_approach:
        try:
            assign_approach_and_clearance(run_id)
            actions.append("assign_approach_and_clearance")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"接近距離の計算に失敗しました: {exc}")

    return actions, warnings, False


def _compute_manual_overtake_event_data(
    run_id: int,
    frame_num: int,
    overtaker_group_id: int,
    overtaken_group_id: int,
    *,
    notes: Optional[str] = None,
    context_window: Optional[int] = None,
    compute_lane_metrics: bool = False,
    lane_width_m: Optional[float] = None,
    group_presence_context: bool = False,
) -> ManualOvertakeComputation:
    detection_frame_num = convert_video_frame_to_detection_frame(run_id, frame_num)
    if detection_frame_num is None:
        raise ManualOvertakeComputationError(
            "指定されたフレームに検出が見つかりません。",
            status_code=404,
        )

    detections_frame = fetch_detections_for_frame(run_id, detection_frame_num)
    if not detections_frame:
        raise ManualOvertakeComputationError(
            "指定されたフレームに検出が見つかりません。",
            status_code=404,
        )

    overtaker_detection = fetch_detection_for_group(run_id, detection_frame_num, overtaker_group_id)
    overtaken_detection = fetch_detection_for_group(run_id, detection_frame_num, overtaken_group_id)

    if overtaker_detection is None:
        raise ManualOvertakeComputationError("追い越し側の検出が見つかりません。", status_code=404)
    if overtaken_detection is None:
        raise ManualOvertakeComputationError("追い越され側の検出が見つかりません。", status_code=404)

    overtaker_frame_value = overtaker_detection.get("frame_num")
    if overtaker_frame_value is not None:
        overtaker_detection["frame_num"] = convert_detection_frame_to_video_frame(
            run_id, overtaker_frame_value
        )
    else:
        overtaker_detection["frame_num"] = frame_num

    overtaken_frame_value = overtaken_detection.get("frame_num")
    if overtaken_frame_value is not None:
        overtaken_detection["frame_num"] = convert_detection_frame_to_video_frame(
            run_id, overtaken_frame_value
        )
    else:
        overtaken_detection["frame_num"] = frame_num

    approach_distance_m: Optional[float] = None
    approach_distance_px: Optional[float] = None
    clearance_distance_m: Optional[float] = None
    clearance_distance_cm: Optional[float] = None
    clearance_distance_px: Optional[float] = None

    if overtaker_detection.get("approach_partner_group_id") == overtaken_group_id:
        approach_distance_m = overtaker_detection.get("approach_distance_m")
        approach_distance_px = overtaker_detection.get("approach_distance_px")
        clearance_distance_m = overtaker_detection.get("clearance_distance_m")
        clearance_distance_cm = overtaker_detection.get("clearance_distance_cm")
        clearance_distance_px = overtaker_detection.get("clearance_distance_px")
    elif overtaken_detection.get("approach_partner_group_id") == overtaker_group_id:
        approach_distance_m = overtaken_detection.get("approach_distance_m")
        approach_distance_px = overtaken_detection.get("approach_distance_px")
        clearance_distance_m = overtaken_detection.get("clearance_distance_m")
        clearance_distance_cm = overtaken_detection.get("clearance_distance_cm")
        clearance_distance_px = overtaken_detection.get("clearance_distance_px")

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    run_info = get_run_video_info(run_id, upload_folder)
    if not run_info:
        raise ManualOvertakeComputationError("Run情報を取得できませんでした。", status_code=404)

    fps = run_info.get("fps")
    try:
        fps_value = float(fps) if fps else None
    except (TypeError, ValueError):
        fps_value = None
    video_time_s = frame_num / fps_value if fps_value else None

    calibration = load_calibration_payload(run_id, run_info.get("profile_name"))
    lane_lines = load_white_lines(calibration)
    left_line, right_line, center_line = lane_lines
    left_inner_line = lane_lines.left_inner
    right_inner_line = lane_lines.right_inner

    lane_width_m_value = _resolve_lane_width_m(lane_width_m)
    bicycle_aliases = {alias.lower() for alias in get_bicycle_class_aliases()}

    def normalize_int(value: object) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _is_bicycle_detection(det: Optional[Mapping[str, Any]]) -> bool:
        if not det:
            return False
        try:
            class_name = det.get("class_name")
        except AttributeError:
            class_name = None
        if not class_name:
            return False
        return str(class_name).lower() in bicycle_aliases

    def inject_tire_measurement(
        target_detection: Optional[dict[str, Any]],
        fallback_group: Optional[int],
        detection_frame_value: Optional[int],
    ) -> None:
        if target_detection is None:
            return
        frame_index = normalize_int(detection_frame_value)
        if frame_index is None:
            return

        group_value = normalize_int(target_detection.get("group_id"))
        if group_value is None:
            group_value = normalize_int(fallback_group)
        if group_value is None:
            return

        tyre_candidates = fetch_tire_detections_for_group(run_id, frame_index, group_value)
        candidates = tyre_candidates or [
            det
            for det in detections_frame
            if isinstance(det, Mapping) and det.get("group_id") == group_value
        ]

        def _group_mid_x(source: Mapping[str, Any]) -> Optional[float]:
            x1_val = _float_or_none(source.get("x1"))
            x2_val = _float_or_none(source.get("x2"))
            if None in (x1_val, x2_val):
                return None
            return (x1_val + x2_val) / 2.0

        def _is_plate(det: Mapping[str, Any]) -> bool:
            try:
                class_name = str(det.get("class_name") or "").lower()
            except AttributeError:
                return False
            return "plate" in class_name or "ナンバー" in class_name

        def _filter_right_half(
            detections: Sequence[Mapping[str, Any]], mid_x: Optional[float]
        ) -> list[Mapping[str, Any]]:
            if mid_x is None:
                return list(detections)
            filtered: list[Mapping[str, Any]] = []
            for det in detections:
                center_candidates = (
                    det.get("measure_x"),
                    det.get("manual_measure_x"),
                    det.get("x2"),
                    det.get("x1"),
                )
                center_values = [
                    _float_or_none(val)
                    for val in center_candidates
                    if _float_or_none(val) is not None
                ]
                if not center_values:
                    continue
                center_x = sum(center_values) / len(center_values)
                if center_x >= mid_x:
                    filtered.append(det)
            return filtered

        def _exclude_plate_detections(
            detections: Sequence[Mapping[str, Any]]
        ) -> list[Mapping[str, Any]]:
            return [det for det in detections if not _is_plate(det)]

        is_bicycle = _is_bicycle_detection(target_detection)
        bbox_source: Mapping[str, Any] = target_detection
        best_bbox = fetch_best_group_bbox(run_id, frame_index, group_value)
        if best_bbox:
            bbox_source = {**bbox_source, **best_bbox}

        def _select_plate_bbox(
            detections: Sequence[Mapping[str, Any]]
        ) -> Optional[tuple[float, float, float, float]]:
            plate_candidates: list[tuple[float, float, float, float, float]] = []
            for det in detections:
                try:
                    class_name = str(det.get("class_name") or "").lower()
                except AttributeError:
                    class_name = ""
                if "plate" not in class_name and "ナンバー" not in class_name:
                    continue

                x1 = _float_or_none(det.get("x1"))
                y1 = _float_or_none(det.get("y1"))
                x2 = _float_or_none(det.get("x2"))
                y2 = _float_or_none(det.get("y2"))
                if None in (x1, y1, x2, y2):
                    continue

                area = (x2 - x1) * (y2 - y1)
                if not math.isfinite(area) or area <= 0:
                    continue

                plate_candidates.append((area, x1, y1, x2, y2))

            if not plate_candidates:
                return None

            _, x1_val, y1_val, x2_val, y2_val = max(
                plate_candidates,
                key=lambda item: item[0],
            )
            return x1_val, y1_val, x2_val, y2_val

        mid_x = _group_mid_x(bbox_source)
        filtered_candidates = _exclude_plate_detections(candidates)
        plate_bbox = _select_plate_bbox(candidates)
        if plate_bbox is None:
            filtered_candidates = _filter_right_half(filtered_candidates, mid_x)

        if is_bicycle:
            measure_x, measure_y = select_bicycle_tire_measure_point(
                bbox_source,
                filtered_candidates,
                left_line,
                right_line,
            )
        else:
            measure_x, measure_y = select_measure_point_from_candidates(
                filtered_candidates,
                left_line,
                right_line,
            )

        fallback_x = _float_or_none(bbox_source.get("x2"))
        fallback_y = _float_or_none(bbox_source.get("y2"))

        if (
            plate_bbox
            and None not in (measure_x, fallback_x, fallback_y)
            and measure_x is not None
        ):
            plate_left = min(plate_bbox[0], plate_bbox[2])
            if measure_x < plate_left:
                measure_x = fallback_x
                measure_y = fallback_y
        elif plate_bbox is None and None in (measure_x, measure_y):
            measure_x = fallback_x
            measure_y = fallback_y
        if None in (measure_x, measure_y):
            return

        target_detection["measure_x"] = float(measure_x)
        target_detection["measure_y"] = float(measure_y)

    def collect_measurement_y(det: Optional[dict[str, Any]]) -> list[float]:
        values: list[float] = []
        if not det:
            return values
        for key in ("measure_y", "manual_measure_y", "y2"):
            try:
                raw_value = det.get(key)
            except AttributeError:
                raw_value = None
            if raw_value is None:
                continue
            try:
                numeric = float(raw_value)
            except (TypeError, ValueError):
                continue
            if math.isnan(numeric):
                continue
            values.append(numeric)
        return values

    inject_tire_measurement(overtaker_detection, overtaker_group_id, detection_frame_num)
    inject_tire_measurement(overtaken_detection, overtaken_group_id, detection_frame_num)

    def _resolve_context_window(value: Optional[int]) -> int:
        if value is None:
            override = current_app.config.get("MANUAL_CONTEXT_CAPTURE_WINDOW")
            if override is not None:
                try:
                    return max(0, int(override))
                except (TypeError, ValueError):
                    return MANUAL_CONTEXT_CAPTURE_WINDOW
            return MANUAL_CONTEXT_CAPTURE_WINDOW
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return MANUAL_CONTEXT_CAPTURE_WINDOW

    context_window_value = _resolve_context_window(context_window)
    context_mode = "group_presence" if group_presence_context else "window"

    def _collect_presence_offsets() -> list[int]:
        frames: set[int] = set()

        def _extend_frames(group_id: int) -> None:
            first_frame = get_first_detection_frame_for_group(run_id, group_id)
            if first_frame is None:
                return
            frames.add(first_frame)

            guard = 0
            current = first_frame
            while True:
                next_frame = get_next_detection_frame_for_group(
                    run_id, group_id, current
                )
                if next_frame is None or next_frame in frames:
                    break
                frames.add(next_frame)
                current = next_frame
                guard += 1
                if guard > 20000:
                    break

        _extend_frames(overtaker_group_id)
        _extend_frames(overtaken_group_id)

        if frame_num >= 0:
            frames.add(frame_num)

        ordered_frames = sorted(frames)
        return [candidate - frame_num for candidate in ordered_frames]

    measurement_band: list[float] = []
    measurement_band.extend(collect_measurement_y(overtaker_detection))
    measurement_band.extend(collect_measurement_y(overtaken_detection))

    if measurement_band:
        center_y = sum(measurement_band) / len(measurement_band)
        half_span = LANE_CONFIRMATION_HALF_SPAN_PX or 15.0
        y_min = center_y - half_span
        y_max = center_y + half_span
        trimmed_lines = restrict_lane_lines_vertical(lane_lines, y_min, y_max)
        left_line = trimmed_lines.left
        right_line = trimmed_lines.right
        center_line = trimmed_lines.center
        left_inner_line = trimmed_lines.left_inner
        right_inner_line = trimmed_lines.right_inner

    clearance_result = None
    overtaker_lane = None
    overtaken_lane = None

    if compute_lane_metrics:
        clearance_result = compute_clearance(
            overtaker_detection,
            overtaken_detection,
            left_line,
            right_line,
            center_line,
            left_inner_line,
            right_inner_line,
            lane_width_m=lane_width_m_value,
        )
        overtaker_lane = compute_lane_distance(
            overtaker_detection,
            left_line,
            right_line,
            center_line,
            left_inner_line,
            right_inner_line,
            lane_width_m=lane_width_m_value,
        )
        overtaken_lane = compute_lane_distance(
            overtaken_detection,
            left_line,
            right_line,
            center_line,
            left_inner_line,
            right_inner_line,
            lane_width_m=lane_width_m_value,
        )

    if clearance_result:
        if clearance_distance_m is None and clearance_result.distance_m is not None:
            clearance_distance_m = clearance_result.distance_m
        if clearance_distance_cm is None and clearance_result.distance_cm is not None:
            clearance_distance_cm = clearance_result.distance_cm
        if clearance_distance_px is None and clearance_result.distance_px is not None:
            clearance_distance_px = clearance_result.distance_px

    sanitized_notes = (notes or "").strip()
    if sanitized_notes and len(sanitized_notes) > 500:
        sanitized_notes = sanitized_notes[:500]

    def coerce_numeric(*values: Any) -> Optional[float]:
        for value in values:
            try:
                if value is None:
                    continue
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if math.isnan(numeric):
                continue
            return numeric
        return None

    def extract_numeric(det: Optional[dict[str, Any]], key: str) -> Optional[float]:
        if not det:
            return None
        try:
            raw_value = det.get(key)
        except AttributeError:
            return None
        return coerce_numeric(raw_value)

    def extract_int(det: Optional[dict[str, Any]], key: str) -> Optional[int]:
        if not det:
            return None
        try:
            raw_value = det.get(key)
        except AttributeError:
            return None
        try:
            if raw_value is None:
                return None
            numeric = int(raw_value)
        except (TypeError, ValueError):
            return None
        return numeric

    overtaker_track_id = extract_int(overtaker_detection, "track_id")
    overtaken_track_id = extract_int(overtaken_detection, "track_id")

    overtaker_line_distance_m = coerce_numeric(
        overtaker_lane.distance_m if overtaker_lane else None,
        overtaker_detection.get("line_distance_m"),
    )
    overtaker_line_distance_cm = coerce_numeric(
        overtaker_lane.distance_m * 100 if overtaker_lane and overtaker_lane.distance_m is not None else None,
        overtaker_detection.get("line_distance_cm"),
    )
    overtaker_line_distance_px = coerce_numeric(
        overtaker_lane.distance_px if overtaker_lane else None,
        overtaker_detection.get("line_distance"),
    )
    overtaker_left_line_distance_m = coerce_numeric(
        overtaker_lane.left_distance_m if overtaker_lane else None,
        overtaker_detection.get("l_line_distance_m"),
    )
    overtaker_left_line_distance_cm = coerce_numeric(
        overtaker_lane.left_distance_m * 100 if overtaker_lane and overtaker_lane.left_distance_m is not None else None,
        overtaker_detection.get("l_line_distance_cm"),
    )
    overtaker_left_line_distance_px = coerce_numeric(
        overtaker_lane.left_distance_px if overtaker_lane else None,
        overtaker_detection.get("l_line_distance"),
    )
    overtaker_right_line_distance_m = coerce_numeric(
        overtaker_lane.right_distance_m if overtaker_lane else None,
        overtaker_detection.get("r_line_distance_m"),
    )
    overtaker_right_line_distance_cm = coerce_numeric(
        overtaker_lane.right_distance_m * 100 if overtaker_lane and overtaker_lane.right_distance_m is not None else None,
        overtaker_detection.get("r_line_distance_cm"),
    )
    overtaker_right_line_distance_px = coerce_numeric(
        overtaker_lane.right_distance_px if overtaker_lane else None,
        overtaker_detection.get("r_line_distance"),
    )
    overtaker_measure_x = coerce_numeric(
        overtaker_lane.measure_x,
        overtaker_detection.get("measure_x"),
        overtaker_detection.get("manual_measure_x"),
        overtaker_detection.get("x2"),
    )
    overtaker_measure_y = coerce_numeric(
        overtaker_lane.measure_y,
        overtaker_detection.get("measure_y"),
        overtaker_detection.get("manual_measure_y"),
        overtaker_detection.get("y2"),
    )

    overtaken_line_distance_m = coerce_numeric(
        overtaken_lane.distance_m,
        overtaken_detection.get("line_distance_m"),
    )
    overtaken_line_distance_cm = coerce_numeric(
        overtaken_lane.distance_m * 100 if overtaken_lane.distance_m is not None else None,
        overtaken_detection.get("line_distance_cm"),
    )
    overtaken_line_distance_px = coerce_numeric(
        overtaken_lane.distance_px,
        overtaken_detection.get("line_distance"),
    )
    overtaken_left_line_distance_m = coerce_numeric(
        overtaken_lane.left_distance_m,
        overtaken_detection.get("l_line_distance_m"),
    )
    overtaken_left_line_distance_cm = coerce_numeric(
        overtaken_lane.left_distance_m * 100 if overtaken_lane.left_distance_m is not None else None,
        overtaken_detection.get("l_line_distance_cm"),
    )
    overtaken_left_line_distance_px = coerce_numeric(
        overtaken_lane.left_distance_px,
        overtaken_detection.get("l_line_distance"),
    )
    overtaken_right_line_distance_m = coerce_numeric(
        overtaken_lane.right_distance_m,
        overtaken_detection.get("r_line_distance_m"),
    )
    overtaken_right_line_distance_cm = coerce_numeric(
        overtaken_lane.right_distance_m * 100 if overtaken_lane.right_distance_m is not None else None,
        overtaken_detection.get("r_line_distance_cm"),
    )
    overtaken_right_line_distance_px = coerce_numeric(
        overtaken_lane.right_distance_px,
        overtaken_detection.get("r_line_distance"),
    )
    overtaken_measure_x = coerce_numeric(
        overtaken_lane.measure_x,
        overtaken_detection.get("measure_x"),
        overtaken_detection.get("manual_measure_x"),
        overtaken_detection.get("x2"),
    )
    overtaken_measure_y = coerce_numeric(
        overtaken_lane.measure_y,
        overtaken_detection.get("measure_y"),
        overtaken_detection.get("manual_measure_y"),
        overtaken_detection.get("y2"),
    )

    lane_scale_details_event = lane_scale_details_at_y(
        overtaker_measure_y,
        left_line,
        right_line,
        center_line=center_line,
        left_inner_line=left_inner_line,
        right_inner_line=right_inner_line,
        lane_width_m=lane_width_m_value,
    )

    lane_width_px_reference = coerce_numeric(
        getattr(lane_scale_details_event, "lane_width_px", None)
    )
    cm_per_px_reference = coerce_numeric(
        getattr(lane_scale_details_event, "centimeters_per_pixel", None)
    )

    def _combine_lane_width(
        left_px_value: Optional[float], right_px_value: Optional[float]
    ) -> Optional[float]:
        left_val = _to_positive_float(left_px_value)
        right_val = _to_positive_float(right_px_value)
        if left_val is None or right_val is None:
            return None
        return left_val + right_val

    if not lane_width_px_reference or lane_width_px_reference <= 0:
        lane_width_px_reference = _combine_lane_width(
            overtaker_left_line_distance_px, overtaker_right_line_distance_px
        )

    if not lane_width_px_reference or lane_width_px_reference <= 0:
        lane_width_px_reference = _combine_lane_width(
            overtaken_left_line_distance_px, overtaken_right_line_distance_px
        )

    if (not cm_per_px_reference or cm_per_px_reference <= 0) and lane_width_px_reference:
        cm_per_px_reference = (lane_width_m_value * 100.0) / lane_width_px_reference

    harmonized_distances = {
        "clearance": {
            "px": clearance_distance_px,
            "cm": clearance_distance_cm,
            "m": clearance_distance_m,
        },
        "overtaker": {
            "px": overtaker_line_distance_px,
            "cm": overtaker_line_distance_cm,
            "m": overtaker_line_distance_m,
            "is_inner": overtaker_lane.is_inner if overtaker_lane else True,
        },
        "overtaken": {
            "px": overtaken_line_distance_px,
            "cm": overtaken_line_distance_cm,
            "m": overtaken_line_distance_m,
            "is_inner": overtaken_lane.is_inner if overtaken_lane else True,
        },
    }

    cm_per_px_reference = _harmonize_manual_distance_units(
        harmonized_distances,
        lane_width_px=lane_width_px_reference,
        cm_per_px=cm_per_px_reference,
        lane_width_m=lane_width_m_value,
        overtaker_px=overtaker_line_distance_px,
    )

    clearance_distance_cm = harmonized_distances["clearance"].get("cm")
    clearance_distance_m = harmonized_distances["clearance"].get("m")
    overtaker_line_distance_cm = harmonized_distances["overtaker"].get("cm")
    overtaker_line_distance_m = harmonized_distances["overtaker"].get("m")
    overtaken_line_distance_cm = harmonized_distances["overtaken"].get("cm")
    overtaken_line_distance_m = harmonized_distances["overtaken"].get("m")

    def fetch_offset_detection(offset: int) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        frame_target = frame_num + offset
        if frame_target < 0:
            return None, None
        detection_target = convert_video_frame_to_detection_frame(run_id, frame_target)
        if detection_target is None:
            return None, None
        overtaker_ctx = fetch_detection_for_group(run_id, detection_target, overtaker_group_id)
        overtaken_ctx = fetch_detection_for_group(run_id, detection_target, overtaken_group_id)
        if overtaker_ctx is None and overtaker_track_id is not None:
            overtaker_ctx = fetch_detection_for_track(run_id, detection_target, overtaker_track_id)
        if overtaken_ctx is None and overtaken_track_id is not None:
            overtaken_ctx = fetch_detection_for_track(run_id, detection_target, overtaken_track_id)
        if overtaker_ctx is not None:
            inject_tire_measurement(overtaker_ctx, overtaker_group_id, detection_target)
            overtaker_ctx["frame_num"] = frame_target
        if overtaken_ctx is not None:
            inject_tire_measurement(overtaken_ctx, overtaken_group_id, detection_target)
            overtaken_ctx["frame_num"] = frame_target
        return overtaker_ctx, overtaken_ctx

    def build_context_entry(
        offset: int,
        overtaker_det_ctx: Optional[dict[str, Any]],
        overtaken_det_ctx: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        target_frame = frame_num + offset
        video_time = target_frame / fps_value if (fps_value and target_frame >= 0) else None
        lane_o = (
            compute_lane_distance(
                overtaker_det_ctx,
                left_line,
                right_line,
                center_line,
                left_inner_line,
                right_inner_line,
                lane_width_m=lane_width_m_value,
            )
            if compute_lane_metrics and overtaker_det_ctx
            else None
        )
        lane_u = (
            compute_lane_distance(
                overtaken_det_ctx,
                left_line,
                right_line,
                center_line,
                left_inner_line,
                right_inner_line,
                lane_width_m=lane_width_m_value,
            )
            if compute_lane_metrics and overtaken_det_ctx
            else None
        )
        clearance_ctx = (
            compute_clearance(
                overtaker_det_ctx,
                overtaken_det_ctx,
                left_line,
                right_line,
                center_line,
                left_inner_line,
                right_inner_line,
                lane_width_m=lane_width_m_value,
            )
            if compute_lane_metrics and overtaker_det_ctx and overtaken_det_ctx
            else None
        )

        overtaker_measure_x_ctx = coerce_numeric(
            lane_o.measure_x if lane_o else None,
            (overtaker_det_ctx or {}).get("measure_x"),
            (overtaker_det_ctx or {}).get("manual_measure_x"),
            (overtaker_det_ctx or {}).get("x2"),
        )
        overtaker_measure_y_ctx = coerce_numeric(
            lane_o.measure_y if lane_o else None,
            (overtaker_det_ctx or {}).get("measure_y"),
            (overtaker_det_ctx or {}).get("manual_measure_y"),
            (overtaker_det_ctx or {}).get("y2"),
        )
        overtaken_measure_x_ctx = coerce_numeric(
            lane_u.measure_x if lane_u else None,
            (overtaken_det_ctx or {}).get("measure_x"),
            (overtaken_det_ctx or {}).get("manual_measure_x"),
            (overtaken_det_ctx or {}).get("x2"),
        )
        overtaken_measure_y_ctx = coerce_numeric(
            lane_u.measure_y if lane_u else None,
            (overtaken_det_ctx or {}).get("measure_y"),
            (overtaken_det_ctx or {}).get("manual_measure_y"),
            (overtaken_det_ctx or {}).get("y2"),
        )

        overtaker_line_distance_m_ctx = coerce_numeric(
            lane_o.distance_m if lane_o else None,
            (overtaker_det_ctx or {}).get("line_distance_m"),
        )
        overtaker_line_distance_cm_ctx = coerce_numeric(
            (lane_o.distance_m * 100) if lane_o and lane_o.distance_m is not None else None,
            (overtaker_det_ctx or {}).get("line_distance_cm"),
        )
        overtaker_line_distance_px_ctx = coerce_numeric(
            lane_o.distance_px if lane_o else None,
            (overtaker_det_ctx or {}).get("line_distance"),
        )
        overtaken_line_distance_m_ctx = coerce_numeric(
            lane_u.distance_m if lane_u else None,
            (overtaken_det_ctx or {}).get("line_distance_m"),
        )
        overtaken_line_distance_cm_ctx = coerce_numeric(
            (lane_u.distance_m * 100) if lane_u and lane_u.distance_m is not None else None,
            (overtaken_det_ctx or {}).get("line_distance_cm"),
        )
        overtaken_line_distance_px_ctx = coerce_numeric(
            lane_u.distance_px if lane_u else None,
            (overtaken_det_ctx or {}).get("line_distance"),
        )

        overtaker_left_line_distance_m_ctx = coerce_numeric(
            lane_o.left_distance_m if lane_o else None,
            (overtaker_det_ctx or {}).get("l_line_distance_m"),
        )
        overtaker_left_line_distance_cm_ctx = coerce_numeric(
            (lane_o.left_distance_m * 100) if lane_o and lane_o.left_distance_m is not None else None,
            (overtaker_det_ctx or {}).get("l_line_distance_cm"),
        )
        overtaker_left_line_distance_px_ctx = coerce_numeric(
            lane_o.left_distance_px if lane_o else None,
            (overtaker_det_ctx or {}).get("l_line_distance"),
        )
        overtaker_right_line_distance_m_ctx = coerce_numeric(
            lane_o.right_distance_m if lane_o else None,
            (overtaker_det_ctx or {}).get("r_line_distance_m"),
        )
        overtaker_right_line_distance_cm_ctx = coerce_numeric(
            (lane_o.right_distance_m * 100) if lane_o and lane_o.right_distance_m is not None else None,
            (overtaker_det_ctx or {}).get("r_line_distance_cm"),
        )
        overtaker_right_line_distance_px_ctx = coerce_numeric(
            lane_o.right_distance_px if lane_o else None,
            (overtaker_det_ctx or {}).get("r_line_distance"),
        )

        overtaken_left_line_distance_m_ctx = coerce_numeric(
            lane_u.left_distance_m if lane_u else None,
            (overtaken_det_ctx or {}).get("l_line_distance_m"),
        )
        overtaken_left_line_distance_cm_ctx = coerce_numeric(
            (lane_u.left_distance_m * 100) if lane_u and lane_u.left_distance_m is not None else None,
            (overtaken_det_ctx or {}).get("l_line_distance_cm"),
        )
        overtaken_left_line_distance_px_ctx = coerce_numeric(
            lane_u.left_distance_px if lane_u else None,
            (overtaken_det_ctx or {}).get("l_line_distance"),
        )
        overtaken_right_line_distance_m_ctx = coerce_numeric(
            lane_u.right_distance_m if lane_u else None,
            (overtaken_det_ctx or {}).get("r_line_distance_m"),
        )
        overtaken_right_line_distance_cm_ctx = coerce_numeric(
            (lane_u.right_distance_m * 100) if lane_u and lane_u.right_distance_m is not None else None,
            (overtaken_det_ctx or {}).get("r_line_distance_cm"),
        )
        overtaken_right_line_distance_px_ctx = coerce_numeric(
            lane_u.right_distance_px if lane_u else None,
            (overtaken_det_ctx or {}).get("r_line_distance"),
        )

        clearance_distance_m_ctx = coerce_numeric(
            clearance_ctx.distance_m if clearance_ctx else None,
            (overtaker_det_ctx or {}).get("clearance_distance_m"),
            (overtaken_det_ctx or {}).get("clearance_distance_m"),
        )
        clearance_distance_cm_ctx = coerce_numeric(
            (clearance_ctx.distance_m * 100) if clearance_ctx and clearance_ctx.distance_m is not None else None,
            (overtaker_det_ctx or {}).get("clearance_distance_cm"),
            (overtaken_det_ctx or {}).get("clearance_distance_cm"),
        )
        clearance_distance_px_ctx = coerce_numeric(
            clearance_ctx.distance_px if clearance_ctx else None,
            (overtaker_det_ctx or {}).get("clearance_distance_px"),
            (overtaken_det_ctx or {}).get("clearance_distance_px"),
        )

        lane_scale_details_ctx = lane_scale_details_at_y(
            overtaker_measure_y_ctx,
            left_line,
            right_line,
            center_line=center_line,
            left_inner_line=left_inner_line,
            right_inner_line=right_inner_line,
            lane_width_m=lane_width_m_value,
        )

        lane_width_px_ctx = coerce_numeric(
            getattr(lane_scale_details_ctx, "lane_width_px", None)
        )
        cm_per_px_ctx = coerce_numeric(
            getattr(lane_scale_details_ctx, "centimeters_per_pixel", None)
        )

        if not lane_width_px_ctx or lane_width_px_ctx <= 0:
            lane_width_px_ctx = _combine_lane_width(
                overtaker_left_line_distance_px_ctx,
                overtaker_right_line_distance_px_ctx,
            )

        if not lane_width_px_ctx or lane_width_px_ctx <= 0:
            lane_width_px_ctx = _combine_lane_width(
                overtaken_left_line_distance_px_ctx,
                overtaken_right_line_distance_px_ctx,
            )

        if (not cm_per_px_ctx or cm_per_px_ctx <= 0) and lane_width_px_ctx:
            cm_per_px_ctx = (lane_width_m_value * 100.0) / lane_width_px_ctx

        harmonized_ctx = {
            "clearance": {
                "px": clearance_distance_px_ctx,
                "cm": clearance_distance_cm_ctx,
                "m": clearance_distance_m_ctx,
            },
            "overtaker": {
                "px": overtaker_line_distance_px_ctx,
                "cm": overtaker_line_distance_cm_ctx,
                "m": overtaker_line_distance_m_ctx,
                "is_inner": lane_o.is_inner if lane_o else True,
            },
            "overtaken": {
                "px": overtaken_line_distance_px_ctx,
                "cm": overtaken_line_distance_cm_ctx,
                "m": overtaken_line_distance_m_ctx,
                "is_inner": lane_u.is_inner if lane_u else True,
            },
        }

        cm_per_px_ctx = _harmonize_manual_distance_units(
            harmonized_ctx,
            lane_width_px=lane_width_px_ctx,
            cm_per_px=cm_per_px_ctx,
            overtaker_px=overtaker_line_distance_px_ctx,
        )

        clearance_distance_cm_ctx = harmonized_ctx["clearance"].get("cm")
        clearance_distance_m_ctx = harmonized_ctx["clearance"].get("m")
        overtaker_line_distance_cm_ctx = harmonized_ctx["overtaker"].get("cm")
        overtaker_line_distance_m_ctx = harmonized_ctx["overtaker"].get("m")
        overtaken_line_distance_cm_ctx = harmonized_ctx["overtaken"].get("cm")
        overtaken_line_distance_m_ctx = harmonized_ctx["overtaken"].get("m")

        result = {
            "offset_frames": offset,
            "frame_num": target_frame,
            "video_time_s": video_time,
            "context_mode": context_mode,
            "group_presence_context": bool(group_presence_context),
            "overtaker_group_id": overtaker_group_id,
            "overtaker_auto_id": (overtaker_det_ctx or {}).get("auto_id"),
            "overtaker_class_name": (overtaker_det_ctx or {}).get("class_name"),
            "overtaker_confidence": (overtaker_det_ctx or {}).get("confidence"),
            "overtaker_track_id": extract_int(overtaker_det_ctx, "track_id") or overtaker_track_id,
            "overtaker_x1": (overtaker_det_ctx or {}).get("x1"),
            "overtaker_y1": (overtaker_det_ctx or {}).get("y1"),
            "overtaker_x2": (overtaker_det_ctx or {}).get("x2"),
            "overtaker_y2": (overtaker_det_ctx or {}).get("y2"),
            "overtaker_measure_x": overtaker_measure_x_ctx,
            "overtaker_measure_y": overtaker_measure_y_ctx,
            "overtaker_speed_km_h": extract_numeric(overtaker_det_ctx, "speed_km_h"),
            "overtaker_pixel_speed": extract_numeric(overtaker_det_ctx, "pixel_speed"),
            "overtaker_pixel_speed_frame": extract_numeric(overtaker_det_ctx, "pixel_speed_frame"),
            "overtaker_travel_direction": (overtaker_det_ctx or {}).get("travel_direction"),
            "overtaker_line_distance_m": overtaker_line_distance_m_ctx,
            "overtaker_line_distance_cm": overtaker_line_distance_cm_ctx,
            "overtaker_line_distance_px": overtaker_line_distance_px_ctx,
            "overtaker_left_line_distance_m": overtaker_left_line_distance_m_ctx,
            "overtaker_left_line_distance_cm": overtaker_left_line_distance_cm_ctx,
            "overtaker_left_line_distance_px": overtaker_left_line_distance_px_ctx,
            "overtaker_right_line_distance_m": overtaker_right_line_distance_m_ctx,
            "overtaker_right_line_distance_cm": overtaker_right_line_distance_cm_ctx,
            "overtaker_right_line_distance_px": overtaker_right_line_distance_px_ctx,
            "overtaken_group_id": overtaken_group_id,
            "overtaken_auto_id": (overtaken_det_ctx or {}).get("auto_id"),
            "overtaken_class_name": (overtaken_det_ctx or {}).get("class_name"),
            "overtaken_confidence": (overtaken_det_ctx or {}).get("confidence"),
            "overtaken_track_id": extract_int(overtaken_det_ctx, "track_id") or overtaken_track_id,
            "overtaken_x1": (overtaken_det_ctx or {}).get("x1"),
            "overtaken_y1": (overtaken_det_ctx or {}).get("y1"),
            "overtaken_x2": (overtaken_det_ctx or {}).get("x2"),
            "overtaken_y2": (overtaken_det_ctx or {}).get("y2"),
            "overtaken_measure_x": overtaken_measure_x_ctx,
            "overtaken_measure_y": overtaken_measure_y_ctx,
            "overtaken_speed_km_h": extract_numeric(overtaken_det_ctx, "speed_km_h"),
            "overtaken_pixel_speed": extract_numeric(overtaken_det_ctx, "pixel_speed"),
            "overtaken_pixel_speed_frame": extract_numeric(overtaken_det_ctx, "pixel_speed_frame"),
            "overtaken_travel_direction": (overtaken_det_ctx or {}).get("travel_direction"),
            "overtaken_line_distance_m": overtaken_line_distance_m_ctx,
            "overtaken_line_distance_cm": overtaken_line_distance_cm_ctx,
            "overtaken_line_distance_px": overtaken_line_distance_px_ctx,
            "overtaken_left_line_distance_m": overtaken_left_line_distance_m_ctx,
            "overtaken_left_line_distance_cm": overtaken_left_line_distance_cm_ctx,
            "overtaken_left_line_distance_px": overtaken_left_line_distance_px_ctx,
            "overtaken_right_line_distance_m": overtaken_right_line_distance_m_ctx,
            "overtaken_right_line_distance_cm": overtaken_right_line_distance_cm_ctx,
            "overtaken_right_line_distance_px": overtaken_right_line_distance_px_ctx,
            "clearance_distance_m": clearance_distance_m_ctx,
            "clearance_distance_cm": clearance_distance_cm_ctx,
            "clearance_distance_px": clearance_distance_px_ctx,
            "lane_width_px_reference": lane_width_px_ctx,
            "lane_width_cm_per_px": cm_per_px_ctx,
        }

        _apply_manual_distance_ratios(result)
        return result

    if group_presence_context:
        offset_candidates = _collect_presence_offsets()
    else:
        offset_candidates = list(range(-context_window_value, context_window_value + 1))

    if not offset_candidates:
        offset_candidates = [0]

    context_frames: list[dict[str, Any]] = []
    for offset in offset_candidates:
        target_frame = frame_num + offset
        if target_frame < 0:
            continue
        over_ctx, under_ctx = fetch_offset_detection(offset)
        context_frames.append(build_context_entry(offset, over_ctx, under_ctx))

    local_notices: list[str] = []
    if not context_frames:
        local_notices.append("前後コンテキストを取得できませんでした。")

    event_payload = {
        "run_id": run_id,
        "frame_num": frame_num,
        "video_time_s": video_time_s,
        "lane_width_m": lane_width_m_value,
        "overtaker_group_id": overtaker_group_id,
        "overtaker_auto_id": overtaker_detection.get("auto_id"),
        "overtaker_class_name": overtaker_detection.get("class_name"),
        "overtaker_confidence": overtaker_detection.get("confidence"),
        "overtaker_track_id": overtaker_track_id,
        "overtaker_x1": overtaker_detection.get("x1"),
        "overtaker_y1": overtaker_detection.get("y1"),
        "overtaker_x2": overtaker_detection.get("x2"),
        "overtaker_y2": overtaker_detection.get("y2"),
        "overtaker_measure_x": overtaker_measure_x,
        "overtaker_measure_y": overtaker_measure_y,
        "overtaker_speed_km_h": overtaker_detection.get("speed_km_h"),
        "overtaker_pixel_speed": overtaker_detection.get("pixel_speed"),
        "overtaker_pixel_speed_frame": overtaker_detection.get("pixel_speed_frame"),
        "overtaker_travel_direction": overtaker_detection.get("travel_direction"),
        "overtaken_group_id": overtaken_group_id,
        "overtaken_auto_id": overtaken_detection.get("auto_id"),
        "overtaken_class_name": overtaken_detection.get("class_name"),
        "overtaken_confidence": overtaken_detection.get("confidence"),
        "overtaken_track_id": overtaken_track_id,
        "overtaken_x1": overtaken_detection.get("x1"),
        "overtaken_y1": overtaken_detection.get("y1"),
        "overtaken_x2": overtaken_detection.get("x2"),
        "overtaken_y2": overtaken_detection.get("y2"),
        "overtaken_measure_x": overtaken_measure_x,
        "overtaken_measure_y": overtaken_measure_y,
        "overtaken_speed_km_h": overtaken_detection.get("speed_km_h"),
        "overtaken_pixel_speed": overtaken_detection.get("pixel_speed"),
        "overtaken_pixel_speed_frame": overtaken_detection.get("pixel_speed_frame"),
        "overtaken_travel_direction": overtaken_detection.get("travel_direction"),
        "approach_distance_m": approach_distance_m,
        "approach_distance_px": approach_distance_px,
        "clearance_distance_m": clearance_distance_m,
        "clearance_distance_cm": clearance_distance_cm,
        "clearance_distance_px": clearance_distance_px,
        "lane_width_px_reference": lane_width_px_reference,
        "lane_width_cm_per_px": cm_per_px_reference,
        "overtaker_line_distance_m": overtaker_line_distance_m,
        "overtaker_line_distance_cm": overtaker_line_distance_cm,
        "overtaker_line_distance_px": overtaker_line_distance_px,
        "overtaker_left_line_distance_m": overtaker_left_line_distance_m,
        "overtaker_left_line_distance_cm": overtaker_left_line_distance_cm,
        "overtaker_left_line_distance_px": overtaker_left_line_distance_px,
        "overtaker_right_line_distance_m": overtaker_right_line_distance_m,
        "overtaker_right_line_distance_cm": overtaker_right_line_distance_cm,
        "overtaker_right_line_distance_px": overtaker_right_line_distance_px,
        "overtaken_line_distance_m": overtaken_line_distance_m,
        "overtaken_line_distance_cm": overtaken_line_distance_cm,
        "overtaken_line_distance_px": overtaken_line_distance_px,
        "overtaken_left_line_distance_m": overtaken_left_line_distance_m,
        "overtaken_left_line_distance_cm": overtaken_left_line_distance_cm,
        "overtaken_left_line_distance_px": overtaken_left_line_distance_px,
        "overtaken_right_line_distance_m": overtaken_right_line_distance_m,
        "overtaken_right_line_distance_cm": overtaken_right_line_distance_cm,
        "overtaken_right_line_distance_px": overtaken_right_line_distance_px,
        "notes": sanitized_notes or None,
    }

    _apply_manual_distance_ratios(event_payload)

    return ManualOvertakeComputation(
        payload=event_payload,
        context_frames=context_frames,
        detection_frame_num=detection_frame_num,
        notices=local_notices,
    )


@main.route("/manual_overtake")
def manual_overtake():
    run_options = list_detection_runs()
    selected_run_id = request.args.get("run_id", type=int)
    events: list[dict[str, Any]] = []
    if selected_run_id is not None:
        try:
            events = list_manual_overtake_events(run_id=selected_run_id, limit=500)
            _prepare_manual_events(events)
        except Exception as exc:  # pragma: no cover - runtime safeguard
            current_app.logger.exception("Failed to load manual overtake events")
            flash(f"手動追い越しイベントの取得に失敗しました: {exc}", "danger")
            events = []
    context_rows = _build_manual_context_rows(events)
    return render_template(
        "manual_overtake.html",
        run_options=run_options,
        selected_run_id=selected_run_id,
        events=events,
        context_rows=context_rows,
    )


@main.route("/manual_overtake/view")
def manual_overtake_view():
    raw_run_ids = request.args.getlist("run_id")
    selected_run_ids = _normalize_run_ids(raw_run_ids)

    limit_param = request.args.get("limit", type=int)
    if limit_param is None or limit_param <= 0:
        limit_value = 500
    else:
        limit_value = min(limit_param, 2000)

    try:
        events = list_manual_overtake_events(
            run_ids=selected_run_ids or None,
            limit=limit_value,
        )
        _prepare_manual_events(events)
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to load manual overtake table view")
        flash(f"手動追い越しイベントの取得に失敗しました: {exc}", "danger")
        events = []
    else:
        if selected_run_ids:
            for rid in selected_run_ids:
                try:
                    touch_manual_run_progress(rid, review=True)
                except Exception:
                    current_app.logger.exception(
                        "Failed to update manual run review timestamp"
                    )

    run_options = list_detection_runs()

    run_label_map: dict[int, str] = {}
    status_groups: dict[str, list[int]] = {
        "all": [],
        "annotated": [],
        "visited": [],
        "new": [],
    }
    for option in run_options:
        rid = option.get("run_id") if isinstance(option, dict) else getattr(option, "run_id", None)
        if rid is None:
            continue
        label = option.get("filename") if isinstance(option, dict) else getattr(option, "filename", "")
        run_label_map[int(rid)] = label or ""
        status = option.get("manual_status") if isinstance(option, dict) else getattr(option, "manual_status", None)
        normalized_status = (status or "new").lower()
        if normalized_status not in {"annotated", "visited", "new"}:
            normalized_status = "new"
        rid_int = int(rid)
        status_groups["all"].append(rid_int)
        status_groups.setdefault(normalized_status, []).append(rid_int)

    timeline_entries: list[dict[str, Any]] = []
    timeline_grouped: "OrderedDict[int, list[dict[str, Any]]]" = OrderedDict()
    timeline_summary: dict[int, dict[str, int]] = {}

    if selected_run_ids:
        try:
            timeline_entries = list_manual_overtake_timeline_entries(selected_run_ids)
        except Exception as exc:  # pragma: no cover - runtime safeguard
            current_app.logger.exception("Failed to load manual overtake timeline view")
            flash(f"追い越しタイムラインの取得に失敗しました: {exc}", "danger")
            timeline_entries = []
        else:
            for entry in timeline_entries:
                run_value = entry.get("run_id")
                try:
                    run_key = int(run_value)
                except (TypeError, ValueError):
                    continue
                if run_key not in timeline_grouped:
                    timeline_grouped[run_key] = []
                timeline_grouped[run_key].append(entry)

            for run_key, items in timeline_grouped.items():
                processed_count = sum(1 for item in items if item.get("last_processed_at"))
                timeline_summary[run_key] = {
                    "total": len(items),
                    "processed": processed_count,
                    "pending": len(items) - processed_count,
                }

    backlog_summary = count_manual_context_backlog(selected_run_ids or None)
    backlog_total = sum(backlog_summary.values())
    backlog_status_summary = summarize_manual_context_backlog_by_status(
        selected_run_ids or None
    )
    backlog_status_total = sum(int(value or 0) for value in backlog_status_summary.values())

    try:
        manual_event_total = count_manual_overtake_events()
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to count manual overtake events")
        manual_event_total = 0

    if selected_run_ids:
        try:
            manual_event_total_selected = count_manual_overtake_events(selected_run_ids)
        except Exception as exc:  # pragma: no cover - runtime safeguard
            current_app.logger.exception("Failed to count selected manual overtake events")
            manual_event_total_selected = 0
    else:
        manual_event_total_selected = manual_event_total

    context_rows = _build_manual_context_rows(events)
    group_rows = _build_manual_group_rows(
        context_rows, include_left=True, include_flags=True
    )

    snapshot_group_ids: set[int] = set()
    for event in events:
        for key in ("overtaker_group_id", "overtaken_group_id"):
            value = event.get(key) if isinstance(event, dict) else None
            try:
                if value is not None:
                    snapshot_group_ids.add(int(value))
            except (TypeError, ValueError):
                continue

    return render_template(
        "manual_overtake_view.html",
        run_options=run_options,
        selected_run_ids=selected_run_ids,
        selected_run_ids_set=set(selected_run_ids),
        events=events,
        event_rows=events,
        limit=limit_value,
        context_rows=context_rows,
        group_rows=group_rows,
        timeline_entries=timeline_entries,
        timeline_grouped=timeline_grouped,
        timeline_summary=timeline_summary,
        run_label_map=run_label_map,
        timeline_total=len(timeline_entries),
        status_groups=status_groups,
        context_backlog_summary=backlog_summary,
        context_backlog_total=backlog_total,
        context_backlog_status=backlog_status_summary,
        context_backlog_status_total=backlog_status_total,
        manual_event_total=manual_event_total,
        manual_event_total_selected=manual_event_total_selected,
        lane_width_default=LANE_WIDTH_METERS,
        snapshot_group_options=sorted(snapshot_group_ids),
    )


@main.route("/manual_overtake/export")
def manual_overtake_export():
    error_response = _ensure_database_ready()
    if error_response is not None:
        return error_response
    fmt = (request.args.get("format") or "csv").lower()
    scope = (request.args.get("scope") or "events").lower()
    valid_scopes = {"events", "context", "context_legacy", "context_fixed", "groups"}
    if scope not in valid_scopes:
        scope = "events"
    limit_value = request.args.get("limit", type=int)
    if limit_value is not None and limit_value <= 0:
        limit_value = None

    raw_run_ids = request.args.getlist("run_id")
    normalized_run_ids = _normalize_run_ids(raw_run_ids)
    if not normalized_run_ids:
        single_run_id = request.args.get("run_id", type=int)
        if single_run_id is not None:
            normalized_run_ids = [single_run_id]

    range_start = request.args.get("range_start", type=int)
    range_end = request.args.get("range_end", type=int)

    query_kwargs: dict[str, Any] = {}
    if normalized_run_ids:
        # 重複排除しつつ順序維持
        deduped = list(dict.fromkeys(normalized_run_ids))
        query_kwargs["run_ids"] = deduped
    elif range_start is not None or range_end is not None:
        if range_start is None:
            range_start = range_end
        if range_end is None:
            range_end = range_start
        if range_start is not None and range_end is not None:
            range_ids = get_run_ids_in_range(range_start, range_end)
        else:
            range_ids = []
        if not range_ids:
            flash("指定したRun範囲に一致する手動追い越しイベントがありません。", "warning")
            return redirect(request.referrer or url_for("main.manual_overtake"))
        query_kwargs["run_ids"] = range_ids

    try:
        # 最新の後処理結果がすぐに反映されるよう、キャッシュを迂回して取得する
        events = list_manual_overtake_events(
            limit=limit_value, use_cache=False, **query_kwargs
        )
        _prepare_manual_events(events)
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to export manual overtake events")
        flash(f"手動追い越しイベントの取得に失敗しました: {exc}", "danger")
        return redirect(request.referrer or url_for("main.manual_overtake"))

    if scope == "events" and not events:
        flash("手動追い越しイベントが登録されていないため、エクスポートできるデータがありません。", "warning")
        return redirect(request.referrer or url_for("main.manual_overtake"))

    context_rows = _build_manual_context_rows(events)

    export_rows: Optional[list[dict[str, Any]]] = None
    export_columns: Optional[list[tuple[str, str]]] = None
    export_prefix: Optional[str] = None
    float_formats: dict[str, str] = MANUAL_OVERTAKE_CONTEXT_FLOAT_FORMATS
    csv_formatter = _format_manual_context_for_csv
    lane_flag_text = False

    if scope == "context":
        export_rows = context_rows
        export_columns = MANUAL_OVERTAKE_CONTEXT_EXPORT_COLUMNS
        export_prefix = "manual_overtake_context"
    elif scope == "context_legacy":
        export_rows = _filter_context_rows_by_window(
            context_rows, MANUAL_LEGACY_CONTEXT_WINDOW
        )
        export_columns = MANUAL_OVERTAKE_CONTEXT_EXPORT_COLUMNS
        export_prefix = "manual_overtake_legacy150"
    elif scope == "context_fixed":
        export_rows = _build_manual_group_rows(
            context_rows, include_left=False, include_flags=True
        )
        export_columns = MANUAL_OVERTAKE_GROUP_FIXED_EXPORT_COLUMNS
        export_prefix = "manual_overtake_groups_fixed"
        float_formats = MANUAL_OVERTAKE_GROUP_FLOAT_FORMATS
        lane_flag_text = True
    elif scope == "groups":
        export_rows = _build_manual_group_rows(
            context_rows, include_left=True, include_flags=False
        )
        export_columns = MANUAL_OVERTAKE_GROUP_EXPORT_COLUMNS
        export_prefix = "manual_overtake_groups"
        float_formats = MANUAL_OVERTAKE_GROUP_FLOAT_FORMATS
        lane_flag_text = True

    if scope != "events" and (export_rows is None or not export_rows):
        message = "出力できるデータがありません。後処理を実行してから再度お試しください。"
        if scope == "context_legacy":
            message = "従来の±150fコンテキストが存在しないため、出力できるデータがありません。"
        flash(message, "warning")
        return redirect(request.referrer or url_for("main.manual_overtake"))

    if fmt == "csv":
        if scope != "events":
            filename = _manual_export_filename(export_prefix or "manual_overtake_context", "csv")
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow([header for _, header in export_columns or []])
            for entry in export_rows or []:
                writer.writerow(
                    [
                        csv_formatter(key, entry.get(key))
                        for key, _ in (export_columns or [])
                    ]
                )
            csv_bytes = io.BytesIO(buffer.getvalue().encode("utf-8-sig"))
            csv_bytes.seek(0)
            return send_file(
                csv_bytes,
                mimetype="text/csv",
                as_attachment=True,
                download_name=filename,
            )

        filename = _manual_export_filename("manual_overtake", "csv")
        base_name, _, _ = filename.partition(".csv")
        text_buffer = io.StringIO()
        writer = csv.writer(text_buffer)
        writer.writerow([header for _, header in MANUAL_OVERTAKE_EXPORT_COLUMNS])
        for event in events:
            row: list[str] = []
            for key, _ in MANUAL_OVERTAKE_EXPORT_COLUMNS:
                row.append(_format_manual_event_for_csv(key, event.get(key)))
            writer.writerow(row)
        main_csv_bytes = text_buffer.getvalue().encode("utf-8-sig")

        if context_rows:
            context_buffer = io.StringIO()
            context_writer = csv.writer(context_buffer)
            context_writer.writerow(
                [header for _, header in MANUAL_OVERTAKE_CONTEXT_EXPORT_COLUMNS]
            )
            for entry in context_rows:
                row = [
                    _format_manual_context_for_csv(key, entry.get(key))
                    for key, _ in MANUAL_OVERTAKE_CONTEXT_EXPORT_COLUMNS
                ]
                context_writer.writerow(row)
            archive_name = f"{base_name}.zip" if base_name else _manual_export_filename(
                "manual_overtake", "zip"
            )
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(filename, main_csv_bytes)
                context_filename = (
                    f"{base_name}_context.csv" if base_name else "manual_overtake_context.csv"
                )
                zf.writestr(
                    context_filename,
                    context_buffer.getvalue().encode("utf-8-sig"),
                )
            zip_buffer.seek(0)
            return send_file(
                zip_buffer,
                mimetype="application/zip",
                as_attachment=True,
                download_name=archive_name,
            )

        csv_bytes = io.BytesIO(main_csv_bytes)
        csv_bytes.seek(0)
        return send_file(
            csv_bytes,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename,
        )

    if fmt in {"xlsx", "excel"}:
        if scope != "events":
            try:
                import xlsxwriter  # type: ignore
            except ImportError:  # pragma: no cover - runtime safeguard
                flash("Excel出力に必要なライブラリが利用できません。", "danger")
                return redirect(request.referrer or url_for("main.manual_overtake"))

            filename = _manual_export_filename(export_prefix or "manual_overtake_context", "xlsx")
            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output, {"in_memory": True})
            worksheet = workbook.add_worksheet("ContextFrames")
            header_format = workbook.add_format({"bold": True, "bg_color": "#F2F2F2"})
            for col_idx, (_, header) in enumerate(export_columns or []):
                worksheet.write(0, col_idx, header, header_format)

            context_format_cache: dict[str, Any] = {}
            for key, fmt_code in float_formats.items():
                context_format_cache[key] = workbook.add_format({"num_format": fmt_code})

            lane_flag_map = {"+": "内側", "-": "外側"}

            for row_idx, entry in enumerate(export_rows or [], start=1):
                for col_idx, (key, _) in enumerate(export_columns or []):
                    value = entry.get(key)
                    if lane_flag_text and key == "lane_position_flag":
                        value = lane_flag_map.get(str(value), value)
                    if value is None or value == "":
                        worksheet.write_blank(row_idx, col_idx, None)
                        continue
                    fmt_obj = context_format_cache.get(key)
                    if key in float_formats:
                        try:
                            worksheet.write_number(row_idx, col_idx, float(value), fmt_obj)
                        except (TypeError, ValueError):
                            worksheet.write(row_idx, col_idx, value)
                    else:
                        worksheet.write(row_idx, col_idx, value)

            workbook.close()
            output.seek(0)
            return send_file(
                output,
                mimetype=(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
                as_attachment=True,
                download_name=filename,
            )

        try:
            import xlsxwriter  # type: ignore
        except ImportError:  # pragma: no cover - runtime safeguard
            flash("Excel出力に必要なライブラリが利用できません。", "danger")
            return redirect(request.referrer or url_for("main.manual_overtake"))

        filename = _manual_export_filename("manual_overtake", "xlsx")
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        worksheet = workbook.add_worksheet("ManualEvents")
        header_format = workbook.add_format({"bold": True, "bg_color": "#F2F2F2"})
        format_cache: dict[str, Any] = {}
        for key, fmt_code in MANUAL_OVERTAKE_FLOAT_FORMATS.items():
            format_cache[key] = workbook.add_format({"num_format": fmt_code})

        for col_idx, (_, header) in enumerate(MANUAL_OVERTAKE_EXPORT_COLUMNS):
            worksheet.write(0, col_idx, header, header_format)

        for row_idx, event in enumerate(events, start=1):
            for col_idx, (key, _) in enumerate(MANUAL_OVERTAKE_EXPORT_COLUMNS):
                value = event.get(key)
                if value is None or value == "":
                    worksheet.write_blank(row_idx, col_idx, None)
                    continue
                fmt_obj = format_cache.get(key)
                if key in MANUAL_OVERTAKE_FLOAT_FORMATS:
                    try:
                        worksheet.write_number(row_idx, col_idx, float(value), fmt_obj)
                    except (TypeError, ValueError):
                        worksheet.write(row_idx, col_idx, value)
                else:
                    worksheet.write(row_idx, col_idx, value)

        worksheet_ctx = workbook.add_worksheet("ContextFrames")
        for col_idx, (_, header) in enumerate(MANUAL_OVERTAKE_CONTEXT_EXPORT_COLUMNS):
            worksheet_ctx.write(0, col_idx, header, header_format)

        context_format_cache: dict[str, Any] = {}
        for key, fmt_code in MANUAL_OVERTAKE_CONTEXT_FLOAT_FORMATS.items():
            context_format_cache[key] = workbook.add_format({"num_format": fmt_code})

        for row_idx, entry in enumerate(context_rows, start=1):
            for col_idx, (key, _) in enumerate(MANUAL_OVERTAKE_CONTEXT_EXPORT_COLUMNS):
                value = entry.get(key)
                if value is None or value == "":
                    worksheet_ctx.write_blank(row_idx, col_idx, None)
                    continue
                fmt_obj = context_format_cache.get(key)
                if key in MANUAL_OVERTAKE_CONTEXT_FLOAT_FORMATS:
                    try:
                        worksheet_ctx.write_number(row_idx, col_idx, float(value), fmt_obj)
                    except (TypeError, ValueError):
                        worksheet_ctx.write(row_idx, col_idx, value)
                else:
                    worksheet_ctx.write(row_idx, col_idx, value)

        workbook.close()
        output.seek(0)
        return send_file(
            output,
            mimetype=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            as_attachment=True,
            download_name=filename,
        )

    flash("サポートされていない出力形式です。", "danger")
    return redirect(request.referrer or url_for("main.manual_overtake"))


@main.route("/api/manual_overtake/events/<int:manual_event_id>/scale_info")
def manual_overtake_scale_info(manual_event_id: int):
    event = fetch_manual_overtake_event(manual_event_id)
    if not event:
        return jsonify({"error": "Manual overtake event not found."}), 404

    _apply_manual_distance_ratios(event)

    run_id = event.get("run_id")
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    video_info = (
        get_run_video_info(run_id, upload_folder)
        if run_id is not None
        else None
    )

    calibration_profile = video_info.get("profile_name") if video_info else None
    calibration = (
        load_calibration_payload(run_id, calibration_profile)
        if run_id is not None
        else None
    )
    lane_lines = load_white_lines(calibration)
    left_line, right_line, center_line = lane_lines
    left_inner_line = lane_lines.left_inner
    right_inner_line = lane_lines.right_inner

    measure_values = _collect_event_measurement_y_values(event)
    if measure_values:
        center_y = sum(measure_values) / len(measure_values)
        half_span = LANE_CONFIRMATION_HALF_SPAN_PX or 15.0
        y_min = center_y - half_span
        y_max = center_y + half_span
        trimmed_lines = restrict_lane_lines_vertical(lane_lines, y_min, y_max)
        left_line = trimmed_lines.left
        right_line = trimmed_lines.right
        center_line = trimmed_lines.center
        left_inner_line = trimmed_lines.left_inner
        right_inner_line = trimmed_lines.right_inner

    lane_width_m = _resolve_lane_width_m(event.get("lane_width_m"))
    tire_bboxes = _collect_tire_bboxes(event)

    role_details, scale_segments = _manual_scale_analysis(
        event,
        left_line,
        right_line,
        center_line,
        left_inner_line,
        right_inner_line,
        lane_width_m=lane_width_m,
        tire_bboxes=tire_bboxes,
    )

    video_path = video_info.get("path") if video_info else None
    video_available = bool(video_path and os.path.exists(video_path))
    image_url = None
    if video_available and left_line and right_line:
        image_url = url_for(
            "main.manual_overtake_scale_image",
            manual_event_id=manual_event_id,
        )

    payload = {
        "event_id": manual_event_id,
        "run_id": event.get("run_id"),
        "frame_num": event.get("frame_num"),
        "video_filename": event.get("video_filename"),
        "lane_width_m": lane_width_m,
        "role_details": role_details,
        "scale_segments": scale_segments,
        "calibration_profile": calibration_profile,
        "video_available": video_available,
        "image_url": image_url,
        "left_line_available": bool(left_line),
        "right_line_available": bool(right_line),
    }
    if left_inner_line:
        payload["left_inner_available"] = True
    if right_inner_line:
        payload["right_inner_available"] = True
    return jsonify(payload)


@main.route("/api/manual_overtake/events/<int:manual_event_id>/snapshot_info")
def manual_overtake_snapshot_info(manual_event_id: int):
    event = fetch_manual_overtake_event(manual_event_id)
    if not event:
        return jsonify({"error": "Manual overtake event not found."}), 404

    _apply_manual_distance_ratios(event)

    run_id = event.get("run_id")
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    video_info = (
        get_run_video_info(run_id, upload_folder)
        if run_id is not None
        else None
    )

    calibration_profile = video_info.get("profile_name") if video_info else None
    calibration = (
        load_calibration_payload(run_id, calibration_profile)
        if run_id is not None
        else None
    )
    lane_lines = load_white_lines(calibration)
    left_line, right_line, center_line = lane_lines
    left_inner_line = lane_lines.left_inner
    right_inner_line = lane_lines.right_inner

    measure_values = _collect_event_measurement_y_values(event)
    if measure_values:
        center_y = sum(measure_values) / len(measure_values)
        half_span = LANE_CONFIRMATION_HALF_SPAN_PX or 15.0
        y_min = center_y - half_span
        y_max = center_y + half_span
        trimmed_lines = restrict_lane_lines_vertical(lane_lines, y_min, y_max)
        left_line = trimmed_lines.left
        right_line = trimmed_lines.right
        center_line = trimmed_lines.center
        left_inner_line = trimmed_lines.left_inner
        right_inner_line = trimmed_lines.right_inner

    lane_width_m = _resolve_lane_width_m(event.get("lane_width_m"))
    tire_bboxes = _collect_tire_bboxes(event)

    role_details, scale_segments = _manual_scale_analysis(
        event,
        left_line,
        right_line,
        center_line,
        left_inner_line,
        right_inner_line,
        lane_width_m=lane_width_m,
        tire_bboxes=tire_bboxes,
    )

    video_path = video_info.get("path") if video_info else None
    video_available = bool(video_path and os.path.exists(video_path))
    image_url = None
    if video_available and left_line and right_line:
        image_url = url_for(
            "main.manual_overtake_snapshot_image",
            manual_event_id=manual_event_id,
        )

    lane_distances: dict[str, Any] = {}
    for detail in role_details:
        role_key = detail.get("role") or ""
        if not role_key:
            continue
        stored_cm = _float_or_none(detail.get("stored_distance_cm"))
        stored_m = _float_or_none(detail.get("stored_distance_m"))
        stored_px = _float_or_none(detail.get("stored_distance_px"))
        computed_cm = _float_or_none(detail.get("distance_cm"))
        computed_m = _float_or_none(detail.get("distance_m"))
        computed_px = _float_or_none(detail.get("distance_px"))
        distance_cm = stored_cm or computed_cm
        distance_m = stored_m or computed_m
        distance_px = stored_px or computed_px

        lane_distances[role_key] = {
            "label": detail.get("label") or role_key,
            "distance_cm": distance_cm,
            "distance_m": distance_m,
            "distance_px": distance_px,
            "distance_label": _format_distance_label(
                distance_cm, distance_m, distance_px
            ),
        }

    clearance_cm = _float_or_none(event.get("clearance_distance_cm"))
    clearance_m = _float_or_none(event.get("clearance_distance_m"))
    clearance_px = _float_or_none(event.get("clearance_distance_px"))
    clearance_ratio = _float_or_none(event.get("clearance_distance_px_ratio"))

    payload: dict[str, Any] = {
        "event_id": manual_event_id,
        "run_id": event.get("run_id"),
        "frame_num": event.get("frame_num"),
        "video_filename": event.get("video_filename"),
        "lane_width_m": lane_width_m,
        "lane_distances": lane_distances,
        "calibration_profile": calibration_profile,
        "video_available": video_available,
        "image_url": image_url,
        "left_line_available": bool(left_line),
        "right_line_available": bool(right_line),
        "clearance": {
            "cm": clearance_cm,
            "m": clearance_m,
            "px": clearance_px,
            "ratio": clearance_ratio,
            "label": _format_distance_label(
                clearance_cm, clearance_m, clearance_px
            ),
        },
        "scale_segments": scale_segments,
    }
    if left_inner_line:
        payload["left_inner_available"] = True
    if right_inner_line:
        payload["right_inner_available"] = True
    return jsonify(payload)


@main.route("/manual_overtake/events/<int:manual_event_id>/scale_image")
def manual_overtake_scale_image(manual_event_id: int):
    event = fetch_manual_overtake_event(manual_event_id)
    if not event:
        return Response(status=404)

    _apply_manual_distance_ratios(event)

    run_id = event.get("run_id")
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    video_info = (
        get_run_video_info(run_id, upload_folder)
        if run_id is not None
        else None
    )
    if not video_info:
        return Response(status=404)

    video_path = video_info.get("path")
    if not video_path or not os.path.exists(video_path):
        return Response(status=404)

    calibration = load_calibration_payload(run_id, video_info.get("profile_name"))
    lane_lines = load_white_lines(calibration)
    left_line, right_line, center_line = lane_lines
    left_inner_line = lane_lines.left_inner
    right_inner_line = lane_lines.right_inner

    measure_values = _collect_event_measurement_y_values(event)
    if measure_values:
        center_y = sum(measure_values) / len(measure_values)
        half_span = LANE_CONFIRMATION_HALF_SPAN_PX or 15.0
        y_min = center_y - half_span
        y_max = center_y + half_span
        trimmed_lines = restrict_lane_lines_vertical(lane_lines, y_min, y_max)
        left_line = trimmed_lines.left
        right_line = trimmed_lines.right
        center_line = trimmed_lines.center
        left_inner_line = trimmed_lines.left_inner
        right_inner_line = trimmed_lines.right_inner
    if not left_line or not right_line:
        return Response(status=404)

    frame_idx = event.get("frame_num")
    try:
        frame_number = int(frame_idx) if frame_idx is not None else 0
    except (TypeError, ValueError):
        frame_number = 0

    requested_width = request.args.get("width", type=int)
    frame = load_video_frame(video_path, frame_number, requested_width)
    if frame is None:
        return Response(status=404)

    lane_width_m = _resolve_lane_width_m(event.get("lane_width_m"))
    tire_bboxes = _collect_tire_bboxes(event)

    role_details, scale_segments = _manual_scale_analysis(
        event,
        left_line,
        right_line,
        center_line,
        left_inner_line,
        right_inner_line,
        lane_width_m=lane_width_m,
        tire_bboxes=tire_bboxes,
    )
    annotated = _draw_scale_overlay(frame, event, role_details, scale_segments)

    ok, buffer = cv2.imencode(
        ".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
    )
    if not ok:
        return Response(status=500)

    resp = Response(buffer.tobytes(), mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@main.route("/manual_overtake/events/<int:manual_event_id>/snapshot_image")
def manual_overtake_snapshot_image(manual_event_id: int):
    event = fetch_manual_overtake_event(manual_event_id)
    if not event:
        return Response(status=404)

    _apply_manual_distance_ratios(event)

    run_id = event.get("run_id")
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    video_info = (
        get_run_video_info(run_id, upload_folder)
        if run_id is not None
        else None
    )
    if not video_info:
        return Response(status=404)

    video_path = video_info.get("path")
    if not video_path or not os.path.exists(video_path):
        return Response(status=404)

    calibration = load_calibration_payload(run_id, video_info.get("profile_name"))
    lane_lines = load_white_lines(calibration)
    left_line, right_line, center_line = lane_lines
    left_inner_line = lane_lines.left_inner
    right_inner_line = lane_lines.right_inner

    measure_values = _collect_event_measurement_y_values(event)
    if measure_values:
        center_y = sum(measure_values) / len(measure_values)
        half_span = LANE_CONFIRMATION_HALF_SPAN_PX or 15.0
        y_min = center_y - half_span
        y_max = center_y + half_span
        trimmed_lines = restrict_lane_lines_vertical(lane_lines, y_min, y_max)
        left_line = trimmed_lines.left
        right_line = trimmed_lines.right
        center_line = trimmed_lines.center
        left_inner_line = trimmed_lines.left_inner
        right_inner_line = trimmed_lines.right_inner
    if not left_line or not right_line:
        return Response(status=404)

    frame_idx = event.get("frame_num")
    try:
        frame_number = int(frame_idx) if frame_idx is not None else 0
    except (TypeError, ValueError):
        frame_number = 0

    requested_width = request.args.get("width", type=int)
    frame = load_video_frame(video_path, frame_number, requested_width)
    if frame is None:
        return Response(status=404)

    lane_width_m = _resolve_lane_width_m(event.get("lane_width_m"))
    tire_bboxes = _collect_tire_bboxes(event)

    role_details, scale_segments = _manual_scale_analysis(
        event,
        left_line,
        right_line,
        center_line,
        left_inner_line,
        right_inner_line,
        lane_width_m=lane_width_m,
        tire_bboxes=tire_bboxes,
    )
    annotated = _draw_scale_overlay(
        frame,
        event,
        role_details,
        scale_segments,
        show_lane_distance=True,
        show_clearance=True,
    )

    ok, buffer = cv2.imencode(
        ".jpg",
        annotated,
        [int(cv2.IMWRITE_JPEG_QUALITY), 85],
    )
    if not ok:
        return Response(status=500)

    resp = Response(buffer.tobytes(), mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@main.route("/api/manual_overtake/<int:run_id>/scale_preview")
def manual_overtake_scale_preview(run_id: int):
    frame_num = request.args.get("frame", type=int)
    overtaker_group_id = request.args.get("overtaker_group_id", type=int)
    overtaken_group_id = request.args.get("overtaken_group_id", type=int)

    if frame_num is None or overtaker_group_id is None or overtaken_group_id is None:
        return jsonify({"error": "Please provide frame number and both group IDs."}), 400

    preview_data, error_info = _collect_manual_scale_preview(
        run_id,
        frame_num,
        overtaker_group_id,
        overtaken_group_id,
    )

    if error_info is not None:
        message, status_code = error_info
        payload: dict[str, Any] = {"error": message}
        if preview_data and preview_data.get("notices"):
            payload["notices"] = preview_data["notices"]
        if preview_data and preview_data.get("actions"):
            payload["actions"] = preview_data["actions"]
        return jsonify(payload), status_code

    assert preview_data is not None  # for type checkers
    event = preview_data["event"]
    left_line = preview_data.get("left_line")
    right_line = preview_data.get("right_line")
    center_line = preview_data.get("center_line")
    left_inner_line = preview_data.get("left_inner_line")
    right_inner_line = preview_data.get("right_inner_line")
    lane_width_m = _resolve_lane_width_m(event.get("lane_width_m"))
    tire_bboxes = _collect_tire_bboxes(event)

    role_details, scale_segments = _manual_scale_analysis(
        event,
        left_line,
        right_line,
        center_line,
        left_inner_line,
        right_inner_line,
        lane_width_m=lane_width_m,
        tire_bboxes=tire_bboxes,
    )

    video_info = preview_data.get("video_info") or {}
    video_path = video_info.get("path") if isinstance(video_info, Mapping) else None
    video_available = bool(video_path and os.path.exists(video_path))

    image_url = None
    if video_available and left_line and right_line:
        image_url = url_for(
            "main.manual_overtake_scale_preview_image",
            run_id=run_id,
            frame=frame_num,
            overtaker_group_id=overtaker_group_id,
            overtaken_group_id=overtaken_group_id,
        )

    response_payload: dict[str, Any] = {
        "run_id": run_id,
        "frame_num": event.get("frame_num"),
        "video_filename": event.get("video_filename"),
        "lane_width_m": lane_width_m,
        "role_details": role_details,
        "scale_segments": scale_segments,
        "calibration_profile": preview_data.get("calibration_profile"),
        "video_available": video_available,
        "image_url": image_url,
        "left_line_available": bool(left_line),
        "right_line_available": bool(right_line),
        "event": event,
    }
    if left_inner_line:
        response_payload["left_inner_available"] = True
    if right_inner_line:
        response_payload["right_inner_available"] = True

    if preview_data.get("actions"):
        response_payload["actions"] = preview_data["actions"]
    if preview_data.get("notices"):
        response_payload["notices"] = preview_data["notices"]

    return jsonify(response_payload)


@main.route("/manual_overtake/<int:run_id>/scale_preview_image")
def manual_overtake_scale_preview_image(run_id: int):
    frame_num = request.args.get("frame", type=int)
    overtaker_group_id = request.args.get("overtaker_group_id", type=int)
    overtaken_group_id = request.args.get("overtaken_group_id", type=int)

    if frame_num is None or overtaker_group_id is None or overtaken_group_id is None:
        return Response(status=400)

    preview_data, error_info = _collect_manual_scale_preview(
        run_id,
        frame_num,
        overtaker_group_id,
        overtaken_group_id,
    )

    if error_info is not None:
        _, status_code = error_info
        return Response(status=status_code)

    assert preview_data is not None
    event = preview_data["event"]

    video_info = preview_data.get("video_info") or {}
    video_path = video_info.get("path") if isinstance(video_info, Mapping) else None
    if not video_path or not os.path.exists(video_path):
        return Response(status=404)

    left_line = preview_data.get("left_line")
    right_line = preview_data.get("right_line")
    center_line = preview_data.get("center_line")
    left_inner_line = preview_data.get("left_inner_line")
    right_inner_line = preview_data.get("right_inner_line")
    if not left_line or not right_line:
        return Response(status=404)

    requested_width = request.args.get("width", type=int)
    frame_number = event.get("frame_num")
    try:
        frame_value = int(frame_number) if frame_number is not None else frame_num
    except (TypeError, ValueError):
        frame_value = frame_num

    frame = load_video_frame(video_path, frame_value, requested_width)
    if frame is None:
        return Response(status=404)

    lane_width_m = _resolve_lane_width_m(event.get("lane_width_m"))
    tire_bboxes = _collect_tire_bboxes(event)

    role_details, scale_segments = _manual_scale_analysis(
        event,
        left_line,
        right_line,
        center_line,
        left_inner_line,
        right_inner_line,
        lane_width_m=lane_width_m,
        tire_bboxes=tire_bboxes,
    )
    annotated = _draw_scale_overlay(frame, event, role_details, scale_segments)

    ok, buffer = cv2.imencode(
        ".jpg",
        annotated,
        [int(cv2.IMWRITE_JPEG_QUALITY), 85],
    )
    if not ok:
        return Response(status=500)

    resp = Response(buffer.tobytes(), mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


# @main.route("/api/manual_overtake/<int:run_id>/metadata")
def legacy_manual_overtake_metadata(run_id: int):
    upload_folder = current_app.config['UPLOAD_FOLDER']
    info = get_run_video_info(run_id, upload_folder)
    if not info:
        return jsonify({"error": "対象のRunが見つかりません。"}), 404
    video_path = info.get('path')
    if not video_path or not os.path.exists(video_path):
        return jsonify({"error": "動画ファイルが見つかりません。"}), 404
    try:
        stats = probe_video(video_path)
    except FileNotFoundError:
        return jsonify({"error": "動画ファイルが見つかりません。"}), 404
    except Exception:
        return jsonify({"error": "動画を読み込めませんでした。"}), 500

    manual_frame_buffer.prepare_video(
        run_id,
        video_path,
        stats.get('frame_count'),
        stats.get('width'),
        stats.get('height'),
        start_prefetch=False,
    )

    try:
        touch_manual_run_progress(run_id, visit=True)
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to update manual run visit timestamp")

    calibration = load_calibration_payload(run_id, info.get('profile_name'))
    lane_lines = load_white_lines(calibration)
    left_line, right_line, center_line = lane_lines
    left_inner_line = lane_lines.left_inner
    right_inner_line = lane_lines.right_inner

    detection_offset = get_detection_frame_offset(run_id)
    first_detection_frame = get_first_detection_frame(run_id)
    first_bicycle_frame = get_first_bicycle_detection_frame(run_id)
    bicycle_orientation_counts = get_bicycle_orientation_counts(run_id)
    bicycle_aliases = sorted(get_bicycle_class_aliases())
    buffer_status = manual_frame_buffer.get_status(run_id) or {}

    return jsonify({
        "run_id": run_id,
        "video_filename": info.get('filename'),
        "frame_count": stats.get('frame_count'),
        "width": stats.get('width'),
        "height": stats.get('height'),
        "fps": info.get('fps'),
        "left_white_line": left_line,
        "right_white_line": right_line,
        "left_inner_line": left_inner_line,
        "right_inner_line": right_inner_line,
        "detection_frame_offset": detection_offset,
        "first_detection_frame": first_detection_frame,
        "first_bicycle_frame": first_bicycle_frame,
        "bicycle_orientation_counts": bicycle_orientation_counts,
        "bicycle_class_aliases": bicycle_aliases,
        "buffer_status": buffer_status,
    })


@main.route("/api/manual_overtake/<int:run_id>/prefetch", methods=["GET", "POST"])
def manual_overtake_prefetch(run_id: int):
    upload_folder = current_app.config['UPLOAD_FOLDER']
    info = get_run_video_info(run_id, upload_folder)
    if not info:
        return jsonify({"error": "対象のRunが見つかりません。"}), 404

    video_path = info.get('path')
    if not video_path or not os.path.exists(video_path):
        return jsonify({"error": "動画ファイルが見つかりません。"}), 404

    try:
        stats = probe_video(video_path)
    except FileNotFoundError:
        return jsonify({"error": "動画ファイルが見つかりません。"}), 404
    except Exception:
        current_app.logger.exception("Failed to open video for manual prefetch")
        return jsonify({"error": "動画を読み込めませんでした。"}), 500

    manual_frame_buffer.prepare_video(
        run_id,
        video_path,
        stats.get('frame_count'),
        stats.get('width'),
        stats.get('height'),
        restart=request.method == "POST",
        start_prefetch=request.method == "POST",
    )

    status = manual_frame_buffer.get_status(run_id) or {}
    status.update(
        {
            "run_id": run_id,
            "frame_count": stats.get('frame_count'),
            "width": stats.get('width'),
            "height": stats.get('height'),
        }
    )

    if request.method == "POST":
        return jsonify({"status": "started", "buffer_status": status})

    return jsonify(status)


@main.route("/api/manual_overtake/<int:run_id>/frame")
def manual_overtake_frame(run_id: int):
    upload_folder = current_app.config['UPLOAD_FOLDER']
    info = get_run_video_info(run_id, upload_folder)
    if not info:
        return Response(status=404)
    video_path = info.get('path')
    if not video_path or not os.path.exists(video_path):
        return Response(status=404)

    frame_idx = request.args.get('frame', default=0, type=int)
    requested_width = request.args.get('width', type=int)
    frame_bytes = manual_frame_buffer.get_frame(
        run_id,
        video_path,
        frame_idx,
        requested_width,
    )
    if frame_bytes is None:
        return Response(status=404)
    response = Response(frame_bytes, mimetype='image/jpeg')
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response


@main.route("/api/manual_overtake/<int:run_id>/detections")
def manual_overtake_detections(run_id: int):
    frame_num = request.args.get('frame', type=int)
    if frame_num is None or frame_num < 0:
        return jsonify({"error": "frameパラメータを正しく指定してください。"}), 400
    detection_frame = convert_video_frame_to_detection_frame(run_id, frame_num)
    if detection_frame is None:
        detections: list[dict[str, Any]] = []
    else:
        detections = fetch_detections_for_frame(run_id, detection_frame)

    def _maybe_attach_tire_measurement() -> None:
        if not detections:
            return

        upload_folder = current_app.config.get("UPLOAD_FOLDER")
        run_info = get_run_video_info(run_id, upload_folder)
        calibration = load_calibration_payload(run_id, run_info.get("profile_name") if run_info else None)
        lane_lines = load_white_lines(calibration)
        left_line, right_line, _ = lane_lines
        bicycle_aliases = {alias.lower() for alias in get_bicycle_class_aliases()}

        def _normalize_group(value: object) -> Optional[int]:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        def _is_bicycle(det: Mapping[str, Any]) -> bool:
            class_name = det.get("class_name") if isinstance(det, Mapping) else None
            return isinstance(class_name, str) and class_name.lower() in bicycle_aliases

        def _is_plate(det: Mapping[str, Any]) -> bool:
            try:
                class_name = str(det.get("class_name") or "").lower()
            except AttributeError:
                return False
            return "plate" in class_name or "ナンバー" in class_name

        for det in detections:
            if not isinstance(det, dict):
                continue
            group_value = _normalize_group(det.get("group_id"))
            if group_value is None:
                continue

            candidates = [
                det for det in fetch_tire_detections_for_group(run_id, detection_frame, group_value)
                if not _is_plate(det)
            ]
            bbox_source: Mapping[str, Any] = det

            if _is_bicycle(det):
                best_bbox = fetch_best_group_bbox(run_id, detection_frame, group_value)
                if best_bbox:
                    bbox_source = {**bbox_source, **best_bbox}
                measure_x, measure_y = select_bicycle_tire_measure_point(
                    bbox_source,
                    candidates,
                    left_line,
                    right_line,
                )
            else:
                measure_x, measure_y = select_measure_point_from_candidates(
                    candidates,
                    left_line,
                    right_line,
                )

            if None in (measure_x, measure_y):
                continue

            det["tire_measure_x"] = float(measure_x)
            det["tire_measure_y"] = float(measure_y)

    try:
        _maybe_attach_tire_measurement()
    except Exception:
        current_app.logger.exception("Failed to attach tire measure points for manual overtake detections")

    offset = get_detection_frame_offset(run_id)
    if detections and offset:
        for det in detections:
            stored_frame = det.get('frame_num')
            det['frame_num'] = convert_detection_frame_to_video_frame(run_id, stored_frame)
    return jsonify(
        {
            "detections": detections,
            "frame_num": frame_num,
            "detection_frame": detection_frame,
            "detection_frame_offset": offset,
        }
    )


@main.route("/api/manual_overtake/<int:run_id>/group_seek")
def manual_overtake_group_seek(run_id: int):
    group_id = request.args.get('group_id', type=int)
    if group_id is None:
        return jsonify({"error": "group_idパラメータを指定してください。"}), 400

    current_frame = request.args.get('frame', type=int)

    first_frame = get_first_detection_frame_for_group(run_id, group_id)
    if first_frame is None:
        return jsonify({"error": "指定グループの検出が見つかりません。"}), 404

    next_frame = get_next_detection_frame_for_group(run_id, group_id, current_frame)

    return jsonify(
        {
            "run_id": run_id,
            "group_id": group_id,
            "requested_frame": current_frame,
            "first_frame": first_frame,
            "next_frame": next_frame,
            "has_next": next_frame is not None,
        }
    )


def _await_manual_overtake_event(
    event_id: int,
    *,
    timeout: float = 1.0,
    interval: float = 0.1,
) -> Optional[dict[str, Any]]:
    """指定した手動追い越しイベントがDBで確認できるまで待機する。"""

    deadline = time.monotonic() + max(timeout, 0.0)
    wait_interval = max(interval, 0.01)

    while True:
        event = fetch_manual_overtake_event(event_id, vehicle_only=False)
        if event:
            return event
        event = fetch_manual_overtake_event(
            event_id,
            vehicle_only=False,
            use_cache=False,
            refresh_cache=True,
        )
        if event:
            return event
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(wait_interval, remaining))


@main.route("/api/manual_overtake/<int:run_id>/events/verify", methods=["GET"])
def manual_overtake_event_verify(run_id: int):
    event_id = request.args.get("event_id", type=int)
    if event_id is None:
        return jsonify({"error": "イベントIDを指定してください。"}), 400
    if event_id <= 0:
        return jsonify({"error": "イベントIDが不正です。"}), 400

    try:
        event = _await_manual_overtake_event(event_id)
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to verify manual overtake event")
        return jsonify({"error": f"イベントの確認に失敗しました: {exc}"}), 500

    if not event:
        return (
            jsonify(
                {
                    "verified": False,
                    "error": "イベントの保存を1秒以内に確認できませんでした。",
                }
            ),
            404,
        )

    event_run_id_raw = event.get("run_id")
    if event_run_id_raw is not None:
        try:
            event_run_id = int(event_run_id_raw)
        except (TypeError, ValueError):
            event_run_id = None
    else:
        event_run_id = None

    if event_run_id is not None and event_run_id != run_id:
        return jsonify({
            "verified": False,
            "error": "指定したRunに一致するイベントではありません。",
        }), 404

    _apply_manual_distance_ratios(event)

    return jsonify({
        "verified": True,
        "event": event,
        "message": "イベントの保存を確認しました。",
    })


@main.route("/api/manual_overtake/db_link_check", methods=["GET"])
def manual_overtake_db_link_check():
    """手動追い越しテーブルとDBの連携状況を確認し、登録済みデータを返す。"""

    raw_run_ids = request.args.getlist("run_id")
    normalized_run_ids: list[int] = []
    for raw in raw_run_ids:
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            normalized_run_ids.append(value)

    requested_limit = request.args.get("limit", type=int)
    if requested_limit is None or requested_limit <= 0:
        requested_limit = 5
    sample_limit = min(max(requested_limit, 1), 20)

    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            ensure_manual_annotation_schema(conn)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ManualOvertakeEvents'"
            )
            table_exists = cursor.fetchone() is not None
            if not table_exists:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "linked": False,
                            "error": "ManualOvertakeEventsテーブルが見つかりません。",
                        }
                    ),
                    404,
                )

            total_count = 0
            run_summaries: list[dict[str, Any]] = []

            if normalized_run_ids:
                for run_id in normalized_run_ids:
                    cursor.execute(
                        "SELECT COUNT(*) AS count FROM ManualOvertakeEvents WHERE run_id = ?",
                        (run_id,),
                    )
                    row = cursor.fetchone()
                    event_count = int(row["count"]) if row and row["count"] is not None else 0
                    total_count += event_count
                    cursor.execute(
                        """
                        SELECT manual_event_id,
                               run_id,
                               frame_num,
                               overtaker_group_id,
                               overtaken_group_id,
                               created_at
                        FROM ManualOvertakeEvents
                        WHERE run_id = ?
                        ORDER BY created_at DESC, manual_event_id DESC
                        LIMIT ?
                        """,
                        (run_id, sample_limit),
                    )
                    sample_rows = cursor.fetchall()
                    samples = [
                        {
                            "manual_event_id": sample["manual_event_id"],
                            "run_id": sample["run_id"],
                            "frame_num": sample["frame_num"],
                            "overtaker_group_id": sample["overtaker_group_id"],
                            "overtaken_group_id": sample["overtaken_group_id"],
                            "created_at": sample["created_at"],
                        }
                        for sample in sample_rows
                    ]
                    run_summaries.append(
                        {
                            "run_id": run_id,
                            "event_count": event_count,
                            "samples": samples,
                        }
                    )
            else:
                cursor.execute("SELECT COUNT(*) AS count FROM ManualOvertakeEvents")
                total_row = cursor.fetchone()
                total_count = (
                    int(total_row["count"])
                    if total_row and total_row["count"] is not None
                    else 0
                )

                cursor.execute(
                    """
                    SELECT run_id, COUNT(*) AS count
                    FROM ManualOvertakeEvents
                    GROUP BY run_id
                    ORDER BY run_id ASC
                    """
                )
                summary_rows = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT manual_event_id,
                           run_id,
                           frame_num,
                           overtaker_group_id,
                           overtaken_group_id,
                           created_at
                    FROM ManualOvertakeEvents
                    ORDER BY created_at DESC, manual_event_id DESC
                    LIMIT ?
                    """,
                    (sample_limit,),
                )
                sample_rows = cursor.fetchall()
                sample_map: dict[int, list[dict[str, Any]]] = {}
                for sample in sample_rows:
                    run_id = sample["run_id"]
                    sample_map.setdefault(run_id, []).append(
                        {
                            "manual_event_id": sample["manual_event_id"],
                            "run_id": run_id,
                            "frame_num": sample["frame_num"],
                            "overtaker_group_id": sample["overtaker_group_id"],
                            "overtaken_group_id": sample["overtaken_group_id"],
                            "created_at": sample["created_at"],
                        }
                    )

                for row in summary_rows:
                    rid = row["run_id"]
                    count_value = int(row["count"]) if row and row["count"] is not None else 0
                    run_summaries.append(
                        {
                            "run_id": rid,
                            "event_count": count_value,
                            "samples": sample_map.get(rid, []),
                        }
                    )

        if normalized_run_ids:
            if total_count > 0:
                message = "選択したRunの手動追い越しテーブルとの連携を確認しました。"
            else:
                message = "選択Runには登録済みの手動追い越しイベントが見つかりませんでした。"
        else:
            if total_count > 0:
                message = "手動追い越しテーブルとの連携を確認しました。"
            else:
                message = "手動追い越しテーブルは存在しますが、登録済みイベントはありません。"

        return jsonify(
            {
                "ok": True,
                "linked": True,
                "total_events": total_count,
                "run_summaries": run_summaries,
                "message": message,
            }
        )
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to verify manual overtake DB link")
        return (
            jsonify(
                {
                    "ok": False,
                    "linked": False,
                    "error": f"DB連携確認に失敗しました: {exc}",
                }
            ),
            500,
        )


@main.route("/api/manual_overtake/<int:run_id>/events/status", methods=["GET"])
def manual_overtake_events_status(run_id: int):
    try:
        summary = summarize_manual_overtake_events(run_id)
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to summarize manual overtake events")
        return jsonify({"error": str(exc)}), 500

    latest_event = summary.get("latest_event")
    if isinstance(latest_event, dict):
        _prepare_manual_events([latest_event])

    return jsonify(summary)


def manual_overtake_calibration_recreate(
    run_id: int, *, payload: Optional[Mapping[str, Any]] = None
):
    """手動追い越し用にキャリブレーションを複製し、Runへ適用する。"""

    body = payload or request.get_json(silent=True) or {}
    profile_raw = body.get("profile_name") if isinstance(body, Mapping) else None
    profile_candidate = sanitize_profile_name(profile_raw or "")
    upload_folder = current_app.config.get("UPLOAD_FOLDER")
    run_info = get_run_video_info(run_id, upload_folder)
    if not run_info:
        return jsonify({"error": "対象のRunが見つかりません。"}), 404

    base_profile = sanitize_profile_name(run_info.get("profile_name") or "")
    calibration_payload = load_calibration_payload(run_id, base_profile) or {}

    if not profile_candidate:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        profile_candidate = sanitize_profile_name(f"manual_run_{run_id}_{timestamp}")

    calib_dir = ensure_calibration_dir()
    try:
        save_calibration_payload(profile_candidate, run_id, calibration_payload, calib_dir)
        update_run_calibration_profile(run_id, profile_candidate)
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to create manual calibration profile")
        return jsonify({"error": f"キャリブレーション保存に失敗しました: {exc}"}), 500

    enqueued = 0
    try:
        enqueued, _ = ensure_manual_context_backlog_for_runs(
            [run_id], force_requeue=True
        )
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to requeue manual contexts after calibration")

    return jsonify(
        {
            "run_id": run_id,
            "profile_name": profile_candidate,
            "calibration_url": url_for(
                "main.calibration_page", run_id=run_id, profile_name=profile_candidate
            ),
            "enqueued": enqueued,
            "message": "新しいキャリブレーションを作成し、手動追い越しの再処理を予約しました。",
        }
    )


@main.route("/api/manual_overtake/<int:run_id>/events", methods=["GET", "POST"])
def manual_overtake_events_api(run_id: int):
    if request.method == "GET":
        limit = request.args.get('limit', type=int)
        try:
            events = list_manual_overtake_events(run_id=run_id, limit=limit)
            _prepare_manual_events(events)
        except Exception as exc:  # pragma: no cover - runtime safeguard
            current_app.logger.exception("Failed to fetch manual overtake events")
            return jsonify({"error": str(exc)}), 500
        return jsonify({"events": events})

    if request.args.get("calibration") == "recreate":
        payload = request.get_json(silent=True) or {}
        return manual_overtake_calibration_recreate(run_id, payload=payload)

    payload = request.get_json(silent=True) or {}
    frame_num_raw = payload.get('frame_num') if 'frame_num' in payload else payload.get('frame')
    overtaker_group_raw = payload.get('overtaker_group_id') if 'overtaker_group_id' in payload else payload.get('overtaker')
    overtaken_group_raw = payload.get('overtaken_group_id') if 'overtaken_group_id' in payload else payload.get('overtaken')
    notes_raw = payload.get('notes')
    lane_width_raw = payload.get('lane_width_m')

    try:
        frame_num = int(frame_num_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "フレーム番号が不正です。"}), 400
    try:
        overtaker_group_id = int(overtaker_group_raw)
        overtaken_group_id = int(overtaken_group_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "Group ID が不正です。"}), 400

    if frame_num < 0:
        return jsonify({"error": "フレーム番号は0以上にしてください。"}), 400
    if overtaker_group_id == overtaken_group_id:
        return jsonify({"error": "追い越し側と追い越され側は別のグループを選択してください。"}), 400

    notices: list[str] = []

    sanitized_notes = (notes_raw or "").strip()
    if sanitized_notes and len(sanitized_notes) > 500:
        sanitized_notes = sanitized_notes[:500]

    event_payload = {
        "run_id": run_id,
        "frame_num": frame_num,
        "overtaker_group_id": overtaker_group_id,
        "overtaken_group_id": overtaken_group_id,
        "notes": sanitized_notes or None,
    }

    try:
        lane_width_value = float(lane_width_raw)
    except (TypeError, ValueError):
        lane_width_value = None
    if lane_width_value is not None and lane_width_value > 0:
        event_payload["lane_width_m"] = lane_width_value

    try:
        event_id = insert_manual_overtake_event(event_payload)
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to insert manual overtake event")
        return jsonify({"error": f"保存に失敗しました: {exc}"}), 500

    database_verified = False
    saved_event: dict[str, Any] | None = None
    try:
        saved_event = fetch_manual_overtake_event_core(event_id)
        if saved_event:
            database_verified = True
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to verify manual overtake event in DB")
        notices.append(f"保存確認に失敗しました: {exc}")

    if not saved_event:
        saved_event = {
            "manual_event_id": event_id,
            "run_id": run_id,
            "frame_num": frame_num,
            "overtaker_group_id": overtaker_group_id,
            "overtaken_group_id": overtaken_group_id,
            "notes": event_payload.get("notes"),
        }

    context_saved = False
    context_notices: list[str] = []
    context_enqueued = False
    try:
        enqueue_manual_context_backlog(
            event_id,
            run_id,
            frame_num,
            event_payload,
            [],
        )
        context_enqueued = True
        context_notices.append(
            "追い越しフレームを後処理キューに登録しました。手動追い越し観覧で後処理を実行してください。"
        )
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to enqueue manual context backlog")
        context_notices.append(f"追い越しフレームの後処理キュー登録に失敗しました: {exc}")

    notices.extend(context_notices)

    try:
        record_manual_overtake_timeline_entry(
            run_id,
            frame_num,
            overtaker_group_id,
            overtaken_group_id,
            notes=event_payload.get("notes"),
            last_event_id=None,
        )
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to record manual overtake timeline entry")
        notices.append(f"タイムラインの更新に失敗しました: {exc}")

    response_payload: dict[str, object] = {
        "event_id": event_id,
        "event": saved_event,
        "database_verified": database_verified,
        "context_saved": context_saved,
        "context_queued": context_enqueued,
    }

    remaining_notices = [msg for msg in notices if msg]
    if remaining_notices:
        response_payload["notices"] = remaining_notices

    return jsonify(response_payload), 201


@main.route("/api/manual_overtake/<int:run_id>/context/flush", methods=["POST"])
def manual_overtake_context_flush(run_id: int):
    ensure_notices: list[str] = []
    enqueued = 0
    enqueued_ids: list[int] = []
    try:
        enqueued, enqueued_ids = ensure_manual_context_backlog_for_runs(
            [run_id], force_requeue=True
        )
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to enqueue manual context backlog before flush")
        ensure_notices.append(f"追い越しフレーム後処理対象の確認に失敗しました: {exc}")
    else:
        if enqueued:
            ensure_notices.append(
                f"追い越しフレーム後処理キューに {enqueued} 件を追加しました。"
            )

    try:
        processed, notices, remaining = _process_manual_context_backlog(
            [run_id], group_presence_context=True
        )
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to flush manual context backlog")
        return jsonify({"error": f"追い越しフレーム後処理に失敗しました: {exc}"}), 500

    payload: dict[str, Any] = {
        "processed": processed,
        "remaining": remaining.get(run_id, 0),
        "enqueued": enqueued,
    }
    if enqueued_ids:
        payload["enqueued_event_ids"] = enqueued_ids
    if notices:
        ensure_notices.extend(notices)

@main.route("/calibration_check")
def calibration_check_view():
    """キャリブレーション設定確認ページを表示する。"""
    return render_template("calibration_check.html", title="Calibration Verification")


@main.route("/api/calibration_check/folders")
def calibration_check_folders_api():
    """登録されているフォルダ一覧と、そのキャリブレーション設定状況、および利用可能なプロファイル一覧を返す。"""
    # 1. Available Profiles
    calib_dir = ensure_calibration_dir()
    profiles = []
    if os.path.exists(calib_dir):
        profiles = sorted([
            f.replace(".json", "") 
            for f in os.listdir(calib_dir) 
            if f.endswith(".json") and not f.startswith("calibration_") and not f.startswith("calib_")
        ])

    # 2. Folder List
    batches = dbm.list_folder_batches()
    folder_list = []
    for b in batches:
        folder_path = b.get("folder_path")
        if not folder_path or not os.path.exists(folder_path):
            continue
            
        settings = load_folder_settings(folder_path)
        current_profile = settings.get("profile", "")
        
        folder_list.append({
            "alias": b.get("folder_alias"),
            "path": folder_path,
            "profile": current_profile
        })
    
    folder_list.sort(key=lambda x: x["alias"] or "")
    
    # 3. Known Folders from DB (for suggestions)
    known_folders = sorted(list(dbm.get_all_video_folders()))

    return jsonify({
        "folders": folder_list,
        "profiles": profiles,
        "known_folders": known_folders
    })


@main.route("/api/calibration_check/update_folder", methods=["POST"])
def calibration_check_update_folder_api():
    """指定フォルダのキャリブレーション設定を更新（上書き）する。"""
    payload = request.get_json(silent=True) or {}
    folder_path = payload.get("folder_path")
    new_profile = payload.get("profile")

    if not folder_path or not os.path.isdir(folder_path):
        return jsonify({"error": "有効なフォルダパスが指定されていません。"}), 400
    
    # Check if profile exists (allow empty to clear)
    if new_profile:
        calib_dir = ensure_calibration_dir()
        profile_path = os.path.join(calib_dir, f"{new_profile}.json")
        if not os.path.exists(profile_path):
             return jsonify({"error": f"指定されたプロファイル '{new_profile}' は存在しません。"}), 404

    try:
        settings = load_folder_settings(folder_path)
        settings["profile"] = new_profile or ""
        save_folder_settings(folder_path, settings)
        return jsonify({"ok": True, "message": "設定を保存しました。"})
    except Exception as e:
        current_app.logger.exception("Failed to update folder settings")
        return jsonify({"error": f"設定の保存に失敗しました: {e}"}), 500


@main.route("/api/calibration_check/folder_info", methods=["POST"])
def calibration_check_folder_info_api():
    """指定されたパスのフォルダ情報（存在確認・プロファイル設定）を返す。"""
    payload = request.get_json(silent=True) or {}
    folder_path = payload.get("folder_path")

    if not folder_path:
        return jsonify({"error": "フォルダパスが指定されていません。"}), 400
    
    # Remove quotes if user copied as path
    folder_path = folder_path.strip('"').strip("'")
    
    if not os.path.isdir(folder_path):
         return jsonify({"error": "指定されたパスはフォルダではありません。"}), 404

    settings = load_folder_settings(folder_path)
    current_profile = settings.get("profile", "")
    
    # Attempt to find alias if possible (reverse lookup in batches)
    alias = ""
    batches = dbm.list_folder_batches()
    for b in batches:
        if os.path.abspath(b.get("folder_path")) == os.path.abspath(folder_path):
            alias = b.get("folder_alias")
            break
            
    return jsonify({
        "path": folder_path,
        "alias": alias or os.path.basename(folder_path),
        "profile": current_profile
    })


@main.route("/api/calibration_check/verify", methods=["POST"])
def calibration_check_verify_api():
    """指定フォルダのサンプル動画を取得し、キャリブレーションラインを返却する。"""
    payload = request.get_json(silent=True) or {}
    folder_path = payload.get("folder_path")
    profile_name = payload.get("profile")

    if not folder_path or not os.path.isdir(folder_path):
        return jsonify({"error": "有効なフォルダパスが指定されていません。"}), 400
    if not profile_name:
        return jsonify({"error": "プロファイルが指定されていません。"}), 400

    # 1. Find a sample video in the folder
    # We can use glob for common extensions
    video_exts = {".mp4", ".avi", ".mov", ".mkv"}
    sample_video_path = None
    
    # First check if there's processed run in DB for this folder for better sample?
    # Simpler: just pick first video file in folder
    try:
        files = os.listdir(folder_path)
        files.sort() # Ensure deterministic order
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in video_exts:
                sample_video_path = os.path.join(folder_path, f)
                break
    except OSError:
        pass

    if not sample_video_path:
        return jsonify({"error": "フォルダ内に検証用動画ファイルが見つかりませんでした。"}), 404

    # 2. Load Calibration Profile
    # Use load_calibration_payload (needs run_id, but here we only have profile name)
    # Actually validation/loading via profile name directly:
    calib_dir = ensure_calibration_dir()
    profile_path = os.path.join(calib_dir, f"{profile_name}.json")
    
    if not os.path.exists(profile_path):
        return jsonify({"error": f"プロファイルデータが見つかりません: {profile_name}"}), 404
        
    try:
        with open(profile_path, "r", encoding="utf-8") as fh:
            calib_data = json.load(fh)
    except Exception:
        return jsonify({"error": "プロファイルデータの読み込みに失敗しました。"}), 500

    # 3. Extract Line Data
    lines_raw = calib_data.get("lines") or {}
    # Helper to clean up points list [ [x,y], ... ]
    def clean_points(pts):
        if not pts: return []
        return [p for p in pts if isinstance(p, list) and len(p) >= 2]

    lines_payload = {
        "left_white_line": clean_points(lines_raw.get("left_white_line")),
        "right_white_line": clean_points(lines_raw.get("right_white_line")),
        "center_line": clean_points(lines_raw.get("center_line")),
        "left_mid_line": clean_points(lines_raw.get("left_mid_line")),
        "right_mid_line": clean_points(lines_raw.get("right_mid_line")),
    }

    # 4. Get Sample Frame (Middle of video usually safest, or just 1st sec)
    try:
        # Load frame around 10% or frame 30 to avoid black start
        metrics = probe_video(sample_video_path)
        total_frames = metrics.get("frame_count", 0)
        target_frame = min(30, total_frames // 2) 
        
        frame = load_video_frame(sample_video_path, target_frame)
        if frame is None:
             raise ValueError("Frame load failed")
             
        # Encode to Base64
        import base64
        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret:
            raise ValueError("Image encode failed")
        
        b64_str = base64.b64encode(buffer).decode('utf-8')
        
        return jsonify({
            "image_base64": b64_str,
            "image_width": frame.shape[1],
            "image_height": frame.shape[0],
            "video_filename": os.path.basename(sample_video_path),
            "lines": lines_payload
        })

    except Exception as e:
        current_app.logger.exception("Verification frame generation failed")
        return jsonify({"error": f"検証画像の生成に失敗しました: {e}"}), 500


@main.route("/manual_overtake/reprocess", methods=["POST"])
def manual_overtake_reprocess():
    error_response = _ensure_database_ready()
    if error_response is not None:
        return error_response

    raw_ids = request.form.getlist("run_id")
    single_value = request.form.get("run_id", type=int)
    if not raw_ids and single_value is not None:
        raw_ids = [single_value]

    run_ids = list(dict.fromkeys(_normalize_run_ids(list(raw_ids))))
    if not run_ids:
        flash("再処理対象のRunを選択してください。", "warning")
        return redirect(request.referrer or url_for("main.manual_overtake_view"))

    for run_id in run_ids:
        actions_taken, dependency_warnings, fatal = _prepare_manual_overtake_dependencies(run_id)
        for action in actions_taken:
            current_app.logger.info(
                "Manual reprocess prerequisites executed for run %s: %s",
                run_id,
                action,
            )
        for warning_msg in dependency_warnings:
            flash(f"Run {run_id}: {warning_msg}", "warning")
        if fatal:
            flash(f"Run {run_id}: 再処理に必要な検出が不足しています。", "danger")
            continue

        entries = list_manual_overtake_timeline_entries([run_id])
        if not entries:
            cores = list_manual_overtake_event_cores([run_id])
            for core in cores:
                frame_core = core.get("frame_num")
                overtaker_core = core.get("overtaker_group_id")
                overtaken_core = core.get("overtaken_group_id")
                if frame_core is None or overtaker_core is None or overtaken_core is None:
                    continue
                try:
                    frame_int = int(frame_core)
                    overtaker_int = int(overtaker_core)
                    overtaken_int = int(overtaken_core)
                except (TypeError, ValueError):
                    continue
                manual_core_id = core.get("manual_event_id")
                try:
                    manual_core_id_int = (
                        int(manual_core_id) if manual_core_id is not None else None
                    )
                except (TypeError, ValueError):
                    manual_core_id_int = None
                try:
                    record_manual_overtake_timeline_entry(
                        run_id,
                        frame_int,
                        overtaker_int,
                        overtaken_int,
                        notes=core.get("notes"),
                        last_event_id=manual_core_id_int,
                    )
                except Exception:
                    current_app.logger.exception(
                        "Failed to backfill manual overtake timeline for run %s", run_id
                    )
            entries = list_manual_overtake_timeline_entries([run_id])

        if not entries:
            flash(f"Run {run_id}: 再処理対象の手動追い越しイベントが見つかりません。", "info")
            continue

        run_errors: list[str] = []
        run_warnings: list[str] = []
        processed_count = 0

        for entry in entries:
            timeline_id_value = entry.get("timeline_id")
            try:
                timeline_id_int = int(timeline_id_value)
            except (TypeError, ValueError):
                timeline_id_int = None
            timeline_label = timeline_id_value
            if timeline_label is None or timeline_label == "":
                timeline_label = "?"

            frame_value = entry.get("frame_num")
            overtaker_gid = entry.get("overtaker_group_id")
            overtaken_gid = entry.get("overtaken_group_id")
            base_notes = entry.get("notes")
            manual_event_id = entry.get("last_event_id")

            if frame_value is None or overtaker_gid is None or overtaken_gid is None:
                run_errors.append(
                    f"timeline #{timeline_label}: 必要な識別情報が不足しているためスキップしました。"
                )
                continue

            try:
                frame_int = int(frame_value)
                overtaker_int = int(overtaker_gid)
                overtaken_int = int(overtaken_gid)
            except (TypeError, ValueError):
                run_errors.append(
                    f"timeline #{timeline_label} (Frame {frame_value}): グループIDまたはフレーム番号を解釈できませんでした。"
                )
                continue

            try:
                computation = _compute_manual_overtake_event_data(
                    run_id,
                    frame_int,
                    overtaker_int,
                    overtaken_int,
                    notes=base_notes,
                    context_window=0,
                    compute_lane_metrics=True,
                )
            except ManualOvertakeComputationError as exc:
                run_errors.append(
                    f"timeline #{timeline_label} (Frame {frame_value}): {exc}"
                )
                continue
            except Exception as exc:  # pragma: no cover - runtime safeguard
                current_app.logger.exception(
                    "Unexpected failure while computing manual overtake data for run %s", run_id
                )
                run_errors.append(
                    f"timeline #{timeline_label} (Frame {frame_value}): 計算に失敗しました ({exc})"
                )
                continue

            payload = computation.payload
            context_rows = computation.context_frames
            detect_frame = computation.detection_frame_num
            if computation.notices:
                run_warnings.extend(computation.notices)

            event_id: Optional[int] = None

            if manual_event_id is not None:
                try:
                    manual_event_id_int = int(manual_event_id)
                except (TypeError, ValueError):
                    manual_event_id_int = None
                if manual_event_id_int is not None:
                    existing_core = fetch_manual_overtake_event_core(manual_event_id_int)
                    if existing_core:
                        updated = update_manual_overtake_event(manual_event_id_int, payload)
                        if updated:
                            event_id = manual_event_id_int

            if event_id is None:
                try:
                    event_id = insert_manual_overtake_event(payload)
                except Exception as exc:  # pragma: no cover - runtime safeguard
                    current_app.logger.exception("Failed to insert manual overtake event during reprocess")
                    run_errors.append(
                        f"timeline #{timeline_label} (Frame {frame_value}): イベント保存に失敗しました ({exc})"
                    )
                    continue

            if event_id is not None:
                backup_notice = _backup_manual_overtake_timing(run_id, event_id, payload)
                if backup_notice:
                    run_warnings.append(backup_notice)

            context_saved, context_messages = _save_manual_overtake_context_frames(
                event_id,
                context_rows,
                payload,
                frame_int,
                label=f"イベントID {event_id}",
            )
            run_warnings.extend(context_messages)

            try:
                flags_applied = apply_manual_overtake_flags(
                    run_id,
                    detect_frame,
                    overtaker_int,
                    overtaken_int,
                )
                if not flags_applied:
                    run_warnings.append(
                        f"イベントID {event_id}: 指定フレームの検出に追い越しフラグを設定できませんでした。"
                    )
            except Exception as exc:  # pragma: no cover - runtime safeguard
                current_app.logger.exception("Failed to update detection flags during manual reprocess")
                run_warnings.append(
                    f"イベントID {event_id}: 追い越しフラグの更新に失敗しました ({exc})"
                )

            if timeline_id_int is not None:
                try:
                    mark_manual_overtake_timeline_processed(timeline_id_int, event_id)
                except Exception as exc:  # pragma: no cover - runtime safeguard
                    current_app.logger.exception("Failed to update manual timeline during reprocess")
                    run_warnings.append(
                        f"timeline #{timeline_label}: タイムラインの更新に失敗しました ({exc})"
                    )
            try:
                record_manual_overtake_timeline_entry(
                    run_id,
                    frame_int,
                    overtaker_int,
                    overtaken_int,
                    notes=payload.get("notes"),
                    last_event_id=event_id,
                )
            except Exception as exc:  # pragma: no cover - runtime safeguard
                current_app.logger.exception("Failed to refresh manual timeline entry during reprocess")
                run_warnings.append(
                    f"timeline #{timeline_label}: タイムラインの再作成に失敗しました ({exc})"
                )

            processed_count += 1

        try:
            touch_manual_run_progress(run_id, annotation=True)
        except Exception:
            current_app.logger.exception("Failed to update manual run annotation timestamp during reprocess")

        if processed_count and not run_errors:
            flash(f"Run {run_id}: 手動追い越しイベントを{processed_count}件再処理しました。", "success")
        elif processed_count:
            flash(
                f"Run {run_id}: {processed_count}件再処理しましたが、{len(run_errors)}件のエラーがあります。",
                "warning",
            )
        else:
            flash(f"Run {run_id}: 再処理に成功したイベントはありません。", "warning")

        for warning_msg in run_warnings:
            flash(f"Run {run_id}: {warning_msg}", "warning")
        for error_msg in run_errors:
            flash(f"Run {run_id}: {error_msg}", "danger")

    target_url = request.referrer or url_for("main.manual_overtake_view", run_id=run_ids)
    return redirect(target_url)


@main.route("/manual_overtake/context/process", methods=["POST"])
def manual_overtake_context_process():
    error_response = _ensure_database_ready()
    if error_response is not None:
        return error_response

    raw_ids = request.form.getlist("run_id")
    single_value = request.form.get("run_id", type=int)
    if not raw_ids and single_value is not None:
        raw_ids = [single_value]

    run_ids = _normalize_run_ids(list(raw_ids))
    if not run_ids:
        flash("後処理対象のRunを選択してください。", "warning")
        return redirect(request.referrer or url_for("main.manual_overtake_view"))

    result = _execute_manual_context_processing(run_ids)

    if result.get("ensure_error"):
        flash(
            f"追い越しフレーム後処理対象の確認に失敗しました: {result['ensure_error']}",
            "danger",
        )
    elif result.get("enqueued"):
        flash(
            f"追い越しフレーム後処理キューに {result['enqueued']} 件を追加しました。",
            "info",
        )

    processed = int(result.get("processed", 0) or 0)
    if processed:
        if int(result.get("remaining_total", 0) or 0) > 0:
            flash(
                f"追い越しフレーム後処理を {processed} 件実行しました (残り {result['remaining_total']} 件)。",
                "success",
            )
        else:
            flash(f"追い越しフレーム後処理を {processed} 件実行しました。", "success")
    elif int(result.get("pending_before", 0) or 0) == 0:
        flash("追い越しフレーム後処理の対象が見つかりませんでした。", "info")
    else:
        flash("追い越しフレーム後処理の対象が見つかりませんでした。", "info")

    for warning in result.get("warnings", []):
        if warning:
            flash(warning, "warning")

    for notice in result.get("notices", []):
        if notice:
            flash(notice, "warning")

    pending_total = int(result.get("remaining_total", 0) or 0)
    if pending_total > 0:
        flash(
            f"未処理の追い越しフレーム後処理キューが {pending_total} 件残っています。",
            "warning",
        )

    target_url = request.referrer or url_for("main.manual_overtake_view", run_id=run_ids)
    return redirect(target_url)


@main.route("/api/manual_overtake/context/backlog", methods=["GET"])
def manual_overtake_context_backlog_status_api():
    error_response = _ensure_database_ready()
    if error_response is not None:
        return error_response

    raw_runs = request.args.getlist("run_id")
    run_ids = _normalize_run_ids(list(raw_runs))
    summary = count_manual_context_backlog(run_ids or None)
    total_pending = sum(int(value or 0) for value in summary.values())
    status_totals = summarize_manual_context_backlog_by_status(run_ids or None)
    backlog_total = sum(int(value or 0) for value in status_totals.values())

    payload = {
        "run_ids": run_ids,
        "pending": {str(key): int(value or 0) for key, value in summary.items()},
        "pending_total": int(total_pending),
        "status_totals": {str(key): int(value or 0) for key, value in status_totals.items()},
        "backlog_total": int(backlog_total),
        "snapshot_taken_at": datetime.now(timezone.utc).isoformat(),
    }
    return jsonify(payload)


@main.route("/api/global_stats", methods=["GET"])
def global_stats_api():
    """全Runの統計情報（総追い越し数、自転車数、自動車数、平均速度等）を返すAPI。"""
    error_response = _ensure_database_ready()
    if error_response is not None:
        return error_response

    stats = {
        "overtakes": 0,
        "bicycles": 0,
        "cars": 0,
        "avg_overtakes_per_file": 0.0,
        "avg_speed_kmh": 0.0,
        "avg_overtake_speed_kmh": 0.0,
        "inner_ratio": 0.0,
        "outer_ratio": 0.0,
    }

    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            configure_connection(conn, mode="read")
            
            # 1. Total Overtakes
            cursor = conn.execute("SELECT COUNT(*) FROM OvertakeEvents")
            row = cursor.fetchone()
            if row:
                stats["overtakes"] = row[0]

            # 2. Total Bicycles (approximate count of detections)
            cursor = conn.execute("SELECT COUNT(*) FROM Detection WHERE model_name IN ('bicycle', 'cyclist')")
            row = cursor.fetchone()
            if row:
                stats["bicycles"] = row[0]

            # 3. Total Cars (approximate count of detections)
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

            # 6. Avg Overtake Speed & Inner/Outer Ratio
            # Link OvertakeEvents to Detection to get speed and lane_position_flag
            # Inner/Outer check: lane_position_flag is '+' (Inner) or '-' (Outer) usually, or check schema/values.
            # db_manager.py: {"value": "+", "label": "内側 (+)"}, {"value": "-", "label": "外側 (-)"}
            
            # Avg Overtake Speed
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
            files = glob.glob(os.path.join(os.getenv("Opt_files", "output").strip('"'), "*", "overtake_snapshots", "*.jpg"))
            files.sort(key=os.path.getmtime, reverse=True) # Sort by new
            
            # Convert to relative path from OPT_FILES_PATH (output root)
            opt_root = os.getenv("Opt_files", "output").strip('"')
            abs_opt = os.path.abspath(opt_root)
            
            image_list = []
            for f in files:
                abs_f = os.path.abspath(f)
                if abs_f.startswith(abs_opt):
                    # Make it relative to 'output' so it can be served via /results/
                    rel = os.path.relpath(abs_f, abs_opt).replace(os.path.sep, '/')
                    image_list.append(rel)
            stats["images"] = image_list

    except Exception as e:
        current_app.logger.exception("Failed to fetch global stats")
        return jsonify({"error": str(e)}), 500

    return jsonify(stats)


@main.route("/global_summary")
def global_summary_view():
    """全Runの統計情報のサマリーページを表示する。"""
    return render_template("global_summary.html", title="Global Stats Summary")


@main.route("/api/manual_overtake/context/process", methods=["POST"])
def manual_overtake_context_process_api():
    error_response = _ensure_database_ready()
    if error_response is not None:
        return error_response

    payload = request.get_json(silent=True) or {}
    raw_runs = payload.get("run_ids")
    if raw_runs is None:
        return jsonify({"error": "後処理対象のRunが指定されていません。"}), 400

    if isinstance(raw_runs, (str, int)):
        run_values = [raw_runs]
    elif isinstance(raw_runs, Sequence):
        run_values = list(raw_runs)
    else:
        run_values = []

    run_ids = _normalize_run_ids(run_values)
    if not run_ids:
        return jsonify({"error": "後処理対象のRunが指定されていません。"}), 400

    lane_width_m_value = payload.get("lane_width_m")
    lane_width_meters: Optional[float]
    try:
        lane_width_meters = float(lane_width_m_value)
    except (TypeError, ValueError):
        lane_width_meters = None
    lane_width_updated = 0
    if lane_width_meters is not None and lane_width_meters > 0:
        try:
            lane_width_updated = update_manual_lane_width(run_ids, lane_width_meters)
        except Exception:  # pragma: no cover - runtime safeguard
            current_app.logger.exception("Failed to update manual lane width before processing")

    limit_value = payload.get("limit")
    try:
        limit_candidate = int(limit_value) if limit_value is not None else None
    except (TypeError, ValueError):
        limit_candidate = None
    else:
        if limit_candidate is not None and limit_candidate <= 0:
            limit_candidate = None

    ensure_flag = payload.get("ensure_missing")
    ensure_missing = True if ensure_flag is None else bool(ensure_flag)

    result = _execute_manual_context_processing(
        run_ids,
        limit=limit_candidate,
        ensure_missing=ensure_missing,
    )

    processed = int(result.get("processed", 0) or 0)
    remaining_total = int(result.get("remaining_total", 0) or 0)
    pending_before = int(result.get("pending_before", 0) or 0)

    if processed and remaining_total:
        default_message = f"追い越しフレーム後処理を {processed} 件実行しました (残り {remaining_total} 件)。"
    elif processed:
        default_message = f"追い越しフレーム後処理を {processed} 件完了しました。"
    elif pending_before == 0:
        default_message = "未処理の追い越しフレーム処理対象は見つかりませんでした。"
    else:
        default_message = "追い越しフレーム後処理の対象が見つかりませんでした。"

    response_payload = {
        "run_ids": result.get("run_ids", run_ids),
        "pending_before": pending_before,
        "processed": processed,
        "remaining": result.get("remaining", {}),
        "remaining_total": remaining_total,
        "notices": result.get("notices", []),
        "warnings": result.get("warnings", []),
        "enqueued": int(result.get("enqueued", 0) or 0),
        "lane_width_updated": int(lane_width_updated or 0),
        "enqueued_event_ids": result.get("enqueued_event_ids", []),
        "ensure_error": result.get("ensure_error"),
        "batch_limit": result.get("batch_limit"),
        "ensure_missing": result.get("ensure_missing"),
        "message": result.get("message", default_message),
        "snapshot_taken_at": datetime.now(timezone.utc).isoformat(),
    }
    if lane_width_meters is not None and lane_width_meters > 0:
        response_payload["lane_width_m"] = lane_width_meters
    return jsonify(response_payload)


@main.route("/api/manual_overtake/events/<int:manual_event_id>", methods=["DELETE"])
def manual_overtake_delete(manual_event_id: int):
    try:
        deleted = delete_manual_overtake_event(manual_event_id)
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to delete manual overtake event")
        return jsonify({"error": "削除に失敗しました。"}), 500

    if not deleted:
        return jsonify({"error": "指定されたイベントが見つかりません。"}), 404

    try:
        mark_manual_overtake_timeline_event_deleted(manual_event_id)
    except Exception:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to unlink manual overtake timeline entry")

    return jsonify({"status": "ok"})


@main.route("/manual_overtake/reset", methods=["POST"])
def manual_overtake_reset():
    run_values = request.form.getlist("run_id")
    extra = request.form.get("run_ids")
    if extra:
        run_values.extend(extra.split(","))

    scope = (request.form.get("scope") or "events").lower()
    if scope not in {"events", "progress", "all"}:
        scope = "events"

    normalized: list[int] = []
    seen: set[int] = set()
    for value in run_values:
        try:
            candidate = int(value)
        except (TypeError, ValueError):
            continue
        if candidate > 0 and candidate not in seen:
            normalized.append(candidate)
            seen.add(candidate)

    if not normalized:
        flash("リセットするRun IDを指定してください。", "warning")
        return redirect(request.referrer or url_for("main.manual_overtake"))

    events_deleted = detections_reset = 0
    progress_cleared = 0

    if scope in {"events", "all"}:
        try:
            events_deleted, detections_reset = reset_manual_overtake_for_runs(normalized)
        except Exception as exc:  # pragma: no cover - runtime safeguard
            current_app.logger.exception("Failed to reset manual overtake data")
            flash("手動追い越しデータの初期化に失敗しました。", "danger")
            return redirect(request.referrer or url_for("main.manual_overtake"))

    if scope in {"progress", "all"}:
        try:
            progress_cleared = clear_manual_run_progress(normalized)
        except Exception as exc:  # pragma: no cover - runtime safeguard
            current_app.logger.exception("Failed to clear manual run progress")
            flash("手動追い越しのステータス初期化に失敗しました。", "danger")
            return redirect(request.referrer or url_for("main.manual_overtake"))

    if scope == "events" and events_deleted:
        for run_id in normalized:
            try:
                touch_manual_run_progress(run_id, annotation=True)
            except Exception:  # pragma: no cover - runtime safeguard
                current_app.logger.exception("Failed to update manual progress timestamp during reset")

    runs_label = ", ".join(str(rid) for rid in normalized)
    if scope == "events":
        if events_deleted or detections_reset:
            flash(
                f"Run {runs_label}: 手動追い越しイベントを{events_deleted}件削除し、{detections_reset}件の検出フラグを初期化しました。",
                "success",
            )
        else:
            flash("対象の手動追い越しイベントは見つかりませんでした。", "info")
    elif scope == "progress":
        if progress_cleared:
            flash(
                f"Run {runs_label}: 観覧ステータスを{progress_cleared}件リセットしました。",
                "success",
            )
        else:
            flash("リセット対象のステータスが見つかりませんでした。", "info")
    else:  # scope == "all"
        messages: list[str] = []
        if events_deleted or detections_reset:
            messages.append(f"イベント{events_deleted}件削除・フラグ{detections_reset}件初期化")
        if progress_cleared:
            messages.append(f"ステータス{progress_cleared}件リセット")
        if messages:
            flash(f"Run {runs_label}: " + " / ".join(messages) + " を実施しました。", "success")
        else:
            flash("対象のデータは見つかりませんでした。", "info")

    return redirect(request.referrer or url_for("main.manual_overtake"))


@main.route("/detections")
def detections():
    try:
        view_mode = (request.args.get('mode') or 'auto').lower()
        if view_mode not in {'auto', 'manual'}:
            view_mode = 'auto'

        run_options = list_detection_runs()

        if view_mode == 'manual':
            selected_run_id = request.args.get('run_id', type=int)
            limit_value = request.args.get('limit', type=int)
            if limit_value is None or limit_value <= 0:
                limit_value = 500
            try:
                manual_events = list_manual_overtake_events(
                    run_id=selected_run_id,
                    limit=limit_value,
                )
                _prepare_manual_events(manual_events)
            except Exception as exc:  # pragma: no cover - runtime safeguard
                current_app.logger.exception("Failed to load manual overtake events for DB view")
                flash(f"手動追い越しイベントの取得に失敗しました: {exc}", "danger")
                manual_events = []

            empty_search_values = {
                'field': '',
                'text': '',
                'option': '',
                'min': '',
                'max': '',
                'value': '',
            }

            return render_template(
                "detections.html",
                view_mode=view_mode,
                detections=[],
                page=1,
                per_page=limit_value,
                total=len(manual_events),
                total_pages=1,
                run_options=run_options,
                selected_run_id=selected_run_id,
                search_fields=[],
                selected_search_field=None,
                search_values=empty_search_values,
                manual_events=manual_events,
                manual_limit=limit_value,
            )

        page = max(request.args.get('page', 1, type=int), 1)
        per_page = request.args.get('per_page', 50, type=int)
        per_page = max(10, min(per_page, 500))
        run_id = request.args.get('run_id', type=int)

        search_field_key = (request.args.get('search_field') or '').strip()
        search_fields = get_detection_search_fields()
        selected_search_field = next(
            (field for field in search_fields if field['key'] == search_field_key),
            None,
        )

        search_filters: Optional[dict[str, Any]] = None
        search_values: dict[str, Any] = {
            'field': search_field_key,
            'text': request.args.get('search_text', ''),
            'option': request.args.get('search_option', ''),
            'min': request.args.get('search_min', ''),
            'max': request.args.get('search_max', ''),
            'value': request.args.get('search_value', ''),
        }

        if selected_search_field:
            search_filters = {'field': selected_search_field['key']}
            field_type = selected_search_field.get('type', 'text')
            if field_type == 'text':
                keyword = search_values['text'].strip()
                if keyword:
                    search_filters['value'] = keyword
            elif field_type == 'enum':
                option = search_values['option']
                if option:
                    search_filters['value'] = option
            elif field_type == 'presence':
                option = search_values['option'] or search_values['value']
                if option in {'has', 'missing'}:
                    search_filters['value'] = option
            elif field_type == 'number':
                coerce_type = selected_search_field.get('coerce')

                def _convert(raw: str) -> Optional[Any]:
                    if raw in (None, ''):
                        return None
                    try:
                        if coerce_type == 'int':
                            return int(raw)
                        if coerce_type == 'float':
                            return float(raw)
                        return float(raw)
                    except (TypeError, ValueError):
                        return None

                min_value = _convert(search_values['min'])
                max_value = _convert(search_values['max'])
                exact_value = _convert(search_values['value'])
                if min_value is not None:
                    search_filters['min'] = min_value
                if max_value is not None:
                    search_filters['max'] = max_value
                if exact_value is not None and min_value is None and max_value is None:
                    search_filters['value'] = exact_value
        else:
            search_filters = None

        data, total = show_recent_detections(
            page=page,
            per_page=per_page,
            run_id=run_id,
            search=search_filters,
        )
        total_pages = max((total + per_page - 1) // per_page, 1)
        if page > total_pages and total > 0:
            return redirect(
                url_for(
                    "main.detections",
                    page=total_pages,
                    run_id=run_id,
                    per_page=per_page,
                    search_field=search_field_key,
                    search_text=search_values['text'],
                    search_option=search_values['option'],
                    search_min=search_values['min'],
                    search_max=search_values['max'],
                    search_value=search_values['value'],
                    mode=view_mode,
                )
            )
        return render_template(
            "detections.html",
            view_mode=view_mode,
            detections=data,
            page=page,
            per_page=per_page,
            total=total,
            total_pages=total_pages,
            run_options=run_options,
            selected_run_id=run_id,
            search_fields=search_fields,
            selected_search_field=selected_search_field,
            search_values=search_values,
            manual_events=[],
            manual_limit=None,
        )
    except Exception as e:
        flash(f"検出結果表示エラー: {e}", "danger")
    return redirect(url_for("main.index"))


@main.route("/downloads/csv_columns")
def download_csv_column_guide():
    if not os.path.exists(CSV_COLUMN_GUIDE_PATH):
        flash("CSVカラム説明ファイルが見つかりません。", "danger")
        return redirect(url_for("main.detections"))
    directory = os.path.dirname(CSV_COLUMN_GUIDE_PATH)
    filename = os.path.basename(CSV_COLUMN_GUIDE_PATH)
    return send_from_directory(directory, filename, as_attachment=True)


@main.route("/results/<path:filename>")
def results_file_serve(filename):
    directory = os.getenv("Opt_files", "output").strip('"')
    if not os.path.isabs(directory):
        directory = os.path.abspath(directory)
    return send_from_directory(directory, filename)


# ========== Video Metadata API Endpoints ==========

@main.route("/api/video/set_metadata", methods=["POST"])
def set_video_metadata():
    """動画ファイルのメタデータ（道路タイプ、収集年度）を設定する。"""
    try:
        data = request.get_json()
        run_ids = data.get("run_ids", [])
        road_type = data.get("road_type")  # 'widened', 'non_widened', or None
        collection_year = data.get("collection_year")  # integer or None
        
        if not run_ids:
            return jsonify({"success": False, "error": "run_idsが指定されていません"}), 400
        
        # Validate road_type
        if road_type is not None and road_type not in ["widened", "non_widened", ""]:
            return jsonify({"success": False, "error": "無効なroad_type値です"}), 400
        
        # Validate collection_year
        if collection_year is not None:
            try:
                collection_year = int(collection_year)
                if collection_year < 0:
                    return jsonify({"success": False, "error": "collection_yearは正の整数である必要があります"}), 400
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "無効なcollection_year値です"}), 400
        
        # Convert empty string to None
        if road_type == "":
            road_type = None
        
        # Update database
        conn = sqlite3.connect(MAIN_DB_PATH)
        configure_connection(conn, mode="write")
        cursor = conn.cursor()
        
        try:
            # Get video_ids for the run_ids
            placeholders = ",".join("?" * len(run_ids))
            cursor.execute(
                f"""
                SELECT DISTINCT v.video_id 
                FROM Video v
                JOIN ProcessLog p ON v.video_id = p.video_id
                WHERE p.run_id IN ({placeholders})
                """,
                run_ids
            )
            video_ids = [row[0] for row in cursor.fetchall()]
            
            if not video_ids:
                return jsonify({"success": False, "error": "指定されたrun_idに対応する動画が見つかりません"}), 404
            
            # Update metadata
            vid_placeholders = ",".join("?" * len(video_ids))
            update_parts = []
            params = []
            
            if road_type is not None:
                update_parts.append("road_type = ?")
                params.append(road_type)
            
            if collection_year is not None:
                update_parts.append("collection_year = ?")
                params.append(collection_year)
            
            if update_parts:
                params.extend(video_ids)
                cursor.execute(
                    f"""
                    UPDATE Video 
                    SET {", ".join(update_parts)}
                    WHERE video_id IN ({vid_placeholders})
                    """,
                    params
                )
                conn.commit()
            
            return jsonify({
                "success": True,
                "updated_videos": len(video_ids),
                "road_type": road_type,
                "collection_year": collection_year
            })
            
        finally:
            cursor.close()
            conn.close()
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@main.route("/api/video/<int:run_id>/calibration_preview")
def get_calibration_preview(run_id):
    """指定されたrun_idの動画にキャリブレーションフレームを重ねたプレビュー画像を返す。"""
    try:
        # Get video info
        conn = sqlite3.connect(MAIN_DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                SELECT v.filename, v.source_path, p.calibration_profile
                FROM Video v
                JOIN ProcessLog p ON v.video_id = p.video_id
                WHERE p.run_id = ?
                """,
                (run_id,)
            )
            result = cursor.fetchone()
            
            if not result:
                return jsonify({"success": False, "error": "動画が見つかりません"}), 404
            
            filename, source_path, profile_name = result
            
            # Load calibration profile from JSON file
            # Try run-specific calibration file first, then fall back to profile name
            # Use same logic as calibration_tool.py: os.getenv("Opt_files") or "output"
            opt_folder = os.getenv("Opt_files") or os.getenv("OPT_FILES") or "output"
            calib_dir = os.path.abspath(os.path.join(opt_folder, "calibrations"))
            
            # Priority 1: Run-specific calibration file
            run_specific_path = os.path.join(calib_dir, f"calibration_{run_id}.json")
            
            # Priority 2: Profile name file (if run-specific doesn't exist)
            profile_path = os.path.join(calib_dir, f"{profile_name}.json") if profile_name else None
            
            profile = None
            used_path = None
            
            # Try run-specific file first
            if os.path.exists(run_specific_path):
                try:
                    with open(run_specific_path, 'r', encoding='utf-8') as f:
                        profile = json.load(f)
                    used_path = run_specific_path
                except Exception as e:
                    print(f"Run専用ファイル読み込みエラー: {e}")
            
            # Fall back to profile name file
            if not profile and profile_path and os.path.exists(profile_path):
                try:
                    with open(profile_path, 'r', encoding='utf-8') as f:
                        profile = json.load(f)
                    used_path = profile_path
                except Exception as e:
                    print(f"プロファイルファイル読み込みエラー: {e}")
            
            if not profile:
                return jsonify({
                    "success": False,
                    "error": f"キャリブレーションデータが見つかりません（Run ID: {run_id}, Profile: {profile_name}）"
                }), 404
            
        finally:
            cursor.close()
            conn.close()
        
        # Load video frame
        video_path = source_path if source_path and os.path.exists(source_path) else None
        if not video_path:
            # Try to find in upload folder
            upload_folder = current_app.config.get('UPLOAD_FOLDER', '')
            for folder_name in os.listdir(upload_folder) if upload_folder else []:
                folder_path = os.path.join(upload_folder, folder_name)
                if os.path.isdir(folder_path):
                    potential_path = os.path.join(folder_path, filename)
                    if os.path.exists(potential_path):
                        video_path = potential_path
                        break
        
        if not video_path or not os.path.exists(video_path):
            return jsonify({"success": False, "error": "動画ファイルが見つかりません"}), 404
        
        # Load a frame from the video (middle frame)
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        middle_frame = total_frames // 2
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame)
        ret, frame = cap.read()
        cap.release()
        
        if not ret or frame is None:
            return jsonify({"success": False, "error": "フレームの読み込みに失敗しました"}), 500
        
        # Draw calibration overlay on the frame
        frame_with_overlay = frame.copy()
        
        # Get lines and scale data from calibration profile
        lines_data = profile.get("lines", {})
        scale_data = profile.get("scale", {})
        scale_mode = scale_data.get("mode", "vertical")
        
        # Draw white lines (left, center, right)
        left_line = lines_data.get("left_white_line", [])
        right_line = lines_data.get("right_white_line", [])
        center_line = lines_data.get("center_line", [])
        left_mid = lines_data.get("left_mid_line", [])
        right_mid = lines_data.get("right_mid_line", [])
        
        # Draw left white line (blue)
        if left_line and len(left_line) >= 2:
            pts = [(int(p[0]), int(p[1])) for p in left_line]
            for i in range(len(pts) - 1):
                cv2.line(frame_with_overlay, pts[i], pts[i+1], (255, 0, 0), 2)
        
        # Draw right white line (blue)
        if right_line and len(right_line) >= 2:
            pts = [(int(p[0]), int(p[1])) for p in right_line]
            for i in range(len(pts) - 1):
                cv2.line(frame_with_overlay, pts[i], pts[i+1], (255, 0, 0), 2)
        
        # Draw center line (orange)
        if center_line and len(center_line) >= 2:
            pts = [(int(p[0]), int(p[1])) for p in center_line]
            for i in range(len(pts) - 1):
                cv2.line(frame_with_overlay, pts[i], pts[i+1], (0, 165, 255), 2)
        
        # Draw mid lines (yellow)
        if left_mid and len(left_mid) >= 2:
            pts = [(int(p[0]), int(p[1])) for p in left_mid]
            for i in range(len(pts) - 1):
                cv2.line(frame_with_overlay, pts[i], pts[i+1], (0, 255, 255), 2)
        
        if right_mid and len(right_mid) >= 2:
            pts = [(int(p[0]), int(p[1])) for p in right_mid]
            for i in range(len(pts) - 1):
                cv2.line(frame_with_overlay, pts[i], pts[i+1], (0, 255, 255), 2)
        
        # Draw scale lines (green)
        scale_lines = scale_data.get("lines", [])
        if scale_lines:
            for line in scale_lines:
                if line and len(line) >= 2:
                    pt1 = (int(line[0][0]), int(line[0][1]))
                    pt2 = (int(line[1][0]), int(line[1][1]))
                    cv2.line(frame_with_overlay, pt1, pt2, (0, 255, 0), 2)
                    cv2.circle(frame_with_overlay, pt1, 5, (0, 255, 0), -1)
                    cv2.circle(frame_with_overlay, pt2, 5, (0, 255, 0), -1)
        
        # Draw homography points if mode is homography
        if scale_mode == "homography":
            homography_data = scale_data.get("homography", {})
            image_points = homography_data.get("image_points", [])
            if image_points and len(image_points) == 4:
                pts = [(int(p[0]), int(p[1])) for p in image_points]
                for i in range(4):
                    cv2.line(frame_with_overlay, pts[i], pts[(i+1) % 4], (255, 0, 255), 2)
                for i, pt in enumerate(pts):
                    cv2.circle(frame_with_overlay, pt, 7, (255, 0, 255), -1)
                    cv2.putText(frame_with_overlay, str(i+1), (pt[0]+10, pt[1]+10), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # Encode image to base64
        import base64
        _, buffer = cv2.imencode('.jpg', frame_with_overlay)
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        
        return jsonify({
            "success": True,
            "preview_image": f"data:image/jpeg;base64,{img_base64}",
            "profile_name": profile_name,
            "calibration_mode": scale_mode,
            "frame_number": middle_frame,
            "total_frames": total_frames
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ========== Comparative Analysis Report Endpoints ==========

@main.route("/comparative_report")
def comparative_report_view():
    """比較分析レポートページを表示"""
    try:
        # 利用可能な年度と道路タイプを取得
        metadata = get_available_years_and_road_types()
        return render_template(
            "comparative_report.html",
            years=metadata.get("years", []),
            road_types=metadata.get("road_types", []),
            combinations=metadata.get("combinations", []),
            counts=metadata.get("counts", {}),
        )
    except Exception as e:
        return render_template(
            "comparative_report.html",
            years=[],
            road_types=[],
            combinations=[],
            counts={},
            error=str(e),
        )


@main.route("/api/comparative_report/metadata", methods=["GET"])
def get_comparative_metadata():
    """利用可能な年度と道路タイプのメタデータを取得"""
    try:
        metadata = get_available_years_and_road_types()
        return jsonify({"success": True, "data": metadata})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@main.route("/api/comparative_report/generate", methods=["POST"])
def generate_comparative_report_api():
    """比較分析レポートを生成"""
    try:
        data = request.get_json()
        run_ids = data.get("run_ids")
        collection_years = data.get("collection_years")
        road_types = data.get("road_types")
        metrics = data.get("metrics", ["line_distances", "clearance_distances", "overtake_speeds"])
        
        # アナライザーを初期化
        analyzer = ComparativeAnalyzer()
        
        # データをロード
        analyzer.load_overtake_data(
            run_ids=run_ids,
            collection_years=collection_years,
            road_types=road_types,
        )
        
        # サマリーを取得
        summary = analyzer.get_summary()
        
        # 各指標の統計量を計算
        statistics = {}
        for metric in metrics:
            stats = analyzer.compute_statistics(metric)
            # Noneを除外してシリアライズ可能な形式に変換
            statistics[metric] = {
                f"{road_type}_{year}": {
                    "count": s.count,
                    "mean": s.mean,
                    "median": s.median,
                    "std": s.std,
                    "min": s.min,
                    "max": s.max,
                    "q1": s.q1,
                    "q3": s.q3,
                } if s else None
                for (road_type, year), s in stats.items()
            }
        
        # 統計検定を実行
        tests = {}
        for metric in metrics:
            # 各年度ごとに拡幅 vs 未拡幅を比較
            for year in analyzer.metadata.get("years", []):
                widened_key = ("widened", year)
                non_widened_key = ("non_widened", year)
                
                if widened_key in analyzer.data and non_widened_key in analyzer.data:
                    widened_data = getattr(analyzer.data[widened_key], metric, [])
                    non_widened_data = getattr(analyzer.data[non_widened_key], metric, [])
                    
                    if widened_data and non_widened_data:
                        test_result = compare_two_groups(
                            widened_data,
                            non_widened_data,
                            f"拡幅_{year}",
                            f"未拡幅_{year}",
                        )
                        
                        test_key = f"{metric}_{year}"
                        tests[test_key] = {
                            "test_type": str(test_result.test_type),
                            "p_value": float(test_result.p_value),
                            "statistic": float(test_result.statistic),
                            "effect_size": float(test_result.effect_size) if test_result.effect_size is not None else None,
                            "significant": bool(test_result.significant),
                            "interpretation": str(test_result.interpretation),
                            "groups_compared": [str(g) for g in test_result.groups_compared],
                            "sample_sizes": {str(k): int(v) for k, v in test_result.sample_sizes.items()},
                        }
            
            # 道路タイプごとに複数年度を比較（3年度以上ある場合）
            if len(analyzer.metadata.get("years", [])) >= 3:
                for road_type in analyzer.metadata.get("road_types", []):
                    groups = {}
                    for year in analyzer.metadata.get("years", []):
                        key = (road_type, year)
                        if key in analyzer.data:
                            data = getattr(analyzer.data[key], metric, [])
                            if data:
                                groups[f"{road_type}_{year}"] = data
                    
                    if len(groups) >= 3:
                        test_result = compare_multiple_groups(groups)
                        test_key = f"{metric}_{road_type}_年度比較"
                        tests[test_key] = {
                            "test_type": str(test_result.test_type),
                            "p_value": float(test_result.p_value),
                            "statistic": float(test_result.statistic),
                            "effect_size": float(test_result.effect_size) if test_result.effect_size is not None else None,
                            "significant": bool(test_result.significant),
                            "interpretation": str(test_result.interpretation),
                            "groups_compared": [str(g) for g in test_result.groups_compared],
                            "sample_sizes": {str(k): int(v) for k, v in test_result.sample_sizes.items()},
                        }
        
        return jsonify({
            "success": True,
            "summary": summary,
            "statistics": statistics,
            "tests": tests,
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

