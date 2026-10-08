# 役割: 進行方向、使用スケール、速度、加速度など、車両の運動に関する情報を計算する
import os
import sqlite3
from typing import Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from ..db_manager import MAIN_DB_PATH
from ..speed_homography import apply_homography_speed
from ..speed_y_axis import VerticalContext, apply_vertical_speed, prepare_vertical_context
from ..calibration_loader import load_calibration_json
from ..measure_points import (
    attach_measure_points,
    compute_front_right_tire_points,
    stabilize_measure_points,
)
from ..speed_regression import rolling_linear_slope


def _coerce_points(raw_points):
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

    points = []
    for pt in raw_points:
        if isinstance(pt, dict):
            x_candidate = pt.get("x")
            y_candidate = pt.get("y")
            try:
                x = float(x_candidate)
                y = float(y_candidate)
            except (TypeError, ValueError):
                continue
            points.append([x, y])
            continue

        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            continue
        try:
            x = float(pt[0])
            y = float(pt[1])
        except (TypeError, ValueError):
            continue
        points.append([x, y])
    return points


def _coerce_path_points(raw_points):
    return _coerce_points(raw_points)


def assign_kinematics(run_id: int):
    load_dotenv()
    REF_WIDTH_M = float(os.getenv("REFERENCE_VEHICLE_WIDTH_M", 1.8))
    ACCEL_THRESHOLD = float(os.getenv("ACCELERATION_THRESHOLD", 0.5))
    DECEL_THRESHOLD = float(os.getenv("DECELERATION_THRESHOLD", -0.5))

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        profile_sql = "SELECT calibration_profile FROM ProcessLog WHERE run_id = ?"
        result = conn.execute(profile_sql, (run_id,)).fetchone()
        if not result or not result[0]:
            raise ValueError(f"Run ID {run_id} にキャリブレーションプロファイルが適用されていません。")
        profile_name = result[0]

        fps_sql = "SELECT v.fps FROM Video v JOIN ProcessLog p ON v.video_id = p.video_id WHERE p.run_id = ?"
        fps_result = conn.execute(fps_sql, (run_id,)).fetchone()
        fps = fps_result[0] if fps_result and fps_result[0] else 30.0

        df = pd.read_sql_query(
            """
            SELECT auto_id, track_id, frame_num, group_id, x1, x2, y1, y2,
                   model_name, travel_direction, class_name
            FROM Detection
            WHERE run_id = ? AND track_id IS NOT NULL
            ORDER BY track_id, frame_num
        """,
            conn,
            params=(run_id,),
        )

    if df.empty:
        return

    calib_data, _ = load_calibration_json(run_id, profile_name)

    scale_meta = calib_data.get("scale", {}) or {}
    scale_mode = (scale_meta.get("mode") or "vertical").lower()

    lines_meta = calib_data.get("lines", {}) or {}
    left_line = lines_meta.get("left_white_line")
    right_line = lines_meta.get("right_white_line")
    tyre_points = compute_front_right_tire_points(
        df[df["model_name"] == "best"],
        left_line,
        right_line,
    )
    df = df[df["model_name"] != "best"].copy()
    if df.empty:
        return
    df = attach_measure_points(
        df,
        tyre_points,
        left_line=left_line,
        right_line=right_line,
    )

    df["center_x"] = (df["x1"] + df["x2"]) / 2
    df["center_y"] = (df["y1"] + df["y2"]) / 2
    df["measure_x"] = pd.to_numeric(df["measure_x"], errors="coerce").fillna(df["center_x"])
    df["measure_y"] = pd.to_numeric(df["measure_y"], errors="coerce").fillna(df["y2"])
    df["frame_diff"] = df.groupby("track_id")["frame_num"].diff()
    df["speed_km_h"] = 0.0
    df["speed_mps"] = 0.0
    df["speed_diff"] = 0.0
    df["time_diff_accel"] = 0.0
    df["acceleration_m_s2"] = 0.0
    df["travel_direction"] = "N"
    df["scale_pixels_per_meter"] = np.nan
    df["x_pixels_per_meter"] = (df["x2"] - df["x1"]) / REF_WIDTH_M
    df["y_delta"] = np.nan

    measurement_smoothing_frames = max(
        int(scale_meta.get("measurement_smoothing_frames") or 11),
        3,
    )
    df = stabilize_measure_points(df, window=measurement_smoothing_frames)
    # Vertical calibration and its homography fallback use these common columns.
    df["smooth_center_x"] = df["smooth_measure_x"]
    df["smooth_center_y"] = df["smooth_measure_y"]
    df["smooth_y2"] = df["smooth_measure_y"]

    frame_window = max(int(round(fps)), 1)
    speed_window_seconds = float(scale_meta.get("speed_window_seconds") or 0.2)
    speed_window_frames = max(int(round(fps * speed_window_seconds)), 1)
    mode_window = 10
    time_s = df["frame_diff"] / fps

    df["pixel_dx"] = df.groupby("track_id")["smooth_measure_x"].diff()
    df["pixel_dy"] = df.groupby("track_id")["smooth_measure_y"].diff()
    df["pixel_distance"] = np.hypot(df["pixel_dx"], df["pixel_dy"])
    df["pixel_speed_frame"] = df["pixel_distance"]
    df["pixel_speed"] = 0.0
    valid_pixel_speed = time_s > 0
    df.loc[valid_pixel_speed, "pixel_speed"] = (
        df.loc[valid_pixel_speed, "pixel_distance"] / time_s[valid_pixel_speed]
    )

    vertical_context: VerticalContext = prepare_vertical_context(df, scale_meta)

    def apply_xy() -> bool:
        path_meta = scale_meta.get("path") or {}
        path_points = _coerce_path_points(path_meta.get("points"))
        total_distance = float(path_meta.get("total_distance_m") or 0)
        if len(path_points) < 2 or total_distance <= 0:
            return False

        path_points = np.array(path_points, dtype=float)

        def cum_distance(points):
            dist = [0.0]
            for i in range(1, len(points)):
                dist.append(dist[-1] + float(np.linalg.norm(points[i] - points[i - 1])))
            return dist

        cumulative = cum_distance(path_points)
        pixels_per_meter = cumulative[-1] / total_distance if cumulative[-1] > 0 else None
        if not pixels_per_meter:
            return False

        def project(point):
            best = None
            best_dist = float("inf")
            for i in range(len(path_points) - 1):
                p1, p2 = path_points[i], path_points[i + 1]
                v = p2 - p1
                if np.allclose(v, 0):
                    continue
                denom = float(np.dot(v, v))
                if denom <= 0:
                    continue
                t = np.clip(np.dot(point - p1, v) / denom, 0, 1)
                proj = p1 + t * v
                dist = np.linalg.norm(point - proj)
                if dist < best_dist:
                    best_dist = dist
                    best = cumulative[i] + float(np.linalg.norm(proj - p1))
            return best

        base_centers = pd.DataFrame(
            {
                "x": df["smooth_center_x"].fillna(df["center_x"]),
                "y": df["smooth_center_y"].fillna(df["center_y"]),
            }
        )
        centers = base_centers.to_numpy(dtype=float)
        path_positions = []
        for pt in centers:
            projected = project(pt)
            path_positions.append(projected if projected is not None else np.nan)
        df["path_position_m"] = np.array(path_positions, dtype=float) / pixels_per_meter
        df["path_position_diff"] = df.groupby("track_id")["path_position_m"].diff(
            periods=speed_window_frames
        )
        path_velocity_mps = rolling_linear_slope(
            df["frame_num"],
            df["path_position_m"],
            df["track_id"],
            fps,
            speed_window_frames,
            valid_mask=df["path_position_m"].notna(),
        )
        valid = path_velocity_mps.notna()
        df.loc[valid, "speed_mps"] = path_velocity_mps[valid].abs()
        df["speed_km_h"] = df["speed_mps"] * 3.6
        df["travel_direction"] = np.where(path_velocity_mps.fillna(0) >= 0, "F", "B")
        df["scale_pixels_per_meter"] = pixels_per_meter
        return True

    def set_accel_state(a: float) -> str:
        if a > ACCEL_THRESHOLD:
            return "加速"
        if a < DECEL_THRESHOLD:
            return "減速"
        return "巡航"

    applied = False
    fallback_reason: Optional[str] = None
    if scale_mode == "xy":
        applied = apply_xy()
        if not applied:
            fallback_reason = "XY"
            print(
                f"Run ID {run_id}: XYパスの適用に失敗したため縦スケールへフォールバックします。"
            )
            scale_mode = "vertical"
    if not applied and scale_mode == "homography":
        homography_meta = scale_meta.get("homography") or {}
        applied = apply_homography_speed(
            df,
            time_s,
            fps,
            frame_window,
            homography_meta,
            vertical_context,
            camera_meta=calib_data.get("camera") or scale_meta.get("camera"),
            speed_window_frames=speed_window_frames,
            calibration_lines=scale_meta.get("lines"),
        )
        if not applied:
            fallback_reason = "homography"
            print(
                f"Run ID {run_id}: ホモグラフィ適用に失敗したため縦スケールへフォールバックします。"
            )
            scale_mode = "vertical"
    if not applied:
        applied = apply_vertical_speed(
            df,
            time_s,
            fps,
            frame_window,
            vertical_context,
            speed_window_frames=speed_window_frames,
        )
    if not applied:
        print(
            f"Run ID {run_id}: スケール情報が見つからないためピクセル速度のみ保存します。"
        )
        df["speed_km_h"] = 0.0
        df["speed_mps"] = 0.0
        df["acceleration_m_s2"] = 0.0
        df["scale_pixels_per_meter"] = np.nan
        if fallback_reason == "XY":
            df["travel_direction"] = np.where(
                df["pixel_dy"].fillna(0) < 0,
                "F",
                "B",
            )
        else:
            dominant = (
                df.groupby("track_id")["pixel_dy"]
                .transform(lambda s: s.rolling(mode_window, min_periods=1).mean())
                .fillna(0)
            )
            df["travel_direction"] = np.where(dominant < 0, "F", "B")
    else:
        df["scale_pixels_per_meter"] = df["scale_pixels_per_meter"].fillna(np.nan)

    df["pixel_speed_frame"] = df["pixel_speed_frame"].fillna(0.0)
    df["pixel_speed"] = df["pixel_speed"].fillna(0.0)
    df["speed_km_h"] = df["speed_km_h"].fillna(0.0)
    df["speed_mps"] = df["speed_mps"].fillna(0.0)
    df["acceleration_m_s2"] = df["acceleration_m_s2"].fillna(0.0)
    df["travel_direction"] = df["travel_direction"].fillna("N")
    df["acceleration_state"] = df["acceleration_m_s2"].apply(set_accel_state)

    speed_smoothing_frames = max(int(scale_meta.get("speed_smoothing_frames") or 5), 1)
    df["speed_mps_smoothed"] = df.groupby("track_id")["speed_mps"].transform(
        lambda s: s.rolling(
            speed_smoothing_frames,
            center=True,
            min_periods=1,
        ).median()
    )
    df["speed_mps"] = df["speed_mps_smoothed"].fillna(df["speed_mps"])
    df["speed_km_h"] = df["speed_mps"] * 3.6
    df["speed_diff"] = df.groupby("track_id")["speed_mps"].diff(periods=frame_window)
    df["time_diff_accel"] = df.groupby("track_id")["frame_num"].diff(periods=frame_window) / fps
    valid_accel = df["time_diff_accel"] > 0
    df.loc[valid_accel, "acceleration_m_s2"] = (
        df["speed_diff"][valid_accel] / df["time_diff_accel"][valid_accel]
    )
    df["acceleration_state"] = df["acceleration_m_s2"].apply(set_accel_state)

    if "group_id" in df.columns:
        forward_mask = df["travel_direction"].isin(["F", "B"])
        direction_subset = df[forward_mask & df["group_id"].notna()].copy()

        if not direction_subset.empty:
            def _choose_direction(group: pd.DataFrame) -> str:
                f_count = int((group["travel_direction"] == "F").sum())
                b_count = int((group["travel_direction"] == "B").sum())
                if f_count > b_count:
                    return "F"
                if b_count > f_count:
                    return "B"
                if "path_position_diff" in group.columns:
                    diffs = group["path_position_diff"].dropna()
                    if not diffs.empty:
                        return "F" if diffs.mean() >= 0 else "B"
                return "F"

            preferred = direction_subset.groupby("group_id").apply(_choose_direction, include_groups=False)
            for gid, direction in preferred.items():
                mask = (df["group_id"] == gid) & df["travel_direction"].isin(["F", "B"])
                df.loc[mask, "travel_direction"] = direction

    updates = [
        (
            row.travel_direction if pd.notna(row.travel_direction) else None,
            float(row.scale_pixels_per_meter) if pd.notna(row.scale_pixels_per_meter) else None,
            float(row.x_pixels_per_meter) if pd.notna(row.x_pixels_per_meter) else None,
            float(row.pixel_speed) if pd.notna(row.pixel_speed) else 0.0,
            float(row.pixel_speed_frame) if pd.notna(row.pixel_speed_frame) else 0.0,
            float(row.speed_km_h),
            float(row.acceleration_m_s2),
            row.acceleration_state if pd.notna(row.acceleration_state) else None,
            int(row.auto_id),
        )
        for row in df.itertuples()
    ]

    if updates:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            conn.executemany(
                "UPDATE Detection SET travel_direction=?, scale_pixels_per_meter=?, x_pixels_per_meter=?, pixel_speed=?, pixel_speed_frame=?, speed_km_h=?, acceleration_m_s2=?, acceleration_state=? WHERE auto_id=?",
                updates,
            )
            print(f"Run ID {run_id}: 速度関連情報を更新しました。")
