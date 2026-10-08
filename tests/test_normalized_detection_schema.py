import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from Source_code.modules.normalized_detection_schema import (
    archive_database,
    ensure_normalized_detection_schema,
    sync_normalized_detection_tables,
)


class NormalizedDetectionSchemaTest(unittest.TestCase):
    def test_sync_splits_detection_and_manual_event_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("CREATE TABLE ProcessLog (run_id INTEGER PRIMARY KEY)")
                conn.execute("CREATE TABLE Video (video_id INTEGER PRIMARY KEY)")
                conn.execute("CREATE TABLE ClassMaster (class_id INTEGER PRIMARY KEY, class_name TEXT)")
                conn.execute(
                    """
                    CREATE TABLE Detection (
                        auto_id INTEGER PRIMARY KEY,
                        run_id INTEGER,
                        video_id INTEGER,
                        class_id INTEGER,
                        frame_num INTEGER,
                        model_name TEXT,
                        class_name TEXT,
                        confidence REAL,
                        track_id INTEGER,
                        x1 REAL, y1 REAL, x2 REAL, y2 REAL,
                        group_id INTEGER,
                        speed_km_h REAL,
                        front_distance_m REAL,
                        ttc_s REAL,
                        measure_x REAL,
                        measure_y REAL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE ManualOvertakeEvents (
                        manual_event_id INTEGER PRIMARY KEY,
                        run_id INTEGER,
                        frame_num INTEGER,
                        overtaker_auto_id INTEGER,
                        overtaker_group_id INTEGER,
                        overtaker_track_id INTEGER,
                        overtaker_class_name TEXT,
                        overtaker_measure_x REAL,
                        overtaker_measure_y REAL,
                        overtaken_auto_id INTEGER,
                        overtaken_group_id INTEGER,
                        overtaken_track_id INTEGER,
                        overtaken_class_name TEXT,
                        overtaken_measure_x REAL,
                        overtaken_measure_y REAL,
                        clearance_distance_m REAL,
                        lane_width_m REAL,
                        notes TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
                conn.execute("INSERT INTO ProcessLog (run_id) VALUES (1)")
                conn.execute("INSERT INTO Video (video_id) VALUES (1)")
                conn.executemany(
                    """
                    INSERT INTO Detection (
                        auto_id, run_id, video_id, class_id, frame_num, model_name,
                        class_name, confidence, track_id, x1, y1, x2, y2,
                        group_id, speed_km_h, front_distance_m, ttc_s, measure_x, measure_y
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (10, 1, 1, 2, 100, "yolo", "car", 0.9, 7, 1, 2, 3, 4, 11, 36.0, 10.0, 2.0, 3.0, 4.0),
                        (20, 1, 1, 3, 100, "yolo", "bicycle", 0.8, 8, 5, 6, 7, 8, 12, 18.0, None, None, 7.0, 8.0),
                    ],
                )
                conn.execute(
                    """
                    INSERT INTO ManualOvertakeEvents (
                        manual_event_id, run_id, frame_num,
                        overtaker_auto_id, overtaker_group_id, overtaker_track_id,
                        overtaker_class_name, overtaker_measure_x, overtaker_measure_y,
                        overtaken_auto_id, overtaken_group_id, overtaken_track_id,
                        overtaken_class_name, overtaken_measure_x, overtaken_measure_y,
                        clearance_distance_m, lane_width_m, notes, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (1, 1, 100, 10, 11, 7, "car", 3.1, 4.1, 20, 12, 8, "bicycle", 7.1, 8.1, 1.5, 7.0, "checked", "now", "now"),
                )

                ensure_normalized_detection_schema(conn)
                summary = sync_normalized_detection_tables(conn)

                self.assertEqual(summary["raw_rows"], 2)
                self.assertEqual(summary["metric_rows"], 2)
                self.assertEqual(summary["manual_override_rows"], 2)

                raw = conn.execute(
                    "SELECT class_name, x1, y2 FROM DetectionRaw WHERE raw_detection_id = 10"
                ).fetchone()
                metric = conn.execute(
                    "SELECT speed_km_h, front_distance_m, ttc_s FROM DetectionMetrics WHERE raw_detection_id = 10"
                ).fetchone()
                manual = conn.execute(
                    """
                    SELECT role, raw_detection_id, measure_x, lane_width_m
                    FROM ManualDetectionOverrides
                    WHERE manual_event_id = 1 AND role = 'overtaker'
                    """
                ).fetchone()

                self.assertEqual(raw, ("car", 1.0, 4.0))
                self.assertEqual(metric, (36.0, 10.0, 2.0))
                self.assertEqual(manual, ("overtaker", 10, 3.1, 7.0))

                archive_path = archive_database(db_path, Path(tmp) / "archive")
                self.assertTrue(archive_path.exists())


if __name__ == "__main__":
    unittest.main()
