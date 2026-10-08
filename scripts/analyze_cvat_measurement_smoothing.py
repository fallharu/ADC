"""Evaluate BBOX-aware measurement-point smoothing on a CVAT track export."""
from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import cv2  # noqa: E402
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.signal import savgol_filter  # noqa: E402

from Source_code.modules.measure_points import stabilize_measure_points  # noqa: E402


INK = "#172033"
MUTED = "#687386"
GRID = "#DDE3EC"
BLUE = "#2F6FED"
ORANGE = "#F08C46"
GREEN = "#20A474"
RED = "#D95852"
PURPLE = "#7950B3"
SURFACE = "#F6F8FC"


def read_cvat_tracks(xml_path: str) -> pd.DataFrame:
    root = ET.parse(xml_path).getroot()
    rows: list[dict[str, object]] = []
    for track in root.findall("track"):
        track_id = int(track.get("id", "-1"))
        label = (track.get("label") or "unknown").strip().lower()
        for box in track.findall("box"):
            if box.get("outside", "0") == "1":
                continue
            rows.append(
                {
                    "track_id": track_id,
                    "label": label,
                    "frame_num": int(box.get("frame", "0")),
                    "x1": float(box.get("xtl", "nan")),
                    "y1": float(box.get("ytl", "nan")),
                    "x2": float(box.get("xbr", "nan")),
                    "y2": float(box.get("ybr", "nan")),
                    "keyframe": int(box.get("keyframe", "0")),
                    "occluded": int(box.get("occluded", "0")),
                }
            )
    frame = pd.DataFrame(rows).sort_values(["track_id", "frame_num"]).reset_index(drop=True)
    if frame.empty:
        raise ValueError("The CVAT XML contains no visible track boxes")
    return frame


def add_measure_points(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    center_x = (result["x1"] + result["x2"]) / 2.0
    bicycle = result["label"].str.contains(r"bicycle|bike|cyclist", regex=True)
    # Match the current application fallback: bicycles use bottom-center;
    # other vehicles use the bottom-right corner when no road line is supplied.
    result["measure_x"] = np.where(bicycle, center_x, result["x2"])
    result["measure_y"] = result["y2"]
    result["raw_bbox_width_px"] = result["x2"] - result["x1"]
    result["raw_bbox_height_px"] = result["y2"] - result["y1"]
    return result


def mark_active_motion(frame: pd.DataFrame) -> pd.DataFrame:
    """Exclude CVAT's unchanged tail after the last geometric box update."""

    result = frame.copy()
    result["active_motion"] = False
    coordinate_columns = ["x1", "y1", "x2", "y2"]
    for _track_id, track in result.groupby("track_id", sort=False):
        track = track.sort_values("frame_num")
        coordinates = track[coordinate_columns].to_numpy(dtype=float)
        changed = np.flatnonzero(np.any(np.abs(np.diff(coordinates, axis=0)) > 1e-6, axis=1))
        active_count = int(changed[-1] + 2) if len(changed) else 1
        result.loc[track.index[:active_count], "active_motion"] = True
    return result


def add_legacy_smoothing(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    result = frame.copy()
    for axis in ("x", "y"):
        source = f"measure_{axis}"
        target = f"legacy_measure_{axis}"
        result[target] = result.groupby("track_id")[source].transform(
            lambda values: values.rolling(
                window,
                center=True,
                min_periods=window,
            ).median()
        )
        result[target] = result[target].fillna(result[source])
    return result


def interval_speed(
    track: pd.DataFrame,
    x_column: str,
    y_column: str,
    fps: float,
    period: int,
) -> np.ndarray:
    dx = track[x_column].diff(periods=period).to_numpy(dtype=float)
    dy = track[y_column].diff(periods=period).to_numpy(dtype=float)
    frame_delta = track["frame_num"].diff(periods=period).to_numpy(dtype=float)
    seconds = frame_delta / fps
    return np.divide(
        np.hypot(dx, dy),
        seconds,
        out=np.full(len(track), np.nan, dtype=float),
        where=seconds > 0,
    )


def velocity_roughness(speed: np.ndarray) -> float:
    finite = speed[np.isfinite(speed)]
    if len(finite) < 3:
        return float("nan")
    return float(np.sqrt(np.mean(np.diff(finite) ** 2)))


def smooth_trend(values: pd.Series, maximum_window: int = 301) -> np.ndarray:
    data = values.to_numpy(dtype=float)
    window = min(maximum_window, len(data) if len(data) % 2 else len(data) - 1)
    if window < 5:
        return data.copy()
    return savgol_filter(data, window, 2, mode="interp")


def safe_corr(left: np.ndarray, right: np.ndarray) -> float:
    valid = np.isfinite(left) & np.isfinite(right)
    if valid.sum() < 3 or np.std(left[valid]) <= 1e-12 or np.std(right[valid]) <= 1e-12:
        return float("nan")
    return float(np.corrcoef(left[valid], right[valid])[0, 1])


def build_summary(frame: pd.DataFrame, fps: float, period: int) -> pd.DataFrame:
    rows = []
    for track_id, track in frame.groupby("track_id", sort=True):
        track = track.sort_values("frame_num")
        annotated_frames = len(track)
        held_tail_frames = int((~track["active_motion"]).sum())
        track = track[track["active_motion"]].copy()
        raw_speed = interval_speed(track, "measure_x", "measure_y", fps, period)
        legacy_speed = interval_speed(track, "legacy_measure_x", "legacy_measure_y", fps, period)
        new_speed = interval_speed(track, "smooth_measure_x", "smooth_measure_y", fps, period)
        deviation = np.hypot(
            track["smooth_measure_x"] - track["measure_x"],
            track["smooth_measure_y"] - track["measure_y"],
        )
        raw_width = track["raw_bbox_width_px"].to_numpy(dtype=float)
        raw_height = track["raw_bbox_height_px"].to_numpy(dtype=float)
        smooth_width = track["smooth_bbox_width_px"].to_numpy(dtype=float)
        smooth_height = track["smooth_bbox_height_px"].to_numpy(dtype=float)
        rows.append(
            {
                "track_id": int(track_id),
                "label": track["label"].iloc[0],
                "frames": len(track),
                "annotated_frames": annotated_frames,
                "held_tail_frames": held_tail_frames,
                "duration_s": (track["frame_num"].iloc[-1] - track["frame_num"].iloc[0]) / fps,
                "keyframes": int(track["keyframe"].sum()),
                "width_q90_q10_ratio": float(np.quantile(raw_width, 0.9) / max(np.quantile(raw_width, 0.1), 1e-6)),
                "height_q90_q10_ratio": float(np.quantile(raw_height, 0.9) / max(np.quantile(raw_height, 0.1), 1e-6)),
                "width_trend_correlation": safe_corr(raw_width, smooth_width),
                "height_trend_correlation": safe_corr(raw_height, smooth_height),
                "mean_measure_adjustment_px": float(np.mean(deviation)),
                "p95_measure_adjustment_px": float(np.quantile(deviation, 0.95)),
                "raw_speed_roughness_px_s": velocity_roughness(raw_speed),
                "legacy_speed_roughness_px_s": velocity_roughness(legacy_speed),
                "new_speed_roughness_px_s": velocity_roughness(new_speed),
            }
        )
    summary = pd.DataFrame(rows)
    summary["new_roughness_reduction_pct"] = 100.0 * (
        1.0 - summary["new_speed_roughness_px_s"] / summary["raw_speed_roughness_px_s"]
    )
    return summary


def style_axis(axis: plt.Axes) -> None:
    axis.set_facecolor("white")
    axis.grid(True, color=GRID, linewidth=0.8, alpha=0.85)
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color(GRID)
    axis.tick_params(colors=MUTED, labelsize=8.5)


def draw_visualization(
    frame: pd.DataFrame,
    summary: pd.DataFrame,
    fps: float,
    output_path: str,
) -> int:
    plt.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "DejaVu Sans"]
    perspective_score = summary["height_q90_q10_ratio"] * np.log1p(summary["frames"])
    focus_id = int(summary.loc[perspective_score.idxmax(), "track_id"])
    focus = frame[frame["track_id"] == focus_id].sort_values("frame_num").copy()
    focus_active = focus[focus["active_motion"]].copy()
    focus_metrics = summary[summary["track_id"] == focus_id].iloc[0]
    focus["time_s"] = (focus["frame_num"] - focus["frame_num"].iloc[0]) / fps
    focus_active["time_s"] = (
        focus_active["frame_num"] - focus["frame_num"].iloc[0]
    ) / fps
    period = max(int(round(fps * 0.2)), 1)
    focus_active["raw_speed"] = interval_speed(focus_active, "measure_x", "measure_y", fps, period)
    focus_active["legacy_speed"] = interval_speed(focus_active, "legacy_measure_x", "legacy_measure_y", fps, period)
    focus_active["new_speed"] = interval_speed(focus_active, "smooth_measure_x", "smooth_measure_y", fps, period)

    fig, axes = plt.subplots(2, 3, figsize=(17, 9.5), dpi=160, facecolor=SURFACE)

    axis = axes[0, 0]
    style_axis(axis)
    colors = [BLUE, ORANGE, GREEN, PURPLE, RED]
    for color, (track_id, track) in zip(colors, frame.groupby("track_id", sort=True)):
        axis.plot(
            track["smooth_measure_x"],
            track["smooth_measure_y"],
            color=color,
            linewidth=1.7,
            label=f"Track {track_id} / {track['label'].iloc[0]}",
        )
    axis.invert_yaxis()
    axis.set_xlabel("画像 x (px)", color=MUTED)
    axis.set_ylabel("画像 y (px)", color=MUTED)
    axis.set_title("全トラックの平滑化後測定点", loc="left", color=INK, fontweight="bold")
    axis.legend(frameon=False, fontsize=7.5)

    axis = axes[0, 1]
    style_axis(axis)
    axis.plot(focus["time_s"], focus["raw_bbox_width_px"], color=BLUE, alpha=0.4, label="幅・CVAT")
    axis.plot(focus["time_s"], focus["smooth_bbox_width_px"], color=BLUE, linewidth=2.0, label="幅・平滑化")
    axis.plot(focus["time_s"], focus["raw_bbox_height_px"], color=ORANGE, alpha=0.4, label="高さ・CVAT")
    axis.plot(focus["time_s"], focus["smooth_bbox_height_px"], color=ORANGE, linewidth=2.0, label="高さ・平滑化")
    keyframes = focus[focus["keyframe"] == 1]
    axis.scatter(keyframes["time_s"], keyframes["raw_bbox_height_px"], color=INK, s=18, zorder=5, label="CVATキーフレーム")
    active_end_s = float(focus_active["time_s"].iloc[-1])
    full_end_s = float(focus["time_s"].iloc[-1])
    if full_end_s > active_end_s:
        axis.axvspan(active_end_s, full_end_s, color=GRID, alpha=0.5, label="座標固定区間")
    axis.set_xlabel("トラック開始からの時間 (秒)", color=MUTED)
    axis.set_ylabel("BBOXサイズ (px)", color=MUTED)
    axis.set_title(f"遠近によるサイズ変化 — Track {focus_id}", loc="left", color=INK, fontweight="bold")
    axis.legend(frameon=False, fontsize=7.5, ncol=2)

    axis = axes[0, 2]
    style_axis(axis)
    axis.plot(focus["measure_x"], focus["measure_y"], color=MUTED, alpha=0.5, linewidth=1.0, label="CVAT測定点")
    axis.plot(focus["legacy_measure_x"], focus["legacy_measure_y"], color=ORANGE, linewidth=1.5, label="従来中央値")
    axis.plot(focus["smooth_measure_x"], focus["smooth_measure_y"], color=GREEN, linewidth=2.0, label="BBOX分解")
    axis.scatter(keyframes["measure_x"], keyframes["measure_y"], color=INK, s=18, zorder=5, label="キーフレーム")
    axis.invert_yaxis()
    axis.set_xlabel("画像 x (px)", color=MUTED)
    axis.set_ylabel("画像 y (px)", color=MUTED)
    axis.set_title("軌跡形状の保持", loc="left", color=INK, fontweight="bold")
    axis.legend(frameon=False, fontsize=7.5)

    axis = axes[1, 0]
    style_axis(axis)
    axis.plot(focus_active["time_s"], focus_active["raw_speed"], color=MUTED, alpha=0.55, linewidth=1.0, label="CVAT測定点")
    axis.plot(focus_active["time_s"], focus_active["legacy_speed"], color=ORANGE, linewidth=1.4, label="従来中央値")
    axis.plot(focus_active["time_s"], focus_active["new_speed"], color=GREEN, linewidth=1.8, label="BBOX分解")
    axis.set_xlabel("トラック開始からの時間 (秒)", color=MUTED)
    axis.set_ylabel("0.2秒区間の画像速度 (px/s)", color=MUTED)
    axis.set_title("測定点から得た画像速度", loc="left", color=INK, fontweight="bold")
    axis.legend(frameon=False, fontsize=7.5)

    axis = axes[1, 1]
    style_axis(axis)
    track_ids = summary["track_id"].astype(str)
    raw = summary["raw_speed_roughness_px_s"]
    legacy = summary["legacy_speed_roughness_px_s"]
    new = summary["new_speed_roughness_px_s"]
    positions = np.arange(len(summary))
    width = 0.25
    axis.bar(positions - width, raw, width, color=MUTED, label="CVAT測定点")
    axis.bar(positions, legacy, width, color=ORANGE, label="従来中央値")
    axis.bar(positions + width, new, width, color=GREEN, label="BBOX分解")
    axis.set_xticks(positions, track_ids)
    axis.set_xlabel("Track ID", color=MUTED)
    axis.set_ylabel("速度粗さ RMS (px/s・差分)", color=MUTED)
    axis.set_title("トラック別の速度ギザギザ", loc="left", color=INK, fontweight="bold")
    axis.legend(frameon=False, fontsize=7.5)

    axis = axes[1, 2]
    style_axis(axis)
    height_trend = smooth_trend(focus_active["raw_bbox_height_px"])
    bottom_trend = smooth_trend(focus_active["measure_y"])
    axis.scatter(
        focus_active["measure_y"],
        focus_active["raw_bbox_height_px"],
        s=7,
        alpha=0.18,
        color=MUTED,
        label="CVAT各フレーム",
    )
    order = np.argsort(bottom_trend)
    axis.plot(bottom_trend[order], height_trend[order], color=BLUE, linewidth=2.2, label="長期的な遠近傾向")
    axis.set_xlabel("BBOX下端 y (px)", color=MUTED)
    axis.set_ylabel("BBOX高さ (px)", color=MUTED)
    axis.set_title("画像位置と見かけサイズ", loc="left", color=INK, fontweight="bold")
    axis.legend(frameon=False, fontsize=7.5)
    axis.text(
        0.03,
        0.95,
        f"高さの生値–平滑値相関 {focus_metrics['height_trend_correlation']:.5f}\n"
        f"測定点補正 p95 {focus_metrics['p95_measure_adjustment_px']:.2f} px\n"
        f"速度粗さ削減 {focus_metrics['new_roughness_reduction_pct']:.1f}%",
        transform=axis.transAxes,
        va="top",
        color=MUTED,
        fontsize=8.5,
    )

    fig.suptitle(
        "CVAT実トラック：BBOXサイズ分離による測定点平滑化",
        x=0.045,
        y=0.985,
        ha="left",
        color=INK,
        fontsize=18,
        fontweight="bold",
    )
    fig.text(
        0.045,
        0.952,
        f"5トラック / {len(frame):,} BBOX / {fps:.1f}fps　主表示: Track {focus_id} ({focus['label'].iloc[0]})",
        color=MUTED,
        fontsize=9,
    )
    fig.text(
        0.045,
        0.018,
        "注: CVATは少数キーフレーム間の線形補間。速度指標は最後の座標変化までを対象とし、未射影のpx/s。",
        color=MUTED,
        fontsize=8.5,
    )
    fig.subplots_adjust(left=0.055, right=0.985, top=0.91, bottom=0.08, wspace=0.27, hspace=0.32)
    fig.savefig(output_path, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return focus_id


def write_readme(output_dir: str, summary: pd.DataFrame, focus_id: int, fps: float) -> None:
    focus = summary[summary["track_id"] == focus_id].iloc[0]
    lines = [
        "# CVAT measurement-point smoothing evaluation",
        "",
        "The source XML and video were read in place. Raw annotations and media were not copied.",
        "",
        f"- FPS: {fps:.3f}",
        f"- Tracks: {len(summary)}",
        f"- Focus track: {focus_id} ({focus['label']})",
        f"- Focus active/annotated frames: {focus['frames']}/{focus['annotated_frames']}",
        f"- Focus unchanged tail frames: {focus['held_tail_frames']}",
        f"- Focus height q90/q10: {focus['height_q90_q10_ratio']:.4f}",
        f"- Focus height raw/smoothed correlation: {focus['height_trend_correlation']:.6f}",
        f"- Focus measurement adjustment p95: {focus['p95_measure_adjustment_px']:.4f} px",
        f"- Focus speed roughness reduction: {focus['new_roughness_reduction_pct']:.2f}%",
        "",
        "`track_summary.csv` contains derived aggregate metrics only, not frame-level coordinates.",
    ]
    with open(os.path.join(output_dir, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xml", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument(
        "--output-dir",
        default=os.path.join(ROOT, "artifacts", "cvat_measurement_smoothing"),
    )
    parser.add_argument("--window", type=int, default=11)
    args = parser.parse_args()

    capture = cv2.VideoCapture(args.video)
    if not capture.isOpened():
        raise FileNotFoundError(f"Video could not be opened: {args.video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    capture.release()

    os.makedirs(args.output_dir, exist_ok=True)
    frame = mark_active_motion(add_measure_points(read_cvat_tracks(args.xml)))
    frame = add_legacy_smoothing(frame, args.window)
    frame = stabilize_measure_points(frame, window=args.window)
    period = max(int(round(fps * 0.2)), 1)
    summary = build_summary(frame, fps, period)
    summary.to_csv(os.path.join(args.output_dir, "track_summary.csv"), index=False)
    visualization_path = os.path.join(args.output_dir, "cvat_measurement_smoothing.png")
    focus_id = draw_visualization(frame, summary, fps, visualization_path)
    write_readme(args.output_dir, summary, focus_id, fps)

    focus = summary[summary["track_id"] == focus_id].iloc[0]
    print(args.output_dir)
    print(f"tracks={len(summary)} boxes={len(frame)} focus_track={focus_id}")
    print(
        f"focus_height_ratio={focus['height_q90_q10_ratio']:.4f} "
        f"height_trend_correlation={focus['height_trend_correlation']:.6f} "
        f"measurement_adjustment_p95={focus['p95_measure_adjustment_px']:.4f}px "
        f"roughness_reduction={focus['new_roughness_reduction_pct']:.2f}%"
    )


if __name__ == "__main__":
    main()
