# Source_code/routes/export_routes.py
from __future__ import annotations

import os
import json
import sqlite3
from pathlib import Path
import datetime

import pandas as pd
from flask import jsonify, send_file, render_template

from ..modules.db_manager import get_db_connection  # MAIN_DB_PATH は不要なら消してOK
from . import main


# =========================
# Bestモデルのクラス対応表を読む
# =========================
BEST_MODEL_CLASSES: dict[str, str] = {}
try:
    config_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
    )
    best_classes_path = os.path.join(config_dir, "best_model_classes.json")
    if os.path.exists(best_classes_path):
        with open(best_classes_path, "r", encoding="utf-8") as f:
            BEST_MODEL_CLASSES = json.load(f)
        print(f"[INFO] Loaded Best model classes: {BEST_MODEL_CLASSES}")
    else:
        print(f"[INFO] best_model_classes.json not found: {best_classes_path}")
except Exception as e:
    print(f"[WARNING] Failed to load best_model_classes.json: {e}")


# =========================
# Utility
# =========================
def ensure_calibration_dir() -> str:
    opt_files = os.getenv("Opt_files", "./output")
    opt_files = opt_files.strip('"').strip("'")
    calib_dir = os.path.join(opt_files, "calibrations")
    os.makedirs(calib_dir, exist_ok=True)
    return calib_dir


def get_calibration_data(profile_name: str | None):
    if not profile_name:
        return None
    calib_dir = ensure_calibration_dir()
    path = os.path.join(calib_dir, f"{profile_name}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _row_has(row: sqlite3.Row, key: str) -> bool:
    try:
        return key in row.keys()
    except Exception:
        return False


def _row_get(row: sqlite3.Row, key: str, default=None):
    return row[key] if _row_has(row, key) else default


def _norm_class_id(x):
    """
    class_id が 2 / 2.0 / "2" / "2.0" のどれでも必ず int(2) にする。
    SQLを触らずに export 側だけで吸収する。
    """
    if x is None:
        return None
    try:
        return int(float(x))
    except Exception:
        return None


# =========================
# Routes
# =========================
@main.route("/api/export/overtake_tracks")
def export_overtake_tracks():
    """
    Export all track data for groups involved in overtake events. (ADC_08)
    - Bestモデルのクラス名は best_model_classes.json を参照
    - SQL(DB)は変更しない（export側だけでclass_idの型ズレを吸収）
    """
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 1) OvertakeEvents 一覧
            query_events = """
                SELECT 
                    e.overtake_event_id as event_id, 
                    e.run_id, 
                    e.event_frame_num,
                    e.overtaker_group_id, 
                    e.overtaken_group_id,
                    p.output_folder,
                    p.calibration_profile,
                    v.filename as video_filename,
                    v.collection_year,
                    v.road_type
                FROM OvertakeEvents e
                LEFT JOIN ProcessLog p ON e.run_id = p.run_id
                LEFT JOIN Video v ON p.video_id = v.video_id
            """
            events = cursor.execute(query_events).fetchall()
            if not events:
                return "No overtake events found", 404

            all_rows: list[dict] = []

            # 2) 各イベントの overtaker / overtaken group の Detection を拾う
            query_tracks = """
                SELECT d.*, c.class_name
                FROM Detection d
                LEFT JOIN ClassMaster c ON d.class_id = c.class_id
                WHERE d.run_id = ? AND d.group_id IN (?, ?)
                ORDER BY d.frame_num ASC
            """

            for event in events:
                run_id = event["run_id"]
                ot_gid = event["overtaker_group_id"]
                on_gid = event["overtaken_group_id"]
                event_frame = event["event_frame_num"]

                tracks = cursor.execute(query_tracks, [run_id, ot_gid, on_gid]).fetchall()
                if not tracks:
                    continue

                for trk in tracks:
                    group_id = trk["group_id"]

                    # Role / partner
                    if group_id == ot_gid:
                        role = "Overtaking"
                        partner_id = on_gid
                    else:
                        role = "Overtaken"
                        partner_id = ot_gid

                    # offset frame
                    try:
                        offset_frame = int(trk["frame_num"]) - int(event_frame)
                    except Exception:
                        offset_frame = None

                    # --- クラス名の決定（ここが今回の要点）---
                    model_name = (_row_get(trk, "model_name", "") or "").lower()
                    cid_norm = _norm_class_id(trk["class_id"])

                    if model_name == "best":
                        # JSONは "0","1","2" ... をキーにしておく
                        class_name = BEST_MODEL_CLASSES.get(str(cid_norm)) if cid_norm is not None else None
                    else:
                        # YOLO側はClassテーブル由来
                        class_name = _row_get(trk, "class_name", None)

                    # distances (DB列が無い場合に備えて安全に読む)
                    line_dist_m = _row_get(trk, "line_distance_m", None)
                    dist_l_m = _row_get(trk, "l_line_distance_m", _row_get(trk, "distance_m", None))
                    dist_r_m = _row_get(trk, "r_line_distance_m", None)

                    row = {
                        "イベントID": event["event_id"],
                        "Run": run_id,
                        "動画名": event["video_filename"],
                        "動画フレーム": trk["frame_num"],
                        "オフセットフレーム": offset_frame,
                        "役割": role,
                        "Group ID": group_id,
                        "相手Group": partner_id,
                        "トラックID": _row_get(trk, "track_id", None),
                        "モデル": _row_get(trk, "model_name", None),
                        "クラスID": cid_norm,  # 正規化した int を出力（見やすい）
                        "クラス名": class_name,
                        "BBOX x1": _row_get(trk, "x1", None),
                        "BBOX y1": _row_get(trk, "y1", None),
                        "BBOX x2": _row_get(trk, "x2", None),
                        "BBOX y2": _row_get(trk, "y2", None),
                        "白線距離(m)": line_dist_m,
                        "左白線距離(m)": dist_l_m,
                        "右白線距離(m)": dist_r_m,
                        "離隔距離(m)": _row_get(trk, "clearance_distance_m", None),
                        "速度(km/h)": _row_get(trk, "speed_km_h", None),
                        "加速度(m/s2)": _row_get(trk, "acceleration_m_s2", None),
                    }
                    all_rows.append(row)

        if not all_rows:
            return "No track data found for events", 404

        # 3) CSV保存 & ダウンロード
        df = pd.DataFrame(all_rows)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        export_dir = Path("output/exports").resolve()
        export_dir.mkdir(parents=True, exist_ok=True)

        filename = f"overtake_tracks_adc08_{timestamp}.csv"
        save_path = export_dir / filename

        df.to_csv(save_path, index=False, encoding="utf-8-sig")

        print("\n==============================================", flush=True)
        print(f"📊 追い越し軌跡データを保存しました: {save_path}", flush=True)
        print("==============================================\n", flush=True)

        return send_file(
            str(save_path),
            mimetype="text/csv",
            as_attachment=True,
            download_name="overtake_tracks_export.csv",
        )

    except Exception as e:
        print(f"Export Error: {e}")
        return jsonify({"error": str(e)}), 500


@main.route("/export_page")
def export_page():
    return render_template("export_page.html")
