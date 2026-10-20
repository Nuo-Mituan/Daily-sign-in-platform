"""Small time helpers. All timestamps are stored as UTC and rendered in the browser locale."""

from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_scheduler_datetime(value: datetime | None, tz: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    return value.astimezone(timezone.utc)


def today_bounds_utc(tz: ZoneInfo) -> tuple[datetime, datetime]:
    local_now = datetime.now(tz)
    start_local = datetime.combine(local_now.date(), time.min, tzinfo=tz)
    end_local = datetime.combine(local_now.date(), time.max, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def local_day_stamp(tz: ZoneInfo) -> str:
    return datetime.now(tz).strftime("%Y-%m-%d")
