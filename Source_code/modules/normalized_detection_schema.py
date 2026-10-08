from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any


RAW_DETECTION_COLUMNS = [
    ("raw_detection_id", "auto_id"),
    ("run_id", "run_id"),
    ("video_id", "video_id"),
    ("frame_num", "frame_num"),
    ("model_name", "model_name"),
    ("class_id", "class_id"),
    ("class_name", "class_name"),
    ("confidence", "confidence"),
    ("track_id", "track_id"),
    ("x1", "x1"),
    ("y1", "y1"),
    ("x2", "x2"),
    ("y2", "y2"),
    ("created_at", "__timestamp__"),
]


DETECTION_METRIC_COLUMNS = [
    ("raw_detection_id", "auto_id"),
    ("run_id", "run_id"),
    ("group_id", "group_id"),
    ("obj_id", "obj_id"),
    ("speed_km_h", "speed_km_h"),
    ("pixel_speed", "pixel_speed"),
    ("pixel_speed_frame", "pixel_speed_frame"),
    ("xy_px_speedpx", "xy_px_speedpx"),
    ("xy_px_karikm", "xy_px_karikm"),
    ("xy_px_changeable", "xy_px_changeable"),
    ("xy_px_changeable_name", "xy_px_changeable_name"),
    ("lane_position_flag", "lane_position_flag"),
    ("distance_m", "distance_m"),
    ("front_vehicle_id", "front_vehicle_id"),
    ("front_distance_m", "front_distance_m"),
    ("ttc_s", "ttc_s"),
    ("acceleration_m_s2", "acceleration_m_s2"),
    ("acceleration_state", "acceleration_state"),
    ("approach_partner_group_id", "approach_partner_group_id"),
    ("approach_distance_m", "approach_distance_m"),
    ("approach_distance_px", "approach_distance_px"),
    ("clearance_distance_m", "clearance_distance_m"),
    ("clearance_distance_cm", "clearance_distance_cm"),
    ("clearance_distance_px", "clearance_distance_px"),
    ("travel_direction", "travel_direction"),
    ("measure_x", "measure_x"),
    ("measure_y", "measure_y"),
    ("scale_pixels_per_meter", "scale_pixels_per_meter"),
    ("x_pixels_per_meter", "x_pixels_per_meter"),
    ("l_line_distance", "l_line_distance"),
    ("l_line_distance_m", "l_line_distance_m"),
    ("l_line_distance_cm", "l_line_distance_cm"),
    ("r_line_distance", "r_line_distance"),
    ("r_line_distance_m", "r_line_distance_m"),
    ("r_line_distance_cm", "r_line_distance_cm"),
    ("line_distance", "line_distance"),
    ("line_distance_m", "line_distance_m"),
    ("line_distance_cm", "line_distance_cm"),
    ("l_line_cross_m", "l_line_cross_m"),
    ("r_line_cross_m", "r_line_cross_m"),
    ("center_line_overtake_status", "center_line_overtake_status"),
    ("white_line_overtake_status", "white_line_overtake_status"),
    ("oncoming_flag", "oncoming_flag"),
    ("updated_at", "__timestamp__"),
]


MANUAL_OVERRIDE_COLUMNS = [
    "manual_event_id",
    "role",
    "raw_detection_id",
    "run_id",
    "frame_num",
    "group_id",
    "track_id",
    "class_name",
    "measure_x",
    "measure_y",
    "x1",
    "y1",
    "x2",
    "y2",
    "speed_km_h",
    "pixel_speed",
    "pixel_speed_frame",
    "line_distance_m",
    "line_distance_cm",
    "line_distance_px",
    "left_line_distance_m",
    "left_line_distance_cm",
    "left_line_distance_px",
    "right_line_distance_m",
    "right_line_distance_cm",
    "right_line_distance_px",
    "clearance_distance_m",
    "clearance_distance_cm",
    "clearance_distance_px",
    "approach_distance_m",
    "approach_distance_px",
    "lane_width_m",
    "lane_width_px_reference",
    "lane_width_cm_per_px",
    "notes",
    "created_at",
    "updated_at",
]


def archive_database(
    db_path: str | Path,
    archive_dir: str | Path | None = None,
    *,
    label: str = "before_normalized_schema",
) -> Path:
    """Create a consistent sqlite backup file before schema migration."""
    source = Path(db_path).resolve()
    if not source.exists():
        raise FileNotFoundError(f"database not found: {source}")

    destination_dir = Path(archive_dir).resolve() if archive_dir else source.parent / "archive"
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = destination_dir / f"{source.stem}.{label}.{timestamp}{source.suffix}"

    source_uri = f"file:{source.as_posix()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
    return destination


def ensure_normalized_detection_schema(conn: sqlite3.Connection) -> None:
    _drop_empty_strict_normalized_tables(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS DetectionRaw (
            raw_detection_id INTEGER PRIMARY KEY,
            run_id INTEGER,
            video_id INTEGER,
            frame_num INTEGER,
            model_name TEXT,
            class_id INTEGER,
            class_name TEXT,
            confidence REAL,
            track_id INTEGER,
            x1 REAL,
            y1 REAL,
            x2 REAL,
            y2 REAL,
            created_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS DetectionMetrics (
            raw_detection_id INTEGER PRIMARY KEY,
            run_id INTEGER,
            group_id INTEGER,
            obj_id INTEGER,
            speed_km_h REAL,
            pixel_speed REAL,
            pixel_speed_frame REAL,
            xy_px_speedpx REAL,
            xy_px_karikm REAL,
            xy_px_changeable REAL,
            xy_px_changeable_name TEXT,
            lane_position_flag TEXT,
            distance_m REAL,
            front_vehicle_id INTEGER,
            front_distance_m REAL,
            ttc_s REAL,
            acceleration_m_s2 REAL,
            acceleration_state TEXT,
            approach_partner_group_id INTEGER,
            approach_distance_m REAL,
            approach_distance_px REAL,
            clearance_distance_m REAL,
            clearance_distance_cm REAL,
            clearance_distance_px REAL,
            travel_direction TEXT,
            measure_x REAL,
            measure_y REAL,
            scale_pixels_per_meter REAL,
            x_pixels_per_meter REAL,
            l_line_distance REAL,
            l_line_distance_m REAL,
            l_line_distance_cm REAL,
            r_line_distance REAL,
            r_line_distance_m REAL,
            r_line_distance_cm REAL,
            line_distance REAL,
            line_distance_m REAL,
            line_distance_cm REAL,
            l_line_cross_m REAL,
            r_line_cross_m REAL,
            center_line_overtake_status TEXT,
            white_line_overtake_status TEXT,
            oncoming_flag INTEGER,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ManualDetectionOverrides (
            override_id INTEGER PRIMARY KEY AUTOINCREMENT,
            manual_event_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('overtaker', 'overtaken')),
            raw_detection_id INTEGER,
            run_id INTEGER,
            frame_num INTEGER,
            group_id INTEGER,
            track_id INTEGER,
            class_name TEXT,
            measure_x REAL,
            measure_y REAL,
            x1 REAL,
            y1 REAL,
            x2 REAL,
            y2 REAL,
            speed_km_h REAL,
            pixel_speed REAL,
            pixel_speed_frame REAL,
            line_distance_m REAL,
            line_distance_cm REAL,
            line_distance_px REAL,
            left_line_distance_m REAL,
            left_line_distance_cm REAL,
            left_line_distance_px REAL,
            right_line_distance_m REAL,
            right_line_distance_cm REAL,
            right_line_distance_px REAL,
            clearance_distance_m REAL,
            clearance_distance_cm REAL,
            clearance_distance_px REAL,
            approach_distance_m REAL,
            approach_distance_px REAL,
            lane_width_m REAL,
            lane_width_px_reference REAL,
            lane_width_cm_per_px REAL,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(manual_event_id, role)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS SchemaMigrationLog (
            migration_id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_name TEXT NOT NULL,
            status TEXT NOT NULL,
            source_db_path TEXT,
            archive_path TEXT,
            detail_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_detection_raw_run_frame ON DetectionRaw(run_id, frame_num)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_detection_raw_video ON DetectionRaw(video_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_detection_metrics_run_group ON DetectionMetrics(run_id, group_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_manual_detection_overrides_run_frame ON ManualDetectionOverrides(run_id, frame_num)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_manual_detection_overrides_event ON ManualDetectionOverrides(manual_event_id)")
    conn.execute("DROP VIEW IF EXISTS DetectionNormalized")
    conn.execute(
        """
        CREATE VIEW DetectionNormalized AS
        SELECT
            r.raw_detection_id AS auto_id,
            r.run_id,
            r.video_id,
            r.class_id,
            r.frame_num,
            r.x1,
            r.y1,
            r.x2,
            r.y2,
            r.model_name,
            r.class_name,
            r.track_id,
            r.confidence,
            m.group_id,
            m.speed_km_h,
            m.pixel_speed,
            m.pixel_speed_frame,
            m.xy_px_speedpx,
            m.xy_px_karikm,
            m.xy_px_changeable,
            m.xy_px_changeable_name,
            m.lane_position_flag,
            m.distance_m,
            m.front_vehicle_id,
            m.front_distance_m,
            m.ttc_s,
            m.acceleration_m_s2,
            m.acceleration_state,
            m.approach_partner_group_id,
            m.approach_distance_m,
            m.approach_distance_px,
            m.clearance_distance_m,
            m.clearance_distance_cm,
            m.clearance_distance_px,
            m.travel_direction,
            m.measure_x,
            m.measure_y,
            m.scale_pixels_per_meter,
            m.x_pixels_per_meter,
            m.l_line_distance,
            m.l_line_distance_m,
            m.l_line_distance_cm,
            m.r_line_distance,
            m.r_line_distance_m,
            m.r_line_distance_cm,
            m.line_distance,
            m.line_distance_m,
            m.line_distance_cm,
            m.l_line_cross_m,
            m.r_line_cross_m,
            m.center_line_overtake_status,
            m.white_line_overtake_status,
            m.oncoming_flag
        FROM DetectionRaw r
        LEFT JOIN DetectionMetrics m ON m.raw_detection_id = r.raw_detection_id
        """
    )


def sync_normalized_detection_tables(
    conn: sqlite3.Connection,
    *,
    run_id: int | None = None,
    include_manual: bool = True,
) -> dict[str, int]:
    """Copy legacy Detection/ManualOvertakeEvents data into normalized tables."""
    ensure_normalized_detection_schema(conn)
    if not _table_exists(conn, "Detection"):
        return {"raw_rows": 0, "metric_rows": 0, "manual_override_rows": 0}

    params: tuple[Any, ...] = ()
    where_clause = ""
    if run_id is not None:
        params = (int(run_id),)
        where_clause = " WHERE run_id = ?"

    if include_manual:
        conn.execute(f"DELETE FROM ManualDetectionOverrides{where_clause}", params)
    conn.execute(f"DELETE FROM DetectionMetrics{where_clause}", params)
    conn.execute(f"DELETE FROM DetectionRaw{where_clause}", params)

    _insert_detection_copy(conn, "DetectionRaw", RAW_DETECTION_COLUMNS, where_clause, params)
    _insert_detection_copy(conn, "DetectionMetrics", DETECTION_METRIC_COLUMNS, where_clause, params)
    if include_manual:
        _insert_manual_overrides(conn, run_id=run_id)

    return {
        "raw_rows": _count_rows(conn, "DetectionRaw", run_id),
        "metric_rows": _count_rows(conn, "DetectionMetrics", run_id),
        "manual_override_rows": _count_rows(conn, "ManualDetectionOverrides", run_id),
    }


def record_schema_migration(
    conn: sqlite3.Connection,
    *,
    status: str,
    source_db_path: str | Path,
    archive_path: str | Path | None,
    details: dict[str, Any],
) -> None:
    ensure_normalized_detection_schema(conn)
    conn.execute(
        """
        INSERT INTO SchemaMigrationLog (
            migration_name, status, source_db_path, archive_path, detail_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "normalized_detection_schema",
            status,
            str(source_db_path),
            str(archive_path) if archive_path else None,
            json.dumps(details, ensure_ascii=False, sort_keys=True),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )


def _drop_empty_strict_normalized_tables(conn: sqlite3.Connection) -> None:
    tables = ("ManualDetectionOverrides", "DetectionMetrics", "DetectionRaw")
    if not all(_table_exists(conn, table) for table in tables):
        return
    if any(_count_rows(conn, table, None) for table in tables):
        return
    has_foreign_keys = any(
        conn.execute(f"PRAGMA foreign_key_list({table})").fetchone() is not None
        for table in tables
    )
    if not has_foreign_keys:
        return
    conn.execute("DROP VIEW IF EXISTS DetectionNormalized")
    for table in tables:
        conn.execute(f"DROP TABLE IF EXISTS {table}")


def _insert_detection_copy(
    conn: sqlite3.Connection,
    target_table: str,
    columns: list[tuple[str, str]],
    where_clause: str,
    params: tuple[Any, ...],
) -> None:
    detection_columns = _table_columns(conn, "Detection")
    target_columns = [target for target, _source in columns]
    select_exprs = [_select_expr(detection_columns, source) for _target, source in columns]
    sql = (
        f"INSERT INTO {target_table} ({', '.join(target_columns)}) "
        f"SELECT {', '.join(select_exprs)} FROM Detection d{where_clause}"
    )
    conn.execute(sql, params)


def _insert_manual_overrides(conn: sqlite3.Connection, *, run_id: int | None) -> None:
    if not _table_exists(conn, "ManualOvertakeEvents"):
        return
    manual_columns = _table_columns(conn, "ManualOvertakeEvents")
    params: tuple[Any, ...] = ()
    where_clause = ""
    if run_id is not None:
        params = (int(run_id),)
        where_clause = " WHERE m.run_id = ?"

    select_sql_parts = []
    for role in ("overtaker", "overtaken"):
        select_sql_parts.append(_manual_override_select(manual_columns, role, where_clause))
    sql = (
        f"INSERT INTO ManualDetectionOverrides ({', '.join(MANUAL_OVERRIDE_COLUMNS)}) "
        + " UNION ALL ".join(select_sql_parts)
    )
    conn.execute(sql, params * 2 if run_id is not None else ())


def _manual_override_select(manual_columns: set[str], role: str, where_clause: str) -> str:
    source_map = {
        "manual_event_id": "manual_event_id",
        "role": f"__literal__:{role}",
        "raw_detection_id": f"{role}_auto_id",
        "run_id": "run_id",
        "frame_num": "frame_num",
        "group_id": f"{role}_group_id",
        "track_id": f"{role}_track_id",
        "class_name": f"{role}_class_name",
        "measure_x": f"{role}_measure_x",
        "measure_y": f"{role}_measure_y",
        "x1": f"{role}_x1",
        "y1": f"{role}_y1",
        "x2": f"{role}_x2",
        "y2": f"{role}_y2",
        "speed_km_h": f"{role}_speed_km_h",
        "pixel_speed": f"{role}_pixel_speed",
        "pixel_speed_frame": f"{role}_pixel_speed_frame",
        "line_distance_m": f"{role}_line_distance_m",
        "line_distance_cm": f"{role}_line_distance_cm",
        "line_distance_px": f"{role}_line_distance_px",
        "left_line_distance_m": f"{role}_left_line_distance_m",
        "left_line_distance_cm": f"{role}_left_line_distance_cm",
        "left_line_distance_px": f"{role}_left_line_distance_px",
        "right_line_distance_m": f"{role}_right_line_distance_m",
        "right_line_distance_cm": f"{role}_right_line_distance_cm",
        "right_line_distance_px": f"{role}_right_line_distance_px",
        "clearance_distance_m": "clearance_distance_m",
        "clearance_distance_cm": "clearance_distance_cm",
        "clearance_distance_px": "clearance_distance_px",
        "approach_distance_m": "approach_distance_m",
        "approach_distance_px": "approach_distance_px",
        "lane_width_m": "lane_width_m",
        "lane_width_px_reference": "lane_width_px_reference",
        "lane_width_cm_per_px": "lane_width_cm_per_px",
        "notes": "notes",
        "created_at": "created_at",
        "updated_at": "updated_at",
    }
    expressions = [_manual_select_expr(manual_columns, source) for source in source_map.values()]
    return f"SELECT {', '.join(expressions)} FROM ManualOvertakeEvents m{where_clause}"


def _manual_select_expr(columns: set[str], source: str) -> str:
    if source.startswith("__literal__:"):
        return "'" + source.split(":", 1)[1].replace("'", "''") + "'"
    if source in columns:
        return f'm."{source}"'
    if source == "updated_at":
        return "CURRENT_TIMESTAMP"
    return "NULL"


def _select_expr(columns: set[str], source: str) -> str:
    if source == "__timestamp__":
        return "CURRENT_TIMESTAMP"
    if source in columns:
        return f'd."{source}"'
    return "NULL"


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _count_rows(conn: sqlite3.Connection, table_name: str, run_id: int | None) -> int:
    if not _table_exists(conn, table_name):
        return 0
    if run_id is None:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
    columns = _table_columns(conn, table_name)
    if "run_id" not in columns:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
    return int(
        conn.execute(f"SELECT COUNT(*) FROM {table_name} WHERE run_id = ?", (int(run_id),)).fetchone()[0]
    )
