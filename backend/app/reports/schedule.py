"""When is a schedule due next? Pure date maths, no database."""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

FREQUENCIES = ("daily", "weekly", "monthly")
PERIODS = (0, 7, 30, 90)            # 0 = all time
FORMATS = ("pdf", "csv")
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def parse_time(value: str) -> tuple[int, int]:
    m = _TIME.match(value or "")
    if not m:
        raise ValueError("Time must look like 08:30 (24-hour).")
    return int(m.group(1)), int(m.group(2))


def next_run(frequency: str, send_time: str, weekday: Optional[int], month_day: Optional[int],
             tz_name: str, after: datetime) -> datetime:
    """The first moment strictly after `after` (naive UTC) that matches the schedule, read on the
    `tz_name` clock. Returned as naive UTC, which is how it is stored."""
    tz = ZoneInfo(tz_name)
    hour, minute = parse_time(send_time)
    local = after.replace(tzinfo=timezone.utc).astimezone(tz)

    def at(day) -> datetime:
        # build from the wall-clock parts so a daylight-saving change cannot shift the time of day
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)

    if frequency == "daily":
        candidate = at(local)
        if candidate <= local:
            candidate = at(local + timedelta(days=1))
    elif frequency == "weekly":
        if weekday is None or not 0 <= weekday <= 6:
            raise ValueError("Pick a day of the week.")
        day = local + timedelta(days=(weekday - local.weekday()) % 7)
        candidate = at(day)
        if candidate <= local:
            candidate = at(day + timedelta(days=7))
    elif frequency == "monthly":
        if month_day is None or not 1 <= month_day <= 28:
            raise ValueError("Pick a day of the month between 1 and 28.")
        candidate = datetime(local.year, local.month, month_day, hour, minute, tzinfo=tz)
        if candidate <= local:
            year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
            candidate = datetime(year, month, month_day, hour, minute, tzinfo=tz)
    else:
        raise ValueError("Frequency must be daily, weekly or monthly.")
    return candidate.astimezone(timezone.utc).replace(tzinfo=None)


def describe(frequency: str, send_time: str, weekday: Optional[int], month_day: Optional[int]) -> str:
    if frequency == "daily":
        return f"Every day at {send_time}"
    if frequency == "weekly":
        return f"Every {WEEKDAYS[weekday or 0]} at {send_time}"
    return f"Day {month_day} of every month at {send_time}"
