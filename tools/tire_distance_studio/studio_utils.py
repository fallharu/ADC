# -*- coding: utf-8 -*-
"""Tire Distance Studio 共通ユーティリティ。

UIコードから入力値の解釈と検証を分離するためのモジュールです。
Tkinterの ``StringVar`` はメインスレッドでしか安全に読めないため、
各画面は処理開始前に、このモジュールの不変設定オブジェクトへ値をコピーします。
バックグラウンドスレッドには設定オブジェクトだけを渡します。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v"})
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


def clean_path_text(value: object) -> str:
    """GUIへ貼り付けたパスを正規化する。

    Windowsの「パスのコピー」は引用符付きになる場合があります。
    前後空白と、対になった一重・二重引用符だけを除去します。
    パス内部の空白や日本語は変更しません。
    """
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and ord(text[0]) in {34, 39}:
        return text[1:-1].strip()
    return text


def required_path(value: object, label: str) -> Path:
    """必須パスを生成し、空欄なら利用者向けの例外を送出する。"""
    text = clean_path_text(value)
    if not text:
        raise ValueError(f"{label}を指定してください。")
    return Path(text)


def optional_path(value: object) -> Optional[Path]:
    """空欄を ``None`` として扱う任意パスを生成する。"""
    text = clean_path_text(value)
    return Path(text) if text else None


def positive_int(value: object, label: str, *, minimum: int = 1) -> int:
    """整数入力を検証する。"""
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}は整数で入力してください。") from exc
    if parsed < minimum:
        raise ValueError(f"{label}は{minimum}以上にしてください。")
    return parsed


def bounded_float(value: object, label: str, *, minimum: float, maximum: float, include_minimum: bool = True) -> float:
    """範囲付き小数入力を検証する。"""
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}は数値で入力してください。") from exc
    lower_ok = parsed >= minimum if include_minimum else parsed > minimum
    if not lower_ok or parsed > maximum:
        op = "以上" if include_minimum else "より大きく"
        raise ValueError(f"{label}は{minimum}{op}{maximum}以下にしてください。")
    return parsed


@dataclass(frozen=True)
class AnalysisConfig:
    """距離解析ワーカーへ渡す、検証済みの不変設定。"""

    source: Path
    model: Path
    csv_path: Path
    video_path: Optional[Path]
    tire_point: str
    device: str
    confidence: float
    image_size: int
    frame_step: int
    max_frames: int
    nearest_only: bool

    @classmethod
    def build(
        cls,
        *,
        source: object,
        model: object,
        csv_path: object,
        video_path: object,
        tire_point: str,
        device: str,
        confidence: object,
        image_size: object,
        frame_step: object,
        max_frames: object,
        nearest_only: bool,
    ) -> "AnalysisConfig":
        """UI文字列から距離解析設定を構築して検証する。"""
        source_path = required_path(source, "入力画像／動画")
        model_path = required_path(model, "タイヤモデル")
        output_csv = required_path(csv_path, "出力CSV")
        output_video = optional_path(video_path)
        if not source_path.is_file():
            raise FileNotFoundError(f"入力ファイルが見つかりません: {source_path}")
        if source_path.suffix.lower() not in MEDIA_EXTENSIONS:
            raise ValueError(f"未対応の入力形式です: {source_path.suffix}")
        if not model_path.is_file():
            raise FileNotFoundError(f"モデルが見つかりません: {model_path}")
        if output_csv.suffix.lower() != ".csv":
            raise ValueError("出力CSVの拡張子は.csvにしてください。")
        if output_video is not None and output_video.suffix.lower() not in {".mp4", ".avi"}:
            raise ValueError("可視化動画の拡張子は.mp4または.aviにしてください。")
        allowed_points = {"center", "bottom_center", "bottom_left", "bottom_right", "nearest_bottom_corner", "nearest_any"}
        if tire_point not in allowed_points:
            raise ValueError(f"未対応のタイヤ基準点です: {tire_point}")
        if output_csv.resolve() == source_path.resolve():
            raise ValueError("入力ファイルと出力CSVに同じパスは指定できません。")
        if output_video is not None and output_video.resolve() == source_path.resolve():
            raise ValueError("入力動画と出力動画に同じパスは指定できません。")
        return cls(
            source=source_path,
            model=model_path,
            csv_path=output_csv,
            video_path=output_video,
            tire_point=str(tire_point),
            device=str(device).strip() or "auto",
            confidence=bounded_float(confidence, "conf", minimum=0.0, maximum=1.0, include_minimum=False),
            image_size=positive_int(image_size, "imgsz", minimum=32),
            frame_step=positive_int(frame_step, "frame step"),
            max_frames=positive_int(max_frames, "最大フレーム", minimum=0),
            nearest_only=bool(nearest_only),
        )


@dataclass(frozen=True)
class AutoLabelConfig:
    """自動アノテーションワーカーへ渡す、検証済みの不変設定。"""

    source: Path
    model: Path
    dataset: Path
    device: str
    confidence: float
    image_size: int
    frame_step: int
    max_frames: int
    validation_ratio: float

    @classmethod
    def build(
        cls,
        *,
        source: object,
        model: object,
        dataset: object,
        device: str,
        confidence: object,
        image_size: object,
        frame_step: object,
        max_frames: object,
        validation_ratio: object,
    ) -> "AutoLabelConfig":
        """UI文字列から自動ラベル設定を構築して検証する。"""
        source_path = required_path(source, "アノテーション元")
        model_path = required_path(model, "ラベル用モデル")
        dataset_path = required_path(dataset, "データセット")
        if not source_path.exists():
            raise FileNotFoundError(f"入力が見つかりません: {source_path}")
        if source_path.is_file() and source_path.suffix.lower() not in MEDIA_EXTENSIONS:
            raise ValueError(f"未対応の入力形式です: {source_path.suffix}")
        if not model_path.is_file():
            raise FileNotFoundError(f"モデルが見つかりません: {model_path}")
        return cls(
            source=source_path,
            model=model_path,
            dataset=dataset_path,
            device=str(device).strip() or "auto",
            confidence=bounded_float(confidence, "conf", minimum=0.0, maximum=1.0, include_minimum=False),
            image_size=positive_int(image_size, "imgsz", minimum=32),
            frame_step=positive_int(frame_step, "抽出間隔"),
            max_frames=positive_int(max_frames, "最大枚数", minimum=0),
            validation_ratio=bounded_float(validation_ratio, "val比率", minimum=0.0, maximum=0.99),
        )


@dataclass(frozen=True)
class TrainingConfig:
    """再学習ワーカーへ渡す、検証済みの不変設定。"""

    dataset: Path
    base_model: Path
    output_root: Path
    run_name: str
    device: str
    epochs: int
    image_size: int
    batch: int
    export_model: Optional[Path]

    @classmethod
    def build(
        cls,
        *,
        dataset: object,
        base_model: object,
        output_root: object,
        run_name: str,
        device: str,
        epochs: object,
        image_size: object,
        batch: object,
        export_model: object,
    ) -> "TrainingConfig":
        """UI文字列から再学習設定を構築して検証する。"""
        dataset_path = required_path(dataset, "データセット")
        model_path = required_path(base_model, "ベースモデル")
        output_path = required_path(output_root, "学習出力先")
        name = str(run_name).strip()
        if not dataset_path.is_dir():
            raise FileNotFoundError(f"データセットが見つかりません: {dataset_path}")
        if not (dataset_path / "images" / "train").is_dir():
            raise ValueError("images/train がありません。YOLOデータセット構造を確認してください。")
        if not model_path.is_file():
            raise FileNotFoundError(f"ベースモデルが見つかりません: {model_path}")
        if not name:
            raise ValueError("run名を入力してください。")
        if Path(name).name != name or name in {".", ".."}:
            raise ValueError("run名にフォルダ区切りや相対パスは使用できません。")
        return cls(
            dataset=dataset_path,
            base_model=model_path,
            output_root=output_path,
            run_name=name,
            device=str(device).strip() or "auto",
            epochs=positive_int(epochs, "epochs"),
            image_size=positive_int(image_size, "imgsz", minimum=32),
            batch=positive_int(batch, "batch"),
            export_model=optional_path(export_model),
        )