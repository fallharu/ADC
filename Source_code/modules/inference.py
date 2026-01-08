# 役割: YOLO推論を実行し、DBに初期データを保存する
import json
import math
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
import torch
from torch import cuda
import cv2
import numpy as np
from datetime import datetime
import tempfile
from typing import Any, Callable, Dict, Iterable, List, Optional
from ultralytics import YOLO
from dotenv import load_dotenv
from tqdm import tqdm

from .db_manager import (
    MAIN_DB_PATH,
    configure_connection,
    get_or_create_video_id,
    get_or_create_class_id,
    create_process_log,
    update_process_log,
    log_error,
    init_db,
)
from .all_save import create_all_save, create_csv_bundle
from .group_id import assign_group_ids
from .speed import assign_kinematics
from .overtake import assign_overtake, summarize_run_overtakes
from .approach_distance import assign_approach_and_clearance
from .lane_distance import assign_lane_distance
from .inter_vehicle_distance import analyze_proximity
from .ttc_calculator import assign_ttc
from .folder_config import load_folder_settings_with_flag
from .class_filters import is_vehicle_class
from .resource_monitor import (
    capture_system_metrics,
    configure_cuda_memory_budget,
    recommend_parallelism,
)

load_dotenv()
MODEL_FILES_PATH = os.getenv("Model_files", "models").strip('"')
OPT_FILES_PATH = os.getenv("Opt_files", "output").strip('"')

VEHICLE_MODEL_FALLBACKS = [
    "yolo11x.pt",
    "yolo11x6.pt",
    "yolov8x.pt",
    "yolov8x6.pt",
    "yolov8l.pt",
    "yolov8m.pt",
]

TIRE_MODEL_FALLBACKS = [
    "tire_best.pt",
]

YOLO_DB_BUFFER_MB = int(os.getenv("YOLO_DB_BUFFER_MB", "1536"))


def _atomic_write_json(path: str, payload: Dict[str, object]) -> None:
    """JSONファイルを一時ファイル経由で安全に書き出す。"""
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


def _normalize_model_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    candidate = str(name).strip().strip('"').strip("'")
    return candidate or None


def _sanitize_track_value(value: Any) -> Optional[int]:
    """YOLOの追跡ID値を正規化して整数IDとして扱う。"""

    if value is None:
        return None

    if isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]

    if isinstance(value, bytes):
        try:
            value = value.decode()
        except Exception:  # noqa: BLE001
            return None

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        value = stripped

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    if math.isnan(numeric) or math.isinf(numeric):
        return None

    track_int = int(round(numeric))
    if track_int < 0:
        return None
    return track_int


def _extract_track_ids(result) -> List[Optional[int]]:
    """YOLOの結果オブジェクトから追跡ID一覧を抽出する。"""

    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return []

    ids_attr = getattr(boxes, "id", None)
    count = len(boxes)
    if ids_attr is None:
        return [None] * count

    try:
        ids_array = ids_attr.cpu().numpy().reshape(-1)
    except Exception:  # noqa: BLE001
        try:
            ids_array = np.array(ids_attr).reshape(-1)
        except Exception:  # noqa: BLE001
            return [None] * count

    normalized: List[Optional[int]] = []
    for raw in ids_array:
        normalized.append(_sanitize_track_value(raw))
    while len(normalized) < count:
        normalized.append(None)
    if len(normalized) > count:
        normalized = normalized[:count]
    return normalized


def _resolve_model_sequence(
    explicit_vehicle_model: Optional[str] = None,
    explicit_tire_model: Optional[str] = None,
) -> tuple[list[str], list[str]]:
    """利用可能なYOLOモデルの組み合わせを検出し、優先順に返す。"""

    base_dir = os.path.abspath(MODEL_FILES_PATH) if MODEL_FILES_PATH else os.getcwd()
    resolved: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()

    def try_add(candidates: Iterable[Optional[str]]) -> Optional[str]:
        for raw in candidates:
            candidate = _normalize_model_name(raw)
            if not candidate or candidate in seen:
                continue
            candidate_path = os.path.join(base_dir, candidate)
            
            # Allow standard YOLO models to be added even if missing locally (will auto-download)
            is_standard_yolo = candidate.lower().startswith("yolo") and candidate.lower().endswith(".pt")

            if os.path.exists(candidate_path) or is_standard_yolo:
                resolved.append(candidate)
                seen.add(candidate)
                return candidate
        return None

    # 1. Vehicle Model
    vehicle_candidates: list[Optional[str]] = []
    if explicit_vehicle_model:
        vehicle_candidates.append(explicit_vehicle_model)
    
    env_primary = _normalize_model_name(os.getenv("YOLO_PRIMARY_MODEL"))
    if env_primary:
        vehicle_candidates.append(env_primary)
    vehicle_candidates.extend(VEHICLE_MODEL_FALLBACKS)

    vehicle_model = try_add(vehicle_candidates)
    if not vehicle_model and not explicit_vehicle_model:
        try:
            fallback_general = sorted(
                name
                for name in os.listdir(base_dir)
                if name.lower().endswith(".pt")
                and "best" not in name.lower()
                and name not in seen
            )
        except OSError:
            fallback_general = []

        vehicle_model = try_add(fallback_general)
        if vehicle_model:
            warnings.append(
                f"警告: 指定の車両検出モデルが見つからなかったため {vehicle_model} を使用します。"
            )
        else:
            warnings.append("警告: 車両検出用モデルが見つかりません。タイヤ検出のみを実行します。")
    elif explicit_vehicle_model and not vehicle_model:
         warnings.append(f"警告: 指定された車両モデル '{explicit_vehicle_model}' が見つかりません。")

    # 2. Tire Model
    tire_candidates: list[Optional[str]] = []
    if explicit_tire_model:
        tire_candidates.append(explicit_tire_model)

    env_tire = _normalize_model_name(os.getenv("YOLO_TIRE_MODEL"))
    if env_tire:
        tire_candidates.append(env_tire)
    tire_candidates.extend(TIRE_MODEL_FALLBACKS)

    tire_model = try_add(tire_candidates)
    if not tire_model and not explicit_tire_model:
        try:
            fallback_tire = sorted(
                name
                for name in os.listdir(base_dir)
                if name.lower().endswith(".pt")
                and "best" in name.lower()
                and name not in seen
            )
        except OSError:
            fallback_tire = []

        tire_model = try_add(fallback_tire)
        if tire_model:
            warnings.append(
                f"警告: 指定のタイヤ検出モデルが見つからなかったため {tire_model} を使用します。"
            )
        else:
            warnings.append("警告: タイヤ検出用モデルが見つかりません。")
    elif explicit_tire_model and not tire_model:
         warnings.append(f"警告: 指定されたタイヤモデル '{explicit_tire_model}' が見つかりません。")

    return resolved, warnings


def _resolve_tracker_config() -> Optional[str]:
    """YOLOのトラッカー設定ファイルを解決する。"""

    raw = (os.getenv("YOLO_TRACKER_CONFIG") or "bytetrack.yaml").strip()
    if not raw:
        return None

    # 絶対パスまたはカレントディレクトリ基準で存在する場合はそのまま返す
    if os.path.isabs(raw) and os.path.isfile(raw):
        return raw

    # モデルディレクトリ内を検索
    base_dir = os.path.abspath(MODEL_FILES_PATH) if MODEL_FILES_PATH else os.getcwd()
    candidate = os.path.join(base_dir, raw)
    if os.path.isfile(candidate):
        return candidate
    
    return raw # YOLO default fallback

FOLDER_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}


def make_relative_video_path(video_path: str, base_folder: str) -> str:
    """フォルダ基準の相対パスを生成し、表示用に整形する。"""
    try:
        rel_path = os.path.relpath(video_path, base_folder)
    except ValueError:
        return os.path.basename(video_path)

    if rel_path == "." or rel_path.startswith(".."):
        return os.path.basename(video_path)

    # Windows パス区切りを揃えて表示を安定させる
    return rel_path.replace(os.sep, "/")


def collect_video_files(folder_path: str, include_subdirectories: bool = True) -> List[str]:
    """指定フォルダ内の動画ファイル一覧を取得する。

    include_subdirectories が True の場合はサブフォルダも再帰的に探索する。
    例外が発生した場合は空のリストを返す。
    """

    video_files: List[str] = []
    if not os.path.isdir(folder_path):
        return video_files

    try:
        if include_subdirectories:
            for current_root, dirs, files in os.walk(folder_path):
                dirs.sort()
                for name in sorted(files):
                    ext = os.path.splitext(name)[1].lower()
                    if ext in FOLDER_VIDEO_EXTENSIONS:
                        video_files.append(os.path.join(current_root, name))
        else:
            for name in sorted(os.listdir(folder_path)):
                full_path = os.path.join(folder_path, name)
                if not os.path.isfile(full_path):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext in FOLDER_VIDEO_EXTENSIONS:
                    video_files.append(full_path)
    except OSError:
        return []

    return video_files


@dataclass
class VideoProcessResult:
    """単体動画の推論結果サマリ。"""

    run_id: int
    model_counts: Dict[str, int]
    total_detections: int
    models_used: List[str] = field(default_factory=list)


@dataclass
class FolderProcessingResult:
    entries: List[Dict[str, Optional[str]]]
    csv_bundle_path: Optional[str] = None


@dataclass
class ResolvedFolderSettings:
    profile: Optional[str]
    auto_postprocess: bool
    auto_csv: bool
    profile_source: Optional[str] = None
    auto_postprocess_source: Optional[str] = None
    auto_csv_source: Optional[str] = None
    process_year: Optional[int] = None
    location_id: Optional[int] = None
    road_type: Optional[str] = None
    vehicle_model: Optional[str] = None
    tire_model: Optional[str] = None
    process_year_source: Optional[str] = None
    location_source: Optional[str] = None
    road_type_source: Optional[str] = None
    vehicle_model_source: Optional[str] = None
    tire_model_source: Optional[str] = None


class SubfolderSettingsResolver:
    """フォルダ内の階層構造に応じた設定を解決するヘルパー。"""

    def __init__(
        self,
        base_folder: str,
        *,
        config_root: Optional[str] = None,
        default_profile: Optional[str] = None,
        default_auto_postprocess: bool = False,
        default_auto_csv: bool = False,
        default_year: Optional[int] = None,
        default_location_id: Optional[int] = None,
        default_road_type: Optional[str] = None,
        default_vehicle_model: Optional[str] = None,
        default_tire_model: Optional[str] = None,
    ) -> None:
        self.base_folder = os.path.abspath(base_folder)
        self.config_root = os.path.abspath(config_root) if config_root else None

        profile_value = (default_profile or "").strip()
        self._defaults = ResolvedFolderSettings(
            profile=profile_value or None,
            auto_postprocess=bool(default_auto_postprocess),
            auto_csv=bool(default_auto_csv),
            profile_source="default" if profile_value else None,
            auto_postprocess_source="default",
            auto_csv_source="default",
            process_year=default_year if default_year is not None else None,
            location_id=default_location_id if default_location_id is not None else None,
            road_type=default_road_type if default_road_type else None,
            vehicle_model=default_vehicle_model if default_vehicle_model else None,
            tire_model=default_tire_model if default_tire_model else None,
            process_year_source="default" if default_year is not None else None,
            location_source="default" if default_location_id is not None else None,
            road_type_source="default" if default_road_type else None,
            vehicle_model_source="default" if default_vehicle_model else None,
            tire_model_source="default" if default_tire_model else None,
        )
        self._real_cache: Dict[str, tuple[Dict[str, Any], bool]] = {}
        self._config_cache: Dict[str, tuple[Dict[str, Any], bool]] = {}

    def _load_settings(
        self,
        directory: str,
        cache: Dict[str, tuple[Dict[str, Any], bool]],
    ) -> tuple[Dict[str, Any], bool]:
        if directory in cache:
            return cache[directory]
        settings, exists = load_folder_settings_with_flag(directory)
        cache[directory] = (settings, exists)
        return settings, exists

    @staticmethod
    def _relative_parts(base_folder: str, target_dir: str) -> List[str]:
        try:
            rel = os.path.relpath(target_dir, base_folder)
        except ValueError:
            return []
        if rel in (".", "") or rel.startswith(".."):
            return []
        return [part for part in rel.split(os.sep) if part and part != "."]

    @staticmethod
    def _build_sequence(root: Optional[str], parts: List[str]) -> List[str]:
        if not root:
            return []
        sequence = [root]
        current = root
        for part in parts:
            current = os.path.join(current, part)
            sequence.append(current)
        return sequence

    @staticmethod
    def _label_from_parts(parts: List[str], depth: int) -> str:
        if depth <= 0 or not parts:
            return "root"
        fragment = "/".join(parts[:depth])
        return fragment or "root"

    def resolve(self, video_path: str) -> ResolvedFolderSettings:
        video_dir = os.path.abspath(os.path.dirname(video_path))
        parts = self._relative_parts(self.base_folder, video_dir)
        real_sequence = self._build_sequence(self.base_folder, parts)
        config_sequence = self._build_sequence(self.config_root, parts)

        resolved = ResolvedFolderSettings(
            profile=self._defaults.profile,
            auto_postprocess=self._defaults.auto_postprocess,
            auto_csv=self._defaults.auto_csv,
            profile_source=self._defaults.profile_source,
            auto_postprocess_source=self._defaults.auto_postprocess_source,
            auto_csv_source=self._defaults.auto_csv_source,
            process_year=self._defaults.process_year,
            location_id=self._defaults.location_id,
            road_type=self._defaults.road_type,
            vehicle_model=self._defaults.vehicle_model,
            tire_model=self._defaults.tire_model,
            process_year_source=self._defaults.process_year_source,
            location_source=self._defaults.location_source,
            road_type_source=self._defaults.road_type_source,
            vehicle_model_source=self._defaults.vehicle_model_source,
            tire_model_source=self._defaults.tire_model_source,
        )

        max_depth = max(len(real_sequence), len(config_sequence))
        for depth in range(max_depth):
            if depth < len(real_sequence):
                directory = real_sequence[depth]
                settings, exists = self._load_settings(directory, self._real_cache)
                if exists:
                    label = f"real:{self._label_from_parts(parts, depth)}"
                    self._apply_settings(resolved, settings, label)
            if depth < len(config_sequence):
                directory = config_sequence[depth]
                settings, exists = self._load_settings(directory, self._config_cache)
                if exists:
                    label = f"config:{self._label_from_parts(parts, depth)}"
                    self._apply_settings(resolved, settings, label)

        return resolved

    @staticmethod
    def _apply_settings(
        target: ResolvedFolderSettings,
        settings: Dict[str, Any],
        source_label: str,
    ) -> None:
        if "profile" in settings:
            raw_profile = str(settings.get("profile") or "").strip()
            if raw_profile:
                target.profile = raw_profile
            else:
                target.profile = None
            target.profile_source = source_label

        if "auto_postprocess" in settings:
            target.auto_postprocess = bool(settings.get("auto_postprocess"))
            target.auto_postprocess_source = source_label

        if "auto_csv" in settings:
            target.auto_csv = bool(settings.get("auto_csv"))
            target.auto_csv_source = source_label

        if "process_year" in settings:
            try:
                year_value = int(settings.get("process_year"))
            except (TypeError, ValueError):
                year_value = None
            if year_value is not None and year_value < 0:
                year_value = None
            target.process_year = year_value
            target.process_year_source = source_label

        if "location_id" in settings:
            try:
                location_value = int(settings.get("location_id"))
            except (TypeError, ValueError):
                location_value = None
            if location_value is not None and location_value <= 0:
                location_value = None
            target.location_id = location_value
            target.location_source = source_label

        if "road_type" in settings:
            raw_road_type = str(settings.get("road_type") or "").strip()
            if raw_road_type:
                target.road_type = raw_road_type
            else:
                target.road_type = None
            target.road_type_source = source_label

        if "vehicle_model" in settings:
            raw_vm = str(settings.get("vehicle_model") or "").strip()
            target.vehicle_model = raw_vm if raw_vm else None
            target.vehicle_model_source = source_label

        if "tire_model" in settings:
            raw_tm = str(settings.get("tire_model") or "").strip()
            target.tire_model = raw_tm if raw_tm else None
            target.tire_model_source = source_label

def _read_parallel_default() -> int:
    raw = (os.getenv("YOLO_PARALLEL_FRAMES") or "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 1
    return max(1, value)


DEFAULT_PARALLEL_FRAMES = _read_parallel_default()


def resolve_parallel_frames(requested: Optional[int]) -> int:
    """環境変数またはユーザー指定値から並列フレーム数を決定する。"""
    if requested is None:
        return DEFAULT_PARALLEL_FRAMES
    try:
        value = int(requested)
    except (TypeError, ValueError):
        return DEFAULT_PARALLEL_FRAMES
    return max(1, value)

def get_video_properties(video_path: str):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened(): return 0.0, 0.0, 0
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps > 0 else 0.0
    cap.release()
    return duration, fps, frame_count


def run_postprocess_pipeline_sync(run_id: int) -> tuple[List[str], List[str]]:
    """後処理7ステップを順番に実行し、成功/失敗の結果を返す。"""
    steps: List[tuple[str, Callable[[int], None]]] = [
        ("グループID", assign_group_ids),
        ("運動学", assign_kinematics),
        ("追い越し", assign_overtake),
        ("接近/離隔", assign_approach_and_clearance),
        ("白線距離", assign_lane_distance),
        ("車両間距離", analyze_proximity),
        ("TTC", assign_ttc),
    ]
    completed: List[str] = []
    errors: List[str] = []
    for label, handler in steps:
        try:
            result = handler(run_id)
            if label == "追い越し" and isinstance(result, int):
                completed.append(f"{label}({result}枚)")
            else:
                completed.append(label)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {exc}")
    return completed, errors

def process_video(
    video_path: str,
    progress_callback=None,
    frame_parallelism: Optional[int] = None,
    *,
    folder_alias: Optional[str] = None,
    is_folder_batch: bool = False,
    process_year: Optional[int] = None,
    location_id: Optional[int] = None,
    road_type: Optional[str] = None,
    vehicle_model: Optional[str] = None,
    tire_model: Optional[str] = None,
):
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"動画ファイルが見つかりません: {video_path}")

    abs_video_path = os.path.abspath(video_path)
    filename = os.path.basename(abs_video_path)
    video_name, _ = os.path.splitext(filename)
    start_dt = datetime.now()

    init_db()

    run_id = None
    conn = None
    class_cache: Dict[str, int] = {}
    model_detection_counts: Dict[str, int] = defaultdict(int)
    try:
        conn = sqlite3.connect(MAIN_DB_PATH)
        configure_connection(conn, mode="write", memory_mb=YOLO_DB_BUFFER_MB)
        conn.execute("PRAGMA foreign_keys=ON;")
        
        duration, fps, total_frames = get_video_properties(abs_video_path)
        video_id = get_or_create_video_id(
            conn,
            filename,
            duration,
            fps,
            source_path=abs_video_path,
            road_type=road_type,
            collection_year=process_year,
        )

        timestamp = start_dt.strftime("%Y%m%d_%H%M%S")
        base_output_root = os.path.abspath(OPT_FILES_PATH) if OPT_FILES_PATH else os.getcwd()
        os.makedirs(base_output_root, exist_ok=True)
        effective_alias = folder_alias.strip() if isinstance(folder_alias, str) else ""
        if effective_alias:
            output_root = os.path.join(base_output_root, effective_alias)
            os.makedirs(output_root, exist_ok=True)
        else:
            output_root = base_output_root
        out_folder = os.path.join(output_root, f"{video_name}_{timestamp}")
        os.makedirs(out_folder, exist_ok=True)

        run_id = create_process_log(
            conn,
            video_id,
            start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            out_folder,
            folder_alias=effective_alias or None,
            is_folder_batch=is_folder_batch,
            process_year=process_year,
            location_id=location_id,
        )
        conn.commit()

        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda":
            configure_cuda_memory_budget(0.8)
            cuda.empty_cache()
            torch.backends.cudnn.benchmark = True
            try:
                torch.set_float32_matmul_precision("high")
            except AttributeError:
                pass
        model_files, model_warnings = _resolve_model_sequence(
            explicit_vehicle_model=vehicle_model,
            explicit_tire_model=tire_model
        )
        if not model_files:
            base_dir = os.path.abspath(MODEL_FILES_PATH) if MODEL_FILES_PATH else os.getcwd()
            raise FileNotFoundError(
                f"モデルディレクトリ {base_dir} に使用可能なYOLOモデルが見つかりません。"
            )
        for message in model_warnings:
            print(f"[モデル選択] {message}")
        total_det = 0

        detections_buffer: List[tuple] = []
        buffer_limit = max(1000, int(os.getenv("YOLO_DB_BUFFER_LIMIT", "20000")))

        parallel_frames = resolve_parallel_frames(frame_parallelism)
        max_auto = int(os.getenv("YOLO_AUTO_PARALLEL_MAX", "8"))

        for mf in model_files:
            model_path = os.path.join(MODEL_FILES_PATH, mf)
            is_standard_yolo = mf.lower().startswith("yolo") and mf.lower().endswith(".pt")

            if not os.path.exists(model_path) and not is_standard_yolo:
                print(f"警告: モデルファイルが見つかりません: {model_path}")
                continue

            raw_model_name = os.path.splitext(mf)[0]
            raw_model_name_lower = raw_model_name.lower()
            if "best" in raw_model_name_lower and not raw_model_name_lower.startswith("yolo"):
                model_name = "best"
            else:
                model_name = raw_model_name
            model_name_lower = model_name.lower()
            metrics = capture_system_metrics()
            tuned_frames = parallel_frames
            if metrics is not None:
                candidate = recommend_parallelism(parallel_frames, metrics, max_parallel=max_auto)
                if candidate != parallel_frames:
                    print(
                        "[AUTO] 並列フレーム数を調整: "
                        f"{parallel_frames} -> {candidate} (CPU={metrics.cpu_util_percent}, "
                        f"GPU={metrics.gpu_util_percent}, RAM_MB={metrics.ram_available_mb})"
                    )
                tuned_frames = candidate
                parallel_frames = candidate

                parallel_frames = candidate

            target_model = model_path if os.path.exists(model_path) else mf
            model = YOLO(target_model)
            # すべての重みとバッファを明示的にfloat32へ変換してdtype不一致を防ぐ
            model.to(device=device)
            model.model.float()
            # UltralyticsのTrack APIはhalf指定を内部で行う場合があるため事前に無効化
            if hasattr(model, "overrides"):
                model.overrides["half"] = False
            if hasattr(model, "predictor") and hasattr(model.predictor, "overrides"):
                model.predictor.overrides["half"] = False
            tracker_config = _resolve_tracker_config()
            tracker_kwargs: dict[str, object] = {}
            if tracker_config:
                tracker_kwargs["tracker"] = tracker_config
                print(f"[YOLO] {model_name} でトラッカー設定 '{tracker_config}' を使用します。")
            try:
                model.fuse()
            except AttributeError:
                pass

            results = model.track(
                source=abs_video_path,
                device=device,
                stream=True,
                conf=0.3,
                persist=True,
                batch=tuned_frames,
                half=False,
                **tracker_kwargs,
            )

            frame_num = 0
            missing_track_warning_emitted = False
            with torch.inference_mode():
                for r in tqdm(results, total=total_frames, desc=f"推論中: {model_name}"):
                    frame_num += 1
                    if progress_callback:
                        progress_callback(frame_num, total_frames, "processing")

                    if r.boxes is None or len(r.boxes) == 0:
                        continue

                    track_ids = _extract_track_ids(r)
                    if track_ids and not missing_track_warning_emitted:
                        if all(tid is None for tid in track_ids):
                            print(
                                f"[警告] {model_name} から有効なトラックIDを取得できませんでした。"
                                " YOLO_TRACKER_CONFIG の設定や Ultralytics のバージョンを確認してください。"
                            )
                            missing_track_warning_emitted = True
                    class_ids_int = r.boxes.cls.int().cpu().tolist()
                    confs = r.boxes.conf.cpu().tolist()
                    xyxys = r.boxes.xyxy.cpu().tolist()

                    is_vehicle_detector = (
                        model_name_lower.startswith("yolo")
                        and "best" not in model_name_lower
                    )

                    for i in range(len(xyxys)):
                        raw_class_name = r.names[class_ids_int[i]]
                        class_name = str(raw_class_name).strip()
                        if not class_name:
                            class_name = str(raw_class_name)

                        if is_vehicle_detector and not is_vehicle_class(class_name):
                            continue

                        cache_key = class_name.lower()
                        class_id = class_cache.get(cache_key)
                        if class_id is None:
                            class_id = get_or_create_class_id(conn, class_name)
                            class_cache[cache_key] = class_id

                        detections_buffer.append((
                            run_id,
                            video_id,
                            class_id,
                            frame_num,
                            xyxys[i][0],
                            xyxys[i][1],
                            xyxys[i][2],
                            xyxys[i][3],
                            model_name,
                            track_ids[i],
                            confs[i],
                        ))
                        total_det += 1
                        model_detection_counts[model_name] += 1

                    if len(detections_buffer) >= buffer_limit:
                        conn.executemany(
                            """
                            INSERT INTO Detection (run_id, video_id, class_id, frame_num, x1, y1, x2, y2, model_name, track_id, confidence)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            detections_buffer,
                        )
                        detections_buffer.clear()

            if device == "cuda":
                cuda.empty_cache()

            current_count = model_detection_counts.get(model_name, 0)
            if current_count:
                print(f"[YOLO] モデル {model_name} の検出件数: {current_count} 件")
            else:
                print(f"[YOLO] モデル {model_name} では検出が得られませんでした。")
        
        if detections_buffer:
            conn.executemany(
                """
                INSERT INTO Detection (run_id, video_id, class_id, frame_num, x1, y1, x2, y2, model_name, track_id, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                detections_buffer,
            )
            detections_buffer.clear()

        conn.commit()

        end_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_process_log(run_id, end_dt, total_det, "completed")

        with open(os.path.join(out_folder, "summary.txt"), "w", encoding="utf-8") as f:
            f.write(f"Run ID: {run_id}\n")
            f.write(f"Video: {filename}\n")
            f.write(f"Total Detections: {total_det}\n")
            f.write(f"Used Models: {', '.join(model_files)}\n")
            if model_detection_counts:
                f.write("Detections by model:\n")
                for model_name, count in model_detection_counts.items():
                    f.write(f"  - {model_name}: {count}\n")

        return VideoProcessResult(
            run_id=run_id,
            model_counts=dict(model_detection_counts),
            total_detections=total_det,
            models_used=list(model_files),
        )

    except Exception as e:
        print(f"エラー発生: {e}")
        if run_id:
            end_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            update_process_log(run_id, end_dt, 0, "error")
            log_error(run_id, str(e))
        if conn:
            conn.rollback()
        raise e

    finally:
        if conn:
            conn.close()

def apply_calibration_profile(run_id: int, profile_name: str) -> str:
    """ProcessLog に既存キャリブレーションプロファイルを適用する。"""
    if not profile_name:
        raise ValueError("プロファイル名が指定されていません")
    sanitized = ''.join(c for c in profile_name if c.isalnum() or c in ('_', '-'))
    if not sanitized:
        raise ValueError("プロファイル名には英数字と '_' 、 '-' のみ使用できます")

    calib_dir = os.path.join(OPT_FILES_PATH, 'calibrations')
    profile_path = os.path.join(calib_dir, f"{sanitized}.json")
    if not os.path.exists(profile_path):
        print(f"[!] 注意: キャリブレーションファイルが見つかりません ({profile_path})")
        payload = None
    else:
        try:
            with open(profile_path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception as exc:
            print(f"[!] 注意: キャリブレーションファイルの読み込みに失敗しました ({profile_path}): {exc}")
            payload = None

    if payload:
        run_specific_path = os.path.join(calib_dir, f"calibration_{run_id}.json")
        try:
            _atomic_write_json(run_specific_path, payload)
        except Exception as exc:
            print(f"[!] 注意: Run専用キャリブレーションの保存に失敗しました ({run_specific_path}): {exc}")

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        conn.execute(
            "UPDATE ProcessLog SET calibration_profile = ? WHERE run_id = ?",
            (sanitized, run_id)
        )
    return sanitized


FolderCallback = Optional[
    Callable[[str, int, int, Optional[str], Optional[Dict[str, Optional[str]]]], None]
]

PostProcessHandler = Optional[Callable[[int, ResolvedFolderSettings], Optional[str]]]


def process_video_folder(
    folder_path: str,
    profile_name: Optional[str] = None,
    export_csv: bool = False,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    frame_parallelism: Optional[int] = None,
    folder_callback: FolderCallback = None,
    folder_alias: Optional[str] = None,
    postprocess_handler: PostProcessHandler = None,
    include_subdirectories: bool = True,
    *,
    default_auto_postprocess: bool = False,
    folder_settings_root: Optional[str] = None,
    default_process_year: Optional[int] = None,
    default_location_id: Optional[int] = None,
    default_road_type: Optional[str] = None,
    default_vehicle_model: Optional[str] = None,
    default_tire_model: Optional[str] = None,
) -> FolderProcessingResult:
    """指定フォルダ内（必要に応じてサブフォルダも含む）の動画ファイルへ一括でYOLO推論を実施する。"""
    if not os.path.isdir(folder_path):
        raise NotADirectoryError(f"フォルダが存在しません: {folder_path}")

    results: List[Dict[str, Optional[str]]] = []
    csv_outputs: List[str] = []
    video_entries = collect_video_files(
        folder_path,
        include_subdirectories=include_subdirectories,
    )

    resolver = SubfolderSettingsResolver(
        folder_path,
        config_root=folder_settings_root,
        default_profile=profile_name,
        default_auto_postprocess=default_auto_postprocess,
        default_auto_csv=export_csv,
        default_year=default_process_year,
        default_location_id=default_location_id,
        default_road_type=default_road_type,
        default_vehicle_model=default_vehicle_model,
        default_tire_model=default_tire_model,
    )

    total = len(video_entries)
    if folder_callback:
        folder_callback("start", 0, total, None, None)

    base_alias = (folder_alias or "").strip()

    for index, video_path in enumerate(video_entries, start=1):
        display_name = make_relative_video_path(video_path, folder_path)
        if folder_callback:
            folder_callback("video_start", index, total, display_name, None)

        resolved_settings = resolver.resolve(video_path)
        relative_dir = ""
        try:
            relative_dir = os.path.relpath(os.path.dirname(video_path), folder_path)
        except ValueError:
            relative_dir = ""
        if relative_dir in ("", ".") or relative_dir.startswith(".."):
            effective_alias = base_alias
        else:
            normalized_subdir = relative_dir.replace(os.sep, "/")
            effective_alias = f"{base_alias}/{normalized_subdir}" if base_alias else normalized_subdir

        stored_alias = effective_alias or None

        result: Dict[str, Optional[str]] = {
            'video': video_path,
            'video_display': display_name,
            'run_id': None,
            'profile': None,
            'csv_path': None,
            'postprocess': None,
            'error': None,
            'folder_alias': stored_alias,
        }
        try:
            video_result = process_video(
                video_path,
                progress_callback=progress_callback,
                frame_parallelism=frame_parallelism,
                folder_alias=stored_alias,
                is_folder_batch=True,
                process_year=resolved_settings.process_year,
                location_id=resolved_settings.location_id,
                road_type=resolved_settings.road_type,
                vehicle_model=resolved_settings.vehicle_model,
                tire_model=resolved_settings.tire_model,
            )
            run_id = video_result.run_id
            result['run_id'] = str(run_id)
            result['detection_counts'] = video_result.model_counts
            result['models_used'] = list(video_result.models_used)

            if resolved_settings.profile:
                try:
                    sanitized = apply_calibration_profile(run_id, resolved_settings.profile)
                    result['profile'] = sanitized
                except Exception as profile_exc:  # noqa: BLE001
                    message = f"プロファイル適用失敗: {profile_exc}"
                    print(f"[!] Run ID {run_id} のプロファイル適用に失敗: {profile_exc}")
                    existing_error = result.get('error')
                    result['error'] = f"{existing_error} / {message}" if existing_error else message

            postprocess_note: Optional[str] = None
            if resolved_settings.auto_csv:
                completed_steps, step_errors = run_postprocess_pipeline_sync(run_id)
                if step_errors:
                    joined = " / ".join(step_errors)
                    print(f"[!] Run ID {run_id} の後処理でエラー: {joined}")
                    postprocess_note = f"後処理エラー: {joined}"
                elif completed_steps:
                    postprocess_note = "後処理を即時実行 (" + " → ".join(completed_steps) + ")"

                try:
                    csv_path = create_all_save(run_id)
                    result['csv_path'] = csv_path
                    csv_outputs.append(csv_path)
                except Exception as csv_exc:  # noqa: BLE001
                    csv_error = f"CSV出力エラー: {csv_exc}"
                    print(f"[!] Run ID {run_id} のCSV出力でエラー: {csv_exc}")
                    existing_error = result.get('error')
                    result['error'] = f"{existing_error} / {csv_error}" if existing_error else csv_error

            if postprocess_note:
                result['postprocess'] = postprocess_note

            if (
                not resolved_settings.auto_csv
                and postprocess_handler
                and run_id
                and resolved_settings.auto_postprocess
            ):
                try:
                    postprocess_status = postprocess_handler(run_id, resolved_settings)
                except Exception as hook_exc:  # noqa: BLE001
                    postprocess_status = f"後処理登録エラー: {hook_exc}"
                if postprocess_status:
                    result['postprocess'] = postprocess_status
            
            # 追い越し集計を追加
            if run_id:
                try:
                    ov_stats = summarize_run_overtakes(run_id)
                    result['overtake_stats'] = ov_stats
                except Exception as e:
                    print(f"[!] Run ID {run_id} の追い越し集計に失敗: {e}")

        except Exception as exc:
            message = f"{exc}"
            print(f"[!] {video_path} の処理でエラー: {message}")
            result['error'] = message

        if folder_callback:
            folder_callback("video_done", index, total, display_name, result.copy())
        results.append(result)

    bundle_path: Optional[str] = None
    if csv_outputs:
        bundle_path = create_csv_bundle(csv_outputs, folder_alias=base_alias or None)

    if folder_callback:
        folder_callback("complete", total, total, None, None)

    return FolderProcessingResult(entries=results, csv_bundle_path=bundle_path)
