"""手動追い越しタブ専用の距離計算ユーティリティ。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence, Tuple


Point = Tuple[float, float]


@dataclass
class LaneLineSet:
    left: Optional[Sequence[Sequence[object]]]
    right: Optional[Sequence[Sequence[object]]]
    center: Optional[Sequence[Sequence[object]]]
    left_inner: Optional[Sequence[Sequence[object]]] = None
    right_inner: Optional[Sequence[Sequence[object]]] = None

    def __iter__(self):
        yield self.left
        yield self.right
        yield self.center


LANE_WIDTH_METERS = 8.0
VERTICAL_TOLERANCE_PX = 5.0
LANE_CONFIRMATION_HALF_SPAN_PX = 15.0


def _to_float(value: object) -> Optional[float]:
    try:
        if value is None:
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric):
        return None
    return numeric


def _distance_to_white_lines(
    point: Point,
    left_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
) -> float:
    horiz_left = _horizontal_distance_to_line(point, left_line)
    horiz_right = _horizontal_distance_to_line(point, right_line)
    best = min(horiz_left, horiz_right)
    if math.isfinite(best):
        return best
    euclid_left = _euclid_distance_to_polyline(point, left_line)
    euclid_right = _euclid_distance_to_polyline(point, right_line)
    return min(euclid_left, euclid_right)


def _measurement_from_bbox(
    det: Mapping[str, object],
    left_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
) -> tuple[Optional[float], Optional[float]]:
    y2 = _to_float(det.get("y2"))
    if y2 is None:
        return None, None

    candidates: list[tuple[float, float, float]] = []
    for key in ("x1", "x2"):
        x_val = _to_float(det.get(key))
        if x_val is None:
            continue
        distance = _distance_to_white_lines((x_val, y2), left_line, right_line)
        candidates.append((distance, x_val, y2))

    if candidates:
        best_distance, best_x, best_y = min(
            candidates,
            key=lambda item: (
                item[0],
                -(item[2] if math.isfinite(item[2]) else float("-inf")),
                -(item[1] if math.isfinite(item[1]) else float("-inf")),
            ),
        )
        if math.isfinite(best_distance):
            return best_x, best_y

    return _to_float(det.get("x2")), y2


def select_measure_point_from_candidates(
    candidates: Sequence[Mapping[str, object]],
    left_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
) -> tuple[Optional[float], Optional[float]]:
    """候補となる検出の中から白線に最も近い測定点を選択する。

    グループ内に複数のタイヤ検出が存在する場合でも、白線との距離が
    最も短い右下角を持つ候補を選択する。白線情報がない場合は
    :func:`_measurement_from_bbox` のフォールバックに従う。
    """

    best_choice: Optional[tuple[tuple[float, float, float], float, float]] = None
    for det in candidates:
        if not isinstance(det, Mapping):
            continue

        measure_x, measure_y = _measurement_from_bbox(det, left_line, right_line)
        if None in (measure_x, measure_y):
            continue

        distance = _distance_to_white_lines((measure_x, measure_y), left_line, right_line)
        rank = (
            distance if math.isfinite(distance) else float("inf"),
            -(measure_y if math.isfinite(measure_y) else float("-inf")),
            -(measure_x if math.isfinite(measure_x) else float("-inf")),
        )

        if best_choice is None or rank < best_choice[0]:
            best_choice = (rank, measure_x, measure_y)

    if best_choice is None:
        return None, None

    return best_choice[1], best_choice[2]


def _bbox_contains(candidate: tuple[float, float, float, float], base: tuple[float, float, float, float]) -> bool:
    cx1, cy1, cx2, cy2 = candidate
    bx1, by1, bx2, by2 = base
    return cx1 >= bx1 and cy1 >= by1 and cx2 <= bx2 and cy2 <= by2


def select_bicycle_tire_measure_point(
    bicycle_bbox: Mapping[str, object],
    candidates: Sequence[Mapping[str, object]],
    left_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
) -> tuple[Optional[float], Optional[float]]:
    """自転車BBOX内で最大のタイヤから測定点を決める。"""

    bike_x1 = _to_float(bicycle_bbox.get("x1"))
    bike_y1 = _to_float(bicycle_bbox.get("y1"))
    bike_x2 = _to_float(bicycle_bbox.get("x2"))
    bike_y2 = _to_float(bicycle_bbox.get("y2"))
    if None in (bike_x1, bike_y1, bike_x2, bike_y2):
        return select_measure_point_from_candidates(candidates, left_line, right_line)

    bike_bbox = (bike_x1, bike_y1, bike_x2, bike_y2)
    best: Optional[tuple[tuple[float, float, float, float], float, float]] = None

    for det in candidates:
        if not isinstance(det, Mapping):
            continue

        x1 = _to_float(det.get("x1"))
        y1 = _to_float(det.get("y1"))
        x2 = _to_float(det.get("x2"))
        y2 = _to_float(det.get("y2"))
        if None in (x1, y1, x2, y2):
            continue

        if not _bbox_contains((x1, y1, x2, y2), bike_bbox):
            continue

        area = (x2 - x1) * (y2 - y1)
        if not math.isfinite(area) or area <= 0:
            continue

        corner_candidates = []
        for corner_x in (x1, x2):
            distance = _distance_to_white_lines((corner_x, y2), left_line, right_line)
            corner_candidates.append((distance, corner_x, y2))

        if not corner_candidates:
            continue

        best_corner = min(
            corner_candidates,
            key=lambda item: (
                item[0],
                -(item[2] if math.isfinite(item[2]) else float("-inf")),
                -(item[1] if math.isfinite(item[1]) else float("-inf")),
            ),
        )

        rank = (
            -area,
            best_corner[0],
            -(best_corner[2] if math.isfinite(best_corner[2]) else float("-inf")),
            -(best_corner[1] if math.isfinite(best_corner[1]) else float("-inf")),
        )

        if best is None or rank < best[0]:
            best = (rank, best_corner[1], best_corner[2])

    if best is None:
        return select_measure_point_from_candidates(candidates, left_line, right_line)

    return best[1], best[2]


def _measurement_point(
    det: Mapping[str, object],
    left_line: Optional[Sequence[Sequence[object]]] = None,
    right_line: Optional[Sequence[Sequence[object]]] = None,
) -> tuple[Optional[float], Optional[float]]:
    """Bounding box右下座標または既存の測定点を返す。"""

    x_candidates: Iterable[object] = (
        det.get("measure_x"),
        det.get("manual_measure_x"),
        det.get("x2"),
    )
    y_candidates: Iterable[object] = (
        det.get("measure_y"),
        det.get("manual_measure_y"),
        det.get("y2"),
    )

    measure_x = next((val for val in map(_to_float, x_candidates) if val is not None), None)
    measure_y = next((val for val in map(_to_float, y_candidates) if val is not None), None)
    if None not in (measure_x, measure_y):
        return measure_x, measure_y

    if left_line or right_line:
        fallback_x, fallback_y = _measurement_from_bbox(det, left_line, right_line)
        if None not in (fallback_x, fallback_y):
            return fallback_x, fallback_y

    return _to_float(det.get("x2")), _to_float(det.get("y2"))


def _vertical_scale(det: Mapping[str, object]) -> Optional[float]:
    value = _to_float(det.get("scale_pixels_per_meter"))
    if value and value > 0:
        return value
    return None


def _mean(values: Iterable[float]) -> Optional[float]:
    vals = [val for val in values if val is not None]
    if not vals:
        return None
    return float(sum(vals) / len(vals))


def _horizontal_distance_to_line(point: Point, line: Sequence[Sequence[object]]) -> float:
    """同一y高さでの水平距離。該当セグメントが無ければinf。"""

    if not line:
        return math.inf
    px, py = point
    best = math.inf
    for idx in range(len(line) - 1):
        x1 = _to_float(line[idx][0])
        y1 = _to_float(line[idx][1])
        x2 = _to_float(line[idx + 1][0])
        y2 = _to_float(line[idx + 1][1])
        if None in (x1, y1, x2, y2):
            continue
        y_low = min(y1, y2)
        y_high = max(y1, y2)
        if py < y_low or py > y_high:
            continue
        if y2 == y1:
            # 水平線は対象外
            continue
        if x2 == x1:
            x_line = x1
        else:
            slope = (x2 - x1) / (y2 - y1)
            x_line = x1 + slope * (py - y1)
        dist = abs(px - x_line)
        if dist < best:
            best = dist
    return best


def _euclid_distance_to_polyline(point: Point, line: Sequence[Sequence[object]]) -> float:
    if not line:
        return math.inf
    px, py = point
    best = math.inf
    for idx in range(len(line) - 1):
        x1 = _to_float(line[idx][0])
        y1 = _to_float(line[idx][1])
        x2 = _to_float(line[idx + 1][0])
        y2 = _to_float(line[idx + 1][1])
        if None in (x1, y1, x2, y2):
            continue
        dx = x2 - x1
        dy = y2 - y1
        denom = dx * dx + dy * dy
        if denom <= 0:
            dist = math.hypot(px - x1, py - y1)
        else:
            t = ((px - x1) * dx + (py - y1) * dy) / denom
            t = max(0.0, min(1.0, t))
            proj_x = x1 + t * dx
            proj_y = y1 + t * dy
            dist = math.hypot(px - proj_x, py - proj_y)
        if dist < best:
            best = dist
    return best


def _restrict_polyline_vertical_band(
    line: Optional[Sequence[Sequence[object]]],
    y_min: float,
    y_max: float,
) -> Optional[list[list[float]]]:
    if not line:
        return line  # type: ignore[return-value]

    if y_min > y_max:
        y_min, y_max = y_max, y_min

    clipped: list[list[float]] = []

    def _append_point(x_val: float, y_val: float) -> None:
        if not math.isfinite(x_val) or not math.isfinite(y_val):
            return
        if clipped:
            last_x, last_y = clipped[-1]
            if math.isclose(last_x, x_val, abs_tol=1e-6) and math.isclose(
                last_y, y_val, abs_tol=1e-6
            ):
                return
        clipped.append([float(x_val), float(y_val)])

    for idx in range(len(line) - 1):
        try:
            x1 = _to_float(line[idx][0])
            y1 = _to_float(line[idx][1])
            x2 = _to_float(line[idx + 1][0])
            y2 = _to_float(line[idx + 1][1])
        except (IndexError, TypeError, ValueError):
            continue

        if None in (x1, y1, x2, y2):
            continue

        if (y1 < y_min and y2 < y_min) or (y1 > y_max and y2 > y_max):
            continue

        start_x, start_y = x1, y1
        end_x, end_y = x2, y2

        if y1 < y_min and y2 != y1:
            t = (y_min - y1) / (y2 - y1)
            start_x = x1 + t * (x2 - x1)
            start_y = y_min
        elif y1 > y_max and y2 != y1:
            t = (y_max - y1) / (y2 - y1)
            start_x = x1 + t * (x2 - x1)
            start_y = y_max

        if y2 < y_min and y2 != y1:
            t = (y_min - y1) / (y2 - y1)
            end_x = x1 + t * (x2 - x1)
            end_y = y_min
        elif y2 > y_max and y2 != y1:
            t = (y_max - y1) / (y2 - y1)
            end_x = x1 + t * (x2 - x1)
            end_y = y_max

        _append_point(start_x, start_y)
        _append_point(end_x, end_y)

    if len(clipped) >= 2:
        return clipped

    fallback: list[list[float]] = []
    for point in line:
        try:
            px = _to_float(point[0])
            py = _to_float(point[1])
        except (IndexError, TypeError, ValueError):
            continue
        if None in (px, py):
            continue
        if y_min <= py <= y_max:
            fallback.append([float(px), float(py)])

    if len(fallback) >= 2:
        return fallback

    return line  # type: ignore[return-value]


def _interpolate_x_at_y(
    line: Optional[Sequence[Sequence[object]]],
    target_y: float,
    *,
    tolerance: float = VERTICAL_TOLERANCE_PX,
) -> Optional[float]:
    if not line:
        return None

    best_x: Optional[float] = None
    best_diff = float("inf")

    for idx in range(len(line) - 1):
        try:
            x1 = _to_float(line[idx][0])
            y1 = _to_float(line[idx][1])
            x2 = _to_float(line[idx + 1][0])
            y2 = _to_float(line[idx + 1][1])
        except (IndexError, TypeError, ValueError):
            continue

        if None in (x1, y1, x2, y2):
            continue

        if y1 == y2:
            diff = abs(target_y - y1)
            if diff <= tolerance and diff < best_diff:
                best_diff = diff
                best_x = (x1 + x2) / 2.0
            continue

        y_min = min(y1, y2) - tolerance
        y_max = max(y1, y2) + tolerance
        if target_y < y_min or target_y > y_max:
            continue

        clamped_y = min(max(target_y, min(y1, y2)), max(y1, y2))
        t = (clamped_y - y1) / (y2 - y1)
        x_val = x1 + t * (x2 - x1)
        diff = abs(target_y - clamped_y)
        if diff < best_diff:
            best_diff = diff
            best_x = x_val
            if diff == 0:
                break

    return best_x


def lane_scale_at_y(
    target_y: Optional[float],
    left_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
    center_line: Optional[Sequence[Sequence[object]]] = None,
    left_inner_line: Optional[Sequence[Sequence[object]]] = None,
    right_inner_line: Optional[Sequence[Sequence[object]]] = None,
    *,
    lane_width_m: float = LANE_WIDTH_METERS,
) -> Optional[float]:
    return lane_scale_details_at_y(
        target_y,
        left_line,
        right_line,
        center_line=center_line,
        left_inner_line=left_inner_line,
        right_inner_line=right_inner_line,
        lane_width_m=lane_width_m,
    ).pixels_per_meter


def lane_scale_at_point(
    target_x: Optional[float],
    target_y: Optional[float],
    left_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
    center_line: Optional[Sequence[Sequence[object]]] = None,
    left_inner_line: Optional[Sequence[Sequence[object]]] = None,
    right_inner_line: Optional[Sequence[Sequence[object]]] = None,
    *,
    lane_width_m: float = LANE_WIDTH_METERS,
) -> Optional[float]:
    details = lane_scale_details_at_y(
        target_y,
        left_line,
        right_line,
        center_line=center_line,
        left_inner_line=left_inner_line,
        right_inner_line=right_inner_line,
        lane_width_m=lane_width_m,
    )

    if not details.is_available:
        return details.pixels_per_meter

    try:
        x_val = float(target_x) if target_x is not None else None
    except (TypeError, ValueError):
        x_val = None

    center_point = details.center_point
    center_x = None
    if center_point is not None:
        try:
            center_x = float(center_point[0])
        except (TypeError, ValueError):
            center_x = None

    if x_val is None:
        return details.pixels_per_meter

    anchors = details.anchor_points or []
    if len(anchors) < 2:
        if center_x is None:
            return details.pixels_per_meter
        if x_val <= center_x:
            return details.left_pixels_per_meter or details.pixels_per_meter
        return details.right_pixels_per_meter or details.pixels_per_meter

    anchors_sorted = sorted(anchors, key=lambda item: item[0])
    segment = None
    if x_val <= anchors_sorted[0][0]:
        segment = anchors_sorted[0], anchors_sorted[1]
    elif x_val >= anchors_sorted[-1][0]:
        segment = anchors_sorted[-2], anchors_sorted[-1]
    else:
        for idx in range(len(anchors_sorted) - 1):
            left_anchor = anchors_sorted[idx]
            right_anchor = anchors_sorted[idx + 1]
            if left_anchor[0] <= x_val <= right_anchor[0]:
                segment = (left_anchor, right_anchor)
                break

    if not segment:
        return details.pixels_per_meter

    (x1, dist1), (x2, dist2) = segment
    delta_dist = dist2 - dist1
    if not delta_dist:
        return details.pixels_per_meter

    pixels_per_meter = abs((x2 - x1) / delta_dist)
    if pixels_per_meter and pixels_per_meter > 0:
        return pixels_per_meter

    if center_x is None:
        return details.pixels_per_meter
    if x_val <= center_x:
        return details.left_pixels_per_meter or details.pixels_per_meter
    return details.right_pixels_per_meter or details.pixels_per_meter


def lane_scale_details_at_y(
    target_y: Optional[float],
    left_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
    *,
    lane_width_m: float = LANE_WIDTH_METERS,
    center_line: Optional[Sequence[Sequence[object]]] = None,
    left_inner_line: Optional[Sequence[Sequence[object]]] = None,
    right_inner_line: Optional[Sequence[Sequence[object]]] = None,
) -> LaneScaleDetails:
    try:
        y_val = float(target_y) if target_y is not None else None
    except (TypeError, ValueError):
        y_val = None

    if y_val is None:
        return LaneScaleDetails(None, None, None, None, lane_width_m)

    left_x = _interpolate_x_at_y(left_line, y_val)
    right_x = _interpolate_x_at_y(right_line, y_val)
    center_x = _interpolate_x_at_y(center_line, y_val) if center_line else None
    left_mid_x = (
        _interpolate_x_at_y(left_inner_line, y_val) if left_inner_line else None
    )
    right_mid_x = (
        _interpolate_x_at_y(right_inner_line, y_val) if right_inner_line else None
    )

    if center_x is None and None not in (left_x, right_x):
        center_x = (float(left_x) + float(right_x)) / 2.0

    if left_x is None or right_x is None:
        lane_half_width_m = lane_width_m / 2.0 if lane_width_m else None
        if center_x is not None and lane_half_width_m:
            if right_x is not None:
                left_x = center_x - abs(right_x - center_x)
            elif left_x is not None:
                right_x = center_x + abs(center_x - left_x)
        if left_x is None or right_x is None:
            return LaneScaleDetails(y_val, None, None, None, lane_width_m)

    lane_width_px = abs(right_x - left_x)
    if lane_width_px <= 0:
        return LaneScaleDetails(
            y_val,
            (left_x, y_val),
            (right_x, y_val),
            None,
            lane_width_m,
        )

    pixels_per_meter = lane_width_px / lane_width_m if lane_width_m else None
    meters_per_pixel = lane_width_m / lane_width_px if lane_width_px else None
    centimeters_per_pixel = (
        meters_per_pixel * 100.0 if meters_per_pixel is not None else None
    )

    half_width_m = lane_width_m / 2.0 if lane_width_m else None
    quarter_width_m = lane_width_m / 4.0 if lane_width_m else None
    left_segment_px = None
    right_segment_px = None
    left_mid_segment_px = None
    right_mid_segment_px = None
    left_pixels_per_meter = None
    right_pixels_per_meter = None
    left_mid_pixels_per_meter = None
    right_mid_pixels_per_meter = None

    anchor_points: list[tuple[float, float]] = []
    anchor_points.append((float(left_x), 0.0))

    if center_x is not None:
        if left_x is not None:
            left_segment_px = abs(float(center_x) - float(left_x))
        if right_x is not None:
            right_segment_px = abs(float(right_x) - float(center_x))
    if left_mid_x is not None and quarter_width_m:
        left_mid_segment_px = abs(float(left_mid_x) - float(left_x))
        anchor_points.append((float(left_mid_x), quarter_width_m))
    if center_x is not None:
        anchor_points.append((float(center_x), lane_width_m / 2.0 if lane_width_m else 0.0))
    if right_mid_x is not None and quarter_width_m:
        right_mid_segment_px = abs(float(right_x) - float(right_mid_x))
        anchor_points.append((float(right_mid_x), lane_width_m - quarter_width_m))
    anchor_points.append((float(right_x), lane_width_m))

    if half_width_m and half_width_m > 0:
        if left_segment_px is not None and left_segment_px > 0:
            left_pixels_per_meter = left_segment_px / half_width_m
        if right_segment_px is not None and right_segment_px > 0:
            right_pixels_per_meter = right_segment_px / half_width_m
    if quarter_width_m and quarter_width_m > 0:
        if left_mid_segment_px is not None and left_mid_segment_px > 0:
            left_mid_pixels_per_meter = left_mid_segment_px / quarter_width_m
        if right_mid_segment_px is not None and right_mid_segment_px > 0:
            right_mid_pixels_per_meter = right_mid_segment_px / quarter_width_m

    return LaneScaleDetails(
        y_val,
        (left_x, y_val),
        (right_x, y_val),
        lane_width_px,
        lane_width_m,
        pixels_per_meter,
        meters_per_pixel,
        centimeters_per_pixel,
        center_point=(center_x, y_val) if center_x is not None else None,
        left_segment_px=left_segment_px,
        right_segment_px=right_segment_px,
        left_pixels_per_meter=left_pixels_per_meter,
        right_pixels_per_meter=right_pixels_per_meter,
        left_mid_point=(left_mid_x, y_val) if left_mid_x is not None else None,
        right_mid_point=(right_mid_x, y_val) if right_mid_x is not None else None,
        left_mid_segment_px=left_mid_segment_px,
        right_mid_segment_px=right_mid_segment_px,
        left_mid_pixels_per_meter=left_mid_pixels_per_meter,
        right_mid_pixels_per_meter=right_mid_pixels_per_meter,
        anchor_points=anchor_points,
    )


def restrict_lane_lines_vertical(
    lane_lines: "LaneLineSet",
    y_min: Optional[float],
    y_max: Optional[float],
) -> "LaneLineSet":
    if y_min is None or y_max is None:
        return lane_lines

    return LaneLineSet(
        _restrict_polyline_vertical_band(lane_lines.left, y_min, y_max),
        _restrict_polyline_vertical_band(lane_lines.right, y_min, y_max),
        _restrict_polyline_vertical_band(lane_lines.center, y_min, y_max),
        _restrict_polyline_vertical_band(lane_lines.left_inner, y_min, y_max),
        _restrict_polyline_vertical_band(lane_lines.right_inner, y_min, y_max),
    )


def _lane_distances_at_point(
    point: Point,
    left_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
) -> tuple[Optional[float], Optional[float]]:
    def _distance(line: Optional[Sequence[Sequence[object]]]) -> Optional[float]:
        if not line:
            return None
        horizontal = _horizontal_distance_to_line(point, line)
        if not math.isfinite(horizontal):
            horizontal = _euclid_distance_to_polyline(point, line)
        return float(horizontal) if math.isfinite(horizontal) else None

    left_px = _distance(left_line)
    right_px = _distance(right_line)
    return left_px, right_px


def _lane_scale_from_distances(
    left_px: Optional[float],
    right_px: Optional[float],
    *,
    lane_width_m: float = LANE_WIDTH_METERS,
) -> Optional[float]:
    if left_px is None or right_px is None:
        return None
    lane_width_px = left_px + right_px
    if lane_width_px <= 0:
        return None
    lane_width_m_val = lane_width_m if lane_width_m else LANE_WIDTH_METERS
    return lane_width_px / lane_width_m_val


@dataclass
class ClearanceResult:
    distance_px: Optional[float]
    distance_m: Optional[float]
    distance_cm: Optional[float]


def compute_clearance(
    det_a: Mapping[str, object],
    det_b: Mapping[str, object],
    left_line: Optional[Sequence[Sequence[object]]] = None,
    right_line: Optional[Sequence[Sequence[object]]] = None,
    center_line: Optional[Sequence[Sequence[object]]] = None,
    left_inner_line: Optional[Sequence[Sequence[object]]] = None,
    right_inner_line: Optional[Sequence[Sequence[object]]] = None,
    *,
    lane_width_m: float = LANE_WIDTH_METERS,
) -> ClearanceResult:
    ax, ay = _measurement_point(det_a, left_line, right_line)
    bx, by = _measurement_point(det_b, left_line, right_line)
    if None in (ax, ay, bx, by):
        return ClearanceResult(None, None, None)

    dx_px = float(ax - bx)
    dy_px = float(ay - by)
    distance_px = math.hypot(dx_px, dy_px)

    lane_scales: list[float] = []
    if left_line or right_line:
        for x_val, y_val in ((ax, ay), (bx, by)):
            scale = lane_scale_at_point(
                x_val,
                y_val,
                left_line,
                right_line,
                center_line,
                left_inner_line,
                right_inner_line,
                lane_width_m=lane_width_m,
            )
            if scale and scale > 0:
                lane_scales.append(scale)

    x_scale = _mean(lane_scales) if lane_scales else None
    y_scale = _mean(
        filter(
            lambda v: v is not None,
            (
                _vertical_scale(det_a),
                _vertical_scale(det_b),
            ),
        )
    )

    distance_m: Optional[float] = None
    fallback_scale = x_scale or y_scale
    if x_scale and y_scale:
        distance_m = math.hypot(dx_px / x_scale, dy_px / y_scale)
    elif fallback_scale:
        distance_m = math.hypot(dx_px / fallback_scale, dy_px / fallback_scale)

    distance_cm = distance_m * 100.0 if distance_m is not None else None
    return ClearanceResult(distance_px, distance_m, distance_cm)


@dataclass
class LaneDistanceResult:
    distance_px: Optional[float]
    distance_m: Optional[float]
    left_distance_px: Optional[float] = None
    left_distance_m: Optional[float] = None
    right_distance_px: Optional[float] = None
    right_distance_m: Optional[float] = None
    measure_x: Optional[float] = None
    measure_y: Optional[float] = None
    is_inner: bool = True


def compute_lane_distance(
    det: Mapping[str, object],
    left_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
    center_line: Optional[Sequence[Sequence[object]]] = None,
    left_inner_line: Optional[Sequence[Sequence[object]]] = None,
    right_inner_line: Optional[Sequence[Sequence[object]]] = None,
    *,
    lane_width_m: float = LANE_WIDTH_METERS,
) -> LaneDistanceResult:
    measure = _measurement_point(det, left_line, right_line)
    if None in measure:
        return LaneDistanceResult(
            None,
            None,
            left_distance_px=None,
            left_distance_m=None,
            right_distance_px=None,
            right_distance_m=None,
            measure_x=None,
            measure_y=None,
            is_inner=False,
        )

    measure_x, measure_y = measure
    point = float(measure_x), float(measure_y)
    left_px, right_px = _lane_distances_at_point(point, left_line, right_line)

    candidates = [value for value in (left_px, right_px) if value is not None]
    nearest_px = min(candidates) if candidates else math.inf

    if not math.isfinite(nearest_px):
        return LaneDistanceResult(
            None,
            None,
            left_distance_px=left_px,
            left_distance_m=None,
            right_distance_px=right_px,
            right_distance_m=None,
            measure_x=measure_x,
            measure_y=measure_y,
            is_inner=False,
        )

    scale_details = lane_scale_details_at_y(
        measure_y,
        left_line,
        right_line,
        center_line=center_line,
        left_inner_line=left_inner_line,
        right_inner_line=right_inner_line,
        lane_width_m=lane_width_m,
    )
    lane_scale = scale_details.pixels_per_meter

    is_inner = True
    if scale_details.is_available and scale_details.left_point and scale_details.right_point:
        lx = _to_float(scale_details.left_point[0])
        rx = _to_float(scale_details.right_point[0])
        mx = measure_x
        if lx is not None and rx is not None and mx is not None:
             # Assuming left < right, but handle swap
             min_x, max_x = min(lx, rx), max(lx, rx)
             is_inner = (min_x <= mx <= max_x)
    if lane_scale is None:
        lane_scale = _lane_scale_from_distances(
            left_px,
            right_px,
            lane_width_m=lane_width_m,
        )

    x_scale = lane_scale if lane_scale is not None else _vertical_scale(det)

    def _convert(px_value: Optional[float]) -> Optional[float]:
        if px_value is None:
            return None
        return px_value / x_scale if x_scale else None

    return LaneDistanceResult(
        nearest_px,
        _convert(nearest_px),
        left_distance_px=left_px,
        left_distance_m=_convert(left_px) if left_px is not None else None,
        right_distance_px=right_px,
        right_distance_m=_convert(right_px) if right_px is not None else None,
        measure_x=measure_x,
        measure_y=measure_y,
        is_inner=is_inner,
    )


@dataclass
class LaneScaleDetails:
    y: Optional[float]
    left_point: Optional[Point]
    right_point: Optional[Point]
    lane_width_px: Optional[float]
    lane_width_m: float = LANE_WIDTH_METERS
    pixels_per_meter: Optional[float] = None
    meters_per_pixel: Optional[float] = None
    centimeters_per_pixel: Optional[float] = None
    center_point: Optional[Point] = None
    left_segment_px: Optional[float] = None
    right_segment_px: Optional[float] = None
    left_pixels_per_meter: Optional[float] = None
    right_pixels_per_meter: Optional[float] = None
    left_mid_point: Optional[Point] = None
    right_mid_point: Optional[Point] = None
    left_mid_segment_px: Optional[float] = None
    right_mid_segment_px: Optional[float] = None
    left_mid_pixels_per_meter: Optional[float] = None
    right_mid_pixels_per_meter: Optional[float] = None
    anchor_points: Optional[list[tuple[float, float]]] = None

    @property
    def is_available(self) -> bool:
        return (
            self.left_point is not None
            and self.right_point is not None
            and self.lane_width_px is not None
            and self.lane_width_px > 0
        )

    def to_dict(self) -> dict[str, Optional[float]]:
        left_point = None
        if self.left_point is not None:
            left_point = {
                "x": _to_float(self.left_point[0]),
                "y": _to_float(self.left_point[1]),
            }

        right_point = None
        if self.right_point is not None:
            right_point = {
                "x": _to_float(self.right_point[0]),
                "y": _to_float(self.right_point[1]),
            }

        center_point = None
        if self.center_point is not None:
            center_point = {
                "x": _to_float(self.center_point[0]),
                "y": _to_float(self.center_point[1]),
            }

        left_mid_point = None
        if self.left_mid_point is not None:
            left_mid_point = {
                "x": _to_float(self.left_mid_point[0]),
                "y": _to_float(self.left_mid_point[1]),
            }

        right_mid_point = None
        if self.right_mid_point is not None:
            right_mid_point = {
                "x": _to_float(self.right_mid_point[0]),
                "y": _to_float(self.right_mid_point[1]),
            }

        anchor_points = None
        if self.anchor_points:
            anchor_points = [
                {"x": _to_float(x), "distance_m": _to_float(dist)}
                for x, dist in self.anchor_points
            ]

        return {
            "y": _to_float(self.y),
            "lane_width_px": _to_float(self.lane_width_px),
            "lane_width_m": _to_float(self.lane_width_m),
            "pixels_per_meter": _to_float(self.pixels_per_meter),
            "meters_per_pixel": _to_float(self.meters_per_pixel),
            "centimeters_per_pixel": _to_float(self.centimeters_per_pixel),
            "left_point": left_point,
            "right_point": right_point,
            "center_point": center_point,
            "left_segment_px": _to_float(self.left_segment_px),
            "right_segment_px": _to_float(self.right_segment_px),
            "left_pixels_per_meter": _to_float(self.left_pixels_per_meter),
            "right_pixels_per_meter": _to_float(self.right_pixels_per_meter),
            "left_mid_point": left_mid_point,
            "right_mid_point": right_mid_point,
            "left_mid_segment_px": _to_float(self.left_mid_segment_px),
            "right_mid_segment_px": _to_float(self.right_mid_segment_px),
            "left_mid_pixels_per_meter": _to_float(self.left_mid_pixels_per_meter),
            "right_mid_pixels_per_meter": _to_float(self.right_mid_pixels_per_meter),
            "anchor_points": anchor_points,
        }


def load_white_lines(calibration_payload: Optional[Mapping[str, object]]) -> LaneLineSet:
    if not calibration_payload:
        return LaneLineSet(None, None, None)
    lines = calibration_payload.get("lines")
    if not isinstance(lines, Mapping):
        return LaneLineSet(None, None, None)
    left = lines.get("left_white_line")
    right = lines.get("right_white_line")
    center = lines.get("center_line")
    left_inner = (
        lines.get("left_inner_line")
        or lines.get("left_mid_line")
        or lines.get("left_sub_line")
    )
    right_inner = (
        lines.get("right_inner_line")
        or lines.get("right_mid_line")
        or lines.get("right_sub_line")
    )
    return LaneLineSet(
        left if isinstance(left, Sequence) else None,
        right if isinstance(right, Sequence) else None,
        center if isinstance(center, Sequence) else None,
        left_inner if isinstance(left_inner, Sequence) else None,
        right_inner if isinstance(right_inner, Sequence) else None,
    )


def estimate_lane_distance_m(
    det: Mapping[str, object],
    left_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
    center_line: Optional[Sequence[Sequence[object]]] = None,
    left_inner_line: Optional[Sequence[Sequence[object]]] = None,
    right_inner_line: Optional[Sequence[Sequence[object]]] = None,
) -> Optional[float]:
    return compute_lane_distance(
        det,
        left_line,
        right_line,
        center_line,
        left_inner_line,
        right_inner_line,
    ).distance_m


def estimate_lane_distance_px(
    det: Mapping[str, object],
    left_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
    center_line: Optional[Sequence[Sequence[object]]] = None,
    left_inner_line: Optional[Sequence[Sequence[object]]] = None,
    right_inner_line: Optional[Sequence[Sequence[object]]] = None,
) -> Optional[float]:
    return compute_lane_distance(
        det,
        left_line,
        right_line,
        center_line,
        left_inner_line,
        right_inner_line,
    ).distance_px


def estimate_clearance_m(
    det_a: Mapping[str, object],
    det_b: Mapping[str, object],
    left_line: Optional[Sequence[Sequence[object]]] = None,
    right_line: Optional[Sequence[Sequence[object]]] = None,
    center_line: Optional[Sequence[Sequence[object]]] = None,
    left_inner_line: Optional[Sequence[Sequence[object]]] = None,
    right_inner_line: Optional[Sequence[Sequence[object]]] = None,
) -> Optional[float]:
    return compute_clearance(
        det_a,
        det_b,
        left_line,
        right_line,
        center_line,
        left_inner_line,
        right_inner_line,
    ).distance_m

