"""Daily retention, startup recovery and legacy-file cleanup helpers."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from ..config import settings
from ..database import SessionLocal
from ..models import (
    STATUS_FAILED,
    STATUS_RUNNING,
    ExecutionLog,
    Module,
    PushBatch,
    PushPool,
    PushRecord,
)
from ..timeutils import utcnow
from .ring_log import ring_log

logger = logging.getLogger(__name__)

_BATCH = 1000


async def mark_stale_running_logs() -> int:
    """A process restart means any 'running' row is orphaned; close it cleanly."""
    async with SessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(ExecutionLog).where(ExecutionLog.status == STATUS_RUNNING)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return 0
        now = utcnow()
        module_ids = {row.module_id for row in rows}
        for row in rows:
            row.status = STATUS_FAILED
            row.message = "服务重启，执行被中断"
            row.finished_at = now
            if row.started_at:
                row.duration_ms = max(
                    0, int((now - row.started_at).total_seconds() * 1000)
                )
            row.output = None
            await asyncio.to_thread(
                ring_log.append_execution,
                module_key=row.module_key,
                log_id=row.id,
                text="\n[系统] 服务重启，执行流中断。\n",
                level="WARNING",
            )
        modules = (
            (
                await db.execute(
                    select(Module).where(
                        Module.id.in_(module_ids),
                        Module.last_status == STATUS_RUNNING,
                    )
                )
            )
            .scalars()
            .all()
        )
        for module in modules:
            module.last_status = STATUS_FAILED
            module.last_message = "服务重启，执行被中断"
        await db.commit()
        logger.info("已将 %s 条遗留运行记录标记为失败", len(rows))
        return len(rows)


def _prune_log_files(cutoff: datetime) -> int:
    base = settings.logs_dir / "executions"
    if not base.exists():
        return 0
    removed = 0
    for path in base.rglob("*.log"):
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if modified < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    for directory in sorted(
        (item for item in base.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
        except OSError:
            continue
    return removed


async def _purge_legacy_execution_rows(cutoff: datetime) -> int:
    """Delete old metadata in batches; ring bodies are trimmed separately."""
    removed = 0
    while True:
        async with SessionLocal() as db:
            ids = list(
                (
                    await db.execute(
                        select(ExecutionLog.id)
                        .where(
                            ExecutionLog.started_at < cutoff,
                            ExecutionLog.status != STATUS_RUNNING,
                        )
                        .order_by(ExecutionLog.id.asc())
                        .limit(_BATCH)
                    )
                ).scalars()
            )
            if not ids:
                return removed
            await db.execute(
                delete(ExecutionLog).where(ExecutionLog.id.in_(ids))
            )
            await db.commit()
            removed += len(ids)


async def _purge_push_tables(cutoff: datetime) -> None:
    """Remove expired push audit rows and orphaned old pool details."""
    async with SessionLocal() as db:
        await db.execute(delete(PushPool).where(PushPool.created_at < cutoff))
        await db.execute(delete(PushRecord).where(PushRecord.created_at < cutoff))
        await db.execute(delete(PushBatch).where(PushBatch.created_at < cutoff))
        await db.commit()


async def purge_old_logs(days: int | None = None) -> tuple[int, int]:
    """Apply the unified retention policy and legacy-file cleanup once.

    The ring body is trimmed in 1000-row batches; old execution metadata and
    pre-ring file mirrors are removed with the same cutoff.  The remaining old
    ``execution_logs.output`` values (from before the ring upgrade) are used as
    a read-only fallback until their row is deleted.
    """
    retention = (
        ring_log.get_retention_days()
        if days is None
        else max(1, min(365, int(days)))
    )
    cutoff = utcnow() - timedelta(days=retention)
    ring_removed = await asyncio.to_thread(ring_log.trim_retention, retention)
    rows_removed = await _purge_legacy_execution_rows(cutoff)
    await _purge_push_tables(cutoff)
    files_removed = _prune_log_files(cutoff)
    if ring_removed or rows_removed or files_removed:
        logger.info(
            "清理过期日志：环形日志 %s 条，历史记录 %s 条，旧文件 %s 个（保留 %s 天）",
            ring_removed,
            rows_removed,
            files_removed,
            retention,
        )
    return rows_removed, files_removed


async def purge_all_logs(module_id: int | None = None) -> int:
    async with SessionLocal() as db:
        condition = ExecutionLog.id.is_not(None)
        if module_id is not None:
            condition = ExecutionLog.module_id == module_id
        ids = list(
            (await db.execute(select(ExecutionLog.id).where(condition))).scalars()
        )
        if ids:
            await asyncio.to_thread(ring_log.delete_execution_ids, ids)
        result = await db.execute(delete(ExecutionLog).where(condition))
        await db.commit()
        return result.rowcount or 0


def remove_empty_log_dirs() -> None:
    base = settings.logs_dir / "executions"
    if not base.exists():
        return
    for directory in sorted(
        [item for item in base.iterdir() if item.is_dir()],
        key=lambda item: item.name,
    ):
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
        except OSError:
            continue
