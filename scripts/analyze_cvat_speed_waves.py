"""Compare CVAT speed waves with image motion and calibration scale."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.analyze_cvat_measurement_smoothing import (  # noqa: E402
    add_legacy_smoothing,
    add_measure_points,
    mark_active_motion,
    read_cvat_tracks,
)
from scripts.visualize_cvat_distance_speed import (  # noqa: E402
    LanePerspectiveModel,
    VerticalLadder,
    _coerce_line_points,
    add_calibrated_positions,
    add_speed_columns,
    enforce_monotonic_depth,
    scale_calibration_geometry,
)
from Source_code.modules.measure_points import stabilize_measure_points  # noqa: E402
from Source_code.modules.speed_regression import rolling_linear_slope  # noqa: E402


def _binned(track: pd.DataFrame, name: str, edges: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    bins = pd.cut(track["smooth_depth_m"], edges, labels=False, include_lowest=True)
    medians = track.groupby(bins, observed=True)[name].median()
    centers = (edges[:-1] + edges[1:]) / 2
    return centers[medians.index.astype(int)], medians.to_numpy(dtype=float)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with args.calibration.open(encoding="utf-8-sig") as handle:
        calibration = json.load(handle)
    calibration = scale_calibration_geometry(calibration, 1280 / 1920, 720 / 1080)
    ladder = VerticalLadder(calibration.get("scale") or {})
    perspective = LanePerspectiveModel(calibration, ladder)
    if not ladder.ready or not perspective.ready:
        raise ValueError("The CVAT calibration is not usable")

    frame = mark_active_motion(add_measure_points(read_cvat_tracks(str(args.xml))))
    frame = add_legacy_smoothing(frame, 11)
    frame = stabilize_measure_points(frame, window=11)
    frame = add_calibrated_positions(frame, ladder, perspective)
    unconstrained_speed = add_speed_columns(frame, 30.0)["smooth_speed_km_h"]
    frame = enforce_monotonic_depth(frame)
    frame = add_speed_columns(frame, 30.0)
    frame["unconstrained_speed_km_h"] = unconstrained_speed
    frame = frame[frame["active_motion"] & frame["smooth_depth_m"].notna()].copy()

    period = 6  # Same 0.2 s window as the displayed speed.
    pixel_slope = rolling_linear_slope(
        frame["frame_num"],
        frame["smooth_measure_y"],
        frame["track_id"],
        30.0,
        period,
        valid_mask=frame["smooth_measure_y"].notna(),
    )
    frame["pixel_speed_px_s"] = pixel_slope.abs().groupby(frame["track_id"]).transform(
        lambda values: values.rolling(5, center=True, min_periods=1).median()
    )
    frame["flat_depth"] = frame.groupby("track_id")["smooth_depth_m"].diff().abs().lt(1e-9)

    far_y = _coerce_line_points(ladder.lines[0])[0][1]
    near_y = _coerce_line_points(ladder.lines[-1])[0][1]
    image_y = np.linspace(far_y, near_y, 2400)
    width = np.array([perspective._lane_width_px(y) for y in image_y])
    road_y = perspective.coefficient / width + perspective.intercept
    meters_per_pixel = np.abs(np.gradient(road_y, image_y))
    order = np.argsort(road_y)
    road_steps = np.diff(road_y)
    largest_steps = np.argsort(np.abs(road_steps))[-6:][::-1]

    edges = np.arange(0, ladder.calibrated_length_m + 0.501, 0.5)
    colors = plt.get_cmap("tab10")
    fig, axes = plt.subplots(1, 4, figsize=(20, 6), dpi=160, sharey=True)
    for ax in axes:
        ax.set_ylim(0, ladder.calibrated_length_m)
        ax.grid(color="#dce3ee", linewidth=0.8)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Road distance (m; near edge = 0)")
    axes[0].set_xlabel("Estimated speed (km/h)")
    axes[0].set_title("Metric speed")
    axes[1].set_xlabel("Image motion (px/s)")
    axes[1].set_title("Before distance conversion")
    axes[2].set_xlabel("Distance scale (m/px)")
    axes[2].set_title("Calibration derivative")
    axes[3].set_xlabel("Repeated-distance fraction")
    axes[3].set_title("Monotonic-fit plateaus")

    for color_index, (track_id, track) in enumerate(frame.groupby("track_id", sort=True)):
        color = colors(color_index % 10)
        for ax, column in (
            (axes[0], "smooth_speed_km_h"),
            (axes[1], "pixel_speed_px_s"),
            (axes[3], "flat_depth"),
        ):
            y, x = _binned(track, column, edges)
            ax.plot(x, y, linewidth=1.8, color=color, label=f"Track {track_id}")
        valid_speed = track["smooth_speed_km_h"].notna()
        print(
            f"Track {track_id}: valid_speed={valid_speed.sum()} "
            f"keyframes={track['keyframe'].sum()} "
            f"flat_depth_fraction={track['flat_depth'].mean():.3f}"
        )

    axes[2].plot(meters_per_pixel[order], road_y[order], color="#172033", linewidth=2)
    rung_y = np.array([_coerce_line_points(line)[0][1] for line in ladder.lines])
    rung_w = np.array([perspective._lane_width_px(y) for y in rung_y])
    rung_d = perspective.coefficient / rung_w + perspective.intercept
    for ax in axes:
        for depth in rung_d:
            if 0 <= depth <= ladder.calibrated_length_m:
                ax.axhline(depth, color="#999999", linewidth=0.45, alpha=0.3)
    axes[0].legend(frameon=False, loc="upper right", fontsize=8)
    fig.suptitle("CVAT speed waves: road scale, image motion, and fitting artefacts", fontsize=14)
    fig.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, bbox_inches="tight")
    plt.close(fig)
    print(f"Scale range: {np.nanmin(meters_per_pixel):.4f} to {np.nanmax(meters_per_pixel):.4f} m/px")
    print(f"Depth increases toward camera at {np.count_nonzero(road_steps > 0)} of {len(road_steps)} sampled steps")
    for index in largest_steps:
        before = perspective._details(image_y[index])
        after = perspective._details(image_y[index + 1])
        print(
            f"Calibration jump: road distance {road_y[index]:.3f} to {road_y[index + 1]:.3f} m "
            f"over {image_y[index + 1] - image_y[index]:.3f} image px; "
            f"lane width {before.lane_width_px:.2f} to {after.lane_width_px:.2f} px; "
            f"left x shift {after.left_point[0] - before.left_point[0]:.2f} px, "
            f"right x shift {after.right_point[0] - before.right_point[0]:.2f} px"
        )
    for low, high in ((1.5, 2.5), (6.5, 7.5), (14.0, 15.0)):
        band = frame[frame["smooth_depth_m"].between(low, high)]
        print(
            f"Distance {low:.1f}-{high:.1f} m: median speed "
            f"{band['smooth_speed_km_h'].median():.2f} km/h; "
            f"without monotonic fit {band['unconstrained_speed_km_h'].median():.2f} km/h; "
            f"flat fraction {band['flat_depth'].mean():.2f}"
        )


if __name__ == "__main__":
    main()
