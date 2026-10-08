"""中央線破線と速度比を同じ基準比の軸へ重ねて描く。

使用例:
    python scripts/plot_central_dash_speed_overlay.py \
        output/cvat_job2_2_250803_new2/distortion_check \
        --out output/cvat_job2_2_250803_new2/distortion_check/central_dash_speed_overlay.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import MultipleLocator  # noqa: E402
from scipy.interpolate import PchipInterpolator  # noqa: E402


SURFACE = "#fcfcfb"
INK = "#191918"
INK_2 = "#565551"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
MEDIAN_BLUE = "#1769aa"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Yu Gothic", "Meiryo", "Noto Sans JP", "DejaVu Sans"]


def smooth_line(x: pd.Series | np.ndarray, y: pd.Series | np.ndarray,
                samples: int = 400) -> tuple[np.ndarray, np.ndarray]:
    """測定値を通り、極値を余計に作りにくい PCHIP 補間。"""
    values = (pd.DataFrame({"x": x, "y": y})
              .dropna()
              .groupby("x", as_index=False)["y"].median()
              .sort_values("x"))
    xp, yp = values["x"].to_numpy(float), values["y"].to_numpy(float)
    if len(xp) < 3:
        return xp, yp
    xs = np.linspace(xp[0], xp[-1], samples)
    return xs, PchipInterpolator(xp, yp)(xs)


def track_name(label: object, track_id: object) -> str:
    if str(label).lower() in {"bicycle", "bike", "cyclist"}:
        return f"自転車 {int(track_id)}"
    if str(label).lower() == "car":
        return f"車 {int(track_id)}"
    return f"{label} {int(track_id)}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--reference-end-m", type=float, default=80.0)
    args = parser.parse_args()

    input_dir = args.input_dir
    dash = pd.read_csv(input_dir / "dash_periods.csv", encoding="utf-8-sig")
    speed = pd.read_csv(input_dir / "keyframe_interval_speeds.csv", encoding="utf-8-sig")
    output = args.out or input_dir / "central_dash_speed_overlay.png"
    output.parent.mkdir(parents=True, exist_ok=True)

    dash_reference = dash.loc[dash["v_to_m"] <= args.reference_end_m, "period_m"].median()
    if not np.isfinite(dash_reference):
        raise ValueError("破線周期の基準値を計算できませんでした。")
    dash["ratio"] = dash["period_m"] / dash_reference
    dash["position_m"] = (dash["v_from_m"] + dash["v_to_m"]) / 2

    speed = speed.dropna(subset=["ratio_to_mid"]).copy()
    speed["position_m"] = (speed["v_from_m"] + speed["v_to_m"]) / 2
    # 同じおおまかな位置にある車両の中央値。個別線より位置依存の傾向を読みやすくする。
    speed["bin_m"] = (speed["position_m"] / 10).round() * 10
    median_speed = speed.groupby("bin_m", as_index=False)["ratio_to_mid"].median()

    fig, ax = plt.subplots(figsize=(12, 7), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.axvspan(40, 90, color="#dfeaf3", alpha=0.65, zorder=0)
    ax.axhline(1.0, color=MUTED, linewidth=1.1, zorder=1)
    ax.grid(axis="y", color=GRID, linewidth=1, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9, length=0, pad=5)

    # 中央線の破線周期（太い破線）。速度と同じ「基準比」の軸に載せる。
    x_dash, y_dash = smooth_line(dash["position_m"], dash["ratio"])
    ax.plot(x_dash, y_dash, color=INK, linewidth=3.4, linestyle=(0, (6, 3)),
            solid_capstyle="round", zorder=5)
    ax.scatter(dash["position_m"], dash["ratio"], s=22, color=INK, edgecolor=SURFACE,
               linewidth=0.6, zorder=6)

    # 車両ごとの速度比は薄くして背景情報にし、位置別中央値を前面に出す。
    track_handles: list[Line2D] = []
    tracks = speed.drop_duplicates("track_id").sort_values("track_id")
    for i, track in enumerate(tracks.itertuples(index=False)):
        color = SERIES[i % len(SERIES)]
        rows = speed[speed["track_id"] == track.track_id]
        x, y = smooth_line(rows["position_m"], rows["ratio_to_mid"])
        ax.plot(x, y, color=color, linewidth=1.55, alpha=0.7, zorder=3)
        ax.scatter(rows["position_m"], rows["ratio_to_mid"], s=12, color=color,
                   alpha=0.7, edgecolor=SURFACE, linewidth=0.4, zorder=4)
        track_handles.append(Line2D([0], [0], color=color, linewidth=1.7, alpha=0.7,
                                    label=track_name(track.label, track.track_id)))

    x_median, y_median = smooth_line(median_speed["bin_m"], median_speed["ratio_to_mid"])
    ax.plot(x_median, y_median, color=MEDIAN_BLUE, linewidth=3.5,
            solid_capstyle="round", zorder=7)
    ax.scatter(median_speed["bin_m"], median_speed["ratio_to_mid"], s=28,
               color=MEDIAN_BLUE, edgecolor=SURFACE, linewidth=0.6, zorder=8)

    ax.set_xlim(152, -2)  # 左 = 奥、右 = カメラ側
    ax.set_ylim(0.55, 1.4)
    ax.xaxis.set_major_locator(MultipleLocator(10))
    ax.yaxis.set_major_locator(MultipleLocator(0.1))
    ax.set_xlabel("位置 (m、カメラ側の端 = 0)    進行方向 →", color=INK_2,
                  fontsize=10, labelpad=10)
    ax.set_ylabel("基準比（1.0 = 基準値）", color=INK_2, fontsize=10, labelpad=10)

    main_handles = [
        Line2D([0], [0], color=INK, linewidth=3.4, linestyle=(0, (6, 3)),
               label=f"中央線の破線周期 ÷ 基準 ({dash_reference:.2f} m)"),
        Line2D([0], [0], color=MEDIAN_BLUE, linewidth=3.5, label="全車両の速度比・位置別中央値"),
    ]
    legend_one = ax.legend(handles=main_handles, loc="upper left", frameon=False,
                           fontsize=9.5, labelcolor=INK_2, handlelength=2.8)
    ax.add_artist(legend_one)
    ax.legend(handles=track_handles, loc="lower left", ncol=len(track_handles), frameon=False,
              fontsize=8.5, labelcolor=INK_2, handlelength=1.6, columnspacing=1.2)

    ax.text(89, 1.38, "速度の基準区間 40–90 m", color=INK_2, fontsize=8.5,
            ha="right", va="top")
    ax.text(150, 1.02, "1.0 = 各系列の基準値", color=INK_2, fontsize=8.5,
            ha="left", va="bottom")
    fig.text(0.09, 0.965, "中央線の破線と算出速度の位置依存性", fontsize=14,
             fontweight="bold", color=INK, va="top")
    fig.text(0.09, 0.92,
             "同じ基準比で重ね表示。黒破線の低下と青線（速度中央値）の低下が同時に現れる位置は、射影変換の整合性を要確認。",
             fontsize=9.3, color=INK_2, va="top")
    fig.text(0.09, 0.04,
             "注: 実際の加減速も含むため、校正歪みとの因果を単独で確定する図ではありません。",
             fontsize=8.2, color=MUTED, va="bottom")
    fig.subplots_adjust(left=0.09, right=0.98, top=0.84, bottom=0.14)
    fig.savefig(output, facecolor=SURFACE)
    print(output)


if __name__ == "__main__":
    main()
