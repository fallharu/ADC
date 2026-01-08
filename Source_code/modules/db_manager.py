import sqlite3
import os
import contextlib
from typing import Optional, Any, List, Dict, Union
from datetime import datetime

# --- Constants ---
# Determine DB path relative to project root or use env var
# layout: Source_code/modules/db_manager.py -> values relative to CWD (usually project root)
# CWD is usually .../ADC_08
MAIN_DB_PATH = os.getenv("MAIN_DB_PATH", os.path.join("db", "my_app_data.db"))

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
            # Table doesn't exist, it will be created by init_db() later
            return
        
        # Check existing columns
        c.execute("PRAGMA table_info(Video)")
        columns = [row[1] for row in c.fetchall()]  # row[1] is the column name
        
        if "collection_year" not in columns:
            c.execute("ALTER TABLE Video ADD COLUMN collection_year INTEGER")
        if "road_type" not in columns:
            c.execute("ALTER TABLE Video ADD COLUMN road_type TEXT")
        conn.commit()
    finally:
        if should_close:
            conn.close()

def ensure_overtake_event_columns(conn=None):
    """Ensure OvertakeEvents table has necessary columns."""
    # Placeholder or implementation if migration needed
    init_db()


def init_db():
    """Initialize database tables."""
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
                base_video_id INTEGER, /* Alias for video_id for comp */
                FOREIGN KEY(video_id) REFERENCES Video(video_id)
            )
        """)
        # Detection table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS Detection (
                auto_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                frame_num INTEGER,
                model_name TEXT,
                class_name TEXT,
                confidence REAL,
                track_id INTEGER,
                speed_km_h REAL,
                lane_position_flag TEXT,
                distance_m REAL,
                ttc_s REAL,
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
        # OvertakeEvents
        conn.execute("""
             CREATE TABLE IF NOT EXISTS OvertakeEvents (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                event_frame_num INTEGER,
                overtaker_auto_id INTEGER,
                overtaken_auto_id INTEGER,
                direction TEXT,
                FOREIGN KEY(run_id) REFERENCES ProcessLog(run_id)
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
    # Placeholder for logic inferred from imports
    pass

# --- Core Run / Detection Functions ---

def list_detection_runs(page=1, per_page=20):
    """List detection runs (ProcessLog joined with Video) - placeholder logic."""
    # This might need to return a complex structure used by index.py
    # For now, implemented as a simple query
    with get_db_connection() as conn:
        c = conn.cursor()
        # Basic query matching likely schema
        sql = """
            SELECT 
                p.run_id, p.process_start as created_at, 
                v.filename, v.collection_year, v.road_type
            FROM ProcessLog p
            LEFT JOIN Video v ON p.video_id = v.video_id
            ORDER BY p.run_id DESC
        """
        rows = c.execute(sql).fetchall()
        return [dict(r) for r in rows]

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

def list_manual_overtake_events(run_id=None, limit=500):
    """Manual overtake events retrieval with optional filtering."""
    with get_db_connection() as conn:
        c = conn.cursor()
        
        # Build WHERE clause based on filters
        where_clauses = []
        params = []
        
        if run_id is not None:
            where_clauses.append("run_id = ?")
            params.append(run_id)
        
        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        # Query manual overtake events from ManualOvertakeEvents table
        sql = f"""
        SELECT 
            manual_event_id,
            run_id,
            frame_num,
            video_time_s,
            overtaker_group_id,
            overtaker_class_name,
            overtaker_speed_km_h,
            overtaker_speed_km_h_m30,
            overtaker_speed_km_h_p30,
            overtaken_group_id,
            overtaken_class_name,
            overtaken_speed_km_h,
            overtaken_speed_km_h_m30,
            overtaken_speed_km_h_p30,
            approach_distance_m,
            clearance_distance_cm,
            clearance_distance_m,
            overtaker_line_distance_m,
            overtaken_line_distance_m,
            created_at,
            notes
        FROM ManualOvertakeEvents
        {where_sql}
        ORDER BY manual_event_id DESC
        LIMIT ?
        """
        
        params.append(limit)
        
        try:
            rows = c.execute(sql, params).fetchall()
            events = [dict(row) for row in rows]
            
            # Add video_filename for each event by joining with ProcessLog and Video
            for event in events:
                if event.get('run_id'):
                    video_query = """
                    SELECT v.filename
                    FROM ProcessLog p
                    JOIN Video v ON p.video_id = v.video_id
                    WHERE p.run_id = ?
                    """
                    video_row = c.execute(video_query, (event['run_id'],)).fetchone()
                    event['video_filename'] = video_row[0] if video_row else None
                else:
                    event['video_filename'] = None
            
            return events
        except sqlite3.Error as e:
            # If ManualOvertakeEvents table doesn't exist, return empty list
            print(f"Warning: Could not query ManualOvertakeEvents: {e}")
            return []

def fetch_manual_overtake_event(event_id):
    return None

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
        
        # Rowオブジェクトをdictに変換しつつ、Noneフィールドを調整
        results = []
        for r in rows:
             d = dict(r)
             # video_filenameがNULLの場合は "(deleted video)" とか入れてもいいが、Unknownのままにする
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
        return [dict(r) for r in rows]

def get_run_ids_by_folder(folder_alias):
    """指定されたフォルダエイリアスに属するRun IDのリストを返す"""
    if not folder_alias:
        return []
        
    with get_db_connection() as conn:
        c = conn.cursor()
        sql = "SELECT run_id FROM ProcessLog WHERE folder_alias = ? ORDER BY run_id"
        rows = c.execute(sql, (folder_alias,)).fetchall()
        return [r[0] for r in rows]

# Removed duplicate definition


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
def get_run_video_info(run_id):
    # Used in manual override logic
    with get_db_connection() as conn:
        c = conn.cursor()
        # ProcessLogから直接取得
        row = c.execute("SELECT * FROM ProcessLog WHERE run_id = ?", (run_id,)).fetchone()
        if not row: return {}
        # Need to fetch video metadata too
        vid = row["video_id"]
        vrow = c.execute("SELECT * FROM Video WHERE video_id = ?", (vid,)).fetchone()
        
        info = dict(row)
        if vrow:
             info.update(dict(vrow))
        return info

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

