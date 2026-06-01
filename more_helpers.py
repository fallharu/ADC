from __future__ import annotations

import math
from typing import Any, Mapping, Optional


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric):
        return None
    return numeric


def _collect_event_measurement_y_values(event: Mapping[str, Any]) -> list[float]:
    if not isinstance(event, Mapping):
        return []
    values: list[float] = []
    for prefix in ("overtaker", "overtaken"):
        for suffix in ("measure_y", "manual_measure_y", "y2"):
            key = f"{prefix}_{suffix}"
            numeric = _float_or_none(event.get(key))
            if numeric is not None:
                values.append(numeric)
    return values


def _point_to_int_tuple(value: Any) -> Optional[tuple[int, int]]:
    if isinstance(value, Mapping):
        x_val = _float_or_none(value.get("x"))
        y_val = _float_or_none(value.get("y"))
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        x_val = _float_or_none(value[0])
        y_val = _float_or_none(value[1])
    else:
        return None

    if x_val is None or y_val is None:
        return None
    return int(round(x_val)), int(round(y_val))


def _bbox_from_mapping(det: Mapping[str, Any]) -> Optional[tuple[int, int, int, int]]:
    x1 = _float_or_none(det.get("x1"))
    y1 = _float_or_none(det.get("y1"))
    x2 = _float_or_none(det.get("x2"))
    y2 = _float_or_none(det.get("y2"))
    if None in (x1, y1, x2, y2):
        return None
    return (int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))


def _manual_event_detection_from_prefix(
    event: Mapping[str, Any], prefix: str
) -> dict[str, Any]:
    return {
        "measure_x": event.get(f"{prefix}_measure_x"),
        "measure_y": event.get(f"{prefix}_measure_y"),
        "manual_measure_x": event.get(f"{prefix}_measure_x"),
        "manual_measure_y": event.get(f"{prefix}_measure_y"),
        "x1": event.get(f"{prefix}_x1"),
        "y1": event.get(f"{prefix}_y1"),
        "x2": event.get(f"{prefix}_x2"),
        "y2": event.get(f"{prefix}_y2"),
        "scale_pixels_per_meter": event.get("scale_pixels_per_meter"),
        "x_pixels_per_meter": event.get("x_pixels_per_meter"),
    }


def _collect_tire_bboxes(event: Mapping[str, Any]) -> dict[str, list[tuple[int, int, int, int]]]:
    return {}
