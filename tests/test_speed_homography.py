import unittest
import json
import gc
import os
import sqlite3
import tempfile
from unittest import mock

import numpy as np
import pandas as pd

from Source_code.modules.speed_homography import apply_homography_speed
from Source_code.modules import speed_homography as homography_module
from Source_code.modules.speed_y_axis import VerticalContext
from Source_code.modules import speed as speed_module
from Source_code.tools.calibration_tool import prepare_save_payload, save_calibration_payload


def _empty_vertical_context(index):
    return VerticalContext(
        ready=False,
        ppm_series=pd.Series(np.nan, index=index),
        y_delta=pd.Series(np.nan, index=index),
        range_min=None,
        range_max=None,
    )


def _trajectory(y_values):
    count = len(y_values)
    frame = pd.DataFrame(
        {
            "track_id": [1] * count,
            "frame_num": list(range(count)),
            "center_x": [5.0] * count,
            "center_y": y_values,
            "y2": y_values,
            "measure_x": [5.0] * count,
            "measure_y": y_values,
            "smooth_measure_x": [5.0] * count,
            "smooth_measure_y": y_values,
            "speed_mps": [0.0] * count,
            "speed_km_h": [0.0] * count,
            "acceleration_m_s2": [0.0] * count,
            "scale_pixels_per_meter": [np.nan] * count,
            "y_delta": [np.nan] * count,
        }
    )
    return frame


class CalibrationSpeedCorrectionTest(unittest.TestCase):
    def test_save_payload_accepts_camera_and_longitudinal_correction(self):
        _, payload, error = prepare_save_payload(
            7,
            {
                "profile_name": "speed-corrected",
                "scale": {
                    "mode": "homography",
                    "speed_window_seconds": 0.3,
                    "speed_smoothing_frames": 7,
                    "measurement_smoothing_frames": 9,
                    "homography": {
                        "image_points": [[0, 0], [10, 0], [10, 100], [0, 100]],
                        "width_m": 10,
                        "length_m": 100,
                        "longitudinal_correction": {
                            "estimated_positions_m": [0, 50, 100],
                            "corrected_positions_m": [0, 48, 95],
                        },
                    },
                },
                "camera": {
                    "model": "standard",
                    "camera_matrix": [[100, 0, 5], [0, 100, 50], [0, 0, 1]],
                    "dist_coeffs": [0.1, -0.02, 0, 0, 0],
                    "image_size": [1920, 1080],
                },
            },
        )

        self.assertIsNone(error)
        self.assertEqual(payload["scale"]["speed_window_seconds"], 0.3)
        self.assertEqual(payload["scale"]["speed_smoothing_frames"], 7)
        self.assertEqual(payload["scale"]["measurement_smoothing_frames"], 9)
        self.assertIn("longitudinal_correction", payload["scale"]["homography"])
        self.assertEqual(payload["camera"]["image_size"], [1920, 1080])

    def test_web_resave_preserves_hidden_correction_for_unchanged_geometry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            existing = {
                "camera": {
                    "camera_matrix": [[100, 0, 5], [0, 100, 50], [0, 0, 1]],
                    "dist_coeffs": [0, 0, 0, 0, 0],
                },
                "scale": {
                    "mode": "homography",
                    "homography": {
                        "image_points": [[0, 0], [10, 0], [10, 100], [0, 100]],
                        "width_m": 10.0,
                        "length_m": 100.0,
                        "longitudinal_correction": {
                            "estimated_positions_m": [0, 100],
                            "corrected_positions_m": [0, 95],
                        },
                    },
                },
            }
            existing_path = os.path.join(temp_dir, "profile.json")
            with open(existing_path, "w", encoding="utf-8") as handle:
                json.dump(existing, handle)
            replacement = {
                "scale": {
                    "mode": "homography",
                    "homography": {
                        "image_points": [[0, 0], [10, 0], [10, 100], [0, 100]],
                        "width_m": 10.0,
                        "length_m": 100.0,
                    },
                },
            }

            save_calibration_payload("profile", 7, replacement, calib_dir=temp_dir)
            with open(existing_path, "r", encoding="utf-8") as handle:
                saved = json.load(handle)

            self.assertIn("camera", saved)
            self.assertIn("longitudinal_correction", saved["scale"]["homography"])


@unittest.skipUnless(
    hasattr(homography_module.cv2, "findHomography"),
    "requires a full OpenCV installation",
)
class HomographySpeedTest(unittest.TestCase):
    def test_speed_uses_multi_frame_longitudinal_displacement(self):
        df = _trajectory([90.0, 80.0, 70.0, 60.0])
        time_s = df.groupby("track_id")["frame_num"].diff() / 10.0
        applied = apply_homography_speed(
            df,
            time_s,
            fps=10.0,
            frame_window=10,
            homography_meta={
                "image_points": [[0, 0], [10, 0], [10, 100], [0, 100]],
                "width_m": 10.0,
                "length_m": 100.0,
            },
            vertical_context=_empty_vertical_context(df.index),
            speed_window_frames=2,
        )

        self.assertTrue(applied)
        self.assertAlmostEqual(df.loc[2, "speed_mps"], 100.0, places=5)
        self.assertAlmostEqual(df.loc[3, "speed_mps"], 100.0, places=5)

    def test_longitudinal_profile_corrects_systematic_scale(self):
        df = _trajectory([10.0, 20.0, 30.0])
        time_s = df.groupby("track_id")["frame_num"].diff() / 10.0
        applied = apply_homography_speed(
            df,
            time_s,
            fps=10.0,
            frame_window=10,
            homography_meta={
                "image_points": [[0, 0], [10, 0], [10, 100], [0, 100]],
                "width_m": 10.0,
                "length_m": 100.0,
                "longitudinal_correction": {
                    "estimated_positions_m": [0.0, 100.0],
                    "corrected_positions_m": [0.0, 50.0],
                },
            },
            vertical_context=_empty_vertical_context(df.index),
            speed_window_frames=2,
        )

        self.assertTrue(applied)
        self.assertAlmostEqual(df.loc[2, "world_y_raw"], 30.0, places=5)
        self.assertAlmostEqual(df.loc[2, "world_y"], 15.0, places=5)
        self.assertAlmostEqual(df.loc[2, "speed_mps"], 50.0, places=5)

    def test_adjusted_calibration_lines_build_position_correction(self):
        df = _trajectory([0.0, 40.0])
        time_s = df.groupby("track_id")["frame_num"].diff() / 10.0
        applied = apply_homography_speed(
            df,
            time_s,
            fps=10.0,
            frame_window=10,
            homography_meta={
                "image_points": [[0, 0], [10, 0], [10, 100], [0, 100]],
                "width_m": 10.0,
                "length_m": 100.0,
                "interval_m": 50.0,
            },
            vertical_context=_empty_vertical_context(df.index),
            calibration_lines=[
                [[0, 0], [10, 0]],
                [[0, 40], [10, 40]],
                [[0, 100], [10, 100]],
            ],
        )

        self.assertTrue(applied)
        self.assertAlmostEqual(df.loc[1, "world_y_raw"], 40.0, places=5)
        self.assertAlmostEqual(df.loc[1, "world_y"], 50.0, places=5)
        self.assertAlmostEqual(df.loc[1, "speed_mps"], 500.0, places=5)

    def test_zero_distortion_camera_parameters_preserve_mapping(self):
        df = _trajectory([10.0, 20.0])
        time_s = df.groupby("track_id")["frame_num"].diff() / 10.0
        applied = apply_homography_speed(
            df,
            time_s,
            fps=10.0,
            frame_window=10,
            homography_meta={
                "image_points": [[0, 0], [10, 0], [10, 100], [0, 100]],
                "width_m": 10.0,
                "length_m": 100.0,
            },
            vertical_context=_empty_vertical_context(df.index),
            camera_meta={
                "camera_matrix": [[100.0, 0.0, 5.0], [0.0, 100.0, 50.0], [0.0, 0.0, 1.0]],
                "dist_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
            },
        )

        self.assertTrue(applied)
        self.assertAlmostEqual(df.loc[1, "world_y"], 20.0, places=4)

    def test_assign_kinematics_uses_homography_in_automatic_pipeline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "test.db")
            output_dir = os.path.join(temp_dir, "output")
            calibration_dir = os.path.join(output_dir, "calibrations")
            os.makedirs(calibration_dir)
            with sqlite3.connect(db_path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE ProcessLog (
                        run_id INTEGER PRIMARY KEY, video_id INTEGER, calibration_profile TEXT
                    );
                    CREATE TABLE Video (video_id INTEGER PRIMARY KEY, fps REAL);
                    CREATE TABLE Detection (
                        auto_id INTEGER PRIMARY KEY, run_id INTEGER, track_id INTEGER,
                        frame_num INTEGER, group_id INTEGER, x1 REAL, x2 REAL, y1 REAL, y2 REAL,
                        model_name TEXT, travel_direction TEXT, class_name TEXT,
                        scale_pixels_per_meter REAL, x_pixels_per_meter REAL,
                        pixel_speed REAL, pixel_speed_frame REAL, speed_km_h REAL,
                        acceleration_m_s2 REAL, acceleration_state TEXT
                    );
                    INSERT INTO ProcessLog VALUES (1, 1, 'profile');
                    INSERT INTO Video VALUES (1, 10.0);
                    """
                )
                rows = [
                    (
                        frame + 1,
                        1,
                        10,
                        frame,
                        10,
                        4.0,
                        6.0,
                        float(frame),
                        float(frame + 1),
                        "vehicle",
                        None,
                        "car",
                    )
                    for frame in range(30)
                ]
                conn.executemany(
                    """
                    INSERT INTO Detection (
                        auto_id, run_id, track_id, frame_num, group_id,
                        x1, x2, y1, y2, model_name, travel_direction, class_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )

            calibration = {
                "lines": {},
                "scale": {
                    "mode": "homography",
                    "speed_window_seconds": 0.2,
                    "speed_smoothing_frames": 3,
                    "homography": {
                        "image_points": [[0, 0], [10, 0], [10, 100], [0, 100]],
                        "width_m": 10.0,
                        "length_m": 100.0,
                    },
                },
            }
            with open(os.path.join(calibration_dir, "profile.json"), "w", encoding="utf-8") as handle:
                json.dump(calibration, handle)

            with mock.patch.object(speed_module, "MAIN_DB_PATH", db_path), mock.patch.dict(
                os.environ, {"Opt_files": output_dir}, clear=False
            ):
                speed_module.assign_kinematics(1)

            with sqlite3.connect(db_path) as conn:
                speed_km_h, x_ppm = conn.execute(
                    "SELECT speed_km_h, x_pixels_per_meter FROM Detection WHERE frame_num = 15"
                ).fetchone()
            del conn
            gc.collect()
            self.assertAlmostEqual(speed_km_h, 36.0, places=4)
            self.assertAlmostEqual(x_ppm, 2.0 / 1.8, places=4)


if __name__ == "__main__":
    unittest.main()
