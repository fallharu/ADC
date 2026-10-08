"""フォルダ単位の既定設定を読み書きするユーティリティ."""
from __future__ import annotations

import json
import os
from typing import Any, Dict

FOLDER_METADATA_FILENAME = ".foldermeta.json"

_DEFAULT_SETTINGS: Dict[str, Any] = {
    "profile": "",
    "auto_postprocess": False,
    "auto_csv": False,
    "process_year": None,
    "location_id": None,
    "road_type": None,
    "vehicle_model": None,
    "tire_model": None,
    "subfolders": {},  # New: subfolder-specific settings
}


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "on"}


def _normalize_settings(data: Any) -> Dict[str, Any]:
    settings = dict(_DEFAULT_SETTINGS)
    if not isinstance(data, dict):
        return settings
    profile = data.get("profile", "")
    settings["profile"] = str(profile).strip() if isinstance(profile, str) else str(profile)
    settings["auto_postprocess"] = _normalize_bool(data.get("auto_postprocess"))
    settings["auto_csv"] = _normalize_bool(data.get("auto_csv"))
    try:
        year_raw = data.get("process_year")
        settings["process_year"] = int(year_raw) if year_raw not in (None, "") else None
    except (TypeError, ValueError):
        settings["process_year"] = None
    try:
        location_raw = data.get("location_id")
        settings["location_id"] = int(location_raw) if location_raw not in (None, "") else None
    except (TypeError, ValueError):
        settings["location_id"] = None
    
    rt_raw = data.get("road_type")
    settings["road_type"] = str(rt_raw).strip() if rt_raw not in (None, "") else None

    vm_raw = data.get("vehicle_model")
    settings["vehicle_model"] = str(vm_raw).strip() if vm_raw not in (None, "") else None

    tm_raw = data.get("tire_model")
    settings["tire_model"] = str(tm_raw).strip() if tm_raw not in (None, "") else None
    
    # Enable safe merge of subfolder dictionary
    sub_raw = data.get("subfolders")
    if isinstance(sub_raw, dict):
        cleaned_sub = {}
        for k, v in sub_raw.items():
            if k and v:  # Basic validation
                cleaned_sub[str(k).strip()] = str(v).strip()
        settings["subfolders"] = cleaned_sub
    else:
        settings["subfolders"] = {}

    return settings


def load_folder_settings_with_flag(directory: str) -> tuple[Dict[str, Any], bool]:
    """設定ファイルを読み込み、存在有無のフラグと共に返す."""

    path = os.path.join(directory, FOLDER_METADATA_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(_DEFAULT_SETTINGS), False
    return _normalize_settings(data), True


def load_folder_settings(directory: str) -> Dict[str, Any]:
    """指定ディレクトリの設定ファイルを読み込む."""

    settings, _ = load_folder_settings_with_flag(directory)
    return settings


def save_folder_settings(directory: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    """設定を正規化して保存し、保存結果を返す."""
    normalized = _normalize_settings(settings)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, FOLDER_METADATA_FILENAME)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(normalized, handle, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp_path, path)
    return normalized


def update_folder_settings(directory: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """既存の設定を読み込み、更新内容をマージして保存する."""
    current = load_folder_settings(directory)
    current.update(updates)
    return save_folder_settings(directory, current)
