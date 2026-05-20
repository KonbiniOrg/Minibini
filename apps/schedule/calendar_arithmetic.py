"""Pure-function calendar arithmetic for the schedule view.

No Django model imports. Inputs are dates / times / datetimes and a DayShape;
outputs are datetimes or lists of (datetime, datetime) tuples. All math is
local to the timezone of the input datetimes — callers are responsible for
ensuring timezone consistency.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.utils import timezone as _tz


@dataclass(frozen=True)
class DayShape:
    workday_start: time
    workday_end: time
    lunch_start: time
    lunch_end: time
    task_buffer_minutes: int

    @classmethod
    def default(cls):
        return cls(
            workday_start=time(8, 0),
            workday_end=time(17, 0),
            lunch_start=time(12, 0),
            lunch_end=time(13, 0),
            task_buffer_minutes=10,
        )


def _combine_local(d: date, t: time) -> datetime:
    """Combine a date and a time in the current Django timezone."""
    naive = datetime.combine(d, t)
    return _tz.make_aware(naive, _tz.get_current_timezone())


def is_working_day(d: date) -> bool:
    """True if `d` is a working day. v1: Mon–Fri only (hardcoded weekend)."""
    return d.weekday() < 5


def workday_start_on(d: date, shape: DayShape) -> datetime:
    return _combine_local(d, shape.workday_start)


def workday_end_on(d: date, shape: DayShape) -> datetime:
    return _combine_local(d, shape.workday_end)


def lunch_window_on(d: date, shape: DayShape) -> tuple:
    return (
        _combine_local(d, shape.lunch_start),
        _combine_local(d, shape.lunch_end),
    )


def next_workable_moment(dt: datetime, shape: DayShape) -> datetime:
    """Return the next moment at or after `dt` when work is allowed.

    Skips: weekends, time before workday_start, time after workday_end, lunch.
    """
    while True:
        d = dt.date()
        if not is_working_day(d):
            next_d = d + timedelta(days=1)
            while not is_working_day(next_d):
                next_d += timedelta(days=1)
            dt = workday_start_on(next_d, shape)
            continue

        wd_start = workday_start_on(d, shape)
        wd_end = workday_end_on(d, shape)
        lunch_a, lunch_b = lunch_window_on(d, shape)

        if dt < wd_start:
            dt = wd_start
            continue
        if dt >= wd_end:
            next_d = d + timedelta(days=1)
            while not is_working_day(next_d):
                next_d += timedelta(days=1)
            dt = workday_start_on(next_d, shape)
            continue
        if lunch_a <= dt < lunch_b:
            dt = lunch_b
            continue
        return dt


def add_work_time(
    start: datetime, work_duration: timedelta, shape: DayShape,
) -> datetime:
    """Add `work_duration` of work-time (skipping lunch/overnight/weekend)
    to `start` and return the resulting wall-clock datetime.

    If `start` is not in a workable moment, it is first advanced to the
    next workable moment, then the duration is added.
    """
    cursor = next_workable_moment(start, shape)
    remaining = work_duration
    while remaining > timedelta(0):
        d = cursor.date()
        wd_end = workday_end_on(d, shape)
        lunch_a, lunch_b = lunch_window_on(d, shape)

        # How much work time is available in this stretch (before lunch or
        # before EOD, whichever comes first)?
        if cursor < lunch_a:
            stretch_end = lunch_a
        else:
            stretch_end = wd_end

        available = stretch_end - cursor
        if remaining <= available:
            return cursor + remaining

        remaining -= available
        cursor = next_workable_moment(stretch_end, shape)
    return cursor


def segments_for(
    start: datetime, end: datetime, shape: DayShape,
) -> list:
    """Split [start, end] at every lunch / overnight / non-working boundary.

    Returns a list of (seg_start, seg_end) tuples, each within a single
    working stretch. Returns [] if start >= end.
    """
    if start >= end:
        return []
    segments = []
    cursor = next_workable_moment(start, shape)
    while cursor < end:
        d = cursor.date()
        wd_end = workday_end_on(d, shape)
        lunch_a, lunch_b = lunch_window_on(d, shape)

        if cursor < lunch_a:
            stretch_end = lunch_a
        else:
            stretch_end = wd_end

        seg_end = min(end, stretch_end)
        if seg_end > cursor:
            segments.append((cursor, seg_end))

        if seg_end >= end:
            break
        cursor = next_workable_moment(stretch_end, shape)
    return segments


def work_minutes_between(a: datetime, b: datetime, shape: DayShape) -> int:
    """Total work-time minutes between `a` and `b`. Zero if b <= a."""
    if b <= a:
        return 0
    total = timedelta(0)
    for seg_start, seg_end in segments_for(a, b, shape):
        total += seg_end - seg_start
    return int(total.total_seconds() // 60)
