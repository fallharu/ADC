import os
import sqlite3
import tempfile
import unittest
import gc

from Source_code.modules import ttc_calculator


class TTCCalculatorTest(unittest.TestCase):
    def test_uses_front_vehicle_speed_from_same_frame(self):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            db_path = tmp.name
        original_path = ttc_calculator.MAIN_DB_PATH
        ttc_calculator.MAIN_DB_PATH = db_path
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE Detection (
                        auto_id INTEGER PRIMARY KEY,
                        run_id INTEGER,
                        frame_num INTEGER,
                        group_id INTEGER,
                        speed_km_h REAL,
                        front_distance_m REAL,
                        front_vehicle_id INTEGER,
                        ttc_s REAL
                    )
                    """
                )
                conn.executemany(
                    """
                    INSERT INTO Detection (
                        auto_id, run_id, frame_num, group_id, speed_km_h,
                        front_distance_m, front_vehicle_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (1, 10, 1, 1, 36.0, 10.0, 2),
                        (2, 10, 1, 2, 18.0, None, None),
                        (3, 10, 2, 2, 0.0, None, None),
                    ],
                )

            ttc_calculator.assign_ttc(10)

            with sqlite3.connect(db_path) as conn:
                ttc = conn.execute(
                    "SELECT ttc_s FROM Detection WHERE auto_id = 1"
                ).fetchone()[0]
                front_ttc = conn.execute(
                    "SELECT ttc_s FROM Detection WHERE auto_id = 2"
                ).fetchone()[0]

            self.assertAlmostEqual(ttc, 2.0)
            self.assertIsNone(front_ttc)
        finally:
            ttc_calculator.MAIN_DB_PATH = original_path
            gc.collect()
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.unlink(db_path + suffix)
                except (FileNotFoundError, PermissionError):
                    pass


if __name__ == "__main__":
    unittest.main()
