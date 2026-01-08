import math
import unittest

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover - dependency missing in CI
    pd = None  # type: ignore[assignment]

try:
    from Source_code.modules.measure_points import attach_measure_points
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
