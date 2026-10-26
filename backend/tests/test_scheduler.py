"""Tests for APScheduler dynamic one-shot jobs (execution / plan / fallback)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from app.config import settings
from app.database import dispose_db, init_db
from app.models import Module, ModuleSchedule
from app.services.bootstrap import initialize_modules
from app.services import scheduler as scheduler_module
from app.services.scheduler import scheduler_service


def future_window() -> tuple[str, str]:
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    start = now + timedelta(minutes=2)
    end = now + timedelta(minutes=4)
    if end.date() != now.date():
        return "00:00", "23:59"
    return start.strftime("%H:%M"), end.strftime("%H:%M")


@pytest.mark.asyncio
async def test_dynamic_schedule_execution_and_fallback_jobs(monkeypatch) -> None:
    await init_db()
    await initialize_modules()
    from app.database import SessionLocal

    async with SessionLocal() as db:
        module = await db.scalar(select(Module).where(Module.key == "demo_checkin"))
        assert module is not None
        start, end = future_window()
        module.start_time = start
        module.end_time = end
        module.repeat_cycle = "daily"
        module.enabled = True
        await db.commit()
        module_id = module.id

    scheduler_service.start()
    try:
        await scheduler_service.refresh_module(module_id)
        scheduler = scheduler_service.scheduler
        assert scheduler is not None
        plan_job = scheduler.get_job(f"module:{module_id}:plan")
        exec_job = scheduler.get_job(f"module:{module_id}:exec")
        assert plan_job is not None, "缺少下个周期计划任务"
        assert exec_job is not None, "缺少本期执行任务"
        run_date = exec_job.trigger.run_date
        assert run_date > datetime.now(timezone.utc)
        assert plan_job.trigger.run_date.hour == 0

        # Force generation failure; a midpoint watchdog must be registered.
        async def failing_ensure(*_args, **_kwargs):
            raise RuntimeError("simulated generation failure")

        monkeypatch.setattr(
            scheduler_module, "ensure_current_schedule", failing_ensure
        )
        await scheduler_service.refresh_module(module_id)
        fallback_job = scheduler.get_job(f"module:{module_id}:fallback")
        assert fallback_job is not None, "随机时间生成失败时缺少兜底任务"
        assert scheduler.get_job(f"module:{module_id}:exec") is None
    finally:
        scheduler_service.unschedule_module(module_id)
        scheduler_service.shutdown()
        async with SessionLocal() as db:
            module = await db.get(Module, module_id)
            if module is not None:
                module.enabled = False
                await db.execute(
                    delete(ModuleSchedule).where(
                        ModuleSchedule.module_id == module_id
                    )
                )
                await db.commit()
        await dispose_db()


@pytest.mark.asyncio
async def test_scheduled_job_runs_module_and_updates_schedule() -> None:
    await init_db()
    from app.services.bootstrap import seed_admin

    await seed_admin()
    await initialize_modules()
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import delete, select

    from zoneinfo import ZoneInfo

    from app.config import settings
    from app.crypto import EncryptionContext, parameter_cipher
    from app.database import SessionLocal
    from app.models import ExecutionLog, Module, ModuleSchedule

    async with SessionLocal() as db:
        module = await db.scalar(select(Module).where(Module.key == "demo_checkin"))
        assert module is not None
        await db.execute(
            delete(ModuleSchedule).where(ModuleSchedule.module_id == module.id)
        )
        module.start_time = "00:00"
        module.end_time = "23:59"
        module.repeat_cycle = "daily"
        module.enabled = True
        module.push_enabled = False
        module.params_encrypted = parameter_cipher.encrypt(
            {
                "account": "scheduler@example.com",
                "password": "secret",
                "server": "cn",
                "mode": "success",
                "retries": 1,
                "verbose": False,
            },
            EncryptionContext(1, module.key),
        )
        scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=4)
        row = ModuleSchedule(
            module_id=module.id,
            period_start=datetime.now(ZoneInfo(settings.timezone)).date(),
            scheduled_at=scheduled_at,
            status="pending",
            source="auto",
            generated_at=datetime.now(timezone.utc),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        row_id = row.id
        module_id = module.id

    scheduler_service.start()
    try:
        await scheduler_service.refresh_module(module_id)
        assert scheduler_service.scheduler.get_job(f"module:{module_id}:exec") is not None  # type: ignore[union-attr]  # TODO(v1.0.3): fix typing
        final_row = None
        log = None
        for _ in range(40):
            await asyncio.sleep(0.5)
            async with SessionLocal() as db:
                final_row = await db.get(ModuleSchedule, row_id)
                log = await db.scalar(
                    select(ExecutionLog)
                    .where(ExecutionLog.module_id == module_id)
                    .order_by(ExecutionLog.id.desc())
                )
            if final_row is not None and final_row.status == "executed" and log:
                break
        assert final_row is not None
        assert final_row.status == "executed", final_row.status
        assert log is not None and log.status == "success", log.status if log else None
        assert log.trigger == "schedule"
    finally:
        scheduler_service.unschedule_module(module_id)
        scheduler_service.shutdown()
        async with SessionLocal() as db:
            module = await db.get(Module, module_id)
            if module is not None:
                module.enabled = False
                await db.execute(
                    delete(ModuleSchedule).where(
                        ModuleSchedule.module_id == module_id
                    )
                )
                await db.commit()
        await dispose_db()
