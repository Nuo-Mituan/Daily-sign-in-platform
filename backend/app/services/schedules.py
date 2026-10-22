"""Random schedule generation and persistence.

This service owns the ModuleSchedule rows.  APScheduler registration lives in
``scheduler.py``; keeping date math and DB writes here keeps both pieces small
and testable.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import SessionLocal
from ..models import Module, ModuleSchedule
from ..scheduling import (
    ScheduleError,
    current_period_start,
    midpoint_scheduled_at,
    period_start_for,
    random_scheduled_at,
    schedule_window,
    validate_schedule,
)
from ..timeutils import utcnow
from .lock_registry import KeyLockRegistry

logger = logging.getLogger(__name__)

SCHEDULE_PENDING = "pending"
SCHEDULE_FALLBACK = "fallback"
SCHEDULE_RUNNING = "running"
SCHEDULE_EXECUTED = "executed"
SCHEDULE_MISSED = "missed"
SCHEDULE_CANCELLED = "cancelled"
SCHEDULE_MISFIRE_GRACE_SECONDS = 300

_schedule_locks = KeyLockRegistry[int](max_unlocked=256)


def _lock_for(module_id: int) -> asyncio.Lock:
    return _schedule_locks.get(module_id)


def _validate_module_schedule(module: Module) -> tuple[str, str, str, str]:
    return validate_schedule(
        module.start_time,
        module.end_time,
        module.repeat_cycle,
        module.repeat_sub_value,
    )


def _local_now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(settings.timezone_info)


async def get_schedule_for_period(
    db: AsyncSession, module_id: int, period_start: date
) -> ModuleSchedule | None:
    return await db.scalar(
        select(ModuleSchedule).where(
            ModuleSchedule.module_id == module_id,
            ModuleSchedule.period_start == period_start,
        )
    )


async def current_schedule(
    db: AsyncSession, module: Module, now: datetime | None = None
) -> ModuleSchedule | None:
    try:
        start, _end, cycle, sub_value = _validate_module_schedule(module)
    except ScheduleError:
        return None
    _ = start
    period = period_start_for(cycle, _local_now(now).date(), sub_value)
    return await get_schedule_for_period(db, module.id, period)


def _new_schedule(
    module: Module,
    period: date,
    scheduled_at: datetime,
    *,
    status: str,
    source: str,
    fallback_used: bool = False,
    note: str | None = None,
) -> ModuleSchedule:
    return ModuleSchedule(
        module_id=module.id,
        period_start=period,
        scheduled_at=scheduled_at,
        status=status,
        source=source,
        fallback_used=fallback_used,
        generated_at=utcnow(),
        note=note,
    )


async def _ensure_current_locked(
    module_id: int,
    *,
    now: datetime | None = None,
    only_if_enabled: bool = True,
) -> ModuleSchedule | None:
    current_local = _local_now(now)
    async with SessionLocal() as db:
        module = await db.get(Module, module_id)
        if module is None:
            return None
        if only_if_enabled and (not module.enabled or module.load_error):
            return None
        try:
            start_time, end_time, cycle, sub_value = _validate_module_schedule(module)
        except ScheduleError as exc:
            logger.warning("模块 %s 的随机时间配置无效：%s", module.key, exc)
            return None

        period = period_start_for(cycle, current_local.date(), sub_value)
        row = await get_schedule_for_period(db, module_id, period)

        if row is not None:
            if row.status in {SCHEDULE_EXECUTED, SCHEDULE_RUNNING, SCHEDULE_MISSED}:
                return row
            if row.status == SCHEDULE_CANCELLED:
                if current_local.date() != period or current_local >= schedule_window(
                    period, start_time, end_time, settings.timezone_info
                )[1]:
                    return row
                scheduled_at = random_scheduled_at(
                    period,
                    start_time,
                    end_time,
                    settings.timezone_info,
                    now=current_local,
                    min_lead_seconds=settings.schedule_min_lead_seconds,
                )
                if scheduled_at is None:
                    return row
                row.scheduled_at = scheduled_at
                row.status = SCHEDULE_PENDING
                row.source = "auto"
                row.fallback_used = False
                row.generated_at = utcnow()
                row.executed_at = None
                row.note = "配置变更后重新生成"
                await db.commit()
                await db.refresh(row)
                return row
            if row.status in {SCHEDULE_PENDING, SCHEDULE_FALLBACK}:
                now_utc = datetime.now(timezone.utc)
                if row.scheduled_at > now_utc:
                    return row
                # Allow APScheduler's misfire grace window; a late startup or a
                # concurrent hourly retry must not cancel a job that is about to
                # fire. After the grace window, mark the period as missed.
                if (now_utc - row.scheduled_at).total_seconds() <= SCHEDULE_MISFIRE_GRACE_SECONDS:
                    return row
                row.status = SCHEDULE_MISSED
                row.note = "执行时间已过，未触发执行"
                await db.commit()
                await db.refresh(row)
                return row
            return row

        if current_local.date() != period:
            return None

        _start_dt, end_dt = schedule_window(
            period, start_time, end_time, settings.timezone_info
        )
        if current_local >= end_dt:
            return None

        scheduled_at = random_scheduled_at(
            period,
            start_time,
            end_time,
            settings.timezone_info,
            now=current_local,
            min_lead_seconds=settings.schedule_min_lead_seconds,
        )
        if scheduled_at is None:
            return None

        row = _new_schedule(
            module,
            period,
            scheduled_at,
            status=SCHEDULE_PENDING,
            source="auto",
        )
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return await get_schedule_for_period(db, module_id, period)
        await db.refresh(row)
        return row


async def ensure_current_schedule(
    module_id: int,
    *,
    now: datetime | None = None,
    only_if_enabled: bool = True,
) -> ModuleSchedule | None:
    lock = _lock_for(module_id)
    async with lock:
        return await _ensure_current_locked(
            module_id, now=now, only_if_enabled=only_if_enabled
        )


async def regenerate_current_schedule(
    module_id: int, *, now: datetime | None = None
) -> ModuleSchedule:
    """Manually replace the current period's random time (before execution)."""
    lock = _lock_for(module_id)
    async with lock:
        current_local = _local_now(now)
        async with SessionLocal() as db:
            module = await db.get(Module, module_id)
            if module is None:
                raise ScheduleError("模块不存在")
            if not module.enabled or module.load_error:
                raise ScheduleError("请先启用模块并确保模块加载正常")
            try:
                start_time, end_time, cycle, sub_value = _validate_module_schedule(module)
            except ScheduleError as exc:
                raise ScheduleError(f"随机时间配置无效：{exc}") from exc

            period = period_start_for(cycle, current_local.date(), sub_value)
            if current_local.date() != period:
                raise ScheduleError("当前不是本周期执行日，无法重新生成")
            _start_dt, end_dt = schedule_window(
                period, start_time, end_time, settings.timezone_info
            )
            if current_local >= end_dt:
                raise ScheduleError("本期随机时间窗口已结束，无法重新生成")

            row = await get_schedule_for_period(db, module.id, period)
            if row is not None and row.status in {
                SCHEDULE_RUNNING,
                SCHEDULE_EXECUTED,
            }:
                raise ScheduleError("本期任务已执行或正在执行，不能重新生成")

            scheduled_at = random_scheduled_at(
                period,
                start_time,
                end_time,
                settings.timezone_info,
                now=current_local,
                min_lead_seconds=settings.schedule_min_lead_seconds,
            )
            if scheduled_at is None:
                raise ScheduleError("无法在剩余时间窗内生成新的执行时间")

            if row is None:
                row = _new_schedule(
                    module,
                    period,
                    scheduled_at,
                    status=SCHEDULE_PENDING,
                    source="manual",
                    note="手动重新生成",
                )
                db.add(row)
            else:
                row.scheduled_at = scheduled_at
                row.status = SCHEDULE_PENDING
                row.source = "manual"
                row.fallback_used = False
                row.generated_at = utcnow()
                row.executed_at = None
                row.note = "手动重新生成"
            await db.commit()
            await db.refresh(row)
            return row


async def apply_fallback(
    module_id: int, *, now: datetime | None = None
) -> tuple[ModuleSchedule | None, bool]:
    """Create a midpoint schedule if no schedule exists for the current period.

    Returns (schedule, created).  The caller is responsible for sending the
    "random schedule generation failed" notification when created is True.
    """
    lock = _lock_for(module_id)
    async with lock:
        current_local = _local_now(now)
        async with SessionLocal() as db:
            module = await db.get(Module, module_id)
            if module is None or not module.enabled or module.load_error:
                return None, False
            try:
                start_time, end_time, cycle, sub_value = _validate_module_schedule(module)
            except ScheduleError:
                return None, False

            period = period_start_for(cycle, current_local.date(), sub_value)
            if current_local.date() != period:
                return None, False
            fallback_at = midpoint_scheduled_at(
                period, start_time, end_time, settings.timezone_info
            )
            existing = await get_schedule_for_period(db, module.id, period)
            if existing is not None and existing.status not in {
                SCHEDULE_CANCELLED,
                SCHEDULE_MISSED,
            }:
                return existing, False

            _start_dt, end_dt = schedule_window(
                period, start_time, end_time, settings.timezone_info
            )
            if current_local >= end_dt:
                return existing, False
            effective_at = fallback_at
            if effective_at <= current_local:
                effective_at = current_local + timedelta(
                    seconds=max(1, settings.schedule_min_lead_seconds)
                )

            if existing is None:
                row = _new_schedule(
                    module,
                    period,
                    effective_at.astimezone(timezone.utc),
                    status=SCHEDULE_FALLBACK,
                    source="fallback",
                    fallback_used=True,
                    note="随机时间生成失败，使用时间窗中点兜底",
                )
                db.add(row)
            else:
                row = existing
                row.scheduled_at = effective_at.astimezone(timezone.utc)
                row.status = SCHEDULE_FALLBACK
                row.source = "fallback"
                row.fallback_used = True
                row.generated_at = utcnow()
                row.executed_at = None
                row.note = "随机时间生成失败，使用时间窗中点兜底"
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                return await get_schedule_for_period(db, module_id, period), False
            await db.refresh(row)
            return row, True


async def claim_schedule_for_execution(schedule_id: int) -> bool:
    """Atomically claim a pending/fallback row.

    Two APScheduler jobs may race after a reschedule (or an hourly recovery).
    Only the caller that flips the row to ``running`` is allowed to execute.
    """
    async with SessionLocal() as db:
        result = await db.execute(
            update(ModuleSchedule)
            .where(
                ModuleSchedule.id == schedule_id,
                ModuleSchedule.status.in_([SCHEDULE_PENDING, SCHEDULE_FALLBACK]),
            )
            .values(status=SCHEDULE_RUNNING)
        )
        await db.commit()
        return result.rowcount == 1




async def mark_schedule_finished(
    schedule_id: int, *, status: str = SCHEDULE_EXECUTED, note: str | None = None
) -> None:
    async with SessionLocal() as db:
        row = await db.get(ModuleSchedule, schedule_id)
        if row is None:
            return
        row.status = status
        row.executed_at = utcnow()
        if note:
            row.note = note[:1000]
        await db.commit()


async def cancel_current_pending(module_id: int, note: str = "配置变更") -> None:
    lock = _lock_for(module_id)
    async with lock:
        async with SessionLocal() as db:
            module = await db.get(Module, module_id)
            if module is None:
                return
            try:
                _start, _end, cycle, sub_value = _validate_module_schedule(module)
            except ScheduleError:
                return
            period = period_start_for(cycle, _local_now().date(), sub_value)
            row = await get_schedule_for_period(db, module_id, period)
            if row is not None and row.status in {
                SCHEDULE_PENDING,
                SCHEDULE_FALLBACK,
            }:
                row.status = SCHEDULE_CANCELLED
                row.note = note[:1000]
                await db.commit()


async def cancel_pending_for_module(
    module_id: int, note: str = "调度配置变更，旧计划已取消"
) -> int:
    """Cancel all pending/fallback rows for a module (used on schedule edits)."""
    lock = _lock_for(module_id)
    async with lock:
        async with SessionLocal() as db:
            rows = (
                (
                    await db.execute(
                        select(ModuleSchedule).where(
                            ModuleSchedule.module_id == module_id,
                            ModuleSchedule.status.in_(
                                [SCHEDULE_PENDING, SCHEDULE_FALLBACK]
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                row.status = SCHEDULE_CANCELLED
                row.note = note[:1000]
            if rows:
                await db.commit()
            return len(rows)


async def mark_stale_running_schedules() -> int:
    """A service restart orphaned any 'running' schedule rows."""
    async with SessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(ModuleSchedule).where(
                        ModuleSchedule.status == SCHEDULE_RUNNING
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.status = SCHEDULE_MISSED
            row.note = "服务重启，执行状态丢失"
        if rows:
            await db.commit()
        return len(rows)


def schedule_to_dict(row: ModuleSchedule | None) -> dict[str, object] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "period_start": row.period_start,
        "scheduled_at": row.scheduled_at,
        "status": row.status,
        "source": row.source,
        "fallback_used": row.fallback_used,
        "generated_at": row.generated_at,
        "executed_at": row.executed_at,
        "note": row.note,
    }


async def current_period_date(module: Module, now: datetime | None = None) -> date:
    return current_period_start(
        module.repeat_cycle or "daily",
        settings.timezone_info,
        now,
        module.repeat_sub_value,
    )
