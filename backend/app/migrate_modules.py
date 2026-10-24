"""One-off, idempotent migration for renamed module directories.

Usage:
    python -m app.migrate_modules --dry-run
    python -m app.migrate_modules --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field

from sqlalchemy import select

from .database import SessionLocal, dispose_db, init_db
from .models import Module
from .module_loader import scan_modules


@dataclass
class MigrationReport:
    migrated: list[dict[str, str]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    conflicts: list[dict[str, str]] = field(default_factory=list)


async def migrate_modules(
    dry_run: bool = True,
    mappings: dict[str, str] | None = None,
) -> MigrationReport:
    await init_db()
    report = MigrationReport()
    scanned = scan_modules()
    async with SessionLocal() as db:
        rows = (await db.execute(select(Module))).scalars().all()
        mapping = mappings or {}
        by_directory = {item.key: item for item in scanned}

        def target_for(row: Module) -> tuple[str, str] | None:
            if row.key in mapping:
                return mapping[row.key], "explicit --map"
            item = next((it for it in scanned if it.key == row.directory_name), None)
            if item is not None and item.config is not None:
                return item.key, "directory_name"
            candidates = [
                it for it in scanned
                if it.config is not None
                and it.key != row.key
                and it.key not in {r.directory_name for r in rows if r.directory_name}
            ]
            if row.directory_name:
                return row.directory_name, "existing directory_name"
            return None

        if mapping:
            for old_key, directory in mapping.items():
                row = next((r for r in rows if r.key == old_key), None)
                item = by_directory.get(directory)
                if row is None or item is None:
                    report.skipped.append(
                        {"old_key": old_key, "directory": directory,
                         "reason": "记录或物理目录不存在"}
                    )
                    continue
                if any(
                    other.key != row.key and other.directory_name == directory
                    for other in rows
                ):
                    report.conflicts.append(
                        {"old_key": row.key, "directory": directory,
                         "reason": "目标目录已被其他记录占用"}
                    )
                    continue
                before = row.directory_name
                report.migrated.append(
                    {"old_key": row.key, "directory": directory,
                     "before": before, "after": directory,
                     "matched_by": "explicit --map"}
                )
                if not dry_run:
                    row.directory_name = directory
                    row.legacy_key = row.key
                    row.load_error = None
            if not dry_run:
                await db.commit()
            await dispose_db()
            return report

        for item in scanned:
            config = item.config
            if config is None or not config.directory_name:
                continue
            candidates = [
                row
                for row in rows
                if row.key != item.key
                and row.directory_name is None
                and row.name == config.name
            ]
            if len(candidates) > 1:
                report.conflicts.append(
                    {
                        "directory": item.key,
                        "reason": "多个同名、未关联的数据库记录",
                        "candidates": ",".join(row.key for row in candidates),
                    }
                )
                continue
            if not candidates:
                report.skipped.append(
                    {"directory": item.key, "reason": "没有可安全关联的旧记录"}
                )
                continue
            row = candidates[0]
            if any(
                other.key != row.key and other.directory_name == item.key
                for other in rows
            ):
                report.conflicts.append(
                    {"directory": item.key, "old_key": row.key,
                     "reason": "目标目录已被其他记录占用"}
                )
                continue
            report.migrated.append(
                {
                    "directory": item.key,
                    "old_key": row.key,
                    "before": row.directory_name,
                    "after": item.key,
                    "matched_by": "unique name",
                }
            )
            if not dry_run:
                row.directory_name = item.key
                row.legacy_key = row.key
                row.load_error = None
        if not dry_run:
            await db.commit()
    await dispose_db()
    return report


async def _main() -> None:
    parser = argparse.ArgumentParser(description="迁移模块物理目录与 API key")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只输出报告，不写数据库")
    mode.add_argument("--apply", action="store_true", help="执行迁移")
    args = parser.parse_args()
    report = await migrate_modules(dry_run=not args.apply)
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "migrated": report.migrated,
                "skipped": report.skipped,
                "conflicts": report.conflicts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(_main())
