"""speed_every_Nf.csv / speed_every_Nm.csv（cvat_speed_clearance_overtake.py の出力）をグラフにする。

  speed_every_Nf.csv : 横軸 = 動画時間、縦軸 = 速度中央値 [km/h] の折れ線
  speed_every_Nm.csv : 横軸 = 位置 [m]、縦軸 = 区間速度 [km/h] の階段状の線
同じフォルダに overtake_events.csv があれば追い越し（時刻 / 自転車の位置）を縦線で重ねる。

使い方:
    python scripts/plot_speed_every_nf.py <speed_every_6f.csv | speed_every_5m.csv> [--out <png>] [--title <文字列>]
"""
from __future__ import annotations

import argparse
import os
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FuncFormatter, MultipleLocator  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
# カテゴリ色は固定順（自転車 -> 車1 -> 車2 ...）。validate_palette.js で検証済みの 5 色
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Yu Gothic", "Meiryo", "Noto Sans JP", "DejaVu Sans"]


def _series_name(col: str) -> str:
    m = re.match(r"(.+)_(\d+)_km_h$", col)
    if not m:
        return col
    label, tid = m.group(1).lower(), m.group(2)
    if label in {"bicycle", "bike", "cyclist"}:
        return "自転車 %s" % tid
    if label == "car":
        return "車 %s" % tid
    return "%s %s" % (label, tid)


def _mmss(sec: float, _pos=None) -> str:
    m, s = divmod(int(round(sec)), 60)
    return "%d:%02d" % (m, s)


def _stairs(df: pd.DataFrame, col: str):
    """区間ごとの値を階段状の線にする座標列。値のない区間で線を切る。"""
    lo = df[["section_from_m", "section_to_m"]].min(axis=1)
    hi = df[["section_from_m", "section_to_m"]].max(axis=1)
    xs, ys, prev_hi = [], [], None
    for l, h, val in sorted(zip(lo, hi, df[col])):
        if pd.isna(val):
            continue
        if prev_hi is not None and l != prev_hi:
            xs.append(float("nan"))
            ys.append(float("nan"))
        xs += [l, h]
        ys += [val, val]
        prev_hi = h
    return xs, ys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--out")
    ap.add_argument("--title")
    args = ap.parse_args()

    df = pd.read_csv(args.csv, encoding="utf-8-sig")
    cols = [c for c in df.columns if c.endswith("_km_h")]
    name = os.path.basename(args.csv)
    linear = "_linear" in name
    by_section = "section_from_m" in df.columns
    out = args.out or os.path.splitext(args.csv)[0] + ".png"

    events_path = os.path.join(os.path.dirname(args.csv), "overtake_events.csv")
    events = pd.read_csv(events_path, encoding="utf-8-sig") if os.path.exists(events_path) else None
    has_events = events is not None and not events.empty

    fig, ax = plt.subplots(figsize=(11, 5.6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ymax = max(20.0, (df[cols].max().max() // 20 + 1) * 20)

    if by_section:
        # 横軸は位置。追い越しは自転車の位置に縦線を引く
        event_x = events["bike_position_v_m"] if has_events else pd.Series(dtype=float)
        x_range = [df["section_from_m"].min(), df["section_from_m"].max(),
                   df["section_to_m"].min(), df["section_to_m"].max(), *event_x]
        pad = 1.0
    else:
        # 追い越し時刻が速度データの範囲外でも縦線が描けるよう横軸に含める
        event_x = events["overtake_time_s"] if has_events else pd.Series(dtype=float)
        x_range = [df["video_time_s"].min(), df["video_time_s"].max(), *event_x]
        pad = 0.3

    if has_events:
        for r, x in zip(events.itertuples(), event_x):
            ax.axvline(x, color=MUTED, linewidth=1, zorder=1)
            ax.text(x, ymax, "追い越し%d\n車 %d" % (r.event_no, r.car_track_id),
                    ha="center", va="bottom", fontsize=8.5, color=INK_2, linespacing=1.2)

    handles = []
    for i, col in enumerate(cols):
        color = SERIES[i % len(SERIES)]
        xs, ys = _stairs(df, col) if by_section else (df["video_time_s"], df[col])
        ax.plot(xs, ys, color=color, linewidth=2, solid_capstyle="round",
                solid_joinstyle="round", zorder=3)
        handles.append(Line2D([0], [0], color=color, linewidth=2.5, label=_series_name(col)))

    ax.set_ylim(0, ymax)
    ax.yaxis.set_major_locator(MultipleLocator(20))
    ax.grid(axis="y", color=GRID, linewidth=1, linestyle="-", zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9, length=0, pad=6)
    ax.set_ylabel("速度（km/h）", color=INK_2, fontsize=10, labelpad=8)

    if by_section:
        section = re.search(r"every_([\d.]+)m", name)
        section = section.group(1) if section else "N"
        toward_near = df["section_from_m"].iloc[0] > df["section_to_m"].iloc[0]
        # 版どうしで比べやすいよう、横軸は 0 m から 10 m 単位で切り上げた位置までにそろえる
        lo = min(0.0, min(x_range)) - pad
        hi = -(-max(x_range) // 10) * 10 + pad
        # 進行方向が左 -> 右になるよう、手前へ向かう場合は軸を反転する
        ax.set_xlim((hi, lo) if toward_near else (lo, hi))
        ax.xaxis.set_major_locator(MultipleLocator(10))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _pos: "%d" % round(v)))
        ax.set_xlabel("位置（m、カメラ側の端 = 0）　進行方向 →", color=INK_2, fontsize=10, labelpad=8)
        title = "%sm区間ごとの速度%s" % (section, "（キーフレーム間を路面上で線形補間）" if linear else "")
        subtitle = "区間長 ÷ 通過時間 ・ 縦線は追い越し位置（自転車の位置）"
    else:
        step = re.search(r"every_(\d+)f", name)
        step = step.group(1) if step else "N"
        ax.set_xlim(min(x_range) - pad, max(x_range) + pad)
        ax.xaxis.set_major_locator(MultipleLocator(2))
        ax.xaxis.set_major_formatter(FuncFormatter(_mmss))
        ax.set_xlabel("動画時間（分:秒）", color=INK_2, fontsize=10, labelpad=8)
        title = "%sフレームごとの速度（中央値%s）" % (
            step, "・キーフレーム間を路面上で線形補間" if linear else "")
        subtitle = "測定区間（奥行 0–150 m）内のみ ・ 縦線は追い越し時刻"

    fig.text(0.06, 0.965, args.title or title, fontsize=14, fontweight="bold", color=INK, va="top")
    fig.text(0.06, 0.915, subtitle, fontsize=9.5, color=INK_2, va="top")
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.055, 0.875),
               ncol=len(handles), frameon=False, fontsize=9.5, labelcolor=INK_2,
               handlelength=1.6, columnspacing=1.6)

    fig.subplots_adjust(left=0.06, right=0.98, top=0.72, bottom=0.12)
    fig.savefig(out, facecolor=SURFACE)
    print(out)


if __name__ == "__main__":
    main()
