def manual_overtake_metadata(run_id: int):
    upload_folder = current_app.config['UPLOAD_FOLDER']
    info = get_run_video_info(run_id, upload_folder)
    if not info:
        return jsonify({"error": "対象のRunが見つかりません。"}), 404
    video_path = info.get('path')
    if not video_path or not os.path.exists(video_path):
        return jsonify({"error": "動画ファイルが見つかりません。"}), 404
    try:
        stats = probe_video(video_path)
    except FileNotFoundError:
        return jsonify({"error": "動画ファイルが見つかりません。"}), 404
    except Exception:
        return jsonify({"error": "動画を読み込めませんでした。"}), 500

    manual_frame_buffer.prepare_video(
        run_id,
        video_path,
        stats.get('frame_count'),
        stats.get('width'),
        stats.get('height'),
        start_prefetch=False,
    )

    try:
        touch_manual_run_progress(run_id, visit=True)
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to update manual run visit timestamp")

    calibration = load_calibration_payload(run_id, info.get('profile_name'))
    lane_lines = load_white_lines(calibration)
    left_line, right_line, center_line = lane_lines
    left_inner_line = lane_lines.left_inner
    right_inner_line = lane_lines.right_inner

    detection_offset = get_detection_frame_offset(run_id)
    first_detection_frame = get_first_detection_frame(run_id)
    first_bicycle_frame = get_first_bicycle_detection_frame(run_id)
    bicycle_orientation_counts = get_bicycle_orientation_counts(run_id)
    bicycle_aliases = sorted(get_bicycle_class_aliases())
    buffer_status = manual_frame_buffer.get_status(run_id) or {}

    return jsonify({
        "run_id": run_id,
        "video_filename": info.get('filename'),
        "frame_count": stats.get('frame_count'),
        "width": stats.get('width'),
        "height": stats.get('height'),
        "fps": info.get('fps'),
        "left_white_line": left_line,
        "right_white_line": right_line,
        "left_inner_line": left_inner_line,
        "right_inner_line": right_inner_line,
        "detection_frame_offset": detection_offset,
        "first_detection_frame": first_detection_frame,
        "first_bicycle_frame": first_bicycle_frame,
        "bicycle_orientation_counts": bicycle_orientation_counts,
        "bicycle_class_aliases": bicycle_aliases,
        "buffer_status": buffer_status,
    })


@main.route("/api/manual_overtake/<int:run_id>/prefetch", methods=["GET", "POST"])
def manual_overtake_prefetch(run_id: int):
    upload_folder = current_app.config['UPLOAD_FOLDER']
    info = get_run_video_info(run_id, upload_folder)
    if not info:
        return jsonify({"error": "対象のRunが見つかりません。"}), 404

    video_path = info.get('path')
    if not video_path or not os.path.exists(video_path):
        return jsonify({"error": "動画ファイルが見つかりません。"}), 404

    try:
        stats = probe_video(video_path)
    except FileNotFoundError:
        return jsonify({"error": "動画ファイルが見つかりません。"}), 404
    except Exception:
        current_app.logger.exception("Failed to open video for manual prefetch")
        return jsonify({"error": "動画を読み込めませんでした。"}), 500

    manual_frame_buffer.prepare_video(
        run_id,
        video_path,
        stats.get('frame_count'),
        stats.get('width'),
        stats.get('height'),
        restart=request.method == "POST",
        start_prefetch=request.method == "POST",
    )

    status = manual_frame_buffer.get_status(run_id) or {}
    status.update(
        {
            "run_id": run_id,
            "frame_count": stats.get('frame_count'),
            "width": stats.get('width'),
            "height": stats.get('height'),
        }
    )

    if request.method == "POST":
        return jsonify({"status": "started", "buffer_status": status})

    return jsonify(status)


@main.route("/api/manual_overtake/<int:run_id>/frame")
def manual_overtake_frame(run_id: int):
    upload_folder = current_app.config['UPLOAD_FOLDER']
    info = get_run_video_info(run_id, upload_folder)
    if not info:
        return Response(status=404)
    video_path = info.get('path')
    if not video_path or not os.path.exists(video_path):
        return Response(status=404)

    frame_idx = request.args.get('frame', default=0, type=int)
    requested_width = request.args.get('width', type=int)
    frame_bytes = manual_frame_buffer.get_frame(
        run_id,
        video_path,
        frame_idx,
        requested_width,
    )
    if frame_bytes is None:
        return Response(status=404)
    response = Response(frame_bytes, mimetype='image/jpeg')
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response


@main.route("/api/manual_overtake/<int:run_id>/detections")
def manual_overtake_detections(run_id: int):
    frame_num = request.args.get('frame', type=int)
    if frame_num is None or frame_num < 0:
        return jsonify({"error": "frameパラメータを正しく指定してください。"}), 400
    detection_frame = convert_video_frame_to_detection_frame(run_id, frame_num)
    if detection_frame is None:
        detections: list[dict[str, Any]] = []
    else:
        detections = fetch_detections_for_frame(run_id, detection_frame)

    def _maybe_attach_tire_measurement() -> None:
        if not detections:
            return

        upload_folder = current_app.config.get("UPLOAD_FOLDER")
        run_info = get_run_video_info(run_id, upload_folder)
        calibration = load_calibration_payload(run_id, run_info.get("profile_name") if run_info else None)
        lane_lines = load_white_lines(calibration)
        left_line, right_line, _ = lane_lines
        bicycle_aliases = {alias.lower() for alias in get_bicycle_class_aliases()}

        def _normalize_group(value: object) -> Optional[int]:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        def _is_bicycle(det: Mapping[str, Any]) -> bool:
            class_name = det.get("class_name") if isinstance(det, Mapping) else None
            return isinstance(class_name, str) and class_name.lower() in bicycle_aliases

        def _is_plate(det: Mapping[str, Any]) -> bool:
            try:
                class_name = str(det.get("class_name") or "").lower()
            except AttributeError:
                return False
            return "plate" in class_name or "ナンバー" in class_name

        for det in detections:
            if not isinstance(det, dict):
                continue
            group_value = _normalize_group(det.get("group_id"))
            if group_value is None:
                continue

            candidates = [
                det for det in fetch_tire_detections_for_group(run_id, detection_frame, group_value)
                if not _is_plate(det)
            ]
            bbox_source: Mapping[str, Any] = det

            if _is_bicycle(det):
                best_bbox = fetch_best_group_bbox(run_id, detection_frame, group_value)
                if best_bbox:
                    bbox_source = {**bbox_source, **best_bbox}
                measure_x, measure_y = select_bicycle_tire_measure_point(
                    bbox_source,
                    candidates,
                    left_line,
                    right_line,
                )
            else:
                measure_x, measure_y = select_measure_point_from_candidates(
                    candidates,
                    left_line,
                    right_line,
                )

            if None in (measure_x, measure_y):
                continue

            det["tire_measure_x"] = float(measure_x)
            det["tire_measure_y"] = float(measure_y)

    try:
        _maybe_attach_tire_measurement()
    except Exception:
        current_app.logger.exception("Failed to attach tire measure points for manual overtake detections")

    offset = get_detection_frame_offset(run_id)
    if detections and offset:
        for det in detections:
            stored_frame = det.get('frame_num')
            det['frame_num'] = convert_detection_frame_to_video_frame(run_id, stored_frame)
    return jsonify(
        {
            "detections": detections,
            "frame_num": frame_num,
            "detection_frame": detection_frame,
            "detection_frame_offset": offset,
        }
    )


@main.route("/api/manual_overtake/<int:run_id>/group_seek")
def manual_overtake_group_seek(run_id: int):
    group_id = request.args.get('group_id', type=int)
    if group_id is None:
        return jsonify({"error": "group_idパラメータを指定してください。"}), 400

    current_frame = request.args.get('frame', type=int)

    first_frame = get_first_detection_frame_for_group(run_id, group_id)
    if first_frame is None:
        return jsonify({"error": "指定グループの検出が見つかりません。"}), 404

    next_frame = get_next_detection_frame_for_group(run_id, group_id, current_frame)

    return jsonify(
        {
            "run_id": run_id,
            "group_id": group_id,
            "requested_frame": current_frame,
            "first_frame": first_frame,
            "next_frame": next_frame,
            "has_next": next_frame is not None,
        }
    )


def _await_manual_overtake_event(
    event_id: int,
    *,
    timeout: float = 1.0,
    interval: float = 0.1,
) -> Optional[dict[str, Any]]:
    """指定した手動追い越しイベントがDBで確認できるまで待機する。"""

    deadline = time.monotonic() + max(timeout, 0.0)
    wait_interval = max(interval, 0.01)

    while True:
        event = fetch_manual_overtake_event(event_id, vehicle_only=False)
        if event:
            return event
        event = fetch_manual_overtake_event(
            event_id,
            vehicle_only=False,
            use_cache=False,
            refresh_cache=True,
        )
        if event:
            return event
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(wait_interval, remaining))


@main.route("/api/manual_overtake/<int:run_id>/events/verify", methods=["GET"])
def manual_overtake_event_verify(run_id: int):
    event_id = request.args.get("event_id", type=int)
    if event_id is None:
        return jsonify({"error": "イベントIDを指定してください。"}), 400
    if event_id <= 0:
        return jsonify({"error": "イベントIDが不正です。"}), 400

    try:
        event = _await_manual_overtake_event(event_id)
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to verify manual overtake event")
        return jsonify({"error": f"イベントの確認に失敗しました: {exc}"}), 500

    if not event:
        return (
            jsonify(
                {
                    "verified": False,
                    "error": "イベントの保存を1秒以内に確認できませんでした。",
                }
            ),
            404,
        )

    event_run_id_raw = event.get("run_id")
    if event_run_id_raw is not None:
        try:
            event_run_id = int(event_run_id_raw)
        except (TypeError, ValueError):
            event_run_id = None
    else:
        event_run_id = None

    if event_run_id is not None and event_run_id != run_id:
        return jsonify({
            "verified": False,
            "error": "指定したRunに一致するイベントではありません。",
        }), 404

    _apply_manual_distance_ratios(event)

    return jsonify({
        "verified": True,
        "event": event,
        "message": "イベントの保存を確認しました。",
    })


@main.route("/api/manual_overtake/db_link_check", methods=["GET"])
def manual_overtake_db_link_check():
    """手動追い越しテーブルとDBの連携状況を確認し、登録済みデータを返す。"""

    raw_run_ids = request.args.getlist("run_id")
    normalized_run_ids: list[int] = []
    for raw in raw_run_ids:
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            normalized_run_ids.append(value)

    requested_limit = request.args.get("limit", type=int)
    if requested_limit is None or requested_limit <= 0:
        requested_limit = 5
    sample_limit = min(max(requested_limit, 1), 20)

    try:
        with sqlite3.connect(MAIN_DB_PATH) as conn:
            ensure_manual_annotation_schema(conn)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ManualOvertakeEvents'"
            )
            table_exists = cursor.fetchone() is not None
            if not table_exists:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "linked": False,
                            "error": "ManualOvertakeEventsテーブルが見つかりません。",
                        }
                    ),
                    404,
                )

            total_count = 0
            run_summaries: list[dict[str, Any]] = []

            if normalized_run_ids:
                for run_id in normalized_run_ids:
                    cursor.execute(
                        "SELECT COUNT(*) AS count FROM ManualOvertakeEvents WHERE run_id = ?",
                        (run_id,),
                    )
                    row = cursor.fetchone()
                    event_count = int(row["count"]) if row and row["count"] is not None else 0
                    total_count += event_count
                    cursor.execute(
                        """
                        SELECT manual_event_id,
                               run_id,
                               frame_num,
                               overtaker_group_id,
                               overtaken_group_id,
                               created_at
                        FROM ManualOvertakeEvents
                        WHERE run_id = ?
                        ORDER BY created_at DESC, manual_event_id DESC
                        LIMIT ?
                        """,
                        (run_id, sample_limit),
                    )
                    sample_rows = cursor.fetchall()
                    samples = [
                        {
                            "manual_event_id": sample["manual_event_id"],
                            "run_id": sample["run_id"],
                            "frame_num": sample["frame_num"],
                            "overtaker_group_id": sample["overtaker_group_id"],
                            "overtaken_group_id": sample["overtaken_group_id"],
                            "created_at": sample["created_at"],
                        }
                        for sample in sample_rows
                    ]
                    run_summaries.append(
                        {
                            "run_id": run_id,
                            "event_count": event_count,
                            "samples": samples,
                        }
                    )
            else:
                cursor.execute("SELECT COUNT(*) AS count FROM ManualOvertakeEvents")
                total_row = cursor.fetchone()
                total_count = (
                    int(total_row["count"])
                    if total_row and total_row["count"] is not None
                    else 0
                )

                cursor.execute(
                    """
                    SELECT run_id, COUNT(*) AS count
                    FROM ManualOvertakeEvents
                    GROUP BY run_id
                    ORDER BY run_id ASC
                    """
                )
                summary_rows = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT manual_event_id,
                           run_id,
                           frame_num,
                           overtaker_group_id,
                           overtaken_group_id,
                           created_at
                    FROM ManualOvertakeEvents
                    ORDER BY created_at DESC, manual_event_id DESC
                    LIMIT ?
                    """,
                    (sample_limit,),
                )
                sample_rows = cursor.fetchall()
                sample_map: dict[int, list[dict[str, Any]]] = {}
                for sample in sample_rows:
                    run_id = sample["run_id"]
                    sample_map.setdefault(run_id, []).append(
                        {
                            "manual_event_id": sample["manual_event_id"],
                            "run_id": run_id,
                            "frame_num": sample["frame_num"],
                            "overtaker_group_id": sample["overtaker_group_id"],
                            "overtaken_group_id": sample["overtaken_group_id"],
                            "created_at": sample["created_at"],
                        }
                    )

                for row in summary_rows:
                    rid = row["run_id"]
                    count_value = int(row["count"]) if row and row["count"] is not None else 0
                    run_summaries.append(
                        {
                            "run_id": rid,
                            "event_count": count_value,
                            "samples": sample_map.get(rid, []),
                        }
                    )

        if normalized_run_ids:
            if total_count > 0:
                message = "選択したRunの手動追い越しテーブルとの連携を確認しました。"
            else:
                message = "選択Runには登録済みの手動追い越しイベントが見つかりませんでした。"
        else:
            if total_count > 0:
                message = "手動追い越しテーブルとの連携を確認しました。"
            else:
                message = "手動追い越しテーブルは存在しますが、登録済みイベントはありません。"

        return jsonify(
            {
                "ok": True,
                "linked": True,
                "total_events": total_count,
                "run_summaries": run_summaries,
                "message": message,
            }
        )
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to verify manual overtake DB link")
        return (
            jsonify(
                {
                    "ok": False,
                    "linked": False,
                    "error": f"DB連携確認に失敗しました: {exc}",
                }
            ),
            500,
        )


@main.route("/api/manual_overtake/<int:run_id>/events/status", methods=["GET"])
def manual_overtake_events_status(run_id: int):
    try:
        summary = summarize_manual_overtake_events(run_id)
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to summarize manual overtake events")
        return jsonify({"error": str(exc)}), 500

    latest_event = summary.get("latest_event")
    if isinstance(latest_event, dict):
        _prepare_manual_events([latest_event])

    return jsonify(summary)


def manual_overtake_calibration_recreate(
    run_id: int, *, payload: Optional[Mapping[str, Any]] = None
):
    """手動追い越し用にキャリブレーションを複製し、Runへ適用する。"""

    body = payload or request.get_json(silent=True) or {}
    profile_raw = body.get("profile_name") if isinstance(body, Mapping) else None
    profile_candidate = sanitize_profile_name(profile_raw or "")
    upload_folder = current_app.config.get("UPLOAD_FOLDER")
    run_info = get_run_video_info(run_id, upload_folder)
    if not run_info:
        return jsonify({"error": "対象のRunが見つかりません。"}), 404

    base_profile = sanitize_profile_name(run_info.get("profile_name") or "")
    calibration_payload = load_calibration_payload(run_id, base_profile) or {}

    if not profile_candidate:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        profile_candidate = sanitize_profile_name(f"manual_run_{run_id}_{timestamp}")

    calib_dir = ensure_calibration_dir()
    try:
        save_calibration_payload(profile_candidate, run_id, calibration_payload, calib_dir)
        update_run_calibration_profile(run_id, profile_candidate)
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to create manual calibration profile")
        return jsonify({"error": f"キャリブレーション保存に失敗しました: {exc}"}), 500

    enqueued = 0
    try:
        enqueued, _ = ensure_manual_context_backlog_for_runs(
            [run_id], force_requeue=True
        )
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to requeue manual contexts after calibration")

    return jsonify(
        {
            "run_id": run_id,
            "profile_name": profile_candidate,
            "calibration_url": url_for(
                "main.calibration_page", run_id=run_id, profile_name=profile_candidate
            ),
            "enqueued": enqueued,
            "message": "新しいキャリブレーションを作成し、手動追い越しの再処理を予約しました。",
        }
    )


@main.route("/api/manual_overtake/<int:run_id>/events", methods=["GET", "POST"])
def manual_overtake_events_api(run_id: int):
    if request.method == "GET":
        limit = request.args.get('limit', type=int)
        try:
            events = list_manual_overtake_events(run_id=run_id, limit=limit)
            _prepare_manual_events(events)
        except Exception as exc:  # pragma: no cover - runtime safeguard
            current_app.logger.exception("Failed to fetch manual overtake events")
            return jsonify({"error": str(exc)}), 500
        return jsonify({"events": events})

    if request.args.get("calibration") == "recreate":
        payload = request.get_json(silent=True) or {}
        return manual_overtake_calibration_recreate(run_id, payload=payload)

    payload = request.get_json(silent=True) or {}
    frame_num_raw = payload.get('frame_num') if 'frame_num' in payload else payload.get('frame')
    overtaker_group_raw = payload.get('overtaker_group_id') if 'overtaker_group_id' in payload else payload.get('overtaker')
    overtaken_group_raw = payload.get('overtaken_group_id') if 'overtaken_group_id' in payload else payload.get('overtaken')
    notes_raw = payload.get('notes')
    lane_width_raw = payload.get('lane_width_m')

    try:
        frame_num = int(frame_num_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "フレーム番号が不正です。"}), 400
    try:
        overtaker_group_id = int(overtaker_group_raw)
        overtaken_group_id = int(overtaken_group_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "Group ID が不正です。"}), 400

    if frame_num < 0:
        return jsonify({"error": "フレーム番号は0以上にしてください。"}), 400
    if overtaker_group_id == overtaken_group_id:
        return jsonify({"error": "追い越し側と追い越され側は別のグループを選択してください。"}), 400

    notices: list[str] = []

    sanitized_notes = (notes_raw or "").strip()
    if sanitized_notes and len(sanitized_notes) > 500:
        sanitized_notes = sanitized_notes[:500]

    event_payload = {
        "run_id": run_id,
        "frame_num": frame_num,
        "overtaker_group_id": overtaker_group_id,
        "overtaken_group_id": overtaken_group_id,
        "notes": sanitized_notes or None,
    }

    try:
        lane_width_value = float(lane_width_raw)
    except (TypeError, ValueError):
        lane_width_value = None
    if lane_width_value is not None and lane_width_value > 0:
        event_payload["lane_width_m"] = lane_width_value

    try:
        event_id = insert_manual_overtake_event(event_payload)
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to insert manual overtake event")
        return jsonify({"error": f"保存に失敗しました: {exc}"}), 500

    database_verified = False
    saved_event: dict[str, Any] | None = None
    try:
        saved_event = fetch_manual_overtake_event_core(event_id)
        if saved_event:
            database_verified = True
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to verify manual overtake event in DB")
        notices.append(f"保存確認に失敗しました: {exc}")

    if not saved_event:
        saved_event = {
            "manual_event_id": event_id,
            "run_id": run_id,
            "frame_num": frame_num,
            "overtaker_group_id": overtaker_group_id,
            "overtaken_group_id": overtaken_group_id,
            "notes": event_payload.get("notes"),
        }

    context_saved = False
    context_notices: list[str] = []
    context_enqueued = False
    try:
        enqueue_manual_context_backlog(
            event_id,
            run_id,
            frame_num,
            event_payload,
            [],
        )
        context_enqueued = True
        context_notices.append(
            "追い越しフレームを後処理キューに登録しました。手動追い越し観覧で後処理を実行してください。"
        )
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to enqueue manual context backlog")
        context_notices.append(f"追い越しフレームの後処理キュー登録に失敗しました: {exc}")

    notices.extend(context_notices)

    try:
        record_manual_overtake_timeline_entry(
            run_id,
            frame_num,
            overtaker_group_id,
            overtaken_group_id,
            notes=event_payload.get("notes"),
            last_event_id=None,
        )
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to record manual overtake timeline entry")
        notices.append(f"タイムラインの更新に失敗しました: {exc}")

    response_payload: dict[str, object] = {
        "event_id": event_id,
        "event": saved_event,
        "database_verified": database_verified,
        "context_saved": context_saved,
        "context_queued": context_enqueued,
    }

    remaining_notices = [msg for msg in notices if msg]
    if remaining_notices:
        response_payload["notices"] = remaining_notices

    return jsonify(response_payload), 201


@main.route("/api/manual_overtake/<int:run_id>/context/flush", methods=["POST"])
def manual_overtake_context_flush(run_id: int):
    ensure_notices: list[str] = []
    enqueued = 0
    enqueued_ids: list[int] = []
    try:
        enqueued, enqueued_ids = ensure_manual_context_backlog_for_runs(
            [run_id], force_requeue=True
        )
    except Exception as exc:  # pragma: no cover - runtime safeguard
        current_app.logger.exception("Failed to enqueue manual context backlog before flush")
        ensure_notices.append(f"追い越しフレーム後処理対象の確認に失敗しました: {exc}")
    else:
        if enqueued:
            ensure_notices.append(
                f"追い越しフレーム後処理キューに {enqueued} 件を追加しました。"
