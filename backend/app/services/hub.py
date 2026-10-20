"""In-memory pub/sub buffer used to stream execution output to browsers in real time."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field

from ..config import settings

logger = logging.getLogger(__name__)

_KEEP_FINISHED_SECONDS = 120


@dataclass
class HubState:
    buffer: list[str] = field(default_factory=list)
    size: int = 0
    last_seq: int = 0
    last_event_at: float = 0.0
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    finished: bool = False
    status: str | None = None
    message: str | None = None
    cleanup_handle: asyncio.TimerHandle | None = None


@dataclass
class Subscription:
    snapshot: str
    last_seq: int
    queue: asyncio.Queue | None
    finished: bool
    status: str | None = None
    message: str | None = None


class ExecutionHub:
    """Thread-safe bridge between module output (possibly in worker threads) and SSE streams."""

    def __init__(self, max_buffer_chars: int = 700_000) -> None:
        self._states: dict[int, HubState] = {}
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._max_buffer_chars = max_buffer_chars
        self._metrics: dict[str, object] = {
            "published_chunks": 0,
            "dropped_chunks": 0,
            "stream_connections": 0,
            "reconnects": 0,
            "max_queue_depth": 0,
            "last_reconnect_at": None,
            "last_reconnect_lag_seconds": None,
        }

    def bind_loop(self) -> None:
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                return self._loop
        return self._loop

    def begin(self, log_id: int) -> None:
        with self._lock:
            self._states[log_id] = HubState()

    def publish(self, log_id: int, text: str, seq: int = 0) -> None:
        if not text:
            return
        with self._lock:
            state = self._states.get(log_id)
            if state is None or state.finished:
                return
            if seq > state.last_seq:
                state.last_seq = seq
            state.last_event_at = time.time()
            if state.size < self._max_buffer_chars:
                remaining = self._max_buffer_chars - state.size
                chunk = text[:remaining]
                state.buffer.append(chunk)
                state.size += len(chunk)
            queues = list(state.subscribers)
        self._metrics["published_chunks"] = int(
            self._metrics["published_chunks"]
        ) + 1
        for queue in queues:
            self._dispatch(queue, ("chunk", {"text": text, "seq": seq}))

    def finish(self, log_id: int, status: str, message: str | None, duration_ms: int | None) -> None:
        with self._lock:
            state = self._states.get(log_id)
            if state is None:
                return
            if state.finished:
                return
            state.finished = True
            state.status = status
            state.message = message
            queues = list(state.subscribers)
            loop = self.loop
            if loop is not None and loop.is_running():
                state.cleanup_handle = loop.call_later(
                    _KEEP_FINISHED_SECONDS, self._cleanup, log_id
                )
        payload = {
            "status": status,
            "message": message,
            "duration_ms": duration_ms,
        }
        for queue in queues:
            self._dispatch(queue, ("done", payload))

    def subscribe(self, log_id: int) -> Subscription:
        queue: asyncio.Queue = asyncio.Queue(maxsize=settings.sse_queue_max)
        with self._lock:
            state = self._states.get(log_id)
            if state is None:
                return Subscription(
                    snapshot="", last_seq=0, queue=None, finished=True
                )
            snapshot = "".join(state.buffer)
            if state.finished:
                return Subscription(
                    snapshot=snapshot,
                    last_seq=state.last_seq,
                    queue=None,
                    finished=True,
                    status=state.status,
                    message=state.message,
                )
            state.subscribers.add(queue)
        return Subscription(
            snapshot=snapshot,
            last_seq=state.last_seq,
            queue=queue,
            finished=False,
        )

    def unsubscribe(self, log_id: int, queue: asyncio.Queue | None) -> None:
        if queue is None:
            return
        with self._lock:
            state = self._states.get(log_id)
            if state is not None:
                state.subscribers.discard(queue)

    def record_stream_connection(
        self, log_id: int | None = None, reconnect: bool = False
    ) -> None:
        with self._lock:
            self._metrics["stream_connections"] = int(
                self._metrics["stream_connections"]
            ) + 1
            if reconnect:
                self._metrics["reconnects"] = int(self._metrics["reconnects"]) + 1
                self._metrics["last_reconnect_at"] = time.time()
                state = self._states.get(log_id) if log_id is not None else None
                if state is not None and state.last_event_at:
                    self._metrics["last_reconnect_lag_seconds"] = round(
                        max(0.0, time.time() - state.last_event_at), 3
                    )

    def metrics(self) -> dict[str, object]:
        with self._lock:
            queue_depth = 0
            for state in self._states.values():
                queue_depth += sum(queue.qsize() for queue in state.subscribers)
            self._metrics["max_queue_depth"] = max(
                int(self._metrics["max_queue_depth"]), queue_depth
            )
            return {
                **self._metrics,
                "active_streams": sum(
                    len(state.subscribers) for state in self._states.values()
                ),
                "current_queue_depth": queue_depth,
                "active_executions": len(self._states),
            }

    def active_streams(self) -> int:
        with self._lock:
            return sum(len(state.subscribers) for state in self._states.values())

    def close_all(self) -> None:
        with self._lock:
            log_ids = list(self._states.keys())
        for log_id in log_ids:
            self.finish(log_id, "failed", "服务正在关闭，执行流已断开", None)

    def _cleanup(self, log_id: int) -> None:
        with self._lock:
            state = self._states.pop(log_id, None)
            queues = list(state.subscribers) if state else []
        for queue in queues:
            queue.put_nowait(("done", {"status": "failed", "message": "日志流已关闭"}))

    def _dispatch(self, queue: asyncio.Queue, item: tuple[str, object]) -> None:
        def put() -> None:
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                with self._lock:
                    self._metrics["dropped_chunks"] = int(
                        self._metrics["dropped_chunks"]
                    ) + 1
                try:
                    queue.get_nowait()
                    queue.put_nowait(item)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

        loop = self.loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(put)
                return
            except RuntimeError:  # pragma: no cover - loop shutting down
                pass
        put()


hub = ExecutionHub()
