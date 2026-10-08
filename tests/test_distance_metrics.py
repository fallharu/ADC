import math
import sqlite3
import unittest

from Source_code.modules.inter_vehicle_distance import _int_or_none
from Source_code.modules.manual_metrics import (
    compute_clearance,
    lane_scale_details_at_y,
)


class DistanceMetricsTest(unittest.TestCase):
    def test_clearance_uses_horizontal_distance_when_vertical_scale_missing(self):
        left_line = [[0.0, 0.0], [0.0, 500.0]]
        right_line = [[100.0, 0.0], [100.0, 500.0]]
        det_a = {"measure_x": 10.0, "measure_y": 100.0}
        det_b = {"measure_x": 30.0, "measure_y": 400.0}

        result = compute_clearance(
            det_a,
            det_b,
            left_line,
            right_line,
            lane_width_m=10.0,
        )

        self.assertTrue(math.isclose(result.distance_px, math.hypot(20.0, 300.0)))
        self.assertAlmostEqual(result.distance_m, 2.0)
        self.assertAlmostEqual(result.distance_cm, 200.0)

    def test_lane_scale_rejects_too_narrow_lane_width(self):
        details = lane_scale_details_at_y(
            50.0,
            [[10.0, 0.0], [10.0, 100.0]],
            [[15.0, 0.0], [15.0, 100.0]],
        )

        self.assertFalse(details.is_available)
        self.assertIsNone(details.pixels_per_meter)

    def test_sqlite_blob_id_is_normalized_to_integer(self):
        blob_value = sqlite3.Binary((42).to_bytes(8, byteorder="little", signed=True))

        self.assertEqual(_int_or_none(blob_value), 42)


if __name__ == "__main__":
    unittest.main()
