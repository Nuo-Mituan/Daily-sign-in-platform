"""Per-execution stdout/stderr/logging capture using context variables.

Using a context variable instead of ``contextlib.redirect_stdout`` keeps
concurrently running modules from capturing each other's output.
"""

from __future__ import annotations

import io
import logging
import sys
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Generator, TextIO

from .hub import ExecutionHub
from .redaction import redact_text
from .ring_log import ring_log

_current_capture: ContextVar["OutputCapture | None"] = ContextVar(
    "current_capture", default=None
)
_router_installed = False


class OutputCapture:
    def __init__(
        self,
        hub: ExecutionHub,
        log_id: int,
        max_chars: int = 512_000,
        module_key: str = "unknown",
    ) -> None:
        self.hub = hub
        self.log_id = log_id
        self.max_chars = max_chars
        self.module_key = module_key
        self.last_seq = 0
        self.ring_failed = False
        self._parts: list[str] = []
        self._size = 0
        self._truncated = False
        self._lock = threading.Lock()

    def write(self, text: object) -> None:
        if text is None:
            return
        chunk = redact_text(str(text))
        if not chunk:
            return
        notice: str | None = None
        published = ""
        with self._lock:
            if self._truncated:
                return
            remaining = self.max_chars - self._size
            if remaining <= 0:
                self._truncated = True
                notice = "\n[日志输出超过上限，后续内容已截断]\n"
                self._parts.append(notice)
                self._size += len(notice)
            else:
                published = chunk[:remaining]
                self._parts.append(published)
                self._size += len(published)
                if len(chunk) > remaining:
                    self._truncated = True
                    notice = "\n[日志输出超过上限，后续内容已截断]\n"
                    self._parts.append(notice)
                    self._size += len(notice)
        if published:
            seq = ring_log.append_execution(
                module_key=self.module_key,
                log_id=self.log_id,
                text=published,
                level="OUT",
            )
            if seq:
                self.last_seq = seq
            else:
                self.ring_failed = True
            self.hub.publish(self.log_id, published, seq)
        if notice:
            seq = ring_log.append_execution(
                module_key=self.module_key,
                log_id=self.log_id,
                text=notice,
                level="WARNING",
            )
            if seq:
                self.last_seq = seq
            else:
                self.ring_failed = True
            self.hub.publish(self.log_id, notice, seq)

    def writeline(self, text: str = "") -> None:
        self.write(text + "\n")

    def getvalue(self) -> str:
        with self._lock:
            return "".join(self._parts)


class _Router(io.TextIOBase):
    """A stdout/stderr proxy that routes writes to the active capture."""

    def __init__(self, original: TextIO) -> None:
        self._original = original

    def write(self, text: str) -> int:  # type: ignore[override]
        capture = _current_capture.get()
        if capture is not None:
            capture.write(text)
            return len(text)
        clean = redact_text(text)
        ring_log.append_system("STDOUT", clean)
        return self._original.write(clean)

    def flush(self) -> None:
        capture = _current_capture.get()
        if capture is None:
            self._original.flush()

    def isatty(self) -> bool:
        try:
            return self._original.isatty()
        except (AttributeError, ValueError):
            return False

    def fileno(self) -> int:
        return self._original.fileno()

    @property
    def encoding(self) -> str | None:  # type: ignore[override]
        return getattr(self._original, "encoding", "utf-8")

    def __getattr__(self, name: str) -> object:
        return getattr(self._original, name)


def _redirect_stream_handlers(old_stdout: TextIO, old_stderr: TextIO) -> int:
    """Point existing stream handlers at the router so app logging is mirrored.

    BasicConfig and uvicorn create their handlers before the application
    lifespan.  Redirecting their stream (rather than adding a second capture
    handler) keeps module logging, print() and container stdout in one path.
    """

    redirected = 0
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
            if not isinstance(handler, logging.StreamHandler):
                continue
            stream = getattr(handler, "stream", None)
            if stream is old_stdout:
                handler.setStream(sys.stdout)
                redirected += 1
            elif stream is old_stderr:
                handler.setStream(sys.stderr)
                redirected += 1
    return redirected


def install_stdout_router() -> None:
    global _router_installed
    if _router_installed:
        return
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = _Router(old_stdout)
    sys.stderr = _Router(old_stderr)
    _redirect_stream_handlers(old_stdout, old_stderr)
    root_logger = logging.getLogger()
    if root_logger.level > logging.INFO or root_logger.level == logging.NOTSET:
        root_logger.setLevel(logging.INFO)
    _router_installed = True


@contextmanager
def capture_output(capture: OutputCapture) -> Generator[OutputCapture, None, None]:
    token = _current_capture.set(capture)
    try:
        yield capture
    finally:
        _current_capture.reset(token)
