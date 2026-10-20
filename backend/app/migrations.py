"""Small forward-only schema migrations for existing installations.

The project intentionally stays migration-framework-free.  SQLite only supports
a limited set of ALTER TABLE operations, but adding nullable columns is enough
for this release.  Fresh databases are created by SQLAlchemy and need no work.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from .database import SessionLocal, engine
from .models import Module
from .scheduling import ScheduleError, normalize_legacy_cycle

logger = logging.getLogger(__name__)

_LEGACY_COLUMNS: dict[str, str] = {
    "default_start_time": "VARCHAR(5)",
    "default_end_time": "VARCHAR(5)",
    "default_repeat_cycle": "VARCHAR(20)",
    "default_repeat_sub_value": "VARCHAR(10)",
    "start_time": "VARCHAR(5)",
    "end_time": "VARCHAR(5)",
    "repeat_cycle": "VARCHAR(20)",
    "repeat_sub_value": "VARCHAR(10)",
    "multi_account": "BOOLEAN",
    "push_enabled": "BOOLEAN",
    "accounts_encrypted": "TEXT",
    "push_independent": "BOOLEAN",
    "push_unified": "BOOLEAN",
}


def _legacy_window(cron: str | None) -> tuple[str, str]:
    parts = (cron or "").split()
    if len(parts) == 5 and parts[0].isdigit() and parts[1].isdigit():
        minute = int(parts[0])
        hour = int(parts[1])
        if 0 <= minute <= 59 and 0 <= hour <= 23:
            start = hour * 60 + minute
            end = min(23 * 60 + 59, start + 60)
            if end <= start:
                start = max(0, end - 1)
            return (
                f"{start // 60:02d}:{start % 60:02d}",
                f"{end // 60:02d}:{end % 60:02d}",
            )
    return "08:00", "10:00"


async def migrate_schema() -> None:
    """Add random-schedule / multi-account columns to an existing SQLite DB."""
    if engine.dialect.name != "sqlite":
        return

    async with engine.begin() as connection:
        result = await connection.exec_driver_sql("PRAGMA table_info(modules)")
        columns = {row[1] for row in result.fetchall()}
        added: list[str] = []
        for name, ddl_type in _LEGACY_COLUMNS.items():
            if name in columns:
                continue
            await connection.exec_driver_sql(
                f'ALTER TABLE modules ADD COLUMN "{name}" {ddl_type}'
            )
            added.append(name)
        if added:
            logger.info("数据库迁移：为 modules 添加字段 %s", ", ".join(added))

        # Push tables were introduced in the same release line; add columns
        # for databases that already have them from an earlier RC build.
        for table, columns in (
            ("push_batches", {"idempotency_key": "VARCHAR(120)"}),
            ("push_records", {"idempotency_key": "VARCHAR(160)"}),
        ):
            result = await connection.exec_driver_sql(f"PRAGMA table_info({table})")
            existing = {row[1] for row in result.fetchall()}
            if not existing:
                continue
            for name, ddl_type in columns.items():
                if name not in existing:
                    await connection.exec_driver_sql(
                        f'ALTER TABLE {table} ADD COLUMN "{name}" {ddl_type}'
                    )
            await connection.exec_driver_sql(
                f'CREATE UNIQUE INDEX IF NOT EXISTS "ix_{table}_{list(columns)[0]}" '
                f'ON {table} ("{list(columns)[0]}")'
            )
    async with SessionLocal() as db:
        rows = (await db.execute(select(Module))).scalars().all()
        changed = 0
        migrated_cycles: list[str] = []
        for row in rows:
            legacy_start, legacy_end = _legacy_window(row.cron)
            row_changed = False
            if not row.start_time:
                row.start_time = legacy_start
                row_changed = True
            if not row.end_time:
                row.end_time = legacy_end
                row_changed = True
            if not row.repeat_cycle:
                row.repeat_cycle = "daily"
                row_changed = True
            if not row.default_start_time:
                row.default_start_time = row.start_time
                row_changed = True
            if not row.default_end_time:
                row.default_end_time = row.end_time
                row_changed = True
            if not row.default_repeat_cycle:
                row.default_repeat_cycle = row.repeat_cycle
                row_changed = True
            if row.multi_account is None:
                row.multi_account = False
                row_changed = True
            if row.push_enabled is None:
                row.push_enabled = False
                row_changed = True
            if row.push_independent is None:
                row.push_independent = bool(row.push_enabled)
                row_changed = True
            if row.push_unified is None:
                row.push_unified = False
                row_changed = True

            old_cycle = row.repeat_cycle or "daily"
            old_sub = row.repeat_sub_value
            try:
                new_cycle, new_sub = normalize_legacy_cycle(old_cycle, old_sub)
            except ScheduleError:
                logger.warning(
                    "旧周期迁移失败：模块 %s 的周期 %s 无效，降级为每月 1 日",
                    row.key,
                    old_cycle,
                )
                new_cycle, new_sub = "monthly", "1"
            if new_cycle != old_cycle or row.repeat_sub_value != new_sub:
                if old_cycle in {"half_month", "quarterly"}:
                    migrated_cycles.append(f"{row.key}: {old_cycle} -> {new_cycle}/{new_sub}")
                row.repeat_cycle = new_cycle
                row.repeat_sub_value = new_sub
                row_changed = True

            old_default_cycle = row.default_repeat_cycle or "daily"
            old_default_sub = row.default_repeat_sub_value
            try:
                new_default_cycle, new_default_sub = normalize_legacy_cycle(
                    old_default_cycle, old_default_sub
                )
            except ScheduleError:
                new_default_cycle, new_default_sub = "monthly", "1"
            if (
                new_default_cycle != old_default_cycle
                or row.default_repeat_sub_value != new_default_sub
            ):
                if old_default_cycle in {"half_month", "quarterly"}:
                    migrated_cycles.append(
                        f"{row.key} default: {old_default_cycle} -> "
                        f"{new_default_cycle}/{new_default_sub}"
                    )
                row.default_repeat_cycle = new_default_cycle
                row.default_repeat_sub_value = new_default_sub
                row_changed = True

            if row_changed:
                changed += 1
        if migrated_cycles:
            logger.warning("旧周期迁移：%s", "；".join(migrated_cycles))
        if changed:
            await db.commit()
            logger.info("数据库迁移：已补齐 %s 个模块的随机调度字段", changed)
