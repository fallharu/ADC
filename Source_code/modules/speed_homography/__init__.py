from __future__ import annotations

from typing import Iterable, List

import cv2
import numpy as np
import pandas as pd

from ..speed_y_axis import VerticalContext


def _coerce_points(raw_points: Iterable) -> List[List[float]]:
    if isinstance(raw_points, dict):
        raw_points = raw_points.values()
    if not isinstance(raw_points, (list, tuple)):
        try:
            raw_points = list(raw_points)
        except TypeError:
            return []
    points: List[List[float]] = []
    for pt in raw_points:
        if isinstance(pt, dict):
            x_candidate = pt.get("x")
            y_candidate = pt.get("y")
            try:
                x = float(x_candidate)
                y = float(y_candidate)
            except (TypeError, ValueError):
                continue
            points.append([x, y])
            continue
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            continue
        try:
            x = float(pt[0])
            y = float(pt[1])
        except (TypeError, ValueError):
            continue
        points.append([x, y])
    return points


def _coerce_homography_points(raw_points: Iterable) -> List[List[float]]:
    points = _coerce_points(raw_points)
    return points[:4]


def apply_homography_speed(
    df: pd.DataFrame,
    time_s: pd.Series,
    fps: float,
    frame_window: int,
    homography_meta: dict,
    vertical_context: VerticalContext,
) -> bool:
    points = _coerce_homography_points(homography_meta.get("image_points"))
    width_m = float(homography_meta.get("width_m") or 0)
    length_m = float(homography_meta.get("length_m") or 0)
    if len(points) != 4 or width_m <= 0 or length_m <= 0:
        return False

    image_points = np.array(points, dtype=np.float32)
    world_points = np.array(
        [[0, 0], [width_m, 0], [width_m, length_m], [0, length_m]],
        dtype=np.float32,
    )
    H, status = cv2.findHomography(image_points, world_points, 0)
    if H is None:
        return False

    bottom_points = np.vstack(
        [
            df["smooth_center_x"].fillna(df["center_x"]).to_numpy(dtype=np.float32),
            df["smooth_y2"].fillna(df["y2"]).to_numpy(dtype=np.float32),
            np.ones(len(df), dtype=np.float32),
        ]
    ).T
    mapped = bottom_points @ H.T
    denom = mapped[:, 2]
    world_x = np.full(len(df), np.nan, dtype=float)
    world_y = np.full(len(df), np.nan, dtype=float)
    valid_mask = denom != 0
    world_x[valid_mask] = mapped[valid_mask, 0] / denom[valid_mask]
    world_y[valid_mask] = mapped[valid_mask, 1] / denom[valid_mask]

    df["world_x"] = world_x
    df["world_y"] = world_y
    df["world_dx"] = df.groupby("track_id")["world_x"].diff()
    df["world_dy"] = df.groupby("track_id")["world_y"].diff()
    distance = np.sqrt(df["world_dx"] ** 2 + df["world_dy"] ** 2)

    within_height = (df["world_y"].notna()) & (df["world_y"] >= 0) & (df["world_y"] <= length_m)
    within_width = (df["world_x"].notna()) & (df["world_x"] >= 0) & (df["world_x"] <= width_m)
    valid = (time_s > 0) & distance.notna() & within_height & within_width

    df.loc[valid, "speed_mps"] = distance[valid] / time_s[valid]
    df["speed_km_h"] = df["speed_mps"] * 3.6
    df["travel_direction"] = np.where(df["world_dy"].fillna(0) <= 0, "F", "B")
    df["scale_pixels_per_meter"] = np.nan
    df["speed_diff"] = df.groupby("track_id")["speed_mps"].diff(periods=frame_window)
    df["time_diff_accel"] = df.groupby("track_id")["frame_num"].diff(periods=frame_window) / fps
    valid_accel = df["time_diff_accel"] > 0
    df.loc[valid_accel, "acceleration_m_s2"] = (
        df["speed_diff"][valid_accel] / df["time_diff_accel"][valid_accel]
    )

    if vertical_context.ready:
        fallback_mask = (
            (time_s > 0)
            & within_height
            & (~within_width)
            & vertical_context.ppm_series.notna()
        )
        if vertical_context.range_min is not None and vertical_context.range_max is not None:
            fallback_mask &= (
                (df["center_y"] >= vertical_context.range_min)
                & (df["center_y"] <= vertical_context.range_max)
            )
        if fallback_mask.any():
            distance_pixels = vertical_context.y_delta.abs()
            df.loc[fallback_mask, "y_delta"] = vertical_context.y_delta[fallback_mask]
            df.loc[fallback_mask, "speed_mps"] = (
                (distance_pixels[fallback_mask] / vertical_context.ppm_series[fallback_mask])
                / time_s[fallback_mask]
            )
            df.loc[fallback_mask, "speed_km_h"] = df.loc[fallback_mask, "speed_mps"] * 3.6
            df.loc[fallback_mask, "travel_direction"] = np.where(
                vertical_context.y_delta[fallback_mask].fillna(0) < 0,
                "F",
                "B",
            )
            df.loc[fallback_mask, "scale_pixels_per_meter"] = vertical_context.ppm_series[fallback_mask]
    return True
