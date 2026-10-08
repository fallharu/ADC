"""Render the calibrated road using exactly the speed estimator's coordinates."""

import cv2
import numpy as np

from .speed_homography import HomographyProjection, _coerce_points


def render_homography_preview(frame, payload, max_width=900, max_height=600, horizontal=False):
    if not (1 <= max_width <= 2400 and 1 <= max_height <= 2400
            and max_width * max_height <= 2_000_000):
        raise ValueError("プレビューサイズが範囲外です。")
    scale = payload.get("scale") or {}
    meta = scale.get("homography") or {}
    lines = scale.get("lines") or []
    projection = HomographyProjection(meta, payload.get("camera") or scale.get("camera"), lines)
    y_min, y_max = projection.correct_y([0, projection.length_m])
    length = float(y_max - y_min)
    if not np.isfinite(length) or length <= 0:
        raise ValueError("補正後の奥行きが不正です。")
    width = projection.width_m
    endpoints = projection.world_to_image([[width / 2, y_min], [width / 2, y_max]])
    zero_is_near = bool(endpoints[0, 1] >= endpoints[1, 1])
    if horizontal:
        out_width, out_height = max_width, max_height
    else:
        ppm = min(max_width / width, max_height / length)
        out_width = max(1, round(width * ppm))
        out_height = max(1, round(length * ppm))
    xx, yy = np.meshgrid(np.arange(out_width), np.arange(out_height))
    if horizontal:
        u = yy * width / max(out_height - 1, 1)
        distance = xx * length / max(out_width - 1, 1)
    else:
        u = xx * width / max(out_width - 1, 1)
        distance = (out_height - 1 - yy) * length / max(out_height - 1, 1)
    v = y_min + distance if zero_is_near else y_max - distance
    pixels = projection.world_to_image(np.column_stack([u.ravel(), v.ravel()]))
    pixels[~np.isfinite(pixels)] = -1
    rendered = cv2.remap(
        frame, pixels[:, 0].reshape(u.shape).astype(np.float32),
        pixels[:, 1].reshape(u.shape).astype(np.float32), cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
    )
    midpoints = []
    for line in lines:
        points = _coerce_points(line)
        if len(points) >= 2:
            midpoints.append(np.mean(points, axis=0))
    stations = []
    if midpoints:
        positions = projection.image_to_world(midpoints)[:, 1]
        distances = positions - y_min if zero_is_near else y_max - positions
        stations = sorted(float(d) for d in distances if np.isfinite(d) and -1e-5 <= d <= length + 1e-5)
    return rendered, {
        "width_m": width, "length_m": length,
        "y_min_m": float(y_min), "y_max_m": float(y_max),
        "zero_is_near": zero_is_near, "stations_m": stations,
        "lens_corrected": projection.camera_matrix is not None,
        "longitudinal_corrected": projection.raw_positions is not None,
    }
