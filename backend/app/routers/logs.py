"""Execution history API including SSE replay by ring-buffer ``seq``."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import SessionLocal, get_db
from ..deps import get_current_user
from ..models import STATUS_FAILED, STATUS_RUNNING, ExecutionLog
from ..schemas import LogDetail, LogOut, LogPage, MessageResponse
from ..services.hub import hub
from ..services.ring_log import ring_log
from ..timeutils import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/logs", tags=["执行日志"], dependencies=[Depends(get_current_user)]
)

LogStatus = Literal["running", "success", "failed"]
LogTrigger = Literal["manual", "schedule"]

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
_STALE_MESSAGE = "执行状态丢失（服务可能重启过）"
_MISSING_MESSAGE = "执行状态丢失"


@dataclass(frozen=True)
class _LogSnapshot:
    """Execution-row fields needed by the stream, read before the response."""

    status: str
    message: str | None
    duration_ms: int | None
    legacy_output: str


@dataclass
class _ReplayState:
    """Replay cursor plus the row count of the latest ring read."""

    cursor: int
    rows: int = 0


def _sse(event: str, data: dict, event_id: int | None = None) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}event: {event}\ndata: {payload}\n\n"


def _done_frame(payload: dict, cursor: int) -> str:
    """Render the terminal frame with ``last_seq`` stamped from the cursor."""
    return _sse("done", {**payload, "last_seq": cursor}, cursor or None)


@router.get("", response_model=LogPage, summary="分页查询执行记录")
async def list_logs(
    module_id: int | None = Query(default=None),
    status: LogStatus | None = Query(default=None),
    trigger: LogTrigger | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> LogPage:
    conditions = []
    if module_id is not None:
        conditions.append(ExecutionLog.module_id == module_id)
    if status is not None:
        conditions.append(ExecutionLog.status == status)
    if trigger is not None:
        conditions.append(ExecutionLog.trigger == trigger)

    total = int(
        await db.scalar(
            select(func.count()).select_from(ExecutionLog).where(*conditions)
        )
        or 0
    )
    rows = (
        (
            await db.execute(
                select(ExecutionLog)
                .where(*conditions)
                .order_by(ExecutionLog.started_at.desc(), ExecutionLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    pages = max(1, math.ceil(total / page_size)) if total else 0
    return LogPage(
        items=[LogOut.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.delete("", response_model=MessageResponse, summary="清空执行记录")
async def clear_logs(
    module_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    conditions = [ExecutionLog.status != STATUS_RUNNING]
    if module_id is not None:
        conditions.append(ExecutionLog.module_id == module_id)
    ids = list(
        (
            await db.execute(select(ExecutionLog.id).where(*conditions))
        ).scalars()
    )
    if ids:
        await asyncio.to_thread(ring_log.delete_execution_ids, ids)
    result = await db.execute(delete(ExecutionLog).where(*conditions))
    await db.commit()
    return MessageResponse(
        message=f"已清理 {result.rowcount or 0} 条已完成记录，执行中的任务会保留"
    )


@router.get("/{log_id}", response_model=LogDetail, summary="执行详情")
async def get_log(log_id: int, db: AsyncSession = Depends(get_db)) -> LogDetail:
    log = await db.get(ExecutionLog, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    output, last_seq = await asyncio.to_thread(ring_log.read_execution_text, log_id)
    # Old rows created before the ring migration retain their output as a
    # read-only fallback; new rows never duplicate it in execution_logs.
    if not output and log.output:
        output = log.output
    detail = LogDetail.model_validate(log)
    return detail.model_copy(update={"output": output, "last_seq": last_seq})


def _resume_cursor(request: Request, last_seq: int) -> int:
    """Honour the ``Last-Event-ID`` header used by EventSource reconnects."""
    header_seq = request.headers.get("last-event-id", "").strip()
    if header_seq.isdigit():
        last_seq = max(last_seq, int(header_seq))
    return last_seq


async def _load_snapshot(log_id: int) -> _LogSnapshot:
    """Read the execution fields the stream needs, or raise the route's 404."""
    async with SessionLocal() as db:
        log = await db.get(ExecutionLog, log_id)
        if log is None:
            raise HTTPException(status_code=404, detail="执行记录不存在")
        return _LogSnapshot(
            status=log.status,
            message=log.message,
            duration_ms=log.duration_ms,
            legacy_output=log.output or "",
        )


async def _replay_ring(log_id: int, state: _ReplayState) -> AsyncIterator[str]:
    """Yield persisted ring chunks newer than ``state.cursor`` and advance it."""
    rows = await asyncio.to_thread(ring_log.read_execution, log_id, state.cursor)
    state.rows = len(rows)
    for row in rows:
        seq = int(row["seq"])
        if seq <= state.cursor:
            continue
        state.cursor = seq
        yield _sse("chunk", {"text": row["text"], "seq": seq}, seq)


async def _close_stale_log(log_id: int) -> tuple[str, str | None, int | None]:
    """Close an orphaned running row the way startup recovery would."""
    async with SessionLocal() as db:
        row = await db.get(ExecutionLog, log_id)
        if row is not None and row.status == STATUS_RUNNING:
            row.status = STATUS_FAILED
            row.message = _STALE_MESSAGE
            row.finished_at = utcnow()
            await db.commit()
        if row is None:
            return STATUS_FAILED, _MISSING_MESSAGE, None
        return row.status, row.message, row.duration_ms


def _live_chunk_frame(payload: object, state: _ReplayState) -> str | None:
    data = payload if isinstance(payload, dict) else {"text": str(payload)}
    seq = int(data.get("seq") or 0)
    if seq and seq <= state.cursor:
        return None
    if seq:
        state.cursor = seq
    return _sse(
        "chunk",
        {"text": str(data.get("text", "")), "seq": seq},
        seq or None,
    )


async def _drain_live(
    log_id: int,
    request: Request,
    queue: asyncio.Queue,
    state: _ReplayState,
) -> AsyncIterator[str]:
    """Relay queued live events until done, disconnect or cancellation."""
    while True:
        try:
            event, payload = await asyncio.wait_for(
                queue.get(), timeout=settings.sse_keepalive_seconds
            )
        except asyncio.TimeoutError:
            if await request.is_disconnected():
                break
            yield ": keep-alive\n\n"
            continue
        except asyncio.CancelledError:
            break
        if event == "chunk":
            frame = _live_chunk_frame(payload, state)
            if frame is not None:
                yield frame
        elif event == "done":
            # Capture writes the ring row before publishing, so this
            # final query closes the small query/live race.
            async for frame in _replay_ring(log_id, state):
                yield frame
            done_payload = payload if isinstance(payload, dict) else {}
            yield _done_frame(done_payload, state.cursor)
            break


async def _completed_frames(
    snapshot: _LogSnapshot, state: _ReplayState
) -> AsyncIterator[str]:
    if not state.rows and snapshot.legacy_output and state.cursor == 0:
        yield _sse("chunk", {"text": snapshot.legacy_output, "seq": 0}, 0)
    yield _done_frame(
        {
            "status": snapshot.status,
            "message": snapshot.message,
            "duration_ms": snapshot.duration_ms,
        },
        state.cursor,
    )


async def _finished_frames(
    log_id: int,
    snapshot: _LogSnapshot,
    subscription: object,
    state: _ReplayState,
) -> AsyncIterator[str]:
    final_status = getattr(subscription, "status", None)
    final_message = getattr(subscription, "message", None)
    if final_status is None and snapshot.status == STATUS_RUNNING:
        final_status, final_message, _ = await _close_stale_log(log_id)
    async for frame in _replay_ring(log_id, state):
        yield frame
    yield _done_frame(
        {
            "status": final_status or snapshot.status,
            "message": final_message or snapshot.message,
            "duration_ms": None,
        },
        state.cursor,
    )


async def _event_stream(
    log_id: int,
    request: Request,
    snapshot: _LogSnapshot,
    last_seq: int,
) -> AsyncIterator[str]:
    """Replay retained output, then relay live events until the execution ends."""
    state = _ReplayState(cursor=max(0, int(last_seq)))
    # Subscribe *before* the ring query so events appended between the two
    # operations are queued, then de-duplicated by seq below.
    subscription = (
        hub.subscribe(log_id) if snapshot.status == STATUS_RUNNING else None
    )
    hub.record_stream_connection(log_id, reconnect=state.cursor > 0)
    async for frame in _replay_ring(log_id, state):
        yield frame

    if snapshot.status != STATUS_RUNNING:
        async for frame in _completed_frames(snapshot, state):
            yield frame
        return

    if subscription is None:
        yield _done_frame(
            {"status": STATUS_FAILED, "message": snapshot.message},
            state.cursor,
        )
        return

    if subscription.finished:
        async for frame in _finished_frames(log_id, snapshot, subscription, state):
            yield frame
        return

    if subscription.queue is None:
        status, message, duration_ms = await _close_stale_log(log_id)
        yield _done_frame(
            {
                "status": status,
                "message": message,
                "duration_ms": duration_ms,
            },
            state.cursor,
        )
        return

    try:
        async for frame in _drain_live(log_id, request, subscription.queue, state):
            yield frame
    finally:
        hub.unsubscribe(log_id, subscription.queue)
        logger.debug("SSE 日志流已断开 log_id=%s", log_id)


@router.get("/{log_id}/stream", summary="实时日志流（SSE，支持 last_seq 断点续读）")
async def stream_log(
    log_id: int,
    request: Request,
    last_seq: int = Query(default=0, ge=0),
) -> StreamingResponse:
    resume = _resume_cursor(request, last_seq)
    snapshot = await _load_snapshot(log_id)
    return StreamingResponse(
        _event_stream(log_id, request, snapshot, resume),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
