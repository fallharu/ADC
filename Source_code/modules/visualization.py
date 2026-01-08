import cv2
import numpy as np
from typing import Any, Mapping, Optional, Sequence
from .utils import _to_positive_float, _resolve_lane_width_m

def _format_distance_label(
    value_cm: Optional[float],
    value_m: Optional[float],
    value_px: Optional[float],
) -> str:
    if value_cm is not None:
        return f"{value_cm:.1f} cm"
    if value_m is not None:
        return f"{value_m:.2f} m"
    if value_px is not None:
        return f"{value_px:.0f} px"
    return "-"


def _draw_scale_overlay(
    frame: "np.ndarray",
    event: Mapping[str, Any],
    role_details: Sequence[Mapping[str, Any]],
    scale_segments: Sequence[Mapping[str, Any]],
    *,
    show_lane_distance: bool = False,
    show_clearance: bool = False,
) -> "np.ndarray":
    image = frame.copy()
    lane_width_m = _resolve_lane_width_m(event.get("lane_width_m"))

    def _draw_text(
        img: "np.ndarray",
        text: str,
        origin: tuple[int, int],
        color: tuple[int, int, int],
        *,
        font_scale: float = 0.6,
        thickness: int = 1,
    ) -> None:
        cv2.putText(
            img,
            text,
            origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (0, 0, 0),
            thickness + 2,
            cv2.LINE_AA,
        )
        cv2.putText(
            img,
            text,
            origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color,
            thickness,
            cv2.LINE_AA,
        )

    scale_colors = [(0, 255, 0), (0, 165, 255), (255, 0, 0)]
    for idx, segment in enumerate(scale_segments):
        start_point = segment.get("left_point")
        end_point = segment.get("right_point")

        if start_point and end_point:
            color = scale_colors[idx % len(scale_colors)]
            cv2.line(
                image,
                start_point,
                end_point,
                color,
                2,
                cv2.LINE_AA,
            )
            cv2.circle(image, start_point, 4, color, -1, cv2.LINE_AA)
            cv2.circle(image, end_point, 4, color, -1, cv2.LINE_AA)

    inner_lines_color = (180, 180, 180)
    for segment in scale_segments:
        l_inner = segment.get("left_inner_point")
        r_inner = segment.get("right_inner_point")
        if l_inner and r_inner:
            cv2.circle(image, l_inner, 3, inner_lines_color, -1, cv2.LINE_AA)
            cv2.circle(image, r_inner, 3, inner_lines_color, -1, cv2.LINE_AA)

    measurement_points: dict[str, tuple[int, int]] = {}
    
    # helper for checking if value is usable number
    def _float_or_none(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            numeric = float(value)
            if np.isnan(numeric): return None
            return numeric
        except (TypeError, ValueError):
            return None

    for detail in role_details:
        role = detail.get("role")
        pt = detail.get("measure_point")
        base = detail.get("base_point")
        color = detail.get("color", (255, 255, 0))
        label = detail.get("label", role)

        if pt:
            measurement_points[str(role)] = pt
            cv2.circle(image, pt, 6, color, -1, cv2.LINE_AA)
            if base:
                cv2.line(image, pt, base, color, 1, cv2.LINE_AA)
                cv2.circle(image, base, 3, color, -1, cv2.LINE_AA)

            line_dist_px = _float_or_none(detail.get("distance_px"))
            if line_dist_px is not None:
                x_text = pt[0] + 10
                y_text = pt[1]
                dist_label = _format_distance_label(
                    _float_or_none(detail.get("distance_cm")),
                    _float_or_none(detail.get("distance_m")),
                    line_dist_px,
                )
                if show_lane_distance:
                    _draw_text(
                        image,
                        f"{label}: {dist_label}",
                        (x_text, y_text),
                        color,
                    )

            tire_box = detail.get("bbox")
            if tire_box:
                p1 = (int(tire_box[0]), int(tire_box[1]))
                p2 = (int(tire_box[2]), int(tire_box[3]))
                cv2.rectangle(
                    image,
                    p1,
                    p2,
                    color,
                    1,
                    cv2.LINE_AA,
                )
                _draw_text(
                    image,
                    "Tire bbox",
                    (int(tire_box[0]), int(tire_box[1]) - 6),
                    color,
                    font_scale=0.45,
                )

    if show_clearance and {
        "overtaker",
        "overtaken",
    }.issubset(measurement_points.keys()):
        overtaker_point = measurement_points.get("overtaker")
        overtaken_point = measurement_points.get("overtaken")
        if overtaker_point and overtaken_point:
            clearance_color = (0, 215, 255)
            cv2.line(
                image,
                overtaker_point,
                overtaken_point,
                clearance_color,
                2,
                cv2.LINE_AA,
            )
            cv2.circle(image, overtaker_point, 5, clearance_color, -1, cv2.LINE_AA)
            cv2.circle(image, overtaken_point, 5, clearance_color, -1, cv2.LINE_AA)
            clearance_label = _format_distance_label(
                _float_or_none(event.get("clearance_distance_cm")),
                _float_or_none(event.get("clearance_distance_m")),
                _float_or_none(event.get("clearance_distance_px")),
            )
            if clearance_label != "-":
                mid_x = int(round((overtaker_point[0] + overtaken_point[0]) / 2.0))
                mid_y = int(round((overtaker_point[1] + overtaken_point[1]) / 2.0)) - 8
                _draw_text(
                    image,
                    f"Clearance {clearance_label}",
                    (mid_x, mid_y),
                    clearance_color,
                    font_scale=0.55,
                    thickness=2,
                )

    summary_lines: list[str] = []
    run_id = event.get("run_id")
    frame_num = event.get("frame_num")
    video_time = _float_or_none(event.get("video_time_s"))
    summary_lines.append(f"Run {run_id} / Frame {frame_num}")
    summary_lines.append(f"Lane width {lane_width_m:.1f} m")
    if video_time is not None:
        summary_lines.append(f"Timestamp {video_time:.2f}s")
    for detail in role_details:
        label = detail.get("label") or detail.get("role") or ""
        stored_distance_cm = _float_or_none(detail.get("stored_distance_cm"))
        computed_distance_cm = _float_or_none(detail.get("distance_cm"))
        distance_cm = stored_distance_cm or computed_distance_cm
        if distance_cm is not None and label:
            summary_lines.append(f"{label}: lane distance {distance_cm:.1f}cm")
    for segment in scale_segments:
        y_val = _float_or_none(segment.get("y"))
        lane_width_px = _float_or_none(segment.get("lane_width_px"))
        cm_per_px = _float_or_none(segment.get("centimeters_per_pixel"))
        if y_val is None or lane_width_px is None:
            continue
        text = f"Y={y_val:.1f}px: {lane_width_m:.1f}m={lane_width_px:.1f}px"
        if cm_per_px is not None:
            text += f" ({cm_per_px:.2f} cm/px)"
        summary_lines.append(text)

    x0, y0 = 12, 24
    for idx, line in enumerate(summary_lines):
        if not line:
            continue
        y = y0 + idx * 22
        _draw_text(image, line, (x0, y), (255, 255, 255))

    return image
