"""Push pool state management: CRUD, batch lifecycle, and record queries."""

from __future__ import annotations


from dataclasses import dataclass

from enum import Enum
import logging
from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import SessionLocal
from .push_lock import get_cycle_lock as _lock
from .redaction import redact_text
from .push_outbox import enqueue as enqueue_outbox, make_idempotency_key
from .push_time import cycle_id_for, module_due
from ..models import (
    Module,
    PushBatch,
    PushPool,
    PushRecord,
)
from .schedules import SCHEDULE_CANCELLED, current_schedule

logger = logging.getLogger(__name__)

# Recovered state functions.


class BatchStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    TIMEOUT = "timeout"
    NOOP = "noop"
    EXPIRED = "expired"


class InvalidStateTransitionError(ValueError):
    pass


_ALLOWED = {
    BatchStatus.PENDING: {BatchStatus.SENT, BatchStatus.FAILED, BatchStatus.NOOP, BatchStatus.TIMEOUT, BatchStatus.EXPIRED},
    BatchStatus.FAILED: {BatchStatus.TIMEOUT, BatchStatus.EXPIRED, BatchStatus.NOOP},
    BatchStatus.SENT: set(),
    BatchStatus.TIMEOUT: set(),
    BatchStatus.NOOP: {BatchStatus.PENDING},
    BatchStatus.EXPIRED: set(),
}


def set_batch_status(batch: PushBatch, target: BatchStatus) -> None:
    """The only legal batch status write path."""
    batch.status = transition(batch.status, target).value


def transition(current: str | BatchStatus, target: BatchStatus) -> BatchStatus:
    current_status = BatchStatus(current)
    if target not in _ALLOWED[current_status]:
        raise InvalidStateTransitionError(f"illegal transition: {current_status} -> {target}")
    return target


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POOL_PENDING = "pending"
POOL_SUCCESS = "success"
POOL_FAILED = "failed"
POOL_SKIPPED = "skipped"
POOL_TIMEOUT = "timeout"

BATCH_PENDING = "pending"
BATCH_SENT = "sent"
BATCH_FAILED = "failed"
BATCH_TIMEOUT = "timeout"
BATCH_NOOP = "noop"
BATCH_EXPIRED = "expired"

# ---------------------------------------------------------------------------
# Locks
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Local helpers (duplicated from push_plan to avoid state→plan import)
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# Recovered CRUD / lifecycle
# ---------------------------------------------------------------------------

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
        "timeout": mapping.get(POOL_TIMEOUT, 0),
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
        due, reason = module_due(module, day)
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


async def _refresh_batch_counts(db: AsyncSession, batch: PushBatch) -> None:
    counts = await _counts(db, batch.cycle_id)
    batch.success_count = counts["success"]
    batch.failed_count = counts["failed"]
    batch.skipped_count = counts["skipped"]
    batch.pending_count = 0
    batch.timeout_count = counts["timeout"]


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
            # New rows added in this transaction are visible after flush().
            await db.flush()
            await _refresh_batch_counts(db, batch)
            await db.commit()
            await db.refresh(batch)
            return batch


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


async def _mark_noop(
    db: AsyncSession, batch: PushBatch, rows: list[PushPool]
) -> dict[str, object]:
    """All expected modules skipped: terminal no-op, no third-party call."""
    batch.status = transition(batch.status, BatchStatus.NOOP).value
    batch.success_count = 0
    batch.failed_count = 0
    batch.skipped_count = len(rows)
    batch.pending_count = 0
    batch.summary = f"全 skip 批次 cycle={batch.cycle_id} skipped={len(rows)}"
    batch.details_cleared = True
    await db.execute(delete(PushPool).where(PushPool.cycle_id == batch.cycle_id))
    return {"cycle_id": batch.cycle_id, "skipped": len(rows)}


@dataclass
class SupplementInfo:
    module_id: int
    module_key: str
    module_name: str


@dataclass
class ApplyOrProbeResult:
    applied: bool
    reject_reason: str | None = None
    supplement: SupplementInfo | None = None


async def apply_or_probe(
    db: AsyncSession,
    cycle_id: str,
    module_id: int,
    result_data: dict[str, object],
) -> ApplyOrProbeResult:
    module = await db.get(Module, module_id)
    batch = await db.scalar(
        select(PushBatch).where(PushBatch.cycle_id == cycle_id)
    )
    if module is None or batch is None or not module.push_unified:
        return ApplyOrProbeResult(False, "not_unified")
    if batch.status == BATCH_NOOP:
        set_batch_status(batch, BatchStatus.PENDING)
        batch.details_cleared = False
    if batch.status in {BATCH_SENT, BATCH_TIMEOUT, BATCH_EXPIRED}:
        reason = "expired" if batch.status == BATCH_EXPIRED else "terminal"
        supplement = None
        if reason != "expired":
            supplement = SupplementInfo(module.id, module.key, module.name)
        await db.rollback()
        return ApplyOrProbeResult(False, reason, supplement)
    await _upsert_pool_result(
        db, module=module, cycle_id=cycle_id,
        status=str(result_data.get("status", "failed")),
        message=str(result_data.get("message", "")),
        details=str(result_data.get("details", "")),
        trigger=str(result_data.get("trigger", "schedule")),
    )
    await db.commit()
    return ApplyOrProbeResult(True)


async def get_scheduled_times(cycle_id: str) -> list[datetime]:
    day = date.fromisoformat(cycle_id)
    async with SessionLocal() as db:
        modules = list(
            (await db.execute(select(Module).where(Module.enabled.is_(True), Module.push_unified.is_(True)).order_by(Module.id.asc()))).scalars().all()
        )
        times: list[datetime] = []
        for module in modules:
            due, _ = module_due(module, day)
            if not due:
                continue
            schedule = await current_schedule(db, module)
            if schedule is None or schedule.status == SCHEDULE_CANCELLED:
                continue
            if schedule.scheduled_at.astimezone(settings.timezone_info).date() == day:
                times.append(schedule.scheduled_at)
        return times


async def persist_schedule(cycle_id: str, trigger_at: datetime | None, timeout_at: datetime | None) -> PushBatch | None:
    async with SessionLocal() as db:
        batch = await db.scalar(select(PushBatch).where(PushBatch.cycle_id == cycle_id))
        if batch is None:
            return None
        batch.trigger_at = trigger_at
        batch.timeout_at = timeout_at
        await db.commit()
        await db.refresh(batch)
        return batch


async def _terminate_cross_day_batches(
    db: AsyncSession,
    batches: list[PushBatch],
    target: BatchStatus,
    reject_reason: str,
    skipped_counts: dict[str, int] | None = None,
) -> list[dict[str, object]]:
    """Apply terminal transitions and audit rows atomically in one transaction."""
    events: list[dict[str, object]] = []
    for batch in batches:
        set_batch_status(batch, target)
        kind = "noop" if target is BatchStatus.NOOP else "expired"
        enqueue_outbox(
            db,
            idempotency_key=make_idempotency_key(
                f"outbox-{kind}", batch.cycle_id, reject_reason
            ),
            kind=kind,
            message=f"历史批次 {batch.cycle_id} 清理为 {kind}: {reject_reason}",
        )
        await db.execute(
            delete(PushPool).where(PushPool.cycle_id == batch.cycle_id)
        )
        events.append({
            "cycle_id": batch.cycle_id,
            "kind": kind,
            "skipped": (skipped_counts or {}).get(batch.cycle_id, 0),
        })
    return events


async def get_due_and_expire_batches() -> list[tuple[PushBatch, bool]]:
    """Terminalize old FAILED batches and return current candidates."""
    today = cycle_id_for()
    async with _lock("cross_day_cleanup"):
      async with SessionLocal() as db:
        failed = list(
            (
                await db.execute(
                    select(PushBatch).where(
                        PushBatch.cycle_id < today,
                        PushBatch.status == BATCH_FAILED,
                    )
                )
            ).scalars()
        )
        await _terminate_cross_day_batches(
            db, failed, BatchStatus.EXPIRED, "cross_day_failed"
        )
        await db.commit()
    async with SessionLocal() as db:
        batches = list(
            (
                await db.execute(
                    select(PushBatch).where(
                        PushBatch.cycle_id == today,
                        PushBatch.status.in_((BATCH_PENDING, BATCH_FAILED)),
                    )
                )
            ).scalars()
        )
        candidate_ids = [batch.cycle_id for batch in batches]
        executing = set(
            (
                await db.execute(
                    select(PushPool.cycle_id)
                    .where(
                        PushPool.cycle_id.in_(candidate_ids),
                        PushPool.status != POOL_SKIPPED,
                    )
                    .distinct()
                )
            ).scalars()
        )
        return [(batch, batch.cycle_id not in executing) for batch in batches]


async def cleanup_cross_day_pending() -> list[dict[str, object]]:
    """Terminalize old PENDING batches atomically and return audit events."""
    today = cycle_id_for()
    async with _lock("cross_day_cleanup"):
      async with SessionLocal() as db:
        old = list(
            (
                await db.execute(
                    select(PushBatch).where(
                        PushBatch.cycle_id < today,
                        PushBatch.status == BATCH_PENDING,
                    )
                )
            ).scalars()
        )
        if not old:
            return []
        ids = [batch.cycle_id for batch in old]
        executing = set(
            (
                await db.execute(
                    select(PushPool.cycle_id)
                    .where(
                        PushPool.cycle_id.in_(ids),
                        PushPool.status != POOL_SKIPPED,
                    )
                    .distinct()
                )
            ).scalars()
        )
        counts = {
            cycle: int(count or 0)
            for cycle, count in (
                await db.execute(
                    select(PushPool.cycle_id, func.count())
                    .where(
                        PushPool.cycle_id.in_(ids),
                        PushPool.status == POOL_SKIPPED,
                    )
                    .group_by(PushPool.cycle_id)
                )
            ).all()
        }
        skipped = [b for b in old if b.cycle_id not in executing]
        active = [b for b in old if b.cycle_id in executing]
        events = await _terminate_cross_day_batches(
            db, skipped, BatchStatus.NOOP, "cross_day_pending_skip", counts
        )
        events += await _terminate_cross_day_batches(
            db, active, BatchStatus.EXPIRED, "cross_day_pending_active", counts
        )
        await db.commit()
        return events


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

