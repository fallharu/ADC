def _collect_tire_bboxes(event: Mapping[str, Any]) -> dict[str, list[tuple[int, int, int, int]]]:
    run_id = event.get("run_id")
    frame_num = event.get("frame_num")
    try:
        frame_value = int(frame_num) if frame_num is not None else None
    except (TypeError, ValueError):
        frame_value = None

    if run_id is None or frame_value is None:
        return {}

    bboxes: dict[str, list[tuple[int, int, int, int]]] = {}
    for prefix, key in (("overtaker", "overtaker_group_id"), ("overtaken", "overtaken_group_id")):
        try:
            group_value = int(event.get(key))
        except (TypeError, ValueError):
            continue
        candidates = fetch_tire_detections_for_group(run_id, frame_value, group_value)
        boxes: list[tuple[int, int, int, int]] = []
        for det in candidates:
            if not isinstance(det, Mapping):
                continue
            bbox = _bbox_from_mapping(det)
            if bbox:
                boxes.append(bbox)
        if boxes:
            bboxes[prefix] = boxes
    return bboxes


def _manual_scale_analysis(
    event: Mapping[str, Any],
    left_line: Optional[Sequence[Sequence[object]]],
    right_line: Optional[Sequence[Sequence[object]]],
    center_line: Optional[Sequence[Sequence[object]]],
    left_inner_line: Optional[Sequence[Sequence[object]]] = None,
    right_inner_line: Optional[Sequence[Sequence[object]]] = None,
    *,
    lane_width_m: float = LANE_WIDTH_METERS,
    tire_bboxes: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    role_defs = (
        ("overtaker", "Overtaking"),
        ("overtaken", "Overtaken"),
    )
    role_details: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    seen_y: set[float] = set()

    for prefix, label in role_defs:
        detection = _manual_event_detection_from_prefix(event, prefix)
        lane_result = compute_lane_distance(
            detection,
            left_line,
            right_line,
            center_line,
            left_inner_line,
            right_inner_line,
            lane_width_m=lane_width_m,
        )
        lane_scale = lane_scale_details_at_y(
            lane_result.measure_y,
            left_line,
            right_line,
            center_line=center_line,
            left_inner_line=left_inner_line,
            right_inner_line=right_inner_line,
            lane_width_m=lane_width_m,
        )
        lane_scale_dict = lane_scale.to_dict()

        stored_px = _float_or_none(event.get(f"{prefix}_line_distance_px"))
        stored_m = _float_or_none(event.get(f"{prefix}_line_distance_m"))
        stored_cm = _float_or_none(event.get(f"{prefix}_line_distance_cm"))

        detail_entry: dict[str, Any] = {
            "role": prefix,
            "label": label,
            "measure_x": _float_or_none(lane_result.measure_x),
            "measure_y": _float_or_none(lane_result.measure_y),
            "distance_px": _float_or_none(lane_result.distance_px),
            "distance_m": _float_or_none(lane_result.distance_m),
            "distance_cm": _float_or_none(
                lane_result.distance_m * 100.0
                if lane_result.distance_m is not None
                else None
            ),
            "stored_distance_px": stored_px,
            "stored_distance_m": stored_m,
            "stored_distance_cm": stored_cm,
            "left_distance_px": _float_or_none(lane_result.left_distance_px),
            "left_distance_m": _float_or_none(lane_result.left_distance_m),
            "left_distance_cm": _float_or_none(
                lane_result.left_distance_m * 100.0
                if lane_result.left_distance_m is not None
                else None
            ),
            "right_distance_px": _float_or_none(lane_result.right_distance_px),
            "right_distance_m": _float_or_none(lane_result.right_distance_m),
            "right_distance_cm": _float_or_none(
                lane_result.right_distance_m * 100.0
                if lane_result.right_distance_m is not None
                else None
            ),
            "stored_left_distance_px": _float_or_none(
                event.get(f"{prefix}_left_line_distance_px")
            ),
            "stored_left_distance_cm": _float_or_none(
                event.get(f"{prefix}_left_line_distance_cm")
            ),
            "stored_right_distance_px": _float_or_none(
                event.get(f"{prefix}_right_line_distance_px")
            ),
            "stored_right_distance_cm": _float_or_none(
                event.get(f"{prefix}_right_line_distance_cm")
            ),
            "lane_scale": lane_scale_dict,
        }
        bbox = _bbox_from_mapping(detection)
        if bbox:
            detail_entry["bbox"] = bbox
        if tire_bboxes:
            boxes_for_role: list[tuple[int, int, int, int]] = []
            for det in tire_bboxes.get(prefix, ()):  # type: ignore[arg-type]
                if not isinstance(det, Mapping):
                    continue
                box = _bbox_from_mapping(det)
                if box:
                    boxes_for_role.append(box)
            if boxes_for_role:
                detail_entry["tire_bboxes"] = boxes_for_role
        role_details.append(detail_entry)

        if lane_scale.is_available and lane_scale.y is not None:
            key = round(lane_scale.y, 3)
            if key not in seen_y:
                seen_y.add(key)
                segments.append(
                    {
                        "y": lane_scale_dict.get("y"),
                        "lane_width_px": lane_scale_dict.get("lane_width_px"),
                        "pixels_per_meter": lane_scale_dict.get("pixels_per_meter"),
                        "centimeters_per_pixel": lane_scale_dict.get(
                            "centimeters_per_pixel"
                        ),
                        "left_point": lane_scale_dict.get("left_point"),
                        "right_point": lane_scale_dict.get("right_point"),
                    }
                )

    return role_details, segments


def _collect_manual_scale_preview(
    run_id: int,
    frame_num: int,
    overtaker_group_id: int,
    overtaken_group_id: int,
) -> tuple[Optional[dict[str, Any]], Optional[tuple[str, int]]]:
    """手動追い越しのスケール確認に必要な情報を取得する。"""

    actions_taken, notices, fatal = _prepare_manual_overtake_dependencies(run_id)
    combined_notices = list(notices)
    if fatal:
        message = combined_notices[-1] if combined_notices else "手動追い越しに必要な検出が不足しています。"
        return (
            {
                "actions": actions_taken,
                "notices": combined_notices,
            },
            (message, 400),
        )

