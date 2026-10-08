"""キャリブレーションから路面の俯瞰図（PNG）を作り、縦間隔と中央線破線による補正を重ねる。

上段: 射影変換だけで作った俯瞰図。interval_m ごとの横断線と、検出した破線の手前端・周期を表示。
下段: 中央線の破線周期が一定になるよう縦方向を補正した俯瞰図。補正は
      correct_speed_with_dash_periods.py の DashCorrection と同じ。横断線は補正座標で interval_m ごと。
      目標の破線周期はキャリブレーションの interval_m の 2 倍を既定とし、
      --actual-period-m を指定した場合はその値を優先する。

背景は動画から間引いたフレームの中央値画像（車両が消える）。破線の検出は
check_calibration_distortion.py と同じ処理を使う。

使い方:
    python scripts/make_calibration_birdseye.py <video> <calibration_profile> <出力PNG> \
        [--px-per-m 20] [--actual-period-m 10]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import cv2  # noqa: E402
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.ticker import FuncFormatter, MultipleLocator  # noqa: E402

from analyze_cvat_annotations import Projection  # noqa: E402
from check_calibration_distortion import dash_periods, detect_dashes, median_background  # noqa: E402
from correct_speed_with_dash_periods import (  # noqa: E402
    AXIS, INK, INK_2, MUTED, SERIES, SURFACE, DashCorrection,
)

EMPTY_BGR = (228, 234, 236)
RUNG = SERIES[0]
DASH = SERIES[1]

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Yu Gothic", "Meiryo", "Noto Sans JP", "DejaVu Sans"]


def render_strip(bg: np.ndarray, proj: Projection, v_cols: np.ndarray, u_rows: np.ndarray) -> np.ndarray:
    """列ごとの v、行ごとの u の路面格子を画像から引く。v が NaN の列と画像外は空白。"""
    Hi = np.linalg.inv(proj.H)
    vv, uu = np.meshgrid(v_cols, u_rows)
    m = np.stack([uu, vv, np.ones_like(uu)], axis=-1) @ Hi.T
    w = m[..., 2]
    # 地平線より向こうは w の符号が反転するので、キャリブレーション範囲内の点と同じ符号だけ使う
    ref_w = (np.array([proj.width_m / 2, proj.length_m / 2, 1.0]) @ Hi.T)[2]
    valid = np.isfinite(vv) & (np.sign(w) == np.sign(ref_w))
    with np.errstate(divide="ignore", invalid="ignore"):
        x = np.where(valid, m[..., 0] / w, -1.0)
        y = np.where(valid, m[..., 1] / w, -1.0)
    return cv2.remap(bg, x.astype(np.float32), y.astype(np.float32), cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=EMPTY_BGR)


def birdseye(bg, proj, v_of_display, v_range, u_range, px_per_m, supersample=2):
    """表示座標 -> 射影座標 v の変換 v_of_display で俯瞰図を作る。

    横軸は奥（v 大）が左、縦軸は u 大が上。カメラから奥を見た地図を反時計回りに
    90° 回した向きで、左右は反転しない。
    """
    ppm = px_per_m * supersample
    v_hi, v_lo = v_range
    u_lo, u_hi = u_range
    cols = v_hi - (np.arange(int(round((v_hi - v_lo) * ppm))) + 0.5) / ppm
    rows = u_hi - (np.arange(int(round((u_hi - u_lo) * ppm))) + 0.5) / ppm
    strip = render_strip(bg, proj, v_of_display(cols), rows)
    strip = cv2.resize(strip, (len(cols) // supersample, len(rows) // supersample),
                       interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(strip, cv2.COLOR_BGR2RGB)


def draw_panel(ax, strip, v_range, u_range, width_m, rungs, dash_v, dash_u, title, xlabel):
    v_hi, v_lo = v_range
    u_lo, u_hi = u_range
    ax.imshow(strip, extent=(v_hi, v_lo, u_lo, u_hi), aspect="equal", interpolation="bilinear")
    ax.vlines(rungs, 0, width_m, color=RUNG, linewidth=0.9, alpha=0.85, zorder=3)
    for v, u in zip(dash_v, dash_u):
        ax.plot([v, v], [u - 0.9, u + 0.9], color=DASH, linewidth=2.2, solid_capstyle="round", zorder=4)
    for a, b in zip(dash_v[:-1], dash_v[1:]):
        ax.annotate("", xy=(a, u_hi + 0.35), xytext=(b, u_hi + 0.35), annotation_clip=False,
                    arrowprops={"arrowstyle": "|-|,widthA=0.25,widthB=0.25", "color": DASH,
                                "linewidth": 1.0, "shrinkA": 0, "shrinkB": 0})
        ax.text((a + b) / 2, u_hi + 0.75, "%.1f" % (b - a), ha="center", va="bottom",
                fontsize=8.5, color=INK_2, clip_on=False)
    ax.set_xlim(v_hi, v_lo)
    ax.set_ylim(u_lo, u_hi)
    ax.xaxis.set_major_locator(MultipleLocator(10))
    ax.xaxis.set_minor_locator(MultipleLocator(5))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: "%d" % round(v)))
    ax.yaxis.set_major_locator(MultipleLocator(width_m))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda u, _p: "%g" % u))
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=9, length=3, pad=4, color=AXIS, which="both")
    ax.set_ylabel("横位置 u (m)", color=INK_2, fontsize=9)
    ax.set_xlabel(xlabel, color=INK_2, fontsize=9.5, labelpad=6)
    ax.set_title(title, loc="left", fontsize=11, color=INK, pad=26)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("profile")
    ap.add_argument("out")
    ap.add_argument("--px-per-m", type=float, default=20.0, help="俯瞰図の解像度 [px/m]")
    ap.add_argument("--u-margin-m", type=float, default=2.0, help="キャリブレーション幅の外側に表示する幅 [m]")
    ap.add_argument("--actual-period-m", type=float,
                    help="実測した破線周期 [m]。省略時はキャリブレーションの interval_m × 2 を使用")
    ap.add_argument("--max-dash-length-m", type=float, default=10.0)
    args = ap.parse_args()

    with open(os.path.join(ROOT, "output", "calibrations", args.profile + ".json"), encoding="utf-8") as fh:
        calib = json.load(fh)
    proj = Projection(calib["scale"]["homography"])
    if not proj.ok:
        raise ValueError("射影変換（homography）モードのキャリブレーションが必要です。")

    bg = median_background(args.video)
    dashes, _ = detect_dashes(bg, calib["lines"]["center_line"], proj)
    periods = dash_periods(dashes, max_length_m=args.max_dash_length_m)
    actual = args.actual_period_m if args.actual_period_m is not None else 2.0 * proj.interval_m
    if not np.isfinite(actual) or actual <= 0:
        raise ValueError("実際の破線周期は正の値にしてください。")
    correction = DashCorrection(periods, actual)

    # 周期の計算に使った破線（遠方でつながった塊より手前）だけを描く
    used = dashes.iloc[:len(periods) + 1]
    dash_u, dash_v = proj.to_world(used["near_x"].to_numpy(float), used["near_y"].to_numpy(float))
    dash_v_corrected = correction.corrected_v(dash_v)
    corrected_max = float(correction.grid_corrected_v[-1])

    interval = proj.interval_m
    v_range = (max(proj.length_m, corrected_max) + 2.0, -2.0)
    u_range = (-args.u_margin_m, proj.width_m + args.u_margin_m)

    raw = birdseye(bg, proj, lambda v: v, v_range, u_range, args.px_per_m)

    def inverse_correction(vc):
        inside = (vc >= 0) & (vc <= corrected_max)
        return np.where(inside, np.interp(vc, correction.grid_corrected_v, correction.grid_v), np.nan)

    corrected = birdseye(bg, proj, inverse_correction, v_range, u_range, args.px_per_m)

    fig, axes = plt.subplots(2, 1, figsize=(18, 6.4), dpi=200, gridspec_kw={"hspace": 0.95})
    fig.patch.set_facecolor(SURFACE)
    draw_panel(axes[0], raw, v_range, u_range, proj.width_m,
               np.arange(0, proj.length_m + 1e-6, interval), dash_v, dash_u,
               "① 射影変換のみ — 横線 %g m 間隔、橙は中央線破線の手前端（数字は破線 1 周期 [m]）" % interval,
               "位置 v (m、カメラ側の端 = 0)")
    draw_panel(axes[1], corrected, v_range, u_range, proj.width_m,
               np.arange(0, corrected_max + 1e-6, interval), dash_v_corrected, dash_u,
               "② 破線補正後 — 破線 1 周期を %.2f m に揃えた縦方向、横線は補正座標で %g m 間隔"
               % (actual, interval),
               "破線補正後の位置 (m)")
    axes[1].text((v_range[0] + corrected_max) / 2, proj.width_m / 2, "補正範囲外\n（破線を検出できない）",
                 ha="center", va="center", fontsize=9, color=MUTED)

    basis = "実測値" if args.actual_period_m is not None else "キャリブレーションの interval_m × 2"
    fig.text(0.05, 0.975, "俯瞰図 — キャリブレーション %s" % args.profile, fontsize=14,
             fontweight="bold", color=INK, va="top")
    fig.text(0.05, 0.925,
             "幅 %g m × 長さ %g m の射影変換。背景は動画の中央値画像。基準破線周期 %.2f m（%s）。"
             % (proj.width_m, proj.length_m, actual, basis),
             fontsize=9.3, color=INK_2, va="top")
    fig.text(0.05, 0.02,
             "注: 補正は破線を検出できた 0〜%.0f m（補正後 0〜%.0f m）のみ。破線の実周期が一定であることを前提とします。"
             % (correction.v_max, corrected_max),
             fontsize=8.2, color=MUTED, va="bottom")
    fig.subplots_adjust(left=0.05, right=0.985, top=0.8, bottom=0.12)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    fig.savefig(args.out, facecolor=SURFACE)

    print("基準破線周期: %.3f m" % actual)
    print("補正前の周期: %s" % np.round(np.diff(dash_v), 2).tolist())
    print("補正後の周期: %s" % np.round(np.diff(dash_v_corrected), 2).tolist())
    print(args.out)


if __name__ == "__main__":
    main()
