import math
import unittest

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover - dependency missing in CI
    pd = None  # type: ignore[assignment]

try:
    from Source_code.modules.measure_points import attach_measure_points, stabilize_measure_points
    import numpy as np  # noqa: F401
    HAS_NUMPY = True
except ModuleNotFoundError:
    attach_measure_points = None
    HAS_NUMPY = False


def _vertical_line(x):
    return [[x, 0], [x, 100]]


def _empty_measure_points():
    return pd.DataFrame({
        "frame_num": pd.Series(dtype=float),
        "group_id": pd.Series(dtype=float),
        "measure_x": pd.Series(dtype=float),
        "measure_y": pd.Series(dtype=float),
    })


@unittest.skipUnless(HAS_NUMPY and pd is not None, "requires numpy and pandas")
def test_attach_measure_points_prefers_corner_closest_to_white_line():
    df = pd.DataFrame(
        [
            {
                "frame_num": 0,
                "group_id": 1,
                "x1": 10,
                "y1": 40,
                "x2": 30,
                "y2": 50,
                "model_name": "yolo11",
            }
        ]
    )
    tyre_points = _empty_measure_points()
    result = attach_measure_points(
        df,
        tyre_points,
        left_line=_vertical_line(12),
        right_line=_vertical_line(100),
    )

    assert math.isclose(result.loc[0, "measure_x"], 10.0)
    assert math.isclose(result.loc[0, "measure_y"], 50.0)


@unittest.skipUnless(HAS_NUMPY and pd is not None, "requires numpy and pandas")
def test_attach_measure_points_falls_back_to_bbox_when_no_lines():
    df = pd.DataFrame(
        [
            {
                "frame_num": 0,
                "group_id": 1,
                "x1": 10,
                "y1": 40,
                "x2": 30,
                "y2": 50,
                "model_name": "yolo11",
            }
        ]
    )
    tyre_points = _empty_measure_points()
    result = attach_measure_points(df, tyre_points)

    assert math.isclose(result.loc[0, "measure_x"], 30.0)
    assert math.isclose(result.loc[0, "measure_y"], 50.0)


@unittest.skipUnless(HAS_NUMPY and pd is not None, "requires numpy and pandas")
def test_stabilize_measure_points_removes_bbox_size_jitter_and_keeps_curve():
    frame = np.arange(61, dtype=float)
    true_center_x = 200.0 + 1.2 * frame + 0.025 * (frame - 30.0) ** 2
    true_center_y = 100.0 + 2.0 * frame + 0.01 * frame**2
    true_width = 40.0 + 0.25 * frame
    true_height = 24.0 + 0.16 * frame

    alternating = np.where(frame.astype(int) % 2 == 0, 1.0, -1.0)
    observed_center_x = true_center_x + 0.7 * np.sin(2.0 * np.pi * frame / 3.0)
    observed_center_y = true_center_y + 0.6 * np.cos(2.0 * np.pi * frame / 3.0)
    observed_width = true_width + 6.0 * alternating
    observed_height = true_height - 5.0 * alternating

    data = pd.DataFrame(
        {
            "track_id": 1,
            "frame_num": frame,
            "x1": observed_center_x - observed_width / 2.0,
            "x2": observed_center_x + observed_width / 2.0,
            "y1": observed_center_y - observed_height / 2.0,
            "y2": observed_center_y + observed_height / 2.0,
        }
    )
    data["measure_x"] = data["x2"]
    data["measure_y"] = data["y2"]

    result = stabilize_measure_points(data, window=11)
    true_measure_x = true_center_x + true_width / 2.0
    true_measure_y = true_center_y + true_height / 2.0
    raw_rmse = np.sqrt(
        np.mean(
            (data["measure_x"].to_numpy() - true_measure_x) ** 2
            + (data["measure_y"].to_numpy() - true_measure_y) ** 2
        )
    )
    smooth_rmse = np.sqrt(
        np.mean(
            (result["smooth_measure_x"].to_numpy() - true_measure_x) ** 2
            + (result["smooth_measure_y"].to_numpy() - true_measure_y) ** 2
        )
    )

    self_curve = np.polyfit(frame, result["smooth_measure_x"], 2)[0]
    expected_curve = np.polyfit(frame, true_measure_x, 2)[0]
    assert smooth_rmse < raw_rmse * 0.35
    assert abs(self_curve - expected_curve) < 0.003
    assert np.allclose(result["smooth_measure_anchor_u"], 0.5, atol=1e-8)
    assert np.allclose(result["smooth_measure_anchor_v"], 0.5, atol=1e-8)
