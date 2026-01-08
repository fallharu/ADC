import os
import math
import re
from typing import Optional, Dict, List, Any
from .manual_metrics import LANE_WIDTH_METERS
from ..tools.calibration_tool import sanitize_profile_name
from .inference import FOLDER_VIDEO_EXTENSIONS

ALLOWED_EXTENSIONS = {"mp4", "avi", "mov"}

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


def _extract_profile_name_candidate(value: Optional[str]) -> List[str]:
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
    candidates: List[str] = []
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

    candidates: List[str] = []

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
            if not remainder.strip():
                # If only stem remains, pop it
                segments.pop()
            elif remainder[0] in {"_", "-"} and any(ch.isdigit() for ch in remainder[1:]):
                 # Pattern like stem_01 or stem-01
                 segments.pop()
    
    return "/".join(segments)

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
