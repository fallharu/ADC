# 役割: 車両に紐付いたタイヤの位置を基準に、左右の白線との距離を計算する（並列対応版）
import os
import re
import sqlite3
from typing import Tuple, Optional, List

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from ..db_manager import MAIN_DB_PATH, ensure_detection_distance_columns
from ..measure_points import (
    attach_measure_points,
    compute_front_right_tire_points,
)
from ..manual_metrics import lane_scale_at_point
from ..calibration_loader import load_calibration_json
from ..white_line import get_line_x_at_y


LANE_WIDTH_METERS = 7.0
CM_PER_METER = 100.0
VERTICAL_TOLERANCE_PX = 5.0


def _build_lane_polygon(
    left_line: Optional[List[List[float]]],
    right_line: Optional[List[List[float]]],
) -> Optional[List[Tuple[float, float]]]:
    if not left_line or not right_line:
        return None
    polygon: List[Tuple[float, float]] = []
    try:
        polygon.extend((float(x), float(y)) for x, y in left_line)
        polygon.extend((float(x), float(y)) for x, y in reversed(right_line))
    except (TypeError, ValueError):
        return None
    if len(polygon) < 3:
        return None
    if polygon[0] != polygon[-1]:
        polygon.append(polygon[0])
    return polygon


def _point_in_polygon(point: Tuple[float, float], polygon: List[Tuple[float, float]]):
    x, y = point
    inside = False
    if len(polygon) < 3:
        return None
    for i in range(len(polygon) - 1):
        x1, y1 = polygon[i]
        x2, y2 = polygon[i + 1]
        if (y1 > y) == (y2 > y):
            continue
        denom = y2 - y1
        if denom == 0:
            continue
        x_cross = x1 + (y - y1) * (x2 - x1) / denom
        if x_cross >= x:
            inside = not inside
    return inside


def _classify_lane_flag(
    measure_x: float,
    measure_y: float,
    polygon: Optional[List[Tuple[float, float]]],
) -> Optional[str]:
    if polygon is None or measure_x is None or measure_y is None:
        return None
    inside = _point_in_polygon((measure_x, measure_y), polygon)
    if inside is None:
        return None
    return "+" if inside else "-"


def _summarize_lane_flags(tyre_points: pd.DataFrame) -> Optional[pd.DataFrame]:
    if "lane_flag" not in tyre_points.columns:
        return None
    valid = tyre_points.dropna(subset=["lane_flag", "group_id"])
    if valid.empty:
        return None

    def decide_flag(series: pd.Series) -> Optional[str]:
        plus = int((series == "+").sum())
        minus = int((series == "-").sum())
        if plus == 0 and minus == 0:
            return None
        if plus > minus:
            return "+"
        if minus > plus:
            return "-"
        last = series.iloc[-1]
        return last if isinstance(last, str) else None

    summary = (
        valid.groupby("group_id", as_index=False)["lane_flag"].agg(decide_flag)
    )
    summary = summary.dropna(subset=["lane_flag"])
    if summary.empty:
        return None
    summary["lane_flag"] = summary["lane_flag"].astype(str)
    return summary


def _min_dist_points_to_polyline(points_xy: np.ndarray, polyline_xy):
    P = np.asarray(points_xy, dtype=np.float64)
    L = np.asarray(polyline_xy, dtype=np.float64)
    if len(L) < 2:
        return np.full((len(P),), np.inf, dtype=np.float64)

    S = L[:-1]
    E = L[1:]
    V = E - S
    denom = (V**2).sum(axis=1)
    zero_seg = denom == 0.0
    denom_safe = np.where(zero_seg, 1.0, denom)

    P_exp = P[:, None, :]
    S_exp = S[None, :, :]
    V_exp = V[None, :, :]

    t = ((P_exp - S_exp) * V_exp).sum(axis=2) / denom_safe[None, :]
    t = np.clip(t, 0.0, 1.0)
    proj = S_exp + t[..., None] * V_exp
    diff = P_exp - proj
    dist2 = (diff**2).sum(axis=2)

    if np.any(zero_seg):
        d2_point = ((P_exp - S_exp) ** 2).sum(axis=2)
        dist2 = np.where(zero_seg[None, :], d2_point, dist2)

    return np.sqrt(dist2.min(axis=1))


def _horizontal_distances_to_polyline(
    points_xy: np.ndarray,
    polyline_xy: list[list[float]],
    tolerance: float,
) -> np.ndarray:
    """Return horizontal distance (Δx) between each point and polyline near the same y."""

    points = np.asarray(points_xy, dtype=np.float64)
    line = np.asarray(polyline_xy, dtype=np.float64)
    if len(line) < 2:
        return np.full((len(points),), np.inf, dtype=np.float64)

    distances = np.full((len(points),), np.inf, dtype=np.float64)

    segment_start = line[:-1]
    segment_end = line[1:]

    for start, end in zip(segment_start, segment_end):
        x1, y1 = start
        x2, y2 = end
        y_low = min(y1, y2) - tolerance
        y_high = max(y1, y2) + tolerance

        mask = (points[:, 1] >= y_low) & (points[:, 1] <= y_high)
        if not np.any(mask):
            continue

        if y2 == y1:
            continue

        clamped_y = np.clip(points[mask, 1], min(y1, y2), max(y1, y2))
        vertical_delta = np.abs(points[mask, 1] - clamped_y)
        valid = vertical_delta <= tolerance
        if not np.any(valid):
            continue

        y_samples = clamped_y[valid]
        x_samples = points[mask, 0][valid]

        if x2 == x1:
            x_line = np.full_like(y_samples, fill_value=x1, dtype=np.float64)
        else:
            slope = (x2 - x1) / (y2 - y1)
            x_line = x1 + slope * (y_samples - y1)

        horizontal = np.abs(x_samples - x_line)
        current = distances[mask][valid]
        distances_subset = np.minimum(current, horizontal)
        distances_indices = np.where(mask)[0][valid]
        distances[distances_indices] = distances_subset

    return distances


def assign_lane_distance(
    run_id: int,
):
    with sqlite3.connect(MAIN_DB_PATH) as conn:
        ensure_detection_distance_columns()
        row = conn.execute(
            "SELECT calibration_profile FROM ProcessLog WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if not row or not row[0]:
        raise ValueError(f"Run ID {run_id} にキャリブレーションプロファイルが適用されていません。")
    profile_name = row[0]

    load_dotenv()
    calib, _ = load_calibration_json(run_id, profile_name)

    from ..manual_metrics import load_white_lines
    lane_lines = load_white_lines(calib)
    left_line, right_line, center_line = lane_lines
    left_inner_line = lane_lines.left_inner
    right_inner_line = lane_lines.right_inner
    if not left_line or not right_line:
        raise ValueError("キャリブレーションファイルに左右の白線データがありません。")

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        df = pd.read_sql_query(
            """
            SELECT d.auto_id, d.frame_num, d.group_id, d.model_name,
                   d.x1, d.y1, d.x2, d.y2, c.class_name, d.travel_direction
            FROM Detection d
            LEFT JOIN Class c ON d.class_id = c.class_id
            WHERE d.run_id = ? AND d.group_id IS NOT NULL
            """,
            conn,
            params=(run_id,),
        )
    if df.empty:
        print(f"Run ID {run_id}: 距離計算の対象データがありません。")
        return

    tire_mask = _build_tire_mask(df)

    df_tires = df[tire_mask].copy()
    df_vehicles = df[~tire_mask].copy()
    if df_vehicles.empty:
        print(
            f"Run ID {run_id}: 車両用の検出が見つかりませんでした。"
            " 車両モデルとタイヤモデルが同一の場合、Classテーブルに"
            " タイヤのクラス名（例: front_tire）が登録されているか確認してください。"
        )
        return

    try:
        tyre_points = compute_front_right_tire_points(
            df_tires,
            left_line,
            right_line,
        )
    except KeyError:
        tyre_points = df_tires.iloc[0:0][["frame_num", "group_id"]].assign(
            measure_x=pd.Series(dtype=float),
            measure_y=pd.Series(dtype=float),
        )

    enriched = attach_measure_points(
        df_vehicles,
        tyre_points,
        left_line=left_line,
        right_line=right_line,
    )
    enriched = enriched.dropna(subset=["group_id", "measure_x", "measure_y"])
    if enriched.empty:
        print(f"Run ID {run_id}: 前輪の測定点を特定できませんでした。")
        return

    lane_polygon = _build_lane_polygon(left_line, right_line)
    if lane_polygon is not None:
        lane_flags = [
            _classify_lane_flag(row.measure_x, row.measure_y, lane_polygon)
            for row in enriched.itertuples()
        ]
    else:
        lane_flags = [None] * len(enriched)

    centers = enriched[["measure_x", "measure_y"]].to_numpy(np.float64)
    l_dists = _horizontal_distances_to_polyline(
        centers, left_line, VERTICAL_TOLERANCE_PX
    )
    r_dists = _horizontal_distances_to_polyline(
        centers, right_line, VERTICAL_TOLERANCE_PX
    )

    missing_left = ~np.isfinite(l_dists)
    if missing_left.any():
        l_dists[missing_left] = _min_dist_points_to_polyline(centers[missing_left], left_line)

    missing_right = ~np.isfinite(r_dists)
    if missing_right.any():
        r_dists[missing_right] = _min_dist_points_to_polyline(centers[missing_right], right_line)

    nearest = np.minimum(l_dists, r_dists)

    measure_x_values = enriched["measure_x"].to_numpy(np.float64)
    measure_y_values = enriched["measure_y"].to_numpy(np.float64)
    lane_scales_list: list[Optional[float]] = []
    for x_val, y_val, left_px, right_px in zip(
        measure_x_values, measure_y_values, l_dists, r_dists
    ):
        scale = None
        if np.isfinite(y_val):
            x_arg = float(x_val) if np.isfinite(x_val) else None
            scale = lane_scale_at_point(
                x_arg,
                float(y_val),
                left_line,
                right_line,
                center_line,
                left_inner_line,
                right_inner_line,
            )
        if scale is None and np.isfinite(left_px) and np.isfinite(right_px):
            width_px = left_px + right_px
            if width_px > 0:
                scale = width_px / LANE_WIDTH_METERS
        lane_scales_list.append(scale)

    lane_scales = np.array(
        [scale if scale and scale > 0 else np.nan for scale in lane_scales_list],
        dtype=np.float64,
    )

    with np.errstate(divide="ignore", invalid="ignore"):
        l_dists_m = np.where(np.isfinite(lane_scales), l_dists / lane_scales, np.nan)
        r_dists_m = np.where(np.isfinite(lane_scales), r_dists / lane_scales, np.nan)
        nearest_m = np.where(np.isfinite(lane_scales), nearest / lane_scales, np.nan)

    l_dists_cm = l_dists_m * CM_PER_METER
    r_dists_cm = r_dists_m * CM_PER_METER
    nearest_cm = nearest_m * CM_PER_METER

    def _normalize_distance(value: float) -> Optional[float]:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(numeric):
            return None
        return numeric

    updates: list[tuple] = []
    measure_x_values = enriched["measure_x"].to_numpy(np.float64)
    measure_y_values = enriched["measure_y"].to_numpy(np.float64)
    center_x_values = ((enriched["x1"] + enriched["x2"]) / 2).to_numpy(np.float64)
    center_y_values = ((enriched["y1"] + enriched["y2"]) / 2).to_numpy(np.float64)
    bbox_x1_values = enriched["x1"].to_numpy(np.float64)
    bbox_x2_values = enriched["x2"].to_numpy(np.float64)
    bbox_y2_values = enriched["y2"].to_numpy(np.float64)
    class_name_values = enriched.get("class_name", pd.Series([""] * len(enriched))).astype(str).str.lower()
    direction_values = (
        enriched.get("travel_direction", pd.Series([""] * len(enriched)))
        .astype(str)
        .str.strip()
        .str.upper()
    )
    for idx, (
        left_px,
        left_m,
        left_cm,
        right_px,
        right_m,
        right_cm,
        near_px,
        near_m,
        near_cm,
        flag,
        auto_id,
    ) in enumerate(
        zip(
            l_dists,
            l_dists_m,
            l_dists_cm,
            r_dists,
            r_dists_m,
            r_dists_cm,
            nearest,
            nearest_m,
            nearest_cm,
            lane_flags,
            enriched["auto_id"].to_numpy(np.int64),
        )
    ):
        l_cross_m = None
        r_cross_m = None
        center_status = None
        white_status = None
        
        if flag == '-':
            # If outside, the smaller distance is the crossing amount
            if np.isfinite(left_m) and np.isfinite(right_m):
                if left_m < right_m:
                    l_cross_m = left_m
                else:
                    r_cross_m = right_m
            elif np.isfinite(left_m):
                l_cross_m = left_m
            elif np.isfinite(right_m):
                r_cross_m = right_m

        if direction_values.iloc[idx] == "B":
            center_line_x = get_line_x_at_y(bbox_y2_values[idx], center_line) if center_line else None
            if center_line_x is not None and np.isfinite(bbox_x1_values[idx]):
                # 左が越え、右が中
                center_status = "中央線越え" if bbox_x1_values[idx] < center_line_x else "中央線内側"

            class_name = class_name_values.iloc[idx]
            if "bicycle" in class_name or "bike" in class_name or "cyclist" in class_name:
                white_y = measure_y_values[idx] if np.isfinite(measure_y_values[idx]) else bbox_y2_values[idx]
                white_x = measure_x_values[idx] if np.isfinite(measure_x_values[idx]) else center_x_values[idx]
                right_line_x = get_line_x_at_y(white_y, right_line) if right_line else None
                if right_line_x is not None and np.isfinite(white_x):
                    # 右側が中、左側が越え
                    white_status = "白線内側" if white_x > right_line_x else "白線越え"

        elif direction_values.iloc[idx] == "F":
            # For 'F': Left=White, Right=Center
            center_line_x = get_line_x_at_y(bbox_y2_values[idx], right_line) if right_line else None
            if center_line_x is not None and np.isfinite(bbox_x2_values[idx]):
                # 右側が越え (x > center_line_x)
                center_status = "中央線越え" if bbox_x2_values[idx] > center_line_x else "中央線内側"

            class_name = class_name_values.iloc[idx]
            if "bicycle" in class_name or "bike" in class_name or "cyclist" in class_name:
                white_y = measure_y_values[idx] if np.isfinite(measure_y_values[idx]) else bbox_y2_values[idx]
                white_x = measure_x_values[idx] if np.isfinite(measure_x_values[idx]) else center_x_values[idx]
                left_line_x = get_line_x_at_y(white_y, left_line) if left_line else None
                if left_line_x is not None and np.isfinite(white_x):
                    # 左側が越え (x < left_line_x)
                    white_status = "白線越え" if white_x < left_line_x else "白線内側"

        updates.append(
            (
                _normalize_distance(measure_x_values[idx]),
                _normalize_distance(measure_y_values[idx]),
                _normalize_distance(left_px),
                _normalize_distance(left_m),
                _normalize_distance(left_cm),
                _normalize_distance(right_px),
                _normalize_distance(right_m),
                _normalize_distance(right_cm),
                _normalize_distance(near_px),
                _normalize_distance(near_m),
                _normalize_distance(near_cm),
                flag if isinstance(flag, str) and flag in {"+", "-"} else None,
                _normalize_distance(l_cross_m),
                _normalize_distance(r_cross_m),
                center_status,
                white_status,
                int(auto_id),
            )
        )

    if not updates:
        print(f"Run ID {run_id}: 更新対象の車両がありません。")
        return

    with sqlite3.connect(MAIN_DB_PATH) as conn:
        conn.executemany(
            """
            UPDATE Detection
            SET measure_x = ?,
                measure_y = ?,
                l_line_distance = ?,
                l_line_distance_m = ?,
                l_line_distance_cm = ?,
                r_line_distance = ?,
                r_line_distance_m = ?,
                r_line_distance_cm = ?,
                line_distance = ?,
                line_distance_m = ?,
                line_distance_cm = ?,
                lane_position_flag = ?,
                l_line_cross_m = ?,
                r_line_cross_m = ?,
                center_line_overtake_status = ?,
                white_line_overtake_status = ?
            WHERE auto_id = ?
            """,
            updates,
        )
    print(f"Run ID {run_id}: {len(updates)}件の白線距離を更新しました。")
_TIRE_PATTERN = re.compile(r"tire|tyre|wheel")


def _build_tire_mask(df: pd.DataFrame) -> pd.Series:
    class_mask = df.get("class_name")
    tire_mask = pd.Series(False, index=df.index)
    if class_mask is not None:
        tire_mask = class_mask.astype(str).str.lower().str.contains(_TIRE_PATTERN, na=False)

    if tire_mask.any():
        return tire_mask

    if "model_name" in df.columns:
        model_lower = df["model_name"].astype(str).str.lower()
        contains_best = model_lower.eq("best")
        if contains_best.any() and not contains_best.all():
            return contains_best

    return tire_mask
