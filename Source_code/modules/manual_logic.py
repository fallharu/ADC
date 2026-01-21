import os
import math
import statistics
import time
import sqlite3
import csv
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque, OrderedDict

# Flask imports - manual_logic needs context sometimes
from flask import current_app

from . import db_manager as dbm

# Safe imports to avoid circular dependency
MAIN_DB_PATH = getattr(dbm, 'MAIN_DB_PATH', None)
fetch_detections_for_frame = getattr(dbm, 'fetch_detections_for_frame', None)
fetch_detection_for_group = getattr(dbm, 'fetch_detection_for_group', None)
fetch_detection_for_track = getattr(dbm, 'fetch_detection_for_track', None)
fetch_tire_detections_for_group = getattr(dbm, 'fetch_tire_detections_for_group', None)
fetch_best_group_bbox = getattr(dbm, 'fetch_best_group_bbox', None)
get_first_detection_frame = getattr(dbm, 'get_first_detection_frame', None)
get_first_detection_frame_for_group = getattr(dbm, 'get_first_detection_frame_for_group', None)
get_next_detection_frame_for_group = getattr(dbm, 'get_next_detection_frame_for_group', None)
get_bicycle_class_aliases = getattr(dbm, 'get_bicycle_class_aliases', None)
convert_video_frame_to_detection_frame = getattr(dbm, 'convert_video_frame_to_detection_frame', None)
convert_detection_frame_to_video_frame = getattr(dbm, 'convert_detection_frame_to_video_frame', None)
update_manual_overtake_event = getattr(dbm, 'update_manual_overtake_event', None)
record_manual_overtake_timeline_entry = getattr(dbm, 'record_manual_overtake_timeline_entry', None)
replace_manual_overtake_context_frames = getattr(dbm, 'replace_manual_overtake_context_frames', None)
apply_manual_overtake_flags = getattr(dbm, 'apply_manual_overtake_flags', None)
touch_manual_run_progress = getattr(dbm, 'touch_manual_run_progress', None)
list_manual_context_backlog = getattr(dbm, 'list_manual_context_backlog', None)
count_manual_context_backlog = getattr(dbm, 'count_manual_context_backlog', None)
mark_manual_context_backlog_processed = getattr(dbm, 'mark_manual_context_backlog_processed', None)
ensure_manual_context_backlog_for_runs = getattr(dbm, 'ensure_manual_context_backlog_for_runs', None)
MANUAL_OVERTAKE_CONTEXT_COLUMNS = getattr(dbm, 'MANUAL_OVERTAKE_CONTEXT_COLUMNS', [])
MANUAL_OVERTAKE_CONTEXT_WINDOW = getattr(dbm, 'MANUAL_OVERTAKE_CONTEXT_WINDOW', 0)

# get_run_video_info fallback
get_run_video_info = getattr(dbm, 'get_run_video_info', None)
if get_run_video_info is None:
    def get_run_video_info(run_id, upload_folder): return None

get_group_movement_direction = getattr(dbm, 'get_group_movement_direction', None)
if get_group_movement_direction is None:
     def get_group_movement_direction(run_id, group_id, frame, window=20): return 'unknown'


from .class_filters import vehicle_allowed_classes
from .group_id import assign_group_ids
from .speed import assign_kinematics
from .approach_distance import assign_approach_and_clearance
from .lane_distance import assign_lane_distance
from .manual_metrics import (
    compute_clearance,
    compute_lane_distance,

    lane_scale_details_at_y,
    LANE_WIDTH_METERS,
    LANE_CONFIRMATION_HALF_SPAN_PX,
    restrict_lane_lines_vertical,
    select_bicycle_tire_measure_point,
    select_measure_point_from_candidates,
)
from .utils import (
    _to_positive_float,
    _resolve_lane_width_m,
)
# We need load_calibration_payload from calibration_tool but cyclic imports might be tricky.
# routes.py imported it from from .calibration_tool
from ..tools.calibration_tool import load_calibration_payload

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

MANUAL_CONTEXT_CAPTURE_WINDOW = 0
MANUAL_OVERTAKE_CSV_FORMATS: dict[str, str] = {
    "collection_year": "{}",
    "road_type": "{}",
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
    "overtaker_white_line_distance_m": "{:.2f}",
    "overtaker_white_line_cross_m": "{:.2f}",
    "overtaker_center_line_distance_m": "{:.2f}",
    "overtaker_center_line_cross_m": "{:.2f}",
    "overtaken_white_line_distance_m": "{:.2f}",
    "overtaken_white_line_cross_m": "{:.2f}",
    "overtaken_center_line_distance_m": "{:.2f}",
    "overtaken_center_line_cross_m": "{:.2f}",
}

MANUAL_OVERTAKE_EXPORT_COLUMNS = list(MANUAL_OVERTAKE_CSV_FORMATS.keys())

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
    run_info = get_run_video_info(run_id, upload_folder) if get_run_video_info else None
    if not run_info:
        return "動画情報を取得できずCSVバックアップをスキップしました。"

    filename = run_info.get("filename") or f"run_{run_id}"
    stem = os.path.splitext(filename)[0] or f"run_{run_id}"
    backup_dir = os.path.join("log", "manual_overtake")
    os.makedirs(backup_dir, exist_ok=True)
    csv_path = os.path.join(backup_dir, f"{stem}_manual_overtake.csv")

    frame_value = event_payload.get("frame_num")
    video_time = event_payload.get("video_time_s")
    overtaker_gid = event_payload.get("overtaker_group_id")
    overtaken_gid = event_payload.get("overtaken_group_id")
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        is_new = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0
        with open(csv_path, "a", encoding="utf-8", newline="") as csv_file:
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

def _manual_export_filename(prefix: str, extension: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}.{extension}"


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

        # --- White/Center Line Logic (Latest Export Rule) ---
        # Default Direction 'B' (Rear Camera): Left=Center, Right=White
        # Map Overtaker
        ot_l_dist = event.get("overtaker_left_line_distance_m")
        ot_r_dist = event.get("overtaker_right_line_distance_m")
        event["overtaker_center_line_distance_m"] = ot_l_dist
        event["overtaker_center_line_cross_m"] = None # No explicit crossing data
        event["overtaker_white_line_distance_m"] = ot_r_dist
        event["overtaker_white_line_cross_m"] = None

        # Map Overtaken
        on_l_dist = event.get("overtaken_left_line_distance_m")
        on_r_dist = event.get("overtaken_right_line_distance_m")
        event["overtaken_center_line_distance_m"] = on_l_dist
        event["overtaken_center_line_cross_m"] = None
        event["overtaken_white_line_distance_m"] = on_r_dist
        event["overtaken_white_line_cross_m"] = None
        
        # Class Suppression
        # White=Bike only, Center=Car(non-Bike) only
        
        ot_cls = str(event.get("overtaker_class_name", "")).lower()
        ot_is_bike = any(x in ot_cls for x in ["bicycle", "bike", "cyclist"])
        if ot_is_bike:
            event["overtaker_center_line_distance_m"] = None
            event["overtaker_center_line_cross_m"] = None
        else:
            event["overtaker_white_line_distance_m"] = None
            event["overtaker_white_line_cross_m"] = None
            
        on_cls = str(event.get("overtaken_class_name", "")).lower()
        on_is_bike = any(x in on_cls for x in ["bicycle", "bike", "cyclist"])
        if on_is_bike:
            event["overtaken_center_line_distance_m"] = None
            event["overtaken_center_line_cross_m"] = None
        else:
            event["overtaken_white_line_distance_m"] = None
            event["overtaken_white_line_cross_m"] = None
        contexts = event.get("context_frames")
        if isinstance(contexts, list):
            for context in contexts:
                if isinstance(context, dict):
                    _apply_manual_distance_ratios(context)


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
    overtaker_track_id: Optional[int] = None,
    overtaken_track_id: Optional[int] = None,
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

    # Fallback to track_id if group_id not found
    if overtaker_detection is None and overtaker_track_id is not None:
        overtaker_detection = next((d for d in detections_frame if d.get('track_id') == overtaker_track_id), None)
    
    if overtaken_detection is None and overtaken_track_id is not None:
        overtaken_detection = next((d for d in detections_frame if d.get('track_id') == overtaken_track_id), None)

    # Fallback search for nearby frames (±5)
    search_range = 5
    if overtaker_detection is None:
        for offset in range(1, search_range + 1):
            for sign in [-1, 1]:
                check_frame = detection_frame_num + (offset * sign)
                det = fetch_detection_for_group(run_id, check_frame, overtaker_group_id)
                if det:
                    overtaker_detection = det
                    break
            if overtaker_detection: break
            
    if overtaken_detection is None:
        for offset in range(1, search_range + 1):
            for sign in [-1, 1]:
                check_frame = detection_frame_num + (offset * sign)
                det = fetch_detection_for_group(run_id, check_frame, overtaken_group_id)
                if det:
                    overtaken_detection = det
                    break
            if overtaken_detection: break

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
    from .manual_metrics import load_white_lines
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

        direction = get_group_movement_direction(run_id, group_value, frame_index)


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
                direction=direction,
            )
        else:
            measure_x, measure_y = select_measure_point_from_candidates(
                filtered_candidates,
                left_line,
                right_line,
                direction=direction,
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


def _process_manual_context_backlog(
    run_ids: Optional[Sequence[int]] = None,
    *,
    limit: Optional[int] = None,
    batch_size: Optional[int] = None,
    time_limit_s: Optional[float] = None,
    group_presence_context: bool = False,
) -> tuple[int, list[str], dict[int, int]]:
    """Process manual context backlog queue."""

    limit_value = limit
    if limit_value is None and batch_size is not None:
        limit_value = batch_size

    backlog_entries = list_manual_context_backlog(run_ids, limit=limit_value)
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
            f"{label} median {median_val:.2f} m / max {max(values):.2f} m / min {min(values):.2f} m"
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

        lane_summary = _format_summary("Lane distance", lane_values)
        clearance_summary = _format_summary("Clearance", clearance_values)

        summary_parts = [part for part in (lane_summary, clearance_summary) if part]
        if not summary_parts:
            return None

        return " / ".join(summary_parts)

    def _entry_label(entry: Mapping[str, Any]) -> str:
        manual_event_id = entry.get("manual_event_id")
        return f"Event ID {manual_event_id}" if manual_event_id else "Event"

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
            notice = f"{label}: run/frame/group data missing; skipped."
            return entry, False, [notice], notice

        actions_taken, warnings, fatal = _prepare_manual_overtake_dependencies(run_int)
        if actions_taken:
            recompute_messages.append(
                f"{label}: prerequisites recomputed ({', '.join(actions_taken)})"
            )
        recompute_messages.extend(warnings)
        if fatal:
            notice = f"{label}: required detections missing."
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
                f"{label}: recompute failed ({exc})"
            )
            recomputation = None
        except Exception as exc:  # pragma: no cover - safety net
            logger.exception("Failed to recompute manual overtake frame")
            recompute_messages.append(
                f"{label}: recompute error ({exc})"
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
                f"{label}: {distance_summary} (frames {len(context_frames)})"
            )
        else:
            recompute_messages.append(
                f"{label}: missing run/group info for context recompute."
            )

        if manual_event_id:
            try:
                update_manual_overtake_event(int(manual_event_id), event_payload)
            except Exception as exc:  # pragma: no cover - safety net
                recompute_messages.append(
                    f"{label}: failed to update event ({exc})"
                )
        else:
            notice = f"{label}: invalid manual_event_id; not saved."
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
            context_notices = [f"{label}: context processing failed ({exc})"]

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
                    f"{label}: timeline update failed ({exc})"
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
                        f"{label}: unable to set manual overtake flags."
                    )
            except Exception as exc:  # pragma: no cover - safety net
                logger.exception("Failed to update detection manual overtake flags during context processing")
                recompute_messages.append(
                    f"{label}: manual overtake flag update failed ({exc})"
                )

        if manual_event_id is not None:
            try:
                _backup_manual_overtake_timing(run_int, int(manual_event_id), event_payload)
            except Exception as exc:  # pragma: no cover - safety net
                logger.exception("Failed to back up manual overtake timing during context processing")
                recompute_messages.append(
                    f"{label}: CSV backup failed ({exc})"
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
        message = f"{label}: context processing error ({exc})"
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
            backlog_table = entry.get("backlog_table") or entry.get("source_table")
            mark_manual_context_backlog_processed(
                entry.get("backlog_id"),
                success=context_saved,
                error_message=error_message,
                backlog_table=backlog_table,
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
    """Run manual context processing and return summary."""

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
            f"Manual context backlog check failed: {result['ensure_error']}"
        )

    return result
def _collect_manual_scale_preview(
    run_id: int,
    frame_num: int,
    overtaker_id: int,
    overtaken_id: int,
) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[str, int]]]:
    """手動スケーリング調整用のプレビュー情報を収集する。"""

    video_info = get_run_video_info(run_id, "uploads") if get_run_video_info else None  # Default upload folder
    if not video_info:
         return None, ("Video info not found", 404)

    try:
        computation = _compute_manual_overtake_event_data(
            run_id,
            frame_num,
            overtaker_id,
            overtaken_id,
            compute_lane_metrics=True,
            group_presence_context=True,
        )
    except ManualOvertakeComputationError as exc:
        return None, (str(exc), exc.status_code)
    except Exception as exc:
        current_app.logger.exception("Failed to compute manual overtake data for preview")
        return None, (f"Computation failed: {exc}", 500)

    # Return structure expected by manual.py
    return {
        "video_info": {
            "file_path": video_info["path"],
             "fps": video_info["fps"],
        },
        "event": computation.payload,
    }, None

def _apply_manual_distance_ratios(event: dict[str, Any]) -> None:
    """イベントデータの距離(m)とピクセル(px)から比率を計算して格納する。"""
    keys = [
        ("clearance_distance", "clearance_distance_px_ratio"),
        ("overtaker_line_distance", "overtaker_line_distance_px_ratio"),
        ("overtaken_line_distance", "overtaken_line_distance_px_ratio"),
    ]
    for prefix, ratio_key in keys:
        dist_m = event.get(f"{prefix}_m")
        dist_px = event.get(f"{prefix}_px")
        
        # 既存の値があれば優先
        if event.get(ratio_key) is not None:
             continue
             
        ratio = None
        if dist_m is not None and dist_px is not None:
            try:
                m_val = float(dist_m)
                px_val = float(dist_px)
                if px_val > 0.001:  # avoid zero div
                    ratio = m_val / px_val
            except (TypeError, ValueError):
                pass
        
        event[ratio_key] = ratio


def recalculate_manual_events_batch(run_ids: Optional[List[int]] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    ManualOvertakeEvents のメトリクス（距離・速度・比率など）を再計算して更新する。
    """
    # Use dbm as imported in top of file
    events = dbm.list_manual_overtake_events(run_ids=run_ids, limit=limit)
    processed_count = 0
    errors = []
    updated_ids = []
    clearance_values = []
    
    for event in events:
        try:
            manual_event_id = event['manual_event_id']
            overtaker_track = event.get('overtaker_track_id')
            overtaken_track = event.get('overtaken_track_id')
            
            computation = _compute_manual_overtake_event_data(
                event['run_id'],
                event['frame_num'],
                event['overtaker_group_id'],
                event['overtaken_group_id'],
                overtaker_track_id=overtaker_track,
                overtaken_track_id=overtaken_track,
                compute_lane_metrics=True,
                group_presence_context=False
            )
            
            payload = computation.payload
            
            if dbm.update_manual_overtake_event(manual_event_id, payload):
                 updated_ids.append(manual_event_id)
                 processed_count += 1
                 val = payload.get('clearance_distance_m')
                 if val is not None:
                     clearance_values.append(float(val))
            else:
                 errors.append(f"Event {manual_event_id}: Update failed (DB specific)")
                 
        except Exception as e:
            errors.append(f"Event {event.get('manual_event_id')}: {e}")
            
    stats = {}
    if clearance_values:
        stats['min'] = min(clearance_values)
        stats['max'] = max(clearance_values)
        stats['median'] = statistics.median(clearance_values)
    else:
        stats['min'] = None
        stats['max'] = None
        stats['median'] = None

    return {
        "processed": processed_count,
        "total": len(events),
        "errors": errors,
        "updated_ids": updated_ids,
        "stats": stats
    }
