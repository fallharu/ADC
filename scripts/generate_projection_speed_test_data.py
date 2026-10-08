"""Generate before/after projection datasets for two controlled speed scenarios."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import cv2  # noqa: E402
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from Source_code.modules.speed_homography import apply_homography_speed  # noqa: E402
from Source_code.modules.speed_y_axis import VerticalContext  # noqa: E402


FPS = 30.0
ROAD_WIDTH_M = 10.0
ROAD_LENGTH_M = 100.0
START_M = 5.0
END_M = 95.0
SPEED_WINDOW_SECONDS = 0.2
SPEED_WINDOW_FRAMES = int(round(FPS * SPEED_WINDOW_SECONDS))
IMAGE_WIDTH = 1920
IMAGE_HEIGHT = 1080
IMAGE_QUAD = np.array(
    [[790.0, 150.0], [1130.0, 150.0], [1650.0, 1000.0], [270.0, 1000.0]],
    dtype=np.float32,
)
WORLD_QUAD = np.array(
    [[0.0, 0.0], [ROAD_WIDTH_M, 0.0], [ROAD_WIDTH_M, ROAD_LENGTH_M], [0.0, ROAD_LENGTH_M]],
    dtype=np.float32,
)

INK = "#172033"
MUTED = "#687386"
GRID = "#DDE3EC"
BLUE = "#2F6FED"
ORANGE = "#F08C46"
GREEN = "#20A474"
RED = "#D95852"
SURFACE = "#F6F8FC"


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    duration_s: float
    time_s: np.ndarray
    position_m: np.ndarray
    speed_mps: np.ndarray


def constant_speed_scenario() -> Scenario:
    speed_mps = 15.0
    duration_s = (END_M - START_M) / speed_mps
    time_s = np.arange(int(round(duration_s * FPS)) + 1, dtype=float) / FPS
    position_m = START_M + speed_mps * time_s
    return Scenario(
        key="constant_speed",
        title="開始から終了まで等速",
        duration_s=duration_s,
        time_s=time_s,
        position_m=position_m,
        speed_mps=np.full_like(time_s, speed_mps),
    )


def accelerate_decelerate_scenario() -> Scenario:
    duration_s = 7.5
    half_s = duration_s / 2.0
    start_speed = 8.0
    peak_speed = 16.0
    acceleration = (peak_speed - start_speed) / half_s
    time_s = np.arange(int(round(duration_s * FPS)) + 1, dtype=float) / FPS
    first_half = time_s <= half_s
    position_m = np.empty_like(time_s)
    speed_mps = np.empty_like(time_s)
    position_m[first_half] = (
        START_M
        + start_speed * time_s[first_half]
        + 0.5 * acceleration * time_s[first_half] ** 2
    )
    speed_mps[first_half] = start_speed + acceleration * time_s[first_half]
    tau = time_s[~first_half] - half_s
    middle_position = START_M + start_speed * half_s + 0.5 * acceleration * half_s**2
    position_m[~first_half] = middle_position + peak_speed * tau - 0.5 * acceleration * tau**2
    speed_mps[~first_half] = peak_speed - acceleration * tau
    return Scenario(
        key="accelerate_decelerate",
        title="中央まで加速・その後減速",
        duration_s=duration_s,
        time_s=time_s,
        position_m=position_m,
        speed_mps=speed_mps,
    )


def empty_vertical_context(index: pd.Index) -> VerticalContext:
    return VerticalContext(
        ready=False,
        ppm_series=pd.Series(np.nan, index=index),
        y_delta=pd.Series(np.nan, index=index),
        range_min=None,
        range_max=None,
    )


def world_to_image(world_x: np.ndarray, world_y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    transform = cv2.getPerspectiveTransform(WORLD_QUAD, IMAGE_QUAD)
    points = np.column_stack([world_x, world_y]).astype(np.float32).reshape(-1, 1, 2)
    projected = cv2.perspectiveTransform(points, transform).reshape(-1, 2)
    return projected[:, 0].astype(float), projected[:, 1].astype(float)


def generate_scenario_data(scenario: Scenario, seed: int) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    true_x = np.full_like(scenario.position_m, ROAD_WIDTH_M / 2.0)
    ideal_image_x, ideal_image_y = world_to_image(true_x, scenario.position_m)
    rng = np.random.default_rng(seed)
    observed_x = ideal_image_x + rng.normal(0.0, 0.65, len(ideal_image_x))
    observed_y = ideal_image_y + rng.normal(0.0, 0.65, len(ideal_image_y))

    pre = pd.DataFrame(
        {
            "scenario": scenario.key,
            "frame_num": np.arange(len(scenario.time_s)),
            "time_s": scenario.time_s,
            "true_world_x_m": true_x,
            "true_world_y_m": scenario.position_m,
            "true_speed_km_h": scenario.speed_mps * 3.6,
            "image_x_ideal_px": ideal_image_x,
            "image_y_ideal_px": ideal_image_y,
            "image_x_observed_px": observed_x,
            "image_y_observed_px": observed_y,
        }
    )

    smooth_x = (
        pd.Series(observed_x)
        .rolling(11, center=True, min_periods=11)
        .median()
        .fillna(pd.Series(observed_x))
    )
    smooth_y = (
        pd.Series(observed_y)
        .rolling(11, center=True, min_periods=11)
        .median()
        .fillna(pd.Series(observed_y))
    )
    frame = pd.DataFrame(
        {
            "track_id": 1,
            "frame_num": pre["frame_num"],
            "center_x": observed_x,
            "center_y": observed_y,
            "y2": observed_y,
            "measure_x": observed_x,
            "measure_y": observed_y,
            "smooth_measure_x": smooth_x,
            "smooth_measure_y": smooth_y,
            "speed_mps": 0.0,
            "speed_km_h": 0.0,
            "acceleration_m_s2": 0.0,
            "scale_pixels_per_meter": np.nan,
            "y_delta": np.nan,
        }
    )
    one_frame_time = frame.groupby("track_id")["frame_num"].diff() / FPS
    applied = apply_homography_speed(
        frame,
        one_frame_time,
        fps=FPS,
        frame_window=int(FPS),
        homography_meta={
            "image_points": IMAGE_QUAD.tolist(),
            "width_m": ROAD_WIDTH_M,
            "length_m": ROAD_LENGTH_M,
            "speed_distance_mode": "longitudinal",
        },
        vertical_context=empty_vertical_context(frame.index),
        speed_window_frames=SPEED_WINDOW_FRAMES,
    )
    if not applied:
        raise RuntimeError(f"homography projection failed for {scenario.key}")

    estimated_speed = (
        frame["speed_km_h"]
        .rolling(5, center=True, min_periods=1)
        .median()
        .to_numpy()
    )
    valid_speed = np.arange(len(frame)) >= SPEED_WINDOW_FRAMES
    estimated_speed[~valid_speed] = np.nan
    speed_center_time = scenario.time_s - SPEED_WINDOW_SECONDS / 2.0
    true_interval_speed = np.full(len(frame), np.nan, dtype=float)
    true_interval_speed[valid_speed] = (
        np.abs(
            scenario.position_m[valid_speed]
            - scenario.position_m[np.arange(len(frame))[valid_speed] - SPEED_WINDOW_FRAMES]
        )
        / SPEED_WINDOW_SECONDS
        * 3.6
    )

    post = pd.DataFrame(
        {
            "scenario": scenario.key,
            "frame_num": pre["frame_num"],
            "time_s": scenario.time_s,
            "speed_time_center_s": speed_center_time,
            "projected_world_x_m": frame["world_x"],
            "projected_world_y_m": frame["world_y"],
            "true_world_x_m": true_x,
            "true_world_y_m": scenario.position_m,
            "position_error_m": frame["world_y"].to_numpy() - scenario.position_m,
            "estimated_speed_km_h": estimated_speed,
            "true_interval_speed_km_h": true_interval_speed,
            "speed_error_km_h": estimated_speed - true_interval_speed,
            "speed_valid": valid_speed.astype(int),
        }
    )
    evaluation = valid_speed & (np.arange(len(frame)) < len(frame) - 3)
    metrics = {
        "position_rmse_m": float(np.sqrt(np.mean(post.loc[evaluation, "position_error_m"] ** 2))),
        "speed_rmse_km_h": float(np.sqrt(np.mean(post.loc[evaluation, "speed_error_km_h"] ** 2))),
        "speed_max_error_km_h": float(np.max(np.abs(post.loc[evaluation, "speed_error_km_h"]))),
    }
    return pre, post, metrics


def style_axis(ax: plt.Axes) -> None:
    ax.set_facecolor("white")
    ax.grid(True, color=GRID, linewidth=0.8, alpha=0.85)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8.5)


def draw_visualization(
    results: list[tuple[Scenario, pd.DataFrame, pd.DataFrame, dict[str, float]]],
    output_path: str,
) -> None:
    plt.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "DejaVu Sans"]
    fig, axes = plt.subplots(2, 4, figsize=(17, 9.5), dpi=160, facecolor=SURFACE)
    scatter_colors = [BLUE, ORANGE]

    for row, (scenario, pre, post, metrics) in enumerate(results):
        color = scatter_colors[row]

        ax = axes[row, 0]
        style_axis(ax)
        polygon = np.vstack([IMAGE_QUAD, IMAGE_QUAD[0]])
        ax.plot(polygon[:, 0], polygon[:, 1], color=INK, linewidth=1.4)
        ax.plot(pre["image_x_ideal_px"], pre["image_y_ideal_px"], color=MUTED, linewidth=1.2, label="理想軌跡")
        scatter = ax.scatter(
            pre["image_x_observed_px"], pre["image_y_observed_px"],
            c=pre["time_s"], cmap="viridis", s=8, alpha=0.7, label="観測点",
        )
        ax.scatter(pre.iloc[0]["image_x_observed_px"], pre.iloc[0]["image_y_observed_px"], color=GREEN, s=38, zorder=5, label="開始")
        ax.scatter(pre.iloc[-1]["image_x_observed_px"], pre.iloc[-1]["image_y_observed_px"], color=RED, s=38, zorder=5, label="終了")
        ax.set_xlim(150, 1770)
        ax.set_ylim(1040, 100)
        ax.set_xlabel("画像 x (px)", color=MUTED)
        ax.set_ylabel("画像 y (px)", color=MUTED)
        ax.set_title("射影前：カメラ画像座標", loc="left", color=INK, fontsize=11, fontweight="bold")
        ax.legend(frameon=False, fontsize=7.5, loc="upper left")
        fig.colorbar(scatter, ax=ax, fraction=0.035, pad=0.02, label="時間 (秒)")

        ax = axes[row, 1]
        style_axis(ax)
        ax.plot([0, ROAD_WIDTH_M, ROAD_WIDTH_M, 0, 0], [0, 0, ROAD_LENGTH_M, ROAD_LENGTH_M, 0], color=INK, linewidth=1.2)
        ax.plot(post["true_world_x_m"], post["true_world_y_m"], color=INK, linestyle="--", linewidth=1.5, label="真値")
        ax.scatter(post["projected_world_x_m"], post["projected_world_y_m"], c=post["time_s"], cmap="viridis", s=8, alpha=0.75, label="射影後")
        ax.set_xlim(-0.5, ROAD_WIDTH_M + 0.5)
        ax.set_ylim(ROAD_LENGTH_M + 2, -2)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel("道路横断 x (m)", color=MUTED)
        ax.set_ylabel("道路縦方向 y (m)", color=MUTED)
        ax.set_title("射影後：道路平面座標", loc="left", color=INK, fontsize=11, fontweight="bold")
        ax.legend(frameon=False, fontsize=7.5, loc="upper right")

        ax = axes[row, 2]
        style_axis(ax)
        ax.plot(post["time_s"], post["true_world_y_m"], color=INK, linestyle="--", linewidth=1.5, label="真の位置")
        ax.plot(post["time_s"], post["projected_world_y_m"], color=color, linewidth=2.0, label="射影後位置")
        ax.set_xlabel("時間 (秒)", color=MUTED)
        ax.set_ylabel("開始点からの位置 (m)", color=MUTED)
        ax.set_title("位置－時間", loc="left", color=INK, fontsize=11, fontweight="bold")
        ax.legend(frameon=False, fontsize=8)
        ax.text(
            0.03, 0.94, f"位置RMSE {metrics['position_rmse_m']:.3f} m",
            transform=ax.transAxes, va="top", color=MUTED, fontsize=8.5,
        )

        ax = axes[row, 3]
        style_axis(ax)
        ax.plot(
            post["speed_time_center_s"], post["true_interval_speed_km_h"],
            color=INK, linestyle="--", linewidth=1.6, label="真の区間速度",
        )
        ax.plot(
            post["speed_time_center_s"], post["estimated_speed_km_h"],
            color=GREEN, linewidth=2.1, label="射影後の推定速度",
        )
        ax.set_xlabel("区間中央時刻 (秒)", color=MUTED)
        ax.set_ylabel("速度 (km/h)", color=MUTED)
        ax.set_title("速度－時間", loc="left", color=INK, fontsize=11, fontweight="bold")
        ax.legend(frameon=False, fontsize=8)
        ax.text(
            0.03, 0.94,
            f"速度RMSE {metrics['speed_rmse_km_h']:.2f} km/h\n最大誤差 {metrics['speed_max_error_km_h']:.2f} km/h",
            transform=ax.transAxes, va="top", color=MUTED, fontsize=8.5,
        )

        axes[row, 0].text(
            -0.02, 1.07, scenario.title,
            transform=axes[row, 0].transAxes, color=color, fontsize=13, fontweight="bold",
        )

    fig.suptitle("射影前・射影後 速度テストデータ", x=0.04, y=0.988, ha="left", color=INK, fontsize=19, fontweight="bold")
    fig.text(
        0.04, 0.954,
        "共通条件: 30fps、道路5→95m、台形カメラ視点、観測ノイズσ=0.65px、速度窓0.2秒",
        color=MUTED, fontsize=9,
    )
    fig.text(
        0.04, 0.015,
        "射影前CSVは画像座標、射影後CSVは道路平面座標と推定速度を収録。速度は0.2秒区間の中央時刻に配置。",
        color=MUTED, fontsize=8.5,
    )
    fig.subplots_adjust(left=0.04, right=0.99, top=0.90, bottom=0.07, wspace=0.32, hspace=0.42)
    fig.savefig(output_path, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def write_readme(output_dir: str, results) -> None:
    lines = [
        "# 射影速度テストデータ",
        "",
        "- `*_pre_projection.csv`: ホモグラフィ適用前の画像座標。`ideal` はノイズなし、`observed` は検出ノイズを付加した座標です。",
        "- `*_post_projection.csv`: 道路平面へ射影した座標、0.2秒区間速度、真値、誤差です。",
        "- `calibration.json`: 生成に使用した画像四隅と道路寸法です。",
        "- `projection_speed_test_visualization.png`: 両シナリオの比較図です。",
        "",
        "## シナリオ",
        "",
        "1. `constant_speed`: 5mから95mまで15m/s（54km/h）の等速走行。",
        "2. `accelerate_decelerate`: 8m/sから16m/sまで中央で加速し、その後8m/sまで対称に減速。",
        "",
        "## 検証値",
        "",
    ]
    for scenario, _pre, _post, metrics in results:
        lines.append(
            f"- {scenario.key}: 位置RMSE={metrics['position_rmse_m']:.4f}m, "
            f"速度RMSE={metrics['speed_rmse_km_h']:.4f}km/h, "
            f"最大速度誤差={metrics['speed_max_error_km_h']:.4f}km/h"
        )
    with open(os.path.join(output_dir, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default=os.path.join(ROOT, "artifacts", "projection_speed_test"),
    )
    args = parser.parse_args()
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    scenarios = [constant_speed_scenario(), accelerate_decelerate_scenario()]
    results = []
    for index, scenario in enumerate(scenarios):
        pre, post, metrics = generate_scenario_data(scenario, seed=100 + index)
        pre.to_csv(
            os.path.join(output_dir, f"{scenario.key}_pre_projection.csv"),
            index=False,
            encoding="utf-8-sig",
            float_format="%.6f",
        )
        post.to_csv(
            os.path.join(output_dir, f"{scenario.key}_post_projection.csv"),
            index=False,
            encoding="utf-8-sig",
            float_format="%.6f",
        )
        results.append((scenario, pre, post, metrics))

    calibration = {
        "fps": FPS,
        "image_size": [IMAGE_WIDTH, IMAGE_HEIGHT],
        "scale": {
            "mode": "homography",
            "speed_window_seconds": SPEED_WINDOW_SECONDS,
            "speed_smoothing_frames": 5,
            "homography": {
                "image_points": IMAGE_QUAD.tolist(),
                "world_points": WORLD_QUAD.tolist(),
                "width_m": ROAD_WIDTH_M,
                "length_m": ROAD_LENGTH_M,
                "speed_distance_mode": "longitudinal",
            },
        },
    }
    with open(os.path.join(output_dir, "calibration.json"), "w", encoding="utf-8") as handle:
        json.dump(calibration, handle, ensure_ascii=False, indent=2)

    visualization_path = os.path.join(output_dir, "projection_speed_test_visualization.png")
    draw_visualization(results, visualization_path)
    write_readme(output_dir, results)

    print(output_dir)
    for scenario, _pre, _post, metrics in results:
        print(
            f"{scenario.key}: position_rmse={metrics['position_rmse_m']:.4f}m "
            f"speed_rmse={metrics['speed_rmse_km_h']:.4f}km/h "
            f"max_speed_error={metrics['speed_max_error_km_h']:.4f}km/h"
        )


if __name__ == "__main__":
    main()
