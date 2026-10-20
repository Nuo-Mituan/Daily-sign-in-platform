"""Transactional push audit outbox and idempotency-key helpers."""

from __future__ import annotations

import asyncio
import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import SessionLocal
from ..models import PushOutbox
from ..timeutils import utcnow
from .redaction import redact_text
from .ring_log import ring_log

logger = logging.getLogger(__name__)


def make_idempotency_key(kind: str, *parts: object) -> str:
    digest = hashlib.sha256(
        "\x1f".join(str(part) for part in parts).encode("utf-8")
    ).hexdigest()[:32]
    return f"{kind}:{digest}"


def enqueue(
    db: AsyncSession,
    *,
    idempotency_key: str,
    kind: str,
    message: str,
) -> PushOutbox:
    """Add an outbox row; caller must commit it with business state."""
    row = PushOutbox(
        idempotency_key=idempotency_key,
        kind=kind,
        message=redact_text(message),
    )
    db.add(row)
    return row


async def drain(limit: int = 200) -> int:
    """Move pending outbox rows to the ring audit log idempotently."""
    drained = 0
    async with SessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(PushOutbox)
                    .where(PushOutbox.status == "pending")
                    .order_by(PushOutbox.id.asc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            try:
                seq = await asyncio.to_thread(
                    ring_log.append_push, row.message, "INFO"
                )
                if not seq:
                    raise RuntimeError("环形日志写入未返回 seq")
                row.status = "processed"
                row.processed_at = utcnow()
                row.last_error = None
                drained += 1
            except Exception as exc:  # ring store catches DB errors internally
                row.attempts += 1
                row.last_error = redact_text(f"{type(exc).__name__}: {exc}")
                logger.warning("推送审计 outbox 处理失败：%s", row.last_error)
        await db.commit()
    return drained


async def pending_count() -> int:
    async with SessionLocal() as db:
        rows = await db.execute(
            select(PushOutbox.id).where(PushOutbox.status == "pending")
        )
        return len(list(rows.scalars()))
