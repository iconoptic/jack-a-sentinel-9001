from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sentinel_recorder.config import ScheduleSettings

_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def is_allowed(dt_aware: datetime, schedule: ScheduleSettings) -> bool:
    """True when recording may start at this instant.

    The quiet window is ``quiet_start`` inclusive through ``quiet_end`` exclusive,
    on ``quiet_days``, in the schedule timezone. ``enabled = false`` always allows.
    """
    if not schedule.enabled:
        return True
    if dt_aware.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    local = dt_aware.astimezone(ZoneInfo(schedule.timezone))
    if _WEEKDAYS[local.weekday()] not in schedule.quiet_days:
        return True
    start, end = schedule.quiet_minutes()
    minute = local.hour * 60 + local.minute
    return not (start <= minute < end)
