"""Plot estimated speed against road distance from CVAT tracks."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from scripts.analyze_cvat_measurement_smoothing import (  # noqa: E402
    add_legacy_smoothing,
    add_measure_points,
    mark_active_motion,
    read_cvat_tracks,
)
from scripts.visualize_cvat_distance_speed import (  # noqa: E402
    LanePerspectiveModel,
    VerticalLadder,
    add_calibrated_positions,
    add_speed_columns,
    enforce_monotonic_depth,
    scale_calibration_geometry,
)
from Source_code.modules.measure_points import stabilize_measure_points  # noqa: E402


def plot_speed_distance(frame, output: Path, road_length_m: float) -> int:
    """Show each valid track sample; distance zero is the near calibration line."""
    valid = frame.loc[
        frame["active_motion"]
        & frame["smooth_depth_m"].notna()
        & frame["smooth_speed_km_h"].notna()
    ]
    if valid.empty:
        raise ValueError("No speed observations inside the calibrated road range")

    plt.rcParams["font.family"] = ["DejaVu Sans"]
    fig, ax = plt.subplots(figsize=(9, 8), dpi=170)
    colors = plt.get_cmap("tab10")
    for color_index, (track_id, track) in enumerate(valid.groupby("track_id", sort=True)):
        ax.scatter(
            track["smooth_speed_km_h"],
            track["smooth_depth_m"],
            s=12,
            alpha=0.35,
            color=colors(color_index % 10),
            edgecolors="none",
            label=f"Track {track_id} ({track['label'].iloc[0]}) · n={len(track)}",
        )

    ax.set(
        title="CVAT: estimated speed vs. road distance",
        xlabel="Estimated speed (km/h)",
        ylabel="Road distance from near calibration line (m)",
        ylim=(0, road_length_m),
    )
    ax.set_xlim(left=0)
    ax.grid(color="#dce3ee", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper right", fontsize=8, markerscale=2)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    return len(valid)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--video-width", type=float, default=1280.0)
    parser.add_argument("--video-height", type=float, default=720.0)
    parser.add_argument("--calibration-width", type=float, default=1920.0)
    parser.add_argument("--calibration-height", type=float, default=1080.0)
    parser.add_argument("--window", type=int, default=11)
    args = parser.parse_args()

    with args.calibration.open(encoding="utf-8-sig") as handle:
        calibration = json.load(handle)
    calibration = scale_calibration_geometry(
        calibration,
        args.video_width / args.calibration_width,
        args.video_height / args.calibration_height,
    )
    ladder = VerticalLadder(calibration.get("scale") or {})
    if not ladder.ready:
        raise ValueError("Calibration has no usable distance ladder")
    perspective = LanePerspectiveModel(calibration, ladder)
    if not perspective.ready:
        raise ValueError("Calibration has no usable lane perspective")

    frame = mark_active_motion(add_measure_points(read_cvat_tracks(os.fspath(args.xml))))
    frame = add_legacy_smoothing(frame, args.window)
    frame = stabilize_measure_points(frame, window=args.window)
    frame = add_calibrated_positions(frame, ladder, perspective)
    frame = enforce_monotonic_depth(frame)
    frame = add_speed_columns(frame, args.fps)
    count = plot_speed_distance(frame, args.output, ladder.calibrated_length_m)
    print(f"Saved chart with {count} observations across {frame['track_id'].nunique()} tracks")


if __name__ == "__main__":
    main()
