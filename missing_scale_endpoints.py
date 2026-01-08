
@main.route("/api/manual_overtake/<int:run_id>/scale_preview")
def manual_overtake_scale_preview(run_id: int):
    frame_num = request.args.get("frame", type=int)
    overtaker_group_id = request.args.get("overtaker_group_id", type=int)
    overtaken_group_id = request.args.get("overtaken_group_id", type=int)

    if frame_num is None or overtaker_group_id is None or overtaken_group_id is None:
        return jsonify({"error": "Please provide frame number and both group IDs."}), 400

    preview_data, error_info = _collect_manual_scale_preview(
        run_id,
        frame_num,
        overtaker_group_id,
        overtaken_group_id,
    )

    if error_info is not None:
        message, status_code = error_info
        payload: dict[str, Any] = {"error": message}
        if preview_data and preview_data.get("notices"):
            payload["notices"] = preview_data["notices"]
        if preview_data and preview_data.get("actions"):
            payload["actions"] = preview_data["actions"]
        return jsonify(payload), status_code

    assert preview_data is not None  # for type checkers
    event = preview_data["event"]
    left_line = preview_data.get("left_line")
    right_line = preview_data.get("right_line")
    center_line = preview_data.get("center_line")
    left_inner_line = preview_data.get("left_inner_line")
    right_inner_line = preview_data.get("right_inner_line")
    lane_width_m = _resolve_lane_width_m(event.get("lane_width_m"))
    tire_bboxes = _collect_tire_bboxes(event)

    role_details, scale_segments = _manual_scale_analysis(
        event,
        left_line,
        right_line,
        center_line,
        left_inner_line,
        right_inner_line,
        lane_width_m=lane_width_m,
        tire_bboxes=tire_bboxes,
    )

    video_info = preview_data.get("video_info") or {}
    video_path = video_info.get("path") if isinstance(video_info, Mapping) else None
    video_available = bool(video_path and os.path.exists(video_path))

    image_url = None
    if video_available and left_line and right_line:
        image_url = url_for(
            "main.manual_overtake_scale_preview_image",
            run_id=run_id,
            frame=frame_num,
            overtaker_group_id=overtaker_group_id,
            overtaken_group_id=overtaken_group_id,
        )

    response_payload: dict[str, Any] = {
        "run_id": run_id,
        "frame_num": event.get("frame_num"),
        "video_filename": event.get("video_filename"),
        "lane_width_m": lane_width_m,
        "role_details": role_details,
        "scale_segments": scale_segments,
        "calibration_profile": preview_data.get("calibration_profile"),
        "video_available": video_available,
        "image_url": image_url,
        "left_line_available": bool(left_line),
        "right_line_available": bool(right_line),
        "event": event,
    }
    if left_inner_line:
        response_payload["left_inner_available"] = True
    if right_inner_line:
        response_payload["right_inner_available"] = True

    if preview_data.get("actions"):
        response_payload["actions"] = preview_data["actions"]
    if preview_data.get("notices"):
        response_payload["notices"] = preview_data["notices"]

    return jsonify(response_payload)


@main.route("/manual_overtake/<int:run_id>/scale_preview_image")
def manual_overtake_scale_preview_image(run_id: int):
    frame_num = request.args.get("frame", type=int)
    overtaker_group_id = request.args.get("overtaker_group_id", type=int)
    overtaken_group_id = request.args.get("overtaken_group_id", type=int)

    if frame_num is None or overtaker_group_id is None or overtaken_group_id is None:
        return Response(status=400)

    preview_data, error_info = _collect_manual_scale_preview(
        run_id,
        frame_num,
        overtaker_group_id,
        overtaken_group_id,
    )

    if error_info is not None:
        _, status_code = error_info
        return Response(status=status_code)

    assert preview_data is not None
    event = preview_data["event"]

    video_info = preview_data.get("video_info") or {}
    video_path = video_info.get("path") if isinstance(video_info, Mapping) else None
    if not video_path or not os.path.exists(video_path):
        return Response(status=404)

    left_line = preview_data.get("left_line")
    right_line = preview_data.get("right_line")
    center_line = preview_data.get("center_line")
    left_inner_line = preview_data.get("left_inner_line")
    right_inner_line = preview_data.get("right_inner_line")
    if not left_line or not right_line:
        return Response(status=404)

    requested_width = request.args.get("width", type=int)
    frame_number = event.get("frame_num")
    try:
        frame_value = int(frame_number) if frame_number is not None else frame_num
    except (TypeError, ValueError):
        frame_value = frame_num

    frame = load_video_frame(video_path, frame_value, requested_width)
    if frame is None:
        return Response(status=404)

    lane_width_m = _resolve_lane_width_m(event.get("lane_width_m"))
    tire_bboxes = _collect_tire_bboxes(event)

    role_details, scale_segments = _manual_scale_analysis(
        event,
        left_line,
        right_line,
        center_line,
        left_inner_line,
        right_inner_line,
        lane_width_m=lane_width_m,
        tire_bboxes=tire_bboxes,
    )
    annotated = _draw_scale_overlay(frame, event, role_details, scale_segments)

    ok, buffer = cv2.imencode(
        ".jpg",
        annotated,
        [int(cv2.IMWRITE_JPEG_QUALITY), 85],
    )
    if not ok:
        return Response(status=500)

    resp = Response(buffer.tobytes(), mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@main.route("/api/manual_overtake/<int:run_id>/metadata")
