import math
import unittest

try:
    import numpy as np
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover
    np = None
    pd = None

from Source_code.modules.inter_vehicle_distance import get_local_scale_from_calib
from Source_code.modules.speed_y_axis import prepare_vertical_context


@unittest.skipUnless(np is not None and pd is not None, "requires numpy and pandas")
class SpeedScaleTest(unittest.TestCase):
    def test_vertical_scale_is_not_extrapolated_outside_calibration_range(self):
        df = pd.DataFrame(
            {
                "center_y": [50.0, 150.0, 250.0],
                "smooth_center_y": [50.0, 150.0, 250.0],
                "track_id": [1, 1, 1],
            }
        )
        context = prepare_vertical_context(
            df,
            {
                "y_axis_lines": [
                    [[0.0, 100.0], [10.0, 100.0]],
                    [[0.0, 200.0], [10.0, 200.0]],
                ],
                "num_intervals": 1,
                "known_distance_m": 10.0,
            },
        )

        self.assertTrue(context.ready)
        self.assertTrue(math.isnan(context.ppm_series.iloc[0]))
        self.assertAlmostEqual(context.ppm_series.iloc[1], 10.0)
        self.assertTrue(math.isnan(context.ppm_series.iloc[2]))

    def test_proximity_scale_is_not_extrapolated_outside_calibration_range(self):
        calib_data = {
            "scale": {
                "y_axis_lines": [
                    [[0.0, 100.0], [10.0, 100.0]],
                    [[0.0, 200.0], [10.0, 200.0]],
                ],
                "num_intervals": 1,
                "known_distance_m": 10.0,
            }
        }

        self.assertIsNone(get_local_scale_from_calib(50.0, calib_data))
        self.assertAlmostEqual(get_local_scale_from_calib(150.0, calib_data), 10.0)
        self.assertIsNone(get_local_scale_from_calib(250.0, calib_data))


if __name__ == "__main__":
    unittest.main()
