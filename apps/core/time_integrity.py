"""Pure helpers enforcing the shift<->blep enclosure invariant.

Invariant: every Blep must be fully enclosed by a Shift of the same user
(shift.start <= blep.start and blep.end <= shift.end). Bleps and shifts are
related by time overlap, not an FK. No function here writes to the DB.
"""
from apps.jobs.models import Blep


def _candidate_bleps(user, span_start, span_end):
    """Closed bleps of `user` that overlap [span_start, span_end].

    `span_end=None` means the span is open-ended (an ongoing shift has no end
    yet) — there is no upper bound on candidates.
    """
    qs = Blep.objects.filter(
        user=user,
        end_time__isnull=False,
        end_time__gt=span_start,
    )
    if span_end is not None:
        qs = qs.filter(start_time__lt=span_end)
    return qs


def unenclosed_bleps_for_shift(user, shift_start, shift_end, exclude_shift=None,
                               also_span=None):
    """Return this user's bleps that a shift spanning [shift_start, shift_end]
    would fail to enclose.

    `shift_end=None` means the shift is open/ongoing (no end yet); it is treated
    as an unbounded upper bound, so it encloses any blep starting at/after its
    start. Likewise an `also_span` end of None is unbounded.

    Candidates are bleps overlapping the proposed span - plus, when editing an
    existing shift, the original span (`also_span`) so a blep shrunk *out* of the
    shift is still caught. A candidate conflicts unless fully inside the new span.
    """
    span_start, span_end = shift_start, shift_end
    if also_span:
        span_start = min(span_start, also_span[0])
        # A None end on either side means "unbounded" — the union of an
        # unbounded span with anything is unbounded (None).
        if span_end is None or also_span[1] is None:
            span_end = None
        else:
            span_end = max(span_end, also_span[1])
    qs = _candidate_bleps(user, span_start, span_end)
    if exclude_shift is not None:
        pass  # shifts carry no blep FK; nothing to exclude
    return [
        b for b in qs
        if not (shift_start <= b.start_time
                and (shift_end is None or b.end_time <= shift_end))
    ]


def enclosing_shift_for_blep(user, blep_start, blep_end, exclude_blep=None):
    """Return a Shift of `user` that fully encloses [blep_start, blep_end], or None.

    A closed shift encloses when start <= blep_start and end >= blep_end. An
    open/ongoing shift (end_time is None) is still running, so its end is
    effectively unbounded — it encloses any blep starting at/after its start
    (a blep's end can never be in the future). This mirrors the open-shift
    handling in unenclosed_bleps_for_shift."""
    from django.db.models import Q
    return (
        user.shifts.filter(start_time__lte=blep_start)
        .filter(Q(end_time__isnull=True) | Q(end_time__gte=blep_end))
        .order_by('start_time')
        .first()
    )


def overlapping_shifts_for_blep(user, blep_start, blep_end):
    """Closed shifts of `user` that overlap [blep_start, blep_end] but don't
    necessarily enclose it — the candidates a manager would widen when no shift
    fully covers the blep. Ordered by start."""
    return (
        user.shifts.filter(
            end_time__isnull=False,
            start_time__lt=blep_end,
            end_time__gt=blep_start,
        )
        .order_by('start_time')
    )
