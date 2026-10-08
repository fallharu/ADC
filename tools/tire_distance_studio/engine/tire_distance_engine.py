# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import math
import re
import shutil
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


ENGINE_DIR = Path(__file__).resolve().parent
APP_DIR = ENGINE_DIR.parent
DEFAULT_CSV_PATH = APP_DIR / "outputs" / "bottom_center_tire_distance_results.csv"
DEFAULT_VIDEO_PATH = APP_DIR / "outputs" / "tire_distance_output.mp4"
DEFAULT_DATASET_DIR = APP_DIR / "datasets" / "tire_training_dataset"
DEFAULT_TRAIN_PROJECT_DIR = APP_DIR / "training" / "tire_training_runs"
DEFAULT_FULL_RETRAIN_DIR = APP_DIR / "training" / "full_tire_retraining"
DEFAULT_AUTO_TRAIN_DIR = APP_DIR / "training" / "auto_tire_training"
DEFAULT_CONVERTED_TIRE_MODEL_PATH = APP_DIR / "training" / "yolo26_tire_best.pt"
DEFAULT_TIRE_MODEL_PATH = APP_DIR / "models" / "best.pt"
# ベースモデルは大容量のため配布物に含めない。再学習時にUIから選択する。
DEFAULT_YOLO26_MODEL_PATH = APP_DIR / "models" / "yolo26x.pt"
DEFAULT_TRAIN_BASE_MODEL_PATH = DEFAULT_YOLO26_MODEL_PATH if DEFAULT_YOLO26_MODEL_PATH.exists() else DEFAULT_TIRE_MODEL_PATH
DEFAULT_DEVICE = "auto"
DEFAULT_CONFIDENCE = 0.10
TRAINING_CLASS_ID = 0
TRAINING_CLASS_NAME = "Tire"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v"}

TIRE_POINT_CHOICES = (
    "center",
    "bottom_center",
    "bottom_left",
    "bottom_right",
    "nearest_bottom_corner",
    "nearest_any",
)
TIRE_POINT_LABELS = {
    "center": "タイヤ中心",
    "bottom_center": "タイヤ下端中央",
    "bottom_left": "タイヤ左下",
    "bottom_right": "タイヤ右下",
    "nearest_bottom_corner": "近い下端角",
    "nearest_any": "最も近い点",
}
TIRE_POINT_BY_LABEL = {label: key for key, label in TIRE_POINT_LABELS.items()}

CSV_COLUMNS = [
    "計算日時",
    "入力ファイル",
    "フレーム番号",
    "フレーム時刻秒",
    "画像幅",
    "画像高さ",
    "基準点",
    "基準点X",
    "基準点Y",
    "モデル",
    "デバイス",
    "クラスID",
    "クラス名",
    "信頼度",
    "タイヤ基準点",
    "タイヤ基準点X",
    "タイヤ基準点Y",
    "ピクセル距離",
    "タイヤ中心距離px",
    "タイヤ下端中央距離px",
    "タイヤ左下距離px",
    "タイヤ右下距離px",
    "近い下端角距離px",
    "最も近い点距離px",
]


@dataclass(frozen=True)
class TireRegion:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def center(self) -> tuple[float, float]:
        return ((self.left + self.right) / 2.0, (self.top + self.bottom) / 2.0)

    @property
    def bottom_center(self) -> tuple[float, float]:
        return ((self.left + self.right) / 2.0, self.bottom)

    @property
    def bottom_left(self) -> tuple[float, float]:
        return (self.left, self.bottom)

    @property
    def bottom_right(self) -> tuple[float, float]:
        return (self.right, self.bottom)


@dataclass(frozen=True)
class TireMeta:
    source_path: str = ""
    frame_index: Optional[int] = None
    frame_time_s: Optional[float] = None
    image_width: int = 0
    image_height: int = 0
    model_path: str = ""
    device: str = ""
    class_id: Optional[int] = None
    class_name: str = ""
    confidence: Optional[float] = None


def image_bottom_center(width: int, height: int) -> tuple[float, float]:
    return (float(width) / 2.0, float(height))


def point_distance_px(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def tire_points(tire: TireRegion) -> dict[str, tuple[float, float]]:
    return {
        "center": tire.center,
        "bottom_center": tire.bottom_center,
        "bottom_left": tire.bottom_left,
        "bottom_right": tire.bottom_right,
    }


def select_tire_point(
    reference_point: tuple[float, float],
    tire: TireRegion,
    point_name: str,
) -> tuple[str, tuple[float, float]]:
    points = tire_points(tire)
    if point_name == "nearest_bottom_corner":
        bottom_corners = {
            "bottom_left": points["bottom_left"],
            "bottom_right": points["bottom_right"],
        }
        return min(
            bottom_corners.items(),
            key=lambda item: point_distance_px(reference_point, item[1]),
        )
    if point_name == "nearest_any":
        return min(
            points.items(),
            key=lambda item: point_distance_px(reference_point, item[1]),
        )
    return point_name, points[point_name]


def distance_report(
    reference_point: tuple[float, float],
    tire: TireRegion,
    tire_point: str,
) -> dict[str, object]:
    selected_name, selected_point = select_tire_point(reference_point, tire, tire_point)
    distances = {
        name: point_distance_px(reference_point, point)
        for name, point in tire_points(tire).items()
    }
    distances["nearest_bottom_corner"] = min(
        distances["bottom_left"],
        distances["bottom_right"],
    )
    distances["nearest_any"] = min(
        distances["center"],
        distances["bottom_center"],
        distances["bottom_left"],
        distances["bottom_right"],
    )

    return {
        "reference_point": reference_point,
        "tire_point_name": selected_name,
        "tire_point": selected_point,
        "distance_px": point_distance_px(reference_point, selected_point),
        "all_distances_px": distances,
    }


def fmt_point(point: Sequence[float]) -> str:
    return f"({float(point[0]):.2f}, {float(point[1]):.2f})"


def default_output_video_path(source_path: Path) -> Path:
    return source_path.with_name(f"{source_path.stem}_tire_distance.mp4")


def select_output_detections(
    detections: list[tuple[TireRegion, TireMeta]],
    reference_point: tuple[float, float],
    tire_point: str,
    nearest_only: bool,
) -> list[tuple[TireRegion, TireMeta]]:
    if not nearest_only or not detections:
        return detections
    return [
        min(
            detections,
            key=lambda item: point_distance_px(
                reference_point,
                select_tire_point(reference_point, item[0], tire_point)[1],
            ),
        )
    ]


def cv_point(point: Sequence[float]) -> tuple[int, int]:
    return (int(round(float(point[0]))), int(round(float(point[1]))))


def draw_text_box(
    cv2_module: object,
    frame: object,
    text: str,
    origin: tuple[int, int],
    *,
    text_color: tuple[int, int, int] = (255, 255, 255),
    background_color: tuple[int, int, int] = (0, 0, 0),
) -> None:
    cv2 = cv2_module
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.55
    thickness = 1
    (width, height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    x, y = origin
    x = max(0, x)
    y = max(height + 6, y)
    cv2.rectangle(
        frame,
        (x - 3, y - height - 5),
        (x + width + 3, y + baseline + 3),
        background_color,
        -1,
    )
    cv2.putText(frame, text, (x, y), font, font_scale, text_color, thickness, cv2.LINE_AA)


def draw_annotated_frame(
    cv2_module: object,
    frame: object,
    detections: list[tuple[TireRegion, TireMeta]],
    reference_point: tuple[float, float],
    tire_point: str,
) -> object:
    cv2 = cv2_module
    annotated = frame.copy()
    reference_xy = cv_point(reference_point)

    cv2.circle(annotated, reference_xy, 7, (0, 0, 255), -1)
    draw_text_box(cv2, annotated, "bottom center", (reference_xy[0] + 8, reference_xy[1] - 12))

    for tire, meta in detections:
        selected_name, selected_point = select_tire_point(reference_point, tire, tire_point)
        selected_xy = cv_point(selected_point)
        distance_px = point_distance_px(reference_point, selected_point)
        left, top = cv_point((tire.left, tire.top))
        right, bottom = cv_point((tire.right, tire.bottom))

        cv2.rectangle(annotated, (left, top), (right, bottom), (0, 220, 0), 2)
        cv2.line(annotated, reference_xy, selected_xy, (255, 255, 0), 2)
        cv2.circle(annotated, selected_xy, 5, (255, 0, 0), -1)

        confidence_text = "" if meta.confidence is None else f" conf={meta.confidence:.2f}"
        label = f"tire {distance_px:.1f}px{confidence_text}"
        draw_text_box(cv2, annotated, label, (left, max(20, top - 6)), background_color=(0, 90, 0))

        point_label = TIRE_POINT_LABELS.get(selected_name, selected_name)
        if point_label != TIRE_POINT_LABELS.get(tire_point, tire_point):
            draw_text_box(cv2, annotated, selected_name, (selected_xy[0] + 6, selected_xy[1] - 8))

    return annotated


def video_fourcc_for_path(cv2_module: object, video_path: Path) -> int:
    cv2 = cv2_module
    if video_path.suffix.lower() == ".avi":
        return cv2.VideoWriter_fourcc(*"XVID")
    return cv2.VideoWriter_fourcc(*"mp4v")


def build_result_text(report: Mapping[str, object]) -> str:
    tire_point_name = str(report["tire_point_name"])
    tire_point_label = TIRE_POINT_LABELS.get(tire_point_name, tire_point_name)
    lines = [
        f"画像下中央: {fmt_point(report['reference_point'])}",
        f"タイヤ基準点[{tire_point_label}]: {fmt_point(report['tire_point'])}",
        f"ピクセル距離: {float(report['distance_px']):.3f} px",
        "",
        "基準点別ピクセル距離:",
    ]

    distances = report["all_distances_px"]
    if isinstance(distances, Mapping):
        for name in TIRE_POINT_CHOICES:
            label = TIRE_POINT_LABELS.get(name, name)
            lines.append(f"  {label}: {float(distances[name]):.3f} px")
    return "\n".join(lines)


def result_to_csv_row(
    tire: TireRegion,
    report: Mapping[str, object],
    meta: Optional[TireMeta] = None,
) -> dict[str, object]:
    reference_point = report["reference_point"]
    tire_point = report["tire_point"]
    distances = report["all_distances_px"]
    if not isinstance(reference_point, Sequence) or not isinstance(tire_point, Sequence):
        raise ValueError("計算結果の座標形式が不正です。")
    if not isinstance(distances, Mapping):
        raise ValueError("計算結果の距離形式が不正です。")

    tire_point_name = str(report["tire_point_name"])
    meta = meta or TireMeta()
    return {
        "計算日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "入力ファイル": meta.source_path,
        "フレーム番号": "" if meta.frame_index is None else meta.frame_index,
        "フレーム時刻秒": "" if meta.frame_time_s is None else meta.frame_time_s,
        "画像幅": meta.image_width,
        "画像高さ": meta.image_height,
        "基準点": "画像下中央",
        "基準点X": float(reference_point[0]),
        "基準点Y": float(reference_point[1]),
        "モデル": meta.model_path,
        "デバイス": meta.device,
        "クラスID": "" if meta.class_id is None else meta.class_id,
        "クラス名": meta.class_name,
        "信頼度": "" if meta.confidence is None else meta.confidence,
        "タイヤ基準点": TIRE_POINT_LABELS.get(tire_point_name, tire_point_name),
        "タイヤ基準点X": float(tire_point[0]),
        "タイヤ基準点Y": float(tire_point[1]),
        "ピクセル距離": float(report["distance_px"]),
        "タイヤ中心距離px": float(distances["center"]),
        "タイヤ下端中央距離px": float(distances["bottom_center"]),
        "タイヤ左下距離px": float(distances["bottom_left"]),
        "タイヤ右下距離px": float(distances["bottom_right"]),
        "近い下端角距離px": float(distances["nearest_bottom_corner"]),
        "最も近い点距離px": float(distances["nearest_any"]),
    }


def append_csv(csv_path: Path, row: Mapping[str, object]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    exists = csv_path.exists() and csv_path.stat().st_size > 0
    with csv_path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not exists:
            writer.writeheader()
        writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})


def class_name_from_model(names: object, class_id: Optional[int]) -> str:
    if class_id is None:
        return ""
    if isinstance(names, Mapping):
        return str(names.get(class_id, names.get(str(class_id), "")))
    if isinstance(names, Sequence) and not isinstance(names, (str, bytes)):
        if 0 <= class_id < len(names):
            return str(names[class_id])
    return ""


def is_tire_class(class_id: Optional[int], class_name: str) -> bool:
    name = class_name.lower()
    if "plate" in name or "number" in name:
        return False
    if "tire" in name or "tyre" in name or "wheel" in name or "タイヤ" in name:
        return True
    return class_id in {0, 2, 100, 102}


def resolve_gpu_device(device_text: str) -> str:
    raw = (device_text or DEFAULT_DEVICE).strip()
    lowered = raw.lower()
    if lowered == "auto":
        try:
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                import torch

                if not torch.cuda.is_available() or torch.cuda.device_count() <= 0:
                    return "cpu"
                gpu_index = 0
                cuda_device = f"cuda:{gpu_index}"
                dummy = torch.randn(1, 1, 3, 3, device=cuda_device)
                kernel = torch.randn(1, 1, 1, 1, device=cuda_device)
                torch.nn.functional.conv2d(dummy, kernel)
                torch.cuda.synchronize(gpu_index)
                return str(gpu_index)
        except Exception:
            return "cpu"
    if lowered == "cpu":
        return "cpu"

    gpu_index: Optional[int] = None
    if lowered in {"gpu", "cuda"}:
        gpu_index = 0
    elif lowered.startswith("cuda:"):
        try:
            gpu_index = int(lowered.split(":", 1)[1])
        except ValueError as exc:
            raise RuntimeError(f"GPUデバイス指定が不正です: {raw}") from exc
    elif raw.isdigit():
        gpu_index = int(raw)

    if gpu_index is None:
        return raw

    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("GPU処理には torch が必要です。") from exc

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPUが利用できません。GPUで処理するにはCUDA対応のPyTorch環境が必要です。")
    if gpu_index >= torch.cuda.device_count():
        raise RuntimeError(f"GPU {gpu_index} が見つかりません。")

    try:
        cuda_device = f"cuda:{gpu_index}"
        dummy = torch.randn(1, 1, 3, 3, device=cuda_device)
        kernel = torch.randn(1, 1, 1, 1, device=cuda_device)
        torch.nn.functional.conv2d(dummy, kernel)
        torch.cuda.synchronize(gpu_index)
    except Exception as exc:
        gpu_name = torch.cuda.get_device_name(gpu_index)
        raise RuntimeError(
            "CUDA GPUは検出されましたが、PyTorchのCUDA演算に失敗しました。"
            f" GPU={gpu_name}。このGPUに対応したPyTorch/CUDAを入れてください。"
            " 一時的にCPUで処理する場合は --device cpu を指定してください。"
        ) from exc

    return str(gpu_index)


def resolve_tire_model_path(model_path_text: str) -> Path:
    raw = model_path_text.strip() if model_path_text else str(DEFAULT_TIRE_MODEL_PATH)
    path = Path(raw).expanduser()
    if path.is_absolute() and path.exists():
        return path
    candidates = [
        (Path.cwd() / path).resolve(),
        (APP_DIR / path).resolve(),
        (APP_DIR.parent / path).resolve(),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"タイヤモデルが見つかりません: {raw}")


def patch_ultralytics_yolo26_compat() -> bool:
    try:
        import inspect

        import torch
        from torch import nn
        from ultralytics.nn.modules import block as block_module
        import ultralytics.nn.tasks as tasks_module
    except Exception:
        return False

    patched = False
    sppf_class = getattr(block_module, "SPPF", None)
    try:
        signature = inspect.signature(sppf_class.__init__) if sppf_class is not None else None
    except Exception:
        signature = None

    conv_class = getattr(block_module, "Conv", None)
    if conv_class is None:
        return False

    if signature is None or "n" not in signature.parameters or "shortcut" not in signature.parameters:
        class YOLO26SPPF(nn.Module):
            def __init__(self, c1: int, c2: int, k: int = 5, n: int = 3, shortcut: bool = False):
                super().__init__()
                c_ = c1 // 2
                self.cv1 = conv_class(c1, c_, 1, 1, act=False)
                self.cv2 = conv_class(c_ * (int(n) + 1), c2, 1, 1)
                self.m = nn.MaxPool2d(kernel_size=k, stride=1, padding=k // 2)
                self.n = int(n)
                self.add = bool(shortcut) and c1 == c2

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                y = [self.cv1(x)]
                y.extend(self.m(y[-1]) for _ in range(int(getattr(self, "n", 3))))
                out = self.cv2(torch.cat(y, 1))
                return out + x if getattr(self, "add", False) else out

        YOLO26SPPF.__name__ = "SPPF"
        YOLO26SPPF.__qualname__ = "SPPF"
        YOLO26SPPF.__module__ = block_module.__name__
        setattr(block_module, "SPPF", YOLO26SPPF)
        setattr(tasks_module, "SPPF", YOLO26SPPF)
        patched = True

    c3k2_class = getattr(block_module, "C3k2", None)
    try:
        c3k2_signature = inspect.signature(c3k2_class.__init__) if c3k2_class is not None else None
    except Exception:
        c3k2_signature = None
    if c3k2_signature is None or "attn" not in c3k2_signature.parameters:
        c2f_class = getattr(block_module, "C2f", None)
        c3k_class = getattr(block_module, "C3k", None)
        bottleneck_class = getattr(block_module, "Bottleneck", None)
        psa_block_class = getattr(block_module, "PSABlock", None)
        if all((c2f_class, c3k_class, bottleneck_class, psa_block_class)):
            class YOLO26C3k2(c2f_class):
                def __init__(
                    self,
                    c1: int,
                    c2: int,
                    n: int = 1,
                    c3k: bool = False,
                    e: float = 0.5,
                    attn: bool = False,
                    g: int = 1,
                    shortcut: bool = True,
                ):
                    super().__init__(c1, c2, n, shortcut, int(g), e)
                    self.m = nn.ModuleList(
                        nn.Sequential(
                            bottleneck_class(self.c, self.c, shortcut, int(g)),
                            psa_block_class(self.c, attn_ratio=0.5, num_heads=max(self.c // 64, 1)),
                        )
                        if attn
                        else c3k_class(self.c, self.c, 2, shortcut, int(g))
                        if c3k
                        else bottleneck_class(self.c, self.c, shortcut, int(g))
                        for _ in range(n)
                    )

            YOLO26C3k2.__name__ = "C3k2"
            YOLO26C3k2.__qualname__ = "C3k2"
            YOLO26C3k2.__module__ = block_module.__name__
            setattr(block_module, "C3k2", YOLO26C3k2)
            setattr(tasks_module, "C3k2", YOLO26C3k2)
            patched = True

    return patched


def patch_ultralytics_yolo26_sppf() -> bool:
    return patch_ultralytics_yolo26_compat()


def frame_size_from_result(result: object) -> tuple[int, int]:
    shape = getattr(result, "orig_shape", None)
    if shape is not None and len(shape) >= 2:
        return int(shape[1]), int(shape[0])

    image = getattr(result, "orig_img", None)
    image_shape = getattr(image, "shape", None)
    if image_shape is not None and len(image_shape) >= 2:
        return int(image_shape[1]), int(image_shape[0])

    return 0, 0


def regions_from_yolo_result(
    result: object,
    names: object,
    *,
    source_path: Path,
    frame_index: Optional[int],
    frame_time_s: Optional[float],
    image_width: int,
    image_height: int,
    model_path: Path,
    device: str,
) -> list[tuple[TireRegion, TireMeta]]:
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return []

    try:
        xyxy_values = boxes.xyxy.detach().cpu().tolist()
    except Exception:
        xyxy_values = []
    try:
        cls_values = boxes.cls.detach().cpu().tolist()
    except Exception:
        cls_values = [None] * len(xyxy_values)
    try:
        conf_values = boxes.conf.detach().cpu().tolist()
    except Exception:
        conf_values = [None] * len(xyxy_values)

    detections: list[tuple[TireRegion, TireMeta]] = []
    for idx, xyxy in enumerate(xyxy_values):
        if len(xyxy) != 4:
            continue
        class_id = None
        if idx < len(cls_values) and cls_values[idx] is not None:
            try:
                class_id = int(cls_values[idx])
            except (TypeError, ValueError):
                class_id = None
        class_name = class_name_from_model(names, class_id)
        if not is_tire_class(class_id, class_name):
            continue

        confidence = None
        if idx < len(conf_values) and conf_values[idx] is not None:
            try:
                confidence = float(conf_values[idx])
            except (TypeError, ValueError):
                confidence = None

        tire = TireRegion(
            left=float(xyxy[0]),
            top=float(xyxy[1]),
            right=float(xyxy[2]),
            bottom=float(xyxy[3]),
        )
        meta = TireMeta(
            source_path=str(source_path),
            frame_index=frame_index,
            frame_time_s=frame_time_s,
            image_width=image_width,
            image_height=image_height,
            model_path=str(model_path),
            device=device,
            class_id=class_id,
            class_name=class_name,
            confidence=confidence,
        )
        detections.append((tire, meta))
    return detections


def run_tire_model_gpu_to_csv(
    *,
    source_path: Path,
    tire_point: str,
    model_path: Path,
    csv_path: Path,
    output_video_path: Optional[Path],
    device: str,
    conf: float,
    imgsz: int,
    frame_step: int,
    max_frames: int,
    nearest_only: bool,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> int:
    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {source_path}")

    device = resolve_gpu_device(device)
    frame_step = max(1, int(frame_step))
    max_frames = max(0, int(max_frames))

    def emit(message: str) -> None:
        if progress_cb is not None:
            progress_cb(message)

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("タイヤモデル処理には ultralytics が必要です。") from exc

    patched_sppf = patch_ultralytics_yolo26_sppf()
    emit(f"タイヤモデルを読み込み中: {model_path}")
    if patched_sppf:
        emit("YOLO26互換パッチを適用しました。")
    model = YOLO(str(model_path))
    names = getattr(model, "names", {})
    saved_count = 0

    def save_detections(
        detections: list[tuple[TireRegion, TireMeta]],
        *,
        image_width: int,
        image_height: int,
    ) -> int:
        reference_point = image_bottom_center(image_width, image_height)

        local_count = 0
        for tire, meta in detections:
            report = distance_report(reference_point, tire, tire_point)
            append_csv(csv_path, result_to_csv_row(tire, report, meta))
            local_count += 1
        return local_count

    suffix = source_path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        emit(f"画像を推論中: device={device}")
        results = model.predict(
            str(source_path),
            conf=conf,
            imgsz=imgsz,
            device=device,
            verbose=False,
        )
        detections: list[tuple[TireRegion, TireMeta]] = []
        image_width = 0
        image_height = 0
        if results:
            image_width, image_height = frame_size_from_result(results[0])
            detections = regions_from_yolo_result(
                results[0],
                names,
                source_path=source_path,
                frame_index=0,
                frame_time_s=0.0,
                image_width=image_width,
                image_height=image_height,
                model_path=model_path,
                device=device,
            )
        if image_width <= 0 or image_height <= 0:
            raise RuntimeError("画像サイズを取得できませんでした。")

        reference_point = image_bottom_center(image_width, image_height)
        detections = select_output_detections(detections, reference_point, tire_point, nearest_only)
        saved_count += save_detections(
            detections,
            image_width=image_width,
            image_height=image_height,
        )
        if output_video_path is not None:
            emit("画像入力のため動画出力は行いません。")
        emit(f"完了: {saved_count}件をCSV保存しました。")
        return saved_count

    if suffix not in VIDEO_EXTENSIONS:
        raise ValueError(f"未対応の入力形式です: {source_path.suffix}")

    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("動画処理には opencv-python が必要です。") from exc

    cap = cv2.VideoCapture(str(source_path))
    if not cap.isOpened():
        raise RuntimeError(f"動画を開けません: {source_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    processed_frames = 0
    frame_index = -1
    emit(f"動画を推論中: device={device}, total_frames={total_frames}, frame_step={frame_step}")

    video_writer = None
    if output_video_path is not None:
        output_video_path.parent.mkdir(parents=True, exist_ok=True)
        emit(f"出力動画: {output_video_path}")

    def ensure_video_writer(frame: object) -> object:
        nonlocal video_writer
        if video_writer is not None:
            return video_writer
        if output_video_path is None:
            raise RuntimeError("動画出力パスが未指定です。")

        image_height, image_width = frame.shape[:2]
        output_fps = fps if fps > 0 else 30.0
        fourcc = video_fourcc_for_path(cv2, output_video_path)
        video_writer = cv2.VideoWriter(str(output_video_path), fourcc, output_fps, (image_width, image_height))
        if not video_writer.isOpened():
            raise RuntimeError(f"出力動画を作成できません: {output_video_path}")
        return video_writer

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame_index += 1
            if frame_index % frame_step != 0:
                if output_video_path is not None:
                    ensure_video_writer(frame).write(frame)
                continue
            if max_frames and processed_frames >= max_frames:
                break

            processed_frames += 1
            image_height, image_width = frame.shape[:2]
            frame_time_s = frame_index / fps if fps > 0 else None
            results = model.predict(
                frame,
                conf=conf,
                imgsz=imgsz,
                device=device,
                verbose=False,
            )
            detections: list[tuple[TireRegion, TireMeta]] = []
            if results:
                detections = regions_from_yolo_result(
                    results[0],
                    names,
                    source_path=source_path,
                    frame_index=frame_index,
                    frame_time_s=frame_time_s,
                    image_width=image_width,
                    image_height=image_height,
                    model_path=model_path,
                    device=device,
                )
            reference_point = image_bottom_center(image_width, image_height)
            detections = select_output_detections(detections, reference_point, tire_point, nearest_only)
            saved_count += save_detections(
                detections,
                image_width=image_width,
                image_height=image_height,
            )
            if output_video_path is not None:
                annotated = draw_annotated_frame(cv2, frame, detections, reference_point, tire_point)
                ensure_video_writer(frame).write(annotated)
            if processed_frames % 10 == 0:
                emit(f"処理中: {processed_frames}フレーム / CSV {saved_count}件")
    finally:
        cap.release()
        if video_writer is not None:
            video_writer.release()

    if output_video_path is not None:
        emit(f"動画を保存しました: {output_video_path}")
    emit(f"完了: {processed_frames}フレーム処理、{saved_count}件をCSV保存しました。")
    return saved_count


def sanitize_file_stem(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return safe.strip("._") or "sample"


def parse_float_list(value: str) -> list[float]:
    values: list[float] = []
    for part in re.split(r"[,、\s]+", value.strip()):
        if not part:
            continue
        number = float(part)
        if number <= 0 or number > 1:
            raise ValueError("conf は 0 より大きく 1 以下で指定してください。")
        values.append(number)
    if not values:
        raise ValueError("conf を1つ以上指定してください。")
    return values


def split_for_index(index: int, val_ratio: float) -> str:
    val_ratio = max(0.0, min(0.5, float(val_ratio)))
    if val_ratio <= 0:
        return "train"
    interval = max(2, round(1.0 / val_ratio))
    return "val" if index % interval == interval - 1 else "train"


def split_for_auto_sample(
    *,
    saved_index: int,
    local_index: int,
    source_index: int,
    source_count: int,
    val_ratio: float,
) -> str:
    val_ratio = max(0.0, min(0.5, float(val_ratio)))
    if val_ratio <= 0:
        return "train"
    interval = max(2, round(1.0 / val_ratio))
    if source_count >= interval:
        return "val" if source_index % interval == interval - 1 else "train"
    return "val" if saved_index % interval == interval - 1 else "train"


def safe_replace_dir(target_dir: Path, allowed_root: Path) -> None:
    target = target_dir.resolve()
    root = allowed_root.resolve()
    if target == root or root not in target.parents:
        raise RuntimeError(f"置換対象が出力ルート配下ではありません: {target}")
    if target.exists():
        shutil.rmtree(target)


def training_variant_name(run_name: str, *, replace_run: bool, suffix: str = "") -> str:
    base = sanitize_file_stem(run_name or "tire_retrain")
    name = f"{base}_{suffix}" if suffix else base
    if replace_run:
        return sanitize_file_stem(name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return sanitize_file_stem(f"{name}_{timestamp}")


def copy_model_as_separate_base(model_path: Path, output_dir: Path, run_name: str) -> Path:
    source = resolve_tire_model_path(str(model_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / f"{sanitize_file_stem(run_name)}_base{source.suffix or '.pt'}"
    shutil.copy2(source, dest)
    return dest


def copy_trained_model(best_path: Path, output_dir: Path, run_name: str) -> Path:
    if not best_path.exists():
        raise FileNotFoundError(f"学習済みモデルが見つかりません: {best_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / f"{sanitize_file_stem(run_name)}_best.pt"
    shutil.copy2(best_path, dest)
    return dest


def export_model_with_backup(best_path: Path, export_path: Path) -> Path:
    if not best_path.exists():
        raise FileNotFoundError(f"学習済みモデルが見つかりません: {best_path}")
    export_path.parent.mkdir(parents=True, exist_ok=True)
    if export_path.exists():
        backup_path = export_path.with_name(
            f"{export_path.stem}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}{export_path.suffix}"
        )
        shutil.copy2(export_path, backup_path)
    shutil.copy2(best_path, export_path)
    return export_path


def iter_training_source_files(source_path: Path) -> list[Path]:
    if not source_path.exists():
        raise FileNotFoundError(f"入力パスが見つかりません: {source_path}")
    if source_path.is_file():
        suffix = source_path.suffix.lower()
        if suffix in IMAGE_EXTENSIONS or suffix in VIDEO_EXTENSIONS:
            return [source_path]
        raise ValueError(f"未対応の入力形式です: {source_path.suffix}")
    if not source_path.is_dir():
        raise ValueError(f"入力パスはファイルまたはフォルダを指定してください: {source_path}")

    files = [
        path
        for path in source_path.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS.union(VIDEO_EXTENSIONS)
    ]
    files.sort(key=lambda path: str(path).lower())
    if not files:
        raise RuntimeError(f"フォルダ内に対応する画像/動画がありません: {source_path}")
    return files


def ensure_yolo_dataset(dataset_dir: Path) -> Path:
    for split in ("train", "val"):
        (dataset_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (dataset_dir / "labels" / split).mkdir(parents=True, exist_ok=True)
    return write_yolo_data_yaml(dataset_dir)


def count_dataset_images(dataset_dir: Path, split: str) -> int:
    image_dir = dataset_dir / "images" / split
    if not image_dir.exists():
        return 0
    return sum(1 for path in image_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)


def ensure_label_files_for_images(dataset_dir: Path) -> int:
    created_count = 0
    ensure_yolo_dataset(dataset_dir)
    for split in ("train", "val"):
        image_dir = dataset_dir / "images" / split
        label_dir = dataset_dir / "labels" / split
        if not image_dir.exists():
            continue
        for image_path in image_dir.iterdir():
            if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            label_path = label_dir / f"{image_path.stem}.txt"
            if label_path.exists():
                continue
            label_path.write_text("", encoding="utf-8")
            created_count += 1
    return created_count


def write_yolo_data_yaml(dataset_dir: Path) -> Path:
    dataset_dir = dataset_dir.resolve()
    dataset_dir.mkdir(parents=True, exist_ok=True)
    val_rel = "images/val" if count_dataset_images(dataset_dir, "val") else "images/train"
    data_yaml = dataset_dir / "data.yaml"
    text = "\n".join(
        [
            f"path: {dataset_dir.as_posix()}",
            "train: images/train",
            f"val: {val_rel}",
            "names:",
            f"  {TRAINING_CLASS_ID}: {TRAINING_CLASS_NAME}",
            "",
        ]
    )
    data_yaml.write_text(text, encoding="utf-8")
    return data_yaml


def tire_region_to_yolo_line(tire: TireRegion, image_width: int, image_height: int) -> Optional[str]:
    left = max(0.0, min(float(image_width), min(tire.left, tire.right)))
    right = max(0.0, min(float(image_width), max(tire.left, tire.right)))
    top = max(0.0, min(float(image_height), min(tire.top, tire.bottom)))
    bottom = max(0.0, min(float(image_height), max(tire.top, tire.bottom)))
    width = right - left
    height = bottom - top
    if width < 2.0 or height < 2.0 or image_width <= 0 or image_height <= 0:
        return None

    x_center = (left + right) / 2.0 / float(image_width)
    y_center = (top + bottom) / 2.0 / float(image_height)
    norm_width = width / float(image_width)
    norm_height = height / float(image_height)
    return f"{TRAINING_CLASS_ID} {x_center:.6f} {y_center:.6f} {norm_width:.6f} {norm_height:.6f}"


def save_yolo_annotation_sample(
    *,
    image_bgr: object,
    regions: Sequence[TireRegion],
    dataset_dir: Path,
    split: str,
    sample_stem: str,
) -> tuple[Path, Path, int]:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("アノテーション保存には opencv-python が必要です。") from exc

    if split not in {"train", "val"}:
        raise ValueError("split は train または val を指定してください。")

    ensure_yolo_dataset(dataset_dir)
    image_height, image_width = image_bgr.shape[:2]
    safe_stem = sanitize_file_stem(sample_stem)
    image_path = dataset_dir / "images" / split / f"{safe_stem}.jpg"
    label_path = dataset_dir / "labels" / split / f"{safe_stem}.txt"

    if not cv2.imwrite(str(image_path), image_bgr):
        raise RuntimeError(f"画像を保存できません: {image_path}")

    lines = []
    for region in regions:
        line = tire_region_to_yolo_line(region, image_width, image_height)
        if line is not None:
            lines.append(line)
    label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    data_yaml = write_yolo_data_yaml(dataset_dir)
    return image_path, label_path, len(lines)


def run_tire_model_training(
    *,
    dataset_dir: Path,
    base_model_path: Path,
    project_dir: Path,
    run_name: str,
    device: str,
    epochs: int,
    imgsz: int,
    batch: int,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Path:
    def emit(message: str) -> None:
        if progress_cb is not None:
            progress_cb(message)

    created_label_count = ensure_label_files_for_images(dataset_dir)
    train_count = count_dataset_images(dataset_dir, "train")
    val_count = count_dataset_images(dataset_dir, "val")
    if train_count <= 0:
        raise RuntimeError("train画像がありません。先にアノテーションを保存してください。")

    data_yaml = write_yolo_data_yaml(dataset_dir)
    model_path = resolve_tire_model_path(str(base_model_path))
    resolved_device = resolve_gpu_device(device)
    epochs = max(1, int(epochs))
    imgsz = max(32, int(imgsz))
    batch = max(1, int(batch))
    run_name = sanitize_file_stem(run_name or "tire_retrain")
    project_dir.mkdir(parents=True, exist_ok=True)

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("再トレーニングには ultralytics が必要です。") from exc

    patched_sppf = patch_ultralytics_yolo26_sppf()
    emit(f"学習データ: {data_yaml}")
    emit(f"train画像: {train_count}件 / val画像: {val_count}件")
    if created_label_count:
        emit(f"不足していた空ラベルを作成: {created_label_count}件")
    emit(f"ベースモデル: {model_path}")
    if patched_sppf:
        emit("YOLO26互換パッチを適用しました。")
    emit(f"学習開始: epochs={epochs}, imgsz={imgsz}, batch={batch}, device={resolved_device}")

    model = YOLO(str(model_path))
    result = model.train(
        data=str(data_yaml),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=resolved_device,
        project=str(project_dir),
        name=run_name,
        exist_ok=True,
    )

    save_dir = Path(getattr(result, "save_dir", project_dir / run_name))
    best_path = save_dir / "weights" / "best.pt"
    if not best_path.exists():
        candidate = project_dir / run_name / "weights" / "best.pt"
        if candidate.exists():
            best_path = candidate
    emit(f"学習完了: {best_path}")
    return best_path


def run_full_retraining(
    *,
    dataset_dir: Path,
    base_model_path: Path,
    output_root: Path,
    run_name: str,
    device: str,
    epochs: int,
    imgsz: int,
    batch: int,
    replace_run: bool = False,
    export_model_path: Optional[Path] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict[str, object]:
    def emit(message: str) -> None:
        if progress_cb is not None:
            progress_cb(message)

    variant_name = training_variant_name(run_name or "tire_retrain", replace_run=replace_run)
    variant_dir = output_root / variant_name
    model_dir = variant_dir / "models"
    project_dir = variant_dir / "runs"
    output_root.mkdir(parents=True, exist_ok=True)
    if replace_run:
        safe_replace_dir(variant_dir, output_root)

    emit(f"フル再トレーニングrun: {variant_name}")
    if replace_run:
        emit("既存runを置き換えます。")
    copied_base = copy_model_as_separate_base(base_model_path, model_dir, variant_name)
    emit(f"元モデルをコピー: {copied_base}")

    best_path = run_tire_model_training(
        dataset_dir=dataset_dir,
        base_model_path=copied_base,
        project_dir=project_dir,
        run_name=variant_name,
        device=device,
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        progress_cb=emit,
    )
    final_model = copy_trained_model(best_path, model_dir, variant_name)
    emit(f"別モデルとして保存: {final_model}")
    exported_model = None
    if export_model_path is not None:
        exported_model = export_model_with_backup(final_model, export_model_path)
        emit(f"変換済みタイヤモデルを入れ替え保存: {exported_model}")

    return {
        "run_name": variant_name,
        "variant_dir": variant_dir,
        "dataset_dir": dataset_dir,
        "copied_base_model": copied_base,
        "best_path": best_path,
        "final_model": final_model,
        "exported_model": exported_model,
    }


def auto_label_dataset_from_model(
    *,
    source_path: Path,
    model_path: Path,
    dataset_dir: Path,
    conf: float,
    device: str,
    imgsz: int,
    frame_step: int,
    max_frames: int,
    val_ratio: float,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    def emit(message: str) -> None:
        if progress_cb is not None:
            progress_cb(message)

    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("自動アノテーションには opencv-python が必要です。") from exc
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("自動アノテーションには ultralytics が必要です。") from exc

    patched_sppf = patch_ultralytics_yolo26_sppf()
    resolved_device = resolve_gpu_device(device)
    model = YOLO(str(resolve_tire_model_path(str(model_path))))
    names = getattr(model, "names", {})
    frame_step = max(1, int(frame_step))
    max_frames = max(0, int(max_frames))
    imgsz = max(32, int(imgsz))
    conf = float(conf)
    source_files = iter_training_source_files(source_path)

    ensure_yolo_dataset(dataset_dir)
    if patched_sppf:
        emit("YOLO26互換パッチを適用しました。")
    saved_images = 0
    saved_boxes = 0

    def predict_and_save(
        current_source_path: Path,
        image_bgr: object,
        sample_stem: str,
        source_frame_index: int,
        *,
        source_index: int,
        local_index: int,
    ) -> bool:
        nonlocal saved_images, saved_boxes
        image_height, image_width = image_bgr.shape[:2]
        results = model.predict(
            image_bgr,
            conf=conf,
            imgsz=imgsz,
            device=resolved_device,
            verbose=False,
        )
        detections: list[tuple[TireRegion, TireMeta]] = []
        if results:
            detections = regions_from_yolo_result(
                results[0],
                names,
                source_path=current_source_path,
                frame_index=source_frame_index,
                frame_time_s=None,
                image_width=image_width,
                image_height=image_height,
                model_path=model_path,
                device=resolved_device,
        )
        regions = [tire for tire, _meta in detections]
        if not regions:
            return False

        split = split_for_auto_sample(
            saved_index=saved_images,
            local_index=local_index,
            source_index=source_index,
            source_count=len(source_files),
            val_ratio=val_ratio,
        )
        image_path, _label_path, count = save_yolo_annotation_sample(
            image_bgr=image_bgr,
            regions=regions,
            dataset_dir=dataset_dir,
            split=split,
            sample_stem=sample_stem,
        )
        saved_images += 1
        saved_boxes += count
        if saved_images % 10 == 0:
            emit(f"自動ラベル作成中: images={saved_images}, bbox={saved_boxes}, last={image_path.name}")
        return True

    emit(f"自動ラベル元: {len(source_files)}ファイル")
    for file_index, current_source_path in enumerate(source_files):
        suffix = current_source_path.suffix.lower()
        emit(f"[{file_index + 1}/{len(source_files)}] {current_source_path}")
        if suffix in IMAGE_EXTENSIONS:
            image = cv2.imread(str(current_source_path))
            if image is None:
                emit(f"画像を読み込めないためスキップ: {current_source_path}")
                continue
            stem = sanitize_file_stem(f"{current_source_path.stem}_conf{conf:.3f}")
            predict_and_save(current_source_path, image, stem, 0, source_index=file_index, local_index=0)
        elif suffix in VIDEO_EXTENSIONS:
            cap = cv2.VideoCapture(str(current_source_path))
            if not cap.isOpened():
                emit(f"動画を開けないためスキップ: {current_source_path}")
                continue
            frame_index = -1
            local_saved = 0
            try:
                while max_frames == 0 or local_saved < max_frames:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    frame_index += 1
                    if frame_index % frame_step != 0:
                        continue
                    stem = sanitize_file_stem(f"{current_source_path.stem}_conf{conf:.3f}_f{frame_index:06d}")
                    if predict_and_save(
                        current_source_path,
                        frame,
                        stem,
                        frame_index,
                        source_index=file_index,
                        local_index=local_saved,
                    ):
                        local_saved += 1
            finally:
                cap.release()
        else:
            emit(f"未対応形式のためスキップ: {current_source_path}")

    write_yolo_data_yaml(dataset_dir)
    if saved_images <= 0:
        raise RuntimeError(f"conf={conf:.3f} でタイヤの自動ラベルを作成できませんでした。")
    emit(f"自動ラベル作成完了: conf={conf:.3f}, images={saved_images}, bbox={saved_boxes}")
    return saved_images, saved_boxes


def run_auto_conf_training(
    *,
    source_path: Path,
    base_model_path: Path,
    label_model_path: Path,
    output_root: Path,
    run_name: str,
    conf_values: Sequence[float],
    device: str,
    epochs: int,
    imgsz: int,
    batch: int,
    frame_step: int,
    max_frames: int,
    val_ratio: float,
    replace_run: bool = False,
    export_model_path: Optional[Path] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> list[dict[str, object]]:
    def emit(message: str) -> None:
        if progress_cb is not None:
            progress_cb(message)

    if not conf_values:
        raise ValueError("conf候補を1つ以上指定してください。")

    base_model = resolve_tire_model_path(str(base_model_path))
    label_model = resolve_tire_model_path(str(label_model_path))
    output_root.mkdir(parents=True, exist_ok=True)
    base_run_name = sanitize_file_stem(run_name or "auto_tire_train")
    results: list[dict[str, object]] = []

    emit(f"元モデル: {base_model}")
    emit(f"自動ラベル用モデル: {label_model}")
    emit(f"自動学習出力先: {output_root}")

    for conf in conf_values:
        conf_tag = f"conf{float(conf):.3f}".replace(".", "p")
        variant_name = training_variant_name(base_run_name, replace_run=replace_run, suffix=conf_tag)
        variant_dir = output_root / variant_name
        model_dir = variant_dir / "models"
        dataset_dir = variant_dir / "dataset"
        project_dir = variant_dir / "runs"
        if replace_run:
            safe_replace_dir(variant_dir, output_root)

        emit("")
        emit(f"=== 自動学習開始: {variant_name} ===")
        if replace_run:
            emit("既存runを置き換えます。")
        copied_base = copy_model_as_separate_base(base_model, model_dir, variant_name)
        emit(f"元モデルをコピー: {copied_base}")

        image_count, box_count = auto_label_dataset_from_model(
            source_path=source_path,
            model_path=label_model,
            dataset_dir=dataset_dir,
            conf=float(conf),
            device=device,
            imgsz=imgsz,
            frame_step=frame_step,
            max_frames=max_frames,
            val_ratio=val_ratio,
            progress_cb=emit,
        )

        best_path = run_tire_model_training(
            dataset_dir=dataset_dir,
            base_model_path=copied_base,
            project_dir=project_dir,
            run_name=variant_name,
            device=device,
            epochs=epochs,
            imgsz=imgsz,
            batch=batch,
            progress_cb=emit,
        )
        final_model = copy_trained_model(best_path, model_dir, variant_name)
        emit(f"別モデルとして保存: {final_model}")
        exported_model = None
        if export_model_path is not None:
            target = export_model_path
            if len(conf_values) > 1:
                target = export_model_path.with_name(f"{export_model_path.stem}_{conf_tag}{export_model_path.suffix}")
            exported_model = export_model_with_backup(final_model, target)
            emit(f"変換済みタイヤモデルを入れ替え保存: {exported_model}")

        results.append(
            {
                "conf": float(conf),
                "dataset_dir": dataset_dir,
                "copied_base_model": copied_base,
                "best_path": best_path,
                "final_model": final_model,
                "exported_model": exported_model,
                "image_count": image_count,
                "box_count": box_count,
            }
        )

    emit("")
    emit(f"自動学習完了: {len(results)} run")
    return results


def launch_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    from PIL import Image, ImageTk

    tire_point_labels = [TIRE_POINT_LABELS[key] for key in TIRE_POINT_CHOICES]

    class AnnotationTrainWindow(tk.Toplevel):
        def __init__(self, master: tk.Tk) -> None:
            super().__init__(master)
            self.title("タイヤアノテーション / 再トレーニング")
            self.geometry("1120x760")
            self.minsize(980, 680)

            self.dataset_dir_var = tk.StringVar(value=str(DEFAULT_DATASET_DIR))
            self.annotation_source_var = tk.StringVar()
            self.split_var = tk.StringVar(value="auto")
            self.frame_step_var = tk.StringVar(value="30")
            self.max_frames_var = tk.StringVar(value="30")
            self.base_model_var = tk.StringVar(value=str(DEFAULT_TRAIN_BASE_MODEL_PATH))
            self.train_project_var = tk.StringVar(value=str(DEFAULT_FULL_RETRAIN_DIR))
            self.train_name_var = tk.StringVar(value="tire_retrain")
            self.train_device_var = tk.StringVar(value=DEFAULT_DEVICE)
            self.train_epochs_var = tk.StringVar(value="50")
            self.train_imgsz_var = tk.StringVar(value="640")
            self.train_batch_var = tk.StringVar(value="8")
            self.auto_label_model_var = tk.StringVar(value=str(DEFAULT_TIRE_MODEL_PATH))
            self.auto_conf_values_var = tk.StringVar(value="0.05,0.10,0.20")
            self.auto_output_root_var = tk.StringVar(value=str(DEFAULT_AUTO_TRAIN_DIR))
            self.auto_val_ratio_var = tk.StringVar(value="0.20")
            self.export_model_path_var = tk.StringVar(value=str(DEFAULT_CONVERTED_TIRE_MODEL_PATH))
            self.replace_run_var = tk.BooleanVar(value=False)

            self.samples: list[dict[str, object]] = []
            self.sample_index = 0
            self.display_scale = 1.0
            self.tk_image: Optional[ImageTk.PhotoImage] = None
            self.drag_start: Optional[tuple[float, float]] = None
            self.drag_rect_id: Optional[int] = None
            self.training_thread: Optional[threading.Thread] = None

            self._build_ui()

        def _build_ui(self) -> None:
            self.columnconfigure(0, weight=1)
            self.rowconfigure(1, weight=1)

            top = ttk.Frame(self, padding=(10, 8))
            top.grid(row=0, column=0, sticky="ew")
            top.columnconfigure(1, weight=1)
            top.columnconfigure(4, weight=1)

            ttk.Label(top, text="データセット").grid(row=0, column=0, sticky="w", pady=3)
            ttk.Entry(top, textvariable=self.dataset_dir_var).grid(row=0, column=1, sticky="ew", padx=6, pady=3)
            ttk.Button(top, text="参照", command=self._browse_dataset_dir).grid(row=0, column=2, sticky="ew", pady=3)

            ttk.Label(top, text="画像/動画").grid(row=1, column=0, sticky="w", pady=3)
            ttk.Entry(top, textvariable=self.annotation_source_var).grid(row=1, column=1, sticky="ew", padx=6, pady=3)
            source_buttons = ttk.Frame(top)
            source_buttons.grid(row=1, column=2, sticky="ew", pady=3)
            ttk.Button(source_buttons, text="ファイル", command=self._browse_annotation_source).pack(side="left")
            ttk.Button(source_buttons, text="フォルダ", command=self._browse_annotation_source_dir).pack(side="left", padx=(4, 0))

            ttk.Label(top, text="保存先").grid(row=0, column=3, sticky="e", padx=(16, 4), pady=3)
            ttk.Combobox(top, textvariable=self.split_var, values=("auto", "train", "val"), width=8, state="readonly").grid(
                row=0, column=4, sticky="w", pady=3
            )
            ttk.Label(top, text="抽出間隔").grid(row=1, column=3, sticky="e", padx=(16, 4), pady=3)
            ttk.Entry(top, textvariable=self.frame_step_var, width=8).grid(row=1, column=4, sticky="w", pady=3)
            ttk.Label(top, text="最大枚数").grid(row=1, column=4, sticky="w", padx=(70, 4), pady=3)
            ttk.Entry(top, textvariable=self.max_frames_var, width=8).grid(row=1, column=4, sticky="w", padx=(130, 0), pady=3)

            ttk.Button(top, text="読み込み", command=self._load_annotation_source).grid(row=0, column=5, rowspan=2, sticky="nsew", padx=(8, 0), pady=3)

            body = ttk.PanedWindow(self, orient="horizontal")
            body.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))

            image_frame = ttk.Frame(body)
            image_frame.columnconfigure(0, weight=1)
            image_frame.rowconfigure(0, weight=1)
            body.add(image_frame, weight=4)

            self.canvas = tk.Canvas(image_frame, bg="#202020", highlightthickness=0, cursor="crosshair")
            self.canvas.grid(row=0, column=0, sticky="nsew")
            self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
            self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
            self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
            self.canvas.bind("<Configure>", lambda _event: self._render_current_sample())

            side = ttk.Frame(body, padding=(10, 0))
            side.columnconfigure(0, weight=1)
            body.add(side, weight=1)

            self.sample_label_var = tk.StringVar(value="未読み込み")
            ttk.Label(side, textvariable=self.sample_label_var, font=("Yu Gothic UI", 10, "bold")).grid(
                row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8)
            )
            ttk.Button(side, text="前へ", command=self._prev_sample).grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=2)
            ttk.Button(side, text="次へ", command=self._next_sample).grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=2)
            ttk.Button(side, text="直前の矩形を削除", command=self._undo_box).grid(row=2, column=0, columnspan=2, sticky="ew", pady=2)
            ttk.Button(side, text="矩形を全削除", command=self._clear_boxes).grid(row=3, column=0, columnspan=2, sticky="ew", pady=2)
            ttk.Button(side, text="現在の画像を保存", command=self._save_current_sample).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 2))
            ttk.Button(side, text="全画像を保存", command=self._save_all_samples).grid(row=5, column=0, columnspan=2, sticky="ew", pady=2)

            train_box = ttk.LabelFrame(side, text="再トレーニング", padding=(8, 8))
            train_box.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(16, 8))
            train_box.columnconfigure(1, weight=1)

            ttk.Label(train_box, text="ベースモデル").grid(row=0, column=0, sticky="w", pady=2)
            ttk.Entry(train_box, textvariable=self.base_model_var).grid(row=0, column=1, sticky="ew", padx=4, pady=2)
            ttk.Button(train_box, text="参照", command=self._browse_base_model).grid(row=0, column=2, pady=2)

            ttk.Label(train_box, text="出力先").grid(row=1, column=0, sticky="w", pady=2)
            ttk.Entry(train_box, textvariable=self.train_project_var).grid(row=1, column=1, sticky="ew", padx=4, pady=2)
            ttk.Button(train_box, text="参照", command=self._browse_train_project).grid(row=1, column=2, pady=2)

            ttk.Label(train_box, text="run名").grid(row=2, column=0, sticky="w", pady=2)
            ttk.Entry(train_box, textvariable=self.train_name_var).grid(row=2, column=1, columnspan=2, sticky="ew", padx=4, pady=2)

            params = ttk.Frame(train_box)
            params.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 2))
            for col in range(4):
                params.columnconfigure(col, weight=1)
            ttk.Label(params, text="device").grid(row=0, column=0, sticky="w")
            ttk.Entry(params, textvariable=self.train_device_var, width=8).grid(row=1, column=0, sticky="ew", padx=(0, 4))
            ttk.Label(params, text="epochs").grid(row=0, column=1, sticky="w")
            ttk.Entry(params, textvariable=self.train_epochs_var, width=8).grid(row=1, column=1, sticky="ew", padx=4)
            ttk.Label(params, text="imgsz").grid(row=0, column=2, sticky="w")
            ttk.Entry(params, textvariable=self.train_imgsz_var, width=8).grid(row=1, column=2, sticky="ew", padx=4)
            ttk.Label(params, text="batch").grid(row=0, column=3, sticky="w")
            ttk.Entry(params, textvariable=self.train_batch_var, width=8).grid(row=1, column=3, sticky="ew", padx=(4, 0))

            self.train_button = ttk.Button(train_box, text="再トレーニング開始", command=self._start_training)
            self.train_button.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0))

            ttk.Separator(train_box).grid(row=5, column=0, columnspan=3, sticky="ew", pady=(10, 8))
            ttk.Label(train_box, text="自動ラベルモデル").grid(row=6, column=0, sticky="w", pady=2)
            ttk.Entry(train_box, textvariable=self.auto_label_model_var).grid(row=6, column=1, sticky="ew", padx=4, pady=2)
            ttk.Button(train_box, text="参照", command=self._browse_auto_label_model).grid(row=6, column=2, pady=2)
            ttk.Label(train_box, text="自動conf候補").grid(row=7, column=0, sticky="w", pady=2)
            ttk.Entry(train_box, textvariable=self.auto_conf_values_var).grid(
                row=7, column=1, columnspan=2, sticky="ew", padx=4, pady=2
            )
            ttk.Label(train_box, text="自動出力先").grid(row=8, column=0, sticky="w", pady=2)
            ttk.Entry(train_box, textvariable=self.auto_output_root_var).grid(row=8, column=1, sticky="ew", padx=4, pady=2)
            ttk.Button(train_box, text="参照", command=self._browse_auto_output_root).grid(row=8, column=2, pady=2)
            ttk.Label(train_box, text="val比率").grid(row=9, column=0, sticky="w", pady=2)
            ttk.Entry(train_box, textvariable=self.auto_val_ratio_var, width=8).grid(row=9, column=1, sticky="w", padx=4, pady=2)
            ttk.Label(train_box, text="変換モデル保存先").grid(row=10, column=0, sticky="w", pady=2)
            ttk.Entry(train_box, textvariable=self.export_model_path_var).grid(row=10, column=1, sticky="ew", padx=4, pady=2)
            ttk.Button(train_box, text="参照", command=self._browse_export_model).grid(row=10, column=2, pady=2)
            ttk.Checkbutton(
                train_box,
                text="再実行時に同じrun名を置き換え",
                variable=self.replace_run_var,
            ).grid(row=11, column=0, columnspan=3, sticky="w", pady=2)
            self.auto_train_button = ttk.Button(
                train_box,
                text="confを変えて自動トレーニング",
                command=self._start_auto_training,
            )
            self.auto_train_button.grid(row=12, column=0, columnspan=3, sticky="ew", pady=(8, 0))

            self.log_text = tk.Text(side, height=10, wrap="word", font=("Consolas", 9))
            self.log_text.grid(row=7, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
            side.rowconfigure(7, weight=1)

        def _log(self, message: str) -> None:
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")

        def _log_threadsafe(self, message: str) -> None:
            self.after(0, lambda: self._log(message))

        def _browse_dataset_dir(self) -> None:
            path = filedialog.askdirectory(title="データセットフォルダを選択", initialdir=str(APP_DIR))
            if path:
                self.dataset_dir_var.set(path)

        def _browse_annotation_source(self) -> None:
            path = filedialog.askopenfilename(
                title="アノテーションする画像または動画を選択",
                initialdir=str(APP_DIR.parent),
                filetypes=(
                    ("画像/動画", "*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff *.mp4 *.avi *.mov *.mkv *.wmv *.m4v"),
                    ("すべてのファイル", "*.*"),
                ),
            )
            if path:
                self.annotation_source_var.set(path)

        def _browse_annotation_source_dir(self) -> None:
            path = filedialog.askdirectory(title="学習元の動画/画像フォルダを選択", initialdir=str(APP_DIR.parent))
            if path:
                self.annotation_source_var.set(path)

        def _browse_base_model(self) -> None:
            path = filedialog.askopenfilename(
                title="ベースモデルを選択",
                initialdir=str(DEFAULT_TIRE_MODEL_PATH.parent),
                filetypes=(("YOLOモデル", "*.pt *.onnx"), ("すべてのファイル", "*.*")),
            )
            if path:
                self.base_model_var.set(path)

        def _browse_auto_label_model(self) -> None:
            path = filedialog.askopenfilename(
                title="自動ラベル用モデルを選択",
                initialdir=str(DEFAULT_TIRE_MODEL_PATH.parent),
                filetypes=(("YOLOモデル", "*.pt *.onnx"), ("すべてのファイル", "*.*")),
            )
            if path:
                self.auto_label_model_var.set(path)

        def _browse_train_project(self) -> None:
            path = filedialog.askdirectory(title="学習結果の出力先を選択", initialdir=str(APP_DIR))
            if path:
                self.train_project_var.set(path)

        def _browse_auto_output_root(self) -> None:
            path = filedialog.askdirectory(title="自動学習の出力先を選択", initialdir=str(APP_DIR))
            if path:
                self.auto_output_root_var.set(path)

        def _browse_export_model(self) -> None:
            path = filedialog.asksaveasfilename(
                title="変換済みタイヤモデルの保存先を選択",
                initialdir=str(APP_DIR),
                initialfile=DEFAULT_CONVERTED_TIRE_MODEL_PATH.name,
                defaultextension=".pt",
                filetypes=(("PyTorchモデル", "*.pt"), ("すべてのファイル", "*.*")),
            )
            if path:
                self.export_model_path_var.set(path)

        def _load_annotation_source(self) -> None:
            source_text = self.annotation_source_var.get().strip()
            if not source_text:
                messagebox.showerror("入力エラー", "画像または動画を選択してください。")
                return

            try:
                import cv2
            except ImportError as exc:
                messagebox.showerror("環境エラー", f"opencv-python が必要です。\n{exc}")
                return

            source_path = Path(source_text)
            if not source_path.exists():
                messagebox.showerror("入力エラー", f"入力パスが見つかりません:\n{source_path}")
                return

            self.samples.clear()
            self.sample_index = 0
            try:
                source_files = iter_training_source_files(source_path)
                frame_step = max(1, int(self.frame_step_var.get().strip()))
                max_frames = max(1, int(self.max_frames_var.get().strip()))
                for current_source_path in source_files:
                    suffix = current_source_path.suffix.lower()
                    if suffix in IMAGE_EXTENSIONS:
                        image = cv2.imread(str(current_source_path))
                        if image is None:
                            self._log(f"画像を読み込めないためスキップ: {current_source_path}")
                            continue
                        self.samples.append({"stem": sanitize_file_stem(current_source_path.stem), "image": image, "boxes": []})
                    elif suffix in VIDEO_EXTENSIONS:
                        cap = cv2.VideoCapture(str(current_source_path))
                        if not cap.isOpened():
                            self._log(f"動画を開けないためスキップ: {current_source_path}")
                            continue
                        frame_index = -1
                        local_count = 0
                        try:
                            while local_count < max_frames:
                                ok, frame = cap.read()
                                if not ok:
                                    break
                                frame_index += 1
                                if frame_index % frame_step != 0:
                                    continue
                                stem = sanitize_file_stem(f"{current_source_path.stem}_f{frame_index:06d}")
                                self.samples.append({"stem": stem, "image": frame.copy(), "boxes": []})
                                local_count += 1
                        finally:
                            cap.release()
                if not self.samples:
                    raise RuntimeError("画像/動画からアノテーション用サンプルを抽出できませんでした。")
            except Exception as exc:
                messagebox.showerror("読み込みエラー", str(exc))
                return

            ensure_yolo_dataset(Path(self.dataset_dir_var.get().strip() or DEFAULT_DATASET_DIR))
            self._log(f"読み込み完了: {len(self.samples)}枚")
            self._render_current_sample()

        def _current_sample(self) -> Optional[dict[str, object]]:
            if not self.samples:
                return None
            self.sample_index = max(0, min(self.sample_index, len(self.samples) - 1))
            return self.samples[self.sample_index]

        def _render_current_sample(self) -> None:
            sample = self._current_sample()
            self.canvas.delete("all")
            if sample is None:
                self.sample_label_var.set("未読み込み")
                return

            image_bgr = sample["image"]
            image_height, image_width = image_bgr.shape[:2]
            canvas_width = max(320, self.canvas.winfo_width())
            canvas_height = max(240, self.canvas.winfo_height())
            self.display_scale = min(canvas_width / image_width, canvas_height / image_height, 1.0)
            display_width = max(1, int(image_width * self.display_scale))
            display_height = max(1, int(image_height * self.display_scale))

            try:
                import cv2
            except ImportError:
                return
            rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb)
            if display_width != image_width or display_height != image_height:
                resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
                pil_image = pil_image.resize((display_width, display_height), resample)
            self.tk_image = ImageTk.PhotoImage(pil_image)
            self.canvas.create_image(0, 0, anchor="nw", image=self.tk_image)

            boxes = sample["boxes"]
            if isinstance(boxes, list):
                for region in boxes:
                    self._draw_region(region)
            self.sample_label_var.set(
                f"{self.sample_index + 1}/{len(self.samples)}  {sample['stem']}  矩形:{len(boxes) if isinstance(boxes, list) else 0}"
            )

        def _draw_region(self, region: TireRegion) -> None:
            scale = self.display_scale
            x1 = region.left * scale
            y1 = region.top * scale
            x2 = region.right * scale
            y2 = region.bottom * scale
            self.canvas.create_rectangle(x1, y1, x2, y2, outline="#00ff66", width=2)
            self.canvas.create_text(x1 + 4, max(10, y1 - 8), anchor="w", fill="#00ff66", text=TRAINING_CLASS_NAME)

        def _canvas_to_image_point(self, x: float, y: float) -> tuple[float, float]:
            sample = self._current_sample()
            if sample is None:
                return (0.0, 0.0)
            image_bgr = sample["image"]
            image_height, image_width = image_bgr.shape[:2]
            scale = self.display_scale if self.display_scale > 0 else 1.0
            image_x = max(0.0, min(float(image_width), x / scale))
            image_y = max(0.0, min(float(image_height), y / scale))
            return image_x, image_y

        def _on_canvas_press(self, event: tk.Event) -> None:
            if self._current_sample() is None:
                return
            self.drag_start = self._canvas_to_image_point(event.x, event.y)
            if self.drag_rect_id is not None:
                self.canvas.delete(self.drag_rect_id)
                self.drag_rect_id = None

        def _on_canvas_drag(self, event: tk.Event) -> None:
            if self.drag_start is None:
                return
            x1, y1 = self.drag_start
            x2, y2 = self._canvas_to_image_point(event.x, event.y)
            scale = self.display_scale
            if self.drag_rect_id is not None:
                self.canvas.delete(self.drag_rect_id)
            self.drag_rect_id = self.canvas.create_rectangle(
                x1 * scale,
                y1 * scale,
                x2 * scale,
                y2 * scale,
                outline="#ffff00",
                width=2,
            )

        def _on_canvas_release(self, event: tk.Event) -> None:
            sample = self._current_sample()
            if sample is None or self.drag_start is None:
                return
            x1, y1 = self.drag_start
            x2, y2 = self._canvas_to_image_point(event.x, event.y)
            self.drag_start = None
            if self.drag_rect_id is not None:
                self.canvas.delete(self.drag_rect_id)
                self.drag_rect_id = None
            region = TireRegion(left=min(x1, x2), top=min(y1, y2), right=max(x1, x2), bottom=max(y1, y2))
            if (region.right - region.left) < 3 or (region.bottom - region.top) < 3:
                return
            boxes = sample["boxes"]
            if isinstance(boxes, list):
                boxes.append(region)
            self._render_current_sample()

        def _prev_sample(self) -> None:
            if self.samples:
                self.sample_index = max(0, self.sample_index - 1)
                self._render_current_sample()

        def _next_sample(self) -> None:
            if self.samples:
                self.sample_index = min(len(self.samples) - 1, self.sample_index + 1)
                self._render_current_sample()

        def _undo_box(self) -> None:
            sample = self._current_sample()
            if sample is None:
                return
            boxes = sample["boxes"]
            if isinstance(boxes, list) and boxes:
                boxes.pop()
                self._render_current_sample()

        def _clear_boxes(self) -> None:
            sample = self._current_sample()
            if sample is None:
                return
            boxes = sample["boxes"]
            if isinstance(boxes, list):
                boxes.clear()
                self._render_current_sample()

        def _save_one_sample(self, sample: dict[str, object], sample_index: int) -> tuple[Path, Path, int]:
            dataset_dir = Path(self.dataset_dir_var.get().strip() or DEFAULT_DATASET_DIR)
            split = self.split_var.get().strip() or "train"
            if split == "auto":
                try:
                    val_ratio = float(self.auto_val_ratio_var.get().strip())
                except ValueError:
                    val_ratio = 0.2
                split = split_for_auto_sample(
                    saved_index=sample_index,
                    local_index=sample_index,
                    source_index=0,
                    source_count=1,
                    val_ratio=val_ratio,
                )
            image = sample["image"]
            boxes = sample["boxes"]
            if not isinstance(boxes, list):
                boxes = []
            return save_yolo_annotation_sample(
                image_bgr=image,
                regions=boxes,
                dataset_dir=dataset_dir,
                split=split,
                sample_stem=str(sample["stem"]),
            )

        def _save_current_sample(self) -> None:
            sample = self._current_sample()
            if sample is None:
                messagebox.showerror("保存エラー", "画像/動画を先に読み込んでください。")
                return
            try:
                image_path, label_path, count = self._save_one_sample(sample, self.sample_index)
            except Exception as exc:
                messagebox.showerror("保存エラー", str(exc))
                return
            self._log(f"保存: {image_path.name} / {label_path.name}  bbox={count}")

        def _save_all_samples(self) -> None:
            if not self.samples:
                messagebox.showerror("保存エラー", "画像/動画を先に読み込んでください。")
                return
            total_boxes = 0
            try:
                for index, sample in enumerate(self.samples):
                    _image_path, _label_path, count = self._save_one_sample(sample, index)
                    total_boxes += count
            except Exception as exc:
                messagebox.showerror("保存エラー", str(exc))
                return
            self._log(f"全保存完了: images={len(self.samples)}, bbox={total_boxes}")

        def _set_training(self, running: bool) -> None:
            self.train_button.configure(state="disabled" if running else "normal")
            self.auto_train_button.configure(state="disabled" if running else "normal")

        def _start_training(self) -> None:
            if self.training_thread is not None and self.training_thread.is_alive():
                messagebox.showinfo("学習中", "再トレーニングはすでに実行中です。")
                return
            try:
                dataset_dir = Path(self.dataset_dir_var.get().strip() or DEFAULT_DATASET_DIR)
                base_model = Path(self.base_model_var.get().strip() or DEFAULT_TIRE_MODEL_PATH)
                output_root = Path(self.train_project_var.get().strip() or DEFAULT_FULL_RETRAIN_DIR)
                run_name = self.train_name_var.get().strip() or "tire_retrain"
                device = self.train_device_var.get().strip() or DEFAULT_DEVICE
                epochs = int(self.train_epochs_var.get().strip())
                imgsz = int(self.train_imgsz_var.get().strip())
                batch = int(self.train_batch_var.get().strip())
                export_text = self.export_model_path_var.get().strip()
                export_model_path = Path(export_text) if export_text else None
                replace_run = bool(self.replace_run_var.get())
            except Exception as exc:
                messagebox.showerror("入力エラー", str(exc))
                return

            self._set_training(True)
            self._log("フル再トレーニングを開始します。")
            self._log("元モデルをコピーし、別モデルとして保存します。")
            if replace_run:
                self._log("同じrun名の既存結果は置き換えます。")

            def worker() -> None:
                try:
                    result = run_full_retraining(
                        dataset_dir=dataset_dir,
                        base_model_path=base_model,
                        output_root=output_root,
                        run_name=run_name,
                        device=device,
                        epochs=epochs,
                        imgsz=imgsz,
                        batch=batch,
                        replace_run=replace_run,
                        export_model_path=export_model_path,
                        progress_cb=self._log_threadsafe,
                    )
                except Exception as exc:
                    error_message = str(exc)
                    self._log_threadsafe(f"エラー: {error_message}")
                    self.after(0, lambda msg=error_message: messagebox.showerror("再トレーニングエラー", msg))
                    self.after(0, lambda: self._set_training(False))
                    return
                final_model = result["final_model"]
                self._log_threadsafe(f"別モデル: {final_model}")
                self.after(0, lambda: self._set_training(False))
                self.after(0, lambda path=final_model: messagebox.showinfo("再トレーニング完了", f"学習済みモデル:\n{path}"))

            self.training_thread = threading.Thread(target=worker, daemon=True)
            self.training_thread.start()

        def _start_auto_training(self) -> None:
            if self.training_thread is not None and self.training_thread.is_alive():
                messagebox.showinfo("学習中", "学習処理はすでに実行中です。")
                return
            try:
                source_text = self.annotation_source_var.get().strip()
                if not source_text:
                    raise ValueError("自動学習に使う画像または動画を選択してください。")
                source_path = Path(source_text)
                base_model = Path(self.base_model_var.get().strip() or DEFAULT_TIRE_MODEL_PATH)
                label_model = Path(self.auto_label_model_var.get().strip() or DEFAULT_TIRE_MODEL_PATH)
                output_root = Path(self.auto_output_root_var.get().strip() or DEFAULT_AUTO_TRAIN_DIR)
                run_name = self.train_name_var.get().strip() or "auto_tire_train"
                conf_values = parse_float_list(self.auto_conf_values_var.get())
                device = self.train_device_var.get().strip() or DEFAULT_DEVICE
                epochs = int(self.train_epochs_var.get().strip())
                imgsz = int(self.train_imgsz_var.get().strip())
                batch = int(self.train_batch_var.get().strip())
                frame_step = int(self.frame_step_var.get().strip())
                max_frames = int(self.max_frames_var.get().strip())
                val_ratio = float(self.auto_val_ratio_var.get().strip())
                export_text = self.export_model_path_var.get().strip()
                export_model_path = Path(export_text) if export_text else None
                replace_run = bool(self.replace_run_var.get())
            except Exception as exc:
                messagebox.showerror("入力エラー", str(exc))
                return

            self._set_training(True)
            self._log("conf候補を変えた自動トレーニングを開始します。")
            self._log("元モデルは各runにコピーしてから使用します。")
            if replace_run:
                self._log("同じrun名/confの既存結果は置き換えます。")

            def worker() -> None:
                try:
                    results = run_auto_conf_training(
                        source_path=source_path,
                        base_model_path=base_model,
                        label_model_path=label_model,
                        output_root=output_root,
                        run_name=run_name,
                        conf_values=conf_values,
                        device=device,
                        epochs=epochs,
                        imgsz=imgsz,
                        batch=batch,
                        frame_step=frame_step,
                        max_frames=max_frames,
                        val_ratio=val_ratio,
                        replace_run=replace_run,
                        export_model_path=export_model_path,
                        progress_cb=self._log_threadsafe,
                    )
                except Exception as exc:
                    error_message = str(exc)
                    self._log_threadsafe(f"エラー: {error_message}")
                    self.after(0, lambda msg=error_message: messagebox.showerror("自動トレーニングエラー", msg))
                    self.after(0, lambda: self._set_training(False))
                    return

                self.after(0, lambda: self._set_training(False))
                summary_lines = ["自動トレーニング完了"]
                for item in results:
                    summary_lines.append(f"conf={item['conf']}: {item['final_model']}")
                self._log_threadsafe("\n".join(summary_lines))
                self.after(0, lambda text="\n".join(summary_lines): messagebox.showinfo("自動トレーニング完了", text))

            self.training_thread = threading.Thread(target=worker, daemon=True)
            self.training_thread.start()

    class DistanceCsvGui(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title("画像下中央とタイヤのピクセル距離CSV出力")
            self.geometry("900x620")
            self.minsize(820, 640)

            self.tire_point_var = tk.StringVar(value=TIRE_POINT_LABELS["bottom_center"])
            self.csv_path_var = tk.StringVar(value=str(DEFAULT_CSV_PATH))
            self.video_output_path_var = tk.StringVar(value=str(DEFAULT_VIDEO_PATH))
            self.source_path_var = tk.StringVar()
            self.tire_model_path_var = tk.StringVar(value=str(DEFAULT_TIRE_MODEL_PATH))
            self.device_var = tk.StringVar(value=DEFAULT_DEVICE)
            self.conf_var = tk.StringVar(value=str(DEFAULT_CONFIDENCE))
            self.imgsz_var = tk.StringVar(value="640")
            self.frame_step_var = tk.StringVar(value="1")
            self.max_frames_var = tk.StringVar(value="0")
            self.nearest_only_var = tk.BooleanVar(value=False)

            self._build_ui()

        def _build_ui(self) -> None:
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass

            self.columnconfigure(0, weight=1)
            self.rowconfigure(3, weight=1)

            header = ttk.Frame(self, padding=(10, 10))
            header.grid(row=0, column=0, sticky="ew")
            ttk.Label(
                header,
                text="画像/動画フレームの下中央とタイヤのピクセル距離",
                font=("Yu Gothic UI", 14, "bold"),
            ).pack(anchor="w")

            input_frame = ttk.LabelFrame(self, text="入力", padding=(10, 8))
            input_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
            input_frame.columnconfigure(1, weight=1)

            ttk.Label(input_frame, text="タイヤ基準点").grid(row=0, column=0, sticky="w", pady=4)
            ttk.Combobox(
                input_frame,
                textvariable=self.tire_point_var,
                values=tire_point_labels,
                state="readonly",
            ).grid(row=0, column=1, sticky="ew", padx=6, pady=4)

            ttk.Label(input_frame, text="出力CSV").grid(row=1, column=0, sticky="w", pady=4)
            ttk.Entry(input_frame, textvariable=self.csv_path_var).grid(
                row=1, column=1, sticky="ew", padx=6, pady=4
            )
            ttk.Button(input_frame, text="参照", command=self._browse_csv).grid(row=1, column=2, pady=4)

            ttk.Label(input_frame, text="出力動画").grid(row=2, column=0, sticky="w", pady=4)
            ttk.Entry(input_frame, textvariable=self.video_output_path_var).grid(
                row=2, column=1, sticky="ew", padx=6, pady=4
            )
            ttk.Button(input_frame, text="参照", command=self._browse_video_output).grid(row=2, column=2, pady=4)

            model_frame = ttk.LabelFrame(self, text="タイヤモデル処理", padding=(10, 8))
            model_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))
            model_frame.columnconfigure(1, weight=1)
            model_frame.columnconfigure(3, weight=1)

            ttk.Label(model_frame, text="画像/動画").grid(row=0, column=0, sticky="w", pady=4)
            ttk.Entry(model_frame, textvariable=self.source_path_var).grid(
                row=0, column=1, columnspan=3, sticky="ew", padx=6, pady=4
            )
            ttk.Button(model_frame, text="参照", command=self._browse_source).grid(row=0, column=4, pady=4)

            ttk.Label(model_frame, text="タイヤモデル").grid(row=1, column=0, sticky="w", pady=4)
            ttk.Entry(model_frame, textvariable=self.tire_model_path_var).grid(
                row=1, column=1, columnspan=3, sticky="ew", padx=6, pady=4
            )
            ttk.Button(model_frame, text="参照", command=self._browse_model).grid(row=1, column=4, pady=4)

            ttk.Label(model_frame, text="デバイス").grid(row=2, column=0, sticky="w", pady=4)
            ttk.Entry(model_frame, textvariable=self.device_var, width=8).grid(
                row=2, column=1, sticky="w", padx=6, pady=4
            )
            ttk.Label(model_frame, text="conf").grid(row=2, column=2, sticky="e", pady=4)
            ttk.Entry(model_frame, textvariable=self.conf_var, width=8).grid(
                row=2, column=3, sticky="w", padx=6, pady=4
            )

            ttk.Label(model_frame, text="imgsz").grid(row=3, column=0, sticky="w", pady=4)
            ttk.Entry(model_frame, textvariable=self.imgsz_var, width=8).grid(
                row=3, column=1, sticky="w", padx=6, pady=4
            )
            ttk.Label(model_frame, text="動画フレーム間隔").grid(row=3, column=2, sticky="e", pady=4)
            ttk.Entry(model_frame, textvariable=self.frame_step_var, width=8).grid(
                row=3, column=3, sticky="w", padx=6, pady=4
            )

            ttk.Label(model_frame, text="最大処理フレーム数").grid(row=4, column=0, sticky="w", pady=4)
            ttk.Entry(model_frame, textvariable=self.max_frames_var, width=8).grid(
                row=4, column=1, sticky="w", padx=6, pady=4
            )
            ttk.Checkbutton(
                model_frame,
                text="各画像/フレームで最も近いタイヤだけ保存",
                variable=self.nearest_only_var,
            ).grid(row=4, column=2, columnspan=2, sticky="w", padx=6, pady=4)
            self.process_button = ttk.Button(
                model_frame,
                text="タイヤモデルで処理してCSV/動画保存",
                command=self._process_tire_model,
            )
            self.process_button.grid(row=5, column=0, columnspan=5, sticky="ew", pady=(8, 0))
            ttk.Button(
                model_frame,
                text="アノテーション/再トレーニングを開く",
                command=self._open_annotation_train_window,
            ).grid(row=6, column=0, columnspan=5, sticky="ew", pady=(6, 0))

            result_frame = ttk.LabelFrame(self, text="結果", padding=(8, 8))
            result_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))
            result_frame.columnconfigure(0, weight=1)
            result_frame.rowconfigure(0, weight=1)

            self.result_text = tk.Text(result_frame, wrap="word", font=("Consolas", 10))
            self.result_text.grid(row=0, column=0, sticky="nsew")
            scroll = ttk.Scrollbar(result_frame, orient="vertical", command=self.result_text.yview)
            scroll.grid(row=0, column=1, sticky="ns")
            self.result_text.configure(yscrollcommand=scroll.set)

        def _browse_csv(self) -> None:
            path = filedialog.asksaveasfilename(
                title="出力CSVを選択",
                initialdir=str(APP_DIR),
                initialfile=DEFAULT_CSV_PATH.name,
                defaultextension=".csv",
                filetypes=(("CSVファイル", "*.csv"), ("すべてのファイル", "*.*")),
            )
            if path:
                self.csv_path_var.set(path)

        def _browse_video_output(self) -> None:
            path = filedialog.asksaveasfilename(
                title="出力動画を選択",
                initialdir=str(APP_DIR),
                initialfile=DEFAULT_VIDEO_PATH.name,
                defaultextension=".mp4",
                filetypes=(("MP4動画", "*.mp4"), ("AVI動画", "*.avi"), ("すべてのファイル", "*.*")),
            )
            if path:
                self.video_output_path_var.set(path)

        def _browse_source(self) -> None:
            path = filedialog.askopenfilename(
                title="画像または動画を選択",
                initialdir=str(APP_DIR.parent),
                filetypes=(
                    ("画像/動画", "*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff *.mp4 *.avi *.mov *.mkv *.wmv *.m4v"),
                    ("すべてのファイル", "*.*"),
                ),
            )
            if path:
                self.source_path_var.set(path)
                source_path = Path(path)
                current_video_path = self.video_output_path_var.get().strip()
                if not current_video_path or current_video_path == str(DEFAULT_VIDEO_PATH):
                    self.video_output_path_var.set(str(default_output_video_path(source_path)))

        def _browse_model(self) -> None:
            path = filedialog.askopenfilename(
                title="タイヤモデルを選択",
                initialdir=str(DEFAULT_TIRE_MODEL_PATH.parent),
                filetypes=(("YOLOモデル", "*.pt *.onnx"), ("すべてのファイル", "*.*")),
            )
            if path:
                self.tire_model_path_var.set(path)

        def _append_result(self, message: str) -> None:
            self.result_text.insert("end", message + "\n")
            self.result_text.see("end")

        def _append_result_threadsafe(self, message: str) -> None:
            self.after(0, lambda: self._append_result(message))

        def _set_processing(self, processing: bool) -> None:
            self.process_button.configure(state="disabled" if processing else "normal")

        def _open_annotation_train_window(self) -> None:
            window = AnnotationTrainWindow(self)
            window.transient(self)
            window.focus_set()

        def _process_tire_model(self) -> None:
            try:
                source_text = self.source_path_var.get().strip()
                if not source_text:
                    raise ValueError("画像または動画を選択してください。")
                source_path = Path(source_text)
                model_path = resolve_tire_model_path(self.tire_model_path_var.get())
                csv_path = Path(self.csv_path_var.get().strip() or DEFAULT_CSV_PATH)
                video_output_text = self.video_output_path_var.get().strip()
                output_video_path = Path(video_output_text) if video_output_text else default_output_video_path(source_path)
                tire_point = TIRE_POINT_BY_LABEL.get(self.tire_point_var.get(), self.tire_point_var.get())
                device = self.device_var.get().strip() or DEFAULT_DEVICE
                conf = float(self.conf_var.get().strip())
                imgsz = int(self.imgsz_var.get().strip())
                frame_step = int(self.frame_step_var.get().strip())
                max_frames = int(self.max_frames_var.get().strip())
                nearest_only = bool(self.nearest_only_var.get())
            except Exception as exc:
                messagebox.showerror("入力エラー", str(exc))
                return

            self.result_text.delete("1.0", "end")
            self._append_result("タイヤモデル処理を開始します。")
            self._append_result("距離の基準点: 画像/動画フレームの下中央")
            self._append_result(f"入力: {source_path}")
            self._append_result(f"モデル: {model_path}")
            self._append_result(f"出力CSV: {csv_path}")
            self._append_result(f"出力動画: {output_video_path}")
            self._set_processing(True)

            def worker() -> None:
                try:
                    count = run_tire_model_gpu_to_csv(
                        source_path=source_path,
                        tire_point=tire_point,
                        model_path=model_path,
                        csv_path=csv_path,
                        output_video_path=output_video_path,
                        device=device,
                        conf=conf,
                        imgsz=imgsz,
                        frame_step=frame_step,
                        max_frames=max_frames,
                        nearest_only=nearest_only,
                        progress_cb=self._append_result_threadsafe,
                    )
                except Exception as exc:
                    error_message = str(exc)
                    self.after(0, lambda msg=error_message: messagebox.showerror("タイヤモデル処理エラー", msg))
                    self._append_result_threadsafe(f"エラー: {error_message}")
                    self.after(0, lambda: self._set_processing(False))
                    return
                self._append_result_threadsafe(f"CSV保存完了: {count}件")
                self.after(0, lambda: self._set_processing(False))
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "処理完了",
                        f"CSVに保存しました。\n{csv_path}\n保存件数: {count}件\n\n出力動画:\n{output_video_path}",
                    ),
                )

            threading.Thread(target=worker, daemon=True).start()

    app = DistanceCsvGui()
    app.mainloop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="画像/動画フレームの下中央と、タイヤモデルで検出したタイヤ基準点のピクセル距離をCSVへ保存します。",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="このヘルプを表示して終了")
    parser._optionals.title = "オプション"
    parser.add_argument("--source", required=False, help="タイヤモデルで処理する画像/動画ファイル")
    parser.add_argument("--tire-model", default=str(DEFAULT_TIRE_MODEL_PATH), help="タイヤ検出モデルのパス")
    parser.add_argument(
        "--video-output",
        default=None,
        help="出力動画パス。省略時は入力動画名に _tire_distance.mp4 を付けて保存",
    )
    parser.add_argument(
        "--device",
        default=DEFAULT_DEVICE,
        help="処理デバイス。autoはGPUが使える場合だけGPU、不可ならCPU。GPU固定は0、CPU固定はcpu",
    )
    parser.add_argument("--conf", type=float, default=DEFAULT_CONFIDENCE, help="YOLO信頼度しきい値")
    parser.add_argument("--imgsz", type=int, default=640, help="YOLO入力画像サイズ")
    parser.add_argument("--frame-step", type=int, default=1, help="動画処理時のフレーム間隔")
    parser.add_argument("--max-frames", type=int, default=0, help="動画処理時の最大処理フレーム数。0は制限なし")
    parser.add_argument("--nearest-only", action="store_true", help="各画像/フレームで最も近いタイヤだけCSV保存")
    parser.add_argument(
        "--tire-point",
        choices=TIRE_POINT_CHOICES,
        default="bottom_center",
        help="距離計算に使うタイヤ基準点",
    )
    parser.add_argument("--csv", default=str(DEFAULT_CSV_PATH), help="出力CSVパス")
    parser.add_argument("--gui", action="store_true", help="GUIを起動")
    parser.add_argument("--train-full", action="store_true", help="YOLOデータセットからフル再トレーニングを実行")
    parser.add_argument("--auto-train-full", action="store_true", help="画像/動画/フォルダから自動ラベル生成してフル再トレーニングを実行")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_DIR), help="YOLO形式データセットフォルダ")
    parser.add_argument("--base-model", default=str(DEFAULT_TRAIN_BASE_MODEL_PATH), help="再トレーニング元モデル")
    parser.add_argument("--label-model", default=str(DEFAULT_TIRE_MODEL_PATH), help="自動ラベル生成に使うタイヤ検出モデル")
    parser.add_argument("--train-output", default=str(DEFAULT_FULL_RETRAIN_DIR), help="フル再トレーニング出力先")
    parser.add_argument("--auto-output", default=str(DEFAULT_AUTO_TRAIN_DIR), help="自動トレーニング出力先")
    parser.add_argument("--run-name", default="tire_retrain", help="学習run名")
    parser.add_argument("--epochs", type=int, default=50, help="学習epoch数")
    parser.add_argument("--batch", type=int, default=8, help="学習batchサイズ")
    parser.add_argument("--auto-conf-values", default="0.05,0.10,0.20", help="自動ラベル生成に使うconf候補。例: 0.05,0.10,0.20")
    parser.add_argument("--val-ratio", type=float, default=0.20, help="自動生成データのval比率")
    parser.add_argument("--replace-run", action="store_true", help="同じrun名の既存出力を削除して置き換え")
    parser.add_argument("--export-model", default=str(DEFAULT_CONVERTED_TIRE_MODEL_PATH), help="変換済みタイヤモデルの保存先。空文字なら保存しない")
    return parser


def main() -> None:
    if len(sys.argv) == 1:
        launch_gui()
        return

    args = build_parser().parse_args()
    if args.gui:
        launch_gui()
        return

    if args.train_full:
        result = run_full_retraining(
            dataset_dir=Path(args.dataset),
            base_model_path=Path(args.base_model),
            output_root=Path(args.train_output),
            run_name=args.run_name,
            device=args.device,
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            replace_run=args.replace_run,
            export_model_path=Path(args.export_model) if args.export_model else None,
            progress_cb=print,
        )
        print(f"フル再トレーニング完了: {result['final_model']}")
        return

    if args.auto_train_full:
        if not args.source:
            raise SystemExit("--auto-train-full では --source に画像/動画/フォルダを指定してください。")
        results = run_auto_conf_training(
            source_path=Path(args.source),
            base_model_path=Path(args.base_model),
            label_model_path=Path(args.label_model),
            output_root=Path(args.auto_output),
            run_name=args.run_name,
            conf_values=parse_float_list(args.auto_conf_values),
            device=args.device,
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            frame_step=args.frame_step,
            max_frames=args.max_frames,
            val_ratio=args.val_ratio,
            replace_run=args.replace_run,
            export_model_path=Path(args.export_model) if args.export_model else None,
            progress_cb=print,
        )
        print("自動フル再トレーニング完了:")
        for item in results:
            print(f"conf={item['conf']}: {item['final_model']}")
        return

    if not args.source:
        raise SystemExit("--source を指定してください。GUIを使う場合は引数なしで起動してください。")

    source_path = Path(args.source)
    output_video_path = Path(args.video_output) if args.video_output else default_output_video_path(source_path)

    count = run_tire_model_gpu_to_csv(
        source_path=source_path,
        tire_point=args.tire_point,
        model_path=resolve_tire_model_path(args.tire_model),
        csv_path=Path(args.csv),
        output_video_path=output_video_path,
        device=args.device,
        conf=args.conf,
        imgsz=args.imgsz,
        frame_step=args.frame_step,
        max_frames=args.max_frames,
        nearest_only=args.nearest_only,
        progress_cb=print,
    )
    print(f"CSVに保存しました: {args.csv} ({count}件)")
    print(f"出力動画: {output_video_path}")


if __name__ == "__main__":
    main()
