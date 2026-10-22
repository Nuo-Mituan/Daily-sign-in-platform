"""Push plan: side-effect-free timing calculations."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from ..config import settings
from ..scheduling import ScheduleError, parse_hhmm
from .push_time import business_date as business_date, cycle_id_for as cycle_id_for

__all__ = ["business_date", "cycle_id_for", "latest_trigger", "timeout_at", "configure_daily_batch"]


def latest_trigger(times: list[datetime]) -> datetime | None:
    """Return max(times) + 1 minute in UTC; None for empty input."""
    if not times:
        return None
    return (max(times) + timedelta(minutes=1)).astimezone(timezone.utc)


def timeout_at(
    cycle_id: str, trigger_at: datetime | None, data: dict[str, object]
) -> datetime | None:
    """Optional fallback time; disabled, missing, or earlier => None."""
    if not bool(data.get("timeout_enabled")) or trigger_at is None:
        return None
    try:
        hour, minute = parse_hhmm(str(data.get("timeout_time", "23:30")))
    except ScheduleError:
        hour, minute = 23, 30
    candidate = datetime.combine(
        date.fromisoformat(cycle_id),
        time(hour, minute),
        tzinfo=settings.timezone_info,
    ).astimezone(timezone.utc)
    return candidate if candidate > trigger_at.astimezone(timezone.utc) else None


def configure_daily_batch(
    cycle_id: str,
    scheduled_times: list[datetime],
    timeout_settings: dict[str, object],
) -> dict[str, datetime | None]:
    """Pure planning result; persistence and scheduler cleanup are facade work."""
    trigger = latest_trigger(scheduled_times)
    return {
        "trigger_at": trigger,
        "timeout_at": timeout_at(cycle_id, trigger, timeout_settings),
    }


# Backward-compatible alias used by delivery and tests.
_timeout_at_for_cycle = timeout_at
