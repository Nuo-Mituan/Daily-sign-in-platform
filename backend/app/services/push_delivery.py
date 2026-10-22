"""Push delivery: summary rendering, sending, retrying, and auditing.

This module owns all outbound unified-push effects:

* rendering the daily summary through :mod:`push_summary`;
* retrying the configured HTTP channel with bounded exponential backoff;
* writing durable ``PushRecord`` rows and transactional outbox audit events;
* executing the main trigger and the timeout fallback after state has
  selected the batch.

It intentionally delegates batch selection, status transitions and pool CRUD
to ``push_state`` so that delivery never becomes the source of truth for the
unified-push state machine.
"""
from __future__ import annotations
import asyncio
import json
import time as clock
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from ..config import settings
from ..database import SessionLocal
from .push_lock import get_cycle_lock as _lock
from .push_plan import _timeout_at_for_cycle
from .push_plan import cycle_id_for
from ..models import (
    PushBatch,
    PushPool,
    PushRecord,
)
from ..timeutils import utcnow
from .push_outbox import drain as drain_outbox, enqueue as enqueue_outbox, make_idempotency_key
from .push_summary import render_summary
from .push import (
    EVENT_LABELS,
    PushConfigError,
    load_push_config,
    load_unified_settings,
    render_template,
    send_message,
)
from .redaction import redact_text
from .ring_log import ring_log
logger = logging.getLogger(__name__)


@dataclass
class SendOutcome:
    sent: bool
    channel: str | None = None
    response: object = None
    error: str | None = None
    reason: str | None = None

FLUSH_MAIN = "main"
FLUSH_TIMEOUT = "timeout"
from .push_state import (  # noqa: E402
    BatchStatus,
    set_batch_status,
    POOL_PENDING,
    POOL_SUCCESS,
    POOL_FAILED,
    POOL_SKIPPED,
    POOL_TIMEOUT,
    BATCH_PENDING,
    BATCH_NOOP,
    BATCH_SENT,
    BATCH_FAILED,
    BATCH_TIMEOUT,
    BATCH_EXPIRED,
    get_due_and_expire_batches,
)
# ---------------------------------------------------------------------------
# Post-flush supplement delivery
# ---------------------------------------------------------------------------


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
    async with SessionLocal() as db:
        record = PushRecord(
            kind="supplement",
            channel=str(config["channel"]),
            module_id=module_id,
            module_key=module_key,
            module_name=module_name,
            cycle_id=cycle_id,
            idempotency_key=key,
            status="pending",
            title=title,
            body=body,
        )
        db.add(record)
        await db.commit()
        record_id = record.id
    result = await send_message(
        config["channel"],
        config["config"],
        title,
        body,
        idempotency_key=key,
    )
    async with SessionLocal() as db:
        stored = await db.get(PushRecord, record_id)
        if stored is not None:
            stored.status = "success" if result.get("sent") else "failed"
            stored.response = redact_text(
                json.dumps(result, ensure_ascii=False)[: settings.push_response_max_chars]
            )
            stored.error = (
                None
                if result.get("sent")
                else redact_text(str(result.get("error") or ""))
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
async def recover_pending_supplements() -> int:
    """Re-send stale pending supplement records with short transactions."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with SessionLocal() as db:
        rows = list(
            (
                await db.execute(
                    select(PushRecord).where(
                        PushRecord.kind == "supplement",
                        PushRecord.status == "pending",
                        PushRecord.created_at < cutoff,
                    ).limit(50)
                )
            ).scalars()
        )
        if not rows:
            return 0
        try:
            config = await load_push_config(db)
        except Exception:
            logger.exception(
                "推送恢复读取配置失败，本轮跳过，PENDING 记录下轮重试"
            )
            return 0
        if config["channel"] == "none":
            return 0
        pending = [
            (r.id, r.title or "", r.body or "", r.idempotency_key or "",
             r.created_at)
            for r in rows
        ]
    retried = 0
    for record_id, title, body, key, created_at in pending:
        try:
            result = await send_message(
                config["channel"], config["config"], title, body,
                idempotency_key=key,
            )
            async with SessionLocal() as db:
                row = await db.get(PushRecord, record_id)
                if row is None:
                    continue
                row.response = redact_text(
                    json.dumps(result, ensure_ascii=False)[: settings.push_response_max_chars]
                )
                if result.get("sent"):
                    row.status = "success"
                    row.error = None
                elif datetime.now(timezone.utc) - created_at > timedelta(hours=24):
                    row.status = "failed"
                    row.error = redact_text(str(result.get("error") or "重发超过 24 小时"))
                await db.commit()
            retried += 1
        except Exception:
            logger.exception("补发 PENDING 记录恢复失败 id=%s", record_id)
            continue
    return retried


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
# ---------------------------------------------------------------------------
# Main / timeout flush execution
# ---------------------------------------------------------------------------


async def _load_push_config() -> dict[str, object]:
    try:
        async with SessionLocal() as config_db:
            return await load_push_config(config_db)
    except PushConfigError as exc:
        logger.warning("推送配置预加载失败，按未配置处理：%s", exc)
        return {"channel": "none", "config": {}}


async def flush_batch(
    cycle_id: str | None = None, *, mode: str = FLUSH_MAIN
) -> bool:
    """Main trigger or timeout fallback; never auto-flushes on result arrival."""
    cycle_id = cycle_id or cycle_id_for()
    config = await _load_push_config()
    async with _lock(cycle_id):
        async with SessionLocal() as db:
            batch = await db.scalar(
                select(PushBatch).where(PushBatch.cycle_id == cycle_id)
            )
            if batch is None:
                return False
            now = datetime.now(timezone.utc)
            if mode == FLUSH_MAIN:
                if batch.status != BATCH_PENDING:
                    return False
                if batch.trigger_at is not None and now < batch.trigger_at.astimezone(timezone.utc):
                    return False
            else:
                if batch.status in {BATCH_SENT, BATCH_TIMEOUT, BATCH_EXPIRED}:
                    return False
                if batch.timeout_attempted_at is not None:
                    return False
                if batch.timeout_at is None or now < batch.timeout_at.astimezone(timezone.utc):
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
                from .push_state import _mark_noop
                noop_event = await _mark_noop(db, batch, [])
                batch.summary = render_summary(batch.cycle_id, [], {
                    "success": 0, "failed": 0, "skipped": 0,
                    "pending": 0, "timeout": 0,
                })
                enqueue_outbox(
                    db,
                    idempotency_key=make_idempotency_key(
                        "outbox-noop", noop_event["cycle_id"]
                    ),
                    kind="noop",
                    message=f"空批次无需推送 cycle={noop_event['cycle_id']}",
                )
                await db.commit()
                await drain_outbox()
                return False
            has_executing = any(row.status != POOL_SKIPPED for row in rows)
            if not has_executing:
                from .push_state import _mark_noop
                noop_summary = render_summary(batch.cycle_id, rows, {
                    "success": 0, "failed": 0, "skipped": len(rows),
                    "pending": 0, "timeout": 0,
                })
                noop_event = await _mark_noop(db, batch, rows)
                batch.summary = noop_summary
                enqueue_outbox(
                    db,
                    idempotency_key=make_idempotency_key(
                        "outbox-noop", noop_event["cycle_id"]
                    ),
                    kind="noop",
                    message=(
                        f"全 skip 批次无需推送 cycle={noop_event['cycle_id']} "
                        f"skipped={noop_event['skipped']}"
                    ),
                )
                await db.commit()
                await drain_outbox()
                return False
            pending = [row for row in rows if row.status == POOL_PENDING]
            if pending:
                for row in pending:
                    if mode == FLUSH_TIMEOUT:
                        row.status = POOL_TIMEOUT
                        row.message = "推送超时（兜底触发）"
                        row.details = "到达用户配置的超时时间，模块仍未完成"
                    else:
                        row.status = POOL_FAILED
                        row.message = "主触发时仍未完成"
                        row.details = "到达统一推送计划时间，模块仍未完成"
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
                "timeout": sum(1 for row in rows if row.status == POOL_TIMEOUT),
            }
            await _flush_locked(db, batch, rows, counts, mode, config)
            return True
async def maybe_flush_batch(cycle_id: str | None = None) -> bool:
    """Backward-compatible main flush; only runs after trigger_at."""
    return await flush_batch(cycle_id, mode=FLUSH_MAIN)
# The caller has already selected and validated pending rows.
# This function only renders and sends the summary, then delegates terminal
# persistence to _finalize_flush.


async def _flush_locked(
    db: AsyncSession,
    batch: PushBatch,
    rows: list[PushPool],
    counts: dict[str, int],
    mode: str,
    config: dict[str, object],
) -> None:
    if batch.status not in {BATCH_PENDING, BATCH_FAILED}:
        return
    timeout = mode == FLUSH_TIMEOUT
    summary = render_summary(batch.cycle_id, rows, counts, timeout=timeout)
    await _persist_summary(db, batch, counts, summary)
    _config, result = await _send_summary(
        db, batch, summary, config=config, timeout=timeout
    )
    await _finalize_flush(
        db, batch, counts, summary, _config, result, mode=mode
    )
# Persist counts and summary before the external HTTP call so operators can
# inspect what was attempted even if the process crashes mid-send.


async def _persist_summary(
    db: AsyncSession,
    batch: PushBatch,
    counts: dict[str, int],
    summary: str,
) -> None:
    batch.success_count = counts["success"]
    batch.failed_count = counts["failed"]
    batch.skipped_count = counts["skipped"]
    batch.pending_count = 0
    batch.timeout_count = counts["timeout"]
    batch.summary = summary
    await db.commit()
# ---------------------------------------------------------------------------
# Summary transmission with bounded retry
# ---------------------------------------------------------------------------


# Delivery invariants:
# 1. Never mutate batch status directly; use push_state.set_batch_status.
# 2. Never delete push_pool rows before the outbox audit is committed.
# 3. Retries reuse the stable idempotency key to avoid duplicate provider sends.
# 4. The main trigger is terminal once sent; timeout is only a fallback.
# 5. Exceptions are logged with stack traces; they are never silently swallowed.
# 6. Every external send leaves a durable PushRecord for operators.
# 7. Pool cleanup is intentionally last to preserve retryable data on failure.
# 8. Timeout fallback must never run after a successful main trigger.
# 9. Delivery reads batches selected by state; it does not scan raw tables.
# 10. All time comparisons use timezone-aware UTC datetimes.

async def _send_summary(
    db: AsyncSession, batch: PushBatch, summary: str, *,
    config: dict[str, object], timeout: bool = False
) -> tuple[dict[str, object], SendOutcome]:
    """Send the unified summary with retries; returns (config, outcome)."""
    result = SendOutcome(False, error="未配置推送渠道")
    attempts = max(1, settings.push_retry_attempts)
    try:
        if config["channel"] == "none":
            raise PushConfigError("未配置全局推送渠道")
        title = (
            f"⚠️ 部分模块推送超时（兜底触发）｜{batch.cycle_id}"
            if timeout
            else f"签到日报｜{batch.cycle_id}"
        )
        for attempt in range(attempts):
            batch.retry_count = attempt
            batch.last_attempt_at = utcnow()
            await db.commit()
            raw_result = await send_message(
                config["channel"],
                config["config"],
                title,
                summary,
                idempotency_key=batch.idempotency_key,
            )
            result = SendOutcome(
                sent=bool(raw_result.get("sent")),
                channel=raw_result.get("channel"),
                response=raw_result.get("response"),
                error=raw_result.get("error"),
                reason=raw_result.get("reason"),
            )
            await asyncio.to_thread(
                ring_log.append_push,
                (
                    f"统一汇总 attempt={attempt + 1}/{attempts} "
                    f"cycle={batch.cycle_id} sent={result.sent} "
                    f"error={result.error or result.reason or ''}"
                ),
                "INFO" if result.sent else "WARNING",
                batch.id,
            )
            if result.sent:
                break
            if attempt + 1 < attempts:
                await asyncio.sleep(settings.push_retry_base_seconds * (2 ** attempt))
    except PushConfigError as exc:
        logger.warning("推送配置错误 cycle=%s: %s", batch.cycle_id, exc)
        result = SendOutcome(False, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("统一推送发送异常 cycle=%s", batch.cycle_id)
        result = SendOutcome(False, error=f"{type(exc).__name__}: {exc}")
    return config, result
# ---------------------------------------------------------------------------
# Terminal status, audit record and pool cleanup
# ---------------------------------------------------------------------------


# Terminal state transition, durable PushRecord and pool cleanup live here.
# The state module still owns all status writes through set_batch_status.


async def _finalize_flush(
    db: AsyncSession,
    batch: PushBatch,
    counts: dict[str, int],
    summary: str,
    config: dict[str, object],
    result: SendOutcome,
    *,
    mode: str,
) -> None:
    timeout = mode == FLUSH_TIMEOUT
    success = result.sent
    if timeout:
        batch.timeout_attempted_at = utcnow()
        set_batch_status(batch, BatchStatus.TIMEOUT if success else BatchStatus.FAILED)
    else:
        set_batch_status(batch, BatchStatus.SENT if success else BatchStatus.FAILED)
    batch.flushed_at = utcnow()
    batch.timeout_count = counts["timeout"]
    if success:
        batch.error = None
        batch.details_cleared = True
    else:
        batch.error = redact_text(
            str(result.error or result.reason or "汇总推送失败")
        )
        batch.details_cleared = False
    title = (
        f"⚠️ 部分模块推送超时（兜底触发）｜{batch.cycle_id}"
        if timeout
        else f"签到日报｜{batch.cycle_id}"
    )
    db.add(
        PushRecord(
            kind="unified",
            channel=str(config.get("channel", "none")),
            cycle_id=batch.cycle_id,
            idempotency_key=make_idempotency_key(
                "unified-record", batch.cycle_id, mode, clock.time_ns()
            ),
            batch_id=batch.id,
            status="success" if success else "failed",
            title=title,
            body=summary,
            response=redact_text(
                json.dumps(result.__dict__, ensure_ascii=False)[
                    : settings.push_response_max_chars
                ]
            ),
            error=None if success else batch.error,
        )
    )
    enqueue_outbox(
        db,
        idempotency_key=make_idempotency_key(
            "outbox-unified", batch.cycle_id, mode, clock.time_ns()
        ),
        kind="unified",
        message=(
            f"统一汇总完成 cycle={batch.cycle_id} mode={mode} status={batch.status} "
            f"success={counts['success']} failed={counts['failed']} "
            f"skipped={counts['skipped']} timeout={counts['timeout']}"
        ),
    )
    if success or timeout:
        await db.execute(delete(PushPool).where(PushPool.cycle_id == batch.cycle_id))
    await db.commit()
    await drain_outbox()
    await asyncio.to_thread(
        ring_log.append_push,
        (
            f"统一汇总完成 cycle={batch.cycle_id} mode={mode} status={batch.status} "
            f"success={counts['success']} failed={counts['failed']} "
            f"skipped={counts['skipped']} timeout={counts['timeout']}"
        ),
        "INFO" if success else "ERROR",
        batch.id,
    )
# ---------------------------------------------------------------------------
# Periodic delivery sweep (selection is delegated to state)
# ---------------------------------------------------------------------------


@dataclass
class FlushStats:
    sent: int = 0
    noop: int = 0
    expired: int = 0
    failed: int = 0
    retried: int = 0

    @property
    def total_processed(self) -> int:
        return self.sent + self.noop + self.expired + self.failed


async def flush_due_batches() -> FlushStats:
    """Sweep persisted batches and execute due main/timeout deliveries."""
    await drain_outbox()
    now = datetime.now(timezone.utc)
    from .push_state import cleanup_cross_day_pending
    events = await cleanup_cross_day_pending()
    stats = FlushStats()
    if events:
        for event in events:
            if event["kind"] == "noop":
                stats.noop += 1
            else:
                stats.expired += 1
        await drain_outbox()
    batches = await get_due_and_expire_batches()
    for batch, all_skipped in batches:
        cycle_id = batch.cycle_id
        try:
            async with SessionLocal() as db:
                stored = await db.scalar(
                    select(PushBatch).where(PushBatch.cycle_id == cycle_id)
                )
                if stored is None:
                    continue
                timeout_settings = await load_unified_settings(db)
                computed_timeout = _timeout_at_for_cycle(
                    cycle_id, stored.trigger_at, timeout_settings
                )
                if stored.timeout_at != computed_timeout:
                    stored.timeout_at = computed_timeout
                    await db.commit()
                trigger_at = stored.trigger_at
                timeout_at = stored.timeout_at
                status = stored.status
            if all_skipped and status == BATCH_PENDING:
                await flush_batch(cycle_id, mode=FLUSH_MAIN)
                async with SessionLocal() as db:
                    stored = await db.scalar(
                        select(PushBatch).where(PushBatch.cycle_id == cycle_id)
                    )
                    final_status = stored.status if stored else None
                if final_status == BATCH_NOOP:
                    stats.noop += 1
                else:
                    logger.warning("all_skipped flush did not reach NOOP: %s", cycle_id)
                    stats.failed += 1
                continue
            main_attempted = False
            main_success = False
            if (
                status == BATCH_PENDING
                and trigger_at is not None
                and now >= trigger_at.astimezone(timezone.utc)
            ):
                main_attempted = True
                main_success = await flush_batch(cycle_id, mode=FLUSH_MAIN)
                async with SessionLocal() as db:
                    stored = await db.scalar(
                        select(PushBatch).where(PushBatch.cycle_id == cycle_id)
                    )
                    status = stored.status if stored else None
            if (
                status in {BATCH_PENDING, BATCH_FAILED}
                and timeout_at is not None
                and now >= timeout_at.astimezone(timezone.utc)
            ):
                stats.retried += 1
                if await flush_batch(cycle_id, mode=FLUSH_TIMEOUT):
                    stats.sent += 1
                else:
                    stats.failed += 1
            elif main_attempted:
                if main_success:
                    stats.sent += 1
                else:
                    stats.failed += 1
        except Exception:
            stats.failed += 1
            logger.exception("统一推送批次检查失败：%s", cycle_id)
    await drain_outbox()
    return stats
