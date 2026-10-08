import os
import json
from typing import Any, Dict

def load_folder_settings(folder_path: str) -> Dict[str, Any]:
    """フォルダごとの設定ファイル(folder_settings.json)を読み込む。"""
    settings_path = os.path.join(folder_path, "folder_settings.json")
    if not os.path.exists(settings_path):
        return {}
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_folder_settings(folder_path: str, settings: Dict[str, Any]) -> None:
    """フォルダごとの設定ファイルを保存する。"""
    settings_path = os.path.join(folder_path, "folder_settings.json")
    try:
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception:
        raise

def ensure_calibration_dir() -> str:
    """キャリブレーション保存ディレクトリを確保してパスを返す。"""
    opt_folder = os.getenv("Opt_files") or os.getenv("OPT_FILES") or "output"
    calib_dir = os.path.abspath(os.path.join(opt_folder, "calibrations"))
    os.makedirs(calib_dir, exist_ok=True)
    return calib_dir
