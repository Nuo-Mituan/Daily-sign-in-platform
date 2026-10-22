"""Facade for unified-push public API."""

from __future__ import annotations

from datetime import datetime
import logging

from .push_delivery import (
    FLUSH_MAIN,
    FLUSH_TIMEOUT,
    _supplement_after_flush,
    flush_batch,
    flush_due_batches,
    maybe_flush_batch,
)
from .push_plan import (
    _timeout_at_for_cycle,
    business_date,
    configure_daily_batch as _configure_daily_batch,
    cycle_id_for,
    latest_trigger,
)
from ..database import SessionLocal
from .push import load_unified_settings
from .push_lock import get_cycle_lock as _lock
from .push_state import (
    BATCH_EXPIRED,
    BATCH_FAILED,
    BATCH_NOOP,
    BATCH_PENDING,
    BATCH_SENT,
    BATCH_TIMEOUT,
    POOL_FAILED,
    POOL_PENDING,
    POOL_SKIPPED,
    POOL_SUCCESS,
    POOL_TIMEOUT,
    ensure_batch,
    get_scheduled_times,
    list_batches,
    persist_schedule,
    apply_or_probe,
    list_records,
)


logger = logging.getLogger(__name__)


async def _remove_unified_job(cycle_id: str) -> None:
    from .scheduler import scheduler_service

    scheduler_service.remove_unified_main_job(cycle_id)


async def _get_timeout_settings() -> dict[str, object]:
    async with SessionLocal() as db:
        return await load_unified_settings(db)


async def calculate_unified_trigger_at(cycle_id: str) -> datetime | None:
    times = await get_scheduled_times(cycle_id)
    return latest_trigger(times)


async def configure_daily_batch(cycle_id: str | None = None):
    cycle_id = cycle_id or cycle_id_for()
    batch = await ensure_batch(cycle_id)
    if batch is None:
        return None
    times = await get_scheduled_times(cycle_id)
    settings_data = await _get_timeout_settings()
    plan = _configure_daily_batch(cycle_id, times, settings_data)
    batch = await persist_schedule(
        cycle_id, plan["trigger_at"], plan["timeout_at"]
    )
    await _remove_unified_job(cycle_id)
    return batch


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
    async with _lock(cycle_id):
        async with SessionLocal() as db:
            decision = await apply_or_probe(
                db,
                cycle_id,
                module_id,
                {
                    "status": status,
                    "message": message,
                    "details": details,
                    "trigger": trigger,
                },
            )
    if not decision.applied:
        if decision.reject_reason == "expired":
            logger.warning("拒绝过期批次迟到结果 cycle=%s module=%s", cycle_id, module_id)
            return
        if decision.supplement is not None:
            await _supplement_after_flush(
                decision.supplement.module_id,
                decision.supplement.module_key,
                decision.supplement.module_name,
                cycle_id,
                trigger,
                status,
                message,
            )


__all__ = [
    "BATCH_EXPIRED", "BATCH_FAILED", "BATCH_NOOP", "BATCH_PENDING",
    "BATCH_SENT", "BATCH_TIMEOUT", "FLUSH_MAIN", "FLUSH_TIMEOUT",
    "POOL_FAILED", "POOL_PENDING", "POOL_SKIPPED", "POOL_SUCCESS",
    "POOL_TIMEOUT", "_timeout_at_for_cycle", "business_date",
    "calculate_unified_trigger_at", "configure_daily_batch", "cycle_id_for",
    "ensure_batch", "flush_batch", "flush_due_batches", "list_batches",
    "list_records", "maybe_flush_batch", "record_unified_result",
]
