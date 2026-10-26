"""Automatic redaction checks for logs, SSE capture and database history."""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime, timezone

import pytest

from app.database import SessionLocal, dispose_db, init_db
from app.models import ExecutionLog, Module
from app.services.bootstrap import seed_admin
from app.services.capture import OutputCapture
from app.services.execution import _finalize
from app.services.hub import ExecutionHub
from app.services.ring_log import ring_log
from app.services.redaction import (
    RedactingFilter,
    redact_text,
    sensitive_values,
)


def test_regex_and_exact_value_redaction() -> None:
    text = (
        "password=hunter2 passwd: abc Cookie: SESSDATA=xyz; bili=1 "
        "token=abc authorization: Bearer abc.def secret=sss key=kkk "
        "phone=13812345678 email=alice@example.com"
    )
    redacted = redact_text(text)
    for value in [
        "hunter2",
        "SESSDATA=xyz",
        "token=abc",
        "abc.def",
        "secret=sss",
        "key=kkk",
        "13812345678",
        "alice@example.com",
    ]:
        assert value not in redacted
    with sensitive_values(["EXACT-SECRET-123", "COOKIE-VALUE-456"]):
        exact = redact_text("value EXACT-SECRET-123 and COOKIE-VALUE-456")
    assert "EXACT-SECRET-123" not in exact
    assert "COOKIE-VALUE-456" not in exact


def test_output_capture_and_logging_filter_redact() -> None:
    hub = ExecutionHub()
    hub.begin(11)
    capture = OutputCapture(hub, 11)
    with sensitive_values(["P@ssw0rd-Exact", "SESSDATA=Cookie-Exact"]):
        capture.write("print P@ssw0rd-Exact and SESSDATA=Cookie-Exact\n")
        logger = logging.getLogger("test.redaction")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(RedactingFilter())
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        try:
            try:
                raise RuntimeError("boom P@ssw0rd-Exact SESSDATA=Cookie-Exact")
            except RuntimeError:
                logger.exception("module failed password=P@ssw0rd-Exact")
        finally:
            logger.removeHandler(handler)
    captured = capture.getvalue()
    streamed = hub.subscribe(11).snapshot
    for text in (captured, streamed, stream.getvalue()):
        assert "P@ssw0rd-Exact" not in text
        assert "SESSDATA=Cookie-Exact" not in text
        assert "***" in text


@pytest.mark.asyncio
async def test_database_and_file_history_do_not_store_plaintext() -> None:
    await init_db()
    await seed_admin()
    async with SessionLocal() as db:
        module = Module(
            key="redaction_test",
            name="Redaction Test",
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
        log = ExecutionLog(
            module_id=module.id,
            module_key=module.key,
            module_name=module.name,
            trigger="manual",
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        log_id, module_id, module_key = log.id, module.id, module.key

    message = "password=DB-SECRET-123 cookie=SESSDATA=DB-COOKIE-456"
    output = "token=DB-TOKEN-789\nemail=db@example.com\n"
    with sensitive_values(["DB-SECRET-123", "DB-COOKIE-456", "DB-TOKEN-789"]):
        await _finalize(
            log_id=log_id,
            module_id=module_id,
            status="failed",
            message=message,
            output=output,
            finished_at=datetime.now(timezone.utc),
            duration_ms=10,
        )
        await asyncio.to_thread(
            ring_log.append_execution,
            module_key=module_key,
            log_id=log_id,
            text=output,
            level="ERROR",
        )

    async with SessionLocal() as db:
        stored = await db.get(ExecutionLog, log_id)
        module = await db.get(Module, module_id)
        assert stored is not None and module is not None
        ring_rows = await asyncio.to_thread(ring_log.read_execution, log_id)
        for text in (
            stored.message or "",
            stored.output or "",
            module.last_message or "",
            "".join(str(row["text"]) for row in ring_rows),
        ):
            for secret in [
                "DB-SECRET-123",
                "DB-COOKIE-456",
                "DB-TOKEN-789",
                "db@example.com",
            ]:
                assert secret not in text
    await dispose_db()


def test_ring_write_failure_marks_emergency_fallback(monkeypatch) -> None:
    from app.services import capture as capture_module

    hub = ExecutionHub()
    hub.begin(77)
    output = capture_module.OutputCapture(hub, 77, module_key="fallback")
    monkeypatch.setattr(
        capture_module.ring_log, "append_execution", lambda **_kwargs: 0
    )
    output.write("must-not-be-lost\n")
    assert output.ring_failed is True
    assert "must-not-be-lost" in hub.subscribe(77).snapshot
