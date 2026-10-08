import unittest

import numpy as np
import pandas as pd

from Source_code.modules.speed_regression import (
    integrate_scaled_axis_position,
    rolling_linear_slope,
)


class RollingSpeedRegressionTest(unittest.TestCase):
    def test_linear_motion_uses_inclusive_lookback_window(self):
        frames = pd.Series(np.arange(8), dtype=float)
        position = frames * 0.1
        track_id = pd.Series([4] * len(frames))

        slope = rolling_linear_slope(
            frames,
            position,
            track_id,
            fps=10.0,
            lookback_frames=2,
        )

        self.assertTrue(slope.iloc[:2].isna().all())
        np.testing.assert_allclose(slope.iloc[2:].to_numpy(), 1.0, atol=1e-12)

    def test_all_points_in_window_affect_the_slope(self):
        frames = pd.Series(np.arange(7), dtype=float)
        position = pd.Series([0.0, 5.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        track_id = pd.Series([1] * len(frames))

        slope = rolling_linear_slope(
            frames,
            position,
            track_id,
            fps=30.0,
            lookback_frames=6,
        )

        expected = np.polyfit(frames.to_numpy() / 30.0, position.to_numpy(), 1)[0]
        endpoint_only = (position.iloc[-1] - position.iloc[0]) / (6.0 / 30.0)
        self.assertAlmostEqual(slope.iloc[-1], expected, places=12)
        self.assertNotAlmostEqual(slope.iloc[-1], endpoint_only, places=6)

    def test_invalid_point_rejects_the_affected_window(self):
        frames = pd.Series(np.arange(8), dtype=float)
        position = frames * 0.1
        track_id = pd.Series([1] * len(frames))
        valid = pd.Series([True, True, True, False, True, True, True, True])

        slope = rolling_linear_slope(
            frames,
            position,
            track_id,
            fps=10.0,
            lookback_frames=4,
            valid_mask=valid,
        )

        self.assertTrue(slope.iloc[4:].isna().all())

    def test_scaled_axis_integration_uses_average_pair_scale(self):
        position = integrate_scaled_axis_position(
            pd.Series([0.0, 10.0, 30.0]),
            pd.Series([10.0, 10.0, 20.0]),
            pd.Series([9, 9, 9]),
        )

        np.testing.assert_allclose(position.to_numpy(), [0.0, 1.0, 7.0 / 3.0])


if __name__ == "__main__":
    unittest.main()
