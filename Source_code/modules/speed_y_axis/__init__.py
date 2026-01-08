from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class VerticalContext:
    ready: bool
    ppm_series: pd.Series
    y_delta: pd.Series
    range_min: float | None
    range_max: float | None


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


def _collect_vertical_lines(scale_meta: dict) -> List[List[List[float]]]:
    raw_lines = (
        scale_meta.get("y_axis_lines")
        or scale_meta.get("lines")
        or scale_meta.get("vertical_lines")
        or []
    )
    if isinstance(raw_lines, dict):
        candidate_iterable = raw_lines.values()
    else:
        candidate_iterable = raw_lines
    vertical_lines: List[List[List[float]]] = []
    for raw_line in candidate_iterable or []:
        points = _coerce_points(raw_line)
        if points:
            vertical_lines.append(points)
    return sorted(vertical_lines, key=lambda pts: pts[0][1]) if vertical_lines else []


def prepare_vertical_context(df: pd.DataFrame, scale_meta: dict) -> VerticalContext:
    vertical_lines = _collect_vertical_lines(scale_meta)
    vertical_intervals = float(scale_meta.get("num_intervals") or 0)
    known_distance = float(scale_meta.get("known_distance_m") or 0)

    vertical_ready = False
    vertical_ppm_series = pd.Series(np.nan, index=df.index)
    vertical_y_delta = pd.Series(np.nan, index=df.index)
    vertical_range_min = None
    vertical_range_max = None

    if len(vertical_lines) > 1 and vertical_intervals > 0 and known_distance > 0:
        meter_per_interval = known_distance / vertical_intervals
        if meter_per_interval > 0:
            intervals: List[Tuple[float, float, float]] = []
            for start_line, end_line in zip(vertical_lines[:-1], vertical_lines[1:]):
                try:
                    start_pt = start_line[0] if start_line else None
                    end_pt = end_line[0] if end_line else None
                    start_y = float(start_pt[1]) if start_pt and len(start_pt) >= 2 else None
                    end_y = float(end_pt[1]) if end_pt and len(end_pt) >= 2 else None
                except (TypeError, ValueError):
                    start_y = end_y = None
                if start_y is None or end_y is None:
                    continue
                diff = abs(end_y - start_y)
                if diff <= 0:
                    continue
                ppm_value = diff / meter_per_interval
                intervals.append((start_y, end_y, ppm_value))

            if intervals:
                def get_local_scale(y_val: float) -> float:
                    try:
                        y_value = float(y_val)
                    except (TypeError, ValueError):
                        return np.nan
                    for start_y, end_y, ppm_value in intervals:
                        if start_y <= y_value <= end_y or end_y <= y_value <= start_y:
                            return ppm_value
                    first_start, first_end, first_ppm = intervals[0]
                    last_start, last_end, last_ppm = intervals[-1]
                    min_first = min(first_start, first_end)
                    max_last = max(last_start, last_end)
                    if y_value < min_first:
                        return first_ppm
                    if y_value > max_last:
                        return last_ppm
                    return intervals[0][2]

                base_y = df["smooth_center_y"].fillna(df["center_y"])
                vertical_ppm_series = base_y.apply(get_local_scale)
                vertical_y_delta = df.groupby("track_id")["smooth_center_y"].diff()
                all_y = [
                    pt[1]
                    for line in vertical_lines
                    for pt in line
                    if isinstance(pt, (list, tuple)) and len(pt) == 2
                ]
                if all_y:
                    vertical_range_min = min(all_y)
                    vertical_range_max = max(all_y)
                vertical_ready = True

    return VerticalContext(
        ready=vertical_ready,
        ppm_series=vertical_ppm_series,
        y_delta=vertical_y_delta,
        range_min=vertical_range_min,
        range_max=vertical_range_max,
    )


def apply_vertical_speed(
    df: pd.DataFrame,
    time_s: pd.Series,
    fps: float,
    frame_window: int,
    context: VerticalContext,
) -> bool:
    if not context.ready:
        return False

    df["scale_pixels_per_meter"] = context.ppm_series
    df["y_delta"] = context.y_delta
    df["travel_direction"] = np.where(df["y_delta"].fillna(0) < 0, "F", "B")

    distance_pixels = df["y_delta"].abs()
    valid = (time_s > 0) & df["scale_pixels_per_meter"].notna()
    df.loc[valid, "speed_mps"] = (
        (distance_pixels[valid] / df["scale_pixels_per_meter"][valid]) / time_s[valid]
    )
    df["speed_km_h"] = df["speed_mps"] * 3.6
    df["speed_diff"] = df.groupby("track_id")["speed_mps"].diff(periods=frame_window)
    df["time_diff_accel"] = df.groupby("track_id")["frame_num"].diff(periods=frame_window) / fps
    valid_accel = df["time_diff_accel"] > 0
    df.loc[valid_accel, "acceleration_m_s2"] = (
        df["speed_diff"][valid_accel] / df["time_diff_accel"][valid_accel]
    )
    return True
