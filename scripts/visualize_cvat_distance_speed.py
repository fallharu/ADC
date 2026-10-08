"""Visualize calibrated distance and speed for smoothed CVAT tracks."""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import cv2  # noqa: E402
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.optimize import isotonic_regression  # noqa: E402

from scripts.analyze_cvat_measurement_smoothing import (  # noqa: E402
    add_legacy_smoothing,
    add_measure_points,
    mark_active_motion,
    read_cvat_tracks,
)
from Source_code.modules.manual_metrics import (  # noqa: E402
    LANE_WIDTH_METERS,
    lane_scale_details_at_y,
    load_white_lines,
)
from Source_code.modules.measure_points import stabilize_measure_points  # noqa: E402
from Source_code.modules.speed_regression import rolling_linear_slope  # noqa: E402


INK = "#172033"
MUTED = "#687386"
GRID = "#DDE3EC"
BLUE = "#2F6FED"
ORANGE = "#F08C46"
GREEN = "#20A474"
RED = "#D95852"
PURPLE = "#7950B3"
SURFACE = "#F6F8FC"


def _scale_line(line, scale_x: float, scale_y: float):
    scaled = []
    for point in line or []:
        if isinstance(point, dict):
            updated = dict(point)
            updated["x"] = float(point["x"]) * scale_x
            updated["y"] = float(point["y"]) * scale_y
            scaled.append(updated)
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            scaled.append([float(point[0]) * scale_x, float(point[1]) * scale_y])
    return scaled


def scale_calibration_geometry(
    calibration: dict,
    scale_x: float,
    scale_y: float,
) -> dict:
    """Scale legacy 1920x1080 calibration coordinates to the source video."""

    result = copy.deepcopy(calibration)
    lines = result.get("lines") or {}
    for name, line in list(lines.items()):
        if isinstance(line, (list, tuple)):
            lines[name] = _scale_line(line, scale_x, scale_y)

    scale = result.get("scale") or {}
    for key in ("lines", "y_axis_lines", "vertical_lines"):
        collection = scale.get(key)
        if isinstance(collection, list):
            scale[key] = [_scale_line(line, scale_x, scale_y) for line in collection]
    homography = scale.get("homography") or {}
    if isinstance(homography.get("image_points"), list):
        homography["image_points"] = _scale_line(
            homography["image_points"],
            scale_x,
            scale_y,
        )
    return result


def _coerce_line_points(line) -> list[tuple[float, float]]:
    points = []
    for point in line or []:
        if isinstance(point, dict):
            x, y = point.get("x"), point.get("y")
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            x, y = point[0], point[1]
        else:
            continue
        try:
            points.append((float(x), float(y)))
        except (TypeError, ValueError):
            continue
    return points


def _line_y_at_x(line, x_value: float) -> float:
    points = _coerce_line_points(line)
    if not points:
        return float("nan")
    if len(points) == 1:
        return points[0][1]
    points.sort(key=lambda point: point[0])
    x = np.array([point[0] for point in points], dtype=float)
    y = np.array([point[1] for point in points], dtype=float)
    return float(np.interp(float(x_value), x, y))


class VerticalLadder:
    def __init__(self, scale: dict):
        raw_lines = scale.get("y_axis_lines") or scale.get("lines") or []
        self.lines = sorted(
            [line for line in raw_lines if _coerce_line_points(line)],
            key=lambda line: _coerce_line_points(line)[0][1],
        )
        intervals = float(scale.get("num_intervals") or 0)
        known_distance = float(scale.get("known_distance_m") or 0)
        self.meters_per_rung = known_distance / intervals if intervals > 0 else 0.0
        self.ready = len(self.lines) >= 2 and self.meters_per_rung > 0

    @property
    def calibrated_length_m(self) -> float:
        return self.meters_per_rung * max(len(self.lines) - 1, 0)

    def position_m(self, x_value: float, y_value: float) -> float:
        if not self.ready or not np.isfinite(x_value) or not np.isfinite(y_value):
            return float("nan")
        rung_y = np.array([_line_y_at_x(line, x_value) for line in self.lines], dtype=float)
        if not np.all(np.isfinite(rung_y)):
            return float("nan")
        order = np.argsort(rung_y)
        rung_y = rung_y[order]
        if y_value < rung_y[0] or y_value > rung_y[-1]:
            return float("nan")
        upper = int(np.searchsorted(rung_y, y_value, side="right"))
        if upper == 0:
            return 0.0
        if upper >= len(rung_y):
            return self.calibrated_length_m
        lower = upper - 1
        span = rung_y[upper] - rung_y[lower]
        fraction = 0.0 if span <= 0 else (y_value - rung_y[lower]) / span
        return float((lower + fraction) * self.meters_per_rung)


class LanePerspectiveModel:
    """Estimate road-plane depth from inverse apparent lane width."""

    def __init__(self, calibration: dict, ladder: VerticalLadder):
        self.lines = load_white_lines(calibration)
        self.lane_width_m = float(calibration.get("lane_width_m") or LANE_WIDTH_METERS)
        rung_y = np.array(
            [float(_coerce_line_points(line)[0][1]) for line in ladder.lines],
            dtype=float,
        )
        widths = np.array([self._lane_width_px(y_value) for y_value in rung_y], dtype=float)
        depth = np.arange(len(rung_y) - 1, -1, -1, dtype=float) * ladder.meters_per_rung
        valid = np.isfinite(widths) & (widths > 0)
        design = np.column_stack([1.0 / widths[valid], np.ones(valid.sum())])
        self.coefficient, self.intercept = np.linalg.lstsq(
            design,
            depth[valid],
            rcond=None,
        )[0]
        predicted = self.coefficient / widths[valid] + self.intercept
        residual = predicted - depth[valid]
        self.fit_rmse_m = float(np.sqrt(np.mean(residual**2)))
        self.fit_max_error_m = float(np.max(np.abs(residual)))
        self.ready = valid.sum() >= 3

    def _details(self, y_value: float):
        return lane_scale_details_at_y(
            float(y_value),
            self.lines.left,
            self.lines.right,
            center_line=self.lines.center,
            left_inner_line=self.lines.left_inner,
            right_inner_line=self.lines.right_inner,
            lane_width_m=self.lane_width_m,
        )

    def _lane_width_px(self, y_value: float) -> float:
        width = self._details(y_value).lane_width_px
        return float(width) if width is not None else float("nan")

    def world_point(self, x_value: float, y_value: float) -> tuple[float, float]:
        if not self.ready or not np.isfinite(x_value) or not np.isfinite(y_value):
            return float("nan"), float("nan")
        details = self._details(y_value)
        if not details.is_available or details.left_point is None or details.right_point is None:
            return float("nan"), float("nan")
        left_x = float(details.left_point[0])
        right_x = float(details.right_point[0])
        width = abs(right_x - left_x)
        if width <= 0:
            return float("nan"), float("nan")
        low_x = min(left_x, right_x)
        lateral = (float(x_value) - low_x) / width * self.lane_width_m
        depth = self.coefficient / width + self.intercept
        if not np.isfinite(depth) or depth < 0:
            return float("nan"), float("nan")
        return float(lateral), float(depth)


def add_calibrated_positions(
    frame: pd.DataFrame,
    ladder: VerticalLadder,
    perspective: LanePerspectiveModel,
) -> pd.DataFrame:
    result = frame.copy()
    point_columns = {
        "raw": ("measure_x", "measure_y"),
        "legacy": ("legacy_measure_x", "legacy_measure_y"),
        "smooth": ("smooth_measure_x", "smooth_measure_y"),
    }
    for name, (x_column, y_column) in point_columns.items():
        result[f"{name}_strict_position_m"] = [
            ladder.position_m(x_value, y_value)
            for x_value, y_value in zip(result[x_column], result[y_column])
        ]
        world = [
            perspective.world_point(x_value, y_value)
            if active else (float("nan"), float("nan"))
            for x_value, y_value, active in zip(
                result[x_column],
                result[y_column],
                result["active_motion"],
            )
        ]
        result[f"{name}_lateral_m"] = [point[0] for point in world]
        result[f"{name}_depth_m"] = [point[1] for point in world]
    return result


def add_lateral_distance(frame: pd.DataFrame, lane_width_m: float) -> pd.DataFrame:
    result = frame.copy()
    result["left_line_distance_m"] = result["smooth_lateral_m"].abs()
    result["right_line_distance_m"] = (lane_width_m - result["smooth_lateral_m"]).abs()
    result["nearest_line_distance_m"] = result[
        ["left_line_distance_m", "right_line_distance_m"]
    ].min(axis=1, skipna=True)
    missing = result["smooth_lateral_m"].isna()
    result.loc[missing, "nearest_line_distance_m"] = np.nan
    return result


def enforce_monotonic_depth(frame: pd.DataFrame) -> pd.DataFrame:
    """Remove calibration-segment backtracking from one-way vehicle motion."""

    result = frame.copy()
    for name in ("raw", "legacy", "smooth"):
        column = f"{name}_depth_m"
        result[f"{name}_depth_unconstrained_m"] = result[column]
        for _track_id, track in result[result["active_motion"]].groupby("track_id", sort=False):
            valid = track[track[column].notna()].sort_values("frame_num")
            if len(valid) < 2:
                continue
            frame_gap = valid["frame_num"].diff().fillna(1).ne(1).cumsum()
            for _segment_id, segment in valid.groupby(frame_gap, sort=False):
                if len(segment) < 2:
                    continue
                values = segment[column].to_numpy(dtype=float)
                increasing = bool(values[-1] >= values[0])
                fitted = isotonic_regression(values, increasing=increasing).x
                result.loc[segment.index, column] = fitted
    return result


def add_speed_columns(frame: pd.DataFrame, fps: float, seconds: float = 0.2) -> pd.DataFrame:
    result = frame.copy()
    period = max(int(round(fps * seconds)), 1)
    for name in ("raw", "legacy", "smooth"):
        frame_delta = result.groupby("track_id")["frame_num"].diff(periods=period)
        depth_delta = result.groupby("track_id")[f"{name}_depth_m"].diff(periods=period)
        elapsed = frame_delta / fps
        endpoint_speed = depth_delta.abs() / elapsed * 3.6
        endpoint_speed[(elapsed <= 0) | result[f"{name}_depth_m"].isna()] = np.nan
        result[f"{name}_endpoint_speed_km_h"] = endpoint_speed

        velocity_mps = rolling_linear_slope(
            result["frame_num"],
            result[f"{name}_depth_m"],
            result["track_id"],
            fps,
            period,
            valid_mask=result["active_motion"] & result[f"{name}_depth_m"].notna(),
        )
        speed = velocity_mps.abs() * 3.6
        if name == "smooth":
            speed = speed.groupby(result["track_id"]).transform(
                lambda values: values.rolling(5, center=True, min_periods=1).median()
            )
        result[f"{name}_speed_km_h"] = speed
    return result


def speed_roughness(speed: pd.Series) -> float:
    values = pd.to_numeric(speed, errors="coerce").dropna().to_numpy(dtype=float)
    if len(values) < 2:
        return np.nan
    return float(np.sqrt(np.mean(np.diff(values) ** 2)))


def build_summary(frame: pd.DataFrame, fps: float) -> pd.DataFrame:
    rows = []
    for track_id, track in frame[frame["active_motion"]].groupby("track_id", sort=True):
        valid = track[track["smooth_depth_m"].notna()].copy()
        strict_valid = track[track["smooth_strict_position_m"].notna()]
        speed = valid["smooth_speed_km_h"].dropna()
        endpoint_roughness = speed_roughness(valid["smooth_endpoint_speed_km_h"])
        regression_roughness = speed_roughness(valid["smooth_speed_km_h"])
        if np.isfinite(endpoint_roughness) and endpoint_roughness > 0:
            roughness_reduction_pct = 100.0 * (1.0 - regression_roughness / endpoint_roughness)
        else:
            roughness_reduction_pct = np.nan
        if len(valid) > 1:
            depth = valid["smooth_depth_m"].to_numpy(dtype=float)
            frames = valid["frame_num"].to_numpy(dtype=int)
            consecutive = np.diff(frames) == 1
            step_distance = np.abs(np.diff(depth))
            traveled = float(step_distance[consecutive].sum())
            duration = float((frames[-1] - frames[0]) / fps)
        else:
            traveled = 0.0
            duration = 0.0
        lateral = pd.to_numeric(track["nearest_line_distance_m"], errors="coerce").dropna()
        rows.append(
            {
                "track_id": int(track_id),
                "label": track["label"].iloc[0],
                "active_frames": len(track),
                "calibrated_frames": len(valid),
                "calibrated_coverage_pct": 100.0 * len(valid) / max(len(track), 1),
                "strict_calibrated_frames": len(strict_valid),
                "strict_calibrated_coverage_pct": 100.0 * len(strict_valid) / max(len(track), 1),
                "calibrated_duration_s": duration,
                "depth_span_m": float(valid["smooth_depth_m"].max() - valid["smooth_depth_m"].min()) if len(valid) else np.nan,
                "traveled_distance_m": traveled,
                "median_speed_km_h": float(speed.median()) if len(speed) else np.nan,
                "max_speed_km_h": float(speed.max()) if len(speed) else np.nan,
                "endpoint_speed_roughness_km_h": endpoint_roughness,
                "regression_speed_roughness_km_h": regression_roughness,
                "roughness_reduction_pct": roughness_reduction_pct,
                "median_nearest_line_distance_m": float(lateral.median()) if len(lateral) else np.nan,
                "min_nearest_line_distance_m": float(lateral.min()) if len(lateral) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def style_axis(axis: plt.Axes) -> None:
    axis.set_facecolor("white")
    axis.grid(True, color=GRID, linewidth=0.8, alpha=0.85)
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color(GRID)
    axis.tick_params(colors=MUTED, labelsize=8.5)


def draw_visualization(
    frame: pd.DataFrame,
    summary: pd.DataFrame,
    fps: float,
    ladder: VerticalLadder,
    perspective: LanePerspectiveModel,
    output_path: str,
) -> int:
    eligible = summary[summary["calibrated_frames"] > 6]
    if eligible.empty:
        raise ValueError("No track has enough observations inside the calibrated distance range")
    focus_id = int(eligible.sort_values("calibrated_frames", ascending=False).iloc[0]["track_id"])
    focus = frame[(frame["track_id"] == focus_id) & frame["active_motion"]].copy()
    valid = focus[focus["smooth_depth_m"].notna()].copy()
    start_frame = int(valid["frame_num"].iloc[0])
    valid["relative_time_s"] = (valid["frame_num"] - start_frame) / fps
    valid["traveled_distance_m"] = (
        valid["smooth_depth_m"].diff().abs().fillna(0).cumsum()
    )
    focus_metrics = summary[summary["track_id"] == focus_id].iloc[0]

    plt.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "DejaVu Sans"]
    fig, axes = plt.subplots(2, 3, figsize=(17, 9.5), dpi=160, facecolor=SURFACE)
    colors = [BLUE, ORANGE, GREEN, PURPLE, RED]

    axis = axes[0, 0]
    style_axis(axis)
    for color, (track_id, track) in zip(colors, frame[frame["active_motion"]].groupby("track_id", sort=True)):
        calibrated = track[track["smooth_depth_m"].notna()]
        if calibrated.empty:
            continue
        axis.plot(
            calibrated["frame_num"] / fps,
            calibrated["smooth_depth_m"],
            color=color,
            linewidth=1.8,
            label=f"Track {track_id} / {track['label'].iloc[0]}",
        )
    axis.set_xlabel("動画時刻 (秒)", color=MUTED)
    axis.set_ylabel("奥行き推定 (m)", color=MUTED)
    axis.set_title("全トラックの縦距離（参考推定）", loc="left", color=INK, fontweight="bold")
    axis.legend(frameon=False, fontsize=7.5)

    axis = axes[0, 1]
    style_axis(axis)
    axis.plot(valid["relative_time_s"], valid["raw_depth_m"], color=MUTED, alpha=0.55, label="CVAT測定点")
    axis.plot(valid["relative_time_s"], valid["legacy_depth_m"], color=ORANGE, linewidth=1.5, label="従来中央値")
    axis.plot(valid["relative_time_s"], valid["smooth_depth_m"], color=GREEN, linewidth=2.1, label="BBOX分解")
    axis.set_xlabel("推定開始からの時間 (秒)", color=MUTED)
    axis.set_ylabel("奥行き (m)", color=MUTED)
    axis.set_title(f"距離–時間 — Track {focus_id}", loc="left", color=INK, fontweight="bold")
    axis.legend(frameon=False, fontsize=7.5)

    axis = axes[0, 2]
    style_axis(axis)
    axis.plot(
        valid["relative_time_s"],
        valid["smooth_endpoint_speed_km_h"],
        color=MUTED,
        alpha=0.6,
        linewidth=1.1,
        label="従来：窓の両端2点差分",
    )
    axis.plot(valid["relative_time_s"], valid["legacy_speed_km_h"], color=ORANGE, linewidth=1.4, label="中央値測定点＋窓内回帰")
    axis.plot(valid["relative_time_s"], valid["smooth_speed_km_h"], color=GREEN, linewidth=2.1, label="BBOX分解＋窓内回帰")
    axis.set_xlabel("推定開始からの時間 (秒)", color=MUTED)
    axis.set_ylabel("速度 (km/h)", color=MUTED)
    axis.set_title("速度–時間（0.2秒窓・全点回帰）", loc="left", color=INK, fontweight="bold")
    axis.legend(frameon=False, fontsize=7.5)

    axis = axes[1, 0]
    style_axis(axis)
    axis.plot(valid["relative_time_s"], valid["traveled_distance_m"], color=BLUE, linewidth=2.2)
    axis.set_xlabel("校正区間へ入ってからの時間 (秒)", color=MUTED)
    axis.set_ylabel("累積移動距離 (m)", color=MUTED)
    axis.set_title("縦方向の累積移動距離", loc="left", color=INK, fontweight="bold")
    axis.text(
        0.03,
        0.94,
        f"距離 {focus_metrics['traveled_distance_m']:.2f} m\n"
        f"中央値速度 {focus_metrics['median_speed_km_h']:.2f} km/h\n"
        f"最大速度 {focus_metrics['max_speed_km_h']:.2f} km/h\n"
        f"速度がたつき低減 {focus_metrics['roughness_reduction_pct']:.1f}%",
        transform=axis.transAxes,
        va="top",
        color=MUTED,
        fontsize=9,
    )

    axis = axes[1, 1]
    style_axis(axis)
    for color, (track_id, track) in zip(colors, frame[frame["active_motion"]].groupby("track_id", sort=True)):
        time = (track["frame_num"] - track["frame_num"].iloc[0]) / fps
        axis.plot(time, track["nearest_line_distance_m"], color=color, linewidth=1.5, label=f"Track {track_id}")
    axis.set_xlabel("各トラック開始からの時間 (秒)", color=MUTED)
    axis.set_ylabel("最寄り白線までの距離 (m)", color=MUTED)
    axis.set_title("横方向距離（全有効区間）", loc="left", color=INK, fontweight="bold")
    axis.legend(frameon=False, fontsize=7.5)

    axis = axes[1, 2]
    style_axis(axis)
    positions = np.arange(len(summary))
    coverage = summary["calibrated_coverage_pct"]
    strict_coverage = summary["strict_calibrated_coverage_pct"]
    width = 0.34
    bars = axis.bar(positions - width / 2, coverage, width, color=BLUE, label="車線幅透視モデル")
    axis.bar(positions + width / 2, strict_coverage, width, color=ORANGE, label="厳密16m校正")
    axis.set_xticks(positions, summary["track_id"].astype(str))
    axis.set_xlabel("Track ID", color=MUTED)
    axis.set_ylabel("有効フレーム率 (%)", color=MUTED)
    axis.set_title("物理速度を算出できる範囲", loc="left", color=INK, fontweight="bold")
    for bar, seconds in zip(bars, summary["calibrated_duration_s"]):
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            f"{seconds:.1f}s",
            ha="center",
            va="bottom",
            color=MUTED,
            fontsize=8,
        )
    axis.legend(frameon=False, fontsize=7.5)

    fig.suptitle(
        "CVAT実トラック：距離・速度の物理量可視化",
        x=0.045,
        y=0.985,
        ha="left",
        color=INK,
        fontsize=18,
        fontweight="bold",
    )
    fig.text(
        0.045,
        0.952,
        f"2_20250720_y / 車線幅透視モデル適合RMSE {perspective.fit_rmse_m:.2f} m / {fps:.1f}fps / 主表示 Track {focus_id}",
        color=MUTED,
        fontsize=9,
    )
    fig.text(
        0.045,
        0.018,
        "距離・速度は9本の既知距離線と車線幅7 mから推定。白線形状の定義範囲外は外挿せず欠損。厳密16 m校正の有効率も併記。",
        color=MUTED,
        fontsize=8.5,
    )
    fig.subplots_adjust(left=0.06, right=0.985, top=0.91, bottom=0.08, wspace=0.28, hspace=0.32)
    fig.savefig(output_path, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return focus_id


def write_readme(
    output_dir: str,
    summary: pd.DataFrame,
    focus_id: int,
    ladder: VerticalLadder,
    perspective: LanePerspectiveModel,
    calibration_size: tuple[float, float],
    video_size: tuple[float, float],
) -> None:
    focus = summary[summary["track_id"] == focus_id].iloc[0]
    lines = [
        "# CVAT calibrated distance and speed",
        "",
        "- Calibration profile: `2_20250720_y`",
        f"- Calibration geometry scaled from {calibration_size[0]:.0f}x{calibration_size[1]:.0f} to {video_size[0]:.0f}x{video_size[1]:.0f}",
        f"- Calibrated longitudinal range: {ladder.calibrated_length_m:.3f} m",
        f"- Lane-perspective fit RMSE: {perspective.fit_rmse_m:.3f} m",
        f"- Lane-perspective fit maximum error: {perspective.fit_max_error_m:.3f} m",
        "- The reference estimate uses inverse apparent lane width for depth.",
        "- Values outside the annotated lane-line geometry are not extrapolated.",
        "- Speed uses least-squares regression over every point in the trailing 0.2-second window.",
        f"- Focus track: {focus_id} ({focus['label']})",
        f"- Focus calibrated duration: {focus['calibrated_duration_s']:.3f} s",
        f"- Focus traveled distance in range: {focus['traveled_distance_m']:.3f} m",
        f"- Focus median speed: {focus['median_speed_km_h']:.3f} km/h",
        f"- Focus maximum speed: {focus['max_speed_km_h']:.3f} km/h",
        f"- Endpoint-difference roughness: {focus['endpoint_speed_roughness_km_h']:.3f} km/h per sample",
        f"- Regression roughness: {focus['regression_speed_roughness_km_h']:.3f} km/h per sample",
        f"- Roughness reduction: {focus['roughness_reduction_pct']:.3f}%",
    ]
    with open(os.path.join(output_dir, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xml", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--calibration", required=True)
    parser.add_argument("--calibration-width", type=float, default=1920.0)
    parser.add_argument("--calibration-height", type=float, default=1080.0)
    parser.add_argument(
        "--output-dir",
        default=os.path.join(ROOT, "artifacts", "cvat_distance_speed"),
    )
    parser.add_argument("--window", type=int, default=11)
    args = parser.parse_args()

    with open(args.calibration, encoding="utf-8") as handle:
        calibration = json.load(handle)

    capture = cv2.VideoCapture(args.video)
    if not capture.isOpened():
        raise FileNotFoundError(args.video)
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    video_width = float(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_height = float(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    calibration = scale_calibration_geometry(
        calibration,
        video_width / args.calibration_width,
        video_height / args.calibration_height,
    )
    ladder = VerticalLadder(calibration.get("scale") or {})
    if not ladder.ready:
        raise ValueError("The calibration profile has no usable vertical distance ladder")
    perspective = LanePerspectiveModel(calibration, ladder)
    if not perspective.ready:
        raise ValueError("The calibration profile cannot fit a lane-perspective model")

    frame = mark_active_motion(add_measure_points(read_cvat_tracks(args.xml)))
    frame = add_legacy_smoothing(frame, args.window)
    frame = stabilize_measure_points(frame, window=args.window)
    frame = add_calibrated_positions(frame, ladder, perspective)
    frame = enforce_monotonic_depth(frame)
    frame = add_lateral_distance(frame, perspective.lane_width_m)
    frame = add_speed_columns(frame, fps)
    summary = build_summary(frame, fps)

    os.makedirs(args.output_dir, exist_ok=True)
    summary_path = os.path.join(args.output_dir, "track_distance_speed_summary.csv")
    summary.to_csv(summary_path, index=False)
    visualization_path = os.path.join(args.output_dir, "distance_speed_visualization.png")
    focus_id = draw_visualization(frame, summary, fps, ladder, perspective, visualization_path)
    write_readme(
        args.output_dir,
        summary,
        focus_id,
        ladder,
        perspective,
        (args.calibration_width, args.calibration_height),
        (video_width, video_height),
    )

    focus = summary[summary["track_id"] == focus_id].iloc[0]
    print(args.output_dir)
    print(
        f"focus_track={focus_id} calibrated_duration={focus['calibrated_duration_s']:.3f}s "
        f"distance={focus['traveled_distance_m']:.3f}m "
        f"median_speed={focus['median_speed_km_h']:.3f}km/h "
        f"max_speed={focus['max_speed_km_h']:.3f}km/h "
        f"roughness_reduction={focus['roughness_reduction_pct']:.1f}%"
    )


if __name__ == "__main__":
    main()
