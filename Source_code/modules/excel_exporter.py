"""Detectionデータを日本語カラム付きExcelとして書き出すユーティリティ."""
from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional, Sequence

import xlsxwriter

from .db_manager import MAIN_DB_PATH, configure_connection


@dataclass(frozen=True)
class ExcelField:
    key: str
    label: str
    formatter: Optional[Callable[[Any, sqlite3.Row], Any]] = None


def _default_formatter(value: Any, _row: sqlite3.Row) -> Any:
    return value if value is not None else "-"


def _format_float(value: Any, _row: sqlite3.Row) -> Optional[float | str]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def _format_int(value: Any, _row: sqlite3.Row) -> Optional[int | str]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def _format_overtake(value: Any, _row: sqlite3.Row) -> str:
    return "あり" if int(value or 0) == 1 else "なし"


def _format_overtake_after(value: Any, _row: sqlite3.Row) -> str:
    return "追い越し後" if int(value or 0) == 1 else "-"


def _format_oncoming(value: Any, _row: sqlite3.Row) -> str:
    return "対向" if int(value or 0) == 1 else "-"


EXCEL_FIELDS: Sequence[ExcelField] = (
    ExcelField("auto_id", "検出ID", _format_int),
    ExcelField("run_id", "Run ID", _format_int),
    ExcelField("video_filename", "動画ファイル名"),
    ExcelField("class_name", "クラス名"),
    ExcelField("frame_num", "フレーム番号", _format_int),
    ExcelField("group_id", "グループID", _format_int),
    ExcelField("approach_partner_group_id", "接近相手グループID", _format_int),
    ExcelField("approach_distance_m", "接近距離(m)", _format_float),
    ExcelField("approach_distance_px", "接近距離(px)", _format_float),
    ExcelField("clearance_distance_cm", "離隔距離(cm)", _format_float),
    ExcelField("clearance_distance_m", "離隔距離(m)", _format_float),
    ExcelField("clearance_distance_px", "離隔距離(px)", _format_float),
    ExcelField("pixel_speed", "ピクセル速度", _format_float),
    ExcelField("pixel_speed_frame", "ピクセル移動量(px/f)", _format_float),
    ExcelField("speed_km_h", "速度(km/h)", _format_float),
    ExcelField("acceleration_m_s2", "加速度(m/s²)", _format_float),
    ExcelField("acceleration_state", "加減速区分"),
    ExcelField("travel_direction", "進行方向"),
    ExcelField("lane_position_flag", "白線内外区分"),
    ExcelField("l_line_distance", "左白線距離(m)", _format_float),
    ExcelField("r_line_distance", "右白線距離(m)", _format_float),
    ExcelField("line_distance", "最短白線距離(m)", _format_float),
    ExcelField("overtake", "追い越しフラグ", _format_overtake),
    ExcelField("overtake_after", "追い越し後フラグ", _format_overtake_after),
    ExcelField("overtake_window_offset", "追い越し±30f", _format_int),
    ExcelField("overtake_by", "追い越した車両Group", _format_int),
    ExcelField("overtake_by_second", "追い越された自転車Group", _format_int),
    ExcelField("oncoming_flag", "対向車フラグ", _format_oncoming),
    ExcelField("front_distance_m", "前方距離(m)", _format_float),
    ExcelField("ttc_s", "TTC(s)", _format_float),
)


def _sanitize_filename(value: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z._-]+", "_", value)
    sanitized = sanitized.strip("._")
    return sanitized or "run"


def _build_detection_rows(cursor: sqlite3.Cursor, run_id: int) -> list[sqlite3.Row]:
    query = """
        SELECT d.auto_id,
               d.run_id,
               v.filename AS video_filename,
               c.class_name,
               d.frame_num,
               d.group_id,
               d.approach_partner_group_id,
               d.approach_distance_m,
               d.approach_distance_px,
               d.clearance_distance_m,
               d.clearance_distance_cm,
               d.clearance_distance_px,
               d.pixel_speed,
               d.pixel_speed_frame,
               d.speed_km_h,
               d.acceleration_m_s2,
               d.acceleration_state,
               d.travel_direction,
               d.lane_position_flag,
               d.l_line_distance,
               d.r_line_distance,
               d.line_distance,
               d.overtake,
               d.overtake_after,
               d.overtake_window_offset,
               d.overtake_by,
               d.overtake_by_second,
               d.oncoming_flag,
               d.front_distance_m,
               d.ttc_s
        FROM Detection d
        LEFT JOIN Video v ON d.video_id = v.video_id
        LEFT JOIN Class c ON d.class_id = c.class_id
        WHERE d.run_id = ?
        ORDER BY d.frame_num, d.auto_id
    """
    cursor.execute(query, (run_id,))
    rows = cursor.fetchall()
    return rows


def _resolve_output_directory(cursor: sqlite3.Cursor, run_id: int) -> tuple[str, str]:
    meta = cursor.execute(
        """
        SELECT p.output_folder, v.filename
        FROM ProcessLog p
        JOIN Video v ON p.video_id = v.video_id
        WHERE p.run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if not meta:
        raise ValueError("指定されたRun IDが見つかりません。")
    output_folder, video_filename = meta
    if not output_folder:
        raise ValueError("出力フォルダが設定されていません。")
    normalized = os.path.normpath(output_folder)
    os.makedirs(normalized, exist_ok=True)
    return normalized, video_filename or ""


def create_detection_excel(run_id: int) -> str:
    """指定RunのDetectionデータをExcelファイルとして出力する。"""

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        configure_connection(conn, mode="read")
        cursor = conn.cursor()
        rows = _build_detection_rows(cursor, run_id)
        output_dir, video_filename = _resolve_output_directory(cursor, run_id)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = _sanitize_filename(f"run_{run_id}_{video_filename}" if video_filename else f"run_{run_id}")
    excel_filename = f"{stem}_detections_{timestamp}.xlsx"
    excel_path = os.path.join(output_dir, excel_filename)

    os.makedirs(os.path.dirname(excel_path), exist_ok=True)
    workbook = xlsxwriter.Workbook(excel_path)
    try:
        worksheet = workbook.add_worksheet("検出データ")

        header_format = workbook.add_format(
            {
                "bold": True,
                "bg_color": "#E9ECEF",
                "border": 1,
                "text_wrap": True,
                "align": "center",
                "valign": "vcenter",
            }
        )
        meta_label_format = workbook.add_format({"bold": True})
        default_format = workbook.add_format({"border": 1})

        row_index = 0
        worksheet.write(row_index, 0, "Run ID", meta_label_format)
        worksheet.write(row_index, 1, run_id, default_format)
        row_index += 1
        worksheet.write(row_index, 0, "動画ファイル", meta_label_format)
        worksheet.write(row_index, 1, video_filename or "-", default_format)
        row_index += 2  # blank row between meta and header

        header_row = row_index
        for col_index, field in enumerate(EXCEL_FIELDS):
            worksheet.write(header_row, col_index, field.label, header_format)
            worksheet.set_column(col_index, col_index, max(len(field.label) + 2, 14))

        data_start_row = header_row + 1
        for row_offset, record in enumerate(rows):
            excel_row = data_start_row + row_offset
            for col_index, field in enumerate(EXCEL_FIELDS):
                raw_value = record[field.key]
                formatter = field.formatter or _default_formatter
                value = formatter(raw_value, record)
                if isinstance(value, str):
                    worksheet.write(excel_row, col_index, value, default_format)
                else:
                    worksheet.write(excel_row, col_index, value, default_format)

        if rows:
            worksheet.autofilter(header_row, 0, data_start_row + len(rows) - 1, len(EXCEL_FIELDS) - 1)
        worksheet.freeze_panes(data_start_row, 0)
    finally:
        workbook.close()

    return excel_path


def create_excel_bundle(
    excel_paths: Sequence[str],
    *,
    folder_alias: Optional[str] = None,
    bundle_dir: Optional[str] = None,
) -> Optional[str]:
    """複数ExcelをZIPとしてまとめる。"""

    valid_paths: list[str] = []
    for path in excel_paths:
        if not path:
            continue
        abs_path = os.path.abspath(path)
        if os.path.isfile(abs_path):
            valid_paths.append(abs_path)

    if not valid_paths:
        return None

    directories = [os.path.dirname(p) for p in valid_paths]
    if bundle_dir:
        base_dir = os.path.abspath(bundle_dir)
    else:
        try:
            base_dir = os.path.commonpath(directories)
        except ValueError:
            base_dir = directories[0]

    os.makedirs(base_dir, exist_ok=True)

    name_seed = folder_alias or os.path.basename(base_dir) or "folder"
    bundle_stem = _sanitize_filename(name_seed)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_filename = f"{bundle_stem}_excel_bundle_{timestamp}.zip"
    bundle_path = os.path.join(base_dir, bundle_filename)

    suffix = 1
    while os.path.exists(bundle_path):
        bundle_filename = f"{bundle_stem}_excel_bundle_{timestamp}_{suffix}.zip"
        bundle_path = os.path.join(base_dir, bundle_filename)
        suffix += 1

    from zipfile import ZIP_DEFLATED, ZipFile

    with ZipFile(bundle_path, "w", ZIP_DEFLATED) as archive:
        for excel_file in valid_paths:
            arcname = os.path.relpath(excel_file, base_dir)
            archive.write(excel_file, arcname)

    return bundle_path
