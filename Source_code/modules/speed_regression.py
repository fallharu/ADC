"""Shared rolling-regression helpers for speed estimation."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def rolling_linear_slope(
    frame_num: pd.Series,
    position: pd.Series,
    track_id: pd.Series,
    fps: float,
    lookback_frames: int,
    valid_mask: Optional[pd.Series] = None,
) -> pd.Series:
    """Fit position against time over each trailing frame window.

    ``lookback_frames=6`` covers the inclusive interval ``[n-6, n]``.  At
    30 fps this keeps the former 0.2 second span while using all seven
    available positions rather than only the two endpoints.
    """

    lookback = max(int(lookback_frames), 1)
    fps_value = float(fps)
    if not np.isfinite(fps_value) or fps_value <= 0:
        raise ValueError("fps must be a positive finite value")

    frames = pd.to_numeric(frame_num, errors="coerce")
    positions = pd.to_numeric(position, errors="coerce")
    if valid_mask is None:
        validity = pd.Series(True, index=positions.index)
    else:
        validity = valid_mask.reindex(positions.index, fill_value=False).astype(bool)

    output = pd.Series(np.nan, index=positions.index, dtype=float)
    minimum_points = min(lookback + 1, 3)

    working = pd.DataFrame(
        {
            "frame": frames,
            "position": positions,
            "track": track_id,
            "valid": validity,
        },
        index=positions.index,
    )
    for _track, group in working.groupby("track", sort=False, dropna=False):
        group = group.sort_values("frame")
        group_frames = group["frame"].to_numpy(dtype=float)
        group_positions = group["position"].to_numpy(dtype=float)
        group_valid = group["valid"].to_numpy(dtype=bool)
        if len(group) < minimum_points or not np.isfinite(group_frames[0]):
            continue

        left = 0
        first_frame = group_frames[0]
        for right, current_frame in enumerate(group_frames):
            if not np.isfinite(current_frame) or current_frame - first_frame < lookback:
                continue
            lower_bound = current_frame - lookback
            while left < right and group_frames[left] < lower_bound:
                left += 1

            window_frames = group_frames[left : right + 1]
            window_positions = group_positions[left : right + 1]
            window_valid = (
                group_valid[left : right + 1]
                & np.isfinite(window_frames)
                & np.isfinite(window_positions)
            )
            if window_valid.sum() < minimum_points or not window_valid.all():
                continue

            time_values = window_frames / fps_value
            centered_time = time_values - time_values.mean()
            denominator = float(np.dot(centered_time, centered_time))
            if denominator <= 0:
                continue
            centered_position = window_positions - window_positions.mean()
            slope = float(np.dot(centered_time, centered_position) / denominator)
            output.loc[group.index[right]] = slope

    return output


def integrate_scaled_axis_position(
    axis_value: pd.Series,
    pixels_per_meter: pd.Series,
    track_id: pd.Series,
) -> pd.Series:
    """Integrate image-axis increments into a local signed metric position."""

    axis = pd.to_numeric(axis_value, errors="coerce")
    scale = pd.to_numeric(pixels_per_meter, errors="coerce")
    previous_scale = scale.groupby(track_id).shift(1)
    pair_scale = (scale + previous_scale) / 2.0
    axis_delta = axis.groupby(track_id).diff()
    step_m = axis_delta / pair_scale
    valid_step = (
        axis_delta.notna()
        & pair_scale.notna()
        & np.isfinite(pair_scale)
        & (pair_scale > 0)
    )
    step_m = step_m.where(valid_step)

    position = pd.Series(np.nan, index=axis.index, dtype=float)
    for _track, indices in axis.groupby(track_id, sort=False).groups.items():
        running = 0.0
        previous_was_valid = False
        for index in indices:
            if not np.isfinite(scale.loc[index]) or scale.loc[index] <= 0:
                previous_was_valid = False
                continue
            if not previous_was_valid:
                position.loc[index] = running
                previous_was_valid = True
                continue
            increment = step_m.loc[index]
            if not np.isfinite(increment):
                previous_was_valid = False
                continue
            running += float(increment)
            position.loc[index] = running
    return position
