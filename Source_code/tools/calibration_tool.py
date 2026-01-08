"""Web UI向けのキャリブレーションデータを管理するユーティリティ。

旧来のOpenCVデスクトップツールを置き換え、Flaskのルートや将来のスクリプトから
共通の検証ロジックを利用できるようにする。
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, TYPE_CHECKING

import cv2
from dotenv import load_dotenv
print("CALIBRATION TOOL LOADED v999")

try:
    from ..modules import db_manager as dbm
    MAIN_DB_PATH = getattr(dbm, 'MAIN_DB_PATH', None)
    ensure_video_source_column = getattr(dbm, 'ensure_video_source_column', None)
    get_run_video_info = getattr(dbm, 'get_run_video_info', None)
    
    # Also for video_path_resolver if needed, but keeping it simple
    from ..modules import video_path_resolver as vpr
    collect_video_candidates = getattr(vpr, 'collect_video_candidates', None)

except ImportError:
    MAIN_DB_PATH = None
    ensure_video_source_column = None
    get_run_video_info = None
    collect_video_candidates = None

if get_run_video_info is None:
    def get_run_video_info(run_id, upload_folder): return None

if TYPE_CHECKING:  # pragma: no cover - type hinting only
    import numpy as np
    from ..modules.manual_metrics import LaneLineSet

load_dotenv()

DEFAULT_KNOWN_DISTANCE = 8.0
DEFAULT_NUM_INTERVALS = 4
DEFAULT_SCALE_MODE = "vertical"
HYBRID_VERTICAL_MODE = "vertical_ex"
VALID_SCALE_MODES = {"vertical", HYBRID_VERTICAL_MODE, "xy", "homography"}


def sanitize_profile_name(value: Optional[str]) -> str:
    """プロファイル名から英数字と_・-のみを残した安全な文字列を返す。"""
    if not value:
        return ""
    safe = "".join(c for c in value if c.isalnum() or c in ("_", "-"))
    return safe[:100]


def delete_calibration_profile(profile_name: str) -> Tuple[List[int], str]:
    """指定したキャリブレーションプロファイルを削除し、クリアしたRun IDを返す。

    Args:
        profile_name: 削除対象のプロファイル名。

    Returns:
        Tuple[List[int], str]: プロファイルを適用していたRun IDの一覧と削除したファイルのパス。

    Raises:
        ValueError: プロファイル名が空もしくは不正な場合。
        FileNotFoundError: 対象のプロファイルファイルが存在しない場合。
        OSError: ファイル削除時にOSエラーが発生した場合。
    """

    safe_name = sanitize_profile_name(profile_name)
    if not safe_name:
        raise ValueError("削除するプロファイル名が指定されていません。")

    calib_dir = ensure_calibration_dir()
    target_path = os.path.join(calib_dir, f"{safe_name}.json")
    if not os.path.isfile(target_path):
        raise FileNotFoundError(f"プロファイル '{safe_name}' は存在しません。")

    cleared_runs: List[int] = []
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT run_id FROM ProcessLog WHERE calibration_profile = ?",
            (safe_name,),
        )
        cleared_runs = [int(row["run_id"]) for row in cursor.fetchall() if row["run_id"] is not None]
        conn.execute(
            "UPDATE ProcessLog SET calibration_profile = '' WHERE calibration_profile = ?",
            (safe_name,),
        )
        conn.commit()

    os.remove(target_path)
    return cleared_runs, target_path


def ensure_calibration_dir() -> str:
    """キャリブレーション保存用ディレクトリを必ず生成し、その絶対パスを返す。"""
    opt_folder = os.getenv("Opt_files") or os.getenv("OPT_FILES") or "output"
    path = os.path.abspath(os.path.join(opt_folder, "calibrations"))
    os.makedirs(path, exist_ok=True)
    return path


def _atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    """一時ファイルを用いてJSONを書き出し、途中失敗でも破損しないようにする。"""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=directory or None, prefix="calib_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass




def load_calibration_payload(
    run_id: int,
    profile_name: Optional[str],
    calib_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Run IDに紐づくキャリブレーションデータを読み込み、プロファイル指定があれば優先する。"""
    calib_dir = calib_dir or ensure_calibration_dir()
    candidates: List[str] = []
    sanitized = sanitize_profile_name(profile_name)
    if sanitized:
        candidates.append(os.path.join(calib_dir, f"{sanitized}.json"))
    candidates.append(os.path.join(calib_dir, f"calibration_{run_id}.json"))
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except json.JSONDecodeError:
                return None
    return None


def probe_video(video_path: str) -> Dict[str, int]:
    """動画ファイルの総フレーム数と解像度を取得して返す。"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        raise FileNotFoundError(f"動画を開けませんでした: {video_path}")
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    return {"frame_count": frame_count, "width": width, "height": height}


def load_video_frame(
    video_path: str,
    frame_idx: int,
    requested_width: Optional[int] = None,
) -> Optional["np.ndarray"]:
    """指定したフレームを動画から読み込み、BGRのnumpy配列として返す。"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        return None
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if frame_idx < 0:
        frame_idx = 0
    elif total_frames and frame_idx >= total_frames:
        frame_idx = max(total_frames - 1, 0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    success, frame = cap.read()
    cap.release()
    if not success or frame is None:
        return None
    if requested_width and requested_width > 0 and frame.shape[1] != requested_width:
        ratio = requested_width / frame.shape[1]
        height = max(int(frame.shape[0] * ratio), 1)
        frame = cv2.resize(frame, (requested_width, height))
    return frame


def update_run_calibration_profile(run_id: int, profile_name: str) -> None:
    """選択したキャリブレーションプロファイルをProcessLogテーブルへ保存する。"""
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        conn.execute(
            "UPDATE ProcessLog SET calibration_profile = ? WHERE run_id = ?",
            (profile_name, run_id),
        )


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_optional_float(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_point(value: Any) -> Optional[List[int]]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        x = int(round(float(value[0])))
        y = int(round(float(value[1])))
    except (TypeError, ValueError):
        return None
    return [x, y]


def _coerce_polyline(points: Any) -> List[List[int]]:
    if not isinstance(points, (list, tuple)):
        return []
    out: List[List[int]] = []
    for pt in points:
        coerced = _coerce_point(pt)
        if coerced:
            out.append(coerced)
    return out


def _coerce_float_polyline(points: Any) -> List[List[float]]:
    if not isinstance(points, (list, tuple)):
        return []
    result: List[List[float]] = []
    for entry in points:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        try:
            x_val = float(entry[0])
            y_val = float(entry[1])
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(x_val) and math.isfinite(y_val)):
            continue
        result.append([x_val, y_val])
    return result


def _coerce_scale_lines(raw_lines: Any) -> List[List[List[int]]]:
    if not isinstance(raw_lines, (list, tuple)):
        return []
    result: List[List[List[int]]] = []
    for entry in raw_lines:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        p1 = _coerce_point(entry[0])
        p2 = _coerce_point(entry[1])
        if p1 and p2:
            result.append([p1, p2])
    return result


def _coerce_path_points(raw_points: Any) -> List[List[int]]:
    return _coerce_polyline(raw_points)


def _coerce_homography_points(raw_points: Any) -> List[List[int]]:
    points = _coerce_polyline(raw_points)
    return points[:4]


def _simplify_polyline(points: List[List[float]]) -> List[List[float]]:
    simplified: List[List[float]] = []
    prev: Optional[Tuple[float, float]] = None
    for entry in points:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        try:
            x_val = float(entry[0])
            y_val = float(entry[1])
        except (TypeError, ValueError):
            continue
        if prev and abs(prev[0] - x_val) < 1e-6 and abs(prev[1] - y_val) < 1e-6:
            continue
        simplified.append([x_val, y_val])
        prev = (x_val, y_val)
    return simplified if len(simplified) >= 2 else []


def _interpolate_x_on_polyline(
    line: Optional[Sequence[Sequence[object]]],
    target_y: float,
) -> Optional[float]:
    if not line:
        return None
    best_x: Optional[float] = None
    best_diff = float("inf")
    for idx in range(len(line) - 1):
        try:
            x1 = float(line[idx][0])
            y1 = float(line[idx][1])
            x2 = float(line[idx + 1][0])
            y2 = float(line[idx + 1][1])
        except (IndexError, TypeError, ValueError):
            continue
        y_low = min(y1, y2)
        y_high = max(y1, y2)
        if target_y < y_low or target_y > y_high:
            continue
        if y2 == y1:
            continue
        if x2 == x1:
            x_line = x1
        else:
            slope = (x2 - x1) / (y2 - y1)
            x_line = x1 + slope * (target_y - y1)
        diff = abs(target_y - max(min(y1, y2), min(max(y1, y2), target_y)))
        if diff < best_diff:
            best_diff = diff
            best_x = x_line
    return best_x


def _generate_mid_lane_lines(
    left_line: Optional[Sequence[Sequence[object]]],
    center_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
) -> Tuple[List[List[float]], List[List[float]]]:
    if not left_line or not right_line or not center_line:
        return [], []

    y_samples: set[float] = set()
    for line in (left_line, center_line, right_line):
        for pt in line:
            try:
                y_value = float(pt[1])
            except (TypeError, ValueError, IndexError):
                continue
            if math.isfinite(y_value):
                y_samples.add(y_value)

    if not y_samples:
        return [], []

    y_min = min(y_samples)
    y_max = max(y_samples)
    if math.isfinite(y_min) and math.isfinite(y_max) and y_max > y_min:
        sample_count = max(10, min(80, len(y_samples) * 3))
        step = (y_max - y_min) / (sample_count - 1)
        for idx in range(sample_count):
            y_samples.add(y_min + step * idx)

    sorted_y = sorted(y_samples)
    left_mid: List[List[float]] = []
    right_mid: List[List[float]] = []

    for y_val in sorted_y:
        center_x = _interpolate_x_on_polyline(center_line, y_val)
        if center_x is None:
            continue
        left_x = _interpolate_x_on_polyline(left_line, y_val)
        if left_x is not None:
            left_mid.append([left_x + (center_x - left_x) * 0.5, y_val])
        right_x = _interpolate_x_on_polyline(right_line, y_val)
        if right_x is not None:
            right_mid.append([right_x + (center_x - right_x) * 0.5, y_val])

    left_mid = _simplify_polyline(left_mid)
    right_mid = _simplify_polyline(right_mid)
    return left_mid, right_mid


def _compute_path_pixel_length(points: List[List[int]]) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    for idx in range(len(points) - 1):
        x1, y1 = points[idx]
        x2, y2 = points[idx + 1]
        total += math.hypot(x2 - x1, y2 - y1)
    return float(total)


def _prepare_scale_payload(
    scale_raw: Dict[str, Any],
    scale_mode: str,
    scale_lines: List[List[List[int]]],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    known_distance = _to_float(scale_raw.get("known_distance_m"), DEFAULT_KNOWN_DISTANCE)
    num_intervals = _to_int(scale_raw.get("num_intervals"), DEFAULT_NUM_INTERVALS)
    if num_intervals <= 0:
        num_intervals = 1
    payload: Dict[str, Any] = {
        "mode": scale_mode,
        "lines": scale_lines,
        "known_distance_m": known_distance,
        "num_intervals": num_intervals,
    }
    if scale_mode in {"vertical", HYBRID_VERTICAL_MODE}:
        if known_distance <= 0:
            return None, "縦方向スケールでは既知距離を0より大きい値で指定してください。"
        if scale_mode == "vertical" and len(scale_lines) < 2:
            return None, "縦方向スケールには目盛り線を2本以上描いてください。"
    elif scale_mode == "xy":
        path_payload = scale_raw.get("path") or {}
        path_points = _coerce_path_points(path_payload.get("points"))
        total_distance = _to_float(path_payload.get("total_distance_m"))
        if len(path_points) < 2 or total_distance <= 0:
            return None, "参照用の経路を描き、実際の距離を入力してください。"
        pixel_length = _to_float(
            path_payload.get("pixel_length"),
            _compute_path_pixel_length(path_points),
        )
        payload["path"] = {
            "points": path_points,
            "total_distance_m": total_distance,
            "pixel_length": pixel_length,
        }
    elif scale_mode == "homography":
        homography_payload = scale_raw.get("homography") or {}
        image_points = _coerce_homography_points(homography_payload.get("image_points"))
        width_m = _to_float(homography_payload.get("width_m"))
        length_m = _to_float(homography_payload.get("length_m"))
        if len(image_points) != 4 or width_m <= 0 or length_m <= 0:
            return None, "画像上の4点と実寸の幅・長さを入力してください。"
        interval_m = _to_float(homography_payload.get("interval_m"))
        payload["homography"] = {
            "image_points": image_points,
            "width_m": width_m,
            "length_m": length_m,
        }
        if interval_m > 0:
            payload["homography"]["interval_m"] = interval_m

    return payload, None


def prepare_save_payload(
    run_id: int,
    raw_payload: Dict[str, Any],
) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    """リクエストデータを検証し、保存用JSONペイロードを構築する。"""
    if not isinstance(raw_payload, dict):
        return None, None, "リクエストの形式が正しくありません。"

    profile_name = sanitize_profile_name(raw_payload.get("profile_name"))
    if not profile_name:
        return None, None, "プロファイル名には英数字と「_」「-」のみ使用できます。"

    lines_raw = raw_payload.get("lines") or {}
    left_line = _coerce_polyline(lines_raw.get("left_white_line"))
    right_line = _coerce_polyline(lines_raw.get("right_white_line"))
    center_line = _coerce_polyline(lines_raw.get("center_line"))
    left_mid_manual = _coerce_float_polyline(lines_raw.get("left_mid_line"))
    right_mid_manual = _coerce_float_polyline(lines_raw.get("right_mid_line"))

    scale_raw = raw_payload.get("scale") or {}
    scale_mode = (scale_raw.get("mode") or DEFAULT_SCALE_MODE).lower()
    if scale_mode not in VALID_SCALE_MODES:
        scale_mode = DEFAULT_SCALE_MODE
    scale_lines = _coerce_scale_lines(scale_raw.get("lines"))

    left_mid_line: List[List[float]] = []
    right_mid_line: List[List[float]] = []

    if scale_mode == HYBRID_VERTICAL_MODE:
        if not left_line or not right_line or not center_line:
            return None, None, "改型Y軸スケールでは左右と中央の線を描いてください。"
        if left_mid_manual and right_mid_manual:
            left_mid_line = left_mid_manual
            right_mid_line = right_mid_manual
        else:
            left_mid_line, right_mid_line = _generate_mid_lane_lines(
                left_line,
                center_line,
                right_line,
            )
        if len(left_mid_line) < 2 or len(right_mid_line) < 2:
            return None, None, "改型Y軸スケールの中間線を生成できませんでした。線の描画を見直してください。"

    if scale_mode == "vertical":
        if not left_line or not right_line:
            return None, None, "縦方向スケールでは左右の境界線を描いてください。"

    scale_payload, scale_error = _prepare_scale_payload(scale_raw, scale_mode, scale_lines)
    if scale_error:
        return None, None, scale_error

    payload: Dict[str, Any] = {
        "run_id": run_id,
        "source_frame": _to_int(raw_payload.get("source_frame"), 0),
        "count_lines": raw_payload.get("count_lines") or [],
        "lines": {
            "left_white_line": left_line,
            "right_white_line": right_line,
            "center_line": center_line,
        },
        "scale": scale_payload,
    }
    if left_mid_line:
        payload["lines"]["left_mid_line"] = left_mid_line
    if right_mid_line:
        payload["lines"]["right_mid_line"] = right_mid_line
    return profile_name, payload, None


def save_calibration_payload(
    profile_name: str,
    run_id: int,
    payload: Dict[str, Any],
    calib_dir: Optional[str] = None,
) -> str:
    """キャリブレーションペイロードを保存し、メインファイルのパスを返す。"""
    calib_dir = calib_dir or ensure_calibration_dir()
    main_path = os.path.join(calib_dir, f"{profile_name}.json")
    run_specific_path = os.path.join(calib_dir, f"calibration_{run_id}.json")
    _atomic_write_json(main_path, payload)
    _atomic_write_json(run_specific_path, payload)
    return os.path.abspath(main_path)


def prepare_lane_test_lines(
    raw_payload: Mapping[str, Any],
) -> Tuple[Optional[LaneLineSet], Optional[str]]:
    """白線距離テスト用に描画データからレーン線情報を構築する。"""

    if not isinstance(raw_payload, Mapping):
        return None, "リクエストの形式が正しくありません。"

    lines_raw = raw_payload.get("lines") or {}
    if not isinstance(lines_raw, Mapping):
        lines_raw = {}

    left_line = _coerce_polyline(lines_raw.get("left_white_line"))
    right_line = _coerce_polyline(lines_raw.get("right_white_line"))
    center_line = _coerce_polyline(lines_raw.get("center_line"))

    left_mid_line = _coerce_float_polyline(lines_raw.get("left_mid_line"))
    right_mid_line = _coerce_float_polyline(lines_raw.get("right_mid_line"))
    left_inner_line = _coerce_float_polyline(lines_raw.get("left_inner_line"))
    right_inner_line = _coerce_float_polyline(lines_raw.get("right_inner_line"))

    scale_raw = raw_payload.get("scale") or {}
    if not isinstance(scale_raw, Mapping):
        scale_raw = {}
    scale_mode = (scale_raw.get("mode") or DEFAULT_SCALE_MODE).lower()
    if scale_mode not in VALID_SCALE_MODES:
        scale_mode = DEFAULT_SCALE_MODE

    if not left_line or not right_line:
        return None, "左右の白線を描画してからテストを実行してください。"

    if scale_mode == HYBRID_VERTICAL_MODE:
        if not center_line:
            return None, "改型Y軸スケールでは中央線も描画してください。"
        if not left_mid_line or not right_mid_line:
            left_mid_line, right_mid_line = _generate_mid_lane_lines(
                left_line,
                center_line,
                right_line,
            )
        if len(left_mid_line) < 2 or len(right_mid_line) < 2:
            return None, "改型Y軸スケールの中間線を生成できませんでした。"

    lines_payload: Dict[str, Any] = {
        "left_white_line": left_line,
        "right_white_line": right_line,
    }
    if center_line:
        lines_payload["center_line"] = center_line
    if left_mid_line:
        lines_payload["left_mid_line"] = left_mid_line
    if right_mid_line:
        lines_payload["right_mid_line"] = right_mid_line
    if left_inner_line:
        lines_payload["left_inner_line"] = left_inner_line
    if right_inner_line:
        lines_payload["right_inner_line"] = right_inner_line

    from ..modules.manual_metrics import load_white_lines
    lane_lines = load_white_lines({"lines": lines_payload})
    if not lane_lines.left or not lane_lines.right:
        return None, "白線情報を正しく解釈できませんでした。"
    return lane_lines, None


def calculate_lane_test_distances(
    lane_lines: LaneLineSet,
    points: Sequence[Any],
) -> List[Dict[str, Any]]:
    """測定点のリストに対して白線距離とスケール情報を計算する。"""

    results: List[Dict[str, Any]] = []
    if not lane_lines.left or not lane_lines.right:
        return results

    left_line = lane_lines.left
    right_line = lane_lines.right
    center_line = lane_lines.center
    left_inner = lane_lines.left_inner
    right_inner = lane_lines.right_inner

    for idx, raw_point in enumerate(points or []):
        entry: Dict[str, Any] = {"index": idx}
        x_val: Optional[float] = None
        y_val: Optional[float] = None

        if isinstance(raw_point, Mapping):
            x_val = _to_optional_float(raw_point.get("x"))
            y_val = _to_optional_float(raw_point.get("y"))
        elif isinstance(raw_point, (list, tuple)) and len(raw_point) >= 2:
            x_val = _to_optional_float(raw_point[0])
            y_val = _to_optional_float(raw_point[1])

        entry["x"] = x_val
        entry["y"] = y_val

        if x_val is None or y_val is None:
            entry["error"] = "測定点の座標が無効です。"
            results.append(entry)
            continue

        from ..modules.manual_metrics import lane_scale_details_at_y
        details = lane_scale_details_at_y(
            y_val,
            left_line,
            right_line,
            center_line=center_line,
            left_inner_line=left_inner,
            right_inner_line=right_inner,
        )
        entry["details"] = details.to_dict()

        if not details.is_available:
            entry["error"] = "指定した高さで白線間隔を取得できません。"
            results.append(entry)
            continue

        left_point = details.left_point
        right_point = details.right_point

        left_x = _to_optional_float(left_point[0]) if left_point else None
        right_x = _to_optional_float(right_point[0]) if right_point else None

        left_px = abs(x_val - left_x) if (left_x is not None) else None
        right_px = abs(right_x - x_val) if (right_x is not None) else None

        lane_width_px = details.lane_width_px if details.lane_width_px else None
        lane_width_m = details.lane_width_m if details.lane_width_m else None
        lane_width_cm = (
            lane_width_m * 100.0 if lane_width_m is not None else None
        )

        centimeters_per_pixel = details.centimeters_per_pixel

        left_cm: Optional[float] = None
        right_cm: Optional[float] = None

        if (
            lane_width_px
            and lane_width_px > 0
            and lane_width_cm is not None
            and left_px is not None
        ):
            left_cm = (lane_width_cm * left_px) / lane_width_px
        elif centimeters_per_pixel and left_px is not None:
            left_cm = centimeters_per_pixel * left_px

        if (
            lane_width_px
            and lane_width_px > 0
            and lane_width_cm is not None
            and right_px is not None
        ):
            right_cm = (lane_width_cm * right_px) / lane_width_px
        elif centimeters_per_pixel and right_px is not None:
            right_cm = centimeters_per_pixel * right_px

        within_lane: Optional[bool] = None
        point_fraction: Optional[float] = None
        if (
            lane_width_px
            and lane_width_px > 0
            and left_px is not None
            and right_px is not None
        ):
            within_lane = (
                0.0 <= left_px <= lane_width_px
                and 0.0 <= right_px <= lane_width_px
            )
            point_fraction = left_px / lane_width_px if lane_width_px else None

        entry.update(
            {
                "left_distance_px": left_px,
                "right_distance_px": right_px,
                "left_distance_cm": left_cm,
                "right_distance_cm": right_cm,
                "lane_width_px": lane_width_px,
                "lane_width_cm": lane_width_cm,
                "centimeters_per_pixel": centimeters_per_pixel,
                "within_lane": within_lane,
                "point_fraction": point_fraction,
            }
        )
        results.append(entry)

    return results


def apply_calibration_profile(run_id: int, profile_name: str) -> str:
    """指定したRun IDにキャリブレーションプロファイルを適用する（後方互換用）。

    Args:
        run_id: 対象のRun ID
        profile_name: 適用するプロファイル名

    Returns:
        str: 適用されたプロファイル名
    """
    safe_name = sanitize_profile_name(profile_name)
    update_run_calibration_profile(run_id, safe_name)
    return safe_name
