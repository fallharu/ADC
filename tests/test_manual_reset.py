import os
import sqlite3
import tempfile
import types
import unittest
import contextlib

import sys

if "dotenv" not in sys.modules:
    dotenv_stub = types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None)
    sys.modules["dotenv"] = dotenv_stub

from Source_code.modules import db_manager


class ManualOvertakeResetTest(unittest.TestCase):
    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(delete=False)
        self.tmp_db.close()
        self.original_path = db_manager.MAIN_DB_PATH
        db_manager.MAIN_DB_PATH = self.tmp_db.name
        with contextlib.closing(sqlite3.connect(db_manager.MAIN_DB_PATH)) as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(
                "CREATE TABLE ProcessLog (run_id INTEGER PRIMARY KEY, calibration_profile TEXT)"
            )
            conn.execute(
                "INSERT INTO ProcessLog (run_id, calibration_profile) VALUES (1, '')"
            )
            conn.execute(
                "CREATE TABLE Detection (\n"
                "    auto_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
                "    run_id INTEGER NOT NULL,\n"
                "    overtake INTEGER DEFAULT 1,\n"
                "    overtake_after INTEGER DEFAULT 1,\n"
                "    overtake_by INTEGER DEFAULT 5,\n"
                "    overtake_by_second INTEGER DEFAULT 6,\n"
                "    overtake_window_offset INTEGER DEFAULT 7\n"
                ")"
            )
            conn.execute(
                "INSERT INTO Detection (run_id) VALUES (1)"
            )
            db_manager.ensure_manual_annotation_schema(conn)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO ManualOvertakeEvents (run_id, frame_num, overtaker_group_id, overtaken_group_id, created_at)"
                " VALUES (1, 100, 10, 20, '2025-01-01T00:00:00')"
            )
            event_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO ManualOvertakeContext (manual_event_id, offset_frames, frame_num, overtaker_group_id, overtaken_group_id, created_at)"
                " VALUES (?, 0, 100, 10, 20, '2025-01-01T00:00:00')",
                (event_id,),
            )
            cursor.execute(
                "INSERT INTO ManualOvertakeTimeline (run_id, frame_num, overtaker_group_id, overtaken_group_id, created_at, updated_at)"
                " VALUES (1, 100, 10, 20, '2025-01-01T00:00:00', '2025-01-01T00:00:00')"
            )
            conn.commit()

    def tearDown(self):
        db_manager.MAIN_DB_PATH = self.original_path
        try:
            os.unlink(self.tmp_db.name)
        except FileNotFoundError:
            pass

    def test_reset_manual_overtake_for_runs_clears_data(self):
        events_deleted, detections_reset = db_manager.reset_manual_overtake_for_runs([1])
        self.assertGreaterEqual(events_deleted, 1)
        self.assertGreaterEqual(detections_reset, 1)
        with contextlib.closing(sqlite3.connect(db_manager.MAIN_DB_PATH)) as conn:
            event_count = conn.execute("SELECT COUNT(*) FROM ManualOvertakeEvents").fetchone()[0]
            context_count = conn.execute("SELECT COUNT(*) FROM ManualOvertakeContext").fetchone()[0]
            timeline_count = conn.execute("SELECT COUNT(*) FROM ManualOvertakeTimeline").fetchone()[0]
            detection_values = conn.execute(
                "SELECT overtake, overtake_after, overtake_by, overtake_by_second, overtake_window_offset FROM Detection"
            ).fetchone()
        self.assertEqual(event_count, 0)
        self.assertEqual(context_count, 0)
        self.assertEqual(timeline_count, 0)
        self.assertEqual(detection_values, (0, 0, 0, 0, 0))

    def test_reset_manual_overtake_handles_large_batches(self):
        run_ids = list(range(1, 1205))
        with contextlib.closing(sqlite3.connect(db_manager.MAIN_DB_PATH)) as conn:
            cursor = conn.cursor()
            for rid in run_ids[1:]:  # setUp ですでに Run1 分を作成済み
                cursor.execute("INSERT INTO Detection (run_id) VALUES (?)", (rid,))
                cursor.execute(
                    "INSERT INTO ManualOvertakeEvents (run_id, frame_num, overtaker_group_id, overtaken_group_id, created_at)"
                    " VALUES (?, ?, 10, 20, '2025-01-01T00:00:00')",
                    (rid, rid + 100),
                )
                event_id = cursor.lastrowid
                cursor.execute(
                    "INSERT INTO ManualOvertakeContext (manual_event_id, offset_frames, frame_num, overtaker_group_id, overtaken_group_id, created_at)"
                    " VALUES (?, 0, ?, 10, 20, '2025-01-01T00:00:00')",
                    (event_id, rid + 100),
                )
                cursor.execute(
                    "INSERT INTO ManualOvertakeTimeline (run_id, frame_num, overtaker_group_id, overtaken_group_id, created_at, updated_at)"
                    " VALUES (?, ?, 10, 20, '2025-01-01T00:00:00', '2025-01-01T00:00:00')",
                    (rid, rid + 100),
                )
            conn.commit()

        events_deleted, detections_reset = db_manager.reset_manual_overtake_for_runs(run_ids)
        self.assertGreaterEqual(events_deleted, len(run_ids))
        self.assertGreaterEqual(detections_reset, len(run_ids))

        with contextlib.closing(sqlite3.connect(db_manager.MAIN_DB_PATH)) as conn:
            remaining_events = conn.execute("SELECT COUNT(*) FROM ManualOvertakeEvents").fetchone()[0]
            remaining_context = conn.execute("SELECT COUNT(*) FROM ManualOvertakeContext").fetchone()[0]
            remaining_timeline = conn.execute("SELECT COUNT(*) FROM ManualOvertakeTimeline").fetchone()[0]
            detection_rows = conn.execute(
                "SELECT COUNT(*) FROM Detection WHERE overtake != 0 OR overtake_after != 0 OR overtake_by != 0 OR overtake_by_second != 0 OR overtake_window_offset != 0"
            ).fetchone()[0]

        self.assertEqual(remaining_events, 0)
        self.assertEqual(remaining_context, 0)
        self.assertEqual(remaining_timeline, 0)
        self.assertEqual(detection_rows, 0)

    def test_clear_manual_run_progress_handles_large_batches(self):
        run_ids = list(range(1, 1205))
        with contextlib.closing(sqlite3.connect(db_manager.MAIN_DB_PATH)) as conn:
            db_manager.ensure_manual_run_progress_columns(conn)
            cursor = conn.cursor()
            timestamp = "2025-01-01T00:00:00"
            for rid in run_ids:
                cursor.execute(
                    "INSERT OR REPLACE INTO ManualRunProgress (run_id, last_visit_at, last_review_at, last_annotation_at, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (rid, timestamp, timestamp, timestamp, timestamp, timestamp),
                )
            conn.commit()

        deleted = db_manager.clear_manual_run_progress(run_ids)
        self.assertEqual(deleted, len(run_ids))

        with contextlib.closing(sqlite3.connect(db_manager.MAIN_DB_PATH)) as conn:
            remaining = conn.execute("SELECT COUNT(*) FROM ManualRunProgress").fetchone()[0]

        self.assertEqual(remaining, 0)


if __name__ == "__main__":
    unittest.main()
