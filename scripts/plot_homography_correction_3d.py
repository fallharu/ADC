"""Plot a road calibration's longitudinal correction as a 3D surface.

Usage:
    python scripts/plot_homography_correction_3d.py \
        output/calibrations/2_250720_cf_v5_720.json \
        artifacts/homography_correction_3d/2_250720_cf_v5_720.png

The height is corrected road position minus the uncorrected homography
position, in metres. A longitudinal-only correction is constant across road
width; this is expected, and the plot makes that limitation visible.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import colors
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Source_code.modules.speed_homography import HomographyProjection  # noqa: E402


def correction_surface(profile: dict, nx: int = 46, ny: int = 201):
    scale = profile.get("scale") or {}
    if str(scale.get("mode") or "").lower() != "homography":
        raise ValueError("射影変換モードの校正プロファイルを指定してください。")
    projection = HomographyProjection(
        scale.get("homography") or {},
        profile.get("camera") or scale.get("camera"),
        scale.get("lines"),
    )
    if projection.raw_positions is None:
        raise ValueError("このプロファイルには縦方向の距離補正データがありません。")
    road_x = np.linspace(0, projection.width_m, nx)
    road_y = np.linspace(0, projection.length_m, ny)
    x, y = np.meshgrid(road_x, road_y)
    z = projection.correct_y(y) - y
    return projection, x, y, z


def plot(profile: dict, profile_name: str, output_path: Path) -> dict[str, float]:
    projection, x, y, z = correction_surface(profile)
    anchors_y = projection.raw_positions
    anchors_z = projection.corrected_positions - anchors_y
    z_min = float(np.nanmin(z))
    z_max = float(np.nanmax(z))
    maximum = float(np.nanmax(np.abs(z)))

    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Yu Gothic", "Meiryo", "Noto Sans CJK JP", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "font.size": 11,
    })
    fig = plt.figure(figsize=(15, 8.5), facecolor="#f8fafc")
    grid = fig.add_gridspec(1, 2, width_ratios=[1.6, 0.8],
                            left=0.045, right=0.96, top=0.85, bottom=0.14, wspace=0.08)
    axis = fig.add_subplot(grid[0, 0], projection="3d")
    side = fig.add_subplot(grid[0, 1])

    lower = min(0.0, z_min)
    upper = max(0.0, z_max)
    if upper - lower < 1e-9:
        upper = lower + 1.0
    norm = colors.TwoSlopeNorm(vmin=lower, vcenter=0, vmax=upper) if lower < 0 < upper else colors.Normalize(vmin=lower, vmax=upper)
    surface = axis.plot_surface(
        x, y, z, cmap="viridis", norm=norm, linewidth=0.13,
        edgecolor=(0.1, 0.19, 0.27, 0.12), antialiased=True,
    )
    floor = lower - max(0.6, (upper - lower) * 0.12)
    axis.contour(x, y, z, zdir="z", offset=floor,
                 levels=np.linspace(lower, upper, 9), cmap="viridis", alpha=0.58)
    axis.plot(np.zeros_like(anchors_y), anchors_y, anchors_z,
              color="#15253b", marker="o", markersize=4.3, linewidth=1.4,
              label="補正基準点")
    axis.set(xlim=(0, projection.width_m), ylim=(0, projection.length_m),
             zlim=(floor, upper + max(0.6, (upper - lower) * 0.18)))
    axis.set_xlabel("道路の横幅 x (m)", labelpad=12)
    axis.set_ylabel("道路の長さ y (m)", labelpad=12)
    axis.set_zlabel("補正量 z (m)", labelpad=12)
    axis.view_init(elev=27, azim=-60)
    axis.set_box_aspect((projection.width_m / projection.length_m * 1.9, 1, 0.72))
    axis.xaxis.pane.fill = False
    axis.yaxis.pane.fill = False
    axis.zaxis.pane.fill = False
    axis.legend(loc="upper left", frameon=False, fontsize=9)
    colorbar = fig.colorbar(surface, ax=axis, shrink=0.63, pad=0.04, aspect=23)
    colorbar.set_label("補正後 − 補正前 (m)")

    road_y = y[:, 0]
    offset = z[:, 0]
    side.axhline(0, color="#718096", linewidth=1, linestyle="--")
    side.fill_between(road_y, 0, offset, color="#2a9d8f", alpha=0.18)
    side.plot(road_y, offset, color="#176b83", linewidth=2.5, label="補正量")
    side.scatter(anchors_y, anchors_z, color="#d97706", s=38, zorder=4, label="補正基準点")
    side.set_xlim(0, projection.length_m)
    side.set_xlabel("道路の長さ y (m)")
    side.set_ylabel("補正量 z (m)")
    side.set_title("進行方向の断面", loc="left", pad=13, color="#16324f", weight="bold")
    side.grid(True, color="#d9e2ec", linewidth=0.8)
    side.spines[["top", "right"]].set_visible(False)
    side.legend(frameon=False, loc="best", fontsize=9)
    peak_index = int(np.argmax(np.abs(offset)))
    side.annotate(
        f"最大 |補正| {maximum:.2f} m",
        xy=(road_y[peak_index], offset[peak_index]),
        xytext=(0.48, 0.89), textcoords="axes fraction",
        arrowprops={"arrowstyle": "->", "color": "#d97706"},
        fontsize=10, color="#8d4c02", weight="bold",
    )

    fig.suptitle("射影変換後の道路距離補正を3D表示", x=0.045, y=0.965,
                 ha="left", fontsize=20, color="#11293f", weight="bold")
    fig.text(0.046, 0.906,
             f"プロファイル: {profile_name}  |  横幅 {projection.width_m:g} m  ×  道路長 {projection.length_m:g} m  |  補正基準点 {len(anchors_y)}個",
             color="#516579", fontsize=10.5)
    fig.text(0.045, 0.055,
             "z = 補正後の道路方向距離 − 射影変換直後の距離。現在の補正は進行方向のみなので、同じ y なら横幅 x によらず同じ高さです。",
             color="#516579", fontsize=10)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    return {"width_m": projection.width_m, "length_m": projection.length_m,
            "max_abs_correction_m": maximum, "anchors": len(anchors_y)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path, help="射影変換校正JSON")
    parser.add_argument("output", type=Path, help="出力PNG")
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text(encoding="utf-8-sig"))
    metrics = plot(profile, args.profile.stem, args.output)
    print(f"3D図を保存しました: {args.output} / 最大補正 {metrics['max_abs_correction_m']:.2f} m")


if __name__ == "__main__":
    main()
