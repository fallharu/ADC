import os
from typing import Any

def load_profile_metadata(calib_dir: str) -> dict[str, dict[str, Any]]:
    """キャリブレーションフォルダ内のプロファイルメタデータを一括読み込みする。"""
    meta = {}
    if not os.path.exists(calib_dir):
        return meta
        
    import glob
    import json
    
    files = glob.glob(os.path.join(calib_dir, "*.json"))
    for f in files:
        if os.path.basename(f).startswith("calibration_"):
            continue
            
        p_name = os.path.basename(f).replace(".json", "")
        try:
             with open(f, "r", encoding="utf-8") as fp:
                 data = json.load(fp)
                 has_cnt = bool(data.get("count_lines"))
                 # Add other useful metadata here if needed
                 meta[p_name] = {"has_count_line": has_cnt}
        except:
            meta[p_name] = {"has_count_line": False}
            
    return meta
