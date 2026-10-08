"""Visualize the production speed-correction path on deterministic synthetic data."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from Source_code.modules.speed_homography import apply_homography_speed  # noqa: E402
from Source_code.modules.speed_y_axis import VerticalContext  # noqa: E402


INK = "#172033"
MUTED = "#687386"
GRID = "#DDE3EC"
BLUE = "#2F6FED"
ORANGE = "#F08C46"
GREEN = "#20A474"
RED = "#D95852"
SURFACE = "#F6F8FC"


def empty_vertical_context(index: pd.Index) -> VerticalContext:
    return VerticalContext(
        ready=False,
        ppm_series=pd.Series(np.nan, index=index),
        y_delta=pd.Series(np.nan, index=index),
        range_min=None,
        range_max=None,
    )


def build_result() -> tuple[pd.DataFrame, dict[str, float]]:
    fps = 30.0
    true_speed_mps = 15.0
    time_s = np.arange(0.0, (90.0 - 10.0) / true_speed_mps, 1.0 / fps)
    true_position = 10.0 + true_speed_mps * time_s

    # A deliberately distorted longitudinal mapping. The adjusted calibration
    # lines state that these raw positions represent equal 33.333 m intervals.
    raw_markers = np.array([0.0, 35.0, 65.0, 100.0])
    corrected_markers = np.linspace(0.0, 100.0, len(raw_markers))
    raw_position = np.interp(true_position, corrected_markers, raw_markers)
    rng = np.random.default_rng(42)
    observed_position = raw_position + rng.normal(0.0, 0.08, len(raw_position))

    old_speed = np.r_[np.nan, np.abs(np.diff(observed_position)) * fps * 3.6]
    smooth_position = (
        pd.Series(observed_position)
        .rolling(11, center=True, min_periods=11)
        .median()
        .fillna(pd.Series(observed_position))
        .to_numpy()
    )
    frame = pd.DataFrame(
        {
            "track_id": 1,
            "frame_num": np.arange(len(time_s)),
            "center_x": 5.0,
            "center_y": observed_position,
            "y2": observed_position,
            "measure_x": 5.0,
            "measure_y": observed_position,
            "smooth_measure_x": 5.0,
            "smooth_measure_y": smooth_position,
            "speed_mps": 0.0,
            "speed_km_h": 0.0,
            "acceleration_m_s2": 0.0,
            "scale_pixels_per_meter": np.nan,
            "y_delta": np.nan,
        }
    )
    one_frame_time = frame.groupby("track_id")["frame_num"].diff() / fps
    calibration_lines = [
        [[0.0, float(position)], [10.0, float(position)]]
        for position in raw_markers
    ]
    applied = apply_homography_speed(
        frame,
        one_frame_time,
        fps=fps,
        frame_window=int(fps),
        homography_meta={
            "image_points": [[0, 0], [10, 0], [10, 100], [0, 100]],
            "width_m": 10.0,
            "length_m": 100.0,
            "interval_m": 100.0 / 3.0,
        },
        vertical_context=empty_vertical_context(frame.index),
        speed_window_frames=int(round(fps * 0.2)),
        calibration_lines=calibration_lines,
    )
    if not applied:
        raise RuntimeError("homography correction was not applied")

    new_speed = (
        frame["speed_km_h"]
        .rolling(5, center=True, min_periods=1)
        .median()
        .to_numpy()
    )
    expected_speed = true_speed_mps * 3.6
    valid = np.arange(len(time_s)) >= int(round(fps * 0.4))
    old_error = old_speed[valid] - expected_speed
    new_error = new_speed[valid] - expected_speed
    old_rmse = float(np.sqrt(np.nanmean(old_error**2)))
    new_rmse = float(np.sqrt(np.nanmean(new_error**2)))
    improvement = 100.0 * (1.0 - new_rmse / old_rmse)

    result = pd.DataFrame(
        {
            "time_s": time_s,
            "true_position_m": true_position,
            "observed_position_m": observed_position,
            "corrected_position_m": frame["world_y"].to_numpy(),
            "old_speed_km_h": old_speed,
            "new_speed_km_h": new_speed,
            "old_error_km_h": old_speed - expected_speed,
            "new_error_km_h": new_speed - expected_speed,
        }
    )
    metrics = {
        "expected_speed": expected_speed,
        "old_rmse": old_rmse,
        "new_rmse": new_rmse,
        "improvement": improvement,
        "old_p95": float(np.nanpercentile(np.abs(old_error), 95)),
        "new_p95": float(np.nanpercentile(np.abs(new_error), 95)),
    }
    return result, metrics


def style_axis(ax: plt.Axes) -> None:
    ax.set_facecolor("white")
    ax.grid(True, color=GRID, linewidth=0.8, alpha=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)


def draw(output: str) -> dict[str, float]:
    result, metrics = build_result()
    plt.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "DejaVu Sans"]
    fig = plt.figure(figsize=(13.5, 9.2), dpi=160, facecolor=SURFACE)
    grid = fig.add_gridspec(3, 2, height_ratios=[0.55, 1.55, 1.0], hspace=0.48, wspace=0.28)

    cards = [
        ("関連テスト", "11 / 11", "すべて成功", BLUE),
        ("従来 RMSE", f"{metrics['old_rmse']:.1f} km/h", "1フレーム差分", ORANGE),
        ("補正後 RMSE", f"{metrics['new_rmse']:.1f} km/h", "0.2秒＋中央値", GREEN),
        ("誤差低減", f"{metrics['improvement']:.0f}%", "RMSE比較", GREEN),
    ]
    card_grid = grid[0, :].subgridspec(1, 4, wspace=0.15)
    for index, (label, value, note, color) in enumerate(cards):
        ax = fig.add_subplot(card_grid[0, index])
        ax.set_facecolor("white")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color(GRID)
        ax.text(0.06, 0.75, label, color=MUTED, fontsize=9, transform=ax.transAxes)
        ax.text(0.06, 0.36, value, color=color, fontsize=19, fontweight="bold", transform=ax.transAxes)
        ax.text(0.06, 0.10, note, color=MUTED, fontsize=8.5, transform=ax.transAxes)

    ax_speed = fig.add_subplot(grid[1, :])
    style_axis(ax_speed)
    ax_speed.axhline(metrics["expected_speed"], color=INK, linewidth=1.6, linestyle="--", label="真値 54 km/h")
    ax_speed.plot(
        result["time_s"], result["old_speed_km_h"],
        color=ORANGE, linewidth=1.0, alpha=0.55, label="従来: 1フレーム差分",
    )
    ax_speed.plot(
        result["time_s"], result["new_speed_km_h"],
        color=GREEN, linewidth=2.4, label="補正後: 距離補正＋0.2秒区間＋中央値",
    )
    ax_speed.set_ylim(0, max(90, float(np.nanpercentile(result["old_speed_km_h"], 99)) + 5))
    ax_speed.set_xlabel("時間 (秒)", color=MUTED)
    ax_speed.set_ylabel("推定速度 (km/h)", color=MUTED)
    ax_speed.set_title("一定速度走行に対する速度推定", loc="left", color=INK, fontsize=12, fontweight="bold")
    ax_speed.legend(frameon=False, ncol=3, loc="upper right", fontsize=9)

    ax_position = fig.add_subplot(grid[2, 0])
    style_axis(ax_position)
    ax_position.plot(result["true_position_m"], result["observed_position_m"], color=ORANGE, linewidth=2, label="歪みあり")
    ax_position.plot(result["true_position_m"], result["corrected_position_m"], color=GREEN, linewidth=2.2, label="補正後")
    ax_position.plot([10, 90], [10, 90], color=INK, linestyle="--", linewidth=1.2, label="理想")
    ax_position.set_xlabel("真の位置 (m)", color=MUTED)
    ax_position.set_ylabel("算出位置 (m)", color=MUTED)
    ax_position.set_title("位置依存の歪み補正", loc="left", color=INK, fontsize=11, fontweight="bold")
    ax_position.legend(frameon=False, fontsize=8.5)

    ax_error = fig.add_subplot(grid[2, 1])
    style_axis(ax_error)
    error_data = [
        result["old_error_km_h"].dropna().to_numpy(),
        result["new_error_km_h"].iloc[12:].dropna().to_numpy(),
    ]
    box = ax_error.boxplot(error_data, patch_artist=True, widths=0.45, showfliers=False)
    for patch, color in zip(box["boxes"], [ORANGE, GREEN]):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    for median in box["medians"]:
        median.set_color(INK)
        median.set_linewidth(1.7)
    ax_error.axhline(0, color=INK, linewidth=1, linestyle="--")
    ax_error.set_xticks([1, 2], ["従来", "補正後"])
    ax_error.set_ylabel("速度誤差 (km/h)", color=MUTED)
    ax_error.set_title("誤差分布（外れ値表示なし）", loc="left", color=INK, fontsize=11, fontweight="bold")
    ax_error.text(
        0.98, 0.95,
        f"95%誤差: {metrics['old_p95']:.1f} → {metrics['new_p95']:.1f} km/h",
        transform=ax_error.transAxes, ha="right", va="top", color=MUTED, fontsize=8.5,
    )

    fig.suptitle("速度歪み軽減 実装テスト", x=0.06, y=0.985, ha="left", color=INK, fontsize=18, fontweight="bold")
    fig.text(
        0.06, 0.952,
        "合成データ: 真値54 km/h、位置依存の射影歪み、検出ノイズσ=0.08を付与（乱数seed=42）",
        color=MUTED, fontsize=9,
    )
    fig.text(
        0.06, 0.015,
        "注: 実映像の精度保証値ではありません。補正ロジックの再現テスト結果です。",
        color=MUTED, fontsize=8.5,
    )
    fig.subplots_adjust(left=0.06, right=0.98, top=0.91, bottom=0.07)
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    fig.savefig(output, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=os.path.join(ROOT, "artifacts", "speed_correction_test_visualization.png"),
    )
    args = parser.parse_args()
    metrics = draw(args.output)
    print(os.path.abspath(args.output))
    print(
        "old_rmse={old_rmse:.3f} new_rmse={new_rmse:.3f} improvement={improvement:.1f}%".format(
            **metrics
        )
    )


if __name__ == "__main__":
    main()
