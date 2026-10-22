"""Pure helpers for per-cycle random execution windows.

Canonical repeat cycles (iteration 4):

* daily      -> every day
* weekly     -> a selected weekday (1=Monday ... 7=Sunday)
* monthly_15 -> the 15th of every month
* monthly    -> a selected day 1..28 of every month
* yearly     -> a selected month-day (February 29 is allowed; non-leap years
                simply have no occurrence and the next leap year is used)

The execution happens on the occurrence day, at a random time inside the
same-day [start_time, end_time] window.  A window never spans midnight.
"""

from __future__ import annotations

import calendar
import random
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

REPEAT_CYCLES = (
    "daily",
    "weekly",
    "monthly_15",
    "monthly",
    "yearly",
)

CYCLE_LABELS = {
    "daily": "每日",
    "weekly": "每周",
    "monthly_15": "每月15日",
    "monthly": "每月",
    "yearly": "每年",
}

WEEKDAY_LABELS = {
    1: "周一",
    2: "周二",
    3: "周三",
    4: "周四",
    5: "周五",
    6: "周六",
    7: "周日",
}

LEGACY_CYCLE_MAP = {
    "half_month": "monthly",
    "quarterly": "monthly",
}

DEFAULT_SUB_VALUES = {
    "daily": "",
    "weekly": "1",
    "monthly_15": "",
    "monthly": "1",
    "yearly": "1-1",
}

_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_YEAR_SUB_RE = re.compile(r"^(\d{1,2})-(\d{1,2})$")


class ScheduleError(ValueError):
    """Invalid schedule configuration."""


def parse_hhmm(value: str | None, field_label: str = "时间") -> tuple[int, int]:
    text = (value or "").strip()
    if not _TIME_RE.fullmatch(text):
        raise ScheduleError(f"{field_label}必须使用 24 小时制 HH:mm 格式，例如 09:30")
    hour, minute = text.split(":", 1)
    return int(hour), int(minute)


def validate_time_value(value: str | None, field_label: str = "时间") -> str:
    hour, minute = parse_hhmm(value, field_label)
    return f"{hour:02d}:{minute:02d}"


def validate_repeat_cycle(value: str | None) -> str:
    cycle = (value or "").strip().lower()
    if cycle in LEGACY_CYCLE_MAP:
        cycle = LEGACY_CYCLE_MAP[cycle]
    if cycle not in REPEAT_CYCLES:
        raise ScheduleError("重复周期无效，可选值：" + "、".join(REPEAT_CYCLES))
    return cycle


def normalize_repeat_sub_value(cycle: str, value: object = None) -> str:
    """Normalize a sub-option for a canonical cycle.

    Storage format:
      weekly      -> "1".."7" (ISO: Monday=1)
      monthly     -> "1".."28"
      yearly      -> "M-D" (no leading zeros; February 29 is valid)
      daily / monthly_15 -> ""
    """
    cycle = validate_repeat_cycle(cycle)
    text = str(value or "").strip()
    if cycle in {"daily", "monthly_15"}:
        return ""
    if cycle == "weekly":
        try:
            number = int(text or DEFAULT_SUB_VALUES[cycle])
        except ValueError as exc:
            raise ScheduleError("每周子选项必须是 1-7（周一至周日）") from exc
        if not 1 <= number <= 7:
            raise ScheduleError("每周子选项必须是 1-7（周一至周日）")
        return str(number)
    if cycle == "monthly":
        try:
            number = int(text or DEFAULT_SUB_VALUES[cycle])
        except ValueError as exc:
            raise ScheduleError("每月日期必须是 1-28") from exc
        if not 1 <= number <= 28:
            raise ScheduleError("每月日期必须是 1-28（固定上限 28）")
        return str(number)
    # yearly
    if not text:
        return DEFAULT_SUB_VALUES["yearly"]
    match = _YEAR_SUB_RE.fullmatch(text)
    if not match:
        raise ScheduleError("每年子选项必须使用 M-D 格式，例如 1-1 或 12-31")
    month, day = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise ScheduleError("月份必须在 1-12 之间")
    max_day = calendar.monthrange(2000, month)[1]  # 2000 is a leap year
    if not 1 <= day <= max_day:
        raise ScheduleError(f"{month} 月日期必须在 1-{max_day} 之间")
    return f"{month}-{day}"


def normalize_legacy_cycle(
    cycle: str | None, sub_value: object = None
) -> tuple[str, str]:
    """Map removed cycles to the new monthly + default-1st representation."""
    raw = (cycle or "").strip().lower()
    mapped = LEGACY_CYCLE_MAP.get(raw, raw)
    if mapped not in REPEAT_CYCLES:
        raise ScheduleError("重复周期无效")
    if raw in LEGACY_CYCLE_MAP:
        return "monthly", "1"
    return mapped, normalize_repeat_sub_value(mapped, sub_value)


def repeat_sub_label(cycle: str, sub_value: object = None) -> str:
    normalized_cycle = validate_repeat_cycle(cycle)
    sub = normalize_repeat_sub_value(normalized_cycle, sub_value)
    if normalized_cycle == "daily":
        return "每天"
    if normalized_cycle == "weekly":
        return f"每{WEEKDAY_LABELS[int(sub)]}"
    if normalized_cycle == "monthly_15":
        return "每月15日"
    if normalized_cycle == "monthly":
        return f"每月{sub}日"
    month, day = sub.split("-", 1)
    return f"每年{int(month)}月{int(day)}日"


def validate_schedule(
    start_time: str | None,
    end_time: str | None,
    repeat_cycle: str | None,
    repeat_sub_value: object = None,
) -> tuple[str, str, str, str]:
    start = validate_time_value(start_time, "开始时间")
    end = validate_time_value(end_time, "结束时间")
    cycle, sub = normalize_legacy_cycle(repeat_cycle, repeat_sub_value)
    if start >= end:
        raise ScheduleError("开始时间必须早于结束时间（时间窗不能跨天）")
    return start, end, cycle, sub


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    day_number = min(day.day, calendar.monthrange(year, month)[1])
    return date(year, month, day_number)


def _yearly_parts(sub: str) -> tuple[int, int]:
    month, day = sub.split("-", 1)
    return int(month), int(day)


def _valid_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def period_start_for(
    cycle: str, day: date, repeat_sub_value: object = None
) -> date:
    """Return the most recent occurrence date on or before ``day``.

    For daily this is the day itself.  For a weekly/monthly/yearly selection it
    is the latest selected occurrence (which may be in a previous week/month/
    year).  Schedulers use ``period_start_for(...) == day`` to decide whether an
    execution should happen today.
    """
    cycle = validate_repeat_cycle(cycle)
    sub = normalize_repeat_sub_value(cycle, repeat_sub_value)
    if cycle == "daily":
        return day
    if cycle == "weekly":
        delta = (day.weekday() + 1 - int(sub)) % 7
        return day - timedelta(days=delta)
    if cycle == "monthly_15":
        if day.day >= 15:
            return day.replace(day=15)
        return _add_months(day.replace(day=1), -1).replace(day=15)
    if cycle == "monthly":
        day_number = int(sub)
        if day.day >= day_number:
            return day.replace(day=day_number)
        return _add_months(day.replace(day=1), -1).replace(day=day_number)
    # yearly
    month, day_number = _yearly_parts(sub)
    for year in range(day.year, day.year - 16, -1):
        candidate = _valid_date(year, month, day_number)
        if candidate is not None and candidate <= day:
            return candidate
    raise ScheduleError("无法计算年度周期")


def next_period_start(
    cycle: str, period_start: date, repeat_sub_value: object = None
) -> date:
    """Return the next occurrence strictly after ``period_start``."""
    cycle = validate_repeat_cycle(cycle)
    sub = normalize_repeat_sub_value(cycle, repeat_sub_value)
    if cycle == "daily":
        return period_start + timedelta(days=1)
    if cycle == "weekly":
        return period_start + timedelta(days=7)
    if cycle == "monthly_15":
        return _add_months(period_start.replace(day=1), 1).replace(day=15)
    if cycle == "monthly":
        return _add_months(period_start.replace(day=1), 1).replace(
            day=int(sub)
        )
    # yearly: skip invalid dates such as February 29 in non-leap years.
    month, day_number = _yearly_parts(sub)
    year = period_start.year + 1
    for _ in range(16):
        candidate = _valid_date(year, month, day_number)
        if candidate is not None:
            return candidate
        year += 1
    raise ScheduleError("无法计算下一个年度周期")


def is_cycle_start(
    cycle: str, day: date, repeat_sub_value: object = None
) -> bool:
    return period_start_for(cycle, day, repeat_sub_value) == day


def next_occurrence(
    cycle: str, start_day: date, repeat_sub_value: object = None
) -> date:
    """Return the first occurrence on or after ``start_day``."""
    candidate = period_start_for(cycle, start_day, repeat_sub_value)
    if candidate < start_day:
        candidate = next_period_start(cycle, candidate, repeat_sub_value)
    return candidate


def current_period_start(
    cycle: str,
    tz: ZoneInfo,
    now: datetime | None = None,
    repeat_sub_value: object = None,
) -> date:
    local_now = (now or datetime.now(timezone.utc)).astimezone(tz)
    return period_start_for(cycle, local_now.date(), repeat_sub_value)


def _at_local(day: date, hhmm: str, tz: ZoneInfo) -> datetime:
    hour, minute = parse_hhmm(hhmm)
    return datetime.combine(day, time(hour, minute), tzinfo=tz)


def schedule_window(
    period_start: date,
    start_time: str,
    end_time: str,
    tz: ZoneInfo,
) -> tuple[datetime, datetime]:
    start = _at_local(period_start, start_time, tz)
    end = _at_local(period_start, end_time, tz)
    if start >= end:
        raise ScheduleError("开始时间必须早于结束时间")
    return start, end


def midpoint_scheduled_at(
    period_start: date,
    start_time: str,
    end_time: str,
    tz: ZoneInfo,
) -> datetime:
    start, end = schedule_window(period_start, start_time, end_time, tz)
    midpoint = start + (end - start) / 2
    return midpoint.astimezone(timezone.utc)


def random_scheduled_at(
    period_start: date,
    start_time: str,
    end_time: str,
    tz: ZoneInfo,
    *,
    now: datetime | None = None,
    min_lead_seconds: int = 5,
) -> datetime | None:
    """Generate a UTC datetime uniformly inside the period's local time window.

    At the normal 00:00 occurrence start the whole [start, end] window is used.
    If recovery happens after ``start`` but before ``end``, the lower bound is
    moved forward so the generated time is still in the future. Returns None
    when the window has ended.
    """
    current = (now or datetime.now(timezone.utc)).astimezone(tz)
    if period_start < current.date():
        return None
    start, end = schedule_window(period_start, start_time, end_time, tz)

    if period_start > current.date():
        lower = start
    else:
        if current >= end:
            return None
        lower = start
        earliest = current + timedelta(seconds=max(0, min_lead_seconds))
        if earliest > lower:
            lower = earliest
            if lower >= end:
                # The window is almost over; schedule as soon as possible.
                lower = current + timedelta(seconds=1)
                if lower >= end:
                    return None

    span_seconds = max(0, int((end - lower).total_seconds()))
    if span_seconds <= 0:
        return None
    chosen = lower + timedelta(
        seconds=random.SystemRandom().randint(0, span_seconds)
    )
    return chosen.astimezone(timezone.utc)


def next_plan_at(
    cycle: str,
    tz: ZoneInfo,
    now: datetime | None = None,
    repeat_sub_value: object = None,
) -> datetime:
    """The next local 00:00 occurrence after today."""
    local_now = (now or datetime.now(timezone.utc)).astimezone(tz)
    occurrence = next_occurrence(
        cycle, local_now.date() + timedelta(days=1), repeat_sub_value
    )
    return datetime.combine(occurrence, time.min, tzinfo=tz)


def readable_window(
    start_time: str,
    end_time: str,
    cycle: str,
    repeat_sub_value: object = None,
) -> str:
    return (
        f"{repeat_sub_label(cycle, repeat_sub_value)} "
        f"{start_time}–{end_time} 随机执行"
    )


def execution_day_status(
    cycle: str, day: date, repeat_sub_value: object = None
) -> tuple[bool, str]:
    """Return whether ``day`` is an execution day and the skip reason.

    The reason is used verbatim in the unified push pool, so non-leap February
    29 has the specific label required by the product rules.
    """
    normalized = validate_repeat_cycle(cycle)
    sub = normalize_repeat_sub_value(normalized, repeat_sub_value)
    if normalized == "yearly" and sub == "2-29" and not calendar.isleap(day.year):
        return False, "本年无执行日"
    try:
        due = period_start_for(normalized, day, sub) == day
    except ScheduleError:
        due = False
    return (True, "") if due else (False, "当日不在执行周期")
