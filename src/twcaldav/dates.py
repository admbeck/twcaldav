"""Date-only handling for DUE and DTSTART.

TaskWarrior has no date-only values: `due:2025-10-20` is midnight local time.
CalDAV dates without a time (VALUE=DATE) are read the same way, and values at
local midnight are written back as dates.
"""

import os
from datetime import UTC, date, datetime, time, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from twcaldav.logger import get_logger
from twcaldav.taskwarrior import to_utc

LOCALTIME = Path("/etc/localtime")


def local_timezone() -> tzinfo:
    """Return the system timezone.

    Uses the TZ environment variable, then /etc/localtime, then UTC.

    Returns:
        Timezone with daylight saving rules.
    """
    name = os.environ.get("TZ", "").removeprefix(":")
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            get_logger().warning(f"Unknown TZ '{name}', using /etc/localtime")
    try:
        with LOCALTIME.open("rb") as file:
            return ZoneInfo.from_file(file, key="localtime")
    except (OSError, ValueError):
        get_logger().warning("Cannot read /etc/localtime, using UTC")
        return UTC


def date_to_datetime(value: date, tz: tzinfo) -> datetime:
    """Return a date as midnight in a timezone.

    Args:
        value: Date without a time.
        tz: Timezone the date is in.

    Returns:
        Aware datetime at local midnight.
    """
    return datetime.combine(value, time(), tzinfo=tz)


def _is_local_midnight(value: datetime, tz: tzinfo) -> bool:
    """Return whether a datetime is exactly midnight in a timezone."""
    return to_utc(value).astimezone(tz).time() == time()


def ical_dates(
    due: datetime | None, dtstart: datetime | None, tz: tzinfo
) -> tuple[date | datetime | None, date | datetime | None]:
    """Return DUE and DTSTART as dates when they are local midnight.

    RFC 5545 requires DUE and DTSTART of one VTODO to have the same value
    type, so both become dates only when every value set is local midnight.

    Args:
        due: Due time.
        dtstart: Start time.
        tz: Local timezone.

    Returns:
        Due and start, as dates or unchanged.
    """
    values = [value for value in (due, dtstart) if value is not None]
    if not values or not all(_is_local_midnight(value, tz) for value in values):
        return due, dtstart

    def as_date(value: datetime | None) -> date | None:
        return to_utc(value).astimezone(tz).date() if value else None

    return as_date(due), as_date(dtstart)
