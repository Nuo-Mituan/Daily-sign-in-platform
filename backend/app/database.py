"""Async database engine, session factory and bootstrap helpers."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings
from .models import Base

logger = logging.getLogger(__name__)

_connect_args: dict[str, object] = {}
if settings.sqlalchemy_url.startswith("sqlite"):
    _connect_args = {"timeout": 30}

engine = create_async_engine(
    settings.sqlalchemy_url,
    echo=False,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


def _enable_sqlite_wal() -> None:
    """WAL greatly improves read/write concurrency for this small SQLite app."""
    if not settings.sqlalchemy_url.startswith("sqlite"):
        return
    db_file = settings.data_dir / "checkin.db"
    try:
        connection = sqlite3.connect(db_file, timeout=10)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
        finally:
            connection.close()
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        logger.warning("启用 SQLite WAL 失败：%s", exc)


async def init_db() -> None:
    _enable_sqlite_wal()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    # Local import avoids a database <-> migration import cycle.
    from .migrations import migrate_schema

    await migrate_schema()
    _secure_sqlite_files()
    # Ring tables/counter are part of the schema; initialization is idempotent
    # and also loads the Web-configured retention override.
    from .services.ring_log import ring_log

    ring_log.initialize()


def _secure_sqlite_files() -> None:
    """SQLite stores passwords/cookies-adjacent data; keep it owner-only."""
    if not settings.sqlalchemy_url.startswith("sqlite"):
        return
    for name in ("checkin.db", "checkin.db-wal", "checkin.db-shm"):
        path = settings.data_dir / name
        try:
            if path.exists():
                path.chmod(0o600)
        except OSError:  # pragma: no cover
            pass


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_db() -> None:
    await engine.dispose()
