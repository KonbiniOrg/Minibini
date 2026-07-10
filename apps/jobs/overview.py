"""JobOverviewService — the aggregate read behind the job overview page.

``GET /api/jobs/{id}/overview/`` is one page's worth of data the SPA can't
cheaply compute client-side: the due-date countdown (shop calendar-aware),
the labor/materials spend split (``apps.jobs.financials.spend_breakdown`` —
the source of truth; this module does not re-derive it), and task-progress
aggregates (counts, estimated-vs-completed hours, who's working right now).

No DB writes; pure read-only aggregation, like ``financials.py`` and
``ScheduleService``. See docs/plans/2026-07-09-job-overview-redesign.md.
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.jobs.financials import spend_breakdown
from apps.schedule.calendar_arithmetic import is_working_day

HOURS_QUANT = Decimal('0.1')
SECONDS_PER_HOUR = Decimal('3600')


def _hours_str(hours) -> str:
    """Format a Decimal (or None) hours figure as a 1-decimal string, e.g.
    Decimal('3') -> '3.0'."""
    if hours is None:
        hours = Decimal('0')
    if not isinstance(hours, Decimal):
        hours = Decimal(str(hours))
    return str(hours.quantize(HOURS_QUANT))


def _duration_hours(total: timedelta) -> Decimal:
    return Decimal(str(total.total_seconds())) / SECONDS_PER_HOUR


def _count_working_days_after(start_date, end_date, envelope) -> int:
    """Count working days strictly after ``start_date`` through ``end_date``
    inclusive. Returns 0 when ``end_date`` <= ``start_date``."""
    if end_date <= start_date:
        return 0
    count = 0
    d = start_date + timedelta(days=1)
    while d <= end_date:
        if is_working_day(d, envelope):
            count += 1
        d += timedelta(days=1)
    return count


def _due_summary(job, today, envelope):
    """None when the job has no due date. Otherwise {'date', 'working_days_left'}
    — working days strictly after `today` through the due date inclusive;
    0 when due today; negative (count of missed working days) when overdue."""
    if job.due_date is None:
        return None
    due_date = timezone.localtime(job.due_date).date()
    if due_date == today:
        working_days_left = 0
    elif due_date > today:
        working_days_left = _count_working_days_after(today, due_date, envelope)
    else:
        working_days_left = -_count_working_days_after(due_date, today, envelope)
    return {'date': due_date.isoformat(), 'working_days_left': working_days_left}


def _spend_summary(job):
    """The labor/materials split, string-formatted. Delegates entirely to
    `spend_breakdown` — see apps/jobs/financials.py for the terms."""
    breakdown = spend_breakdown(job)
    return {
        'labor': str(breakdown['labor']),
        'labor_hours': _hours_str(breakdown['labor_hours']),
        'materials_bought': str(breakdown['materials_bought']),
        'total': str(breakdown['total']),
    }


def _work_summary(job):
    from apps.jobs.models import Blep, Task

    tasks = list(job.tasks.all())
    tasks_total = len(tasks)
    tasks_complete = sum(1 for t in tasks if t.status == Task.STATUS_COMPLETE)
    tasks_blocked = sum(1 for t in tasks if t.status == Task.STATUS_BLOCKED)
    tasks_terminal = sum(
        1 for t in tasks
        if t.status in (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED)
    )

    total_est = timedelta()
    complete_est = timedelta()
    for t in tasks:
        if not t.est_worker_time:
            continue
        total_est += t.est_worker_time
        if t.status == Task.STATUS_COMPLETE:
            complete_est += t.est_worker_time

    # "Working now": open (running) bleps on the job's tasks. Name shape
    # mirrors BlepSerializer.get_user_name / TaskSerializer.get_assignee_name
    # (full name, falling back to username).
    open_bleps = (
        Blep.objects.filter(task__job=job, end_time__isnull=True)
        .select_related('user', 'task')
        .order_by('start_time', 'blep_id')
    )
    working_now = [
        {
            'task_name': blep.task.name,
            'worker_name': blep.user.get_full_name() or blep.user.username,
        }
        for blep in open_bleps
    ]

    return {
        'tasks_total': tasks_total,
        'tasks_complete': tasks_complete,
        'tasks_blocked': tasks_blocked,
        'tasks_terminal': tasks_terminal,
        'est_time_total_hours': _hours_str(_duration_hours(total_est)),
        'est_time_complete_hours': _hours_str(_duration_hours(complete_est)),
        'working_now': working_now,
    }


class JobOverviewService:
    """Aggregate read for ``GET /api/jobs/{id}/overview/``."""

    @staticmethod
    def summary(job, today=None, envelope=None):
        """Return {'due', 'spend', 'work'} for the job overview page.

        `today` and `envelope` are injectable for testability (fixed dates,
        fixed Mon-Fri envelope); the view passes the real shop values.
        """
        if today is None:
            today = timezone.localdate()
        if envelope is None:
            from apps.schedule.services import load_shop_envelope
            envelope = load_shop_envelope()

        return {
            'due': _due_summary(job, today, envelope),
            'spend': _spend_summary(job),
            'work': _work_summary(job),
        }
