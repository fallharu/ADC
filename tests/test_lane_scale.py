import unittest

from Source_code.modules.manual_metrics import lane_scale_at_point, lane_scale_details_at_y


class LaneScaleDetailsTest(unittest.TestCase):
    def setUp(self):
        self.left_line = [[10.0, 0.0], [10.0, 100.0]]
        self.center_line = [[30.0, 0.0], [30.0, 100.0]]
        self.right_line = [[50.0, 0.0], [50.0, 100.0]]
        self.left_mid_line = [[20.0, 0.0], [20.0, 100.0]]
        self.right_mid_line = [[40.0, 0.0], [40.0, 100.0]]

    def test_anchor_points_include_mid_lines(self):
        details = lane_scale_details_at_y(
            50.0,
            self.left_line,
            self.right_line,
            center_line=self.center_line,
            left_inner_line=self.left_mid_line,
            right_inner_line=self.right_mid_line,
        )
        self.assertTrue(details.is_available)
        # 全幅は40px -> 8m なので 5px/m
        self.assertAlmostEqual(details.pixels_per_meter, 5.0)
        self.assertAlmostEqual(details.left_pixels_per_meter, 5.0)
        self.assertAlmostEqual(details.right_pixels_per_meter, 5.0)
        self.assertAlmostEqual(details.left_mid_pixels_per_meter, 5.0)
        self.assertAlmostEqual(details.right_mid_pixels_per_meter, 5.0)
        anchors = details.anchor_points
        self.assertIsNotNone(anchors)
        self.assertGreaterEqual(len(anchors), 5)
        xs = [pt[0] for pt in anchors]
        self.assertIn(20.0, xs)
        self.assertIn(40.0, xs)

    def test_scale_at_point_uses_segment_interpolation(self):
        scale_left = lane_scale_at_point(
            12.0,
            50.0,
            self.left_line,
            self.right_line,
            center_line=self.center_line,
            left_inner_line=self.left_mid_line,
            right_inner_line=self.right_mid_line,
        )
        scale_mid = lane_scale_at_point(
            30.0,
            50.0,
            self.left_line,
            self.right_line,
            center_line=self.center_line,
            left_inner_line=self.left_mid_line,
            right_inner_line=self.right_mid_line,
        )
        scale_right = lane_scale_at_point(
            45.0,
            50.0,
            self.left_line,
            self.right_line,
            center_line=self.center_line,
            left_inner_line=self.left_mid_line,
            right_inner_line=self.right_mid_line,
        )
        self.assertAlmostEqual(scale_left, 5.0)
        self.assertAlmostEqual(scale_mid, 5.0)
        self.assertAlmostEqual(scale_right, 5.0)


if __name__ == "__main__":
    unittest.main()
