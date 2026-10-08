"""動画フレームを事前デコードして手動追い越しタブの再生を高速化するバッファ管理。"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from ..tools.calibration_tool import load_video_frame


MANUAL_BUFFER_LIMIT_BYTES = 3 * 1024 * 1024 * 1024  # 3GB
_PREFETCH_MAX_WIDTH = 1280
_JPEG_QUALITY = 80


@dataclass
class _FrameEntry:
    run_id: int
    frame_index: int
    width: int
    payload: bytes
    size: int
    last_access: float


class _VideoContext:
    """特定Runの動画に対するプリフェッチ状態を管理する。"""

    def __init__(
        self,
        manager: "ManualVideoFrameBuffer",
        run_id: int,
        video_path: str,
        frame_count: Optional[int],
        source_width: Optional[int],
        source_height: Optional[int],
    ) -> None:
        self.manager = manager
        self.run_id = run_id
        self.video_path = video_path
        self.frame_count = frame_count or 0
        self.source_width = source_width or 0
        self.source_height = source_height or 0
        self.prefetch_width = self._determine_prefetch_width()
        self.stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.frame_index_map: Dict[int, set[int]] = defaultdict(set)
        self.state_lock = threading.Lock()
        self.prefetched_frames = 0
        self.last_frame_index = -1
        self.prefetching = False
        self.prefetch_completed = False
        self.prefetch_error: Optional[str] = None

    def _determine_prefetch_width(self) -> Optional[int]:
        if not self.source_width:
            return None
        return min(self.source_width, _PREFETCH_MAX_WIDTH)

    def start_prefetch(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.stop_event.clear()
        self._thread = threading.Thread(target=self._prefetch_loop, name=f"ManualBufferPrefetch-{self.run_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    def update_metadata(
        self,
        frame_count: Optional[int],
        width: Optional[int],
        height: Optional[int],
    ) -> None:
        with self.state_lock:
            if frame_count:
                self.frame_count = int(frame_count)
            if width:
                self.source_width = int(width)
            if height:
                self.source_height = int(height)
            self.prefetch_width = self._determine_prefetch_width()

    def reset_progress(self) -> None:
        with self.state_lock:
            self.prefetched_frames = 0
            self.last_frame_index = -1
            self.prefetching = False
            self.prefetch_completed = False
            self.prefetch_error = None

    def register_frame(self, frame_index: int, width: int) -> None:
        self.frame_index_map[frame_index].add(width)

    def unregister_frame(self, frame_index: int, width: int) -> None:
        widths = self.frame_index_map.get(frame_index)
        if not widths:
            return
        widths.discard(width)
        if not widths:
            self.frame_index_map.pop(frame_index, None)

    def cached_widths(self, frame_index: int) -> Tuple[int, ...]:
        widths = self.frame_index_map.get(frame_index)
        if not widths:
            return tuple()
        return tuple(widths)

    def _prefetch_loop(self) -> None:
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            with self.state_lock:
                self.prefetch_error = "動画を開けませんでした"
            return
        try:
            target_width = self.prefetch_width
            frame_idx = 0
            with self.state_lock:
                self.prefetching = True
                self.prefetch_completed = False
                self.prefetch_error = None
                self.prefetched_frames = 0
                self.last_frame_index = -1
            while not self.stop_event.is_set():
                if self.frame_count and frame_idx >= self.frame_count:
                    break
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                resized = frame
                if target_width and frame.shape[1] != target_width:
                    ratio = target_width / float(frame.shape[1])
                    target_height = max(int(frame.shape[0] * ratio), 1)
                    resized = cv2.resize(frame, (target_width, target_height))
                width = resized.shape[1]
                success, buffer = cv2.imencode(
                    ".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY]
                )
                if success:
                    self.manager.store_frame(self.run_id, frame_idx, width, buffer.tobytes())
                with self.state_lock:
                    self.prefetched_frames = frame_idx + 1
                    self.last_frame_index = frame_idx
                frame_idx += 1
        except Exception as exc:  # pragma: no cover - 予期せぬ例外の記録
            with self.state_lock:
                self.prefetch_error = str(exc)
        finally:
            cap.release()
            with self.state_lock:
                self.prefetching = False
                if not self.stop_event.is_set() and self.prefetch_error is None:
                    self.prefetch_completed = True


class ManualVideoFrameBuffer:
    """3GBのメモリを利用して手動追い越し向け動画フレームをキャッシュする。"""

    def __init__(self, max_bytes: int = MANUAL_BUFFER_LIMIT_BYTES) -> None:
        self.max_bytes = max_bytes
        self.total_bytes = 0
        self.entries: "OrderedDict[Tuple[int, int, int], _FrameEntry]" = OrderedDict()
        self.videos: Dict[int, _VideoContext] = {}
        self.lock = threading.RLock()

    def prepare_video(
        self,
        run_id: int,
        video_path: str,
        frame_count: Optional[int],
        width: Optional[int],
        height: Optional[int],
        *,
        restart: bool = False,
        start_prefetch: bool = False,
    ) -> None:
        ctx_to_start: Optional[_VideoContext] = None
        with self.lock:
            ctx = self.videos.get(run_id)
            if ctx and ctx.video_path != video_path:
                self._purge_run_locked(run_id)
                ctx = None
            if restart and ctx:
                self._purge_run_locked(run_id)
                ctx = None
            if not ctx:
                ctx = _VideoContext(self, run_id, video_path, frame_count, width, height)
                self.videos[run_id] = ctx
            else:
                ctx.update_metadata(frame_count, width, height)
            if start_prefetch and ctx:
                ctx.reset_progress()
                ctx_to_start = ctx
        if ctx_to_start:
            ctx_to_start.start_prefetch()

    def get_frame(
        self,
        run_id: int,
        video_path: str,
        frame_index: int,
        requested_width: Optional[int] = None,
    ) -> Optional[bytes]:
        ctx = self._ensure_context(run_id, video_path)
        if not ctx:
            return None
        key_width = self._normalize_width(requested_width, ctx)
        data = self._get_cached_frame(run_id, frame_index, key_width)
        if data is not None:
            return data
        # 既存幅のキャッシュを転用できるか確認
        fallback_entry = self._find_any_entry(run_id, frame_index)
        if fallback_entry and requested_width and requested_width > 0:
            converted = self._convert_width(fallback_entry.payload, fallback_entry.width, requested_width, run_id, frame_index)
            if converted is not None:
                return converted
        # ディスクから直接読み込み
        frame = load_video_frame(video_path, frame_index, requested_width)
        if frame is None:
            return None
        success, buffer = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY]
        )
        if not success:
            return None
        payload = buffer.tobytes()
        actual_width = frame.shape[1]
        self.store_frame(run_id, frame_index, actual_width, payload)
        return payload

    def store_frame(self, run_id: int, frame_index: int, width: int, payload: bytes) -> None:
        if not payload:
            return
        size = len(payload)
        if size > self.max_bytes:
            return
        key = (run_id, frame_index, width)
        with self.lock:
            existing = self.entries.pop(key, None)
            if existing:
                self.total_bytes -= existing.size
                ctx = self.videos.get(run_id)
                if ctx:
                    ctx.unregister_frame(frame_index, width)
            entry = _FrameEntry(run_id, frame_index, width, payload, size, time.time())
            self.entries[key] = entry
            self.total_bytes += size
            ctx = self.videos.get(run_id)
            if ctx:
                ctx.register_frame(frame_index, width)
            self._evict_if_needed_locked()

    def _get_cached_frame(self, run_id: int, frame_index: int, width: int) -> Optional[bytes]:
        key = (run_id, frame_index, width)
        with self.lock:
            entry = self.entries.get(key)
            if not entry:
                return None
            entry.last_access = time.time()
            self.entries.move_to_end(key)
            return entry.payload

    def _find_any_entry(self, run_id: int, frame_index: int) -> Optional[_FrameEntry]:
        with self.lock:
            ctx = self.videos.get(run_id)
            if not ctx:
                return None
            widths = ctx.cached_widths(frame_index)
            for width in widths:
                key = (run_id, frame_index, width)
                entry = self.entries.get(key)
                if entry:
                    entry.last_access = time.time()
                    self.entries.move_to_end(key)
                    return entry
            return None

    def _convert_width(
        self,
        base_payload: bytes,
        base_width: int,
        target_width: int,
        run_id: int,
        frame_index: int,
    ) -> Optional[bytes]:
        if base_width == target_width:
            return base_payload
        if target_width <= 0:
            return base_payload
        array = np.frombuffer(base_payload, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            return None
        if image.shape[1] != target_width:
            ratio = target_width / float(image.shape[1])
            target_height = max(int(image.shape[0] * ratio), 1)
            image = cv2.resize(image, (target_width, target_height))
        success, buffer = cv2.imencode(
            ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY]
        )
        if not success:
            return None
        payload = buffer.tobytes()
        self.store_frame(run_id, frame_index, target_width, payload)
        return payload

    def _normalize_width(self, requested_width: Optional[int], ctx: _VideoContext) -> int:
        if requested_width and requested_width > 0:
            return requested_width
        if ctx.prefetch_width:
            return ctx.prefetch_width
        if ctx.source_width:
            return ctx.source_width
        return 0

    def _ensure_context(self, run_id: int, video_path: str) -> Optional[_VideoContext]:
        with self.lock:
            ctx = self.videos.get(run_id)
            if ctx and ctx.video_path == video_path:
                return ctx
            if ctx and ctx.video_path != video_path:
                self._purge_run_locked(run_id)
            # 動画情報が無い場合は最小限のコンテキストを生成
            ctx = _VideoContext(self, run_id, video_path, frame_count=None, source_width=None, source_height=None)
            self.videos[run_id] = ctx
        return ctx

    def _purge_run_locked(self, run_id: int) -> None:
        ctx = self.videos.pop(run_id, None)
        if ctx:
            ctx.stop()
            ctx.reset_progress()
        keys_to_remove = [key for key in self.entries.keys() if key[0] == run_id]
        for key in keys_to_remove:
            entry = self.entries.pop(key)
            self.total_bytes -= entry.size
        if ctx:
            ctx.frame_index_map.clear()

    def get_status(self, run_id: int) -> Optional[dict[str, object]]:
        with self.lock:
            ctx = self.videos.get(run_id)
            if not ctx:
                return None
            with ctx.state_lock:
                status = {
                    "prefetched_frames": ctx.prefetched_frames,
                    "frame_count": ctx.frame_count,
                    "prefetching": ctx.prefetching and not ctx.stop_event.is_set(),
                    "prefetch_completed": ctx.prefetch_completed,
                    "last_frame_index": ctx.last_frame_index,
                    "prefetch_width": ctx.prefetch_width,
                    "error": ctx.prefetch_error,
                }
            cached_frames = len(ctx.frame_index_map)
            cached_bytes = 0
            for key, entry in self.entries.items():
                if key[0] == run_id:
                    cached_bytes += entry.size
            status.update(
                {
                    "cached_frames": cached_frames,
                    "cached_bytes": cached_bytes,
                    "max_bytes": self.max_bytes,
                }
            )
            return status

    def _evict_if_needed_locked(self) -> None:
        while self.total_bytes > self.max_bytes and self.entries:
            key, entry = self.entries.popitem(last=False)
            self.total_bytes -= entry.size
            ctx = self.videos.get(entry.run_id)
            if ctx:
                ctx.unregister_frame(entry.frame_index, entry.width)


manual_frame_buffer = ManualVideoFrameBuffer()
"""手動追い越し用フレームバッファのシングルトン。"""
