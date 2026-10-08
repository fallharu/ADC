import unittest

import numpy as np

from scripts.generate_projection_speed_test_data import (
    END_M,
    START_M,
    accelerate_decelerate_scenario,
    constant_speed_scenario,
    generate_scenario_data,
)


class ProjectionSpeedTestDataTest(unittest.TestCase):
    def test_constant_speed_scenario_reaches_end_at_fixed_speed(self):
        scenario = constant_speed_scenario()

        self.assertAlmostEqual(scenario.position_m[0], START_M)
        self.assertAlmostEqual(scenario.position_m[-1], END_M)
        np.testing.assert_allclose(scenario.speed_mps, 15.0)

    def test_acceleration_scenario_peaks_near_middle_then_slows(self):
        scenario = accelerate_decelerate_scenario()
        peak_index = int(np.argmax(scenario.speed_mps))

        self.assertAlmostEqual(scenario.position_m[0], START_M)
        self.assertAlmostEqual(scenario.position_m[-1], END_M)
        self.assertAlmostEqual(scenario.speed_mps[0], 8.0)
        self.assertAlmostEqual(scenario.speed_mps[-1], 8.0)
        self.assertGreaterEqual(scenario.speed_mps[peak_index], 15.9)
        self.assertLess(abs(scenario.position_m[peak_index] - 50.0), 0.6)
        self.assertTrue(np.all(np.diff(scenario.speed_mps[: peak_index + 1]) >= 0.0))
        self.assertTrue(np.all(np.diff(scenario.speed_mps[peak_index:]) <= 0.0))

    def test_projection_round_trip_is_within_test_tolerance(self):
        scenarios = [constant_speed_scenario(), accelerate_decelerate_scenario()]

        for index, scenario in enumerate(scenarios):
            with self.subTest(scenario=scenario.key):
                pre, post, metrics = generate_scenario_data(scenario, seed=100 + index)

                self.assertEqual(len(pre), len(post))
                self.assertLess(metrics["position_rmse_m"], 0.2)
                self.assertLess(metrics["speed_rmse_km_h"], 2.5)
                self.assertEqual(post["speed_valid"].sum(), len(post) - 6)


if __name__ == "__main__":
    unittest.main()
