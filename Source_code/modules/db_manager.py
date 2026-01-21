import sqlite3
import os
import contextlib
from typing import Optional, Any, List, Dict, Union
from datetime import datetime
from pathlib import Path

# --- Constants ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

def resolve_project_path(path_value: str) -> str:
    path = Path(os.path.expanduser(str(path_value)).strip('"'))
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return str(path)

# Determine DB path relative to project root or use env var
MAIN_DB_PATH = resolve_project_path(os.getenv("MAIN_DB_PATH", os.path.join("db", "my_app_data.db")))

def resolve_output_root(conn: Optional[sqlite3.Connection] = None) -> str:
    opt_root = resolve_project_path(os.getenv("Opt_files") or "output")
    try:
        if conn is None:
            with sqlite3.connect(MAIN_DB_PATH) as tmp_conn:
                tmp_conn.row_factory = sqlite3.Row
                rows = tmp_conn.execute(
                    "SELECT DISTINCT output_folder FROM ProcessLog "
                    "WHERE output_folder IS NOT NULL AND output_folder != ''"
                ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT output_folder FROM ProcessLog "
                "WHERE output_folder IS NOT NULL AND output_folder != ''"
            ).fetchall()

        paths = []
        for row in rows:
            value = row["output_folder"] if isinstance(row, sqlite3.Row) else row[0]
            if value:
                paths.append(os.path.abspath(value))
        if paths:
            return os.path.commonpath(paths)
    except Exception:
        pass
    return opt_root

SQLITE_CACHE_MB = -2000 # Default to ~2GB (negative value in kb) or use positive for pages
# Using standard default if not sure, but let's try to be smart
SQLITE_CACHE_MB = int(os.getenv("SQLITE_CACHE_MB", "512")) 
POSTPROCESS_MEMORY_MB = int(os.getenv("POSTPROCESS_MEMORY_MB", "4096"))
SQLITE_MAX_MMAP_BYTES = int(os.getenv("SQLITE_MAX_MMAP_BYTES", "0"))

DETECTION_COLUMN_ORDER = [
    "frame_num",
    "auto_id",
    "model_name",
    "class_name",
    "confidence",
    "track_id",
    "speed_km_h",
    "lane_position_flag",
    "distance_m",
    "ttc_s"
]

MANUAL_OVERTAKE_CONTEXT_WINDOW = 150

MANUAL_OVERTAKE_CONTEXT_COLUMNS = [
    "run_id", "frame_num", "video_time_s", "offset_frames",
    "overtaker_group_id", "overtaker_track_id", "overtaker_class_name",
    "overtaker_speed_km_h", "overtaker_pixel_speed", "overtaker_pixel_speed_frame",
    "overtaker_x1", "overtaker_y1", "overtaker_x2", "overtaker_y2",
    "overtaker_measure_x", "overtaker_measure_y",
    "overtaken_group_id", "overtaken_track_id", "overtaken_class_name",
    "overtaken_speed_km_h", "overtaken_pixel_speed", "overtaken_pixel_speed_frame",
    "overtaken_x1", "overtaken_y1", "overtaken_x2", "overtaken_y2",
    "overtaken_measure_x", "overtaken_measure_y",
    "approach_distance_m", "approach_distance_px",
    "clearance_distance_m", "clearance_distance_cm", "clearance_distance_px", "clearance_distance_px_ratio",
    "overtaker_line_distance_m", "overtaker_line_distance_cm", "overtaker_line_distance_px", "overtaker_line_distance_px_ratio",
    "overtaken_line_distance_m", "overtaken_line_distance_cm", "overtaken_line_distance_px", "overtaken_line_distance_px_ratio",
    "overtaker_left_line_distance_m", "overtaker_left_line_distance_cm", "overtaker_left_line_distance_px",
    "overtaker_right_line_distance_m", "overtaker_right_line_distance_cm", "overtaker_right_line_distance_px",
    "overtaken_left_line_distance_m", "overtaken_left_line_distance_cm", "overtaken_left_line_distance_px",
    "overtaken_right_line_distance_m", "overtaken_right_line_distance_cm", "overtaken_right_line_distance_px",
    "lane_width_m"
]

# --- Exceptions ---

class DatabaseInitializationError(Exception):
    """データベース初期化エラー"""
    pass

# --- Database Sidecar Files ---

def get_database_sidecar_files(db_path: str) -> List[Dict[str, Any]]:
    """データベースのサイドカーファイル(WAL, SHM)情報を取得"""
    sidecars = []
    base_path = os.path.abspath(db_path)
    
    # WAL file
    wal_path = base_path + "-wal"
    if os.path.exists(wal_path):
        sidecars.append({
            "name": os.path.basename(wal_path),
            "path": wal_path,
            "size": os.path.getsize(wal_path)
        })
    
    # SHM file
    shm_path = base_path + "-shm"
    if os.path.exists(shm_path):
        sidecars.append({
            "name": os.path.basename(shm_path),
            "path": shm_path,
            "size": os.path.getsize(shm_path)
        })
    
    return sidecars

def diagnose_sqlite_database(db_path: str) -> Dict[str, Any]:
    """データベースの診断情報を取得"""
    if not os.path.exists(db_path):
        return {"ok": False, "error": "Database file not found"}
    
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            # Basic integrity check
            cursor.execute("PRAGMA integrity_check")
            integrity = cursor.fetchone()[0]
            
            # Get size
            size_bytes = os.path.getsize(db_path)
            
            # Get table count
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            table_count = cursor.fetchone()[0]
            
            return {
                "ok": integrity == "ok",
                "integrity": integrity,
                "size_bytes": size_bytes,
                "size_mb": round(size_bytes / (1024 * 1024), 2),
                "table_count": table_count
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def create_new_main_database(db_path: str):
    """新しいデータベースを作成（既存のものを削除）"""
    if os.path.exists(db_path):
        backup_path = db_path + ".backup_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        os.rename(db_path, backup_path)
        print(f"Existing database backed up to: {backup_path}")
    
    # Delete sidecar files
    for suffix in ["-wal", "-shm"]:
        sidecar = db_path + suffix
        if os.path.exists(sidecar):
            os.remove(sidecar)
    
    # Initialize new database
    init_db()
    print(f"New database created at: {db_path}")

def replace_main_database(new_db_path: str, target_db_path: str):
    """既存のデータベースを新しいものに置き換える"""
    if not os.path.exists(new_db_path):
        raise DatabaseInitializationError(f"Source database not found: {new_db_path}")
    
    # Backup existing
    if os.path.exists(target_db_path):
        backup_path = target_db_path + ".backup_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        os.rename(target_db_path, backup_path)
    
    # Copy new database
    import shutil
    shutil.copy2(new_db_path, target_db_path)


# --- Connection Helpers ---

def configure_connection(conn: sqlite3.Connection, mode: str = "default", memory_mb: Optional[int] = None):
    """Apply performance settings to connection.
    
    Args:
        conn: SQLite connection
        mode: Connection mode ("default", "read", "write")
        memory_mb: Cache size in MB (overrides SQLITE_CACHE_MB if provided)
    """
    cache_mb = memory_mb if memory_mb is not None else SQLITE_CACHE_MB
    
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(f"PRAGMA cache_size={-1024 * cache_mb}")  # Negative value = KB
    conn.execute("PRAGMA foreign_keys=ON")
    if SQLITE_MAX_MMAP_BYTES > 0:
        conn.execute(f"PRAGMA mmap_size={SQLITE_MAX_MMAP_BYTES}")

@contextlib.contextmanager
def get_db_connection():
    """Context manager for database connection."""
    conn = sqlite3.connect(MAIN_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        configure_connection(conn)
        yield conn
    finally:
        conn.close()

def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None

def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}

def _get_table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    if not _table_exists(conn, table_name):
        return []
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cursor.fetchall()]

# --- Schema / Initialization ---

def ensure_video_metadata_columns(conn=None):
    """Ensure Video table has collection_year and road_type columns."""
    should_close = False
    if conn is None:
        conn = sqlite3.connect(MAIN_DB_PATH)
        should_close = True
        
    try:
        c = conn.cursor()
        
        # Check if Video table exists
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Video'")
        if not c.fetchone():
            return
        
        c.execute("PRAGMA table_info(Video)")
        columns = [row[1] for row in c.fetchall()]
        
        if "collection_year" not in columns:
            c.execute("ALTER TABLE Video ADD COLUMN collection_year INTEGER")
        if "road_type" not in columns:
            c.execute("ALTER TABLE Video ADD COLUMN road_type TEXT")
            
        conn.commit()
    finally:
        if should_close:
            conn.close()

def ensure_manual_overtake_event_columns(conn=None):
    """Ensure ManualOvertakeEvents table has necessary columns (migration)."""
    should_close = False
    if conn is None:
        conn = sqlite3.connect(MAIN_DB_PATH)
        should_close = True
        
    try:
        c = conn.cursor()
        
        # Check if table exists
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ManualOvertakeEvents'")
        if not c.fetchone():
            return # Will be created by init_db if missing

        c.execute("PRAGMA table_info(ManualOvertakeEvents)")
        columns = [row[1] for row in c.fetchall()]
        
        # List of columns to check and types
        required = {
            "clearance_distance_px_ratio": "REAL",
            "overtaker_line_distance_px_ratio": "REAL",
            "overtaken_line_distance_px_ratio": "REAL",
            "lane_width_m": "REAL",
            "lane_width_px_reference": "REAL",
            "lane_width_cm_per_px": "REAL",
            "context_frames": "TEXT",
            "notes": "TEXT",
            "created_at": "TEXT",
            "updated_at": "TEXT"
        }
        
        for col, dtype in required.items():
            if col not in columns:
                print(f"Migrating ManualOvertakeEvents: Adding {col}")
                c.execute(f"ALTER TABLE ManualOvertakeEvents ADD COLUMN {col} {dtype}")
        
        conn.commit()
    except Exception as e:
        print(f"Error during migration: {e}")
    finally:
        if should_close:
            conn.close()

def ensure_overtake_event_columns(conn=None):
    """Ensure OvertakeEvents table has necessary columns."""
    should_close = False
    if conn is None:
        conn = sqlite3.connect(MAIN_DB_PATH)
        should_close = True
        
    try:
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='OvertakeEvents'")
        if not c.fetchone():
            return

        c.execute("PRAGMA table_info(OvertakeEvents)")
        columns = [row[1] for row in c.fetchall()]
        
        required = {
            "overtaker_l_line_cross_m": "REAL",
            "overtaker_r_line_cross_m": "REAL",
            "overtaken_l_line_cross_m": "REAL",
            "overtaken_r_line_cross_m": "REAL"
        }
        
        for col, dtype in required.items():
            if col not in columns:
                print(f"Migrating OvertakeEvents: Adding {col}")
                c.execute(f"ALTER TABLE OvertakeEvents ADD COLUMN {col} {dtype}")
        
        conn.commit()
    except Exception as e:
        print(f"Error during OvertakeEvents migration: {e}")
    finally:
        if should_close:
            conn.close()

def ensure_detection_columns(conn=None):
    """Ensure Detection table has bbox and relation columns."""
    should_close = False
    if conn is None:
        conn = sqlite3.connect(MAIN_DB_PATH)
        should_close = True
        
    try:
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Detection'")
        if not c.fetchone():
            return

        c.execute("PRAGMA table_info(Detection)")
        columns = [row[1] for row in c.fetchall()]
        
        required = {
            "x1": "REAL", "y1": "REAL", "x2": "REAL", "y2": "REAL",
            "video_id": "INTEGER", "class_id": "INTEGER",
            "track_id": "INTEGER", "group_id": "INTEGER",
            "front_distance_m": "REAL",
            "acceleration_m_s2": "REAL",
            "acceleration_state": "TEXT",
            "approach_partner_group_id": "INTEGER",
            "approach_distance_m": "REAL",
            "clearance_distance_m": "REAL",
            "travel_direction": "TEXT",
            "l_line_distance_m": "REAL",
            "r_line_distance_m": "REAL",
            "line_distance_m": "REAL",
            "overtake": "INTEGER",
            "overtake_after": "INTEGER",
            "overtake_by": "TEXT",
            "l_line_cross_m": "REAL",
            "r_line_cross_m": "REAL"
        }
        
        for col, dtype in required.items():
            if col not in columns:
                print(f"Migrating Detection: Adding {col}")
                c.execute(f"ALTER TABLE Detection ADD COLUMN {col} {dtype}")
        
        conn.commit()
    except Exception as e:
        print(f"Error during Detection migration: {e}")
    finally:
        if should_close:
            conn.close()

def ensure_manual_annotation_schema(conn=None):
    """Ensure manual annotation tables and columns exist."""
    should_close = False
    if conn is None:
        conn = sqlite3.connect(MAIN_DB_PATH)
        should_close = True

    try:
        c = conn.cursor()

        # ManualOvertakeEvents columns
        ensure_manual_overtake_event_columns(conn)

        # ManualRunProgress table
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS ManualRunProgress (
                run_id INTEGER PRIMARY KEY,
                last_visit_at TEXT,
                last_review_at TEXT,
                last_annotation_at TEXT,
                created_at TEXT,
                updated_at TEXT,
                manual_status TEXT,
                FOREIGN KEY(run_id) REFERENCES ProcessLog(run_id)
            )
            """
        )

        # ManualOvertakeTimeline table
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS ManualOvertakeTimeline (
                timeline_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                frame_num INTEGER NOT NULL,
                overtaker_group_id INTEGER NOT NULL,
                overtaken_group_id INTEGER NOT NULL,
                notes TEXT,
                created_at TEXT,
                updated_at TEXT,
                last_event_id INTEGER,
                last_processed_at TEXT,
                manual_event_id INTEGER,
                is_deleted INTEGER DEFAULT 0,
                FOREIGN KEY(run_id) REFERENCES ProcessLog(run_id)
            )
            """
        )

        # ManualOvertakeContextBacklog table
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS ManualOvertakeContextBacklog (
                backlog_id INTEGER PRIMARY KEY AUTOINCREMENT,
                manual_event_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                frame_num INTEGER NOT NULL,
                event_payload_json TEXT NOT NULL,
                context_frames_json TEXT,
                created_at TEXT NOT NULL,
                processed_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                FOREIGN KEY(manual_event_id) REFERENCES ManualOvertakeEvents(manual_event_id) ON DELETE CASCADE
            )
            """
        )

        conn.commit()

        # ManualRunProgress columns
        progress_cols = _get_table_columns(conn, "ManualRunProgress")
        progress_required = {
            "last_visit_at": "TEXT",
            "last_review_at": "TEXT",
            "last_annotation_at": "TEXT",
            "created_at": "TEXT",
            "updated_at": "TEXT",
            "manual_status": "TEXT",
        }
        for col, dtype in progress_required.items():
            if col not in progress_cols:
                c.execute(f"ALTER TABLE ManualRunProgress ADD COLUMN {col} {dtype}")

        # ManualOvertakeTimeline columns
        timeline_cols = _get_table_columns(conn, "ManualOvertakeTimeline")
        timeline_required = {
            "created_at": "TEXT",
            "updated_at": "TEXT",
            "last_event_id": "INTEGER",
            "last_processed_at": "TEXT",
            "manual_event_id": "INTEGER",
            "is_deleted": "INTEGER DEFAULT 0",
        }
        for col, dtype in timeline_required.items():
            if col not in timeline_cols:
                c.execute(f"ALTER TABLE ManualOvertakeTimeline ADD COLUMN {col} {dtype}")

        # ManualOvertakeContextBacklog columns
        backlog_cols = _get_table_columns(conn, "ManualOvertakeContextBacklog")
        backlog_required = {
            "event_payload_json": "TEXT",
            "context_frames_json": "TEXT",
            "created_at": "TEXT",
            "processed_at": "TEXT",
            "status": "TEXT DEFAULT 'pending'",
            "error_message": "TEXT",
        }
        for col, dtype in backlog_required.items():
            if col not in backlog_cols:
                c.execute(
                    f"ALTER TABLE ManualOvertakeContextBacklog ADD COLUMN {col} {dtype}"
                )

        conn.commit()
    finally:
        if should_close:
            conn.close()


def ensure_overtake_stats_table(conn=None):
    """Ensure OvertakeStats table exists. (Statistics Feature)"""
    should_close = False
    if conn is None:
        conn = sqlite3.connect(MAIN_DB_PATH)
        should_close = True
        
    try:
        c = conn.cursor()
        
        # Check if table exists
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='OvertakeStats'")
        if not c.fetchone():
            print("Creating OvertakeStats table...")
            c.execute("""
                CREATE TABLE IF NOT EXISTS OvertakeStats (
                    stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER UNIQUE,
                    run_id INTEGER,
                    duration_s REAL,
                    is_out_of_bounds INTEGER,
                    area_m2 REAL,
                    trajectory_image_path TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(event_id) REFERENCES OvertakeEvents(event_id) ON DELETE CASCADE,
                    FOREIGN KEY(run_id) REFERENCES ProcessLog(run_id)
                )
            """)
        
        conn.commit()
    except Exception as e:
        print(f"Error during OvertakeStats creation: {e}")
    finally:
        if should_close:
            conn.close()


def init_db():
    """Initialize database tables."""
    ensure_video_metadata_columns()
    ensure_manual_overtake_event_columns()
    ensure_video_metadata_columns()
    ensure_processlog_columns()
    ensure_manual_overtake_event_columns()
    ensure_detection_columns()
    ensure_overtake_stats_table()
    
    with get_db_connection() as conn:
        # Video table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS Video (
                video_id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL UNIQUE,
                upload_datetime TEXT,
                fps REAL,
                duration REAL,
                source_path TEXT,
                collection_year INTEGER,
                road_type TEXT,
                location_point INTEGER,
                recorded_date TEXT
            )
        """)
        # ProcessLog table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ProcessLog (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER,
                process_start TEXT,
                process_end TEXT,
                output_folder TEXT,
                status TEXT,
                error_message TEXT,
                folder_alias TEXT,
                calibration_profile TEXT,
                process_year INTEGER,
                location_id INTEGER,
                is_folder_batch INTEGER DEFAULT 0,
                base_video_id INTEGER,
                FOREIGN KEY(video_id) REFERENCES Video(video_id)
            )
        """)
        # Detection table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS Detection (
                auto_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                video_id INTEGER,
                class_id INTEGER,
                frame_num INTEGER,
                model_name TEXT,
                class_name TEXT,
                confidence REAL,
                track_id INTEGER,
                x1 REAL, y1 REAL, x2 REAL, y2 REAL,
                speed_km_h REAL,
                xy_px_speedpx REAL,
                xy_px_karikm REAL,
                xy_px_changeable REAL,
                xy_px_changeable_name TEXT,
                lane_position_flag TEXT,
                distance_m REAL,
                group_id INTEGER,
                front_distance_m REAL,
                ttc_s REAL,
                acceleration_m_s2 REAL,
                acceleration_state TEXT,
                approach_partner_group_id INTEGER,
                approach_distance_m REAL,
                clearance_distance_m REAL,
                travel_direction TEXT,
                measure_x REAL,
                measure_y REAL,
                l_line_distance REAL,
                l_line_distance_m REAL,
                l_line_distance_cm REAL,
                r_line_distance REAL,
                r_line_distance_m REAL,
                r_line_distance_cm REAL,
                line_distance REAL,
                line_distance_m REAL,
                line_distance_cm REAL,
                overtake INTEGER,
                overtake_after INTEGER,
                overtake_by TEXT,
                l_line_cross_m REAL,
                r_line_cross_m REAL,
                center_line_overtake_status TEXT,
                white_line_overtake_status TEXT,
                FOREIGN KEY(run_id) REFERENCES ProcessLog(run_id)
            )
        """)
        # ClassMaster
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ClassMaster (
                class_id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_name TEXT UNIQUE
            )
        """)
        # OvertakeEvents - 追い越しイベント詳細（overtake.py と同期）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS OvertakeEvents (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                event_frame_num INTEGER,
                overtaker_group_id INTEGER,
                overtaken_group_id INTEGER,
                overtaker_auto_id INTEGER,
                overtaken_auto_id INTEGER,
                approach_distance_px REAL,
                approach_distance_m REAL,
                clearance_distance_px REAL,
                clearance_distance_m REAL,
                clearance_distance_cm REAL,
                l_line_distance REAL,
                l_line_distance_m REAL,
                l_line_distance_cm REAL,
                r_line_distance REAL,
                r_line_distance_m REAL,
                r_line_distance_cm REAL,
                line_distance REAL,
                line_distance_m REAL,
                line_distance_cm REAL,
                speed_profile_json TEXT,
                overtaker_l_line_cross_m REAL,
                overtaker_r_line_cross_m REAL,
                overtaken_l_line_cross_m REAL,
                overtaken_r_line_cross_m REAL,
                FOREIGN KEY(run_id) REFERENCES ProcessLog(run_id)
            )
        """)
        # OvertakeStats - 追い越し統計情報
        conn.execute("""
            CREATE TABLE IF NOT EXISTS OvertakeStats (
                stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER UNIQUE,
                run_id INTEGER,
                duration_s REAL,
                is_out_of_bounds INTEGER,
                area_m2 REAL,
                trajectory_image_path TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(event_id) REFERENCES OvertakeEvents(event_id) ON DELETE CASCADE,
                FOREIGN KEY(run_id) REFERENCES ProcessLog(run_id)
            )
        """)
        # TrafficCount - カウント線通過車両集計
        conn.execute("""
            CREATE TABLE IF NOT EXISTS TrafficCount (
                count_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                line_name TEXT,
                object_type TEXT,
                direction TEXT,
                count INTEGER,
                created_at TEXT,
                FOREIGN KEY(run_id) REFERENCES ProcessLog(run_id)
            )
        """)
        # ManualOvertakeEvents - 手動追い越しイベント
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ManualOvertakeEvents (
                manual_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                frame_num INTEGER,
                video_time_s REAL,
                
                overtaker_group_id INTEGER,
                overtaker_track_id INTEGER,
                overtaker_class_name TEXT,
                overtaker_speed_km_h REAL,
                overtaker_pixel_speed REAL,
                overtaker_pixel_speed_frame REAL,
                
                overtaken_group_id INTEGER,
                overtaken_track_id INTEGER,
                overtaken_class_name TEXT,
                overtaken_speed_km_h REAL,
                overtaken_pixel_speed REAL,
                overtaken_pixel_speed_frame REAL,
                
                approach_distance_m REAL,
                approach_distance_px REAL,
                
                clearance_distance_m REAL,
                clearance_distance_cm REAL,
                clearance_distance_px REAL,
                clearance_distance_px_ratio REAL,
                
                overtaker_line_distance_m REAL,
                overtaker_line_distance_cm REAL,
                overtaker_line_distance_px REAL,
                overtaker_line_distance_px_ratio REAL,
                
                overtaken_line_distance_m REAL,
                overtaken_line_distance_cm REAL,
                overtaken_line_distance_px REAL,
                overtaken_line_distance_px_ratio REAL,
                
                overtaker_left_line_distance_m REAL,
                overtaker_left_line_distance_cm REAL,
                overtaker_left_line_distance_px REAL,
                
                overtaker_right_line_distance_m REAL,
                overtaker_right_line_distance_cm REAL,
                overtaker_right_line_distance_px REAL,
                
                overtaken_left_line_distance_m REAL,
                overtaken_left_line_distance_cm REAL,
                overtaken_left_line_distance_px REAL,
                
                overtaken_right_line_distance_m REAL,
                overtaken_right_line_distance_cm REAL,
                overtaken_right_line_distance_px REAL,
                
                overtaker_measure_x REAL,
                overtaker_measure_y REAL,
                overtaken_measure_x REAL,
                overtaken_measure_y REAL,
                
                overtaker_x1 REAL, overtaker_y1 REAL, overtaker_x2 REAL, overtaker_y2 REAL,
                overtaken_x1 REAL, overtaken_y1 REAL, overtaken_x2 REAL, overtaken_y2 REAL,
                
                lane_width_m REAL,
                lane_width_px_reference REAL,
                lane_width_cm_per_px REAL,
                
                context_frames TEXT, -- JSON storage for efficiency
                
                notes TEXT,
                created_at TEXT,
                updated_at TEXT,
                
                FOREIGN KEY(run_id) REFERENCES ProcessLog(run_id)
            )
        """)

        # ManualRunProgress - 手動確認の進捗
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ManualRunProgress (
                run_id INTEGER PRIMARY KEY,
                last_visit_at TEXT,
                last_review_at TEXT,
                last_annotation_at TEXT,
                created_at TEXT,
                updated_at TEXT,
                manual_status TEXT,
                FOREIGN KEY(run_id) REFERENCES ProcessLog(run_id)
            )
        """)

        # ManualOvertakeTimeline - イベント履歴（タイムライン）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ManualOvertakeTimeline (
                timeline_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                frame_num INTEGER NOT NULL,
                overtaker_group_id INTEGER NOT NULL,
                overtaken_group_id INTEGER NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_event_id INTEGER,
                last_processed_at TEXT,
                manual_event_id INTEGER,
                is_deleted INTEGER DEFAULT 0,
                FOREIGN KEY(run_id) REFERENCES ProcessLog(run_id),
                FOREIGN KEY(last_event_id) REFERENCES ManualOvertakeEvents(manual_event_id) ON DELETE SET NULL,
                UNIQUE(run_id, frame_num, overtaker_group_id, overtaken_group_id)
            )
        """)

        # ManualContextBacklog - コンテキスト処理待ち行列
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ManualOvertakeContextBacklog (
                backlog_id INTEGER PRIMARY KEY AUTOINCREMENT,
                manual_event_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                frame_num INTEGER NOT NULL,
                event_payload_json TEXT NOT NULL,
                context_frames_json TEXT,
                created_at TEXT NOT NULL,
                processed_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                FOREIGN KEY(manual_event_id) REFERENCES ManualOvertakeEvents(manual_event_id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS ManualContextBacklog (
                backlog_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                frame_num INTEGER,
                manual_event_id INTEGER,
                status TEXT DEFAULT 'pending', -- pending, processing, completed, error
                created_at TEXT,
                updated_at TEXT,
                retry_count INTEGER DEFAULT 0,
                error_message TEXT,
                payload_json TEXT
            )
        """)
        # Run table compatibility (view or alias)
        # Some old code query 'Run'
        conn.execute("CREATE VIEW IF NOT EXISTS Run AS SELECT * FROM ProcessLog")

def get_or_create_video_id(conn, filename, duration, fps, source_path=None, road_type=None, collection_year=None):
    cur = conn.cursor()
    cur.execute("SELECT video_id FROM Video WHERE filename = ?", (filename,))
    row = cur.fetchone()
    if row:
        video_id = row[0]
        # Update metadata if provided
        updates = []
        params = []
        if road_type is not None:
             updates.append("road_type = ?")
             params.append(road_type)
        if collection_year is not None:
             updates.append("collection_year = ?")
             params.append(collection_year)
        
        if updates:
             params.append(video_id)
             cur.execute(f"UPDATE Video SET {', '.join(updates)} WHERE video_id = ?", params)
             conn.commit()
        return video_id
    
    upload_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        INSERT INTO Video (filename, upload_datetime, duration, fps, source_path, road_type, collection_year)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (filename, upload_datetime, duration, fps, source_path, road_type, collection_year))
    # Don't commit here if conn is shared transaction, but usually safer to commit creation
    conn.commit()
    return cur.lastrowid

def create_process_log(conn, video_id, process_start, output_folder, folder_alias=None, is_folder_batch=False, process_year=None, location_id=None):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ProcessLog (video_id, base_video_id, process_start, output_folder, folder_alias, status, process_year, location_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (video_id, video_id, process_start, output_folder, folder_alias, "processing", process_year, location_id))
    conn.commit()
    return cur.lastrowid

def delete_runs_for_video(conn, video_id):
    """ 指定した video_id に紐づく全Runとその関連データを削除する（Cascade Delete） """
    cur = conn.cursor()
    # 1. Get List of Run IDs
    cur.execute("SELECT run_id FROM ProcessLog WHERE video_id = ?", (video_id,))
    runs = cur.fetchall()
    run_ids = [r[0] for r in runs]
    
    if not run_ids:
        return

    # Delete related data for these runs
    # Placeholders for IN clause
    placeholders = ','.join('?' for _ in run_ids)
    
    tables_to_clean = [
        "Detection", 
        "OvertakeEvents", 
        "ManualOvertakeEvents", 
        "TrafficCount",
        # Add other tables if they have run_id FK
    ]
    
    for table in tables_to_clean:
        try:
            # Check if table exists to avoid errors on partial migrations
            cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            if cur.fetchone():
                cur.execute(f"DELETE FROM {table} WHERE run_id IN ({placeholders})", run_ids)
        except Exception as e:
            print(f"Error deleting from {table}: {e}")

    # Delete ProcessLogs
    cur.execute(f"DELETE FROM ProcessLog WHERE run_id IN ({placeholders})", run_ids)
    conn.commit()
    print(f"[DB] Cleanup: Deleted {len(run_ids)} runs and related data for video_id={video_id}")

def update_process_log(conn, run_id, status, error_message=None):
    cur = conn.cursor()
    updates = ["status = ?"]
    params = [status]
    if error_message:
        updates.append("error_message = ?")
        params.append(error_message)
    
    if status in ('completed', 'error'):
        updates.append("process_end = ?")
        params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    sql = f"UPDATE ProcessLog SET {', '.join(updates)} WHERE run_id = ?"
    params.append(run_id)
    cur.execute(sql, params)
    conn.commit()

def log_error(conn, run_id, message, stack_trace=None):
    print(f"[ERROR Log] RunID={run_id}: {message}")
    if run_id:
        update_process_log(conn, run_id, "error", message)

def get_or_create_class_id(conn, class_name):
    cur = conn.cursor()
    cur.execute("SELECT class_id FROM ClassMaster WHERE class_name = ?", (class_name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO ClassMaster (class_name) VALUES (?)", (class_name,))
    # conn.commit()
    return cur.lastrowid


def ensure_detection_distance_columns():
    """Ensure Detection table has distance related columns."""
    should_close = False
    conn = None
    try:
        conn = sqlite3.connect(MAIN_DB_PATH)
        should_close = True
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Detection'")
        if not c.fetchone():
            return

        c.execute("PRAGMA table_info(Detection)")
        columns = [row[1] for row in c.fetchall()]

        required = {
            "measure_x": "REAL",
            "measure_y": "REAL",
            "l_line_distance": "REAL",
            "l_line_distance_m": "REAL",
            "l_line_distance_cm": "REAL",
            "r_line_distance": "REAL",
            "r_line_distance_m": "REAL",
            "r_line_distance_cm": "REAL",
            "line_distance": "REAL",
            "line_distance_m": "REAL",
            "line_distance_cm": "REAL",
            "lane_position_flag": "TEXT",
            "l_line_cross_m": "REAL",
            "r_line_cross_m": "REAL",
            "center_line_overtake_status": "TEXT",
            "white_line_overtake_status": "TEXT",
        }

        for col, dtype in required.items():
            if col not in columns:
                print(f"Migrating Detection: Adding {col}")
                c.execute(f"ALTER TABLE Detection ADD COLUMN {col} {dtype}")

        conn.commit()
    except Exception as e:
        print(f"Error during Detection distance migration: {e}")
    finally:
        if should_close and conn:
            conn.close()


def ensure_detection_xy_speed_columns():
    """Ensure Detection table has xy speed related columns."""
    should_close = False
    conn = None
    try:
        conn = sqlite3.connect(MAIN_DB_PATH)
        should_close = True
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Detection'")
        if not c.fetchone():
            return

        c.execute("PRAGMA table_info(Detection)")
        columns = [row[1] for row in c.fetchall()]

        required = {
            "xy_px_speedpx": "REAL",
            "xy_px_karikm": "REAL",
            "xy_px_changeable": "REAL",
            "xy_px_changeable_name": "TEXT",
        }

        for col, dtype in required.items():
            if col not in columns:
                print(f"Migrating Detection: Adding {col}")
                c.execute(f"ALTER TABLE Detection ADD COLUMN {col} {dtype}")

        conn.commit()
    except Exception as e:
        print(f"Error during Detection xy speed migration: {e}")
    finally:
        if should_close and conn:
            conn.close()

def ensure_processlog_columns():
    """Ensure ProcessLog table has necessary columns."""
    with get_db_connection() as conn:
        c = conn.cursor()
        
        # Check if table exists first
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ProcessLog'")
        if not c.fetchone():
            return

        try:
            c.execute("SELECT is_folder_batch FROM ProcessLog LIMIT 1")
        except sqlite3.OperationalError:
            print("Migrating ProcessLog: Adding is_folder_batch")
            c.execute("ALTER TABLE ProcessLog ADD COLUMN is_folder_batch INTEGER DEFAULT 0")
            conn.commit()

# --- Core Run / Detection Functions ---

def list_detection_runs(page=1, per_page=20):
    """List detection runs (ProcessLog joined with Video) - placeholder logic."""
    # This might need to return a complex structure used by index.py
    # For now, implemented as a simple query
    with get_db_connection() as conn:
        c = conn.cursor()
        # Basic query matching likely schema with ManualRunProgress for status
        sql = """
            SELECT 
                p.run_id, p.process_start as created_at, 
                v.filename, v.collection_year, v.road_type,
                m.manual_status
            FROM ProcessLog p
            LEFT JOIN Video v ON p.video_id = v.video_id
            LEFT JOIN ManualRunProgress m ON p.run_id = m.run_id
            ORDER BY p.run_id DESC
        """
        rows = c.execute(sql).fetchall()
        return [dict(r) for r in rows]

def list_runs_for_manual_tool():
    """手動ツール用にRUN一覧と詳細ステータスを取得する。"""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        sql = """
        SELECT 
            p.run_id,
            v.filename,
            v.collection_year,
            v.road_type,
            m.last_visit_at,
            (SELECT COUNT(*) FROM ManualOvertakeEvents moe WHERE moe.run_id = p.run_id) as manual_count,
            (SELECT COUNT(*) FROM OvertakeEvents oe WHERE oe.run_id = p.run_id) as auto_count
        FROM ProcessLog p
        LEFT JOIN Video v ON p.video_id = v.video_id
        LEFT JOIN ManualRunProgress m ON p.run_id = m.run_id
        ORDER BY p.run_id DESC
        """
        rows = c.execute(sql).fetchall()
        
        results = []
        for r in rows:
            d = dict(r)
            if d['manual_count'] > 0:
                d['manual_status'] = 'annotated'
            elif d['auto_count'] > 0 and not d['last_visit_at']:
                d['manual_status'] = 'new_auto'
            elif d['last_visit_at']:
                 d['manual_status'] = 'visited'
            else:
                d['manual_status'] = 'new'
            results.append(d)
        return results

def get_all_runs_with_stats():

    """全Runの情報と統計を取得（検証済みコードの再実装）"""
    with get_db_connection() as conn:
        c = conn.cursor()
        
        # Use ProcessLog directly - it's the main table for run records
        sql = """
        SELECT 
            r.run_id,
            r.process_start as created_at,
            v.filename,
            v.collection_year,
            v.road_type,
            COUNT(d.auto_id) as detection_count
        FROM ProcessLog r
        LEFT JOIN Video v ON r.video_id = v.video_id
        LEFT JOIN Detection d ON r.run_id = d.run_id
        GROUP BY r.run_id
        ORDER BY r.run_id DESC
        """
        rows = c.execute(sql).fetchall()
        return [dict(row) for row in rows]

def batch_update_run_attributes(run_ids: List[int], collection_year: Optional[int] = None, road_type: Optional[str] = None) -> int:
    """複数のRunに紐づくVideoの属性を一括更新"""
    with get_db_connection() as conn:
        c = conn.cursor()
        
        updates = []
        params = []
        
        if collection_year is not None:
            updates.append("collection_year = ?")
            params.append(collection_year)
        
        if road_type is not None:
            updates.append("road_type = ?")
            params.append(road_type)
        
        if not updates:
            return 0

        # Runからvideo_idを取得
        run_placeholders = ','.join(['?'] * len(run_ids))
        sub_sql = f"SELECT DISTINCT video_id FROM ProcessLog WHERE run_id IN ({run_placeholders}) AND video_id IS NOT NULL"
        video_ids_rows = c.execute(sub_sql, run_ids).fetchall()
        video_ids = [r[0] for r in video_ids_rows]
        
        if not video_ids:
            return 0

        video_placeholders = ','.join(['?'] * len(video_ids))
        final_params = list(params) + video_ids
        
        sql = f"UPDATE Video SET {', '.join(updates)} WHERE video_id IN ({video_placeholders})"
        c.execute(sql, final_params)
        conn.commit()
        return c.rowcount

def update_run_profiles(run_ids: List[int], profile_name: str) -> int:
    """多个Runのcalibration_profileを一括更新"""
    with get_db_connection() as conn:
        c = conn.cursor()
        
        if not run_ids:
            return 0
            
        placeholders = ','.join(['?'] * len(run_ids))
        params = [profile_name] + run_ids
        
        sql = f"UPDATE ProcessLog SET calibration_profile = ? WHERE run_id IN ({placeholders})"
        c.execute(sql, params)
        conn.commit()
        return c.rowcount

def get_run_video_info(run_id, upload_base_folder=None):
    """Runに関連する動画ファイルの情報を取得する"""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        sql = """
            SELECT 
                p.run_id, 
                p.folder_alias as profile_name,
                p.output_folder,
                p.calibration_profile,
                v.filename, 
                v.source_path,
                v.fps,
                v.duration,
                v.collection_year,
                v.road_type

            FROM ProcessLog p
            LEFT JOIN Video v ON p.video_id = v.video_id
            WHERE p.run_id = ?
        """
        row = cur.execute(sql, (run_id,)).fetchone()
        
        if not row:
            return None
        
        info = dict(row)
        
        # パス解決ロジック
        video_path = info.get('source_path')
        filename = info.get('filename')
        folder_alias = info.get('profile_name')  # ProcessLog.folder_alias
        output_folder = info.get('output_folder')
        
        # upload_base_folder のデフォルト値
        if not upload_base_folder:
            upload_base_folder = os.getenv("Upload_folder", "uploads")
        
        # Case 1: source_path が有効
        if video_path and os.path.exists(video_path):
            info['path'] = video_path
            return info
        
        # Case 2: filenameがあればupload_base_folder内を探索
        if filename and upload_base_folder:
            # Direct path
            candidate = os.path.join(upload_base_folder, filename)
            if os.path.exists(candidate):
                video_path = candidate
            
            # folder_alias based path (例: uploads/2_/20250713/xxx.mp4)
            if not video_path and folder_alias:
                candidate_alias = os.path.join(upload_base_folder, folder_alias, filename)
                if os.path.exists(candidate_alias):
                    video_path = candidate_alias
        
        # Case 3: Videoテーブルにデータがなくてもfolder_aliasから動画を探す
        if not video_path and folder_alias and upload_base_folder:
            alias_folder = os.path.join(upload_base_folder, folder_alias)
            if os.path.isdir(alias_folder):
                # フォルダ内の動画ファイルを検索
                video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.webm')
                try:
                    for f in os.listdir(alias_folder):
                        if f.lower().endswith(video_extensions):
                            candidate = os.path.join(alias_folder, f)
                            if os.path.isfile(candidate):
                                video_path = candidate
                                info['filename'] = f  # 発見したファイル名をセット
                                break
                except Exception:
                    pass
        
        # Case 4: output_folder から探索
        if not video_path and output_folder:
            if os.path.isdir(output_folder):
                video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.webm')
                try:
                    for f in os.listdir(output_folder):
                        if f.lower().endswith(video_extensions):
                            candidate = os.path.join(output_folder, f)
                            if os.path.isfile(candidate):
                                video_path = candidate
                                info['filename'] = f
                                break
                except Exception:
                    pass
                    
        info['path'] = video_path
        return info



        # ProcessLogから直接video_idを取得
        # (Runビューは単なるProcessLogのエイリアスなので、直接ProcessLogを使用)
        placeholders = ','.join('?' * len(run_ids))
        video_ids_query = f"SELECT DISTINCT video_id FROM ProcessLog WHERE run_id IN ({placeholders})"
        video_rows = c.execute(video_ids_query, run_ids).fetchall()
        video_ids = [row[0] for row in video_rows if row[0] is not None]
        
        if not video_ids:
            return 0
        
        # Update Video
        video_placeholders = ','.join('?' * len(video_ids))
        params_with_ids = params + video_ids
        
        sql = f"UPDATE Video SET {', '.join(updates)} WHERE video_id IN ({video_placeholders})"
        
        c.execute(sql, params_with_ids)
        conn.commit()
        
        return c.rowcount

def get_all_road_types() -> List[str]:
    """Videoテーブルから登録済みのroad_type一覧を取得する(重複なし)"""
    if "MAIN_DB_PATH" not in globals():
        return []

    with get_db_connection() as conn:
        c = conn.cursor()
        try:
            c.execute("SELECT DISTINCT road_type FROM Video WHERE road_type IS NOT NULL AND road_type != ''")
            rows = c.fetchall()
            return sorted([r[0] for r in rows])
        except sqlite3.Error:
            return []

# --- Search / Filter / Misc ---

def get_detection_search_fields():
    """Return list of fields available for search."""
    return [
        {"key": "run_id", "label": "Run ID", "type": "number", "coerce": "int"},
        {"key": "class_name", "label": "クラス名", "type": "text"},
        {"key": "confidence", "label": "信頼度", "type": "number", "coerce": "float"},
        {"key": "distance_m", "label": "車間距離(m)", "type": "number", "coerce": "float"},
        {"key": "ttc_s", "label": "TTC(s)", "type": "number", "coerce": "float"},
        {"key": "line_distance_m", "label": "白線距離(m)", "type": "number", "coerce": "float"},
        {"key": "acceleration_m_s2", "label": "加速度(m/s²)", "type": "number", "coerce": "float"},
        {"key": "acceleration_state", "label": "加速状態", "type": "enum", "options": [
            {"value": "加速", "label": "加速"},
            {"value": "減速", "label": "減速"},
            {"value": "定速", "label": "定速"}
        ]},
        {"key": "group_id", "label": "グループID", "type": "number", "coerce": "int"},
        {"key": "overtake", "label": "追い越し (有無)", "type": "presence"},
        {"key": "overtake_after", "label": "追い越し後 (有無)", "type": "presence"},
        {"key": "overtake_by", "label": "追い越し者", "type": "text"},
    ]


def show_recent_detections(page=1, per_page=50, run_id=None, sort_by=None, sort_order='asc', **kwargs):
    """Retrieve detections with pagination, search, and sorting."""
    with get_db_connection() as conn:
        c = conn.cursor()
        offset = (page - 1) * per_page
        where = []
        params = []
        if run_id:
            where.append("d.run_id = ?")
            params.append(run_id)
        
        search = kwargs.get('search')
        if search:
            field = search.get('field')
            # Search Mapping
            field_map = {
                'run_id': 'd.run_id',
                'class_name': 'cm.class_name',
                'confidence': 'd.confidence',
                'distance_m': 'd.front_distance_m',
                'ttc_s': 'd.ttc_s',
                'line_distance_m': 'd.line_distance_m',
                'acceleration_m_s2': 'd.acceleration_m_s2',
                'acceleration_state': 'd.acceleration_state',
                'group_id': 'd.group_id',
                'overtake': 'd.overtake',
                'overtake_after': 'd.overtake_after',
                'overtake_by': 'd.overtake_by',
            }
            
            sql_col = field_map.get(field)
            if sql_col:
                if 'min' in search and search['min'] is not None:
                    where.append(f"{sql_col} >= ?")
                    params.append(search['min'])
                if 'max' in search and search['max'] is not None:
                    where.append(f"{sql_col} <= ?")
                    params.append(search['max'])
                if 'value' in search and search['value'] is not None:
                    val = search['value']
                    # Handle specific types
                    if field == 'class_name' or field == 'overtake_by':
                         where.append(f"{sql_col} LIKE ?")
                         params.append(f"%{val}%")
                    elif field in ('overtake', 'overtake_after'):
                        if val == 'has':
                             where.append(f"{sql_col} = 1")
                        elif val == 'missing':
                             where.append(f"({sql_col} IS NULL OR {sql_col} = 0)")
                    elif field == 'acceleration_state':
                         where.append(f"{sql_col} = ?")
                         params.append(val)
                    else:
                         # Default exact match for numbers/others
                         where.append(f"{sql_col} = ?")
                         params.append(val)
            
        where_clause = "WHERE " + " AND ".join(where) if where else ""
        
        # Get total count
        count_sql = f"SELECT COUNT(*) FROM Detection d {where_clause}"
        total = c.execute(count_sql, params).fetchone()[0]
        
        # Column mapping: template name -> SQL expression
        sortable_columns = {
            'detection_id': 'd.auto_id',
            'run_id': 'd.run_id',
            'frame_num': 'd.frame_num',
            'class_name': 'cm.class_name',
            'confidence': 'd.confidence',
            'absolute_speed_kmph': 'd.speed_km_h',
            'distance_m': 'd.front_distance_m',
            'ttc_s': 'd.ttc_s',
            'line_distance_m': 'd.line_distance_m',
            'acceleration_m_s2': 'd.acceleration_m_s2',
            'acceleration_state': 'd.acceleration_state',
            'group_id': 'd.group_id',
            'approach_distance_m': 'd.approach_distance_m',
            'clearance_distance_m': 'd.clearance_distance_m',
            'overtake': 'd.overtake',
            'overtake_after': 'd.overtake_after',
            'overtake_by': 'd.overtake_by',
            'filename': 'v.filename',
            'collection_year': 'v.collection_year',
            'road_type': 'v.road_type',
        }
        
        # Build ORDER BY clause
        order_by = "d.auto_id DESC"  # Default
        if sort_by and sort_by in sortable_columns:
            sort_col = sortable_columns[sort_by]
            direction = 'DESC' if sort_order.lower() == 'desc' else 'ASC'
            order_by = f"{sort_col} {direction}"
        
        # Get paginated data with proper column mapping
        sql = f"""
        SELECT 
            d.auto_id as detection_id,
            d.run_id,
            d.frame_num,
            d.model_name,
            cm.class_name,
            d.confidence,
            d.track_id,
            d.speed_km_h as absolute_speed_kmph,
            d.front_distance_m as distance_m,
            d.ttc_s,
            d.line_distance_m,
            d.acceleration_m_s2,
            d.acceleration_state,
            d.group_id,
            d.approach_partner_group_id,
            d.approach_distance_m,
            d.clearance_distance_m,
            d.travel_direction,
            d.l_line_distance_m,
            d.r_line_distance_m,
            d.overtake,
            d.overtake_after,
            d.overtake_by,
            d.x1 as x_min,
            d.y1 as y_min,
            d.x2 as x_max,
            d.y2 as y_max,
            v.filename,
            v.collection_year,
            v.road_type
        FROM Detection d
        LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
        LEFT JOIN ProcessLog p ON d.run_id = p.run_id
        LEFT JOIN Video v ON p.video_id = v.video_id
        {where_clause}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
        """
        rows = c.execute(sql, params + [per_page, offset]).fetchall()
        return [dict(r) for r in rows], total

def list_locations():
    """List registered locations."""
    return []

def register_location(name, address):
    pass





def get_detection_preview_info(detection_id: int):
    """プレビュー表示用にDetectionの詳細情報（BBOXと動画パス）を取得する"""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # 1. 対象のDetectionとVideo情報を取得
        sql = """
            SELECT 
                d.run_id, d.frame_num, d.group_id, d.class_id,
                d.x1, d.y1, d.x2, d.y2,
                d.overtake_by, d.overtake,
                v.filename, v.source_path,
                pl.output_folder, pl.folder_alias,
                cm.class_name
            FROM Detection d
            JOIN ProcessLog pl ON d.run_id = pl.run_id
            JOIN Video v ON pl.video_id = v.video_id
            LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
            WHERE d.auto_id = ?
        """
        row = c.execute(sql, (detection_id,)).fetchone()
        if not row:
            return None
        
        info = dict(row)
        
        # 2. パートナー車両（相手）のBBOXを取得
        partner_sql = None
        partner_binding = None

        # Case A: 自分が追い越された（overtake_by がセットされている）
        if info['overtake_by']:
            partner_sql = """
                SELECT x1, y1, x2, y2, cm.class_name
                FROM Detection d
                LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
                WHERE auto_id = ?
            """
            partner_binding = (info['overtake_by'],)
        


        if partner_sql:
            partner = c.execute(partner_sql, partner_binding).fetchone()
            if partner:
                info['partner_bbox'] = {
                    'x1': partner['x1'],
                    'y1': partner['y1'],
                    'x2': partner['x2'],
                    'y2': partner['y2'],
                    'class_name': partner['class_name']
                }
        
        return info

def insert_manual_overtake_event(event_data):
    """手動追い越しイベントを新規作成する"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            
            run_id = event_data.get("run_id")
            frame_num = event_data.get("frame_num")
            
            if not run_id or frame_num is None:
                 raise ValueError("run_id and frame_num are required")
                 
            context_frames = event_data.get("context_frames")
            if isinstance(context_frames, list):
                import json
                context_frames_json = json.dumps(context_frames)
            else:
                context_frames_json = None
                
            keys = [
                "run_id", "frame_num", "video_time_s",
                "overtaker_group_id", "overtaker_track_id", "overtaker_class_name",
                "overtaker_speed_km_h", "overtaker_pixel_speed", "overtaker_pixel_speed_frame",
                "overtaken_group_id", "overtaken_track_id", "overtaken_class_name",
                "overtaken_speed_km_h", "overtaken_pixel_speed", "overtaken_pixel_speed_frame",
                "approach_distance_m", "approach_distance_px",
                "clearance_distance_m", "clearance_distance_cm", "clearance_distance_px", "clearance_distance_px_ratio",
                "overtaker_line_distance_m", "overtaker_line_distance_cm", "overtaker_line_distance_px", "overtaker_line_distance_px_ratio",
                "overtaken_line_distance_m", "overtaken_line_distance_cm", "overtaken_line_distance_px", "overtaken_line_distance_px_ratio",
                "overtaker_left_line_distance_m", "overtaker_left_line_distance_cm", "overtaker_left_line_distance_px",
                "overtaker_right_line_distance_m", "overtaker_right_line_distance_cm", "overtaker_right_line_distance_px",
                "overtaken_left_line_distance_m", "overtaken_left_line_distance_cm", "overtaken_left_line_distance_px",
                "overtaken_right_line_distance_m", "overtaken_right_line_distance_cm", "overtaken_right_line_distance_px",
                "overtaker_measure_x", "overtaker_measure_y",
                "overtaken_measure_x", "overtaken_measure_y",
                "overtaker_x1", "overtaker_y1", "overtaker_x2", "overtaker_y2",
                "overtaken_x1", "overtaken_y1", "overtaken_x2", "overtaken_y2",
                "lane_width_m", "lane_width_px_reference", "lane_width_cm_per_px",
                "notes"
            ]
            
            columns = ", ".join(keys + ["context_frames", "created_at", "updated_at"])
            placeholders = ", ".join(["?"] * (len(keys) + 3))
            
            values = [event_data.get(k) for k in keys]
            
            now = datetime.now().isoformat()
            values.append(context_frames_json)
            values.append(now)
            values.append(now)
            
            sql = f"INSERT INTO ManualOvertakeEvents ({columns}) VALUES ({placeholders})"
            
            c.execute(sql, values)
            event_id = c.lastrowid
            conn.commit()
            return event_id
    except Exception as e:
        print(f"Error inserting manual event: {e}")
        raise

def update_manual_overtake_event(event_id, event_data):
    """既存の手動追い越しイベントを更新する"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            
            keys = [
                "overtaker_speed_km_h", "overtaker_pixel_speed", "overtaker_pixel_speed_frame",
                "overtaken_speed_km_h", "overtaken_pixel_speed", "overtaken_pixel_speed_frame",
                "approach_distance_m", "approach_distance_px",
                "clearance_distance_m", "clearance_distance_cm", "clearance_distance_px", "clearance_distance_px_ratio",
                "overtaker_line_distance_m", "overtaker_line_distance_cm", "overtaker_line_distance_px", "overtaker_line_distance_px_ratio",
                "overtaken_line_distance_m", "overtaken_line_distance_cm", "overtaken_line_distance_px", "overtaken_line_distance_px_ratio",
                "overtaker_left_line_distance_m", "overtaker_left_line_distance_cm", "overtaker_left_line_distance_px",
                "overtaker_right_line_distance_m", "overtaker_right_line_distance_cm", "overtaker_right_line_distance_px",
                "overtaken_left_line_distance_m", "overtaken_left_line_distance_cm", "overtaken_left_line_distance_px",
                "overtaken_right_line_distance_m", "overtaken_right_line_distance_cm", "overtaken_right_line_distance_px",
                "overtaker_measure_x", "overtaker_measure_y",
                "overtaken_measure_x", "overtaken_measure_y",
                "lane_width_m", "lane_width_px_reference", "lane_width_cm_per_px",
                "notes"
            ]
            
            updates = []
            values = []
            
            for k in keys:
                if k in event_data:
                    updates.append(f"{k} = ?")
                    values.append(event_data[k])
            
            context_frames = event_data.get("context_frames")
            if context_frames is not None:
                 import json
                 if isinstance(context_frames, list):
                     updates.append("context_frames = ?")
                     values.append(json.dumps(context_frames))
            
            if not updates:
                return False
                
            updates.append("updated_at = ?")
            values.append(datetime.now().isoformat())
            
            values.append(event_id)
            
            sql = f"UPDATE ManualOvertakeEvents SET {', '.join(updates)} WHERE manual_event_id = ?"
            c.execute(sql, values)
            conn.commit()
            return True
    except Exception as e:
        print(f"Error updating manual event: {e}")
        raise

def delete_manual_overtake_event(event_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM ManualOvertakeEvents WHERE manual_event_id = ?", (event_id,))
        conn.commit()
        return True

def replace_manual_overtake_context_frames(manual_event_id, frames):
    import json
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            json_str = json.dumps(frames)
            c.execute("UPDATE ManualOvertakeEvents SET context_frames = ? WHERE manual_event_id = ?", (json_str, manual_event_id))
            conn.commit()
            return True
    except Exception as e:
        print(f"Error replacing context frames: {e}")
        return False

def touch_manual_run_progress(run_id, annotation=False, visit=False, review=False):
    """Run進捗ステータスを更新する
    
    Args:
        run_id: 対象のRun ID
        annotation: 付与済みとしてマーク
        visit: 観覧済みとしてマーク
        review: レビュー済みとしてマーク (visitと同等に扱う)
    """
    # Forced reload trigger
    import datetime
    now = datetime.datetime.now().isoformat()
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO ManualRunProgress (run_id) VALUES (?)", (run_id,))
        if annotation:
            c.execute("UPDATE ManualRunProgress SET manual_status = 'annotated', last_annotation_at = ? WHERE run_id = ?", (now, run_id))
        elif visit or review:
            c.execute("UPDATE ManualRunProgress SET manual_status = CASE WHEN manual_status = 'annotated' THEN 'annotated' ELSE 'visited' END, last_visit_at = ? WHERE run_id = ?", (now, run_id))
        else:
            c.execute("UPDATE ManualRunProgress SET manual_status = CASE WHEN manual_status = 'annotated' THEN 'annotated' ELSE 'visited' END, last_visit_at = ? WHERE run_id = ?", (now, run_id))
        conn.commit()

def record_manual_overtake_timeline_entry(
    run_id,
    frame_num,
    overtaker_gid,
    overtaken_gid,
    notes=None,
    last_event_id=None,
):
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        c = conn.cursor()
        try:
            ensure_manual_annotation_schema(conn)
        except Exception:
            pass
        columns = _table_columns(conn, "ManualOvertakeTimeline")
        match_sql = (
            "SELECT timeline_id FROM ManualOvertakeTimeline "
            "WHERE run_id = ? AND frame_num = ? AND overtaker_group_id = ? AND overtaken_group_id = ?"
        )
        row = c.execute(
            match_sql,
            (run_id, frame_num, overtaker_gid, overtaken_gid),
        ).fetchone()
        if row:
            updates = ["notes = ?"]
            params = [notes]
            if "updated_at" in columns:
                updates.append("updated_at = ?")
                params.append(now)
            if last_event_id is not None:
                if "last_event_id" in columns:
                    updates.append("last_event_id = ?")
                    params.append(last_event_id)
                if "manual_event_id" in columns:
                    updates.append("manual_event_id = COALESCE(manual_event_id, ?)")
                    params.append(last_event_id)
                if "last_processed_at" in columns:
                    updates.append("last_processed_at = ?")
                    params.append(now)
            timeline_id = row[0] if not isinstance(row, sqlite3.Row) else row["timeline_id"]
            sql = f"UPDATE ManualOvertakeTimeline SET {', '.join(updates)} WHERE timeline_id = ?"
            params.append(timeline_id)
            c.execute(sql, params)
        else:
            insert_cols = [
                "run_id",
                "frame_num",
                "overtaker_group_id",
                "overtaken_group_id",
                "notes",
            ]
            insert_vals = [
                run_id,
                frame_num,
                overtaker_gid,
                overtaken_gid,
                notes,
            ]
            if "created_at" in columns:
                insert_cols.append("created_at")
                insert_vals.append(now)
            if "updated_at" in columns:
                insert_cols.append("updated_at")
                insert_vals.append(now)
            if "last_event_id" in columns:
                insert_cols.append("last_event_id")
                insert_vals.append(last_event_id)
            if "manual_event_id" in columns:
                insert_cols.append("manual_event_id")
                insert_vals.append(last_event_id)
            if "last_processed_at" in columns and last_event_id is not None:
                insert_cols.append("last_processed_at")
                insert_vals.append(now)
            placeholders = ", ".join(["?"] * len(insert_cols))
            c.execute(
                f"INSERT INTO ManualOvertakeTimeline ({', '.join(insert_cols)}) VALUES ({placeholders})",
                insert_vals,
            )
        conn.commit()

def list_manual_overtake_timeline_entries(run_ids=None):
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if run_ids is None:
            rows = c.execute(
                "SELECT * FROM ManualOvertakeTimeline ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

        if not isinstance(run_ids, (list, tuple, set)):
            run_ids = [run_ids]
        normalized = []
        for value in run_ids:
            try:
                normalized.append(int(value))
            except (TypeError, ValueError):
                continue
        if not normalized:
            return []
        placeholders = ",".join(["?"] * len(normalized))
        rows = c.execute(
            f"SELECT * FROM ManualOvertakeTimeline WHERE run_id IN ({placeholders}) ORDER BY created_at DESC",
            normalized,
        ).fetchall()
        return [dict(r) for r in rows]

def mark_manual_overtake_timeline_processed(timeline_id, last_event_id=None):
    if timeline_id is None:
        return 0
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        c = conn.cursor()
        columns = _table_columns(conn, "ManualOvertakeTimeline")
        updates = []
        params = []
        if "updated_at" in columns:
            updates.append("updated_at = ?")
            params.append(now)
        if "last_processed_at" in columns:
            updates.append("last_processed_at = ?")
            params.append(now)
        if last_event_id is not None:
            if "last_event_id" in columns:
                updates.append("last_event_id = ?")
                params.append(last_event_id)
            if "manual_event_id" in columns:
                updates.append("manual_event_id = COALESCE(manual_event_id, ?)")
                params.append(last_event_id)
        if not updates:
            return 0
        params.append(timeline_id)
        c.execute(
            f"UPDATE ManualOvertakeTimeline SET {', '.join(updates)} WHERE timeline_id = ?",
            params,
        )
        conn.commit()
        return c.rowcount

def mark_manual_overtake_timeline_event_deleted(manual_event_id):
    if manual_event_id is None:
        return 0
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        c = conn.cursor()
        columns = _table_columns(conn, "ManualOvertakeTimeline")
        updates = []
        params = []
        if "updated_at" in columns:
            updates.append("updated_at = ?")
            params.append(now)
        if "last_processed_at" in columns:
            updates.append("last_processed_at = NULL")
        if "last_event_id" in columns:
            updates.append("last_event_id = NULL")
        if "manual_event_id" in columns:
            updates.append("manual_event_id = NULL")
        if "is_deleted" in columns:
            updates.append("is_deleted = 1")
        if not updates:
            return 0
        where_clauses = []
        if "last_event_id" in columns:
            where_clauses.append("last_event_id = ?")
            params.append(manual_event_id)
        if "manual_event_id" in columns:
            where_clauses.append("manual_event_id = ?")
            params.append(manual_event_id)
        if not where_clauses:
            return 0
        sql = f"UPDATE ManualOvertakeTimeline SET {', '.join(updates)} WHERE {' OR '.join(where_clauses)}"
        c.execute(sql, params)
        conn.commit()
        return c.rowcount


def _model_filter_attempts() -> list[str]:
    """
    (Internal) Returns a list of SQL WHERE clauses to try for filtering detections.
    Used by manual_logic to heuristically find valid detection counts.
    """
    # Currently just return empty string to select all (or assume single model per run)
    return [""]

def list_manual_overtake_events(run_id=None, run_ids=None, limit=500):
    """Manual overtake events retrieval with optional filtering."""
    with get_db_connection() as conn:
        c = conn.cursor()
        
        where_clauses = []
        params = []
        
        # Support both run_id (single) and run_ids (list)
        if run_ids is not None and len(run_ids) > 0:
            placeholders = ",".join(["?"] * len(run_ids))
            where_clauses.append(f"run_id IN ({placeholders})")
            params.extend(run_ids)
        elif run_id is not None:
            where_clauses.append("run_id = ?")
            params.append(run_id)
        
        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        limit_clause = ""
        if limit is not None:
            try:
                limit_value = int(limit)
            except (TypeError, ValueError):
                limit_value = None
            else:
                if limit_value <= 0:
                    limit_value = None
            if limit_value is not None:
                limit_clause = "LIMIT ?"
                params.append(limit_value)

        sql = f"""
        SELECT *
        FROM ManualOvertakeEvents
        {where_sql}
        ORDER BY manual_event_id DESC
        {limit_clause}
        """
        
        try:
            rows = c.execute(sql, params).fetchall()
            events = [dict(row) for row in rows]

            # Deserialize context_frames
            import json
            for event in events:
                if event.get('context_frames'):
                    try:
                        event['context_frames'] = json.loads(event['context_frames'])
                    except:
                        event['context_frames'] = []
                else:
                    event['context_frames'] = []
            
            # Helper to get filenames and metadata efficiently? 
            # Doing it per-row is slow but matches previous implementation
            for event in events:
                if event.get('run_id'):
                    video_query = """
                    SELECT v.filename, v.road_type, v.collection_year
                    FROM ProcessLog p
                    JOIN Video v ON p.video_id = v.video_id
                    WHERE p.run_id = ?
                    """
                    video_row = c.execute(video_query, (event['run_id'],)).fetchone()
                    if video_row:
                        event['video_filename'] = video_row[0]
                        event['road_type'] = video_row[1]
                        event['collection_year'] = video_row[2]
                    else:
                        event['video_filename'] = None
                        event['road_type'] = None
                        event['collection_year'] = None
                else:
                    event['video_filename'] = None
                    event['road_type'] = None
                    event['collection_year'] = None
            
            return events
        except sqlite3.Error as e:
            print(f"Warning: Could not query ManualOvertakeEvents: {e}")
            return []

def fetch_manual_overtake_event(event_id, **kwargs):
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        row = c.execute("SELECT * FROM ManualOvertakeEvents WHERE manual_event_id = ?", (event_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        if data.get('context_frames'):
            import json
            try:
                data['context_frames'] = json.loads(data['context_frames'])
            except:
                data['context_frames'] = []
        return data

        return data

# Alias for backwards compatibility with routes
fetch_manual_overtake_event_core = fetch_manual_overtake_event

# --- Manual Overtake Helpers ---

def count_manual_overtake_events(run_id=None, run_ids=None):
    if run_ids is None and isinstance(run_id, (list, tuple, set)):
        run_ids = list(run_id)
        run_id = None
    with get_db_connection() as conn:
        c = conn.cursor()
        if run_ids:
            placeholders = ",".join(["?"] * len(run_ids))
            row = c.execute(
                f"SELECT COUNT(*) FROM ManualOvertakeEvents WHERE run_id IN ({placeholders})",
                list(run_ids),
            ).fetchone()
        elif run_id is not None:
            row = c.execute(
                "SELECT COUNT(*) FROM ManualOvertakeEvents WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        else:
            row = c.execute("SELECT COUNT(*) FROM ManualOvertakeEvents").fetchone()
        return row[0] if row else 0

def update_manual_lane_width(
    target_ids,
    lane_width_m,
    lane_width_px_reference=None,
    lane_width_cm_per_px=None,
):
    if target_ids is None:
        return 0

    updates = ["lane_width_m = ?"]
    params = [lane_width_m]
    if lane_width_px_reference is not None:
        updates.append("lane_width_px_reference = ?")
        params.append(lane_width_px_reference)
    if lane_width_cm_per_px is not None:
        updates.append("lane_width_cm_per_px = ?")
        params.append(lane_width_cm_per_px)
    updates.append("updated_at = ?")
    params.append(datetime.now().isoformat())

    with get_db_connection() as conn:
        c = conn.cursor()
        if isinstance(target_ids, (list, tuple, set)):
            run_ids = []
            for value in target_ids:
                try:
                    run_ids.append(int(value))
                except (TypeError, ValueError):
                    continue
            if not run_ids:
                return 0
            placeholders = ",".join(["?"] * len(run_ids))
            sql = f"UPDATE ManualOvertakeEvents SET {', '.join(updates)} WHERE run_id IN ({placeholders})"
            c.execute(sql, params + run_ids)
            conn.commit()
            return c.rowcount

        try:
            target_int = int(target_ids)
        except (TypeError, ValueError):
            return 0

        row = c.execute(
            "SELECT 1 FROM ManualOvertakeEvents WHERE manual_event_id = ? LIMIT 1",
            (target_int,),
        ).fetchone()
        if row:
            sql = f"UPDATE ManualOvertakeEvents SET {', '.join(updates)} WHERE manual_event_id = ?"
            c.execute(sql, params + [target_int])
            conn.commit()
            return c.rowcount

        sql = f"UPDATE ManualOvertakeEvents SET {', '.join(updates)} WHERE run_id = ?"
        c.execute(sql, params + [target_int])
        conn.commit()
        return c.rowcount

def update_manual_overtake_event(manual_event_id, data):
    """手動追い越しイベントデータを更新する。"""
    if not data:
        return False
        
    allowed_columns = {
        "lane_width_m", "lane_width_px_reference", "lane_width_cm_per_px",
        "overtaker_measure_x", "overtaker_measure_y",
        "overtaken_measure_x", "overtaken_measure_y",
        "overtaker_line_distance_m", "overtaker_line_distance_cm", "overtaker_line_distance_px",
        "overtaker_left_line_distance_m", "overtaker_left_line_distance_cm", "overtaker_left_line_distance_px",
        "overtaker_right_line_distance_m", "overtaker_right_line_distance_cm", "overtaker_right_line_distance_px",
        "overtaken_line_distance_m", "overtaken_line_distance_cm", "overtaken_line_distance_px",
        "overtaken_left_line_distance_m", "overtaken_left_line_distance_cm", "overtaken_left_line_distance_px",
        "overtaken_right_line_distance_m", "overtaken_right_line_distance_cm", "overtaken_right_line_distance_px",
        "clearance_distance_m", "clearance_distance_cm", "clearance_distance_px",
        "approach_distance_m", "approach_distance_px",
        "overtaker_travel_direction", "overtaken_travel_direction",
        "notes"
    }

    updates = []
    params = []
    
    for key, value in data.items():
        if key in allowed_columns:
            updates.append(f"{key} = ?")
            params.append(value)
            
    if not updates:
        return False
        
    updates.append("updated_at = ?")
    params.append(datetime.now().isoformat())
    params.append(manual_event_id)
    
    with get_db_connection() as conn:
        c = conn.cursor()
        sql = f"UPDATE ManualOvertakeEvents SET {', '.join(updates)} WHERE manual_event_id = ?"
        try:
            c.execute(sql, params)
            conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Error updating manual overtake event: {e}")
            return False


def apply_manual_overtake_flags(run_id, frame_num, overtaker_gid, overtaken_gid):
    with get_db_connection() as conn:
        c = conn.cursor()
        try:
            # 追い越し側
            c.execute("UPDATE Detection SET overtake = 1 WHERE run_id = ? AND frame_num = ? AND group_id = ?", (run_id, frame_num, overtaker_gid))
            # 追い越され側
            c.execute("UPDATE Detection SET overtake_by = ? WHERE run_id = ? AND frame_num = ? AND group_id = ?", (overtaker_gid, run_id, frame_num, overtaken_gid))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error applying manual flags: {e}")
            return False

def reset_manual_overtake_for_runs(run_ids):
    if not run_ids: return
    placeholders = ','.join(['?'] * len(run_ids))
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            if _table_exists(conn, "ManualOvertakeContext"):
                c.execute(
                    f"DELETE FROM ManualOvertakeContext WHERE manual_event_id IN (SELECT manual_event_id FROM ManualOvertakeEvents WHERE run_id IN ({placeholders}))",
                    run_ids,
                )
            c.execute(f"DELETE FROM ManualOvertakeEvents WHERE run_id IN ({placeholders})", run_ids)
            c.execute(f"DELETE FROM ManualOvertakeTimeline WHERE run_id IN ({placeholders})", run_ids)
            if _table_exists(conn, "ManualOvertakeContextBacklog"):
                c.execute(
                    f"DELETE FROM ManualOvertakeContextBacklog WHERE run_id IN ({placeholders})",
                    run_ids,
                )
            if _table_exists(conn, "ManualContextBacklog"):
                c.execute(
                    f"DELETE FROM ManualContextBacklog WHERE run_id IN ({placeholders})",
                    run_ids,
                )
            c.execute(f"DELETE FROM ManualRunProgress WHERE run_id IN ({placeholders})", run_ids)
            conn.commit()
    except Exception as e:
        print(f"Error resetting manual overtake: {e}")

def list_manual_context_backlog(run_ids=None, limit=10):
    def _normalize_runs(values):
        if values is None:
            return []
        if not isinstance(values, (list, tuple, set)):
            values = [values]
        normalized = []
        for value in values:
            try:
                normalized.append(int(value))
            except (TypeError, ValueError):
                continue
        return normalized

    def _load_json(raw_value):
        if not raw_value:
            return None
        try:
            import json
            return json.loads(raw_value)
        except Exception:
            return None

    run_ids_norm = _normalize_runs(run_ids)
    entries = []

    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        def _fetch_event_core(event_id):
            if event_id is None:
                return None
            row = c.execute(
                "SELECT manual_event_id, run_id, frame_num, overtaker_group_id, overtaken_group_id, notes "
                "FROM ManualOvertakeEvents WHERE manual_event_id = ?",
                (event_id,),
            ).fetchone()
            return dict(row) if row else None

        def _merge_payload(entry, payload):
            if not payload:
                return
            for key in ("overtaker_group_id", "overtaken_group_id", "notes"):
                if entry.get(key) in (None, "") and payload.get(key) is not None:
                    entry[key] = payload.get(key)

        def _merge_core(entry, core):
            if not core:
                return
            for key in ("run_id", "frame_num", "overtaker_group_id", "overtaken_group_id", "notes"):
                if entry.get(key) in (None, "") and core.get(key) is not None:
                    entry[key] = core.get(key)

        if _table_exists(conn, "ManualOvertakeContextBacklog"):
            sql = (
                "SELECT backlog_id, manual_event_id, run_id, frame_num, "
                "event_payload_json, context_frames_json, created_at, processed_at, status, error_message "
                "FROM ManualOvertakeContextBacklog WHERE status = 'pending'"
            )
            params = []
            if run_ids_norm:
                placeholders = ",".join(["?"] * len(run_ids_norm))
                sql += f" AND run_id IN ({placeholders})"
                params.extend(run_ids_norm)
            sql += " ORDER BY created_at ASC"
            rows = c.execute(sql, params).fetchall()
            for row in rows:
                entry = dict(row)
                event_payload = _load_json(entry.get("event_payload_json")) or {}
                context_frames = _load_json(entry.get("context_frames_json")) or []
                entry["event_payload"] = event_payload
                entry["context_frames"] = context_frames
                entry["backlog_table"] = "ManualOvertakeContextBacklog"
                entry["source_table"] = entry["backlog_table"]
                _merge_payload(entry, event_payload)
                _merge_core(entry, _fetch_event_core(entry.get("manual_event_id")))
                entries.append(entry)

        if _table_exists(conn, "ManualContextBacklog"):
            sql = (
                "SELECT backlog_id, manual_event_id, run_id, frame_num, payload_json, "
                "created_at, updated_at, status, error_message "
                "FROM ManualContextBacklog WHERE status = 'pending'"
            )
            params = []
            if run_ids_norm:
                placeholders = ",".join(["?"] * len(run_ids_norm))
                sql += f" AND run_id IN ({placeholders})"
                params.extend(run_ids_norm)
            sql += " ORDER BY created_at ASC"
            rows = c.execute(sql, params).fetchall()
            for row in rows:
                entry = dict(row)
                event_payload = _load_json(entry.get("payload_json")) or {}
                entry["event_payload"] = event_payload
                entry["context_frames"] = []
                entry["backlog_table"] = "ManualContextBacklog"
                entry["source_table"] = entry["backlog_table"]
                _merge_payload(entry, event_payload)

                manual_event_id = entry.get("manual_event_id")
                core = _fetch_event_core(manual_event_id)
                if core is None:
                    alt_id = entry.get("run_id")
                    core = _fetch_event_core(alt_id)
                    if core is not None:
                        entry["manual_event_id"] = alt_id
                _merge_core(entry, core)
                entries.append(entry)

    entries.sort(key=lambda item: item.get("created_at") or "")
    if limit is not None:
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            limit_value = None
        if limit_value and limit_value > 0:
            entries = entries[:limit_value]
    return entries

def mark_manual_context_backlog_processed(
    backlog_id,
    success=None,
    status=None,
    error_message=None,
    backlog_table=None,
):
    if backlog_id is None:
        return 0
    if status is None:
        if success is True:
            status = "completed"
        elif success is False:
            status = "error"
        else:
            status = "completed"
    now = datetime.now().isoformat()
    rows_updated = 0
    with get_db_connection() as conn:
        c = conn.cursor()
        target_tables = []
        if backlog_table in ("ManualOvertakeContextBacklog", "ManualContextBacklog"):
            target_tables.append(backlog_table)
        else:
            if _table_exists(conn, "ManualOvertakeContextBacklog"):
                target_tables.append("ManualOvertakeContextBacklog")
            if _table_exists(conn, "ManualContextBacklog"):
                target_tables.append("ManualContextBacklog")

        for table_name in target_tables:
            if table_name == "ManualOvertakeContextBacklog":
                c.execute(
                    """
                    UPDATE ManualOvertakeContextBacklog
                    SET status = ?, processed_at = ?, error_message = ?
                    WHERE backlog_id = ?
                    """,
                    (status, now, error_message, backlog_id),
                )
                rows_updated += c.rowcount
            elif table_name == "ManualContextBacklog":
                c.execute(
                    """
                    UPDATE ManualContextBacklog
                    SET status = ?, updated_at = ?, error_message = ?
                    WHERE backlog_id = ?
                    """,
                    (status, now, error_message, backlog_id),
                )
                rows_updated += c.rowcount
        conn.commit()
    return rows_updated

def count_manual_context_backlog(run_ids=None):
    run_ids_norm = []
    if run_ids:
        if not isinstance(run_ids, (list, tuple, set)):
            run_ids = [run_ids]
        for value in run_ids:
            try:
                run_ids_norm.append(int(value))
            except (TypeError, ValueError):
                continue

    summary = {}
    with get_db_connection() as conn:
        c = conn.cursor()
        if _table_exists(conn, "ManualOvertakeContextBacklog"):
            sql = "SELECT run_id, COUNT(*) FROM ManualOvertakeContextBacklog WHERE status = 'pending'"
            params = []
            if run_ids_norm:
                placeholders = ",".join(["?"] * len(run_ids_norm))
                sql += f" AND run_id IN ({placeholders})"
                params.extend(run_ids_norm)
            sql += " GROUP BY run_id"
            for run_id, count in c.execute(sql, params).fetchall():
                summary[int(run_id)] = summary.get(int(run_id), 0) + int(count or 0)

        if _table_exists(conn, "ManualContextBacklog"):
            sql = (
                "SELECT e.run_id, COUNT(*) "
                "FROM ManualContextBacklog b "
                "JOIN ManualOvertakeEvents e ON e.manual_event_id = b.manual_event_id "
                "WHERE b.status = 'pending'"
            )
            params = []
            if run_ids_norm:
                placeholders = ",".join(["?"] * len(run_ids_norm))
                sql += f" AND e.run_id IN ({placeholders})"
                params.extend(run_ids_norm)
            sql += " GROUP BY e.run_id"
            for run_id, count in c.execute(sql, params).fetchall():
                summary[int(run_id)] = summary.get(int(run_id), 0) + int(count or 0)

    return summary

def ensure_manual_context_backlog_for_runs(run_ids, force_requeue=False):
    if not run_ids:
        return 0, []

    normalized = []
    for value in run_ids:
        try:
            normalized.append(int(value))
        except (TypeError, ValueError):
            continue
    if not normalized:
        return 0, []

    enqueued = 0
    enqueued_ids = []
    now = datetime.now().isoformat()

    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        try:
            ensure_manual_annotation_schema(conn)
        except Exception:
            pass

        has_new = _table_exists(conn, "ManualOvertakeContextBacklog")
        has_old = _table_exists(conn, "ManualContextBacklog")
        if not has_new and not has_old:
            return 0, []

        existing = set()
        placeholders = ",".join(["?"] * len(normalized))

        if has_new:
            rows = c.execute(
                f"SELECT manual_event_id FROM ManualOvertakeContextBacklog WHERE run_id IN ({placeholders})",
                normalized,
            ).fetchall()
            for row in rows:
                existing.add(row[0] if not isinstance(row, sqlite3.Row) else row["manual_event_id"])
            if force_requeue and rows:
                c.execute(
                    f"UPDATE ManualOvertakeContextBacklog SET status = 'pending', processed_at = NULL, error_message = NULL WHERE run_id IN ({placeholders})",
                    normalized,
                )
                enqueued += c.rowcount

        if has_old:
            rows = c.execute(
                f"SELECT manual_event_id FROM ManualContextBacklog WHERE run_id IN ({placeholders})",
                normalized,
            ).fetchall()
            for row in rows:
                existing.add(row[0] if not isinstance(row, sqlite3.Row) else row["manual_event_id"])
            if force_requeue and rows:
                c.execute(
                    f"UPDATE ManualContextBacklog SET status = 'pending', updated_at = ?, error_message = NULL WHERE run_id IN ({placeholders})",
                    [now] + normalized,
                )
                enqueued += c.rowcount

        target_table = "ManualOvertakeContextBacklog" if has_new else "ManualContextBacklog"

        events = c.execute(
            f"SELECT * FROM ManualOvertakeEvents WHERE run_id IN ({placeholders})",
            normalized,
        ).fetchall()

        import json
        for event in events:
            event_id = event["manual_event_id"] if isinstance(event, sqlite3.Row) else event[0]
            if not force_requeue and event_id in existing:
                continue
            event_payload = dict(event)
            payload_json = json.dumps(event_payload, ensure_ascii=False)
            context_frames_json = event_payload.get("context_frames")
            if isinstance(context_frames_json, list):
                context_frames_json = json.dumps(context_frames_json, ensure_ascii=False)

            if target_table == "ManualOvertakeContextBacklog":
                c.execute(
                    """
                    INSERT INTO ManualOvertakeContextBacklog (
                        manual_event_id,
                        run_id,
                        frame_num,
                        event_payload_json,
                        context_frames_json,
                        created_at,
                        status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        event_id,
                        event_payload.get("run_id"),
                        event_payload.get("frame_num"),
                        payload_json,
                        context_frames_json,
                        now,
                    ),
                )
            else:
                c.execute(
                    """
                    INSERT INTO ManualContextBacklog (
                        run_id,
                        frame_num,
                        manual_event_id,
                        status,
                        created_at,
                        payload_json
                    )
                    VALUES (?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        event_payload.get("run_id"),
                        event_payload.get("frame_num"),
                        event_id,
                        now,
                        payload_json,
                    ),
                )
            enqueued += 1
            enqueued_ids.append(event_id)
        conn.commit()

    return enqueued, enqueued_ids

def summarize_manual_overtake_events(run_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM ManualOvertakeEvents WHERE run_id = ?", (run_id,))
        row = c.fetchone()
        return {"count": row[0] if row else 0}

def enqueue_manual_context_backlog(
    manual_event_id,
    run_id=None,
    frame_num=None,
    event_payload=None,
    context_frames=None,
):
    import json
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        try:
            ensure_manual_annotation_schema(conn)
        except Exception:
            pass

        if manual_event_id is None:
            return 0

        if run_id is not None and frame_num is not None:
            check = c.execute(
                "SELECT run_id, frame_num FROM ManualOvertakeEvents WHERE manual_event_id = ?",
                (manual_event_id,),
            ).fetchone()
            if check is None:
                alt_row = c.execute(
                    "SELECT run_id, frame_num FROM ManualOvertakeEvents WHERE manual_event_id = ?",
                    (run_id,),
                ).fetchone()
                if alt_row is not None:
                    manual_event_id = run_id
                    run_id = (
                        alt_row["run_id"] if isinstance(alt_row, sqlite3.Row) else alt_row[0]
                    )
                    frame_num = (
                        alt_row["frame_num"] if isinstance(alt_row, sqlite3.Row) else alt_row[1]
                    )

        if event_payload is None and manual_event_id is not None:
            row = c.execute(
                "SELECT * FROM ManualOvertakeEvents WHERE manual_event_id = ?",
                (manual_event_id,),
            ).fetchone()
            if row is not None:
                event_payload = dict(row)

        if event_payload:
            if run_id is None:
                run_id = event_payload.get("run_id")
            if frame_num is None:
                frame_num = event_payload.get("frame_num")

        payload_json = json.dumps(event_payload or {}, ensure_ascii=False)
        context_json = None
        if context_frames:
            context_json = json.dumps(context_frames, ensure_ascii=False)
        elif event_payload and isinstance(event_payload.get("context_frames"), list):
            context_json = json.dumps(event_payload.get("context_frames"), ensure_ascii=False)

        now = datetime.now().isoformat()

        if _table_exists(conn, "ManualOvertakeContextBacklog"):
            c.execute(
                """
                INSERT INTO ManualOvertakeContextBacklog (
                    manual_event_id,
                    run_id,
                    frame_num,
                    event_payload_json,
                    context_frames_json,
                    created_at,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (manual_event_id, run_id, frame_num, payload_json, context_json, now),
            )
            conn.commit()
            return c.lastrowid

        if _table_exists(conn, "ManualContextBacklog"):
            c.execute(
                """
                INSERT INTO ManualContextBacklog (
                    run_id,
                    frame_num,
                    manual_event_id,
                    status,
                    created_at,
                    payload_json
                )
                VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (run_id, frame_num, manual_event_id, now, payload_json),
            )
            conn.commit()
            return c.lastrowid

    return 0

def summarize_manual_context_backlog_by_status(run_ids=None):
    run_ids_norm = []
    if run_ids:
        if not isinstance(run_ids, (list, tuple, set)):
            run_ids = [run_ids]
        for value in run_ids:
            try:
                run_ids_norm.append(int(value))
            except (TypeError, ValueError):
                continue

    summary = {}
    with get_db_connection() as conn:
        c = conn.cursor()
        if _table_exists(conn, "ManualOvertakeContextBacklog"):
            sql = "SELECT status, COUNT(*) FROM ManualOvertakeContextBacklog"
            params = []
            if run_ids_norm:
                placeholders = ",".join(["?"] * len(run_ids_norm))
                sql += f" WHERE run_id IN ({placeholders})"
                params.extend(run_ids_norm)
            sql += " GROUP BY status"
            rows = c.execute(sql, params).fetchall()
            for status, count in rows:
                summary[status] = summary.get(status, 0) + int(count or 0)

        if _table_exists(conn, "ManualContextBacklog"):
            sql = "SELECT status, COUNT(*) FROM ManualContextBacklog"
            params = []
            if run_ids_norm:
                placeholders = ",".join(["?"] * len(run_ids_norm))
                sql += f" WHERE run_id IN ({placeholders})"
                params.extend(run_ids_norm)
            sql += " GROUP BY status"
            rows = c.execute(sql, params).fetchall()
            for status, count in rows:
                summary[status] = summary.get(status, 0) + int(count or 0)

    return summary

def list_manual_overtake_event_cores(run_ids):
    if run_ids is None:
        return []
    if not isinstance(run_ids, (list, tuple, set)):
        run_ids = [run_ids]
    normalized = []
    for value in run_ids:
        try:
            normalized.append(int(value))
        except (TypeError, ValueError):
            continue
    if not normalized:
        return []
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        placeholders = ",".join(["?"] * len(normalized))
        rows = c.execute(
            f"SELECT manual_event_id, frame_num, overtaker_group_id, overtaken_group_id, notes FROM ManualOvertakeEvents WHERE run_id IN ({placeholders})",
            normalized,
        ).fetchall()
        return [dict(r) for r in rows]
    
def get_all_process_logs():
    """ProcessLogとVideoを結合して全実行ログを取得する"""
    with get_db_connection() as conn:
        c = conn.cursor()
        sql = """
            SELECT 
                p.run_id,
                p.video_id,
                v.filename as video_filename,
                p.process_start,
                p.process_end,
                p.output_folder,
                p.folder_alias,
                p.status,
                p.error_message as message,
                p.calibration_profile,
                p.is_folder_batch,
                v.collection_year,
                v.road_type
            FROM ProcessLog p
            LEFT JOIN Video v ON p.video_id = v.video_id
            ORDER BY p.run_id DESC
        """
        rows = c.execute(sql).fetchall()
        
        # 集計: folder_alias ごとのRun数
        alias_counts = {}
        for r in rows:
            alias = r[6] # folder_alias
            if alias:
                alias_counts[alias] = alias_counts.get(alias, 0) + 1
        
        # Rowオブジェクトをdictに変換しつつ、サブフォルダ情報を追加
        results = []
        for r in rows:
             d = dict(r)
             
             # Count info based on alias
             alias = d.get('folder_alias')
             d['folder_run_count'] = alias_counts.get(alias, 0) if alias else 0
             
             # サブフォルダ表示用フィールドを抽出
             # folder_alias が "root/subfolder/section" の場合、各レベルで分割
             if alias:
                 parts = alias.replace("\\", "/").split("/")
                 if len(parts) >= 2:
                     # ルートフォルダ (例: new_x)
                     d['root_folder'] = parts[0]
                     # サブフォルダ (例: 1_250803)
                     d['subfolder'] = parts[1]
                     # 区間があれば (例: 区間A)
                     d['section'] = parts[2] if len(parts) >= 3 else None
                     # 表示用: サブフォルダ + 区間
                     d['subfolder_display'] = "/".join(parts[1:])
                 else:
                     d['root_folder'] = alias
                     d['subfolder'] = None
                     d['section'] = None
                     d['subfolder_display'] = None
             else:
                 d['root_folder'] = None
                 d['subfolder'] = None
                 d['section'] = None
                 d['subfolder_display'] = None
             
             results.append(d)
        return results

def list_folder_batches():
    """フォルダ単位（folder_alias）でProcessLogを集計して返す"""
    with get_db_connection() as conn:
        c = conn.cursor()
        # folder_alias ごとの集計
        # folder_alias が NULL または 空文字 の場合は "-" として扱うか、集計から除外するか。
        # ここでは folder_alias があるものを対象とする
        sql = """
            SELECT 
                folder_alias,
                COUNT(*) as run_count,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_runs,
                SUM(CASE WHEN calibration_profile IS NULL OR calibration_profile = '' THEN 1 ELSE 0 END) as missing_profiles
            FROM ProcessLog
            WHERE folder_alias IS NOT NULL AND folder_alias != ''
            GROUP BY folder_alias
            ORDER BY folder_alias
        """
        rows = c.execute(sql).fetchall()
        
        results = []
        for r in rows:
            d = dict(r)
            alias = d.get('folder_alias')
            if alias:
                 parts = alias.replace("\\", "/").split("/")
                 if len(parts) >= 2:
                     d['subfolder_display'] = "/".join(parts[1:])
                 else:
                     d['subfolder_display'] = alias
            else:
                 d['subfolder_display'] = "-"
            results.append(d)
        return results

def get_run_ids_by_folder(folder_alias):
    """指定されたフォルダエイリアスに属するRun IDのリストを返す"""
    if not folder_alias:
        return []
        
    with get_db_connection() as conn:
        c = conn.cursor()
        # Recursive match: Exact match OR starts with "alias/"
        sql = "SELECT run_id FROM ProcessLog WHERE folder_alias = ? OR folder_alias LIKE ? ORDER BY run_id"
        # Note: We assume '/' is the separator. 
        rows = c.execute(sql, (folder_alias, folder_alias + '/%')).fetchall()
        return [r[0] for r in rows]

# Removed duplicate definition


def get_all_run_ids():
    """ProcessLogに存在する全てのRun IDのリストを返す"""
    with get_db_connection() as conn:
        c = conn.cursor()
        sql = "SELECT run_id FROM ProcessLog ORDER BY run_id"
        rows = c.execute(sql).fetchall()
        return [r[0] for r in rows]




def get_run_ids_by_condition(road_type=None, process_year=None):
    """条件（道路タイプ、年度）に一致するRun IDのリストを返す"""
    with get_db_connection() as conn:
        c = conn.cursor()
        
        where = []
        params = []
        
        if road_type and road_type != 'all':
            where.append("v.road_type = ?")
            params.append(road_type)
            
        if process_year and process_year != 'all':
             try:
                 year_int = int(process_year)
                 where.append("v.collection_year = ?")
                 params.append(year_int)
             except (ValueError, TypeError):
                 pass
        
        where_clause = "WHERE " + " AND ".join(where) if where else ""
        
        sql = f"""
            SELECT p.run_id 
            FROM ProcessLog p
            JOIN Video v ON p.video_id = v.video_id
            {where_clause}
            ORDER BY p.run_id
        """
        rows = c.execute(sql, params).fetchall()
        return [r[0] for r in rows]


def update_run_metadata(run_id, collection_year=None, road_type=None):
    """Runのメタデータ（年度、道路タイプ）を更新する
    
    Args:
        run_id: 更新対象のRun ID
        collection_year: 収集年度（Noneの場合は更新しない）
        road_type: 道路タイプ（Noneの場合は更新しない）
    
    Returns:
        bool: 更新成功時はTrue、失敗時はFalse
    """
    if collection_year is None and road_type is None:
        return True  # 更新対象がない場合は成功扱い
    
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # まずrun_idからvideo_idを取得
            c.execute("SELECT video_id FROM ProcessLog WHERE run_id = ?", (run_id,))
            row = c.fetchone()
            if not row:
                return False  # Run IDが存在しない
            
            video_id = row[0]
            if video_id is None:
                return False  # video_idが設定されていない
            
            # Videoテーブルを更新
            updates = []
            params = []
            
            if collection_year is not None:
                updates.append("collection_year = ?")
                params.append(collection_year)
            
            if road_type is not None:
                updates.append("road_type = ?")
                params.append(road_type)
            
            if updates:
                params.append(video_id)
                sql = f"UPDATE Video SET {', '.join(updates)} WHERE video_id = ?"
                c.execute(sql, params)
                conn.commit()
            
            return True
    except Exception as e:
        print(f"Error updating run metadata: {e}")
        return False

def batch_update_run_metadata_direct(run_ids, collection_year=None, road_type=None):
    """複数のRunのメタデータ（年度、道路タイプ）を一括更新する
    
    Args:
        run_ids: 更新対象のRun IDのリスト
        collection_year: 収集年度（Noneの場合は更新しない）
        road_type: 道路タイプ（Noneの場合は更新しない）
    
    Returns:
        tuple: (updated_count, error_count)
    """
    if not run_ids:
        return 0, 0
    if collection_year is None and road_type is None:
        return 0, 0
    
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Run IDリストからVideo IDリストを取得
            # run_idsは数値リストと仮定
            placeholders = ','.join(['?'] * len(run_ids))
            c.execute(f"SELECT video_id FROM ProcessLog WHERE run_id IN ({placeholders})", run_ids)
            rows = c.fetchall()
            video_ids = [r[0] for r in rows if r[0] is not None]
            
            if not video_ids:
                return 0, 0
            
            # Videoテーブルを一括更新
            updates = []
            params = []
            
            if collection_year is not None:
                updates.append("collection_year = ?")
                params.append(collection_year)
            
            if road_type is not None:
                updates.append("road_type = ?")
                params.append(road_type)
            
            if updates:
                vid_placeholders = ','.join(['?'] * len(video_ids))
                params.extend(video_ids)
                
                sql = f"UPDATE Video SET {', '.join(updates)} WHERE video_id IN ({vid_placeholders})"
                c.execute(sql, params)
                conn.commit()
                return c.rowcount, 0
            
            return 0, 0
    except Exception as e:
        print(f"Error batch updating run metadata: {e}")
        return 0, 1

def reset_run_records():
    """全てのRunデータをリセットする（ProcessLogとDetectionを削除）"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            # 外部キー制約により、ProcessLogを削除するとDetectionも削除される
            # ただし、安全のため明示的に削除する
            c.execute("DELETE FROM Detection")
            c.execute("DELETE FROM ProcessLog")
            conn.commit()
            return True
    except Exception as e:
        print(f"Error resetting run records: {e}")
        return False


# --- Calibration Helper Functions ---
def get_calibration_profile_for_run(run_id: int) -> Optional[str]:
    """指定されたRun IDのキャリブレーションプロファイル名を取得する"""
    if not run_id:
        return None
    
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT calibration_profile FROM ProcessLog WHERE run_id = ?", (run_id,))
        row = c.fetchone()
        if row and row[0]:
            return row[0]
        return None

def get_calibration_profile(profile_name):
    # Retrieve profile json
    return {}

def list_calibration_profiles():
    # Return list of profile names
    return []

def register_calibration_profile(name, data):
    pass

def update_calibration_profile(name, data):
    pass

def delete_calibration_profile(name):
    pass

# --- Additional Run Helpers ---


def check_update_needed_files(folder):
    return []

def vacuum_database():
    """データベースをVACUUMして最適化する"""
    with get_db_connection() as conn:
        conn.execute("VACUUM")

def update_folder_profiles(folder_alias: str, profile_name: str, scope: Optional[str] = None) -> int:
    """指定されたフォルダ（の特定サブフォルダ）のプロファイルを一括更新する"""
    if not folder_alias:
        return 0
        
    with get_db_connection() as conn:
        c = conn.cursor()
        
        # Base query
        sql = "UPDATE ProcessLog SET calibration_profile = ? WHERE folder_alias = ?"
        params = [profile_name, folder_alias]
        
        if scope:
             # スコープ（サブフォルダ）フィルタ
             # output_folder が scope を含むか、scope配下にあるか
             # ここでは簡易に LIKE で判定
             sql += " AND output_folder LIKE ?"
             # Make sure scope uses correct separator or is treated as substring
             clean_scope = scope.replace('/', '%').replace('\\', '%')
             params.append(f"%{clean_scope}%")
        
        c.execute(sql, params)
        conn.commit()
        return c.rowcount


def get_track_data_for_export(run_id=None):
    """
    Exports track data for groups involved in overtake events.
    Includes all frames for these groups.
    Unified into a single 'overtake' DataFrame.
    
    Columns:
    イベントID, Run, 動画名, オフセットフレーム, 動画フレーム, 動画時間(s), 役割, Group ID, 相手Group,
    トラックID, クラス, BBOX x1, BBOX y1, BBOX x2, BBOX y2, 測定X(px), 測定Y(px),
    白線距離(m), 白線距離(cm), 白線距離(px), 白線距離比率(%), 白線内外判定,
    左白線距離(m), 左白線距離(cm), 左白線距離(px),
    右白線距離(m), 右白線距離(cm), 右白線距離(px),
    離隔距離(m), 離隔距離(cm), 離隔距離(px)
    """
    import pandas as pd
    import numpy as np
    
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # 1. Get relevant group IDs (only those present in OvertakeEvents)
        params = []
        sql_groups = """
            SELECT overtaker_group_id as gid FROM OvertakeEvents WHERE 1=1
        """
        if run_id is not None:
             sql_groups += " AND run_id = ?"
             params.append(run_id)
             
        sql_groups += " UNION SELECT overtaken_group_id as gid FROM OvertakeEvents WHERE 1=1"
        if run_id is not None:
             sql_groups += " AND run_id = ?"
             params.append(run_id)
             
        try:
            rows = c.execute(sql_groups, params).fetchall()
            group_ids = [r['gid'] for r in rows if r['gid'] is not None]
        except Exception as e:
            print(f"Error fetching group IDs: {e}")
            return {'bicycle': pd.DataFrame(), 'overtake': pd.DataFrame()}

        if not group_ids:
            return {'bicycle': pd.DataFrame(), 'overtake': pd.DataFrame()}

        # 2. Fetch all frames for these groups
        placeholders = ','.join(['?'] * len(group_ids))
        
        sql_tracks = f"""
            SELECT 
                d.auto_id as event_id,
                d.run_id,
                v.filename as video_name,
                v.fps as video_fps,
                d.frame_num,
                0 as offset_frame, -- Placeholder
                d.group_id,
                d.approach_partner_group_id,
                d.track_id,
                cm.class_name,
                d.x1, d.y1, d.x2, d.y2,
                d.measure_x, d.measure_y,
                
                -- Coalesce with OvertakeEvents (oe) for distances
                COALESCE(d.line_distance_m, oe.line_distance_m) as line_distance_m,
                COALESCE(d.line_distance, oe.line_distance) as line_distance_px,
                
                COALESCE(d.l_line_distance_m, oe.l_line_distance_m) as l_line_distance_m,
                COALESCE(d.l_line_distance, oe.l_line_distance) as l_line_distance_px,
                
                COALESCE(d.r_line_distance_m, oe.r_line_distance_m) as r_line_distance_m,
                COALESCE(d.r_line_distance, oe.r_line_distance) as r_line_distance_px,
                
                COALESCE(d.clearance_distance_m, oe.clearance_distance_m) as clearance_distance_m,
                COALESCE(d.clearance_distance_px, oe.clearance_distance_px) as clearance_distance_px,
                
                d.lane_position_flag,
                d.overtake,
                d.overtake_by
            FROM Detection d
            JOIN ProcessLog pl ON d.run_id = pl.run_id
            JOIN Video v ON pl.video_id = v.video_id
            LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
            LEFT JOIN OvertakeEvents oe ON d.run_id = oe.run_id 
                AND d.frame_num = oe.event_frame_num 
                AND (d.group_id = oe.overtaker_group_id OR d.group_id = oe.overtaken_group_id)
            WHERE d.group_id IN ({placeholders})
        """
        
        query_params = list(group_ids)
        if run_id is not None:
             sql_tracks += " AND d.run_id = ?"
             query_params.append(run_id)
        
        sql_tracks += " ORDER BY d.group_id, d.frame_num"
        
        try:
            df = pd.read_sql_query(sql_tracks, conn, params=query_params)
        except Exception as e:
            print(f"Error fetching main tracks: {e}")
            return {'bicycle': pd.DataFrame(), 'overtake': pd.DataFrame()}

        if df.empty:
             return {'bicycle': pd.DataFrame(), 'overtake': pd.DataFrame()}

        # 3. Post-process in Pandas
        result_rows = []
        
        for _, row in df.iterrows():
             # Calculate video time
             fps = row.get('video_fps') or 30.0
             frame_num = row.get('frame_num') or 0
             video_time_s = frame_num / fps if fps > 0 else 0
             
             # Determine role
             if row.get('overtake') == 1:
                 role = '追い越し車'
             elif row.get('overtake_by'):
                 role = '追い越され車'
                 # If we have OvertakeEvents link, 'overtake_by' might also imply being overtaken by someone specific
                 # but for now we follow detection flags.
             else:
                 # Even if not flagged in this frame, if it's in the group list, meaningful role might be inferred
                 # Check if the class is bicycle
                 cls = str(row.get('class_name') or '').lower()
                 if 'bicycle' in cls:
                     role = '追い越され車' # Assumption for now if in this filtered list
                 else:
                     role = '追い越し車' # Assumption
             
             # Refine role based on flags if available
             # Note: Detection flags 'overtake'/'overtake_by' might be 0 in non-event frames
             # We rely on the group membership essentially.
             
             # Measures
             x1, y1 = row.get('x1') or 0, row.get('y1') or 0
             x2, y2 = row.get('x2') or 0, row.get('y2') or 0
             measure_x = row.get('measure_x') or ((x1 + x2) / 2)
             measure_y = row.get('measure_y') or y2
             
             # Line Distances
             line_m = row.get('line_distance_m')
             line_cm = line_m * 100 if line_m is not None else None
             line_px = row.get('line_distance_px')
             
             l_line_m = row.get('l_line_distance_m')
             l_line_cm = l_line_m * 100 if l_line_m is not None else None
             l_line_px = row.get('l_line_distance_px')
             
             r_line_m = row.get('r_line_distance_m')
             r_line_cm = r_line_m * 100 if r_line_m is not None else None
             r_line_px = row.get('r_line_distance_px')
             
             # Clearance
             clr_m = row.get('clearance_distance_m')
             clr_cm = clr_m * 100 if clr_m is not None else None
             clr_px = row.get('clearance_distance_px')
             
             # Calculations
             # Ratio based on assumption (e.g., 3.0m lane width)
             line_ratio = (line_m / 3.0 * 100) if line_m is not None else None
             
             # Line Judgment
             lane_flag = str(row.get('lane_position_flag') or '')
             if 'outside' in lane_flag.lower() or 'はみ出し' in lane_flag:
                 judgment = '外'
             elif 'inside' in lane_flag.lower() or '内側' in lane_flag:
                 judgment = '内'
             else:
                 judgment = '-'
                 
             result_rows.append({
                 'イベントID': row.get('event_id'),
                 'Run': row.get('run_id'),
                 '動画名': row.get('video_name'),
                 'オフセットフレーム': 0, 
                 '動画フレーム': frame_num,
                 '動画時間(s)': round(video_time_s, 2),
                 '役割': role,
                 'Group ID': row.get('group_id'),
                 '相手Group': row.get('approach_partner_group_id'),
                 'トラックID': row.get('track_id'),
                 'クラス': row.get('class_name'),
                 'BBOX x1': round(x1, 1),
                 'BBOX y1': round(y1, 1),
                 'BBOX x2': round(x2, 1),
                 'BBOX y2': round(y2, 1),
                 '測定X(px)': round(measure_x, 1),
                 '測定Y(px)': round(measure_y, 1),
                 '白線距離(m)': round(line_m, 3) if line_m is not None else None,
                 '白線距離(cm)': round(line_cm, 1) if line_cm is not None else None,
                 '白線距離(px)': round(line_px, 1) if line_px is not None else None,
                 '白線距離比率(%)': round(line_ratio, 1) if line_ratio is not None else None,
                 '白線内外判定': judgment,
                 '左白線距離(m)': round(l_line_m, 3) if l_line_m is not None else None,
                 '左白線距離(cm)': round(l_line_cm, 1) if l_line_cm is not None else None,
                 '左白線距離(px)': round(l_line_px, 1) if l_line_px is not None else None,
                 '右白線距離(m)': round(r_line_m, 3) if r_line_m is not None else None,
                 '右白線距離(cm)': round(r_line_cm, 1) if r_line_cm is not None else None,
                 '右白線距離(px)': round(r_line_px, 1) if r_line_px is not None else None,
                 '離隔距離(m)': round(clr_m, 3) if clr_m is not None else None,
                 '離隔距離(cm)': round(clr_cm, 1) if clr_cm is not None else None,
                 '離隔距離(px)': round(clr_px, 1) if clr_px is not None else None,
             })
             
        final_df = pd.DataFrame(result_rows)
        return {'bicycle': pd.DataFrame(), 'overtake': final_df}


def get_detection_frame_offset(run_id: int) -> int:
    return 0


def convert_video_frame_to_detection_frame(run_id, frame):
    return frame

def convert_detection_frame_to_video_frame(run_id, frame):
    return frame

def fetch_detections_for_frame(run_id, frame):
    """指定フレームの検出データ(BBOX)を取得する"""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        sql = """
            SELECT 
                d.auto_id,
                d.run_id,
                d.frame_num,
                d.group_id,
                d.track_id,
                d.class_id,
                cm.class_name,
                d.x1, d.y1, d.x2, d.y2,
                d.confidence,
                d.speed_km_h,
                d.travel_direction
            FROM Detection d
            LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
            WHERE d.run_id = ? AND d.frame_num = ?
            ORDER BY d.group_id, d.track_id
        """
        rows = c.execute(sql, (run_id, frame)).fetchall()
        return [dict(row) for row in rows]

def delete_manual_overtake_event(run_id: int, manual_event_id: int) -> bool:
    """手動追い越しイベントを削除し、関連するDetectionフラグをクリアする"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # 1. 削除対象のイベント情報を取得してフラグクリアの準備
            c.execute("SELECT frame_num, overtaker_group_id, overtaken_group_id FROM ManualOvertakeEvents WHERE run_id = ? AND manual_event_id = ?", (run_id, manual_event_id))
            row = c.fetchone()
            
            if row:
                frame_num, overtaker_gid, overtaken_gid = row
                
                # フラグリセット
                # overtakeフラグ (追い越し側)
                c.execute("UPDATE Detection SET overtake = 0 WHERE run_id = ? AND frame_num = ? AND group_id = ?", (run_id, frame_num, overtaker_gid))
                # overtake_byフラグ (追い越され側)
                c.execute("UPDATE Detection SET overtake_by = NULL WHERE run_id = ? AND frame_num = ? AND group_id = ?", (run_id, frame_num, overtaken_gid))
            
            # 2. 関連テーブルからの削除
            c.execute("DELETE FROM ManualOvertakeEvents WHERE run_id = ? AND manual_event_id = ?", (run_id, manual_event_id))
            c.execute("DELETE FROM ManualOvertakeTimeline WHERE run_id = ? AND manual_event_id = ?", (run_id, manual_event_id))
            c.execute("DELETE FROM ManualContextBacklog WHERE run_id = ? AND manual_event_id = ?", (run_id, manual_event_id))
            
            conn.commit()
            return True
            
    except Exception as e:
        print(f"Error deleting manual overtake event: {e}")
        return False

def fetch_detection_for_group(run_id, frame_num, group_id):
    """指定されたフレーム、Group IDの検出データを1件取得する"""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        sql = """
            SELECT 
                d.auto_id,
                d.run_id,
                d.frame_num,
                d.group_id,
                d.track_id,
                d.class_id,
                cm.class_name,
                d.x1, d.y1, d.x2, d.y2,
                d.confidence,
                d.speed_km_h,
                d.travel_direction,
                d.approach_distance_m,
                d.approach_distance_px,
                d.clearance_distance_m,
                d.clearance_distance_cm,
                d.clearance_distance_px,
                d.approach_partner_group_id,
                d.line_distance_m,
                d.l_line_distance_m,
                d.r_line_distance_m,
                d.overtake,
                d.overtake_by,
                d.pixel_speed,
                d.pixel_speed_frame
            FROM Detection d
            LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
            WHERE d.run_id = ? AND d.frame_num = ? AND d.group_id = ?
            LIMIT 1
        """
        row = c.execute(sql, (run_id, frame_num, group_id)).fetchone()
        if row:
            return dict(row)
        return None

def fetch_detection_for_track(run_id, frame_num, track_id):
    """指定されたフレーム、Track IDの検出データを1件取得する"""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        sql = """
            SELECT 
                d.auto_id,
                d.run_id,
                d.frame_num,
                d.group_id,
                d.track_id,
                d.class_id,
                cm.class_name,
                d.x1, d.y1, d.x2, d.y2,
                d.confidence,
                d.speed_km_h,
                d.travel_direction,
                d.approach_distance_m,
                d.approach_distance_px,
                d.clearance_distance_m,
                d.clearance_distance_cm,
                d.clearance_distance_px,
                d.approach_partner_group_id,
                d.line_distance_m,
                d.l_line_distance_m,
                d.r_line_distance_m,
                d.overtake,
                d.overtake_by,
                d.pixel_speed,
                d.pixel_speed_frame
            FROM Detection d
            LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
            WHERE d.run_id = ? AND d.frame_num = ? AND d.track_id = ?
            LIMIT 1
        """
        row = c.execute(sql, (run_id, frame_num, track_id)).fetchone()
        if row:
            return dict(row)
        return None

def get_first_detection_frame(run_id):
    """指定Runの最初の検出フレーム番号を取得"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT MIN(frame_num) FROM Detection WHERE run_id = ?", (run_id,))
        row = c.fetchone()
        return row[0] if row and row[0] is not None else 0

def get_first_bicycle_detection_frame(run_id):
    """指定Runの自転車の最初の検出フレーム番号を取得"""
    bicycle_aliases = get_bicycle_class_aliases()
    if not bicycle_aliases:
        return get_first_detection_frame(run_id)
    with get_db_connection() as conn:
        c = conn.cursor()
        placeholders = ",".join("?" * len(bicycle_aliases))
        sql = f"""
            SELECT MIN(d.frame_num) 
            FROM Detection d
            JOIN ClassMaster cm ON d.class_id = cm.class_id
            WHERE d.run_id = ? AND LOWER(cm.class_name) IN ({placeholders})
        """
        aliases_lower = [a.lower() for a in bicycle_aliases]
        c.execute(sql, (run_id, *aliases_lower))
        row = c.fetchone()
        return row[0] if row and row[0] is not None else 0

def get_bicycle_orientation_counts(run_id):
    """自転車の向き(travel_direction)別のカウントを取得"""
    bicycle_aliases = get_bicycle_class_aliases()
    if not bicycle_aliases:
        return {}
    with get_db_connection() as conn:
        c = conn.cursor()
        placeholders = ",".join("?" * len(bicycle_aliases))
        sql = f"""
            SELECT d.travel_direction, COUNT(*) as cnt
            FROM Detection d
            JOIN ClassMaster cm ON d.class_id = cm.class_id
            WHERE d.run_id = ? AND LOWER(cm.class_name) IN ({placeholders})
            GROUP BY d.travel_direction
        """
        aliases_lower = [a.lower() for a in bicycle_aliases]
        rows = c.execute(sql, (run_id, *aliases_lower)).fetchall()
        return {row[0]: row[1] for row in rows if row[0] is not None}

def get_bicycle_class_aliases():
    """自転車として扱うクラス名のエイリアス一覧を返す"""
    return ["bicycle", "bike", "cyclist", "自転車"]

def fetch_tire_detections_for_group(run_id, frame, group_id):
    """指定グループのタイヤ検出を取得"""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        sql = """
            SELECT 
                d.auto_id, d.frame_num, d.group_id, d.track_id,
                d.class_id, cm.class_name,
                d.x1, d.y1, d.x2, d.y2, d.confidence
            FROM Detection d
            LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
            WHERE d.run_id = ? AND d.frame_num = ? AND d.group_id = ?
                AND (LOWER(cm.class_name) LIKE '%tire%' OR LOWER(cm.class_name) LIKE '%wheel%')
        """
        rows = c.execute(sql, (run_id, frame, group_id)).fetchall()
        return [dict(row) for row in rows]

def fetch_best_group_bbox(run_id, frame, group_id):
    """指定グループの最も信頼度の高いBBOXを取得"""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        sql = """
            SELECT 
                d.auto_id, d.frame_num, d.group_id, d.track_id,
                d.class_id, cm.class_name,
                d.x1, d.y1, d.x2, d.y2, d.confidence,
                d.speed_km_h
            FROM Detection d
            LEFT JOIN ClassMaster cm ON d.class_id = cm.class_id
            WHERE d.run_id = ? AND d.frame_num = ? AND d.group_id = ?
            ORDER BY d.confidence DESC
            LIMIT 1
        """
        row = c.execute(sql, (run_id, frame, group_id)).fetchone()
        return dict(row) if row else {}

def get_first_detection_frame_for_group(run_id, group_id):
    """指定グループの最初の検出フレーム番号を取得"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT MIN(frame_num) FROM Detection WHERE run_id = ? AND group_id = ?", (run_id, group_id))
        row = c.fetchone()
        return row[0] if row and row[0] is not None else 0

def get_next_detection_frame_for_group(run_id, group_id, current_frame):
    """指定グループの次の検出フレーム番号を取得"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT MIN(frame_num) FROM Detection WHERE run_id = ? AND group_id = ? AND frame_num > ?",
            (run_id, group_id, current_frame)
        )
        row = c.fetchone()
        return row[0] if row and row[0] is not None else None

def get_auto_overtake_events_for_run(run_id):
    """指定Runの自動検出追い越しイベントを取得する"""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        sql = """
            SELECT 
                overtake_event_id,
                event_frame_num,
                overtaker_group_id,
                overtaken_group_id,
                clearance_distance_m,
                clearance_distance_cm
            FROM OvertakeEvents
            WHERE run_id = ?
            ORDER BY event_frame_num
        """
        rows = c.execute(sql, (run_id,)).fetchall()
        return [dict(row) for row in rows]

def fetch_detections_for_group_window(run_id, group_id, center_frame, window=10):
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        start = center_frame - window
        end = center_frame + window
        c.execute("""
            SELECT frame_num, y1, y2 
            FROM Detection 
            WHERE run_id = ? AND group_id = ? AND frame_num BETWEEN ? AND ?
            ORDER BY frame_num ASC
        """, (run_id, group_id, start, end))
        return [dict(row) for row in c.fetchall()]

def get_group_movement_direction(run_id, group_id, current_frame, window=20):
    """
    グループの移動方向を判定する。
    return: 'up_to_down' (Y増), 'down_to_up' (Y減), 'unknown'
    """
    if group_id is None:
        return 'unknown'
        
    detections = fetch_detections_for_group_window(run_id, group_id, current_frame, window)
    if len(detections) < 2:
        return 'unknown'
    
    first = detections[0]
    last = detections[-1]
    
    # 中心Y座標の変化を見る
    def get_center_y(d):
        y1 = d.get('y1')
        y2 = d.get('y2')
        if y1 is None or y2 is None: return None
        return (float(y1) + float(y2)) / 2.0
        
    y_first = get_center_y(first)
    y_last = get_center_y(last)
    
    if y_first is None or y_last is None:
        return 'unknown'
        
    diff = y_last - y_first
    frame_diff = last['frame_num'] - first['frame_num']
    
    if frame_diff == 0:
        return 'unknown'
        
    # Yが増加 -> 画面上から下へ (通常の手前来る方向)
    # Yが減少 -> 画面下から上へ (奥へ行く方向)
    # 閾値を設ける (例えば 5px以上の変化)
    if diff > 5.0:
        return 'up_to_down'
    elif diff < -5.0:
        return 'down_to_up'
        
    return 'unknown'

def update_run_profile(run_id, profile_name):
    """Runのキャリブレーションプロファイルを更新する"""
    val = None if not profile_name or profile_name == "__CLEAR__" else profile_name
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE ProcessLog SET calibration_profile = ? WHERE run_id = ?", (val, run_id))
        conn.commit()
        return c.rowcount

def update_folder_profiles(folder_alias, profile_name, scope=None):
    """指定されたフォルダ（エイリアス）に属するすべてのRunのプロファイルを更新する。"""
    targets = get_run_ids_by_folder(folder_alias)
    if not targets:
        return 0
    
    count = 0
    for rid in targets:
        if update_run_profile(rid, profile_name):
            count += 1
    return count

def get_manual_events_for_run(run_id: int) -> List[Dict[str, Any]]:
    """指定されたRun IDに関連するManualOvertakeEventsのデータを取得する（バックアップ用）。"""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        # idは自動採番なので除外、run_idは後で置換するので取得はするが使わない
        sql = """
            SELECT * FROM ManualOvertakeEvents WHERE run_id = ?
        """
        rows = c.execute(sql, (run_id,)).fetchall()
        return [dict(row) for row in rows]

def restore_manual_events(new_run_id: int, events: List[Dict[str, Any]]) -> int:
    """バックアップしたManualOvertakeEventsデータを新しいRun IDで復元する。"""
    if not events:
        return 0
    
    restored_count = 0
    with get_db_connection() as conn:
        c = conn.cursor()
        
        # カラム名を取得（最初のイベントデータから推定）
        # ただし manual_event_id は除外、run_id は上書き
        first_event = events[0]
        columns = [k for k in first_event.keys() if k != 'manual_event_id']
        
        placeholders = ', '.join(['?'] * len(columns))
        col_names = ', '.join(columns)
        
        sql = f"INSERT INTO ManualOvertakeEvents ({col_names}) VALUES ({placeholders})"
        
        for event in events:
            # 新しいRun IDを適用
            event['run_id'] = new_run_id
            
            values = [event[col] for col in columns]
            try:
                c.execute(sql, values)
                restored_count += 1
            except Exception as e:
                print(f"[Restore Manual Events] Error restoring event: {e}")
                
        conn.commit()
    return restored_count
