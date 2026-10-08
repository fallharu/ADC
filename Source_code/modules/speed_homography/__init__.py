from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

import cv2
import numpy as np
import pandas as pd

from ..speed_regression import integrate_scaled_axis_position, rolling_linear_slope
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
    return _coerce_points(raw_points)


def _coerce_camera_parameters(camera_meta: Optional[dict]) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    if not isinstance(camera_meta, dict):
        return None, None
    raw_matrix = camera_meta.get("camera_matrix") or camera_meta.get("matrix")
    raw_distortion = camera_meta.get("dist_coeffs") or camera_meta.get("distortion_coefficients")
    try:
        matrix = np.asarray(raw_matrix, dtype=np.float64)
        distortion = np.asarray(raw_distortion, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError):
        return None, None
    if matrix.shape != (3, 3) or distortion.size < 4:
        return None, None
    if not np.isfinite(matrix).all() or not np.isfinite(distortion).all():
        return None, None
    return matrix, distortion


def _undistort_points(points: np.ndarray, camera_meta: Optional[dict]) -> np.ndarray:
    matrix, distortion = _coerce_camera_parameters(camera_meta)
    if matrix is None or distortion is None:
        return points.astype(np.float32, copy=False)

    shaped = points.astype(np.float64).reshape(-1, 1, 2)
    model = str((camera_meta or {}).get("model") or "standard").strip().lower()
    try:
        if model in {"fisheye", "fish_eye"}:
            corrected = cv2.fisheye.undistortPoints(shaped, matrix, distortion[:4], P=matrix)
        else:
            corrected = cv2.undistortPoints(shaped, matrix, distortion, P=matrix)
    except cv2.error:
        return points.astype(np.float32, copy=False)
    return corrected.reshape(-1, 2).astype(np.float32)


def _coerce_longitudinal_correction(homography_meta: dict) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    correction = homography_meta.get("longitudinal_correction") or {}
    if not isinstance(correction, dict):
        return None, None

    raw_positions = (
        correction.get("estimated_positions_m")
        or correction.get("raw_positions_m")
        or correction.get("input_m")
    )
    corrected_positions = correction.get("corrected_positions_m") or correction.get("output_m")
    if raw_positions is None or corrected_positions is None:
        samples = correction.get("samples") or []
        if isinstance(samples, (list, tuple)):
            raw_positions = []
            corrected_positions = []
            for sample in samples:
                if not isinstance(sample, dict):
                    continue
                raw_positions.append(sample.get("estimated_m", sample.get("raw_m")))
                corrected_positions.append(sample.get("corrected_m"))

    try:
        raw = np.asarray(raw_positions, dtype=float).reshape(-1)
        corrected = np.asarray(corrected_positions, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return None, None
    if raw.size < 2 or raw.size != corrected.size:
        return None, None

    valid = np.isfinite(raw) & np.isfinite(corrected)
    raw, corrected = raw[valid], corrected[valid]
    if raw.size < 2:
        return None, None
    order = np.argsort(raw)
    raw, corrected = raw[order], corrected[order]
    unique_raw, unique_indices = np.unique(raw, return_index=True)
    corrected = corrected[unique_indices]
    if unique_raw.size < 2 or np.any(np.diff(corrected) <= 0):
        return None, None
    return unique_raw, corrected


def _derive_line_correction(
    calibration_lines: Optional[Iterable],
    interval_m: float,
    homography: np.ndarray,
    camera_meta: Optional[dict],
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    if not calibration_lines or interval_m <= 0:
        return None, None
    midpoints: List[List[float]] = []
    for raw_line in calibration_lines:
        line = _coerce_points(raw_line)
        if len(line) < 2:
            continue
        midpoint = np.mean(np.asarray(line, dtype=float), axis=0)
        midpoints.append([float(midpoint[0]), float(midpoint[1])])
    if len(midpoints) < 2:
        return None, None

    image_points = _undistort_points(np.asarray(midpoints, dtype=np.float32), camera_meta)
    homogeneous = np.column_stack(
        [image_points, np.ones(len(image_points), dtype=np.float32)]
    )
    mapped = homogeneous @ homography.T
    denominator = mapped[:, 2]
    valid = np.isfinite(denominator) & (~np.isclose(denominator, 0))
    raw_positions = mapped[valid, 1] / denominator[valid]
    raw_positions = np.unique(np.sort(raw_positions[np.isfinite(raw_positions)]))
    if raw_positions.size < 2:
        return None, None

    corrected_positions = raw_positions[0] + np.arange(raw_positions.size, dtype=float) * interval_m
    return raw_positions, corrected_positions


def _apply_position_map(
    values: np.ndarray,
    raw: Optional[np.ndarray],
    corrected: Optional[np.ndarray],
) -> np.ndarray:
    if raw is None or corrected is None:
        return values
    result = values.copy()
    covered = np.isfinite(values) & (values >= raw[0]) & (values <= raw[-1])
    result[covered] = np.interp(values[covered], raw, corrected)
    below = np.isfinite(values) & (values < raw[0])
    above = np.isfinite(values) & (values > raw[-1])
    result[below] = values[below] + (corrected[0] - raw[0])
    result[above] = values[above] + (corrected[-1] - raw[-1])
    return result


class HomographyProjection:
    """The road coordinate transform shared by speed estimation and its preview."""

    def __init__(self, homography_meta, camera_meta=None, calibration_lines=None):
        points = _coerce_homography_points(homography_meta.get("image_points"))
        self.width_m = float(homography_meta.get("width_m") or 0)
        self.length_m = float(homography_meta.get("length_m") or 0)
        if (len(points) < 4 or not np.isfinite(points).all()
                or not np.isfinite([self.width_m, self.length_m]).all()
                or self.width_m <= 0 or self.length_m <= 0):
            raise ValueError("画像上の4点と正の実寸を指定してください。")
        world_points = _coerce_points(homography_meta.get("world_points") or [])
        if len(world_points) != len(points):
            if len(points) != 4:
                raise ValueError("画像点と実座標の数が一致しません。")
            world_points = [[0, 0], [self.width_m, 0],
                            [self.width_m, self.length_m], [0, self.length_m]]
        if not np.isfinite(world_points).all():
            raise ValueError("実座標が不正です。")
        self.camera_meta = camera_meta
        self.camera_matrix, self.distortion = _coerce_camera_parameters(camera_meta)
        # Invalid camera parameters have historically meant no lens correction.
        # Decide once so that forward and inverse mappings use the same model.
        if self.camera_matrix is not None:
            try:
                np.linalg.inv(self.camera_matrix)
                probe = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
                if self.is_fisheye:
                    cv2.fisheye.undistortPoints(probe, self.camera_matrix, self.distortion[:4], P=self.camera_matrix)
                else:
                    cv2.undistortPoints(probe, self.camera_matrix, self.distortion, P=self.camera_matrix)
            except (cv2.error, np.linalg.LinAlgError):
                self.camera_matrix = self.distortion = None
                self.camera_meta = None
        image_points = _undistort_points(np.asarray(points, dtype=np.float32), self.camera_meta)
        method = cv2.RANSAC if len(points) > 4 else 0
        threshold = float(homography_meta.get("ransac_reproj_threshold_px") or 3.0)
        self.H, _ = cv2.findHomography(image_points, np.asarray(world_points, dtype=np.float32), method, threshold)
        if self.H is None or not np.isfinite(self.H).all():
            raise ValueError("射影を計算できません。4点の配置を確認してください。")
        try:
            self.inverse_H = np.linalg.inv(self.H)
        except np.linalg.LinAlgError as exc:
            raise ValueError("射影を計算できません。4点の配置を確認してください。") from exc
        self.raw_positions, self.corrected_positions = _coerce_longitudinal_correction(homography_meta)
        if self.raw_positions is None:
            self.raw_positions, self.corrected_positions = _derive_line_correction(
                calibration_lines, float(homography_meta.get("interval_m") or 0),
                self.H, self.camera_meta,
            )

    @property
    def is_fisheye(self):
        return str((self.camera_meta or {}).get("model") or "standard").strip().lower() in {"fisheye", "fish_eye"}

    def correct_y(self, values):
        return _apply_position_map(np.asarray(values, dtype=float), self.raw_positions, self.corrected_positions)

    @staticmethod
    def _project(points, matrix):
        homogeneous = np.column_stack([points, np.ones(len(points))]) @ matrix.T
        result = np.full((len(points), 2), np.nan)
        valid = np.isfinite(homogeneous).all(axis=1) & (homogeneous[:, 2] != 0)
        result[valid] = homogeneous[valid, :2] / homogeneous[valid, 2:3]
        return result

    def image_to_world(self, points, corrected=True):
        points = _undistort_points(np.asarray(points, dtype=np.float32).reshape(-1, 2), self.camera_meta)
        world = self._project(points, self.H)
        if corrected:
            world[:, 1] = self.correct_y(world[:, 1])
        return world

    def world_to_image(self, points):
        world = np.asarray(points, dtype=float).reshape(-1, 2).copy()
        world[:, 1] = _apply_position_map(world[:, 1], self.corrected_positions, self.raw_positions)
        pixels = self._project(world, self.inverse_H)
        if self.camera_matrix is None:
            return pixels
        normalized = self._project(pixels, np.linalg.inv(self.camera_matrix))
        if self.is_fisheye:
            distorted = cv2.fisheye.distortPoints(
                normalized.reshape(-1, 1, 2), self.camera_matrix, self.distortion[:4],
            )
        else:
            # Python's projectPoints also allocates a Jacobian. Bound that allocation
            # when inverse-mapping a large preview rather than a handful of tracks.
            distorted = np.empty_like(normalized)
            for start in range(0, len(normalized), 16384):
                batch = normalized[start:start + 16384]
                rays = np.column_stack([batch, np.ones(len(batch))])
                projected, _ = cv2.projectPoints(
                    rays, np.zeros(3), np.zeros(3), self.camera_matrix, self.distortion,
                )
                distorted[start:start + len(batch)] = projected.reshape(-1, 2)
        return distorted.reshape(-1, 2)


def apply_homography_speed(
    df: pd.DataFrame,
    time_s: pd.Series,
    fps: float,
    frame_window: int,
    homography_meta: dict,
    vertical_context: VerticalContext,
    camera_meta: Optional[dict] = None,
    speed_window_frames: int = 1,
    calibration_lines: Optional[Iterable] = None,
) -> bool:
    try:
        projection = HomographyProjection(homography_meta, camera_meta, calibration_lines)
    except (ValueError, TypeError, cv2.error):
        return False
    width_m, length_m = projection.width_m, projection.length_m

    x_column = "smooth_measure_x" if "smooth_measure_x" in df.columns else "smooth_center_x"
    y_column = "smooth_measure_y" if "smooth_measure_y" in df.columns else "smooth_y2"
    fallback_x = "measure_x" if "measure_x" in df.columns else "center_x"
    fallback_y = "measure_y" if "measure_y" in df.columns else "y2"
    image_measurements = np.column_stack(
        [
            df[x_column].fillna(df[fallback_x]).to_numpy(dtype=np.float32),
            df[y_column].fillna(df[fallback_y]).to_numpy(dtype=np.float32),
        ]
    )
    world = projection.image_to_world(image_measurements, corrected=False)
    world_x, world_y = world[:, 0], world[:, 1]

    df["world_x"] = world_x
    df["world_y_raw"] = world_y
    df["world_y"] = projection.correct_y(world_y)
    speed_window_frames = max(int(speed_window_frames), 1)
    df["world_dx"] = df.groupby("track_id")["world_x"].diff(periods=speed_window_frames)
    df["world_dy"] = df.groupby("track_id")["world_y"].diff(periods=speed_window_frames)

    boundary_tolerance = 1e-6
    within_height = (
        df["world_y_raw"].notna()
        & (df["world_y_raw"] >= -boundary_tolerance)
        & (df["world_y_raw"] <= length_m + boundary_tolerance)
    )
    within_width = (
        df["world_x"].notna()
        & (df["world_x"] >= -boundary_tolerance)
        & (df["world_x"] <= width_m + boundary_tolerance)
    )
    primary_point_valid = within_height & within_width
    world_vx_mps = rolling_linear_slope(
        df["frame_num"],
        df["world_x"],
        df["track_id"],
        fps,
        speed_window_frames,
        valid_mask=primary_point_valid,
    )
    world_vy_mps = rolling_linear_slope(
        df["frame_num"],
        df["world_y"],
        df["track_id"],
        fps,
        speed_window_frames,
        valid_mask=primary_point_valid,
    )
    distance_mode = str(homography_meta.get("speed_distance_mode") or "longitudinal").lower()
    if distance_mode in {"euclidean", "xy", "total"}:
        regressed_speed_mps = np.hypot(world_vx_mps, world_vy_mps)
    else:
        regressed_speed_mps = world_vy_mps.abs()
    valid = regressed_speed_mps.notna()

    df.loc[valid, "speed_mps"] = regressed_speed_mps[valid]
    df["speed_km_h"] = df["speed_mps"] * 3.6
    df["travel_direction"] = np.where(world_vy_mps.fillna(0) <= 0, "F", "B")
    df["scale_pixels_per_meter"] = np.nan
    df["speed_diff"] = df.groupby("track_id")["speed_mps"].diff(periods=frame_window)
    df["time_diff_accel"] = df.groupby("track_id")["frame_num"].diff(periods=frame_window) / fps
    valid_accel = df["time_diff_accel"] > 0
    df.loc[valid_accel, "acceleration_m_s2"] = (
        df["speed_diff"][valid_accel] / df["time_diff_accel"][valid_accel]
    )

    if vertical_context.ready:
        vertical_point_valid = (
            within_height
            & (~within_width)
            & vertical_context.ppm_series.notna()
        )
        if vertical_context.range_min is not None and vertical_context.range_max is not None:
            vertical_point_valid &= (
                (df["center_y"] >= vertical_context.range_min)
                & (df["center_y"] <= vertical_context.range_max)
            )
        y_source = df[y_column].fillna(df[fallback_y])
        vertical_position_m = integrate_scaled_axis_position(
            y_source,
            vertical_context.ppm_series,
            df["track_id"],
        )
        vertical_velocity_mps = rolling_linear_slope(
            df["frame_num"],
            vertical_position_m,
            df["track_id"],
            fps,
            speed_window_frames,
            valid_mask=vertical_point_valid & vertical_position_m.notna(),
        )
        fallback_mask = vertical_velocity_mps.notna()
        if fallback_mask.any():
            fallback_delta = y_source.groupby(df["track_id"]).diff(periods=speed_window_frames)
            df.loc[fallback_mask, "y_delta"] = fallback_delta[fallback_mask]
            df.loc[fallback_mask, "speed_mps"] = vertical_velocity_mps[fallback_mask].abs()
            df.loc[fallback_mask, "speed_km_h"] = df.loc[fallback_mask, "speed_mps"] * 3.6
            df.loc[fallback_mask, "travel_direction"] = np.where(
                vertical_velocity_mps[fallback_mask] < 0,
                "F",
                "B",
            )
            df.loc[fallback_mask, "scale_pixels_per_meter"] = vertical_context.ppm_series[fallback_mask]
    return True
