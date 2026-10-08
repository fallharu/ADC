"""中央線の破線の周期と 5 m 区間速度を、同じ位置軸で上下に並べて描く。

  上段 : dash_periods.csv（check_calibration_distortion.py の出力）の破線 1 周期の長さ
  下段 : speed_every_5m[_linear].csv（cvat_speed_clearance_overtake.py の出力）の区間速度

使い方:
    python scripts/plot_dash_vs_speed.py <dash_periods.csv> <speed_every_5m.csv> [--out <png>]
"""
from __future__ import annotations

import argparse
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FuncFormatter, MultipleLocator  # noqa: E402

from plot_speed_every_nf import (  # noqa: E402
    AXIS, GRID, INK, INK_2, MUTED, SERIES, SURFACE, _series_name, _stairs,
)

REF_MAX_M = 80.0   # 破線周期の基準（中央値）をとる範囲 [m]


def _style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, linewidth=1, linestyle="-", zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9, length=0, pad=5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dash_csv")
    ap.add_argument("speed_csv")
    ap.add_argument("--out")
    args = ap.parse_args()

    periods = pd.read_csv(args.dash_csv, encoding="utf-8-sig")
    speed = pd.read_csv(args.speed_csv, encoding="utf-8-sig")
    cols = [c for c in speed.columns if c.endswith("_km_h")]
    linear = "_linear" in os.path.basename(args.speed_csv)
    out = args.out or os.path.join(
        os.path.dirname(args.dash_csv),
        "dash_vs_%s.png" % os.path.splitext(os.path.basename(args.speed_csv))[0].replace("speed_every_", "speed_"))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), dpi=200, sharex=True,
                                   gridspec_kw={"height_ratios": [1, 1.7], "hspace": 0.42})
    fig.patch.set_facecolor(SURFACE)
    _style(ax1)
    _style(ax2)

    # 上段: 破線の周期
    ref = periods.loc[periods["v_to_m"] <= REF_MAX_M, "period_m"].median()
    ax1.axhline(ref, color=MUTED, linewidth=1, zorder=1)
    for r in periods.itertuples():
        ax1.plot([r.v_from_m, r.v_to_m], [r.period_m, r.period_m], color=INK_2, linewidth=2.5,
                 solid_capstyle="round", zorder=3)
    far_end = periods["v_to_m"].max()
    ax1.text(far_end + 3, ref, "0〜%d m の中央値 %.1f m" % (REF_MAX_M, ref),
             color=INK_2, fontsize=8.5, ha="left", va="bottom")
    ax1.text((150 + far_end) / 2, ref / 2, "%d m より奥は\n破線がつながり測定できない" % round(far_end),
             color=MUTED, fontsize=8.5, ha="center", va="center", linespacing=1.3)
    ax1.set_ylim(0, max(14, periods["period_m"].max() + 2))
    ax1.yaxis.set_major_locator(MultipleLocator(4))
    ax1.set_ylabel("周期（m）", color=INK_2, fontsize=10, labelpad=8)
    ax1.set_title("中央線の破線 1 周期の長さ（キャリブレーション上）— 実際は一定のはず",
                  loc="left", fontsize=11, color=INK, pad=10)

    # 下段: 5 m 区間速度
    handles = []
    for i, col in enumerate(cols):
        color = SERIES[i % len(SERIES)]
        xs, ys = _stairs(speed, col)
        ax2.plot(xs, ys, color=color, linewidth=2, solid_capstyle="round",
                 solid_joinstyle="round", zorder=3)
        handles.append(Line2D([0], [0], color=color, linewidth=2.5, label=_series_name(col)))
    ymax = max(20.0, (speed[cols].max().max() // 20 + 1) * 20)
    ax2.set_ylim(0, ymax)
    ax2.yaxis.set_major_locator(MultipleLocator(20))
    ax2.set_ylabel("速度（km/h）", color=INK_2, fontsize=10, labelpad=8)
    ax2.set_title("5m 区間ごとの速度%s" % ("（キーフレーム間を路面上で線形補間）" if linear else ""),
                  loc="left", fontsize=11, color=INK, pad=28)
    ax2.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=len(handles),
               frameon=False, fontsize=9.5, labelcolor=INK_2, handlelength=1.6,
               columnspacing=1.6, borderaxespad=0.2)

    ax2.set_xlim(152, -2)
    ax2.xaxis.set_major_locator(MultipleLocator(10))
    ax2.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: "%d" % round(v)))
    ax2.set_xlabel("位置（m、カメラ側の端 = 0）　進行方向 →", color=INK_2, fontsize=10, labelpad=8)

    fig.text(0.07, 0.975, "中央線の破線と速度", fontsize=14, fontweight="bold", color=INK, va="top")
    fig.text(0.07, 0.94, "破線の周期が短い位置ほど距離が縮んで計算され、速度も低く出る",
             fontsize=9.5, color=INK_2, va="top")
    fig.subplots_adjust(left=0.08, right=0.97, top=0.86, bottom=0.08)
    fig.savefig(out, facecolor=SURFACE)
    print(out)


if __name__ == "__main__":
    main()
