"""共通のキャリブレーションファイル読込ヘルパー。"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()


def _normalize_path(value: Optional[str], default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    return text.strip('"').strip("'")


def build_calibration_candidates(
    run_id: int,
    profile_name: Optional[str],
) -> Tuple[str, List[str]]:
    """候補となるキャリブレーションファイルパスを返す。"""

    opt_folder = _normalize_path(os.getenv("Opt_files"), "output")
    calib_dir = os.path.join(opt_folder, "calibrations")
    candidates: List[str] = []

    sanitized = (profile_name or "").strip()
    if sanitized:
        candidates.append(os.path.join(calib_dir, f"{sanitized}.json"))

    candidates.append(os.path.join(calib_dir, f"calibration_{run_id}.json"))
    return calib_dir, candidates


def load_calibration_json(
    run_id: int,
    profile_name: Optional[str],
) -> Tuple[Dict, str]:
    """キャリブレーションJSONを読み込み、辞書と使用したパスを返す。"""

    calib_dir, candidates = build_calibration_candidates(run_id, profile_name)
    attempted: List[str] = []
    for path in candidates:
        if not path:
            continue
        attempted.append(path)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh), path

    if not os.path.isdir(calib_dir):
        attempted.append(calib_dir)

    detail = ", ".join(attempted) if attempted else "<未探索>"
    raise FileNotFoundError(
        f"キャリブレーションファイルが見つかりません。探索したパス: {detail}"
    )
