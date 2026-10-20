"""Unified SQLite-backed ring-buffer log store.

Design choice
-------------
SQLite (the application's existing database) is used instead of day-sharded
files.  A persisted ``ring_state.next_seq`` counter is allocated in the same
``BEGIN IMMEDIATE`` transaction as the insert and the quota eviction, so a
single-process deployment gets a total order that survives restarts.  Reads
always sort by ``seq``; database row ids and file line order are never used.
The small synchronous writer is protected by a process-wide lock and uses WAL,
which keeps module output, application logging and push audit records in one
place without duplicating per-subsystem file writers.
"""

from __future__ import annotations

import logging
import queue
import sqlite3
from contextlib import closing
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable

from ..config import settings
from ..contracts import RingLogEntry, RingScopeEntry
from .redaction import redact_text

logger = logging.getLogger(__name__)

_SCOPE_SYSTEM = "system"
_SCOPE_PUSH = "push"
_SCOPE_MODULE = "module"
_WRITING = threading.local()


class RingLogError(RuntimeError):
    pass


class RingLogStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._db_lock = threading.RLock()
        self._seq_lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue(maxsize=settings.ring_queue_max)
        self._writer: threading.Thread | None = None
        self._next_seq = 1
        self._writer_failed = False
        self._initialized = False
        self._retention_days = max(1, min(365, int(settings.log_retention_days)))
        self._path = settings.data_dir / "checkin.db"

    # --------------------------------------------------------------- lifecycle
    def initialize(self) -> None:
        """Create/repair the counter and load the persisted retention setting."""
        with self._lock:
            if self._initialized and self._writer is not None and self._writer.is_alive():
                return
            if not self._path.exists():
                raise RingLogError(f"日志数据库不存在：{self._path}")
            with closing(self._connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS ring_state ("
                    "id INTEGER PRIMARY KEY, next_seq INTEGER NOT NULL)"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS app_settings ("
                    "key VARCHAR(80) PRIMARY KEY, value TEXT NOT NULL DEFAULT '', "
                    "updated_at DATETIME)"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS ring_logs ("
                    "seq INTEGER PRIMARY KEY, scope_type VARCHAR(16) NOT NULL, "
                    "scope_key VARCHAR(160) NOT NULL, category VARCHAR(24) NOT NULL, "
                    "level VARCHAR(16) NOT NULL, text TEXT NOT NULL, "
                    "byte_size INTEGER NOT NULL, created_at VARCHAR(40) NOT NULL, "
                    "created_at_epoch INTEGER NOT NULL, ref_type VARCHAR(24), "
                    "ref_id INTEGER)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS ix_ring_logs_scope_seq "
                    "ON ring_logs(scope_type, scope_key, seq)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS ix_ring_logs_ref_seq "
                    "ON ring_logs(ref_type, ref_id, seq)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS ix_ring_logs_created_epoch "
                    "ON ring_logs(created_at_epoch)"
                )
                max_seq = int(
                    conn.execute("SELECT COALESCE(MAX(seq), 0) FROM ring_logs").fetchone()[0]
                )
                row = conn.execute(
                    "SELECT next_seq FROM ring_state WHERE id = 1"
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO ring_state(id, next_seq) VALUES(1, ?)",
                        (max_seq + 1,),
                    )
                elif int(row[0]) <= max_seq:
                    conn.execute(
                        "UPDATE ring_state SET next_seq = ? WHERE id = 1",
                        (max_seq + 1,),
                    )
                stored = conn.execute(
                    "SELECT value FROM app_settings WHERE key = 'log_retention_days'"
                ).fetchone()
                if stored is not None:
                    try:
                        candidate = int(stored[0])
                    except (TypeError, ValueError):
                        candidate = self._retention_days
                    self._retention_days = max(1, min(365, candidate))
                self._next_seq = int(
                    conn.execute(
                        "SELECT next_seq FROM ring_state WHERE id = 1"
                    ).fetchone()[0]
                )
                conn.commit()
            self._initialized = True
            if self._writer is None or not self._writer.is_alive():
                self._writer = threading.Thread(
                    target=self._writer_loop,
                    name="ring-log-writer",
                    daemon=True,
                )
                self._writer.start()

    def close(self) -> None:
        """Flush queued rows and stop the writer thread on graceful shutdown."""
        self.flush()
        if self._writer is not None and self._writer.is_alive():
            self._queue.put(None)
            self._writer.join(timeout=10)
        self._writer = None
        self._initialized = False
        self._writer_failed = False
        self._queue = queue.Queue(maxsize=settings.ring_queue_max)

    def flush(self) -> None:
        """Wait until every record enqueued before this call is persisted."""
        if self._writer is not None:
            self._queue.join()

    # ------------------------------------------------------------------ writes
    def append(
        self,
        *,
        scope_type: str,
        scope_key: str,
        text: str,
        category: str = "app",
        level: str = "INFO",
        ref_type: str | None = None,
        ref_id: int | None = None,
        created_at: datetime | None = None,
    ) -> int:
        if not self._initialized or self._writer_failed:
            return 0
        if getattr(_WRITING, "active", False):
            return 0
        clean = redact_text(str(text or ""))
        if not clean:
            return 0
        local = self._local_time(created_at)
        iso = local.isoformat(timespec="microseconds")
        epoch = int(local.timestamp())
        payload = clean.encode("utf-8")
        if len(payload) > max(1024, settings.ring_module_max_bytes):
            clean = clean.encode("utf-8")[
                : max(1024, settings.ring_module_max_bytes)
            ].decode("utf-8", errors="ignore")
            payload = clean.encode("utf-8")
        # Allocate and enqueue under one lock: producers can never enqueue
        # seq 2 before seq 1, even across threads.
        with self._seq_lock:
            seq = self._next_seq
            self._next_seq += 1
            self._queue.put(
                (
                    seq,
                    scope_type,
                    scope_key,
                    category,
                    level,
                    clean,
                    len(payload),
                    iso,
                    epoch,
                    ref_type,
                    ref_id,
                )
            )
        return seq

    def _writer_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                return
            batch = [item]
            stop_after = False
            while len(batch) < 256:
                try:
                    extra = self._queue.get_nowait()
                except queue.Empty:
                    break
                if extra is None:
                    self._queue.task_done()
                    stop_after = True
                    break
                batch.append(extra)
            try:
                self._write_batch(batch)
            except Exception:
                self._writer_failed = True
                logger.exception("环形日志写线程异常，已进入降级模式")
            finally:
                for _ in batch:
                    self._queue.task_done()
            if stop_after:
                return

    def _write_batch(self, items: list[tuple]) -> None:
        with self._db_lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                scopes: set[tuple[str, str]] = set()
                max_seq = self._next_seq
                for item in items:
                    (seq, scope_type, scope_key, category, level, text,
                     byte_size, created_at, epoch, ref_type, ref_id) = item
                    max_seq = max(max_seq, seq + 1)
                    conn.execute(
                        "INSERT INTO ring_logs("
                        "seq, scope_type, scope_key, category, level, text, byte_size, "
                        "created_at, created_at_epoch, ref_type, ref_id"
                        ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (seq, scope_type, scope_key, category, level, text,
                         byte_size, created_at, epoch, ref_type, ref_id),
                    )
                    scopes.add((scope_type, scope_key))
                conn.execute(
                    "UPDATE ring_state SET next_seq = MAX(next_seq, ?) WHERE id=1",
                    (max_seq,),
                )
                for scope_type, scope_key in scopes:
                    self._trim_scope(conn, scope_type, scope_key)
                self._trim_global(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _scope_limits(self, scope_type: str, scope_key: str) -> tuple[int, int]:
        if scope_type == _SCOPE_MODULE:
            return settings.ring_module_max_rows, settings.ring_module_max_bytes
        if scope_type == _SCOPE_PUSH:
            return settings.ring_push_max_rows, settings.ring_push_max_bytes
        return settings.ring_system_max_rows, settings.ring_system_max_bytes

    def _trim_scope(self, conn: sqlite3.Connection, scope_type: str, scope_key: str) -> int:
        max_rows, max_bytes = self._scope_limits(scope_type, scope_key)
        removed = 0
        while True:
            count, size = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(byte_size), 0) FROM ring_logs "
                "WHERE scope_type = ? AND scope_key = ?",
                (scope_type, scope_key),
            ).fetchone()
            if int(count) <= max_rows and int(size) <= max_bytes:
                break
            rows = conn.execute(
                "SELECT seq, byte_size FROM ring_logs "
                "WHERE scope_type = ? AND scope_key = ? ORDER BY seq ASC LIMIT ?",
                (scope_type, scope_key, settings.ring_trim_batch_size),
            ).fetchall()
            if not rows:
                break
            remaining_rows = int(count)
            remaining_bytes = int(size)
            delete: list[int] = []
            for seq, byte_size in rows:
                if remaining_rows <= max_rows and remaining_bytes <= max_bytes:
                    break
                delete.append(int(seq))
                remaining_rows -= 1
                remaining_bytes -= int(byte_size)
            if not delete:
                break
            self._delete_seqs(conn, delete)
            removed += len(delete)
        return removed

    def _trim_global(self, conn: sqlite3.Connection) -> int:
        removed = 0
        while True:
            count, size = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(byte_size), 0) FROM ring_logs"
            ).fetchone()
            if (
                int(count) <= settings.ring_log_max_rows
                and int(size) <= settings.ring_log_max_bytes
            ):
                break
            rows = conn.execute(
                "SELECT seq, byte_size FROM ring_logs ORDER BY seq ASC LIMIT ?",
                (settings.ring_trim_batch_size,),
            ).fetchall()
            if not rows:
                break
            remaining_rows = int(count)
            remaining_bytes = int(size)
            delete: list[int] = []
            for seq, byte_size in rows:
                if (
                    remaining_rows <= settings.ring_log_max_rows
                    and remaining_bytes <= settings.ring_log_max_bytes
                ):
                    break
                delete.append(int(seq))
                remaining_rows -= 1
                remaining_bytes -= int(byte_size)
            if not delete:
                break
            self._delete_seqs(conn, delete)
            removed += len(delete)
        return removed

    @staticmethod
    def _delete_seqs(conn: sqlite3.Connection, seqs: list[int]) -> None:
        if not seqs:
            return
        placeholders = ",".join("?" for _ in seqs)
        conn.execute(f"DELETE FROM ring_logs WHERE seq IN ({placeholders})", seqs)

    # --------------------------------------------------------------- retention
    def get_retention_days(self) -> int:
        return self._retention_days

    def set_retention_days(self, days: int) -> int:
        self.flush()
        if isinstance(days, bool) or not isinstance(days, int):
            raise ValueError("保留天数必须是整数")
        if days < 1 or days > 365:
            raise ValueError("保留天数必须在 1~365 之间")
        with self._lock:
            with closing(self._connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO app_settings(key, value, updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                    "updated_at=excluded.updated_at",
                    ("log_retention_days", str(days), datetime.now(timezone.utc)),
                )
                conn.commit()
            self._retention_days = days
            return self.trim_retention(days)

    def trim_retention(self, days: int | None = None) -> int:
        if not self._initialized:
            return 0
        self.flush()
        retention = self._retention_days if days is None else max(1, min(365, int(days)))
        cutoff = int(
            (datetime.now(settings.timezone_info) - timedelta(days=retention)).timestamp()
        )
        removed = 0
        for _ in range(settings.ring_trim_max_loops):
            try:
                with self._lock:
                    with closing(self._connect()) as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        ids = conn.execute(
                            "SELECT seq FROM ring_logs WHERE created_at_epoch < ? "
                            "ORDER BY seq ASC LIMIT ?",
                            (cutoff, settings.ring_trim_batch_size),
                        ).fetchall()
                        if not ids:
                            self._trim_global(conn)
                            conn.commit()
                            break
                        self._delete_seqs(conn, [int(item[0]) for item in ids])
                        conn.commit()
                        removed += len(ids)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                time.sleep(0.05)
        if removed:
            logger.info("环形日志按保留期清理：%s 条（%s 天）", removed, retention)
        return removed

    # ------------------------------------------------------------------- reads
    def read_execution(
        self, log_id: int, after_seq: int = 0, limit: int | None = None
    ) -> list[RingLogEntry]:
        self.flush()
        sql = (
            "SELECT seq, level, text, created_at FROM ring_logs "
            "WHERE ref_type = 'execution' AND ref_id = ? AND seq > ? "
            "ORDER BY seq ASC"
        )
        params: list[object] = [log_id, max(0, int(after_seq))]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        try:
            with closing(self._connect()) as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            logger.warning("读取环形执行日志失败：%s", exc)
            return []
        return [
            {"seq": int(row[0]), "level": row[1], "text": row[2], "created_at": row[3]}
            for row in rows
        ]

    def read_execution_text(self, log_id: int) -> tuple[str, int]:
        rows = self.read_execution(log_id)
        return "".join(str(row["text"]) for row in rows), (
            int(rows[-1]["seq"]) if rows else 0
        )

    def read_scope(
        self, scope_type: str, scope_key: str, after_seq: int = 0
    ) -> list[RingScopeEntry]:
        self.flush()
        try:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    "SELECT seq, level, text, created_at, byte_size FROM ring_logs "
                    "WHERE scope_type = ? AND scope_key = ? AND seq > ? "
                    "ORDER BY seq ASC",
                    (scope_type, scope_key, max(0, int(after_seq))),
                ).fetchall()
        except sqlite3.Error:
            return []
        return [
            {
                "seq": int(row[0]),
                "level": row[1],
                "text": row[2],
                "created_at": row[3],
                "byte_size": int(row[4]),
            }
            for row in rows
        ]

    def read_page(
        self,
        *,
        page: int,
        page_size: int,
        scope_type: str | None = None,
        level: str | None = None,
    ) -> tuple[list[dict[str, object]], int]:
        self.flush()
        conditions: list[str] = []
        params: list[object] = []
        if scope_type:
            conditions.append("scope_type = ?")
            params.append(scope_type)
        if level:
            conditions.append("level = ?")
            params.append(level)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        offset = max(0, (page - 1) * page_size)
        with closing(self._connect()) as conn:
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM ring_logs{where}", params
                ).fetchone()[0]
            )
            rows = conn.execute(
                "SELECT seq, scope_type, scope_key, category, level, text, "
                f"created_at FROM ring_logs{where} ORDER BY seq DESC LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            ).fetchall()
        return (
            [
                {
                    "seq": int(row[0]),
                    "scope_type": row[1],
                    "scope_key": row[2],
                    "category": row[3],
                    "level": row[4],
                    "text": row[5],
                    "created_at": row[6],
                }
                for row in rows
            ],
            total,
        )

    def last_execution_seq(self, log_id: int) -> int:
        try:
            with closing(self._connect()) as conn:
                row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) FROM ring_logs "
                    "WHERE ref_type = 'execution' AND ref_id = ?",
                    (log_id,),
                ).fetchone()
            return int(row[0]) if row else 0
        except sqlite3.Error:
            return 0

    def delete_execution(self, log_id: int) -> int:
        try:
            with self._lock:
                with closing(self._connect()) as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    result = conn.execute(
                        "DELETE FROM ring_logs WHERE ref_type = 'execution' AND ref_id = ?",
                        (log_id,),
                    )
                    conn.commit()
                    return result.rowcount or 0
        except sqlite3.Error:
            return 0

    def delete_execution_ids(self, ids: Iterable[int]) -> int:
        values = [int(item) for item in ids]
        if not values:
            return 0
        try:
            with self._lock:
                with closing(self._connect()) as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    placeholders = ",".join("?" for _ in values)
                    result = conn.execute(
                        f"DELETE FROM ring_logs WHERE ref_type = 'execution' "
                        f"AND ref_id IN ({placeholders})",
                        values,
                    )
                    conn.commit()
                    return result.rowcount or 0
        except sqlite3.Error:
            return 0

    def stats(self) -> dict[str, object]:
        self.flush()
        try:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    "SELECT scope_type, COUNT(*), COALESCE(SUM(byte_size), 0) "
                    "FROM ring_logs GROUP BY scope_type"
                ).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(byte_size), 0) FROM ring_logs"
                ).fetchone()
                last = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) FROM ring_logs"
                ).fetchone()
        except sqlite3.Error:
            return {"retention_days": self._retention_days, "total_rows": 0, "total_bytes": 0, "last_seq": 0, "scopes": []}
        return {
            "retention_days": self._retention_days,
            "total_rows": int(total[0]),
            "total_bytes": int(total[1]),
            "last_seq": int(last[0]),
            "queue_depth": self._queue.qsize(),
            "next_seq": self._next_seq,
            "writer_failed": self._writer_failed,
            "scopes": [
                {"scope_type": row[0], "rows": int(row[1]), "bytes": int(row[2])}
                for row in rows
            ],
        }

    # ---------------------------------------------------------------- helpers
    def append_system(self, level: str, text: str) -> int:
        return self.append(
            scope_type=_SCOPE_SYSTEM,
            scope_key=_SCOPE_SYSTEM,
            category="app",
            level=level,
            text=text,
        )

    def append_push(self, text: str, level: str = "INFO", ref_id: int | None = None) -> int:
        return self.append(
            scope_type=_SCOPE_PUSH,
            scope_key=_SCOPE_PUSH,
            category="push",
            level=level,
            text=text,
            ref_type="push" if ref_id is not None else None,
            ref_id=ref_id,
        )

    def append_execution(
        self,
        *,
        module_key: str,
        log_id: int,
        text: str,
        level: str = "INFO",
        created_at: datetime | None = None,
    ) -> int:
        return self.append(
            scope_type=_SCOPE_MODULE,
            scope_key=module_key or "unknown",
            category="execution",
            level=level,
            text=text,
            ref_type="execution",
            ref_id=log_id,
            created_at=created_at,
        )

    def _local_time(self, value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(settings.timezone_info)
        if value.tzinfo is None:
            return value.replace(tzinfo=settings.timezone_info)
        return value.astimezone(settings.timezone_info)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._path, timeout=settings.ring_busy_timeout_seconds, isolation_level=None, check_same_thread=False
        )
        conn.execute(f"PRAGMA busy_timeout={int(settings.ring_busy_timeout_seconds * 1000)}")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn


ring_log = RingLogStore()
