import os
import sqlite3
import tempfile
import types
import unittest
from typing import Optional
from unittest import mock

import sys

if "dotenv" not in sys.modules:
    dotenv_stub = types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None)
    sys.modules["dotenv"] = dotenv_stub

if "cv2" not in sys.modules:
    cv2_stub = types.ModuleType("cv2")
    cv2_stub.IMWRITE_JPEG_QUALITY = 95
    cv2_stub.IMREAD_COLOR = 1
    cv2_stub.LINE_AA = 16
    cv2_stub.FONT_HERSHEY_SIMPLEX = 0
    cv2_stub.MARKER_CROSS = 0

    def _cv2_imencode(*args, **kwargs):  # pragma: no cover - simple stub
        return True, b""

    def _cv2_noop(*args, **kwargs):  # pragma: no cover - simple stub
        return None

    cv2_stub.imencode = _cv2_imencode
    cv2_stub.imread = lambda *args, **kwargs: None
    cv2_stub.imshow = _cv2_noop
    cv2_stub.imwrite = _cv2_noop
    cv2_stub.putText = _cv2_noop
    cv2_stub.line = _cv2_noop
    cv2_stub.circle = _cv2_noop
    cv2_stub.drawMarker = _cv2_noop
    sys.modules["cv2"] = cv2_stub

if "ultralytics" not in sys.modules:
    ultralytics_stub = types.ModuleType("ultralytics")

    class _YOLOStub:  # pragma: no cover - only used to avoid optional import
        def __init__(self, *args, **kwargs):
            pass

    ultralytics_stub.YOLO = _YOLOStub
    sys.modules["ultralytics"] = ultralytics_stub

from Source_code.modules import db_manager
from Source_code.modules.manual_metrics import (
    LaneLineSet,
    restrict_lane_lines_vertical,
)


class ManualOvertakeVerifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(delete=False)
        self.tmp_db.close()
        self.original_path = db_manager.MAIN_DB_PATH
        db_manager.MAIN_DB_PATH = self.tmp_db.name
        with sqlite3.connect(db_manager.MAIN_DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("CREATE TABLE ProcessLog (run_id INTEGER PRIMARY KEY, calibration_profile TEXT)")
            conn.execute("INSERT INTO ProcessLog (run_id, calibration_profile) VALUES (1, '')")
            db_manager.ensure_manual_annotation_schema(conn)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO ManualOvertakeEvents (run_id, frame_num, overtaker_group_id, overtaken_group_id, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (1, 120, 10, 20, "2025-01-01T00:00:00"),
            )
            self.manual_event_id = cursor.lastrowid
            conn.commit()

        try:
            from Source_code.app import app
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            if exc.name == "flask":
                self.skipTest("Flask がインストールされていないため検証APIをテストできません。")
            raise

        self.app = app
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def tearDown(self):
        db_manager.MAIN_DB_PATH = self.original_path
        try:
            os.unlink(self.tmp_db.name)
        except FileNotFoundError:
            pass

    def test_verify_endpoint_returns_event(self):
        response = self.client.get(
            f"/api/manual_overtake/1/events/verify?event_id={self.manual_event_id}"
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        self.assertTrue(payload.get("verified"))
        event = payload.get("event")
        self.assertIsInstance(event, dict)
        self.assertEqual(int(event.get("manual_event_id")), self.manual_event_id)
        self.assertEqual(int(event.get("run_id")), 1)

    def test_verify_endpoint_with_wrong_run_returns_404(self):
        response = self.client.get(
            f"/api/manual_overtake/99/events/verify?event_id={self.manual_event_id}"
        )
        self.assertEqual(response.status_code, 404)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        self.assertFalse(payload.get("verified", True))

    def test_verify_endpoint_requires_event_id(self):
        response = self.client.get("/api/manual_overtake/1/events/verify")
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertIn("error", payload)

    def test_verify_endpoint_waits_for_event_confirmation(self):
        call_counter = {"count": 0}

        def fake_fetch(event_id, *args, **kwargs):
            call_counter["count"] += 1
            if call_counter["count"] < 3:
                return None
            return {
                "manual_event_id": self.manual_event_id,
                "run_id": 1,
            }

        with mock.patch("Source_code.routes.fetch_manual_overtake_event", side_effect=fake_fetch):
            response = self.client.get(
                f"/api/manual_overtake/1/events/verify?event_id={self.manual_event_id}"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload.get("verified"))
        self.assertGreaterEqual(call_counter["count"], 3)

    def test_verify_endpoint_accepts_unrecognized_vehicle_classes(self):
        with sqlite3.connect(db_manager.MAIN_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO ManualOvertakeEvents (
                    run_id,
                    frame_num,
                    overtaker_group_id,
                    overtaken_group_id,
                    overtaker_class_name,
                    overtaken_class_name,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    150,
                    30,
                    40,
                    "rider",
                    "kick_scooter",
                    "2025-01-02T00:00:00",
                ),
            )
            special_event_id = cursor.lastrowid
            conn.commit()

        try:
            response = self.client.get(
                f"/api/manual_overtake/1/events/verify?event_id={special_event_id}"
            )
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertIsInstance(payload, dict)
            self.assertTrue(payload.get("verified"))
            event = payload.get("event")
            self.assertIsInstance(event, dict)
            self.assertEqual(int(event.get("manual_event_id")), special_event_id)
        finally:
            with sqlite3.connect(db_manager.MAIN_DB_PATH) as conn:
                conn.execute(
                    "DELETE FROM ManualOvertakeEvents WHERE manual_event_id = ?",
                    (special_event_id,),
                )
                conn.commit()

    def test_events_status_endpoint_reports_database_state(self):
        response = self.client.get("/api/manual_overtake/1/events/status")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload.get("run_id"), 1)
        self.assertEqual(payload.get("event_count"), 1)
        self.assertEqual(int(payload.get("latest_event_id")), self.manual_event_id)
        self.assertIn("snapshot_taken_at", payload)
        latest_event = payload.get("latest_event")
        self.assertIsInstance(latest_event, dict)
        self.assertEqual(int(latest_event.get("manual_event_id")), self.manual_event_id)

    def test_events_status_endpoint_handles_empty_run(self):
        response = self.client.get("/api/manual_overtake/99/events/status")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload.get("run_id"), 99)
        self.assertEqual(payload.get("event_count"), 0)
        self.assertIsNone(payload.get("latest_event_id"))
        self.assertIsNone(payload.get("latest_event"))

    def test_context_storage_limits_offset_window(self):
        frames = [
            {
                "offset_frames": -200,
                "frame_num": 10,
                "overtaker_group_id": 10,
                "overtaken_group_id": 20,
            },
            {
                "offset_frames": -150,
                "frame_num": 11,
                "overtaker_group_id": 10,
                "overtaken_group_id": 20,
            },
            {
                "offset_frames": 0,
                "frame_num": 12,
                "overtaker_group_id": 10,
                "overtaken_group_id": 20,
            },
            {
                "offset_frames": 150,
                "frame_num": 13,
                "overtaker_group_id": 10,
                "overtaken_group_id": 20,
            },
            {
                "offset_frames": 200,
                "frame_num": 14,
                "overtaker_group_id": 10,
                "overtaken_group_id": 20,
            },
        ]

        db_manager.replace_manual_overtake_context_frames(self.manual_event_id, frames)
        context_map = db_manager.fetch_manual_overtake_context_frames(
            [self.manual_event_id]
        )
        stored = context_map.get(self.manual_event_id, [])
        offsets = [row.get("offset_frames") for row in stored]
        self.assertIn(-150, offsets)
        self.assertIn(0, offsets)
        self.assertIn(150, offsets)
        self.assertNotIn(-200, offsets)
        self.assertNotIn(200, offsets)

    def test_restrict_lane_lines_vertical_limits_band(self):
        lane_lines = LaneLineSet(
            left=[[0, 0], [0, 400]],
            right=[[100, 0], [100, 400]],
            center=[[50, 0], [50, 400]],
        )
        trimmed = restrict_lane_lines_vertical(lane_lines, 70, 130)
        for line in (trimmed.left, trimmed.right, trimmed.center):
            if not line:
                continue
            self.assertGreaterEqual(len(line), 2)
            for _, y_val in line:
                self.assertGreaterEqual(y_val, 70)
                self.assertLessEqual(y_val, 130)

    @mock.patch("Source_code.routes.touch_manual_run_progress")
    @mock.patch("Source_code.routes.apply_manual_overtake_flags", return_value=True)
    @mock.patch("Source_code.routes.mark_manual_overtake_timeline_processed")
    @mock.patch("Source_code.routes.record_manual_overtake_timeline_entry", return_value=None)
    @mock.patch("Source_code.routes.enqueue_manual_context_backlog")
    @mock.patch("Source_code.routes._compute_manual_overtake_event_data")
    @mock.patch("Source_code.routes._prepare_manual_overtake_dependencies")
    def test_save_endpoint_returns_db_summary(
        self,
        mock_prepare,
        mock_compute,
        mock_enqueue,
        mock_record,
        mock_mark,
        mock_apply_flags,
        mock_touch,
    ):
        mock_prepare.return_value = ([], [], False)
        payload = {
            "run_id": 1,
            "frame_num": 200,
            "video_time_s": 8.0,
            "overtaker_group_id": 3,
            "overtaken_group_id": 4,
            "notes": "test",
        }
        computation = types.SimpleNamespace(
            payload=dict(payload),
            context_frames=[],
            detection_frame_num=payload["frame_num"],
            notices=[],
        )
        mock_compute.return_value = computation
        mock_enqueue.return_value = 1

        response = self.client.post(
            "/api/manual_overtake/1/events",
            json={
                "frame_num": payload["frame_num"],
                "overtaker_group_id": payload["overtaker_group_id"],
                "overtaken_group_id": payload["overtaken_group_id"],
                "notes": payload["notes"],
            },
        )

        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertIn("event_id", body)
        summary = body.get("db_summary")
        self.assertIsInstance(summary, dict)
        self.assertGreaterEqual(int(summary.get("event_count") or 0), 1)
        self.assertEqual(
            int(summary.get("latest_event_id") or 0),
            int(body.get("event_id") or 0),
        )

    def test_context_flush_endpoint_processes_backlog(self):
        event_payload = db_manager.fetch_manual_overtake_event(self.manual_event_id)
        self.assertIsInstance(event_payload, dict)
        context_frames = [
            {
                "offset_frames": 0,
                "frame_num": event_payload.get("frame_num", 0),
                "overtaker_group_id": event_payload.get("overtaker_group_id"),
                "overtaken_group_id": event_payload.get("overtaken_group_id"),
            }
        ]
        db_manager.enqueue_manual_context_backlog(
            self.manual_event_id,
            event_payload.get("run_id", 1),
            event_payload.get("frame_num", 0),
            event_payload,
            context_frames,
        )

        response = self.client.post("/api/manual_overtake/1/context/flush")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload.get("processed"), 1)
        self.assertEqual(payload.get("remaining"), 0)
        self.assertEqual(payload.get("enqueued"), 0)

        with sqlite3.connect(db_manager.MAIN_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM ManualOvertakeContext WHERE manual_event_id = ?",
                (self.manual_event_id,),
            )
            count = cursor.fetchone()[0]
        self.assertGreater(count, 0)

    def test_ensure_context_backlog_enqueues_missing_events(self):
        with sqlite3.connect(db_manager.MAIN_DB_PATH) as conn:
            conn.execute("DELETE FROM ManualOvertakeContextBacklog")
            conn.commit()

        enqueued, event_ids = db_manager.ensure_manual_context_backlog_for_runs([1])
        self.assertEqual(enqueued, 1)
        self.assertIn(self.manual_event_id, event_ids)

        with sqlite3.connect(db_manager.MAIN_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM ManualOvertakeContextBacklog
                WHERE manual_event_id = ? AND status = 'pending'
                """,
                (self.manual_event_id,),
            )
            pending_count = cursor.fetchone()[0]
        self.assertEqual(pending_count, 1)

    @mock.patch(
        "Source_code.routes._process_manual_context_backlog",
        return_value=(0, ["after"], {1: 0}),
    )
    @mock.patch(
        "Source_code.routes.ensure_manual_context_backlog_for_runs",
        return_value=(2, [101, 102]),
    )
    def test_context_flush_reports_enqueued_events(
        self,
        mock_ensure,
        mock_process,
    ):
        response = self.client.post("/api/manual_overtake/1/context/flush")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload.get("enqueued"), 2)
        self.assertEqual(payload.get("enqueued_event_ids"), [101, 102])
        self.assertIn("notices", payload)
        self.assertIn("after", payload["notices"])
        mock_ensure.assert_called_once_with([1])
        mock_process.assert_called_once_with([1])

    @mock.patch("Source_code.routes.count_manual_context_backlog", return_value={1: 0})
    @mock.patch("Source_code.routes.mark_manual_context_backlog_processed")
    @mock.patch(
        "Source_code.routes._save_manual_overtake_context_frames",
        return_value=(True, []),
    )
    @mock.patch("Source_code.routes._compute_manual_overtake_event_data")
    @mock.patch("Source_code.routes.list_manual_context_backlog")
    def test_context_flush_recomputes_full_window_when_missing(
        self,
        mock_list,
        mock_compute,
        mock_save,
        mock_mark,
        mock_count,
    ):
        entry = {
            "backlog_id": 10,
            "manual_event_id": 99,
            "run_id": 1,
            "frame_num": 250,
            "event_payload": {
                "run_id": 1,
                "frame_num": 250,
                "overtaker_group_id": 11,
                "overtaken_group_id": 12,
            },
            "context_frames": [
                {
                    "offset_frames": 0,
                    "frame_num": 250,
                    "overtaker_group_id": 11,
                    "overtaken_group_id": 12,
                }
            ],
        }
        mock_list.return_value = [entry]
        mock_compute.return_value = types.SimpleNamespace(
            payload=dict(entry["event_payload"]),
            context_frames=[
                {"offset_frames": -1},
                {"offset_frames": 0},
                {"offset_frames": 1},
            ],
            notices=["recomputed"],
        )

        response = self.client.post("/api/manual_overtake/1/context/flush")
        self.assertEqual(response.status_code, 200)

        mock_compute.assert_called_once()
        self.assertTrue(mock_save.called)
        args, _ = mock_save.call_args
        saved_frames = args[1]
        offsets = {frame.get("offset_frames") for frame in saved_frames}
        self.assertIn(-1, offsets)
        self.assertIn(1, offsets)

    def test_context_flush_uses_parallel_workers_when_configured(self):
        backlog_entries = [
            {
                "backlog_id": 1,
                "manual_event_id": 101,
                "run_id": 1,
                "frame_num": 500,
                "event_payload": {"frame_num": 500},
                "context_frames": [
                    {
                        "offset_frames": 0,
                        "frame_num": 500,
                        "overtaker_group_id": 1,
                        "overtaken_group_id": 2,
                    }
                ],
            },
            {
                "backlog_id": 2,
                "manual_event_id": 102,
                "run_id": 1,
                "frame_num": 600,
                "event_payload": {"frame_num": 600},
                "context_frames": [
                    {
                        "offset_frames": 0,
                        "frame_num": 600,
                        "overtaker_group_id": 3,
                        "overtaken_group_id": 4,
                    }
                ],
            },
        ]

        try:
            from Source_code import routes as routes_module
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency guard
            self.skipTest(f"必要な依存関係を読み込めないためスキップします: {exc}")

        with self.app.app_context():
            self.app.config["MANUAL_CONTEXT_BACKLOG_WORKERS"] = 8
            recorded_workers: dict[str, int] = {}
            real_executor = routes_module.ThreadPoolExecutor

            class RecordingExecutor(real_executor):
                def __init__(self, *args, **kwargs):
                    max_workers = kwargs.get("max_workers")
                    if max_workers is None and args:
                        max_workers = args[0]
                    recorded_workers["value"] = max_workers
                    super().__init__(*args, **kwargs)

            with mock.patch.object(routes_module, "ThreadPoolExecutor", RecordingExecutor):
                with mock.patch.object(routes_module, "list_manual_context_backlog", return_value=backlog_entries):
                    with mock.patch.object(routes_module, "count_manual_context_backlog", return_value={1: 0}):
                        saved_ids: list[int] = []

                        def fake_save(manual_event_id, frames, event_payload, frame_num, *, label=None):
                            saved_ids.append(manual_event_id)
                            return True, [f"{label} OK"]

                        with mock.patch.object(
                            routes_module,
                            "_save_manual_overtake_context_frames",
                            side_effect=fake_save,
                        ):
                            marked: list[tuple[int, bool, Optional[str]]] = []

                            def fake_mark(backlog_id, *, success, error_message=None):
                                marked.append((backlog_id, success, error_message))

                            with mock.patch.object(
                                routes_module,
                                "mark_manual_context_backlog_processed",
                                side_effect=fake_mark,
                            ):
                                processed, notices, remaining = routes_module._process_manual_context_backlog([1])

        self.assertEqual(processed, 2)
        self.assertEqual(len(notices), 2)
        self.assertEqual(remaining.get(1), 0)
        self.assertCountEqual(saved_ids, [101, 102])
        self.assertTrue(all(item[1] for item in marked))
        self.assertEqual(recorded_workers.get("value"), 2)

    def test_list_events_falls_back_for_unrecognized_classes(self):
        with sqlite3.connect(db_manager.MAIN_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO ProcessLog (run_id, calibration_profile) VALUES (?, ?)",
                (2, ""),
            )
            cursor.execute(
                """
                INSERT INTO ManualOvertakeEvents (
                    run_id,
                    frame_num,
                    overtaker_group_id,
                    overtaken_group_id,
                    overtaker_class_name,
                    overtaken_class_name,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    2,
                    200,
                    50,
                    60,
                    "personal_mobility",
                    "cart",
                    "2025-01-03T00:00:00",
                ),
            )
            fallback_event_id = cursor.lastrowid
            conn.commit()

        try:
            events = db_manager.list_manual_overtake_events(run_id=2, limit=10)
            self.assertTrue(
                any(
                    int(event.get("manual_event_id")) == fallback_event_id
                    for event in events
                )
            )
        finally:
            with sqlite3.connect(db_manager.MAIN_DB_PATH) as conn:
                conn.execute(
                    "DELETE FROM ManualOvertakeEvents WHERE run_id = ?",
                    (2,)
                )
                conn.execute(
                    "DELETE FROM ProcessLog WHERE run_id = ?",
                    (2,)
                )
                conn.commit()

    def test_db_link_check_returns_summary_for_run(self):
        response = self.client.get("/api/manual_overtake/db_link_check", query_string={
            "run_id": 1,
            "limit": 3,
        })
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        self.assertTrue(payload.get("linked"))
        self.assertEqual(payload.get("total_events"), 1)
        summaries = payload.get("run_summaries")
        self.assertIsInstance(summaries, list)
        self.assertGreaterEqual(len(summaries), 1)
        summary = summaries[0]
        self.assertEqual(summary.get("run_id"), 1)
        self.assertEqual(summary.get("event_count"), 1)
        samples = summary.get("samples")
        self.assertIsInstance(samples, list)
        self.assertGreaterEqual(len(samples), 1)
        self.assertEqual(samples[0].get("manual_event_id"), self.manual_event_id)

    def test_db_link_check_reports_missing_run(self):
        response = self.client.get("/api/manual_overtake/db_link_check", query_string={
            "run_id": 999,
        })
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        self.assertTrue(payload.get("linked"))
        self.assertEqual(payload.get("total_events"), 0)
        summaries = payload.get("run_summaries")
        self.assertIsInstance(summaries, list)
        self.assertEqual(len(summaries), 1)
        summary = summaries[0]
        self.assertEqual(summary.get("run_id"), 999)
        self.assertEqual(summary.get("event_count"), 0)
        self.assertEqual(summary.get("samples"), [])

    def test_db_link_check_without_run_id(self):
        response = self.client.get("/api/manual_overtake/db_link_check")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        self.assertTrue(payload.get("linked"))
        self.assertEqual(payload.get("total_events"), 1)
        summaries = payload.get("run_summaries")
        self.assertIsInstance(summaries, list)
        self.assertGreaterEqual(len(summaries), 1)


    def test_context_backlog_status_api_reports_counts(self):
        with sqlite3.connect(db_manager.MAIN_DB_PATH) as conn:
            conn.execute("DELETE FROM ManualOvertakeContextBacklog")
            conn.commit()

        event_payload = {
            "run_id": 1,
            "frame_num": 120,
            "overtaker_group_id": 10,
            "overtaken_group_id": 20,
        }
        context_frames = [
            {
                "offset_frames": 0,
                "frame_num": 120,
                "overtaker_group_id": 10,
                "overtaken_group_id": 20,
            }
        ]
        db_manager.enqueue_manual_context_backlog(
            self.manual_event_id,
            1,
            120,
            event_payload,
            context_frames,
        )

        response = self.client.get(
            "/api/manual_overtake/context/backlog",
            query_string={"run_id": 1},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("run_ids"), [1])
        self.assertEqual(payload.get("pending_total"), 1)
        self.assertIn("snapshot_taken_at", payload)
        pending_map = payload.get("pending") or {}
        self.assertEqual(int(pending_map.get("1", pending_map.get(1, 0))), 1)

    def test_context_process_api_handles_batches(self):
        with sqlite3.connect(db_manager.MAIN_DB_PATH) as conn:
            conn.execute("DELETE FROM ManualOvertakeContextBacklog")
            conn.commit()

        for frame in (130, 131):
            event_payload = {
                "run_id": 1,
                "frame_num": frame,
                "overtaker_group_id": 10,
                "overtaken_group_id": 20,
            }
            context_frames = [
                {
                    "offset_frames": 0,
                    "frame_num": frame,
                    "overtaker_group_id": 10,
                    "overtaken_group_id": 20,
                }
            ]
            db_manager.enqueue_manual_context_backlog(
                self.manual_event_id,
                1,
                frame,
                event_payload,
                context_frames,
            )

        first_response = self.client.post(
            "/api/manual_overtake/context/process",
            json={"run_ids": [1], "limit": 1},
        )
        self.assertEqual(first_response.status_code, 200)
        first_payload = first_response.get_json()
        self.assertIsInstance(first_payload, dict)
        self.assertEqual(first_payload.get("pending_before"), 2)
        self.assertEqual(first_payload.get("processed"), 1)
        self.assertGreaterEqual(first_payload.get("remaining_total"), 1)
        self.assertIn("snapshot_taken_at", first_payload)

        second_response = self.client.post(
            "/api/manual_overtake/context/process",
            json={"run_ids": [1], "limit": 5, "ensure_missing": False},
        )
        self.assertEqual(second_response.status_code, 200)
        second_payload = second_response.get_json()
        self.assertEqual(second_payload.get("remaining_total"), 0)
        self.assertEqual(second_payload.get("processed"), 1)

        with sqlite3.connect(db_manager.MAIN_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM ManualOvertakeContextBacklog WHERE status = 'pending'")
            remaining = cursor.fetchone()[0]
        self.assertEqual(remaining, 0)


if __name__ == "__main__":
    unittest.main()
