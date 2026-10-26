"""Unified push pool: skip generation, timeout, flush cleanup and idempotency."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update

from app.config import settings
from app.database import SessionLocal, init_db
from app.models import Module, PushBatch, PushPool, PushRecord
from app.services import push_delivery, push_pool


def _module(
    *,
    cycle: str = "daily",
    sub: str = "",
    unified: bool = True,
    independent: bool = False,
) -> Module:
    key = f"pool-{uuid.uuid4().hex[:10]}"
    return Module(
        key=key,
        name=key,
        description="",
        author="",
        default_cron="0 8 * * *",
        cron="0 8 * * *",
        default_start_time="08:00",
        default_end_time="10:00",
        default_repeat_cycle=cycle,
        default_repeat_sub_value=sub,
        start_time="08:00",
        end_time="10:00",
        repeat_cycle=cycle,
        repeat_sub_value=sub,
        push_enabled=unified or independent,
        push_unified=unified,
        push_independent=independent,
        enabled=True,
        param_schema=[],
    )


async def _disable_pool_modules() -> None:
    async with SessionLocal() as db:
        await db.execute(
            update(Module)
            .where(Module.key.like("pool-%"))
            .values(enabled=False, push_unified=False, push_independent=False, push_enabled=False)
        )
        await db.commit()


async def _add_modules(*modules: Module) -> list[int]:
    async with SessionLocal() as db:
        for module in modules:
            db.add(module)
        await db.commit()
        for module in modules:
            await db.refresh(module)
        return [module.id for module in modules]


@pytest.fixture
def fast_retries(monkeypatch):
    old_attempts = settings.push_retry_attempts
    old_base = settings.push_retry_base_seconds
    old_skip = settings.push_skip_notice
    settings.push_retry_attempts = 1
    settings.push_retry_base_seconds = 0
    sent: list[dict] = []

    async def fake_load(*_args, **_kwargs):
        return {
            "channel": "bark",
            "config": {"key": "test-key"},
            "title_template": "{event}｜{module_name}",
            "body_template": "{result}",
        }

    async def fake_send(channel, config, title, body, **_kwargs):
        sent.append({"channel": channel, "title": title, "body": body})
        return {"sent": True, "channel": channel, "response": "ok"}

    monkeypatch.setattr("app.services.push_delivery.load_push_config", fake_load)
    monkeypatch.setattr("app.services.push_delivery.send_message", fake_send)
    yield sent
    settings.push_retry_attempts = old_attempts
    settings.push_retry_base_seconds = old_base
    settings.push_skip_notice = old_skip


@pytest.mark.asyncio
async def test_expected_set_skip_rows_and_all_skip_no_push(fast_retries) -> None:
    await init_db()
    await _disable_pool_modules()
    cycle = "2026-11-01"
    due = _module(cycle="daily")
    no_day = _module(cycle="weekly", sub="1")  # Sunday cycle date
    no_leap = _module(cycle="yearly", sub="2-29")
    await _add_modules(due, no_day, no_leap)

    batch = await push_pool.ensure_batch(cycle)
    assert batch is not None
    assert batch.expected_count >= 3
    async with SessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(PushPool)
                    .where(PushPool.cycle_id == cycle)
                    .order_by(PushPool.id.asc())
                )
            )
            .scalars()
            .all()
        )
    by_key = {row.module_key: row for row in rows}
    assert by_key[due.key].status == "pending"
    assert by_key[no_day.key].status == "skipped"
    assert by_key[no_day.key].message == "当日不在执行周期"
    assert by_key[no_leap.key].status == "skipped"
    assert by_key[no_leap.key].message == "本年无执行日"
    # Disable this test's modules so the next batch really is all-skip.
    async with SessionLocal() as db:
        await db.execute(
            update(Module)
            .where(Module.key.in_([due.key, no_day.key, no_leap.key]))
            .values(enabled=False, push_unified=False)
        )
        await db.commit()
    # All expected modules skipped in a future all-skip batch => no push.
    all_skip_cycle = "2027-02-28"
    only_skip = _module(cycle="yearly", sub="2-29")
    await _add_modules(only_skip)
    await push_pool.ensure_batch(all_skip_cycle)
    assert await push_pool.maybe_flush_batch(all_skip_cycle) is False
    async with SessionLocal() as db:
        batch_row = await db.scalar(
            select(PushBatch).where(PushBatch.cycle_id == all_skip_cycle)
        )
        assert batch_row is not None and batch_row.status == "noop"
        assert batch_row.details_cleared is True


@pytest.mark.asyncio
async def test_flush_clears_pool_idempotent_and_manual_after_flush(fast_retries) -> None:
    await init_db()
    await _disable_pool_modules()
    cycle = "2026-11-02"
    module = _module(cycle="daily")
    (module_id,) = await _add_modules(module)
    await push_pool.ensure_batch(cycle)
    await push_pool.record_unified_result(
        module_id,
        status="success",
        message="签到成功",
        details="账号 1 成功",
        trigger="schedule",
        cycle_id=cycle,
    )
    assert await push_pool.flush_batch(cycle) is True
    async with SessionLocal() as db:
        batch = await db.scalar(
            select(PushBatch).where(PushBatch.cycle_id == cycle)
        )
        assert batch is not None
        assert batch.status == "sent", batch
        assert batch.details_cleared is True
        pool_count = await db.scalar(
            select(func.count()).select_from(PushPool).where(PushPool.cycle_id == cycle)
        )
        records = (
            (
                await db.execute(
                    select(PushRecord).where(PushRecord.cycle_id == cycle)
                )
            )
            .scalars()
            .all()
        )
    assert pool_count == 0
    assert any(record.kind == "unified" for record in records)
    assert len(fast_retries) == 1
    # Idempotent: no second summary.
    assert await push_pool.flush_batch(cycle) is False
    assert len(fast_retries) == 1
    # Manual execution after flush => one supplement record, no new pool row.
    await push_pool.record_unified_result(
        module_id,
        status="success",
        message="手动补执行成功",
        details="manual",
        trigger="manual",
        cycle_id=cycle,
    )
    assert len(fast_retries) == 2
    async with SessionLocal() as db:
        supplements = (
            (
                await db.execute(
                    select(PushRecord).where(
                        PushRecord.cycle_id == cycle,
                        PushRecord.kind == "supplement",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(supplements) == 1
        pool_count = await db.scalar(
            select(func.count()).select_from(PushPool).where(PushPool.cycle_id == cycle)
        )
    assert pool_count == 0


@pytest.mark.asyncio
async def test_skip_manual_override_and_skip_notice(fast_retries) -> None:
    await init_db()
    await _disable_pool_modules()
    cycle = "2026-11-03"
    skipped = _module(cycle="weekly", sub="1")  # Tuesday, not Monday
    executed = _module(cycle="daily")
    skipped_id, executed_id = await _add_modules(skipped, executed)
    await push_pool.ensure_batch(cycle)
    settings.push_skip_notice = False
    await push_pool.record_unified_result(
        executed_id,
        status="success",
        message="正常签到",
        details="one",
        trigger="schedule",
        cycle_id=cycle,
    )
    assert await push_pool.flush_batch(cycle) is True
    async with SessionLocal() as db:
        batch = await db.scalar(
            select(PushBatch).where(PushBatch.cycle_id == cycle)
        )
        assert batch is not None and batch.status == "sent"
        assert "跳过" in (batch.summary or "")
        # Skip details are suppressed, but the skip count remains in the summary.
        assert skipped.name not in (batch.summary or "")
        assert executed.name in (batch.summary or "")
    assert len(fast_retries) == 1
    # Now a manual override of the skipped module still produces a supplement
    # only after a flushed batch, not a second batch summary.
    await push_pool.record_unified_result(
        skipped_id,
        status="success",
        message="手动补执行成功",
        details="manual",
        trigger="manual",
        cycle_id=cycle,
    )
    assert len(fast_retries) == 2


@pytest.mark.asyncio
async def test_main_trigger_marks_unfinished_and_clears(fast_retries) -> None:
    await init_db()
    await _disable_pool_modules()
    cycle = "2026-11-04"
    module = _module(cycle="daily")
    await _add_modules(module)
    await push_pool.ensure_batch(cycle)
    async with SessionLocal() as db:
        batch = await db.scalar(
            select(PushBatch).where(PushBatch.cycle_id == cycle)
        )
        assert batch is not None
        batch.trigger_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        await db.commit()
    assert await push_pool.flush_batch(cycle, mode="main") is True
    async with SessionLocal() as db:
        batch = await db.scalar(
            select(PushBatch).where(PushBatch.cycle_id == cycle)
        )
        assert batch is not None and batch.status == "sent"
        assert batch.failed_count >= 1
        assert batch.timeout_count == 0
        assert (
            await db.scalar(
                select(func.count())
                .select_from(PushPool)
                .where(PushPool.cycle_id == cycle)
            )
            == 0
        )


@pytest.mark.asyncio
async def test_flush_failure_clears_body_and_keeps_summary(monkeypatch) -> None:
    await init_db()
    await _disable_pool_modules()
    cycle = "2026-11-05"
    module = _module(cycle="daily")
    (module_id,) = await _add_modules(module)
    await push_pool.ensure_batch(cycle)

    async def fake_load(*_args, **_kwargs):
        return {"channel": "bark", "config": {"key": "test"}, "title_template": "{event}", "body_template": "{result}"}

    async def fake_fail(*_args, **_kwargs):
        return {"sent": False, "channel": "bark", "error": "network down"}

    monkeypatch.setattr("app.services.push_delivery.load_push_config", fake_load)
    monkeypatch.setattr("app.services.push_delivery.send_message", fake_fail)
    old_attempts, old_base = settings.push_retry_attempts, settings.push_retry_base_seconds
    settings.push_retry_attempts = 1
    settings.push_retry_base_seconds = 0
    try:
        await push_pool.record_unified_result(
            module_id,
            status="failed",
            message="签到失败",
            details="error",
            trigger="schedule",
            cycle_id=cycle,
        )
    finally:
        settings.push_retry_attempts = old_attempts
        settings.push_retry_base_seconds = old_base
    assert await push_pool.flush_batch(cycle, mode="main") is True
    async with SessionLocal() as db:
        batch = await db.scalar(
            select(PushBatch).where(PushBatch.cycle_id == cycle)
        )
        assert batch is not None and batch.status == "failed"
        assert batch.details_cleared is False
        assert batch.error and "network down" in batch.error
        assert (
            await db.scalar(
                select(func.count()).select_from(PushPool).where(PushPool.cycle_id == cycle)
            )
            == 1
        )


@pytest.mark.asyncio
async def test_concurrent_results_only_one_summary(fast_retries) -> None:
    await init_db()
    await _disable_pool_modules()
    cycle = "2026-11-06"
    module = _module(cycle="daily")
    (module_id,) = await _add_modules(module)
    await push_pool.ensure_batch(cycle)
    await asyncio.gather(
        push_pool.record_unified_result(
            module_id,
            status="success",
            message="并发成功 A",
            details="A",
            trigger="schedule",
            cycle_id=cycle,
        ),
        push_pool.record_unified_result(
            module_id,
            status="failed",
            message="并发失败 B",
            details="B",
            trigger="schedule",
            cycle_id=cycle,
        ),
    )
    assert await push_pool.flush_batch(cycle) is True
    async with SessionLocal() as db:
        batch = await db.scalar(
            select(PushBatch).where(PushBatch.cycle_id == cycle)
        )
        assert batch is not None and batch.status == "sent"
        assert (
            await db.scalar(
                select(func.count()).select_from(PushPool).where(PushPool.cycle_id == cycle)
            )
            == 0
        )
        unified = await db.scalar(
            select(func.count())
            .select_from(PushRecord)
            .where(PushRecord.cycle_id == cycle, PushRecord.kind == "unified")
        )
        assert unified == 1
    assert len(fast_retries) == 1


@pytest.mark.asyncio
async def test_independent_push_is_immediate_and_recorded(monkeypatch) -> None:
    from app.services import push as push_service

    await init_db()
    await _disable_pool_modules()
    module = _module(cycle="daily", unified=False, independent=True)
    (module_id,) = await _add_modules(module)

    async def fake_load(*_args, **_kwargs):
        return {
            "channel": "bark",
            "config": {"key": "test"},
            "title_template": "{event}｜{module_name}",
            "body_template": "{result}",
        }

    sent = []

    async def fake_send(channel, config, title, body, **_kwargs):
        sent.append(title)
        return {"sent": True, "channel": channel, "response": "ok"}

    monkeypatch.setattr(push_service, "load_push_config", fake_load)
    monkeypatch.setattr(push_service, "send_message", fake_send)
    result = await push_service.send_independent_module(
        module_id,
        event="success",
        status_text="成功",
        result="独立推送成功",
        trigger="schedule",
    )
    assert result["sent"] is True
    assert len(sent) == 1
    async with SessionLocal() as db:
        records = (
            (
                await db.execute(
                    select(PushRecord).where(
                        PushRecord.module_id == module_id,
                        PushRecord.kind == "independent",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(records) == 1 and records[0].status == "success"
        # Independent only: no unified batch/pool row was created.
        batches = await db.scalar(
            select(func.count()).select_from(PushBatch).where(PushBatch.cycle_id == "2026-10-19")
        )
        assert batches in (0, None)


@pytest.mark.asyncio
async def test_concurrent_retention_flush_and_supplement_no_deadlock(fast_retries) -> None:
    """Cross-batch: ring trimming, batch flush and post-flush supplement together."""
    from datetime import datetime, timedelta

    from app.services.ring_log import ring_log

    await init_db()
    await _disable_pool_modules()
    cycle = "2026-11-07"
    module = _module(cycle="daily")
    (module_id,) = await _add_modules(module)
    old_days = ring_log.get_retention_days()
    try:
        ring_log.set_retention_days(1)
        scope = f"retention-{uuid.uuid4().hex[:8]}"
        old = datetime.now(settings.timezone_info) - timedelta(days=3)
        ring_log.append_execution(
            module_key=scope, log_id=999, text="expired-during-concurrency", created_at=old
        )
        ring_log.append_execution(
            module_key=scope, log_id=999, text="fresh-during-concurrency"
        )
        await push_pool.ensure_batch(cycle)

        async def trim() -> int:
            return await asyncio.to_thread(ring_log.trim_retention, 1)

        async def flush() -> None:
            await push_pool.record_unified_result(
                module_id,
                status="success",
                message="并发 flush 成功",
                details="one",
                trigger="schedule",
                cycle_id=cycle,
            )

        await asyncio.wait_for(asyncio.gather(trim(), flush()), timeout=10)
        assert await push_pool.flush_batch(cycle) is True
        async with SessionLocal() as db:
            batch = await db.scalar(
                select(PushBatch).where(PushBatch.cycle_id == cycle)
            )
            assert batch is not None and batch.status == "sent"
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(PushPool)
                    .where(PushPool.cycle_id == cycle)
                )
                == 0
            )

        async def supplement() -> None:
            await push_pool.record_unified_result(
                module_id,
                status="success",
                message="并发补发",
                details="manual",
                trigger="manual",
                cycle_id=cycle,
            )

        await asyncio.wait_for(asyncio.gather(trim(), supplement()), timeout=10)
        rows = ring_log.read_scope("module", scope)
        assert all("expired" not in row["text"] for row in rows)
        async with SessionLocal() as db:
            supplements = (
                (
                    await db.execute(
                        select(PushRecord).where(
                            PushRecord.cycle_id == cycle,
                            PushRecord.kind == "supplement",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(supplements) == 1, "flush 后补发应恰好一条"
        assert len(fast_retries) == 2
    finally:
        ring_log.set_retention_days(old_days)


@pytest.mark.asyncio
async def test_calculate_trigger_uses_latest_schedule_plus_one_minute(monkeypatch) -> None:
    await init_db()
    await _disable_pool_modules()
    module = _module(cycle="daily")
    await _add_modules(module)

    class FakeSchedule:
        status = "pending"
        scheduled_at = datetime(
            2026, 11, 8, 9, 37, tzinfo=settings.timezone_info
        )

    async def fake_current(*_args, **_kwargs):
        return FakeSchedule()

    monkeypatch.setattr("app.services.push_state.current_schedule", fake_current)
    trigger = await push_pool.calculate_unified_trigger_at("2026-11-08")
    assert trigger is not None
    assert trigger == datetime(
        2026, 11, 8, 9, 38, tzinfo=settings.timezone_info
    ).astimezone(timezone.utc)


@pytest.mark.asyncio
async def test_main_success_blocks_timeout_fallback(fast_retries) -> None:
    await init_db()
    await _disable_pool_modules()
    cycle = "2026-11-09"
    module = _module(cycle="daily")
    await _add_modules(module)
    await push_pool.ensure_batch(cycle)
    async with SessionLocal() as db:
        batch = await db.scalar(
            select(PushBatch).where(PushBatch.cycle_id == cycle)
        )
        assert batch is not None
        batch.status = "sent"
        batch.timeout_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    assert await push_pool.flush_batch(cycle, mode="timeout") is False
    assert fast_retries == []


@pytest.mark.asyncio
async def test_timeout_fallback_marks_unfinished_and_warns(fast_retries) -> None:
    await init_db()
    await _disable_pool_modules()
    cycle = "2026-11-10"
    module = _module(cycle="daily")
    (module_id,) = await _add_modules(module)
    await push_pool.ensure_batch(cycle)
    await push_pool.record_unified_result(
        module_id,
        status="success",
        message="已成功",
        details="ok",
        trigger="schedule",
        cycle_id=cycle,
    )
    async with SessionLocal() as db:
        batch = await db.scalar(
            select(PushBatch).where(PushBatch.cycle_id == cycle)
        )
        assert batch is not None
        batch.status = "failed"
        batch.trigger_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        batch.timeout_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        # Add one still-pending module to exercise the timeout state.
        pending = _module(cycle="daily")
        db.add(pending)
        await db.commit()
        await db.refresh(pending)
        db.add(
            PushPool(
                cycle_id=cycle,
                module_id=pending.id,
                module_key=pending.key,
                module_name=pending.name,
                status="pending",
            )
        )
        await db.commit()
    assert await push_pool.flush_batch(cycle, mode="timeout") is True
    async with SessionLocal() as db:
        batch = await db.scalar(
            select(PushBatch).where(PushBatch.cycle_id == cycle)
        )
        assert batch is not None
        assert batch.status == "timeout"
        assert batch.timeout_count >= 1
        assert "⚠️" in (batch.summary or "")
        assert "推送超时" in (batch.summary or "")
    assert fast_retries and "⚠️" in fast_retries[0]["title"]


@pytest.mark.asyncio
async def test_unified_timeout_settings_roundtrip() -> None:
    from app.services.push import load_unified_settings, save_unified_settings

    await init_db()
    async with SessionLocal() as db:
        initial = await load_unified_settings(db)
        assert initial["timeout_enabled"] is False
        saved = await save_unified_settings(
            db, timeout_enabled=True, timeout_time="23:30"
        )
        assert saved == {"timeout_enabled": True, "timeout_time": "23:30"}
    async with SessionLocal() as db:
        reloaded = await load_unified_settings(db)
        assert reloaded["timeout_enabled"] is True
        assert reloaded["timeout_time"] == "23:30"


@pytest.mark.asyncio
async def test_old_failed_batch_expires_instead_of_sending(monkeypatch) -> None:
    from datetime import datetime, timedelta, timezone

    await init_db()
    await _disable_pool_modules()
    cycle = "2020-01-01"
    module = _module(cycle="daily")
    await _add_modules(module)
    await push_pool.ensure_batch(cycle)
    async with SessionLocal() as db:
        batch = await db.scalar(select(PushBatch).where(PushBatch.cycle_id == cycle))
        assert batch is not None
        batch.status = "failed"
        batch.trigger_at = datetime.now(timezone.utc) - timedelta(days=1)
        await db.commit()
    sent = []
    async def fake_load(*_args, **_kwargs):
        return {"channel": "bark", "config": {}, "title_template": "", "body_template": ""}
    async def fake_send(*_args, **_kwargs):
        sent.append(1)
        return {"sent": True}
    monkeypatch.setattr("app.services.push_delivery.load_push_config", fake_load)
    monkeypatch.setattr("app.services.push_delivery.send_message", fake_send)
    await push_pool.flush_due_batches()
    async with SessionLocal() as db:
        batch = await db.scalar(select(PushBatch).where(PushBatch.cycle_id == cycle))
        assert batch is not None and batch.status == "expired"
    assert sent == []


@pytest.mark.asyncio
async def test_configure_clears_plan_when_no_schedule(monkeypatch) -> None:
    await init_db()
    await _disable_pool_modules()
    cycle = "2026-12-02"
    module = _module(cycle="daily")
    await _add_modules(module)
    await push_pool.ensure_batch(cycle)
    async with SessionLocal() as db:
        batch = await db.scalar(select(PushBatch).where(PushBatch.cycle_id == cycle))
        assert batch is not None
        batch.trigger_at = datetime.now(timezone.utc)
        batch.timeout_at = datetime.now(timezone.utc)
        await db.commit()
    async def no_trigger(*_args, **_kwargs):
        return None
    monkeypatch.setattr("app.services.push_state.get_scheduled_times", no_trigger, raising=False)
    await push_pool.configure_daily_batch(cycle)
    async with SessionLocal() as db:
        batch = await db.scalar(select(PushBatch).where(PushBatch.cycle_id == cycle))
        assert batch is not None
        assert batch.trigger_at is None
        assert batch.timeout_at is None


def test_batch_state_enum_and_transition_guard() -> None:
    from app.services.push_state import BatchStatus, InvalidStateTransitionError, transition

    assert {item.value for item in BatchStatus} >= {"pending", "sent", "failed", "timeout", "noop", "expired"}
    assert transition("pending", BatchStatus.SENT) is BatchStatus.SENT
    assert transition("failed", BatchStatus.TIMEOUT) is BatchStatus.TIMEOUT
    with pytest.raises(InvalidStateTransitionError):
        transition("sent", BatchStatus.PENDING)


def test_push_batch_schema_drops_deadline_at() -> None:
    from app.schemas import PushBatchOut
    assert "deadline_at" not in PushBatchOut.model_fields


@pytest.mark.asyncio
async def test_ring_async_wrappers_do_not_require_sync_flush() -> None:
    from app.services.ring_log import ring_log

    ring_log.append_execution(module_key="async-wrap", log_id=2001, text="ok\n")
    await ring_log.flush_async()
    rows = await ring_log.read_scope_async("module", "async-wrap")
    assert rows and rows[-1]["text"] == "ok\n"


def test_unified_batch_status_values_are_shared() -> None:
    from app.models import PushBatch
    from app.services.push_state import BatchStatus

    assert BatchStatus.EXPIRED.value == "expired"
    assert PushBatch.status.property.columns[0].type.length >= 8


@pytest.mark.asyncio
async def test_expired_batch_cannot_be_revived_by_late_result(fast_retries) -> None:
    await init_db()
    await _disable_pool_modules()
    cycle = "2026-12-03"
    module = _module(cycle="daily")
    (module_id,) = await _add_modules(module)
    await push_pool.ensure_batch(cycle)
    async with SessionLocal() as db:
        batch = await db.scalar(select(PushBatch).where(PushBatch.cycle_id == cycle))
        assert batch is not None
        batch.status = "expired"
        await db.commit()
    await push_pool.record_unified_result(
        module_id,
        status="success",
        message="late",
        details="late",
        trigger="schedule",
        cycle_id=cycle,
    )
    async with SessionLocal() as db:
        batch = await db.scalar(select(PushBatch).where(PushBatch.cycle_id == cycle))
        assert batch is not None and batch.status == "expired"
    assert fast_retries == []


def test_timeout_helper_requires_later_than_main_trigger() -> None:
    from datetime import datetime, timezone

    from app.services.push_pool import _timeout_at_for_cycle

    trigger = datetime(2026, 12, 4, 23, 59, tzinfo=timezone.utc)
    assert _timeout_at_for_cycle(
        "2026-12-04", trigger, {"timeout_enabled": True, "timeout_time": "23:30"}
    ) is None
    assert _timeout_at_for_cycle(
        "2026-12-04", trigger, {"timeout_enabled": False, "timeout_time": "23:59"}
    ) is None


@pytest.mark.asyncio
async def test_expired_batch_rejects_late_result(fast_retries) -> None:
    await init_db()
    await _disable_pool_modules()
    cycle = "2026-12-05"
    module = _module(cycle="daily")
    (module_id,) = await _add_modules(module)
    await push_pool.ensure_batch(cycle)
    async with SessionLocal() as db:
        batch = await db.scalar(select(PushBatch).where(PushBatch.cycle_id == cycle))
        assert batch is not None
        batch.status = "expired"
        from sqlalchemy import delete as _delete
        await db.execute(_delete(PushPool).where(PushPool.cycle_id == cycle))
        await db.commit()
    await push_pool.record_unified_result(
        module_id, status="success", message="late", details="late",
        trigger="schedule", cycle_id=cycle,
    )
    async with SessionLocal() as db:
        count = await db.scalar(
            select(func.count()).select_from(PushPool).where(PushPool.cycle_id == cycle)
        )
        assert count == 0
    assert fast_retries == []


@pytest.mark.asyncio
async def test_configure_clear_removes_scheduler_job(monkeypatch) -> None:
    await init_db()
    await _disable_pool_modules()
    cycle = "2026-12-06"
    module = _module(cycle="daily")
    await _add_modules(module)
    await push_pool.ensure_batch(cycle)
    async def no_trigger(*_args, **_kwargs):
        return []
    removed: list[str] = []
    async def remove(cycle_id: str) -> None:
        removed.append(cycle_id)
    monkeypatch.setattr("app.services.push_state.get_scheduled_times", no_trigger, raising=False)
    monkeypatch.setattr("app.services.push_pool._remove_unified_job", remove)
    await push_pool.configure_daily_batch(cycle)
    assert removed == [cycle]


@pytest.mark.asyncio
async def test_expired_batch_manual_late_result_never_supplements(monkeypatch) -> None:
    await init_db()
    await _disable_pool_modules()
    cycle = "2026-12-07"
    module = _module(cycle="daily")
    (module_id,) = await _add_modules(module)
    await push_pool.ensure_batch(cycle)
    async with SessionLocal() as db:
        batch = await db.scalar(select(PushBatch).where(PushBatch.cycle_id == cycle))
        assert batch is not None
        batch.status = "expired"
        await db.commit()
    supplements: list[tuple] = []
    async def fake_supp(*args, **_kwargs):
        supplements.append(args)
    monkeypatch.setattr("app.services.push_pool._supplement_after_flush", fake_supp)
    await push_pool.record_unified_result(
        module_id, status="success", message="late", details="late",
        trigger="manual", cycle_id=cycle,
    )
    assert supplements == []


@pytest.mark.asyncio
async def test_direct_flush_rejects_expired_batch() -> None:
    await init_db()
    await _disable_pool_modules()
    cycle = "2026-12-08"
    module = _module(cycle="daily")
    await _add_modules(module)
    await push_pool.ensure_batch(cycle)
    async with SessionLocal() as db:
        batch = await db.scalar(select(PushBatch).where(PushBatch.cycle_id == cycle))
        assert batch is not None
        batch.status = "expired"
        batch.timeout_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    assert await push_pool.flush_batch(cycle, mode="timeout") is False


@pytest.mark.asyncio
async def test_noop_batch_restores_outbox_audit() -> None:
    from app.models import PushOutbox

    await init_db()
    await _disable_pool_modules()
    cycle = datetime.now(settings.timezone_info).date().isoformat()
    only_skip = _module(cycle="weekly", sub="1")
    await _add_modules(only_skip)
    await push_pool.ensure_batch(cycle)
    await push_pool.flush_due_batches()
    async with SessionLocal() as db:
        batch = await db.scalar(select(PushBatch).where(PushBatch.cycle_id == cycle))
        assert batch is not None and batch.status == "noop"
        rows = (
            await db.execute(
                select(PushOutbox).where(PushOutbox.kind == "noop")
            )
        ).scalars().all()
        assert any(cycle in (row.message or "") for row in rows)



@pytest.mark.asyncio
async def test_cross_day_pending_batches_are_terminalized() -> None:
    from datetime import timedelta

    await init_db()
    await _disable_pool_modules()
    today = datetime.now(settings.timezone_info).date()
    skip_cycle = (today - timedelta(days=2)).isoformat()
    active_cycle = (today - timedelta(days=1)).isoformat()
    active_module = _module(cycle="daily")
    async with SessionLocal() as db:
        db.add(PushBatch(cycle_id=skip_cycle, status="pending", expected_count=0))
        db.add(PushBatch(cycle_id=active_cycle, status="pending", expected_count=1))
        db.add(active_module)
        await db.commit()
        await db.refresh(active_module)
        db.add(
            PushPool(
                cycle_id=active_cycle,
                module_id=active_module.id,
                module_key=active_module.key,
                module_name=active_module.name,
                status="pending",
            )
        )
        await db.commit()
    stats = await push_pool.flush_due_batches()
    async with SessionLocal() as db:
        skipped = await db.scalar(select(PushBatch).where(PushBatch.cycle_id == skip_cycle))
        active = await db.scalar(select(PushBatch).where(PushBatch.cycle_id == active_cycle))
        assert skipped is not None and skipped.status == "noop"
        assert active is not None and active.status == "expired"
    assert stats.total_processed >= 2
