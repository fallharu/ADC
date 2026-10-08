# -*- coding: utf-8 -*-
"""
役割: 全ての解析結果を描画した動画を生成する（完全修正版）
- 安全なSQL（? プレースホルダ）
- 出力フォルダの自動作成
- 例外/中断時でも確実に VideoCapture/DB をクローズ
- FPS は DB > 動画ヘッダ > 30 の優先順位
- 車両ボックス選択を堅牢化（class_name 優先→面積最大）
- 日本語ラベルは PIL(TrueType) で描画（FONT_PATH 未設定時は英数字のみ）
- キャリブレーション線は DB(優先) → JSON(後方互換) の順で読み込み
- frame_num の 0/1 始まり差異を自動吸収 (オフセット判定)
"""

import os
import sqlite3
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Dict, List, Tuple, Optional, Set, Iterable
import pandas as pd
import cv2
from tqdm import tqdm
from dotenv import load_dotenv
import json
import numpy as np
from collections import defaultdict, deque
from pathlib import Path
from copy import deepcopy

# --- PILは日本語ラベル対策で利用。未導入でも動くようにガード ---
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

from .db_manager import MAIN_DB_PATH, configure_connection
from .perf_utils import resolve_worker_count
from .video_path_resolver import collect_video_candidates

# --- 色やスタイルの定義（BGR） ---
VEHICLE_BOX_COLOR = (255, 178, 50)   # 水色：通常車両
OVERTAKE_COLOR    = (0, 255, 0)      # 緑：追い越しフラグON
TEXT_COLOR        = (255, 255, 255)  # 白：ラベル文字
TRACE_COLOR       = (255, 0, 0)      # 赤：トレース点（軌跡）
TIRE_COLOR        = (0, 255, 0)      # 緑：タイヤ
LINE_COLOR        = (0, 255, 255)    # シアン：キャリブレーション線
APPROACH_LINE_COLOR = (40, 200, 255)   # 接近距離ライン
CLEARANCE_LINE_HIGHLIGHT_COLOR = (0, 0, 255)  # 離角距離ハイライト
APPROACH_LINE_THICKNESS = 2
CLEARANCE_HIGHLIGHT_WINDOW = 5  # 離角距離の前後フレーム数
TRACE_HISTORY_FRAMES = 10
TRACE_MIN_ALPHA = 0.25
TRACE_MAX_ALPHA = 1.0
TRACE_POINT_RADIUS = 4

# --- 車両とみなす class_name 候補（英小文字で比較） ---
VEHICLE_CLASS_CANDIDATES = {'car', 'bicycle', 'motorcycle', 'bus', 'truck', 'vehicle'}

FONT_SEARCH_PATTERNS = ('*.ttf', '*.otf')
DEFAULT_FONT_SIZE = 18

DEFAULT_VIDEO_OPTIONS = {
    'show_vehicle_box': True,
    'show_tire_boxes': True,
    'show_trace': True,
    'show_measurement': True,
    'show_approach_lines': True,
    'show_lane_left': True,
    'show_lane_right': True,
    'show_lane_center': True,
    'label_group_id': True,
    'label_speed': True,
    'label_lane_distance': True,
    'label_approach': True,
    'label_clearance': True,
    'label_direction': True,
    'label_overtake': True,
    'label_acceleration': True,
    'font_size': DEFAULT_FONT_SIZE,
    'font_path': None,
}


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "off", "no"}


def _gpu_video_supported() -> bool:
    if not hasattr(cv2, "cuda") or not hasattr(cv2, "cudacodec"):
        return False
    try:
        return cv2.cuda.getCudaEnabledDeviceCount() > 0
    except Exception:
        return False


class _VideoWriterWrapper:
    def __init__(self, writer, *, use_gpu: bool) -> None:
        self._writer = writer
        self._use_gpu = use_gpu
        self._gpu_frame = cv2.cuda_GpuMat() if use_gpu and hasattr(cv2, "cuda") else None

    def write(self, frame: np.ndarray) -> None:
        if self._use_gpu and self._gpu_frame is not None:
            try:
                self._gpu_frame.upload(frame)
                self._writer.write(self._gpu_frame)
                return
            except Exception:
                # GPU書き込みに失敗した場合はCPU経由でフォールバック
                self._use_gpu = False
        self._writer.write(frame)

    def release(self) -> None:
        if self._writer is not None:
            release = getattr(self._writer, "release", None)
            if callable(release):
                release()
        self._writer = None
        self._gpu_frame = None


def _default_fonts_dir_candidates() -> List[Path]:
    repo_root = Path(__file__).resolve().parents[2]
    candidates: List[Path] = []
    env_dir = os.getenv('ADC_FONTS_DIR')
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.append(repo_root / 'fonts')
    candidates.append(Path.cwd() / 'fonts')
    return candidates


def discover_font_files() -> List[Dict[str, str]]:
    """フォント候補の一覧を取得する。"""
    results: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for base_dir in _default_fonts_dir_candidates():
        try:
            resolved_dir = base_dir.resolve()
        except Exception:
            continue
        if not resolved_dir.is_dir():
            continue
        for pattern in FONT_SEARCH_PATTERNS:
            for path in sorted(resolved_dir.glob(pattern)):
                try:
                    resolved = path.resolve()
                except Exception:
                    continue
                resolved_str = str(resolved)
                if resolved_str in seen:
                    continue
                seen.add(resolved_str)
                results.append({
                    'path': resolved_str,
                    'name': path.stem,
                    'display_name': path.name,
                    'directory': str(resolved_dir),
                })
    return results


def _coerce_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {'1', 'true', 'yes', 'on'}:
            return True
        if lowered in {'0', 'false', 'no', 'off'}:
            return False
    return bool(value)


def normalize_video_options(
    options: Optional[dict],
    available_fonts: Optional[Iterable[str]] = None,
) -> Dict[str, object]:
    """動画描画オプションを既定値とマージしつつ正規化する。"""
    normalized = deepcopy(DEFAULT_VIDEO_OPTIONS)
    if options is None:
        options = {}

    if available_fonts is not None:
        font_candidates = [str(Path(p).resolve()) for p in available_fonts]
    else:
        font_candidates = [entry['path'] for entry in discover_font_files()]

    env_font_path = os.getenv('FONT_PATH')
    if env_font_path:
        try:
            env_resolved = str(Path(env_font_path).resolve())
        except Exception:
            env_resolved = None
        if env_resolved and env_resolved not in font_candidates:
            font_candidates.insert(0, env_resolved)

    font_set = set(font_candidates)
    default_font = font_candidates[0] if font_candidates else None

    bool_keys = [key for key in normalized if key.startswith('show_') or key.startswith('label_')]
    for key in bool_keys:
        normalized[key] = _coerce_bool(options.get(key), normalized[key])

    font_size_value = options.get('font_size', normalized['font_size'])
    try:
        font_size = float(font_size_value)
    except (TypeError, ValueError):
        font_size = float(normalized['font_size'])
    font_size = max(8.0, min(96.0, font_size))
    normalized['font_size'] = font_size

    requested_font = options.get('font_path')
    if isinstance(requested_font, str):
        requested_font = requested_font.strip()
    else:
        requested_font = None

    selected_font: Optional[str] = None
    if requested_font:
        try:
            resolved_request = str(Path(requested_font).resolve())
        except Exception:
            resolved_request = ''
        if resolved_request and resolved_request in font_set:
            selected_font = resolved_request

    if not selected_font:
        selected_font = default_font

    normalized['font_path'] = selected_font

    return normalized


def _safe_float(x) -> Optional[float]:
    """数値らしき値を float にして返す。不可なら None。"""
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _is_finite_number(x) -> bool:
    """有限実数かどうかの安全判定。"""
    try:
        return x is not None and np.isfinite(float(x))
    except Exception:
        return False


def _safe_int(x) -> Optional[int]:
    """有限実数であれば int にして返す。"""
    if _is_finite_number(x):
        try:
            return int(float(x))
        except Exception:
            return None
    return None


class VideoGenerator:
    """
    解析データからアノテーション付き動画を生成するためのクラス
    - __init__ で DB/設定のロード（線情報も事前ロード）
    - run() でフレームループして描画＋出力
    """

    def __init__(self, run_id: int, options: Optional[dict] = None):
        self.run_id = run_id

        load_dotenv()
        self.prefer_gpu = _env_flag("VIDEO_GPU_ENABLED", True)
        self.conn = sqlite3.connect(MAIN_DB_PATH)
        configure_connection(self.conn, mode="read")
        self.use_gpu_writer = self.prefer_gpu and _gpu_video_supported()

        self.cv_font = cv2.FONT_HERSHEY_SIMPLEX

        font_entries = discover_font_files()
        self.available_fonts = [Path(entry['path']).resolve() for entry in font_entries]
        self.options = normalize_video_options(options, self.available_fonts)

        self.render_workers = resolve_worker_count(
            "VIDEO_RENDER_WORKERS",
            fallback=min(8, (os.cpu_count() or 2)),
            max_workers=16,
        )

        self.font_size = float(self.options.get('font_size', DEFAULT_FONT_SIZE))
        self.cv_font_scale = max(0.3, (self.font_size / DEFAULT_FONT_SIZE) * 0.5)
        self.cv_font_thickness = max(1, int(round(self.cv_font_scale * 2)))

        self.ttf_path = self.options.get('font_path') or ''
        self.ttf: Optional['ImageFont.FreeTypeFont'] = None
        if PIL_AVAILABLE and self.ttf_path and os.path.exists(self.ttf_path):
            try:
                self.ttf = ImageFont.truetype(self.ttf_path, int(round(self.font_size)))
            except Exception:
                self.ttf = None

        self.label_flags = {
            key: bool(self.options.get(key, False))
            for key in DEFAULT_VIDEO_OPTIONS
            if key.startswith('label_')
        }
        self.labels_enabled = any(self.label_flags.values())

        self.show_vehicle_box = bool(self.options.get('show_vehicle_box', True))
        self.show_tire_boxes = bool(self.options.get('show_tire_boxes', True))
        self.show_trace = bool(self.options.get('show_trace', True))
        self.show_measurement = bool(self.options.get('show_measurement', True))
        self.show_approach_lines = bool(self.options.get('show_approach_lines', True))
        self.show_lane_left = bool(self.options.get('show_lane_left', True))
        self.show_lane_right = bool(self.options.get('show_lane_right', True))
        self.show_lane_center = bool(self.options.get('show_lane_center', True))

        self._load_core_data()
        self._preprocess_data()
        self._load_lines()
        self._prepare_calibration_overlay()

    # ---------------------------------------------------------------------
    # データロード
    # ---------------------------------------------------------------------

    # ---------------------------------------------------------------------
    # データロード
    # ---------------------------------------------------------------------
    def _load_core_data(self) -> None:
        """DBから Detection / Video / 出力関連情報を読み取る（SQLはプレースホルダで安全化）。"""
        print("データの読み込みを開始...")

        # --- Detection + Class（車種名などを使えるようにしておく） ---
        self.detections_df = pd.read_sql_query(
            """
            SELECT d.*, c.class_name
            FROM Detection d
            LEFT JOIN Class c ON d.class_id = c.class_id
            WHERE d.run_id = ?
            """,
            self.conn, params=(self.run_id,)
        )

        # --- 出力先や元動画・FPS（ProcessLog -> Video） ---
        video_info_df = pd.read_sql_query(
            """
            SELECT p.output_folder, v.filename, v.fps
            FROM ProcessLog p
            JOIN Video v ON p.video_id = v.video_id
            WHERE p.run_id = ?
            """,
            self.conn, params=(self.run_id,)
        )
        if video_info_df.empty:
            raise RuntimeError(f"[VideoGenerator] run_id={self.run_id} の動画情報が見つかりません。")
        vi = video_info_df.iloc[0]

        # 出力先フォルダは存在しないと失敗するので先に作成
        self.output_folder = str(vi["output_folder"])
        os.makedirs(self.output_folder, exist_ok=True)

        # 元動画ファイル名と DB由来のFPS（Noneの可能性あり）
        self.original_video_filename = str(vi["filename"])
        self.db_fps = _safe_float(vi["fps"])

        # --- 旧来の JSON キャリブ設定（DBに無い場合の後方互換用） ---
        opt_folder = os.getenv("Opt_files", "output")
        self.calibration_json_path = os.path.join(opt_folder, "calibrations", f"calibration_{self.run_id}.json")
        self.calib_json_data: Optional[Dict] = None
        if os.path.exists(self.calibration_json_path):
            try:
                with open(self.calibration_json_path, "r", encoding="utf-8") as f:
                    self.calib_json_data = json.load(f)
            except Exception:
                self.calib_json_data = None  # JSON壊れ対策。無いものとして扱う

        print("DB/設定の読み込み完了。")

    def _preprocess_data(self) -> None:
        """
        描画しやすいよう、Detectionを
        frame_num → group_id → [dict(row), ...] の二段ディクショナリへ整形。
        """
        self.data_by_frame: Dict[int, Dict[int, List[dict]]] = defaultdict(lambda: defaultdict(list))
        clearance_events: Dict[tuple[int, int], set[int]] = defaultdict(set)

        # DataFrame から1行ずつ dict 化して格納
        for _, row in self.detections_df.iterrows():
            frame_num = row.get("frame_num")
            group_id = row.get("group_id")
            partner_group = row.get("approach_partner_group_id")
            if pd.isna(frame_num) or pd.isna(group_id):
                continue

            fn = _safe_int(frame_num)
            gid = _safe_int(group_id)
            if fn is None or gid is None:
                continue

            row_dict = row.to_dict()
            self.data_by_frame[fn][gid].append(row_dict)

            partner_gid = _safe_int(partner_group)
            if partner_gid is None:
                continue

            clearance_px = row.get("clearance_distance_px")
            if pd.notna(clearance_px):
                pair_key = tuple(sorted((gid, partner_gid)))
                clearance_events[pair_key].add(fn)

        self.clearance_event_frames = {key: sorted(values) for key, values in clearance_events.items()}

    def _load_lines(self) -> None:
        """
        キャリブレーション線のロード。
        1) DB テーブル `CalibrationLines(run_id, line_type, points_json)` を**優先**
           - points_json: [[x,y], [x,y], ...] の配列（自由曲線/折れ線）
        2) 1) が無ければ JSON ファイル（後方互換: calib_json_data["lines"]）
        結果は描画用の `self.calib_polylines`（np.int32 配列のリスト）に格納。
        """
        self.calib_polylines: List[np.ndarray] = []

        # --- まず DB を試す ---
        try:
            # テーブルが無い場合は OperationalError が起き得る
            df = pd.read_sql_query(
                "SELECT line_type, points_json FROM CalibrationLines WHERE run_id = ?",
                self.conn, params=(self.run_id,)
            )
            for _, r in df.iterrows():
                pts = r.get("points_json")
                if isinstance(pts, str):
                    try:
                        pts = json.loads(pts)
                    except Exception:
                        pts = None
                if pts and isinstance(pts, list) and len(pts) >= 2:
                    arr = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
                    self.calib_polylines.append(arr)
        except Exception:
            # 無ければ次の JSON フォールバックへ
            pass

        # --- DBに何も無ければ JSON（後方互換） ---
        if not self.calib_polylines and self.calib_json_data and self.calib_json_data.get("lines"):
            for line_points in self.calib_json_data["lines"].values():
                if line_points and len(line_points) >= 2:
                    arr = np.array(line_points, dtype=np.int32).reshape((-1, 1, 2))
                    self.calib_polylines.append(arr)

    def _prepare_calibration_overlay(self) -> None:
        lines_info = (self.calib_json_data or {}).get('lines') or {}
        self.scale_info = (self.calib_json_data or {}).get('scale') or {}
        self.scale_mode = (self.scale_info.get('mode') or 'vertical').lower()

        self.left_lane_points = self._points_to_array(lines_info.get('left_white_line'))
        self.right_lane_points = self._points_to_array(lines_info.get('right_white_line'))
        self.center_lane_points = self._points_to_array(lines_info.get('center_line'))

        self.left_lane_poly = self._convert_to_polyline(self.left_lane_points)
        self.right_lane_poly = self._convert_to_polyline(self.right_lane_points)
        self.center_lane_poly = self._convert_to_polyline(self.center_lane_points)

        self.scale_line_segments = []
        for seg in (self.scale_info.get('lines') or []):
            arr = self._points_to_array(seg)
            if arr is not None:
                poly = self._convert_to_polyline(arr)
                if poly is not None:
                    self.scale_line_segments.append(poly)

        homography = self.scale_info.get('homography') or {}
        image_points = homography.get('image_points')
        self.homography_polygon = None
        if image_points and len(image_points) == 4:
            try:
                self.homography_polygon = np.array(image_points, dtype=np.int32).reshape((-1, 1, 2))
            except Exception:
                self.homography_polygon = None

        self.homography_scale_segments = []
        if self.scale_mode == 'homography':
            for seg in (self.scale_info.get('lines') or []):
                arr = self._points_to_array(seg)
                if arr is not None:
                    poly = self._convert_to_polyline(arr)
                    if poly is not None:
                        self.homography_scale_segments.append(poly)
        self.white_line_color = (255, 255, 255)
        self.center_line_color = (180, 180, 180)
        self.scale_line_color = (0, 255, 255)

    def _points_to_array(self, points) -> Optional[np.ndarray]:
        if not points or len(points) < 2:
            return None
        try:
            arr = np.array(points, dtype=float)
        except Exception:
            return None
        if arr.ndim != 2 or arr.shape[1] != 2:
            return None
        return arr

    def _convert_to_polyline(self, arr: Optional[np.ndarray]) -> Optional[np.ndarray]:
        if arr is None:
            return None
        try:
            return arr.reshape((-1, 1, 2)).astype(np.int32)
        except Exception:
            return None

    def _interpolate_lane_x(self, points: Optional[np.ndarray], y: int) -> Optional[float]:
        if points is None or len(points) < 2:
            return None
        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]
            if (y1 <= y <= y2) or (y2 <= y <= y1):
                if y2 == y1:
                    return float(x1)
                ratio = (y - y1) / (y2 - y1)
                return float(x1 + ratio * (x2 - x1))
        return None

    def _get_measure_point(
        self,
        data: dict,
        tires: Optional[List[dict]] = None,
    ) -> Optional[Tuple[int, int]]:
        cached = data.get("_measure_point")
        if isinstance(cached, (tuple, list)) and len(cached) == 2:
            try:
                point = (int(cached[0]), int(cached[1]))
                data["_measure_point"] = point
                return point
            except Exception:
                pass

        if tires:
            best_point: Optional[Tuple[int, int]] = None
            best_score: Optional[Tuple[float, float]] = None
            for tire in tires:
                x2 = _safe_float(tire.get('x2'))
                y2 = _safe_float(tire.get('y2'))
                if not _is_finite_number(x2) or not _is_finite_number(y2):
                    continue
                score = (float(y2), float(x2))
                if best_score is None or score > best_score:
                    best_score = score
                    best_point = (int(float(x2)), int(float(y2)))
            if best_point is not None:
                data['_measure_point'] = best_point
                return best_point

        x2 = _safe_float(data.get('x2'))
        y2 = _safe_float(data.get('y2'))
        if _is_finite_number(x2) and _is_finite_number(y2):
            point = (int(float(x2)), int(float(y2)))
            data['_measure_point'] = point
            return point
        return None

    def _draw_measurement_annotations(self, frame: np.ndarray, data: dict) -> None:
        point = self._get_measure_point(data)
        if point is None:
            return
        cv2.circle(frame, point, TRACE_POINT_RADIUS, TRACE_COLOR, -1, cv2.LINE_AA)

        left_x = self._interpolate_lane_x(self.left_lane_points, point[1])
        right_x = self._interpolate_lane_x(self.right_lane_points, point[1])

        if left_x is not None and self.show_lane_left:
            left_pt = (int(left_x), point[1])
            cv2.line(frame, point, left_pt, (200, 200, 200), 1, cv2.LINE_AA)
            cv2.circle(frame, left_pt, 3, self.white_line_color, -1, cv2.LINE_AA)
            left_dist = _safe_float(data.get('l_line_distance'))
            if _is_finite_number(left_dist):
                label = f"L:{float(left_dist):.1f}px"
                cv2.putText(frame, label, (min(point[0], left_pt[0]), point[1] - 6), self.cv_font, 0.45, (220, 220, 220), 1, cv2.LINE_AA)

        if right_x is not None and self.show_lane_right:
            right_pt = (int(right_x), point[1])
            cv2.line(frame, point, right_pt, (200, 200, 200), 1, cv2.LINE_AA)
            cv2.circle(frame, right_pt, 3, self.white_line_color, -1, cv2.LINE_AA)
            right_dist = _safe_float(data.get('r_line_distance'))
            if _is_finite_number(right_dist):
                label = f"R:{float(right_dist):.1f}px"
                cv2.putText(frame, label, (max(point[0], right_pt[0]) - 80, point[1] - 6), self.cv_font, 0.45, (220, 220, 220), 1, cv2.LINE_AA)

    def _prepare_frame_payload(
        self,
        frame_number: int,
        trace_history: Dict[int, deque],
    ) -> Tuple[Dict[int, dict], Dict[int, List[dict]], Dict[int, List[Tuple[int, Tuple[int, int]]]]]:
        frame_groups = self.data_by_frame.get(frame_number, {})
        selected_vehicles: Dict[int, dict] = {}
        group_tires: Dict[int, List[dict]] = {}

        for detections in frame_groups.values():
            if not detections:
                continue
            vehicle = self._pick_vehicle(detections)
            if vehicle is None:
                continue
            gid = _safe_int(vehicle.get("group_id"))
            if gid is None:
                continue
            
            selected_vehicles[gid] = vehicle
            group_tires[gid] = [
                d for d in detections
                if str(d.get("model_name", "")).lower() == "best"
            ]

        used_track_ids: Set[int] = set()
        for gid, vehicle in selected_vehicles.items():
            measure_point = self._get_measure_point(vehicle, group_tires.get(gid))
            if measure_point is None:
                continue
            track_id = _safe_int(vehicle.get("track_id"))
            if track_id is None:
                continue
            history = trace_history[track_id]
            history.append((frame_number, measure_point))
            while history and (
                frame_number - history[0][0] > TRACE_HISTORY_FRAMES
                or len(history) > TRACE_HISTORY_FRAMES
            ):
                history.popleft()
            used_track_ids.add(track_id)

        trace_snapshot = {track_id: list(trace_history[track_id]) for track_id in used_track_ids}
        return selected_vehicles, group_tires, trace_snapshot

    def _render_frame(
        self,
        frame: np.ndarray,
        frame_number: int,
        selected_vehicles: Dict[int, dict],
        group_tires: Dict[int, List[dict]],
        trace_snapshot: Dict[int, List[Tuple[int, Tuple[int, int]]]],
    ) -> np.ndarray:
        self._draw_calibration_lines(frame)
        if selected_vehicles:
            self._draw_approach_lines(frame, frame_number, selected_vehicles)
            trace_history_snapshot: Dict[int, deque] = {
                track_id: deque(history)
                for track_id, history in trace_snapshot.items()
            }
            for gid in sorted(selected_vehicles.keys()):
                vehicle = selected_vehicles[gid]
                tires = group_tires.get(gid, [])
                self._draw_vehicle_elements(frame, vehicle, tires, trace_history_snapshot)
        return frame

    def _try_create_gpu_writer(self, output_path: str, frame_width: int, frame_height: int):
        if not self.use_gpu_writer:
            return None
        try:
            color_format = getattr(cv2.cudacodec, "COLOR_FORMAT_BGR", 0)
            writer = cv2.cudacodec.createVideoWriter(
                output_path,
                (frame_width, frame_height),
                self.fps,
                color_format,
            )
            print("[VideoGenerator] GPUエンコードを使用して動画を書き出します。")
            return writer
        except Exception as exc:
            print(f"[VideoGenerator] GPUエンコード初期化に失敗: {exc}")
            self.use_gpu_writer = False
            return None

    def _create_video_writer(self, output_path: str, frame_width: int, frame_height: int) -> _VideoWriterWrapper:
        gpu_writer = self._try_create_gpu_writer(output_path, frame_width, frame_height)
        if gpu_writer is not None:
            return _VideoWriterWrapper(gpu_writer, use_gpu=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        print("[VideoGenerator] CPUエンコードで動画を書き出します。")
        return _VideoWriterWrapper(
            cv2.VideoWriter(output_path, fourcc, self.fps, (frame_width, frame_height)),
            use_gpu=False,
        )

    # ---------------------------------------------------------------------
    # メイン処理
    # ---------------------------------------------------------------------
    def run(self) -> str:
        """
        動画生成処理を実行し、出力ファイルパスを返す。
        - 例外の有無に関わらず VideoCapture/DB は必ず解放する
        """
        upload_folder = os.getenv("Upload_folder", "uploads")
        
        # パス解決の強化: collect_video_candidates を使用して再帰的に探索
        candidates = collect_video_candidates(
            upload_folder=upload_folder,
            filename=self.original_video_filename,
            source_path=None, # DBにsource_pathがあれば渡すべきだが、今回はfilenameベースで探索
            output_folder=self.output_folder
        )
        
        original_video_path = None
        for path in candidates:
            if os.path.exists(path):
                original_video_path = path
                break
        
        if not original_video_path:
             # フォールバック: 元のロジック + 絶対パス化
             original_video_path = os.path.abspath(os.path.join(upload_folder, self.original_video_filename))

        cap = cv2.VideoCapture(original_video_path)
        if not cap.isOpened():
            # DBを開いたままにしない
            self.conn.close()
            raise IOError(f"[VideoGenerator] 動画ファイルが開けません: {original_video_path} (探索候補: {len(candidates)}件)")

        writer_wrapper = None
        try:
            # --- 入出力設定（FPS は DB > ヘッダ > 30 で決定） ---
            frame_width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap_fps = _safe_float(cap.get(cv2.CAP_PROP_FPS))
            fps = self.db_fps or (cap_fps if _is_finite_number(cap_fps) and cap_fps > 0 else 30.0)
            self.fps = float(fps)

            output_video_path = os.path.join(self.output_folder, f"annotated_run_{self.run_id}.mp4")
            writer_wrapper = self._create_video_writer(output_video_path, frame_width, frame_height)

            # --- frame_num の起点（0/1）を自動推定 ---
            # data_by_frame の最小キーが 0 → 0始まり、そうでなければ 1始まりとみなす
            min_frame_key = min(self.data_by_frame.keys(), default=1)
            frame_offset = 0 if min_frame_key == 0 else 1

            # --- 軌跡（track_id 毎に直近 N 点保持） ---
            trace_history: Dict[int, deque] = defaultdict(deque)

            progress_bar = tqdm(total=total_frames, desc="動画生成中")
            try:
                if self.render_workers <= 1 or total_frames <= 1:
                    for frame_idx in range(total_frames):
                        ret, frame = cap.read()
                        if not ret:
                            break

                        frame_number = frame_idx + frame_offset
                        selected_vehicles, group_tires, trace_snapshot = self._prepare_frame_payload(
                            frame_number,
                            trace_history,
                        )
                        rendered = self._render_frame(
                            frame,
                            frame_number,
                            selected_vehicles,
                            group_tires,
                            trace_snapshot,
                        )
                        writer_wrapper.write(rendered)
                        progress_bar.update(1)
                else:
                    pending: Dict[int, Future] = {}
                    next_to_write = 0
                    with ThreadPoolExecutor(max_workers=self.render_workers) as executor:
                        for frame_idx in range(total_frames):
                            ret, frame = cap.read()
                            if not ret:
                                break

                            frame_number = frame_idx + frame_offset
                            selected_vehicles, group_tires, trace_snapshot = self._prepare_frame_payload(
                                frame_number,
                                trace_history,
                            )
                            future = executor.submit(
                                self._render_frame,
                                frame,
                                frame_number,
                                selected_vehicles,
                                group_tires,
                                trace_snapshot,
                            )
                            pending[frame_idx] = future

                            while next_to_write in pending and pending[next_to_write].done():
                                processed = pending.pop(next_to_write).result()
                                writer_wrapper.write(processed)
                                progress_bar.update(1)
                                next_to_write += 1

                        while pending:
                            future = pending.pop(next_to_write, None)
                            if future is None:
                                next_to_write += 1
                                continue
                            processed = future.result()
                            writer_wrapper.write(processed)
                            progress_bar.update(1)
                            next_to_write += 1
            finally:
                progress_bar.close()

            print(f"[VideoGenerator] 動画生成完了: {output_video_path}")
            return output_video_path

        finally:
            # 例外の有無に関わらず確実にリソースを解放
            if writer_wrapper is not None:
                writer_wrapper.release()
            cap.release()
            self.conn.close()
            cv2.destroyAllWindows()

    # ---------------------------------------------------------------------
    # 個別描画・選定ロジック
    # ---------------------------------------------------------------------
    def _pick_vehicle(self, detections: List[dict]) -> Optional[dict]:
        """
        車両ボックスを堅牢に選ぶ。
        1) class_name が VEHICLE_CLASS_CANDIDATES に含まれるものを優先
        2) 無ければ model_name != 'best' の中から「面積が最大」のもの
        """
        # 1) class_name ベース（英小文字比較）
        class_based = [
            d for d in detections
            if str(d.get("class_name", "")).lower() in VEHICLE_CLASS_CANDIDATES
        ]
        candidates = class_based if class_based else [
            d for d in detections
            if str(d.get("model_name", "")).lower() != "best"
        ]

        if not candidates:
            return None

        def _area(d: dict) -> float:
            try:
                x1 = _safe_float(d["x1"]); y1 = _safe_float(d["y1"])
                x2 = _safe_float(d["x2"]); y2 = _safe_float(d["y2"])
                if not all(map(_is_finite_number, (x1, y1, x2, y2))):
                    return -1.0
                return max(0.0, (x2 - x1) * (y2 - y1))
            except Exception:
                return -1.0

        # 面積最大を選択
        return max(candidates, key=_area)

    def _draw_vehicle_elements(
        self,
        frame: np.ndarray,
        vehicle: dict,
        tires: List[dict],
        trace_history: Dict[int, deque],
    ) -> None:
        """
        車両に関連する要素をまとめて描画
        - 車両 BBox（追越し時は緑）
        - タイヤ BBox（細線）
        - 情報ラベル（ID/速度/TTC/線距離 等）
        """
        # --- 追い越しフラグに応じて色分け ---
        overtake = vehicle.get("overtake")
        try:
            is_overtaking = (int(overtake) == 1)
        except Exception:
            is_overtaking = False
        box_color = OVERTAKE_COLOR if is_overtaking else VEHICLE_BOX_COLOR

        # --- 車両 BBox ---
        if self.show_vehicle_box:
            try:
                p1 = (int(_safe_float(vehicle["x1"])), int(_safe_float(vehicle["y1"])))
                p2 = (int(_safe_float(vehicle["x2"])), int(_safe_float(vehicle["y2"])))
                cv2.rectangle(frame, p1, p2, box_color, 2)
            except Exception:
                # BBox 欠損時は描画スキップ
                pass

        # --- タイヤ BBox（薄め） ---
        if self.show_tire_boxes:
            for t in tires:
                try:
                    tp1 = (int(_safe_float(t["x1"])), int(_safe_float(t["y1"])))
                    tp2 = (int(_safe_float(t["x2"])), int(_safe_float(t["y2"])))
                    cv2.rectangle(frame, tp1, tp2, TIRE_COLOR, 1)
                except Exception:
                    continue

        # --- 軌跡の描画 ---
        track_id_int = _safe_int(vehicle.get("track_id"))
        if track_id_int is not None:
            history = trace_history.get(track_id_int)
            if history and self.show_trace:
                self._draw_trace_points(frame, history)

        # --- 計測点・ラベル ---
        if self.show_measurement:
            self._draw_measurement_annotations(frame, vehicle)
        if self.labels_enabled:
            self._draw_label(frame, vehicle, is_overtaking)

    def _draw_trace_points(self, frame: np.ndarray, history: deque) -> None:
        if not history:
            return

        points: List[Tuple[int, int]] = []
        for item in history:
            if isinstance(item, (tuple, list)) and len(item) == 2:
                # 対象は (frame_num, point)
                point = item[1]
                if isinstance(point, (tuple, list)) and len(point) == 2:
                    try:
                        points.append((int(point[0]), int(point[1])))
                    except Exception:
                        continue

        if not points:
            return

        alphas = np.linspace(TRACE_MIN_ALPHA, TRACE_MAX_ALPHA, len(points))
        for pt, alpha in zip(points, alphas):
            color = tuple(int(component * float(alpha)) for component in TRACE_COLOR)
            cv2.circle(frame, pt, TRACE_POINT_RADIUS, color, -1, cv2.LINE_AA)

    def _draw_label(self, frame: np.ndarray, data: dict, is_overtaking: bool) -> None:
        """描画対象のラベル文字列を組み立てて表示する。"""
        if not self.labels_enabled:
            return

        parts: List[str] = []
        flags = self.label_flags

        if flags.get('label_group_id'):
            gi = _safe_int(data.get('group_id'))
            if gi is not None:
                parts.append(f"ID:{gi}")

        if flags.get('label_speed'):
            speed = _safe_float(data.get('speed_km_h'))
            if _is_finite_number(speed):
                parts.append(f"速度:{float(speed):.1f}km/h")

        if flags.get('label_acceleration'):
            accel_value = _safe_float(data.get('acceleration_m_s2'))
            accel_state = data.get('acceleration_state')
            accel_parts: List[str] = []
            if _is_finite_number(accel_value):
                accel_parts.append(f"{float(accel_value):+.2f}m/s²")
            if isinstance(accel_state, str) and accel_state:
                accel_parts.append(str(accel_state))
            if accel_parts:
                parts.append(f"加減速:{' '.join(accel_parts)}")

        if flags.get('label_lane_distance'):
            lane_label = self._format_lane_distance_label(data)
            if lane_label:
                parts.append(f"白線:{lane_label}")

        if flags.get('label_approach'):
            approach_label = self._format_distance_label(
                data,
                'approach_distance_m',
                'approach_distance_px',
            )
            if approach_label:
                parts.append(f"接近:{approach_label}")

        if flags.get('label_clearance'):
            clearance_label = self._format_distance_label(
                data,
                'clearance_distance_m',
                'clearance_distance_px',
            )
            if clearance_label:
                parts.append(f"離隔:{clearance_label}")

        if flags.get('label_direction'):
            direction_label = self._format_direction_label(data.get('travel_direction'))
            if direction_label:
                parts.append(f"進行:{direction_label}")

        if flags.get('label_overtake'):
            parts.append("追越:有" if is_overtaking else "追越:無")

        label_text = " | ".join(parts)
        if not label_text:
            return

        try:
            x1 = int(_safe_float(data['x1']))
            y1 = int(_safe_float(data['y1']))
        except Exception:
            return

        if PIL_AVAILABLE and self.ttf is not None:
            pad_x = max(6, int(self.font_size * 0.4))
            pad_y = max(4, int(self.font_size * 0.3))
            try:
                pil_img = Image.fromarray(frame)
                draw = ImageDraw.Draw(pil_img)
                bbox = draw.textbbox((0, 0), label_text, font=self.ttf)
                w, h = (bbox[2] - bbox[0], bbox[3] - bbox[1])
                bg_rect = [x1, y1 - h - pad_y * 2, x1 + w + pad_x * 2, y1]
                draw.rectangle(bg_rect, fill=(0, 0, 0, 255))
                draw.text((x1 + pad_x, y1 - h - pad_y), label_text, font=self.ttf, fill=(255, 255, 255, 255))
                frame[:] = np.array(pil_img)
                return
            except Exception:
                pass

        (w, h), baseline = cv2.getTextSize(label_text, self.cv_font, self.cv_font_scale, self.cv_font_thickness)
        padding = max(4, int(self.font_size * 0.25))
        bg_top_left = (x1, y1 - h - padding * 2)
        bg_bottom_right = (x1 + w + padding * 2, y1)
        cv2.rectangle(frame, bg_top_left, bg_bottom_right, (0, 0, 0), -1)
        cv2.putText(
            frame,
            label_text,
            (x1 + padding, y1 - padding),
            self.cv_font,
            self.cv_font_scale,
            TEXT_COLOR,
            self.cv_font_thickness,
            cv2.LINE_AA,
        )

    def _format_distance_label(self, data: dict, meters_key: str, pixels_key: str) -> Optional[str]:
        distance_m = _safe_float(data.get(meters_key))
        if _is_finite_number(distance_m):
            return f"{float(distance_m):.2f}m"
        distance_px = _safe_float(data.get(pixels_key))
        if _is_finite_number(distance_px):
            return f"{float(distance_px):.1f}px"
        return None

    def _format_lane_distance_label(self, data: dict) -> Optional[str]:
        distances: List[Tuple[str, float]] = []
        left = _safe_float(data.get("l_line_distance"))
        if _is_finite_number(left):
            distances.append(("L", float(left)))
        right = _safe_float(data.get("r_line_distance"))
        if _is_finite_number(right):
            distances.append(("R", float(right)))
        if not distances:
            return None
        side, value = min(distances, key=lambda item: abs(item[1]))
        return f"{side}:{abs(value):.1f}px"

    def _format_direction_label(self, value) -> Optional[str]:
        if value is None:
            return None
        try:
            key = str(value).strip().upper()
        except Exception:
            return None
        mapping = {
            'F': '前進',
            'B': '後退',
            'L': '左',
            'R': '右',
            'N': '不明',
        }
        if not key:
            return None
        if key in mapping:
            return mapping[key]
        return key

    def _draw_distance_label(self, frame: np.ndarray, position: Tuple[int, int], text: str, color: Tuple[int, int, int]) -> None:
        (text_w, text_h), baseline = cv2.getTextSize(text, self.cv_font, 0.45, 1)
        x, y = position
        x = int(max(0, min(frame.shape[1] - text_w, x - text_w / 2)))
        y = int(max(text_h + 4, min(frame.shape[0] - baseline - 1, y - 8)))
        bg_tl = (x - 4, y - text_h - 4)
        bg_br = (x + text_w + 4, y + baseline)
        cv2.rectangle(frame, bg_tl, bg_br, (0, 0, 0), -1)
        cv2.putText(frame, text, (x, y), self.cv_font, 0.45, color, 1, cv2.LINE_AA)

    def _is_clearance_highlight_frame(self, pair_key: Tuple[int, int], frame_number: int) -> bool:
        frames = self.clearance_event_frames.get(pair_key)
        if not frames:
            return False
        for event_frame in frames:
            if abs(frame_number - event_frame) <= CLEARANCE_HIGHLIGHT_WINDOW:
                return True
        return False

    def _draw_approach_lines(
        self,
        frame: np.ndarray,
        frame_number: int,
        selected_vehicles: Dict[int, dict],
    ) -> None:
        if not self.show_approach_lines:
            return
        drawn_pairs: Set[Tuple[int, int]] = set()
        for gid, vehicle in selected_vehicles.items():
            partner_gid = _safe_int(vehicle.get("approach_partner_group_id"))
            if partner_gid is None:
                continue
            partner_vehicle = selected_vehicles.get(partner_gid)
            if partner_vehicle is None:
                continue

            pair_key = tuple(sorted((gid, partner_gid)))
            if pair_key in drawn_pairs:
                continue

            start_pt = self._get_measure_point(vehicle)
            end_pt = self._get_measure_point(partner_vehicle)
            if start_pt is None or end_pt is None:
                continue

            highlight = self._is_clearance_highlight_frame(pair_key, frame_number)
            color = CLEARANCE_LINE_HIGHLIGHT_COLOR if highlight else APPROACH_LINE_COLOR
            cv2.line(frame, start_pt, end_pt, color, APPROACH_LINE_THICKNESS, cv2.LINE_AA)

            label_text: Optional[str] = None
            if highlight:
                label_text = self._format_distance_label(
                    vehicle,
                    "clearance_distance_m",
                    "clearance_distance_px",
                )
                if not label_text:
                    label_text = self._format_distance_label(
                        partner_vehicle,
                        "clearance_distance_m",
                        "clearance_distance_px",
                    )
            if not label_text:
                label_text = self._format_distance_label(
                    vehicle,
                    "approach_distance_m",
                    "approach_distance_px",
                )
                if not label_text:
                    label_text = self._format_distance_label(
                        partner_vehicle,
                        "approach_distance_m",
                        "approach_distance_px",
                    )

            if label_text:
                midpoint = (
                    int((start_pt[0] + end_pt[0]) / 2),
                    int((start_pt[1] + end_pt[1]) / 2),
                )
                self._draw_distance_label(frame, midpoint, label_text, color)

            drawn_pairs.add(pair_key)

    def _draw_calibration_lines(self, frame: np.ndarray) -> None:
        """Draw calibration overlays such as lane lines, scale markers, and homography area."""
        if self.left_lane_poly is not None and self.show_lane_left:
            cv2.polylines(frame, [self.left_lane_poly], False, self.white_line_color, 2, cv2.LINE_AA)
        if self.right_lane_poly is not None and self.show_lane_right:
            cv2.polylines(frame, [self.right_lane_poly], False, self.white_line_color, 2, cv2.LINE_AA)
        if self.center_lane_poly is not None and self.show_lane_center:
            cv2.polylines(frame, [self.center_lane_poly], False, self.center_line_color, 1, cv2.LINE_AA)

        if self.scale_mode == 'homography' and self.homography_polygon is not None:
            overlay = frame.copy()
            cv2.fillPoly(overlay, [self.homography_polygon], (40, 120, 255))
            cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)
            for seg in self.homography_scale_segments:
                if seg is not None:
                    cv2.polylines(frame, [seg], False, self.scale_line_color, 1, cv2.LINE_AA)
        else:
            for seg in self.scale_line_segments:
                if seg is not None:
                    cv2.polylines(frame, [seg], False, self.scale_line_color, 1, cv2.LINE_AA)

        for arr in self.calib_polylines:
            cv2.polylines(frame, [arr], isClosed=False, color=LINE_COLOR, thickness=1, lineType=cv2.LINE_AA)

        for arr in self.calib_polylines:
            # isClosed=False で折れ線表示。線の太さやAAを有効化。
            cv2.polylines(frame, [arr], isClosed=False, color=LINE_COLOR, thickness=2, lineType=cv2.LINE_AA)


# -------------------------------------------------------------------------
# 外部から呼ぶラッパー関数
# -------------------------------------------------------------------------
def create_annotated_video(run_id: int, video_options: Optional[dict] = None) -> str:
    """
    ラッパー関数（既存コード互換）
    - 使用例: output_path = create_annotated_video(run_id=123)
    """
    generator = VideoGenerator(run_id, video_options)
    return generator.run()
