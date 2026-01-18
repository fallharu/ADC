# Source_code/modules/all_save.py
import os
import csv
import sqlite3
import re
from datetime import datetime
from typing import Optional, Sequence, Tuple
from zipfile import ZipFile, ZIP_DEFLATED

from dotenv import load_dotenv

from .db_manager import (
    DETECTION_COLUMN_ORDER,
    MAIN_DB_PATH,
    configure_connection,
    ensure_detection_distance_columns,
)


def _resolve_detection_columns(cursor: sqlite3.Cursor) -> list[str]:
    """現在のDetectionテーブル構成から出力対象のカラム順を決定する。"""

    existing_columns = [row[1] for row in cursor.execute("PRAGMA table_info(Detection)")]
    if not existing_columns:
        raise ValueError("Detectionテーブルのカラム情報を取得できませんでした。")

    ordered_columns = [col for col in DETECTION_COLUMN_ORDER if col in existing_columns]
    additional_columns = [col for col in existing_columns if col not in ordered_columns]
    return ordered_columns + additional_columns


def create_all_save(run_id: int):
    load_dotenv()

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="write")
        ensure_detection_distance_columns()
        conn.commit()
        configure_connection(conn, mode="read")
        c = conn.cursor()

        sql = (
            "SELECT p.output_folder, v.filename "
            "FROM ProcessLog p JOIN Video v ON p.video_id=v.video_id WHERE p.run_id = ?"
        )
        res = c.execute(sql, (run_id,)).fetchone()
        if not res:
            raise ValueError("指定されたRun IDが見つかりません。")
        output_folder, _video_name = res[0], res[1]

        select_columns = _resolve_detection_columns(c)

        columns_clause = ", ".join(select_columns)
        query = (
            f"SELECT {columns_clause} FROM Detection "
            "WHERE run_id = ? ORDER BY frame_num, auto_id"
        )
        rows = c.execute(query, (run_id,)).fetchall()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = f"all_detections_run_{run_id}_{timestamp}.csv"
        normalized_output_folder = os.path.normpath(output_folder) if output_folder else ""
        if not normalized_output_folder:
            raise ValueError("出力フォルダが設定されていません。")

        os.makedirs(normalized_output_folder, exist_ok=True)
        csv_path = os.path.join(normalized_output_folder, csv_filename)

        with open(csv_path, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(select_columns)
            writer.writerows(rows)

        return csv_path


def _determine_output_directory(
    run_metadata: Sequence[Tuple[int, Optional[str], str]],
    *,
    explicit_dir: Optional[str] = None,
) -> str:
    """共通の出力ディレクトリを決定する。

    Parameters
    ----------
    run_metadata:
        (run_id, output_folder, video_filename) のタプル一覧。
    explicit_dir:
        呼び出し側で指定された出力先。指定があればそのまま利用する。
    """

    if explicit_dir:
        base = os.path.abspath(explicit_dir)
        os.makedirs(base, exist_ok=True)
        return base

    candidates = [
        os.path.normpath(folder)
        for (_, folder, _) in run_metadata
        if folder
    ]

    if not candidates:
        base = os.getcwd()
        os.makedirs(base, exist_ok=True)
        return base

    if len(candidates) == 1:
        base = os.path.abspath(candidates[0])
        os.makedirs(base, exist_ok=True)
        return base

    try:
        common = os.path.commonpath(candidates)
    except ValueError:
        common = candidates[0]

    base = os.path.abspath(common)
    os.makedirs(base, exist_ok=True)
    return base


def create_combined_detection_csv(
    run_ids: Sequence[int],
    *,
    folder_alias: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> Optional[str]:
    """複数RunのDetectionデータを1つのCSVへまとめて出力する。"""

    unique_ids = [int(r) for r in dict.fromkeys(run_ids)]
    if not unique_ids:
        return None

    placeholders = ", ".join(["?"] * len(unique_ids))

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="read")
        cursor = conn.cursor()

        select_columns = _resolve_detection_columns(cursor)
        column_clause = ", ".join(f"d.{col}" for col in select_columns)

        metadata = cursor.execute(
            f"""
            SELECT p.run_id, p.output_folder, v.filename
            FROM ProcessLog p
            JOIN Video v ON p.video_id = v.video_id
            WHERE p.run_id IN ({placeholders})
            ORDER BY p.run_id
            """,
            unique_ids,
        ).fetchall()

        if not metadata:
            return None

        rows = cursor.execute(
            f"""
            SELECT {column_clause}, v.filename AS video_filename
            FROM Detection d
            JOIN ProcessLog p ON d.run_id = p.run_id
            JOIN Video v ON p.video_id = v.video_id
            WHERE d.run_id IN ({placeholders})
            ORDER BY d.run_id, d.frame_num, d.auto_id
            """,
            unique_ids,
        ).fetchall()

    if not rows:
        return None

    base_dir = _determine_output_directory(metadata, explicit_dir=output_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if folder_alias:
        stem = _sanitize_bundle_name(folder_alias)
    elif len(unique_ids) == 1:
        stem = f"run_{unique_ids[0]}"
    else:
        stem = f"runs_{unique_ids[0]}_{unique_ids[-1]}"

    combined_name = f"{stem}_detections_combined_{timestamp}.csv"
    combined_path = os.path.join(base_dir, combined_name)

    header = select_columns + ["video_filename"]

    with open(combined_path, mode="w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)

    return combined_path


def _sanitize_bundle_name(value: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z._-]+", "_", value.strip())
    sanitized = sanitized.strip("._")
    return sanitized or "folder"


def create_csv_bundle(
    csv_paths: Sequence[str],
    *,
    folder_alias: Optional[str] = None,
    bundle_dir: Optional[str] = None,
) -> Optional[str]:
    """指定したCSVファイルを1つのZIPへまとめて出力する。"""

    valid_paths = []
    for path in csv_paths:
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
        if len(directories) == 1:
            base_dir = directories[0]
        else:
            base_dir = os.path.commonpath(directories)

    os.makedirs(base_dir, exist_ok=True)

    name_seed = folder_alias or os.path.basename(base_dir) or "folder"
    bundle_stem = _sanitize_bundle_name(name_seed)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_filename = f"{bundle_stem}_csv_bundle_{timestamp}.zip"
    bundle_path = os.path.join(base_dir, bundle_filename)

    suffix = 1
    while os.path.exists(bundle_path):
        bundle_filename = f"{bundle_stem}_csv_bundle_{timestamp}_{suffix}.zip"
        bundle_path = os.path.join(base_dir, bundle_filename)
        suffix += 1

    with ZipFile(bundle_path, "w", ZIP_DEFLATED) as archive:
        for csv_file in valid_paths:
            arcname = os.path.relpath(csv_file, base_dir)
            archive.write(csv_file, arcname)

    return bundle_path
