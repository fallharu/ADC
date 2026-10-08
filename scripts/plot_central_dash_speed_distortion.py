"""中央線の破線・算出速度・射影変換の位置依存性を同じ位置軸で可視化する。

使用例:
    python scripts/plot_central_dash_speed_distortion.py \
        output/cvat_job2_2_250803_new2/distortion_check \
        --out output/cvat_job2_2_250803_new2/distortion_check/central_dash_speed_distortion.png

入力は check_calibration_distortion.py が出力する CSV だけなので、動画を再解析
せずに図を再生成できる。速度は各車両の 40--90 m 区間の中央値で正規化する。
これは車両固有の巡航速度を取り除き、位置に依存する系統的な偏りを確認しやすく
するためであり、車両の実際の加減速を補正するものではない。
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
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Yu Gothic", "Meiryo", "Noto Sans JP", "DejaVu Sans"]


def style_axis(ax: plt.Axes) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, linewidth=1, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9, length=0, pad=5)


def track_label(row: pd.Series) -> str:
    label = str(row["label"]).lower()
    if label in {"bicycle", "bike", "cyclist"}:
        return f"自転車 {int(row['track_id'])}"
    if label == "car":
        return f"車 {int(row['track_id'])}"
    return f"{row['label']} {int(row['track_id'])}"


def smooth_line(x: pd.Series | np.ndarray, y: pd.Series | np.ndarray,
                samples: int = 300) -> tuple[np.ndarray, np.ndarray]:
    """測定点を必ず通り、極値を不自然に作りにくい PCHIP 補間を返す。"""
    points = (pd.DataFrame({"x": x, "y": y})
              .dropna()
              .groupby("x", as_index=False)["y"].mean()
              .sort_values("x"))
    xp = points["x"].to_numpy(dtype=float)
    yp = points["y"].to_numpy(dtype=float)
    if len(xp) < 3:
        return xp, yp
    x_smooth = np.linspace(xp[0], xp[-1], samples)
    return x_smooth, PchipInterpolator(xp, yp)(x_smooth)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path, help="distortion_check ディレクトリ")
    parser.add_argument("--out", type=Path, help="出力 PNG パス")
    parser.add_argument("--reference-end-m", type=float, default=80.0,
                        help="破線間隔の基準を取る最遠位置 [m]（既定: 80）")
    args = parser.parse_args()

    input_dir = args.input_dir
    dash = pd.read_csv(input_dir / "dash_periods.csv", encoding="utf-8-sig")
    speed = pd.read_csv(input_dir / "keyframe_interval_speeds.csv", encoding="utf-8-sig")
    mpp = pd.read_csv(input_dir / "meters_per_pixel.csv", encoding="utf-8-sig")
    out = args.out or input_dir / "central_dash_speed_distortion.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    reference = dash.loc[dash["v_to_m"] <= args.reference_end_m, "period_m"].median()
    if not np.isfinite(reference):
        raise ValueError("破線間隔の基準値を計算できませんでした。")
    dash["ratio_to_reference"] = dash["period_m"] / reference
    speed = speed.dropna(subset=["ratio_to_mid"]).copy()

    x_max = max(float(mpp["v_m"].max()), float(speed[["v_from_m", "v_to_m"]].max().max()))
    fig, axes = plt.subplots(
        3, 1, figsize=(11, 10.2), dpi=200, sharex=True,
        gridspec_kw={"height_ratios": [1.0, 1.45, 0.85], "hspace": 0.55},
    )
    fig.patch.set_facecolor(SURFACE)
    for ax in axes:
        style_axis(ax)

    # 1) 実世界で一定であるはずの破線周期。変動は位置換算の歪みの指標になる。
    ax = axes[0]
    ax.axhline(reference, color=MUTED, linewidth=1.1, zorder=1)
    dash_x = (dash["v_from_m"] + dash["v_to_m"]) / 2
    dash_x_smooth, dash_y_smooth = smooth_line(dash_x, dash["period_m"])
    ax.plot(dash_x_smooth, dash_y_smooth, color=INK_2, linewidth=2.8,
            solid_capstyle="round", solid_joinstyle="round", zorder=3)
    ax.scatter(dash_x, dash["period_m"], s=20, color=INK_2, edgecolor=SURFACE,
               linewidth=0.6, zorder=4, label="測定点")
    ax.set_ylim(0, max(14.0, float(dash["period_m"].max()) + 2.0))
    ax.yaxis.set_major_locator(MultipleLocator(4))
    ax.set_ylabel("破線周期 (m)", color=INK_2, fontsize=10, labelpad=8)
    ax.set_title("① 中央線の破線 1 周期の長さ（射影変換後）", loc="left",
                 fontsize=11, color=INK, pad=10)
    ax.text(x_max - 7, reference, f"0–{args.reference_end_m:.0f} m の中央値: {reference:.2f} m",
            color=INK_2, fontsize=8.5, ha="left", va="bottom")
    lowest = dash.loc[dash["period_m"].idxmin()]
    ax.annotate(
        f"最小 {lowest.period_m:.2f} m\n（基準の {lowest.ratio_to_reference:.0%}）",
        xy=((lowest.v_from_m + lowest.v_to_m) / 2, lowest.period_m),
        xytext=(lowest.v_from_m + 14, lowest.period_m - 3.2),
        color=INK_2, fontsize=8.5, ha="left", va="top",
        arrowprops={"arrowstyle": "-", "color": MUTED, "lw": 1},
    )

    # 2) 各車両の基準区間に対する算出速度の比。個別速度の違いを除いて比較する。
    ax = axes[1]
    ax.axhline(1.0, color=MUTED, linewidth=1.1, zorder=1)
    tracks = speed.drop_duplicates("track_id").sort_values("track_id")
    handles: list[Line2D] = []
    for i, first in enumerate(tracks.itertuples(index=False)):
        color = SERIES[i % len(SERIES)]
        rows = speed[speed["track_id"] == first.track_id].copy()
        speed_x = (rows["v_from_m"] + rows["v_to_m"]) / 2
        speed_x_smooth, speed_y_smooth = smooth_line(speed_x, rows["ratio_to_mid"])
        ax.plot(speed_x_smooth, speed_y_smooth, color=color, linewidth=2.6,
                solid_capstyle="round", solid_joinstyle="round", zorder=3)
        ax.scatter(speed_x, rows["ratio_to_mid"], s=16, color=color, edgecolor=SURFACE,
                   linewidth=0.5, zorder=4)
        handles.append(Line2D([0], [0], color=color, linewidth=2.6,
                              label=track_label(pd.Series(first._asdict()))))
    ax.set_ylim(0.5, 1.5)
    ax.yaxis.set_major_locator(MultipleLocator(0.25))
    ax.set_ylabel("基準速度比", color=INK_2, fontsize=10, labelpad=8)
    ax.set_title("② 算出速度 ÷ 各車両の 40–90 m 区間の中央値", loc="left",
                 fontsize=11, color=INK, pad=26)
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=len(handles),
              frameon=False, fontsize=9, labelcolor=INK_2, handlelength=1.6,
              columnspacing=1.4, borderaxespad=0.2)
    ax.text(x_max - 7, 1.03, "1.0 = 各車両の基準速度", color=INK_2, fontsize=8.5,
            ha="left", va="bottom")

    # 3) 射影変換による座標感度。遠方ほど 1 px の位置ずれが実距離に大きく効く。
    ax = axes[2]
    mpp_x_smooth, mpp_y_smooth = smooth_line(mpp["v_m"], mpp["m_per_px"], samples=500)
    ax.plot(mpp_x_smooth, mpp_y_smooth, color=INK_2, linewidth=2.5,
            solid_capstyle="round", solid_joinstyle="round", zorder=3)
    ax.set_ylim(0, max(3.5, float(mpp["m_per_px"].max()) * 1.1))
    ax.yaxis.set_major_locator(MultipleLocator(1))
    ax.set_ylabel("位置感度 (m / px)", color=INK_2, fontsize=10, labelpad=8)
    ax.set_title("③ 画像上で y が 1 px ずれたときの実距離への換算量", loc="left",
                 fontsize=11, color=INK, pad=10)
    near = mpp.iloc[(mpp["v_m"] - 0).abs().argsort().iloc[0]]
    far = mpp.iloc[(mpp["v_m"] - x_max).abs().argsort().iloc[0]]
    ax.text(x_max - 7, float(mpp["m_per_px"].max()) * 0.95,
            f"0 m: {near.m_per_px:.3f} m/px  →  {far.v_m:.0f} m: {far.m_per_px:.3f} m/px",
            color=INK_2, fontsize=8.5, ha="left", va="top")

    axes[-1].set_xlim(x_max + 2, -2)  # 左 = 奥、右 = カメラ側
    axes[-1].xaxis.set_major_locator(MultipleLocator(10))
    axes[-1].set_xlabel("位置 (m、カメラ側の端 = 0)    進行方向 →", color=INK_2,
                        fontsize=10, labelpad=8)
    fig.text(0.07, 0.975, "中央線の破線・算出速度・射影変換の歪み", fontsize=14,
             fontweight="bold", color=INK, va="top")
    fig.text(0.07, 0.944,
             "破線間隔の変動と速度の位置依存性を比較する図。実際の加減速も含むため、因果の証明ではなく校正の整合性確認に用いる。",
             fontsize=9.3, color=INK_2, va="top")
    fig.subplots_adjust(left=0.09, right=0.97, top=0.89, bottom=0.08)
    fig.savefig(out, facecolor=SURFACE)
    print(out)


if __name__ == "__main__":
    main()
