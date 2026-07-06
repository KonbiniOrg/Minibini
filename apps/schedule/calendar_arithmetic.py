"""Pure-function calendar arithmetic for the schedule view.

No Django model imports. Inputs are dates / times / datetimes and a DayShape;
outputs are datetimes or lists of (datetime, datetime) tuples. All math is
local to the timezone of the input datetimes — callers are responsible for
ensuring timezone consistency.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.utils import timezone as _tz

# Canonical JSON day keys, index-aligned with date.weekday() (0 = Monday).
DAY_KEYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')

_HHMM_RE = re.compile(r'([01]\d|2[0-3]):([0-5]\d)')


def _parse_hhmm_strict(s):
    """Parse a zero-padded 'HH:MM' string to a time, or None if invalid."""
    if not isinstance(s, str):
        return None
    m = _HHMM_RE.fullmatch(s)
    if not m:
        return None
    return time(int(m.group(1)), int(m.group(2)))


def validate_week_envelope(data) -> list:
    """Validate a weekly-envelope JSON structure. Returns a list of error
    message strings — empty when valid.

    Canonical shape: a dict with exactly the seven DAY_KEYS; each value an
    ordered list of ["HH:MM", "HH:MM"] pairs (zero-padded, 00:00–23:59),
    start < end, strictly increasing across the day's boundaries — no
    overlaps, no zero-length intervals, no touching intervals (merge those
    instead). An empty list is a day off.
    """
    errors = []
    if not isinstance(data, dict):
        return ['Envelope must be an object with keys mon…sun.']
    missing = [k for k in DAY_KEYS if k not in data]
    extra = [k for k in data if k not in DAY_KEYS]
    if missing:
        errors.append(f"Missing day(s): {', '.join(missing)}.")
    if extra:
        errors.append(f"Unknown key(s): {', '.join(sorted(extra))}.")
    for key in DAY_KEYS:
        if key not in data:
            continue
        day = data[key]
        if not isinstance(day, list):
            errors.append(f'{key}: must be a list of ["HH:MM", "HH:MM"] intervals.')
            continue
        prev_end = None
        for i, interval in enumerate(day):
            if (not isinstance(interval, (list, tuple))
                    or len(interval) != 2):
                errors.append(f'{key}: interval {i + 1} must be a ["HH:MM", "HH:MM"] pair.')
                continue
            start = _parse_hhmm_strict(interval[0])
            end = _parse_hhmm_strict(interval[1])
            if start is None or end is None:
                errors.append(
                    f'{key}: interval {i + 1} has an invalid time '
                    f'(use zero-padded HH:MM, 00:00–23:59).'
                )
                continue
            if start >= end:
                errors.append(f'{key}: interval {i + 1} must end after it starts.')
                continue
            if prev_end is not None and start <= prev_end:
                errors.append(
                    f'{key}: intervals must be in order and must not overlap '
                    f'or touch — merge adjacent intervals instead.'
                )
            prev_end = end
    return errors


@dataclass(frozen=True)
class WeekEnvelope:
    """A weekly working pattern: 7 days (indexed by date.weekday(), 0=Mon),
    each an ordered tuple of (start, end) time pairs. Empty tuple = day off;
    gaps between intervals are breaks. This is where work is *planned* —
    actuals are never clipped by it."""

    days: tuple  # 7-tuple of tuples of (time, time)

    @classmethod
    def default(cls):
        workday = ((time(8, 0), time(17, 0)),)
        return cls(days=(workday,) * 5 + ((), ()))

    @classmethod
    def from_json(cls, data):
        """Build from the canonical JSON dict. Raises ValueError on invalid
        input (message = joined validation errors)."""
        errors = validate_week_envelope(data)
        if errors:
            raise ValueError(' '.join(errors))
        days = tuple(
            tuple(
                (_parse_hhmm_strict(start), _parse_hhmm_strict(end))
                for start, end in data[key]
            )
            for key in DAY_KEYS
        )
        return cls(days=days)

    def to_json(self) -> dict:
        return {
            key: [
                [start.strftime('%H:%M'), end.strftime('%H:%M')]
                for start, end in self.days[i]
            ]
            for i, key in enumerate(DAY_KEYS)
        }

    def intervals_on(self, d: date) -> tuple:
        return self.days[d.weekday()]

    def is_working_day(self, d: date) -> bool:
        return bool(self.days[d.weekday()])


@dataclass(frozen=True)
class DayShape:
    workday_start: time
    workday_end: time
    task_buffer_minutes: int

    @classmethod
    def default(cls):
        return cls(
            workday_start=time(8, 0),
            workday_end=time(17, 0),
            task_buffer_minutes=10,
        )


def _combine_local(d: date, t: time) -> datetime:
    """Combine a date and a time in the current Django timezone."""
    naive = datetime.combine(d, t)
    return _tz.make_aware(naive, _tz.get_current_timezone())


def is_working_day(d: date) -> bool:
    """True if `d` is a working day. v1: Mon–Fri only (hardcoded weekend)."""
    return d.weekday() < 5


def shift_working_days(d: date, n: int) -> date:
    """Return the date `n` working days from `d`. n > 0 moves forward, n < 0
    moves backward, n == 0 returns `d` unchanged. Non-working days are
    stepped over without being counted."""
    if n == 0:
        return d
    step = 1 if n > 0 else -1
    remaining = abs(n)
    cur = d
    while remaining > 0:
        cur = cur + timedelta(days=step)
        if is_working_day(cur):
            remaining -= 1
    return cur


def workday_start_on(d: date, shape: DayShape) -> datetime:
    return _combine_local(d, shape.workday_start)


def workday_end_on(d: date, shape: DayShape) -> datetime:
    return _combine_local(d, shape.workday_end)


def next_workable_moment(dt: datetime, shape: DayShape) -> datetime:
    """Return the next moment at or after `dt` when work is allowed.

    Skips: weekends, time before workday_start, time after workday_end. The
    workday is continuous (no lunch break — that returns with per-worker
    lunch later).
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

        if dt < wd_start:
            dt = wd_start
            continue
        if dt >= wd_end:
            next_d = d + timedelta(days=1)
            while not is_working_day(next_d):
                next_d += timedelta(days=1)
            dt = workday_start_on(next_d, shape)
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

        # Work time available before end of day (continuous workday).
        available = wd_end - cursor
        if remaining <= available:
            return cursor + remaining

        remaining -= available
        cursor = next_workable_moment(wd_end, shape)
    return cursor


def segments_for(
    start: datetime, end: datetime, shape: DayShape,
) -> list:
    """Split [start, end] at every overnight / non-working boundary.

    Returns a list of (seg_start, seg_end) tuples, each within a single
    working day. Returns [] if start >= end.
    """
    if start >= end:
        return []
    segments = []
    cursor = next_workable_moment(start, shape)
    while cursor < end:
        d = cursor.date()
        wd_end = workday_end_on(d, shape)

        seg_end = min(end, wd_end)
        if seg_end > cursor:
            segments.append((cursor, seg_end))

        if seg_end >= end:
            break
        cursor = next_workable_moment(wd_end, shape)
    return segments


def work_minutes_between(a: datetime, b: datetime, shape: DayShape) -> int:
    """Total work-time minutes between `a` and `b`. Zero if b <= a."""
    if b <= a:
        return 0
    total = timedelta(0)
    for seg_start, seg_end in segments_for(a, b, shape):
        total += seg_end - seg_start
    return int(total.total_seconds() // 60)
