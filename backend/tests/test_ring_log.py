"""Ring-buffer ordering, quotas, per-module isolation and restart tests."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.database import SessionLocal, init_db
from app.models import ExecutionLog, Module
from app.services.maintenance import purge_old_logs
from app.services.ring_log import ring_log


def _scope(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.mark.asyncio
async def test_fifo_scope_quota_and_restart_preserves_seq() -> None:
    await init_db()
    scope = _scope("ring-fifo")
    old_rows = settings.ring_module_max_rows
    old_bytes = settings.ring_module_max_bytes
    settings.ring_module_max_rows = 3
    settings.ring_module_max_bytes = 10 * 1024 * 1024
    try:
        seqs = [
            ring_log.append_execution(
                module_key=scope, log_id=1, text=f"row-{index}\n"
            )
            for index in range(6)
        ]
        rows = ring_log.read_scope("module", scope)
        assert len(rows) == 3
        assert [row["seq"] for row in rows] == seqs[-3:]
        assert [row["text"] for row in rows] == ["row-3\n", "row-4\n", "row-5\n"]
        assert all(
            rows[index + 1]["seq"] == rows[index]["seq"] + 1
            for index in range(len(rows) - 1)
        )

        ring_log.close()
        ring_log.initialize()
        resumed = ring_log.append_execution(
            module_key=scope, log_id=1, text="after-restart\n"
        )
        assert resumed > seqs[-1]
        rows = ring_log.read_scope("module", scope)
        assert rows[-1]["text"] == "after-restart\n"
        assert len(rows) == 3
        assert all(
            rows[index + 1]["seq"] == rows[index]["seq"] + 1
            for index in range(len(rows) - 1)
        )
    finally:
        settings.ring_module_max_rows = old_rows
        settings.ring_module_max_bytes = old_bytes


@pytest.mark.asyncio
async def test_bytes_quota_and_module_isolation() -> None:
    await init_db()
    scope_a = _scope("ring-a")
    scope_b = _scope("ring-b")
    old_rows = settings.ring_module_max_rows
    old_bytes = settings.ring_module_max_bytes
    settings.ring_module_max_rows = 100
    settings.ring_module_max_bytes = 1000
    try:
        for index in range(10):
            ring_log.append_execution(
                module_key=scope_a, log_id=2, text="A" * 200 + f"-{index}"
            )
        for index in range(3):
            ring_log.append_execution(
                module_key=scope_b, log_id=3, text="B" * 50 + f"-{index}"
            )
        rows_a = ring_log.read_scope("module", scope_a)
        rows_b = ring_log.read_scope("module", scope_b)
        assert sum(row["byte_size"] for row in rows_a) <= 1000
        assert len(rows_a) == 4
        assert rows_a[-1]["text"].endswith("-9")
        assert len(rows_b) == 3
        assert rows_b[-1]["text"].endswith("-2")
        # Module B never gets evicted because module A is full.
        assert all(row["text"].startswith("B") for row in rows_b)
    finally:
        settings.ring_module_max_rows = old_rows
        settings.ring_module_max_bytes = old_bytes


@pytest.mark.asyncio
async def test_retention_immediate_and_validation() -> None:
    await init_db()
    scope = _scope("ring-retention")
    old_rows = settings.ring_module_max_rows
    old_bytes = settings.ring_module_max_bytes
    settings.ring_module_max_rows = 100
    settings.ring_module_max_bytes = 10 * 1024 * 1024
    old_days = ring_log.get_retention_days()
    try:
        old = datetime.now(settings.timezone_info) - timedelta(days=3)
        ring_log.append_execution(
            module_key=scope, log_id=4, text="expired\n", created_at=old
        )
        ring_log.append_execution(module_key=scope, log_id=4, text="fresh\n")
        removed = ring_log.set_retention_days(1)
        assert removed >= 1
        rows = ring_log.read_scope("module", scope)
        assert [row["text"] for row in rows] == ["fresh\n"]
        with pytest.raises(ValueError):
            ring_log.set_retention_days(0)
        with pytest.raises(ValueError):
            ring_log.set_retention_days(366)
        with pytest.raises(ValueError):
            ring_log.set_retention_days(True)
    finally:
        ring_log.set_retention_days(old_days)
        settings.ring_module_max_rows = old_rows
        settings.ring_module_max_bytes = old_bytes


@pytest.mark.asyncio
async def test_startup_retention_purges_old_history_and_files() -> None:
    await init_db()
    key = _scope("ring-legacy")
    async with SessionLocal() as db:
        module = Module(
            key=key,
            name="Legacy Log Test",
            description="",
            author="",
            default_cron="0 8 * * *",
            cron="0 8 * * *",
            default_start_time="08:00",
            default_end_time="10:00",
            default_repeat_cycle="daily",
            default_repeat_sub_value="",
            start_time="08:00",
            end_time="10:00",
            repeat_cycle="daily",
            repeat_sub_value="",
            enabled=False,
            param_schema=[],
        )
        db.add(module)
        await db.commit()
        await db.refresh(module)
        old_log = ExecutionLog(
            module_id=module.id,
            module_key=key,
            module_name="Legacy Log Test",
            trigger="manual",
            status="success",
            output="legacy plaintext that should be purged",
            started_at=datetime.now(timezone.utc) - timedelta(days=40),
            finished_at=datetime.now(timezone.utc) - timedelta(days=40),
            duration_ms=1,
        )
        db.add(old_log)
        await db.commit()
        log_id = old_log.id

    legacy_dir = settings.logs_dir / "executions" / key
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_file = legacy_dir / "old.log"
    legacy_file.write_text("legacy file\n", encoding="utf-8")
    old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).timestamp()
    os.utime(legacy_file, (old_ts, old_ts))

    removed_rows, removed_files = await purge_old_logs(31)
    assert removed_rows >= 1
    assert removed_files >= 1
    async with SessionLocal() as db:
        assert await db.get(ExecutionLog, log_id) is None
    assert not legacy_file.exists()


@pytest.mark.asyncio
async def test_capture_async_path_does_not_block_on_full_queue() -> None:
    import asyncio
    import queue
    import time

    from app.services.capture import OutputCapture
    from app.services.hub import hub
    from app.services.ring_log import ring_log

    old_queue = ring_log._queue
    ring_log._queue = queue.Queue(maxsize=1)
    ring_log._queue.put_nowait("full")
    capture = OutputCapture(hub, 999001, 1000, "nonblocking")
    started = time.perf_counter()
    try:
        await asyncio.to_thread(capture.write, "payload")
    finally:
        ring_log._queue = old_queue
    assert (time.perf_counter() - started) < 0.1
