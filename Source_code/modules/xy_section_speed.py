from __future__ import annotations

import math
import os
import sqlite3
from collections import Counter
from typing import Dict, Iterable, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from .calibration_loader import load_calibration_json
from .db_manager import (
    MAIN_DB_PATH,
    configure_connection,
    ensure_detection_xy_speed_columns,
)
from .manual_metrics import load_white_lines

SEGMENT_COUNT = 20
DEFAULT_FPS = 30.0
DEFAULT_MEDIAN_KM_H = 60.0
DEFAULT_BICYCLE_CLASSES = {"bicycle", "bike", "cyclist"}


def _coerce_points(raw_points: object) -> list[Tuple[float, float]]:
    if isinstance(raw_points, dict):
        for key in ("points", "coords", "coordinates"):
            if key in raw_points:
                raw_points = raw_points[key]
                break
        else:
            raw_points = raw_points.values()

    if not isinstance(raw_points, (list, tuple)):
        try:
            raw_points = list(raw_points)
        except TypeError:
            return []

    points: list[Tuple[float, float]] = []
    for pt in raw_points:
        if isinstance(pt, dict):
            x_candidate = pt.get("x")
            y_candidate = pt.get("y")
            try:
                x = float(x_candidate)
                y = float(y_candidate)
            except (TypeError, ValueError):
                continue
            points.append((x, y))
            continue

        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            continue
        try:
            x = float(pt[0])
            y = float(pt[1])
        except (TypeError, ValueError):
            continue
        points.append((x, y))
    return points


def _line_y_bounds(line: Optional[Sequence[Sequence[object]]]) -> Optional[Tuple[float, float]]:
    if not line:
        return None
    points = _coerce_points(line)
    if not points:
        return None
    ys = [pt[1] for pt in points if isinstance(pt[1], (int, float))]
    if not ys:
        return None
    return min(ys), max(ys)


def compute_measurement_range(calibration_payload: Optional[dict]) -> Optional[Tuple[float, float]]:
    lane_lines = load_white_lines(calibration_payload)
    bounds: list[Tuple[float, float]] = []
    for line in (lane_lines.left, lane_lines.right, lane_lines.center):
        bound = _line_y_bounds(line)
        if bound:
            bounds.append(bound)
    if not bounds:
        return None
    y_start = max(bound[0] for bound in bounds)
    y_end = min(bound[1] for bound in bounds)
    if not math.isfinite(y_start) or not math.isfinite(y_end) or y_end <= y_start:
        return None
    return y_start, y_end


def get_measurement_length_for_run(run_id: int) -> Optional[float]:
    if not run_id:
        return None
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="read")
        row = conn.execute(
            "SELECT calibration_profile FROM ProcessLog WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if not row or not row[0]:
        return None

    try:
        calibration, _ = load_calibration_json(run_id, row[0])
    except FileNotFoundError:
        return None
    except Exception:
        return None

    measurement_range = compute_measurement_range(calibration)
    if not measurement_range:
        return None
    y_start, y_end = measurement_range
    return float(y_end - y_start)


def collect_measurement_lengths(run_ids: Iterable[int]) -> list[float]:
    lengths = []
    for run_id in run_ids:
        length = get_measurement_length_for_run(int(run_id))
        if length is not None:
            lengths.append(float(length))
    return lengths


def _median_of_three(values: pd.Series) -> Optional[float]:
    values = values.dropna()
    if values.empty:
        return None
    median_val = values.median()
    closest = values.loc[(values - median_val).abs().sort_values().index[:3]]
    if closest.empty:
        return None
    return float(closest.mean())


def _infer_is_bike(class_name: object) -> bool:
    name = str(class_name or "").lower()
    return any(alias in name for alias in DEFAULT_BICYCLE_CLASSES)


def _build_speed_dataframe(run_id: int) -> Tuple[pd.DataFrame, float, Optional[str], Optional[Tuple[float, float]]]:
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="read")
        fps_row = conn.execute(
            """
            SELECT v.fps, p.calibration_profile
            FROM Video v
            JOIN ProcessLog p ON v.video_id = p.video_id
            WHERE p.run_id = ?
            """,
            (run_id,),
        ).fetchone()
        fps = float(fps_row[0] or DEFAULT_FPS) if fps_row else DEFAULT_FPS
        profile_name = fps_row[1] if fps_row and fps_row[1] else None

        df = pd.read_sql_query(
            """
            SELECT d.auto_id, d.run_id, d.frame_num, d.group_id, d.track_id,
                   d.model_name, d.x1, d.y1, d.x2, d.y2,
                   d.overtake, d.overtake_by, d.acceleration_m_s2,
                   d.xy_px_speedpx, c.class_name
            FROM Detection d
            LEFT JOIN Class c ON d.class_id = c.class_id
            WHERE d.run_id = ?
              AND d.model_name != 'best'
            ORDER BY d.group_id, d.frame_num
            """,
            conn,
            params=(run_id,),
        )
    measurement_range = None
    if profile_name:
        try:
            calibration, _ = load_calibration_json(run_id, profile_name)
            measurement_range = compute_measurement_range(calibration)
        except FileNotFoundError:
            measurement_range = None
        except Exception:
            measurement_range = None

    return df, fps, profile_name, measurement_range


def _assign_segments(df: pd.DataFrame, measurement_range: Tuple[float, float]) -> pd.DataFrame:
    y_start, y_end = measurement_range
    segment_height = (y_end - y_start) / SEGMENT_COUNT
    df["segment_index"] = -1
    if segment_height <= 0:
        return df
    in_range = (df["point_y"] >= y_start) & (df["point_y"] <= y_end)
    seg = ((df["point_y"] - y_start) / segment_height).astype(int)
    seg = seg.clip(lower=0, upper=SEGMENT_COUNT - 1)
    df.loc[in_range, "segment_index"] = seg[in_range]
    return df


def _compute_xy_speed(df: pd.DataFrame, fps: float) -> pd.DataFrame:
    df = df.copy()
    df["track_key"] = df["track_id"].where(df["track_id"].notna(), df["group_id"])
    df = df[df["track_key"].notna()].copy()
    df["track_key"] = df["track_key"].astype(int)
    df.sort_values(["track_key", "frame_num"], inplace=True)
    df["prev_x"] = df.groupby("track_key")["point_x"].shift(1)
    df["prev_y"] = df.groupby("track_key")["point_y"].shift(1)
    df["frame_diff"] = df.groupby("track_key")["frame_num"].diff()
    dx = df["point_x"] - df["prev_x"]
    dy = df["point_y"] - df["prev_y"]
    df["dist_px"] = np.hypot(dx, dy)
    df["xy_px_speedpx"] = np.nan
    valid = df["frame_diff"] > 0
    df.loc[valid, "xy_px_speedpx"] = df.loc[valid, "dist_px"] / (df.loc[valid, "frame_diff"] / fps)
    df.loc[~np.isfinite(df["xy_px_speedpx"]), "xy_px_speedpx"] = np.nan
    return df


def _baseline_by_segment(df: pd.DataFrame, value_col: str) -> Dict[int, float]:
    baseline: Dict[int, float] = {}
    if df.empty:
        return baseline
    for seg, seg_df in df.groupby("segment_index"):
        if seg < 0:
            continue
        group_medians = seg_df.groupby("group_id")[value_col].median()
        baseline_val = _median_of_three(group_medians)
        if baseline_val is not None:
            baseline[int(seg)] = baseline_val
    return baseline


def _median_speed_for_cars(df: pd.DataFrame) -> Optional[float]:
    if df.empty:
        return None
    group_medians = df.groupby("group_id")["xy_px_speedpx"].median()
    return _median_of_three(group_medians)


def assign_xy_section_speed(run_id: int) -> Optional[float]:
    """
    測定区間を20分割し、車は右下、自転車は中央下の点でpx速度を計算。
    xy_px_speedpx / xy_px_karikm / xy_px_changeable / xy_px_changeable_name を更新する。
    """
    load_dotenv()
    ensure_detection_xy_speed_columns()

    accel_threshold = float(os.getenv("ACCELERATION_THRESHOLD", 0.5))
    decel_threshold = float(os.getenv("DECELERATION_THRESHOLD", -0.5))

    df, fps, profile_name, measurement_range = _build_speed_dataframe(run_id)
    if df.empty or not measurement_range:
        print(f"[xy_section_speed] Run {run_id}: 測定区間が取得できないためスキップします。")
        return None

    df["is_bike"] = df["class_name"].apply(_infer_is_bike)
    df["point_x"] = np.where(df["is_bike"], (df["x1"] + df["x2"]) / 2.0, df["x2"])
    df["point_y"] = df["y2"]
    df = _assign_segments(df, measurement_range)
    df = _compute_xy_speed(df, fps)
    df.loc[df["segment_index"] < 0, "xy_px_speedpx"] = np.nan

    # Persist speed for this run before baseline calculations.
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="write")
        speed_updates = [
            (float(row.xy_px_speedpx) if pd.notna(row.xy_px_speedpx) else None, int(row.auto_id))
            for row in df.itertuples()
        ]
        conn.executemany(
            "UPDATE Detection SET xy_px_speedpx = ? WHERE auto_id = ?",
            speed_updates,
        )

    if not profile_name:
        print(f"[xy_section_speed] Run {run_id}: calibration_profile が未設定です。")
        return float(measurement_range[1] - measurement_range[0])

    # Load reference data for baseline from same calibration profile.
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="read")
        run_rows = conn.execute(
            "SELECT run_id FROM ProcessLog WHERE calibration_profile = ?",
            (profile_name,),
        ).fetchall()
        ref_run_ids = [int(r[0]) for r in run_rows]
        if not ref_run_ids:
            ref_run_ids = [run_id]
        placeholders = ",".join(["?"] * len(ref_run_ids))
        ref_df = pd.read_sql_query(
            f"""
            SELECT d.auto_id, d.run_id, d.frame_num, d.group_id, d.track_id,
                   d.model_name, d.x1, d.y1, d.x2, d.y2,
                   d.overtake, d.overtake_by, d.acceleration_m_s2,
                   d.xy_px_speedpx, c.class_name
            FROM Detection d
            LEFT JOIN Class c ON d.class_id = c.class_id
            WHERE d.run_id IN ({placeholders})
              AND d.model_name != 'best'
            """,
            conn,
            params=ref_run_ids,
        )

    ref_df["is_bike"] = ref_df["class_name"].apply(_infer_is_bike)
    ref_df["point_x"] = np.where(ref_df["is_bike"], (ref_df["x1"] + ref_df["x2"]) / 2.0, ref_df["x2"])
    ref_df["point_y"] = ref_df["y2"]
    ref_df = _assign_segments(ref_df, measurement_range)
    ref_df = ref_df[ref_df["segment_index"] >= 0].copy()
    ref_df = ref_df[ref_df["group_id"].notna()].copy()

    # Non-overtake filtering
    ref_df["overtake_flag"] = ref_df["overtake"].fillna(0).astype(int)
    ref_df["overtake_by_flag"] = ref_df["overtake_by"].fillna("").astype(str).str.strip() != ""

    car_ref = ref_df[(~ref_df["is_bike"]) & (ref_df["overtake_flag"] != 1)]
    bike_ref = ref_df[(ref_df["is_bike"]) & (~ref_df["overtake_by_flag"])]

    car_speed_ref = car_ref[car_ref["xy_px_speedpx"].notna()].copy()
    car_baseline_speed = _median_speed_for_cars(car_speed_ref)
    scale_factor = None
    if car_baseline_speed and car_baseline_speed > 0:
        scale_factor = DEFAULT_MEDIAN_KM_H / car_baseline_speed

    car_baseline_accel = _baseline_by_segment(car_ref, "acceleration_m_s2")
    bike_baseline_accel = _baseline_by_segment(bike_ref, "acceleration_m_s2")

    # Apply baseline + changeable
    df["xy_px_karikm"] = np.nan
    if scale_factor:
        df.loc[df["xy_px_speedpx"].notna(), "xy_px_karikm"] = (
            df.loc[df["xy_px_speedpx"].notna(), "xy_px_speedpx"] * scale_factor
        )

    df["xy_px_changeable"] = np.nan
    df["xy_px_changeable_name"] = None
    df["overtake_flag"] = df["overtake"].fillna(0).astype(int)
    df["overtake_by_flag"] = df["overtake_by"].fillna("").astype(str).str.strip() != ""

    for idx, row in df.iterrows():
        seg = int(row["segment_index"])
        if seg < 0:
            continue
        accel_val = row["acceleration_m_s2"]
        if pd.isna(accel_val):
            continue
        baseline_accel = None
        if row["is_bike"]:
            baseline_accel = bike_baseline_accel.get(seg)
        else:
            baseline_accel = car_baseline_accel.get(seg)
        if baseline_accel is None:
            baseline_accel = 0.0
        change_val = float(accel_val) - float(baseline_accel)
        df.at[idx, "xy_px_changeable"] = change_val

        is_overtake = (row["is_bike"] and row["overtake_by_flag"]) or (
            (not row["is_bike"]) and row["overtake_flag"] == 1
        )
        if is_overtake:
            if change_val >= accel_threshold:
                df.at[idx, "xy_px_changeable_name"] = "加速"
            elif change_val <= decel_threshold:
                df.at[idx, "xy_px_changeable_name"] = "減速"
            else:
                df.at[idx, "xy_px_changeable_name"] = "変わらない"

    updates = [
        (
            float(row.xy_px_speedpx) if pd.notna(row.xy_px_speedpx) else None,
            float(row.xy_px_karikm) if pd.notna(row.xy_px_karikm) else None,
            float(row.xy_px_changeable) if pd.notna(row.xy_px_changeable) else None,
            row.xy_px_changeable_name if isinstance(row.xy_px_changeable_name, str) else None,
            int(row.auto_id),
        )
        for row in df.itertuples()
    ]

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        configure_connection(conn, mode="write")
        conn.executemany(
            """
            UPDATE Detection
            SET xy_px_speedpx = ?,
                xy_px_karikm = ?,
                xy_px_changeable = ?,
                xy_px_changeable_name = ?
            WHERE auto_id = ?
            """,
            updates,
        )

    return float(measurement_range[1] - measurement_range[0])
