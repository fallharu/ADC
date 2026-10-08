"""射影キャリブレーションの歪みと、位置による速度の増減を検証する。

3 つの材料を同じ「位置 v [m]」の軸に並べる:
  1. 中央線の破線の周期  : 実際は一定のはず。キャリブレーション上で位置により伸び縮みすれば
                           その位置の距離の縮尺がずれている。
  2. 車両の速度比        : CVAT のキーフレーム間の進行方向速度を、その車両の中間区間
                           （区間中点が 40〜90 m）の中央値で割った値。全車両で同じ位置に
                           同じ増減が出れば測定側の要因、車両ごとに違えば実際の加減速。
  3. 1px あたりの距離    : 画面の y が 1px ずれたときの v の変化。奥ほど粗くなる。

破線は動画から間引いて取ったフレームの中央値画像（車両が消える）で検出する。

使い方:
    python scripts/check_calibration_distortion.py <video> <annotations.xml> <calibration_profile> \
        <出力ディレクトリ> [--fps 30] [--lane-u 6.0]
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
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FuncFormatter, MultipleLocator  # noqa: E402

from analyze_cvat_annotations import (  # noqa: E402
    Projection,
    attach_measure_points,
    load_white_lines,
    parse_cvat_xml,
)
from plot_speed_every_nf import AXIS, GRID, INK, INK_2, MUTED, SERIES, SURFACE, _series_name  # noqa: E402

MID_RANGE_M = (40.0, 90.0)


def median_background(video: str, samples: int = 21) -> np.ndarray:
    cap = cv2.VideoCapture(video)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    for f in np.linspace(total * 0.02, total * 0.98, samples).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
        ok, img = cap.read()
        if ok:
            frames.append(img)
    cap.release()
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def detect_dashes(bg: np.ndarray, center_line, proj: Projection):
    """中央線ポリラインの周囲で白い塊を探し、塊ごとに手前端・奥端の v を返す。"""
    gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
    mask = np.zeros_like(gray)
    cv2.polylines(mask, [np.array(center_line, np.int32)], False, 255, 40)
    blur = cv2.GaussianBlur(gray, (0, 0), 8)
    white = ((gray.astype(int) - blur.astype(int)) > 20) & (gray > 130) & (mask > 0)
    white = cv2.morphologyEx(white.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(white, 8)
    rows = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < 5:
            continue
        ys, xs = np.nonzero(lab == i)
        u, v = proj.to_world(xs.astype(float), ys.astype(float))
        k0, k1 = int(np.argmin(v)), int(np.argmax(v))
        rows.append({"near_x": int(xs[k0]), "near_y": int(ys[k0]), "far_x": int(xs[k1]),
                     "far_y": int(ys[k1]), "v_near_m": float(v[k0]), "v_far_m": float(v[k1]),
                     "length_m": float(v[k1] - v[k0]), "area_px": int(stats[i, cv2.CC_STAT_AREA])})
    dashes = pd.DataFrame(rows).sort_values("v_near_m").reset_index(drop=True)
    return dashes, white.astype(bool)


def dash_periods(dashes: pd.DataFrame, max_length_m: float) -> pd.DataFrame:
    """隣り合う破線の手前端どうしの距離。遠方で塊がつながったもの（長すぎる塊）以降は使わない。"""
    ok = dashes["length_m"] <= max_length_m
    cut = int(np.argmin(ok.values)) if not ok.all() else len(dashes)
    d = dashes.iloc[:cut]
    return pd.DataFrame({
        "v_from_m": d["v_near_m"].values[:-1],
        "v_to_m": d["v_near_m"].values[1:],
        "period_m": np.diff(d["v_near_m"].values),
        "image_y": d["near_y"].values[:-1],
    })


def keyframe_speeds(df: pd.DataFrame, proj: Projection, fps: float) -> pd.DataFrame:
    rows = []
    for tid, g in df[df["is_keyframe"] == 1].groupby("track_id"):
        g = g.sort_values("frame_num")
        for a, b in zip(g.itertuples(), list(g.itertuples())[1:]):
            if not (0 <= a.v <= proj.length_m and 0 <= b.v <= proj.length_m):
                continue
            dt = (b.frame_num - a.frame_num) / fps
            rows.append({"track_id": tid, "label": a.label, "frame_from": a.frame_num,
                         "frame_to": b.frame_num, "v_from_m": a.v, "v_to_m": b.v,
                         "y2_from": a.y2, "y2_to": b.y2,
                         "speed_long_km_h": abs(b.v - a.v) / dt * 3.6,
                         "speed_total_km_h": np.hypot(b.u - a.u, b.v - a.v) / dt * 3.6})
    out = pd.DataFrame(rows)
    mid = (out["v_from_m"] + out["v_to_m"]) / 2
    base = (out[mid.between(*MID_RANGE_M)].groupby("track_id")["speed_long_km_h"].median())
    out["mid_speed_km_h"] = out["track_id"].map(base)
    out["ratio_to_mid"] = out["speed_long_km_h"] / out["mid_speed_km_h"]
    return out


def meters_per_pixel(proj: Projection, lane_u: float) -> pd.DataFrame:
    Hi = np.linalg.inv(proj.H)
    rows = []
    for v in np.arange(0, proj.length_m + 1e-6, 5.0):
        p = np.array([lane_u, v, 1.0]) @ Hi.T
        x, y = p[0] / p[2], p[1] / p[2]
        _, v2 = proj.to_world([x], [y + 1.0])
        rows.append({"v_m": v, "image_x": x, "image_y": y, "m_per_px": abs(v - float(v2[0]))})
    return pd.DataFrame(rows)


def _style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, linewidth=1, linestyle="-", zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9, length=0, pad=5)


def plot(periods, speeds, mpp, length_m, out_path):
    fig, axes = plt.subplots(3, 1, figsize=(11, 9.6), dpi=200, sharex=True,
                             gridspec_kw={"height_ratios": [1, 1.35, 0.8], "hspace": 0.55})
    fig.patch.set_facecolor(SURFACE)
    for ax in axes:
        _style(ax)

    # 1. 破線の周期
    ax = axes[0]
    ref = periods.loc[periods["v_to_m"] <= 80, "period_m"].median()
    ax.axhline(ref, color=MUTED, linewidth=1, zorder=1)
    ax.text(length_m, ref, " 0〜80 m の中央値 %.1f m" % ref, color=INK_2, fontsize=8.5, va="bottom")
    for r in periods.itertuples():
        ax.plot([r.v_from_m, r.v_to_m], [r.period_m, r.period_m], color=INK_2, linewidth=2,
                solid_capstyle="round", zorder=3)
    ax.set_ylim(0, max(14, periods["period_m"].max() + 2))
    ax.yaxis.set_major_locator(MultipleLocator(4))
    ax.set_ylabel("m", color=INK_2, fontsize=9)
    ax.set_title("① 中央線の破線 1 周期の長さ（キャリブレーション上）— 実際は一定のはず",
                 loc="left", fontsize=11, color=INK, pad=10)

    # 2. 車両の速度比
    ax = axes[1]
    ax.axhline(1.0, color=MUTED, linewidth=1, zorder=1)
    # 速度グラフと同じ色順（自転車 -> 車 ID 順）
    order = (speeds.drop_duplicates("track_id")
             .assign(_car=lambda x: x["label"].str.lower() != "bicycle")
             .sort_values(["_car", "track_id"]))
    handles = []
    for i, r0 in enumerate(order.itertuples()):
        color = SERIES[i % len(SERIES)]
        for r in speeds[speeds["track_id"] == r0.track_id].itertuples():
            ax.plot([r.v_from_m, r.v_to_m], [r.ratio_to_mid, r.ratio_to_mid], color=color,
                    linewidth=2, solid_capstyle="round", zorder=3)
        handles.append(Line2D([0], [0], color=color, linewidth=2.5,
                              label=_series_name("%s_%d_km_h" % (r0.label, r0.track_id))))
    ax.set_ylim(0.5, 1.5)
    ax.yaxis.set_major_locator(MultipleLocator(0.25))
    ax.set_ylabel("倍", color=INK_2, fontsize=9)
    ax.set_title("② 各車両の速度 ÷ その車両の中間区間（%d〜%d m）の速度 — キーフレーム間ごと"
                 % MID_RANGE_M, loc="left", fontsize=11, color=INK, pad=24)
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=len(handles),
              frameon=False, fontsize=9, labelcolor=INK_2, handlelength=1.6, columnspacing=1.4,
              borderaxespad=0.2)

    # 3. 1px あたりの距離
    ax = axes[2]
    ax.plot(mpp["v_m"], mpp["m_per_px"], color=INK_2, linewidth=2, zorder=3)
    ax.set_ylim(0, max(3.5, mpp["m_per_px"].max() * 1.1))
    ax.yaxis.set_major_locator(MultipleLocator(1))
    ax.set_ylabel("m / px", color=INK_2, fontsize=9)
    ax.set_title("③ 画面の y が 1px ずれたときの位置の誤差（車線内）", loc="left",
                 fontsize=11, color=INK, pad=10)

    ax.set_xlim(length_m + 2, -2)
    ax.xaxis.set_major_locator(MultipleLocator(10))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: "%d" % round(v)))
    ax.set_xlabel("位置（m、カメラ側の端 = 0）　進行方向 →", color=INK_2, fontsize=10, labelpad=8)

    fig.text(0.06, 0.975, "キャリブレーションの歪みと位置による速度の増減", fontsize=14,
             fontweight="bold", color=INK, va="top")
    fig.subplots_adjust(left=0.07, right=0.97, top=0.9, bottom=0.07)
    fig.savefig(out_path, facecolor=SURFACE)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("xml")
    ap.add_argument("profile")
    ap.add_argument("outdir")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--lane-u", type=float, default=6.0, help="1px 誤差を測る横位置 u [m]")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    with open(os.path.join(ROOT, "output", "calibrations", args.profile + ".json"), encoding="utf-8") as fh:
        calib = json.load(fh)
    proj = Projection(calib["scale"]["homography"])

    bg = median_background(args.video)
    dashes, white = detect_dashes(bg, calib["lines"]["center_line"], proj)
    periods = dash_periods(dashes, max_length_m=10.0)

    vis = bg.copy()
    vis[white] = (0, 0, 255)
    for r in dashes.itertuples():
        cv2.circle(vis, (r.near_x, r.near_y), 3, (0, 255, 255), -1)
    cv2.imwrite(os.path.join(args.outdir, "dash_detection.png"), vis)

    df, _ = parse_cvat_xml(args.xml)
    df = attach_measure_points(df[df["is_held"] == 0], load_white_lines(calib))
    df["u"], df["v"] = proj.to_world(df["measure_x"].values, df["measure_y"].values)
    speeds = keyframe_speeds(df, proj, args.fps)
    mpp = meters_per_pixel(proj, args.lane_u)

    for name, frame in (("dashes.csv", dashes), ("dash_periods.csv", periods),
                        ("keyframe_interval_speeds.csv", speeds), ("meters_per_pixel.csv", mpp)):
        frame.round(3).to_csv(os.path.join(args.outdir, name), index=False, encoding="utf-8-sig")
    plot(periods, speeds, mpp, proj.length_m, os.path.join(args.outdir, "distortion_check.png"))
    print(args.outdir)


if __name__ == "__main__":
    main()
