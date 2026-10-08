from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Source_code.modules.db_manager import MAIN_DB_PATH, configure_connection
from Source_code.modules.normalized_detection_schema import (
    archive_database,
    ensure_normalized_detection_schema,
    record_schema_migration,
    sync_normalized_detection_tables,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Archive the current SQLite DB and add normalized detection tables."
    )
    parser.add_argument("--db", default=MAIN_DB_PATH, help="SQLite DB path")
    parser.add_argument("--archive-dir", default=None, help="Backup output directory")
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Skip the pre-migration SQLite backup",
    )
    parser.add_argument(
        "--run-id",
        type=int,
        default=None,
        help="Only sync one run. Schema is still created globally.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).resolve()
    archive_path = None
    if not args.no_archive:
        archive_path = archive_database(db_path, args.archive_dir)

    with sqlite3.connect(db_path) as conn:
        configure_connection(conn, mode="write")
        ensure_normalized_detection_schema(conn)
        summary = sync_normalized_detection_tables(conn, run_id=args.run_id)
        record_schema_migration(
            conn,
            status="completed",
            source_db_path=db_path,
            archive_path=archive_path,
            details=summary,
        )
        conn.commit()

    payload = {
        "db_path": str(db_path),
        "archive_path": str(archive_path) if archive_path else None,
        "summary": summary,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
