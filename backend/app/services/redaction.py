"""Central log redaction for application, module and container output.

A context variable carries the exact sensitive values of the current module
execution.  Everyone writing logs (logging handlers, print()/stdout, SSE and
execution history) runs text through :func:`redact_text`.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Generator, Iterable
from urllib.parse import quote

_SENSITIVE_VALUES: ContextVar[frozenset[str]] = ContextVar(
    "sensitive_log_values", default=frozenset()
)
_installed = False

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*[^\s,;&]+"), r"\1=***"),
    (re.compile(r"(?i)\b(authorization)\s*[:=]\s*[^\n]+"), r"\1: ***"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer ***"),
    (re.compile(r"(?i)\b(cookie|cookies)\s*[:=]\s*[^\n]+"), r"\1: ***"),
    (
        re.compile(
            r"(?i)\b(token|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)"
            r"\s*[:=]\s*[^\s,;&]+"
        ),
        r"\1=***",
    ),
    (re.compile(r"(?i)\bkey\s*[:=]\s*[^\s,;&]+"), "key=***"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "1**********"),
    (
        re.compile(r"(?i)\b([A-Z0-9._%+-]{1,64})@([A-Z0-9.-]+\.[A-Z]{2,})\b"),
        r"***@\2",
    ),
)


def _sensitive_values() -> frozenset[str]:
    return _SENSITIVE_VALUES.get()


@contextmanager
def sensitive_values(values: Iterable[object]) -> Generator[None, None, None]:
    items: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = str(value)
        if len(text) < 3:
            continue
        items.add(text)
        encoded = quote(text, safe="")
        if encoded != text:
            items.add(encoded)
    # Longest first so overlapping secrets are fully removed.
    frozen = frozenset(sorted(items, key=len, reverse=True))
    token = _SENSITIVE_VALUES.set(frozen)
    try:
        yield
    finally:
        _SENSITIVE_VALUES.reset(token)


def redact_text(text: object) -> str:
    value = str(text or "")
    if not value:
        return value
    for secret in _sensitive_values():
        value = value.replace(secret, "***")
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value


class RedactingFilter(logging.Filter):
    """Redact message, args and traceback text on every logging handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact_text(record.getMessage())
            record.args = ()
            if record.exc_info:
                record.exc_text = redact_text(
                    logging.Formatter().formatException(record.exc_info)
                )
                record.exc_info = None
            elif record.exc_text:
                record.exc_text = redact_text(record.exc_text)
        except Exception:  # pragma: no cover - logging must never fail
            pass
        return True


def _add_filter(handler: logging.Handler) -> None:
    if not any(isinstance(item, RedactingFilter) for item in handler.filters):
        handler.addFilter(RedactingFilter())


def install_redaction() -> None:
    """Install the filter on root and known third-party handlers."""
    global _installed
    loggers = [logging.getLogger()]
    for name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "httpx",
        "httpcore",
        "apscheduler",
        "apscheduler.scheduler",
        "apscheduler.executors.default",
    ):
        loggers.append(logging.getLogger(name))
    for logger in loggers:
        for handler in logger.handlers:
            _add_filter(handler)
        if not any(isinstance(item, RedactingFilter) for item in logger.filters):
            logger.addFilter(RedactingFilter())
    _installed = True


def collect_sensitive_values(
    schema: Iterable[dict[str, object]],
    params: dict[str, object] | None,
    accounts: Iterable[dict[str, object]] | None = None,
) -> list[str]:
    """Extract configured sensitive values (single or multi-account)."""
    sensitive_keys = {
        str(spec.get("key"))
        for spec in schema
        if spec.get("sensitive")
        or spec.get("type") == "password"
        or str(spec.get("key") or "").lower()
        in {"cookie", "token", "secret", "key", "password", "passwd"}
    }
    values: list[str] = []
    sources: list[dict[str, object]] = []
    if params:
        sources.append(params)
    for account in accounts or []:
        account_params = account.get("params")
        if isinstance(account_params, dict):
            sources.append(account_params)
    for source in sources:
        for key in sensitive_keys:
            value = source.get(key)
            if value not in (None, ""):
                values.append(str(value))
    return values
