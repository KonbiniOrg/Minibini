"""Pure-function calendar arithmetic for the schedule view.

No Django model imports. Inputs are dates / times / datetimes and a
WeekEnvelope; outputs are datetimes or lists of segments. All math is
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


def _combine_local(d: date, t: time) -> datetime:
    """Combine a date and a time in the current Django timezone."""
    naive = datetime.combine(d, t)
    return _tz.make_aware(naive, _tz.get_current_timezone())


def is_working_day(d: date, env: WeekEnvelope) -> bool:
    """True if the envelope has any working interval on `d`."""
    return env.is_working_day(d)


def shift_working_days(d: date, n: int, env: WeekEnvelope) -> date:
    """Return the date `n` working days from `d` under `env`. n > 0 moves
    forward, n < 0 moves backward, n == 0 returns `d` unchanged. Non-working
    days are stepped over without being counted. An all-off envelope returns
    `d` unchanged (there is nothing to count)."""
    if n == 0 or not any(env.days):
        return d
    step = 1 if n > 0 else -1
    remaining = abs(n)
    cur = d
    while remaining > 0:
        cur = cur + timedelta(days=step)
        if env.is_working_day(cur):
            remaining -= 1
    return cur


def next_workable_moment(dt: datetime, env: WeekEnvelope) -> datetime:
    """Return the next moment at or after `dt` when work is allowed under
    `env` — skipping days off, time before/after the day's intervals, and
    the gaps (breaks) between intervals.

    Raises ValueError for an all-off envelope (there is no workable moment;
    callers must guard — the schedule simply never forecasts such a worker).
    """
    if not any(env.days):
        raise ValueError('Envelope has no working time on any day.')
    while True:
        d = dt.date()
        for start_t, end_t in env.intervals_on(d):
            int_start = _combine_local(d, start_t)
            int_end = _combine_local(d, end_t)
            if dt < int_start:
                return int_start
            if dt < int_end:
                return dt
        # Past the last interval (or a day off) — start of the next day.
        dt = _combine_local(d + timedelta(days=1), time(0, 0))


def _interval_end_at(dt: datetime, env: WeekEnvelope) -> datetime:
    """End of the envelope interval containing `dt`. `dt` must be a workable
    moment (as returned by next_workable_moment)."""
    d = dt.date()
    for start_t, end_t in env.intervals_on(d):
        if _combine_local(d, start_t) <= dt < _combine_local(d, end_t):
            return _combine_local(d, end_t)
    raise ValueError(f'{dt} is not inside a working interval.')


def add_work_time(
    start: datetime, work_duration: timedelta, env: WeekEnvelope,
) -> datetime:
    """Add `work_duration` of work-time (skipping breaks/overnights/days off)
    to `start` and return the resulting wall-clock datetime.

    If `start` is not in a workable moment, it is first advanced to the
    next workable moment, then the duration is added.
    """
    cursor = next_workable_moment(start, env)
    remaining = work_duration
    while remaining > timedelta(0):
        int_end = _interval_end_at(cursor, env)
        available = int_end - cursor
        if remaining <= available:
            return cursor + remaining
        remaining -= available
        cursor = next_workable_moment(int_end, env)
    return cursor


def segments_for(
    start: datetime, end: datetime, env: WeekEnvelope,
) -> list:
    """Split [start, end] at every envelope boundary — overnight, day off,
    and the gaps between a day's intervals.

    Returns a list of (seg_start, seg_end) tuples, each within a single
    working interval. Returns [] if start >= end. Used for FORECAST bars —
    actuals use day_segments_clamped, which never splits at gaps.
    """
    if start >= end:
        return []
    segments = []
    cursor = next_workable_moment(start, env)
    while cursor < end:
        int_end = _interval_end_at(cursor, env)
        seg_end = min(end, int_end)
        if seg_end > cursor:
            segments.append((cursor, seg_end))
        if seg_end >= end:
            break
        cursor = next_workable_moment(int_end, env)
    return segments


def work_minutes_between(a: datetime, b: datetime, env: WeekEnvelope) -> int:
    """Total work-time minutes between `a` and `b`. Zero if b <= a."""
    if b <= a:
        return 0
    total = timedelta(0)
    for seg_start, seg_end in segments_for(a, b, env):
        total += seg_end - seg_start
    return int(total.total_seconds() // 60)


def day_segments_clamped(
    start: datetime, end: datetime, axis_start: time, axis_end: time,
) -> list:
    """Segment an ACTUAL (logged) interval for display: split ONLY at local
    midnight, clamp each piece to the display axis hours, and flag what got
    cut. Deliberately envelope-blind — logged work draws straight over
    breaks; the envelope is where work is planned, not a claim about where
    it happened.

    Returns a list of dicts:
        {'start': dt, 'end': dt, 'clipped_left': bool, 'clipped_right': bool}

    A piece entirely outside the axis is dropped. If NOTHING survives, one
    one-minute sliver is returned so the work stays visible: at `start` when
    it lies inside the axis (a just-started blep), otherwise hugging the
    axis edge nearest the work with the matching clipped flag.
    """
    if end < start:
        end = start
    # Split at local midnights.
    pieces = []
    cursor = start
    while True:
        next_midnight = _combine_local(cursor.date() + timedelta(days=1), time(0, 0))
        piece_end = min(end, next_midnight)
        pieces.append((cursor, piece_end))
        if piece_end >= end:
            break
        cursor = piece_end

    out = []
    for piece_start, piece_end in pieces:
        d = piece_start.date()
        lo = _combine_local(d, axis_start)
        hi = _combine_local(d, axis_end)
        seg_start = max(piece_start, lo)
        seg_end = min(piece_end, hi)
        if seg_end > seg_start:
            out.append({
                'start': seg_start,
                'end': seg_end,
                'clipped_left': piece_start < lo,
                'clipped_right': piece_end > hi,
            })
    if not out:
        # Visibility sliver — see docstring.
        first_start = pieces[0][0]
        d = first_start.date()
        lo = _combine_local(d, axis_start)
        hi = _combine_local(d, axis_end)
        if lo <= first_start < hi:
            out.append({
                'start': first_start,
                'end': first_start + timedelta(minutes=1),
                'clipped_left': False, 'clipped_right': False,
            })
        elif first_start >= hi:
            out.append({
                'start': hi - timedelta(minutes=1), 'end': hi,
                'clipped_left': False, 'clipped_right': True,
            })
        else:
            out.append({
                'start': lo, 'end': lo + timedelta(minutes=1),
                'clipped_left': True, 'clipped_right': False,
            })
    return out
