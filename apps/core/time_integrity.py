"""Pure helpers enforcing the shift<->blep enclosure invariant.

Invariant: every Blep must be fully enclosed by a Shift of the same user
(shift.start <= blep.start and blep.end <= shift.end). Bleps and shifts are
related by time overlap, not an FK. No function here writes to the DB.
"""
from apps.jobs.models import Blep


def _candidate_bleps(user, span_start, span_end):
    """Closed bleps of `user` that overlap [span_start, span_end]."""
    return Blep.objects.filter(
        user=user,
        end_time__isnull=False,
        start_time__lt=span_end,
        end_time__gt=span_start,
    )


def unenclosed_bleps_for_shift(user, shift_start, shift_end, exclude_shift=None,
                               also_span=None):
    """Return this user's bleps that a shift spanning [shift_start, shift_end]
    would fail to enclose.

    Candidates are bleps overlapping the proposed span - plus, when editing an
    existing shift, the original span (`also_span`) so a blep shrunk *out* of the
    shift is still caught. A candidate conflicts unless fully inside the new span.
    """
    span_start, span_end = shift_start, shift_end
    if also_span:
        span_start = min(span_start, also_span[0])
        span_end = max(span_end, also_span[1])
    qs = _candidate_bleps(user, span_start, span_end)
    if exclude_shift is not None:
        pass  # shifts carry no blep FK; nothing to exclude
    return [b for b in qs if not (shift_start <= b.start_time and b.end_time <= shift_end)]


def enclosing_shift_for_blep(user, blep_start, blep_end, exclude_blep=None):
    """Return a Shift of `user` that fully encloses [blep_start, blep_end], or None.
    Only closed shifts can enclose (an open shift has no end yet)."""
    return (
        user.shifts.filter(
            end_time__isnull=False,
            start_time__lte=blep_start,
            end_time__gte=blep_end,
        )
        .order_by('start_time')
        .first()
    )
