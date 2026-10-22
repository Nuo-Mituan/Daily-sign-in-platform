"""Pure business-date and recurrence helpers shared by plan/state."""

from __future__ import annotations

from datetime import date, datetime

from ..config import settings
from ..models import Module
from ..scheduling import ScheduleError, execution_day_status


def business_date() -> date:
    return datetime.now(settings.timezone_info).date()


def cycle_id_for(day: date | None = None) -> str:
    return (day or business_date()).isoformat()


def module_due(module: Module, day: date) -> tuple[bool, str]:
    try:
        return execution_day_status(
            module.repeat_cycle, day, module.repeat_sub_value
        )
    except ScheduleError:
        return False, "当日不在执行周期"
