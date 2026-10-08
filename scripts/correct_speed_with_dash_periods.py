"""中央線の破線周期を使い、縦方向の速度を相対補正する。

破線の実際の周期が一定であると仮定する。位置 v で射影変換後の破線周期を
p(v)、実際の周期を D とすると、縦方向の局所補正係数は D / p(v) になる。
補正座標はこの係数を積分して作るため、区間速度には端点間の補正座標差を使う。

--actual-period-m を省略した場合、0--80 m における算出周期の中央値を D とする。
これは基準区間の絶対速度を保った「相対補正」。実測した破線周期を指定すれば、
絶対スケールもその値へ合わせられる。
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
from scipy.integrate import cumulative_trapezoid  # noqa: E402
from scipy.interpolate import PchipInterpolator  # noqa: E402
from scipy.ndimage import gaussian_filter1d  # noqa: E402


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


def track_name(label: object, track_id: object) -> str:
    if str(label).lower() in {"bicycle", "bike", "cyclist"}:
        return f"自転車 {int(track_id)}"
    if str(label).lower() == "car":
        return f"車 {int(track_id)}"
    return f"{label} {int(track_id)}"


class DashCorrection:
    """推定座標 v を破線周期で補正した座標へ変換する。"""

    def __init__(self, periods: pd.DataFrame, actual_period_m: float) -> None:
        self.actual_period_m = actual_period_m
        centers = ((periods["v_from_m"] + periods["v_to_m"]) / 2).to_numpy(float)
        values = periods["period_m"].to_numpy(float)
        order = np.argsort(centers)
        centers, values = centers[order], values[order]
        self.v_min = 0.0
        self.v_max = float(periods["v_to_m"].max())
        # 破線の先頭より手前は最初の周期を維持し、範囲外への外挿は行わない。
        x = np.r_[self.v_min, centers, self.v_max]
        y = np.r_[values[0], values, values[-1]]
        unique = pd.DataFrame({"x": x, "y": y}).groupby("x", as_index=False)["y"].mean()
        self.period_at = PchipInterpolator(unique["x"], unique["y"], extrapolate=False)
        self.grid_v = np.linspace(self.v_min, self.v_max, 5001)
        self.grid_period = self.period_at(self.grid_v)
        self.grid_factor = self.actual_period_m / self.grid_period
        self.grid_corrected_v = cumulative_trapezoid(
            self.grid_factor, self.grid_v, initial=0.0
        )

    def corrected_v(self, v: pd.Series | np.ndarray) -> np.ndarray:
        v_array = np.asarray(v, dtype=float)
        result = np.full(v_array.shape, np.nan, dtype=float)
        valid = (v_array >= self.v_min) & (v_array <= self.v_max)
        result[valid] = np.interp(v_array[valid], self.grid_v, self.grid_corrected_v)
        return result

    def factor_at(self, v: pd.Series | np.ndarray) -> np.ndarray:
        v_array = np.asarray(v, dtype=float)
        result = np.full(v_array.shape, np.nan, dtype=float)
        valid = (v_array >= self.v_min) & (v_array <= self.v_max)
        result[valid] = self.actual_period_m / self.period_at(v_array[valid])
        return result


def correct_keyframe_speeds(speed: pd.DataFrame, correction: DashCorrection) -> pd.DataFrame:
    out = speed.copy()
    out["v_from_dash_corrected_m"] = correction.corrected_v(out["v_from_m"])
    out["v_to_dash_corrected_m"] = correction.corrected_v(out["v_to_m"])
    out["dash_correction_covered"] = (
        out[["v_from_dash_corrected_m", "v_to_dash_corrected_m"]].notna().all(axis=1)
    )
    original_distance = (out["v_to_m"] - out["v_from_m"]).abs()
    corrected_distance = (out["v_to_dash_corrected_m"] - out["v_from_dash_corrected_m"]).abs()
    out["longitudinal_distance_dash_corrected_m"] = corrected_distance
    out["dash_speed_factor"] = corrected_distance / original_distance
    out["speed_long_dash_corrected_km_h"] = out["speed_long_km_h"] * out["dash_speed_factor"]
    return out


def corrected_section_speeds(per_frame: pd.DataFrame, correction: DashCorrection,
                             section_m: float) -> pd.DataFrame:
    """補正座標を基準に、通過時刻から section_m ごとの縦速度を計算する。"""
    data = per_frame.copy()
    data["bev_v_dash_corrected_m"] = correction.corrected_v(data["bev_v_m"])
    data = data.dropna(subset=["bev_v_dash_corrected_m", "time_s"])
    if data.empty:
        return pd.DataFrame(columns=["section_from_m", "section_to_m"])

    max_v = float(data["bev_v_dash_corrected_m"].max())
    edges = np.arange(0, np.floor(max_v / section_m) * section_m + section_m, section_m)
    columns: dict[str, pd.Series] = {}
    directions: list[float] = []
    for track_id, group in data.groupby("track_id"):
        group = group.sort_values("frame_num")
        v = group["bev_v_dash_corrected_m"].to_numpy(float)
        t = group["time_s"].to_numpy(float)
        if len(v) < 2 or np.isclose(v[-1], v[0]):
            continue
        forward = -1.0 if v[-1] < v[0] else 1.0
        directions.append(forward)
        times: dict[int, float] = {}
        for index, boundary in enumerate(edges):
            side = forward * (v - boundary)
            hit = np.flatnonzero(side >= 0)
            if hit.size == 0 or hit[0] == 0:
                continue
            i = int(hit[0])
            denominator = side[i] - side[i - 1]
            if np.isclose(denominator, 0):
                continue
            fraction = -side[i - 1] / denominator
            times[index] = t[i - 1] + fraction * (t[i] - t[i - 1])
        values: dict[int, float] = {}
        for index in range(len(edges) - 1):
            if index in times and index + 1 in times:
                dt = abs(times[index + 1] - times[index])
                if dt > 0:
                    values[index] = section_m / dt * 3.6
        label = group["label"].iloc[0]
        columns[f"{label}_{int(track_id)}_km_h"] = pd.Series(values, dtype=float)

    result = pd.DataFrame(columns, index=range(len(edges) - 1)).dropna(how="all")
    toward_near = (directions[0] if directions else -1.0) < 0
    if result.empty:
        return pd.DataFrame(columns=["section_from_m", "section_to_m", *columns])
    if toward_near:
        result.insert(0, "section_from_m", edges[result.index + 1])
        result.insert(1, "section_to_m", edges[result.index])
        result = result.sort_values("section_from_m", ascending=False)
    else:
        result.insert(0, "section_from_m", edges[result.index])
        result.insert(1, "section_to_m", edges[result.index + 1])
    return result.reset_index(drop=True)


def corrected_time_speeds(per_frame: pd.DataFrame, correction: DashCorrection,
                          step_s: float, smoothing_s: float) -> pd.DataFrame:
    """破線補正座標で 0.2 秒窓の縦速度を作り、ガウス平滑化する。"""
    data = per_frame.copy()
    data["bev_v_dash_corrected_m"] = correction.corrected_v(data["bev_v_m"])
    rows: list[dict[str, float | int | str]] = []
    for track_id, group in data.groupby("track_id"):
        group = group.dropna(subset=["time_s", "bev_v_m", "bev_v_dash_corrected_m"])
        group = group.sort_values("time_s")
        if len(group) < 2:
            continue
        times = group["time_s"].to_numpy(float)
        estimated_v = group["bev_v_m"].to_numpy(float)
        corrected_v = group["bev_v_dash_corrected_m"].to_numpy(float)
        first = np.ceil(times[0] / step_s - 1e-9) * step_s
        last = np.floor((times[-1] - step_s) / step_s + 1e-9) * step_s
        if last < first:
            continue
        starts = np.arange(first, last + step_s * 0.5, step_s)
        before = np.interp(starts, times, corrected_v)
        after = np.interp(starts + step_s, times, corrected_v)
        speeds = np.abs(after - before) / step_s * 3.6
        mid_time = starts + step_s / 2
        for time_s, speed, v_est, v_corrected in zip(
            mid_time, speeds, np.interp(mid_time, times, estimated_v),
            np.interp(mid_time, times, corrected_v),
        ):
            rows.append({
                "track_id": int(track_id),
                "label": str(group["label"].iloc[0]),
                "video_time_s": float(time_s),
                "estimated_position_m": float(v_est),
                "dash_corrected_position_m": float(v_corrected),
                "speed_long_dash_corrected_km_h": float(speed),
            })
    result = pd.DataFrame(rows)
    if result.empty:
        return result

    # 1 秒相当の平滑化。0.2 秒ごとの値はそのまま CSV にも残す。
    sigma = max(smoothing_s / step_s / 2.0, 0.01)
    result["speed_long_dash_corrected_smooth_km_h"] = np.nan
    for track_id, index in result.groupby("track_id").groups.items():
        values = result.loc[index, "speed_long_dash_corrected_km_h"].to_numpy(float)
        result.loc[index, "speed_long_dash_corrected_smooth_km_h"] = gaussian_filter1d(
            values, sigma=sigma, mode="nearest"
        )
    return result


def plot_time_speeds(time_speeds: pd.DataFrame, step_s: float, smoothing_s: float,
                     output: Path) -> None:
    fig, ax = plt.subplots(figsize=(11.5, 6.4), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    style_axis(ax)
    handles: list[Line2D] = []
    for i, (track_id, group) in enumerate(time_speeds.groupby("track_id")):
        color = SERIES[i % len(SERIES)]
        group = group.sort_values("video_time_s")
        # 0.2 秒値を薄く残し、PCHIP で滑らかに表示する。
        x = group["video_time_s"].to_numpy(float)
        y = group["speed_long_dash_corrected_smooth_km_h"].to_numpy(float)
        if len(x) >= 3:
            smooth_x = np.linspace(x[0], x[-1], max(300, len(x) * 4))
            smooth_y = PchipInterpolator(x, y)(smooth_x)
        else:
            smooth_x, smooth_y = x, y
        ax.plot(x, group["speed_long_dash_corrected_km_h"], color=color, alpha=0.18,
                linewidth=1.0, zorder=2)
        ax.plot(smooth_x, smooth_y, color=color, linewidth=2.8,
                solid_capstyle="round", zorder=4)
        handles.append(Line2D([0], [0], color=color, linewidth=2.8,
                              label=track_name(group["label"].iloc[0], track_id)))

    ax.set_ylabel("破線補正後の縦方向速度 (km/h)", color=INK_2, fontsize=10, labelpad=8)
    ax.set_xlabel("動画時刻 (秒)", color=INK_2, fontsize=10, labelpad=8)
    ax.xaxis.set_major_locator(MultipleLocator(2))
    ax.set_ylim(bottom=0)
    ax.legend(handles=handles, loc="upper left", frameon=False, fontsize=9.5,
              labelcolor=INK_2, handlelength=1.8, ncol=len(handles))
    fig.text(0.08, 0.97, "破線補正後の速度（0.2 秒ごと・平滑表示）", fontsize=14,
             fontweight="bold", color=INK, va="top")
    fig.text(0.08, 0.925,
             f"薄線: {step_s:.1f} 秒窓の速度値　／　太線: {smoothing_s:.1f} 秒相当のガウス平滑化（破線検出範囲内のみ）",
             fontsize=9.3, color=INK_2, va="top")
    fig.text(0.08, 0.035,
             "注: 中央線の破線周期が一定であり、その縦方向スケールが対象車両にも適用できることを前提とします。",
             fontsize=8.2, color=MUTED, va="bottom")
    fig.subplots_adjust(left=0.08, right=0.98, top=0.86, bottom=0.12)
    fig.savefig(output, facecolor=SURFACE)


def plot_comparison(corrected: pd.DataFrame, correction: DashCorrection,
                    reference_period: float, output: Path) -> None:
    fig, (ax_factor, ax_speed) = plt.subplots(
        2, 1, figsize=(11.5, 8.2), dpi=200, sharex=True,
        gridspec_kw={"height_ratios": [0.85, 1.35], "hspace": 0.38},
    )
    fig.patch.set_facecolor(SURFACE)
    for ax in (ax_factor, ax_speed):
        style_axis(ax)

    ax_factor.axhline(1.0, color=MUTED, linewidth=1, zorder=1)
    ax_factor.plot(correction.grid_v, correction.grid_factor, color=INK, linewidth=2.8,
                   solid_capstyle="round", zorder=3)
    ax_factor.set_ylim(0.8, max(1.65, float(np.nanmax(correction.grid_factor)) * 1.08))
    ax_factor.yaxis.set_major_locator(MultipleLocator(0.2))
    ax_factor.set_ylabel("速度補正係数", color=INK_2, fontsize=10, labelpad=8)
    ax_factor.set_title("① 破線周期から得た縦方向の補正係数", loc="left",
                        fontsize=11, color=INK, pad=10)
    ax_factor.text(correction.v_max - 6, 1.02, f"基準破線周期: {reference_period:.2f} m", color=INK_2,
                   fontsize=8.5, ha="left", va="bottom")

    handles: list[Line2D] = [
        Line2D([0], [0], color=INK_2, linestyle=(0, (4, 2)), linewidth=1.8,
               label="補正前"),
        Line2D([0], [0], color=INK, linewidth=2.8, label="破線補正後"),
    ]
    tracks = corrected[corrected["dash_correction_covered"]].drop_duplicates("track_id")
    for i, track in enumerate(tracks.itertuples(index=False)):
        color = SERIES[i % len(SERIES)]
        rows = corrected[(corrected["track_id"] == track.track_id)
                         & corrected["dash_correction_covered"]].copy()
        rows["position_m"] = (rows["v_from_m"] + rows["v_to_m"]) / 2
        rows = rows.sort_values("position_m")
        ax_speed.plot(rows["position_m"], rows["speed_long_km_h"], color=color,
                      alpha=0.72, linewidth=1.7, linestyle=(0, (4, 2)), marker="o",
                      markersize=3.5, zorder=3)
        ax_speed.plot(rows["position_m"], rows["speed_long_dash_corrected_km_h"], color=color,
                      linewidth=2.7, marker="o", markersize=3.8, zorder=4)
        handles.append(Line2D([0], [0], color=color, linewidth=2.5,
                              label=track_name(track.label, track.track_id)))
    ax_speed.set_ylabel("縦方向速度 (km/h)", color=INK_2, fontsize=10, labelpad=8)
    ax_speed.set_title("② キーフレーム区間の速度: 補正前（破線）と補正後（実線）", loc="left",
                       fontsize=11, color=INK, pad=29)
    ax_speed.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.0),
                    ncol=len(handles), frameon=False, fontsize=8.5, labelcolor=INK_2,
                    handlelength=2, columnspacing=1.1, borderaxespad=0.2)
    ax_speed.set_xlim(correction.v_max + 2, -2)
    ax_speed.xaxis.set_major_locator(MultipleLocator(10))
    ax_speed.set_xlabel("補正前の位置 (m、カメラ側の端 = 0)    進行方向 →", color=INK_2,
                        fontsize=10, labelpad=8)

    fig.text(0.08, 0.975, "中央線の破線を使った縦方向速度の補正", fontsize=14,
             fontweight="bold", color=INK, va="top")
    fig.text(0.08, 0.944,
             "破線が検出できる範囲だけを補正。補正係数 = 基準破線周期 ÷ その位置での算出破線周期。",
             fontsize=9.3, color=INK_2, va="top")
    fig.text(0.08, 0.035,
             "注: 破線の実周期が一定であること、中心線上の縦方向スケールが対象車両にも適用できることを前提とします。",
             fontsize=8.2, color=MUTED, va="bottom")
    fig.subplots_adjust(left=0.08, right=0.97, top=0.89, bottom=0.11)
    fig.savefig(output, facecolor=SURFACE)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path, help="speed_per_frame.csv のある出力ディレクトリ")
    parser.add_argument("--dash-dir", type=Path, help="dash_periods.csv のあるディレクトリ")
    parser.add_argument("--reference-end-m", type=float, default=80.0)
    parser.add_argument("--actual-period-m", type=float,
                        help="実測した破線周期 [m]。省略時は基準区間の算出中央値を使用")
    parser.add_argument("--section-m", type=float, default=5.0)
    parser.add_argument("--plot-out", type=Path, help="比較図の出力先")
    parser.add_argument("--time-step-s", type=float, default=0.2,
                        help="時系列速度の集計窓 [秒]（既定: 0.2）")
    parser.add_argument("--smoothing-s", type=float, default=1.0,
                        help="時系列速度の平滑化の強さ [秒]（既定: 1.0）")
    args = parser.parse_args()

    output_dir = args.output_dir
    dash_dir = args.dash_dir or output_dir / "distortion_check"
    periods = pd.read_csv(dash_dir / "dash_periods.csv", encoding="utf-8-sig")
    keyframes = pd.read_csv(dash_dir / "keyframe_interval_speeds.csv", encoding="utf-8-sig")
    per_frame = pd.read_csv(output_dir / "speed_per_frame.csv", encoding="utf-8-sig")
    reference_period = periods.loc[periods["v_to_m"] <= args.reference_end_m, "period_m"].median()
    actual_period = args.actual_period_m if args.actual_period_m is not None else reference_period
    if not np.isfinite(actual_period) or actual_period <= 0:
        raise ValueError("実際の破線周期は正の値にしてください。")

    correction = DashCorrection(periods, float(actual_period))
    corrected_keyframes = correct_keyframe_speeds(keyframes, correction)
    corrected_sections = corrected_section_speeds(per_frame, correction, args.section_m)
    corrected_time = corrected_time_speeds(
        per_frame, correction, args.time_step_s, args.smoothing_s
    )

    profile = pd.DataFrame({
        "estimated_position_m": correction.grid_v,
        "estimated_dash_period_m": correction.grid_period,
        "dash_speed_factor": correction.grid_factor,
        "dash_corrected_position_m": correction.grid_corrected_v,
    })
    corrected_keyframes.round(3).to_csv(
        dash_dir / "keyframe_interval_speeds_dash_corrected.csv", index=False, encoding="utf-8-sig"
    )
    corrected_sections.round(3).to_csv(
        dash_dir / "speed_every_5m_dash_corrected.csv", index=False, encoding="utf-8-sig"
    )
    profile.round(5).to_csv(dash_dir / "dash_speed_correction_profile.csv", index=False,
                            encoding="utf-8-sig")
    corrected_time.round(3).to_csv(
        dash_dir / "speed_every_0p2s_dash_corrected.csv", index=False, encoding="utf-8-sig"
    )
    plot_comparison(corrected_keyframes, correction, float(actual_period),
                    args.plot_out or dash_dir / "dash_speed_correction_comparison.png")
    if not corrected_time.empty:
        plot_time_speeds(
            corrected_time, args.time_step_s, args.smoothing_s,
            dash_dir / "dash_corrected_speed_0p2s_smooth.png"
        )
    print(f"補正対象範囲: {correction.v_min:.3f}-{correction.v_max:.3f} m")
    print(f"基準破線周期: {actual_period:.3f} m")
    print(dash_dir)


if __name__ == "__main__":
    main()
