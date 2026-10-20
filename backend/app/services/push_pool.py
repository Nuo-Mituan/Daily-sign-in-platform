"""Unified push pool, daily batches, skip rules and immediate flush cleanup."""

from __future__ import annotations

import asyncio
import json
import time as clock
import logging
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import SessionLocal
from .lock_registry import KeyLockRegistry
from ..models import (
    Module,
    PushBatch,
    PushPool,
    PushRecord,
)
from ..scheduling import ScheduleError, execution_day_status, parse_hhmm
from ..timeutils import utcnow
from .push_outbox import drain as drain_outbox, enqueue as enqueue_outbox, make_idempotency_key
from .push import (
    EVENT_LABELS,
    PushConfigError,
    load_push_config,
    render_template,
    send_message,
)
from .redaction import redact_text
from .ring_log import ring_log

logger = logging.getLogger(__name__)

POOL_PENDING = "pending"
POOL_SUCCESS = "success"
POOL_FAILED = "failed"
POOL_SKIPPED = "skipped"
BATCH_PENDING = "pending"
BATCH_SENT = "sent"
BATCH_FAILED = "failed"
BATCH_NOOP = "noop"

_locks = KeyLockRegistry[str](max_unlocked=256)


def _lock(cycle_id: str) -> asyncio.Lock:
    return _locks.get(cycle_id)


def business_date() -> date:
    return datetime.now(settings.timezone_info).date()


def cycle_id_for(day: date | None = None) -> str:
    return (day or business_date()).isoformat()


def _module_due(module: Module, day: date) -> tuple[bool, str]:
    try:
        return execution_day_status(
            module.repeat_cycle, day, module.repeat_sub_value
        )
    except ScheduleError:
        return False, "当日不在执行周期"


async def _counts(db: AsyncSession, cycle_id: str) -> dict[str, int]:
    rows = (
        await db.execute(
            select(PushPool.status, func.count())
            .where(PushPool.cycle_id == cycle_id)
            .group_by(PushPool.status)
        )
    ).all()
    mapping = {str(row[0]): int(row[1]) for row in rows}
    return {
        "success": mapping.get(POOL_SUCCESS, 0),
        "failed": mapping.get(POOL_FAILED, 0),
        "skipped": mapping.get(POOL_SKIPPED, 0),
        "pending": mapping.get(POOL_PENDING, 0),
    }


async def _load_expected(db: AsyncSession) -> list[Module]:
    """Load the enabled unified modules that belong to the expected set."""
    return list(
        (
            await db.execute(
                select(Module)
                .where(Module.enabled.is_(True), Module.push_unified.is_(True))
                .order_by(Module.id.asc())
            )
        )
        .scalars()
        .all()
    )


async def _sync_pool_rows(
    db: AsyncSession, modules: list[Module], cycle_id: str, day: date
) -> None:
    """Create missing pool rows, pre-marking modules that are not due today."""
    existing = (
        (
            await db.execute(
                select(PushPool).where(PushPool.cycle_id == cycle_id)
            )
        )
        .scalars()
        .all()
    )
    by_module = {row.module_id: row for row in existing}
    for module in modules:
        if module.id in by_module:
            continue
        due, reason = _module_due(module, day)
        db.add(
            PushPool(
                cycle_id=cycle_id,
                module_id=module.id,
                module_key=module.key,
                module_name=module.name,
                status=POOL_PENDING if due else POOL_SKIPPED,
                trigger="schedule",
                message=None if due else reason,
                details=None if due else reason,
            )
        )


def _module_deadline(module: Module, day: date) -> datetime:
    try:
        hour, minute = parse_hhmm(module.end_time)
    except ScheduleError:
        hour, minute = 23, 59
    return datetime.combine(
        day, time(hour, minute), tzinfo=settings.timezone_info
    )


def _apply_deadline(
    batch: PushBatch, modules: list[Module], day: date
) -> None:
    latest_end = max(
        (_module_deadline(module, day) for module in modules), default=None
    )
    if latest_end is not None:
        batch.deadline_at = (
            latest_end + timedelta(minutes=settings.push_max_wait_minutes)
        ).astimezone(timezone.utc)


async def _refresh_batch_counts(db: AsyncSession, batch: PushBatch) -> None:
    counts = await _counts(db, batch.cycle_id)
    batch.success_count = counts["success"]
    batch.failed_count = counts["failed"]
    batch.skipped_count = counts["skipped"]
    batch.pending_count = counts["pending"]


async def ensure_batch(cycle_id: str | None = None) -> PushBatch | None:
    """Create the expected set (enabled + unified) and pre-generate skips."""
    cycle_id = cycle_id or cycle_id_for()
    day = date.fromisoformat(cycle_id)
    async with _lock(cycle_id):
        async with SessionLocal() as db:
            modules = await _load_expected(db)
            if not modules:
                return None
            batch = await db.scalar(
                select(PushBatch).where(PushBatch.cycle_id == cycle_id)
            )
            if batch is None:
                batch = PushBatch(
                    cycle_id=cycle_id,
                    idempotency_key=f"unified:{cycle_id}",
                    status=BATCH_PENDING,
                    expected_count=len(modules),
                )
                db.add(batch)
                await db.flush()
            elif batch.status != BATCH_PENDING:
                return batch
            await _sync_pool_rows(db, modules, cycle_id, day)
            batch.expected_count = len(modules)
            if not batch.idempotency_key:
                batch.idempotency_key = f"unified:{cycle_id}"
            _apply_deadline(batch, modules, day)
            # New rows added in this transaction are visible after flush().
            await db.flush()
            await _refresh_batch_counts(db, batch)
            await db.commit()
            await db.refresh(batch)
            return batch


async def _supplement_after_flush(
    module_id: int,
    module_key: str,
    module_name: str,
    cycle_id: str,
    trigger: str,
    status: str,
    message: str,
) -> None:
    """Send a single post-flush supplement for manual executions only."""
    if trigger == "manual" and settings.push_after_flush_mode == "single":
        await _send_supplement(
            module_id, module_key, module_name, cycle_id, status, message
        )


async def _record_probe(
    module_id: int,
    cycle_id: str,
    *,
    trigger: str,
    status: str,
    message: str,
) -> bool:
    """Cheap pre-check outside the cycle lock: may a result be recorded?"""
    async with SessionLocal() as probe_db:
        probe = await probe_db.scalar(
            select(PushBatch).where(PushBatch.cycle_id == cycle_id)
        )
        module_probe = await probe_db.get(Module, module_id)
        if module_probe is None or not module_probe.push_unified:
            return False
        if probe is None or probe.status not in {BATCH_SENT, BATCH_FAILED}:
            return True
        await _supplement_after_flush(
            module_id,
            module_probe.key,
            module_probe.name,
            cycle_id,
            trigger,
            status,
            message,
        )
        return False


async def _upsert_pool_result(
    db: AsyncSession,
    *,
    module: Module,
    cycle_id: str,
    status: str,
    message: str,
    details: str,
    trigger: str,
) -> None:
    """Insert or overwrite the single pool row for this module and cycle."""
    row = await db.scalar(
        select(PushPool).where(
            PushPool.cycle_id == cycle_id,
            PushPool.module_id == module.id,
        )
    )
    final_status = POOL_SUCCESS if status == "success" else POOL_FAILED
    note = redact_text(message or "")
    if row is None:
        row = PushPool(
            cycle_id=cycle_id,
            module_id=module.id,
            module_key=module.key,
            module_name=module.name,
        )
        db.add(row)
    was_skipped = row.status == POOL_SKIPPED
    row.status = final_status
    row.trigger = trigger
    row.message = (
        f"手动补执行：{note}" if trigger == "manual" and was_skipped else note
    )
    row.details = redact_text(details or note)
    if trigger == "manual" and was_skipped:
        row.manual_override = True


async def _apply_result(
    db: AsyncSession,
    *,
    module_id: int,
    cycle_id: str,
    status: str,
    message: str,
    details: str,
    trigger: str,
) -> bool:
    """Apply one module result while the cycle lock is held."""
    module = await db.get(Module, module_id)
    batch = await db.scalar(
        select(PushBatch).where(PushBatch.cycle_id == cycle_id)
    )
    if module is None or batch is None or not module.push_unified:
        return False
    if batch.status == BATCH_NOOP:
        batch.status = BATCH_PENDING
        batch.details_cleared = False
    if batch.status in {BATCH_SENT, BATCH_FAILED}:
        module_key, module_name = module.key, module.name
        await db.rollback()
        await _supplement_after_flush(
            module_id,
            module_key,
            module_name,
            cycle_id,
            trigger,
            status,
            message,
        )
        return False
    await _upsert_pool_result(
        db,
        module=module,
        cycle_id=cycle_id,
        status=status,
        message=message,
        details=details,
        trigger=trigger,
    )
    await db.commit()
    return True


async def record_unified_result(
    module_id: int,
    *,
    status: str,
    message: str,
    details: str,
    trigger: str,
    cycle_id: str | None = None,
) -> None:
    cycle_id = cycle_id or cycle_id_for()
    batch = await ensure_batch(cycle_id)
    if batch is None:
        return
    if not await _record_probe(
        module_id,
        cycle_id,
        trigger=trigger,
        status=status,
        message=message,
    ):
        return
    async with _lock(cycle_id):
        async with SessionLocal() as db:
            applied = await _apply_result(
                db,
                module_id=module_id,
                cycle_id=cycle_id,
                status=status,
                message=message,
                details=details,
                trigger=trigger,
            )
    if applied:
        await maybe_flush_batch(cycle_id)


async def maybe_flush_batch(cycle_id: str | None = None) -> bool:
    cycle_id = cycle_id or cycle_id_for()
    async with _lock(cycle_id):
        async with SessionLocal() as db:
            batch = await db.scalar(
                select(PushBatch).where(PushBatch.cycle_id == cycle_id)
            )
            if batch is None or batch.status != BATCH_PENDING:
                return False
            rows = (
                (
                    await db.execute(
                        select(PushPool)
                        .where(PushPool.cycle_id == cycle_id)
                        .order_by(PushPool.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                return False
            # Rule: no execution day and no manual execution => no push at all.
            # A pending row means at least one module was expected to execute
            # today; it can still be summarised as timeout-incomplete.
            has_executing = any(row.status != POOL_SKIPPED for row in rows)
            if not has_executing:
                await _mark_noop(db, batch, rows)
                return False
            pending = [row for row in rows if row.status == POOL_PENDING]
            deadline = batch.deadline_at or (
                batch.created_at
                + timedelta(minutes=settings.push_max_wait_minutes)
            )
            timed_out = datetime.now(timezone.utc) >= deadline
            if pending and not timed_out:
                return False
            if pending and timed_out:
                for row in pending:
                    row.status = POOL_FAILED
                    row.message = "超时未完成"
                    row.details = "超过批次最大等待时间，未收到模块终态"
                await db.commit()
                rows = (
                    (
                        await db.execute(
                            select(PushPool)
                            .where(PushPool.cycle_id == cycle_id)
                            .order_by(PushPool.id.asc())
                        )
                    )
                    .scalars()
                    .all()
                )
            counts = {
                "success": sum(1 for row in rows if row.status == POOL_SUCCESS),
                "failed": sum(1 for row in rows if row.status == POOL_FAILED),
                "skipped": sum(1 for row in rows if row.status == POOL_SKIPPED),
                "pending": 0,
            }
            await _flush_locked(db, batch, rows, counts)
            return True


async def flush_batch(cycle_id: str | None = None) -> bool:
    """Public idempotent flush entry point, also used by the timeout sweep."""
    return await maybe_flush_batch(cycle_id)


async def _flush_locked(
    db: AsyncSession,
    batch: PushBatch,
    rows: list[PushPool],
    counts: dict[str, int],
) -> None:
    if batch.status != BATCH_PENDING:
        return
    summary = _summary(batch.cycle_id, rows, counts)
    await _persist_summary(db, batch, counts, summary)
    config, result = await _send_summary(db, batch, summary)
    await _finalize_flush(db, batch, counts, summary, config, result)


async def _persist_summary(
    db: AsyncSession,
    batch: PushBatch,
    counts: dict[str, int],
    summary: str,
) -> None:
    batch.success_count = counts["success"]
    batch.failed_count = counts["failed"]
    batch.skipped_count = counts["skipped"]
    batch.pending_count = counts["pending"]
    batch.summary = summary
    await db.commit()


async def _send_summary(
    db: AsyncSession, batch: PushBatch, summary: str
) -> tuple[dict[str, object], dict[str, object]]:
    """Send the unified summary with retries; returns (config, result)."""
    result: dict[str, object] = {"sent": False, "error": "未配置推送渠道"}
    config: dict[str, object] = {"channel": "none", "config": {}}
    attempts = max(1, settings.push_retry_attempts)
    try:
        async with SessionLocal() as config_db:
            config = await load_push_config(config_db)
        if config["channel"] == "none":
            raise PushConfigError("未配置全局推送渠道")
        title = f"签到日报｜{batch.cycle_id}"
        for attempt in range(attempts):
            batch.retry_count = attempt
            batch.last_attempt_at = utcnow()
            await db.commit()
            result = await send_message(
                config["channel"],
                config["config"],
                title,
                summary,
                idempotency_key=batch.idempotency_key,
            )
            await asyncio.to_thread(
                ring_log.append_push,
                (
                    f"统一汇总 attempt={attempt + 1}/{attempts} "
                    f"cycle={batch.cycle_id} sent={bool(result.get('sent'))} "
                    f"error={result.get('error') or result.get('reason') or ''}"
                ),
                "INFO" if result.get("sent") else "WARNING",
                batch.id,
            )
            if result.get("sent"):
                break
            if attempt + 1 < attempts:
                await asyncio.sleep(settings.push_retry_base_seconds * (2**attempt))
    except PushConfigError as exc:
        result = {"sent": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        result = {"sent": False, "error": f"{type(exc).__name__}: {exc}"}
    return config, result


async def _finalize_flush(
    db: AsyncSession,
    batch: PushBatch,
    counts: dict[str, int],
    summary: str,
    config: dict[str, object],
    result: dict[str, object],
) -> None:
    success = bool(result.get("sent"))
    batch.status = BATCH_SENT if success else BATCH_FAILED
    batch.flushed_at = utcnow()
    batch.details_cleared = True
    if success:
        batch.error = None
    else:
        batch.error = redact_text(
            str(result.get("error") or result.get("reason") or "汇总推送失败")
        )
    db.add(
        PushRecord(
            kind="unified",
            channel=str(config.get("channel", "none")),
            cycle_id=batch.cycle_id,
            idempotency_key=batch.idempotency_key,
            batch_id=batch.id,
            status="success" if success else "failed",
            title=f"签到日报｜{batch.cycle_id}",
            body=summary,
            response=redact_text(json.dumps(result, ensure_ascii=False)[: settings.push_response_max_chars]),
            error=None if success else batch.error,
        )
    )
    enqueue_outbox(
        db,
        idempotency_key=make_idempotency_key("outbox-unified", batch.cycle_id),
        kind="unified",
        message=(
            f"统一汇总完成 cycle={batch.cycle_id} status={batch.status} "
            f"success={counts['success']} failed={counts['failed']} "
            f"skipped={counts['skipped']}"
        ),
    )
    # Physical cleanup of the full detail content is intentional and immediate.
    await db.execute(delete(PushPool).where(PushPool.cycle_id == batch.cycle_id))
    await db.commit()
    await drain_outbox()
    await asyncio.to_thread(
        ring_log.append_push,
        (
            f"统一汇总完成 cycle={batch.cycle_id} status={batch.status} "
            f"success={counts['success']} failed={counts['failed']} "
            f"skipped={counts['skipped']}"
        ),
        "INFO" if success else "ERROR",
        batch.id,
    )


async def _mark_noop(
    db: AsyncSession, batch: PushBatch, rows: list[PushPool]
) -> None:
    """All expected modules skipped: terminal no-op, no third-party call."""
    batch.status = BATCH_NOOP
    batch.success_count = 0
    batch.failed_count = 0
    batch.skipped_count = len(rows)
    batch.pending_count = 0
    batch.summary = _summary(batch.cycle_id, rows, {
        "success": 0, "failed": 0, "skipped": len(rows), "pending": 0
    })
    batch.details_cleared = True
    enqueue_outbox(
        db,
        idempotency_key=make_idempotency_key("outbox-noop", batch.cycle_id),
        kind="noop",
        message=f"全 skip 批次无需推送 cycle={batch.cycle_id} skipped={len(rows)}",
    )
    await db.execute(delete(PushPool).where(PushPool.cycle_id == batch.cycle_id))
    await db.commit()
    await drain_outbox()


def _summary(cycle_id: str, rows: list[PushPool], counts: dict[str, int]) -> str:
    lines = [
        f"### 签到日报｜{cycle_id}",
        f"- 预期：{len(rows)} 个模块",
        f"- 成功：{counts['success']}",
        f"- 失败：{counts['failed']}",
        f"- 跳过：{counts['skipped']}",
        f"- 未完成：{counts['pending']}",
        "",
    ]
    for row in rows:
        if row.status == POOL_SKIPPED and not settings.push_skip_notice:
            continue
        label = {
            POOL_SUCCESS: "成功",
            POOL_FAILED: "失败",
            POOL_SKIPPED: "跳过",
            POOL_PENDING: "未完成",
        }.get(row.status, row.status)
        detail = redact_text(row.message or row.details or "")
        lines.append(f"- {row.module_name}：{label}" + (f"（{detail}）" if detail else ""))
    return redact_text("\n".join(lines))


async def _send_supplement(
    module_id: int,
    module_key: str,
    module_name: str,
    cycle_id: str,
    status: str,
    message: str,
) -> None:
    if settings.push_after_flush_mode != "single":
        return
    try:
        async with SessionLocal() as db:
            config = await load_push_config(db)
    except PushConfigError as exc:
        logger.warning("补发单条读取推送配置失败：%s", exc)
        return
    if config["channel"] == "none":
        return
    variables = {
        "event": EVENT_LABELS.get("success" if status == "success" else "failure", status),
        "module_name": module_name,
        "module_key": module_key,
        "account": "—",
        "status": "成功" if status == "success" else "失败",
        "result": message,
        "duration": "—",
        "error": "" if status == "success" else message,
        "time": datetime.now(settings.timezone_info).strftime("%Y-%m-%d %H:%M:%S"),
        "summary": message,
        "details": f"批次 {cycle_id} 已汇总，补发本条手动补执行结果",
    }
    title = render_template(config["title_template"], variables)
    body = render_template(config["body_template"], variables)
    key = make_idempotency_key(
        "supplement", cycle_id, module_id, message, clock.time_ns()
    )
    result = await send_message(
        config["channel"],
        config["config"],
        title,
        body,
        idempotency_key=key,
    )
    async with SessionLocal() as db:
        db.add(
            PushRecord(
                kind="supplement",
                channel=str(config["channel"]),
                module_id=module_id,
                module_key=module_key,
                module_name=module_name,
                cycle_id=cycle_id,
                idempotency_key=key,
                status="success" if result.get("sent") else "failed",
                title=title,
                body=body,
                response=redact_text(
                    json.dumps(result, ensure_ascii=False)[: settings.push_response_max_chars]
                ),
                error=None
                if result.get("sent")
                else redact_text(str(result.get("error") or "")),
            )
        )
        await db.commit()
    await asyncio.to_thread(
        ring_log.append_push,
        (
            f"flush 后手动补发 cycle={cycle_id} module={module_key} "
            f"sent={bool(result.get('sent'))}"
        ),
        "INFO" if result.get("sent") else "ERROR",
    )


async def flush_due_batches() -> int:
    await drain_outbox()
    async with SessionLocal() as db:
        cycles = list(
            (
                await db.execute(
                    select(PushBatch.cycle_id).where(
                        PushBatch.status == BATCH_PENDING
                    )
                )
            ).scalars()
        )
    flushed = 0
    for cycle_id in cycles:
        try:
            if await maybe_flush_batch(cycle_id):
                flushed += 1
        except Exception:
            logger.exception("统一推送批次检查失败：%s", cycle_id)
    return flushed


async def list_batches(
    *, page: int, page_size: int, status: str | None = None
) -> tuple[list[PushBatch], int]:
    async with SessionLocal() as db:
        conditions = []
        if status:
            conditions.append(PushBatch.status == status)
        total = int(
            await db.scalar(
                select(func.count()).select_from(PushBatch).where(*conditions)
            )
            or 0
        )
        rows = (
            (
                await db.execute(
                    select(PushBatch)
                    .where(*conditions)
                    .order_by(PushBatch.created_at.desc(), PushBatch.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total


async def list_records(
    *, page: int, page_size: int, kind: str | None = None, status: str | None = None
) -> tuple[list[PushRecord], int]:
    async with SessionLocal() as db:
        conditions = []
        if kind:
            conditions.append(PushRecord.kind == kind)
        if status:
            conditions.append(PushRecord.status == status)
        total = int(
            await db.scalar(
                select(func.count()).select_from(PushRecord).where(*conditions)
            )
            or 0
        )
        rows = (
            (
                await db.execute(
                    select(PushRecord)
                    .where(*conditions)
                    .order_by(PushRecord.created_at.desc(), PushRecord.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total
