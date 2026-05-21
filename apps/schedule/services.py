"""ScheduleService — produces the per-worker time-axis layout for the
schedule view. No DB writes; only reads Tasks, Bleps, Jobs, Users, and
Configuration."""
from datetime import datetime, time, timedelta
from typing import Optional

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from apps.core.models import Configuration
from apps.schedule.calendar_arithmetic import (
    DayShape, add_work_time, is_working_day, next_workable_moment,
    segments_for, work_minutes_between, workday_start_on,
)


# Configuration keys + defaults. Defaults are written into Configuration on
# first read (mirrors the email_retention_days pattern in apps/core/services.py).
CONFIG_DEFAULTS = {
    'schedule_workday_start': '08:00',
    'schedule_workday_end': '17:00',
    'schedule_lunch_start': '12:00',
    'schedule_lunch_length_minutes': '60',
    'schedule_task_buffer_minutes': '10',
    'schedule_horizon_days': '3',
}


def _read_config(key: str) -> str:
    try:
        return Configuration.objects.get(key=key).value
    except Configuration.DoesNotExist:
        default = CONFIG_DEFAULTS[key]
        Configuration.objects.create(key=key, value=default)
        return default


def _parse_hhmm(s: str) -> time:
    hh, mm = s.split(':')
    return time(int(hh), int(mm))


def load_day_shape() -> DayShape:
    """Read the schedule's day shape from Configuration."""
    workday_start = _parse_hhmm(_read_config('schedule_workday_start'))
    workday_end = _parse_hhmm(_read_config('schedule_workday_end'))
    lunch_start = _parse_hhmm(_read_config('schedule_lunch_start'))
    lunch_length = int(_read_config('schedule_lunch_length_minutes'))
    buffer_min = int(_read_config('schedule_task_buffer_minutes'))

    lunch_end_minutes = lunch_start.hour * 60 + lunch_start.minute + lunch_length
    lunch_end = time(lunch_end_minutes // 60, lunch_end_minutes % 60)

    return DayShape(
        workday_start=workday_start,
        workday_end=workday_end,
        lunch_start=lunch_start,
        lunch_end=lunch_end,
        task_buffer_minutes=buffer_min,
    )


def load_horizon_days(override: Optional[int] = None) -> int:
    """Read horizon_days from Configuration. Clamped to [1, 14]."""
    if override is not None:
        try:
            n = int(override)
        except (TypeError, ValueError):
            n = 3
    else:
        try:
            n = int(_read_config('schedule_horizon_days'))
        except (TypeError, ValueError):
            n = 3
    return max(1, min(14, n))


class ScheduleService:
    """Produces the per-worker schedule data for GET /api/schedule/."""

    @staticmethod
    def get_schedule(now: datetime, horizon_days: Optional[int] = None) -> dict:
        from apps.jobs.models import Task, Job

        User = get_user_model()
        shape = load_day_shape()
        days_n = load_horizon_days(horizon_days)

        # Horizon window: midnight today (local) to N days later.
        tz = timezone.get_current_timezone()
        local_now = now.astimezone(tz)
        local_today = local_now.date()
        horizon_start = timezone.make_aware(
            datetime.combine(local_today, time(0, 0)), tz,
        )
        horizon_end = horizon_start + timedelta(days=days_n)

        # Days list
        days = []
        d = local_today
        for _ in range(days_n):
            days.append({
                'date': d.isoformat(),
                'is_working': is_working_day(d),
                'label': d.strftime('%a · %b %d'),
            })
            d += timedelta(days=1)

        # Half-open range covering "today" in local time. Used instead of
        # `__date` lookups because MySQL's CONVERT_TZ() requires the timezone
        # tables to be loaded — without them, `__date` filters return NULL
        # and match nothing.
        today_start_local = horizon_start  # midnight today, local
        today_end_local = horizon_start + timedelta(days=1)

        # Active workers: anyone with at least one relevant task.
        relevant_statuses = [
            Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS, Task.STATUS_BLOCKED,
        ]
        worker_ids = set(Task.objects.filter(
            assignee__isnull=False,
            status__in=relevant_statuses,
        ).values_list('assignee_id', flat=True))
        # Plus workers with completed tasks blepped today (local).
        completed_today_worker_ids = set(Task.objects.filter(
            assignee__isnull=False,
            status=Task.STATUS_COMPLETE,
            blep__end_time__gte=today_start_local,
            blep__end_time__lt=today_end_local,
        ).values_list('assignee_id', flat=True))
        worker_ids |= completed_today_worker_ids

        workers = User.objects.filter(pk__in=worker_ids).order_by(
            'first_name', 'last_name',
        )

        # Jobs in play (for the JobChipStrip at top)
        job_ids = set(Task.objects.filter(
            assignee_id__in=worker_ids,
            status__in=relevant_statuses + [Task.STATUS_COMPLETE],
        ).values_list('job_id', flat=True))
        jobs = Job.objects.filter(pk__in=job_ids).select_related('contact')
        jobs_payload = []
        for j in jobs:
            contact_name = ''
            if j.contact_id:
                fn = j.contact.first_name or ''
                ln = j.contact.last_name or ''
                contact_name = (fn + ' ' + ln).strip()
            jobs_payload.append({
                'job_id': j.pk,
                'job_number': getattr(j, 'job_number', '') or '',
                # Job has both `name` (short) and `description` (long). The
                # board's JobCard uses `name`; reuse it here.
                'name': getattr(j, 'name', '') or getattr(j, 'description', '') or '',
                'accent_color': j.accent_color,
                'contact_id': j.contact_id,
                'contact_name': contact_name,
                'due_date': j.due_date.isoformat() if j.due_date else None,
            })

        worker_lanes = []
        for worker in workers:
            bars = ScheduleService._build_lane(worker, local_now, shape)
            worker_lanes.append({
                'user': ScheduleService._serialize_user(worker),
                'bars': bars,
            })

        return {
            'now': local_now.isoformat(),
            'horizon_start': horizon_start.isoformat(),
            'horizon_end': horizon_end.isoformat(),
            'horizon_days': days_n,
            'day_shape': {
                'workday_start': shape.workday_start.strftime('%H:%M'),
                'workday_end': shape.workday_end.strftime('%H:%M'),
                'lunch_start': shape.lunch_start.strftime('%H:%M'),
                'lunch_end': shape.lunch_end.strftime('%H:%M'),
                'task_buffer_minutes': shape.task_buffer_minutes,
            },
            'days': days,
            'jobs': jobs_payload,
            'workers': worker_lanes,
        }

    @staticmethod
    def _serialize_user(user) -> dict:
        fn = user.first_name or ''
        ln = user.last_name or ''
        name = (fn + ' ' + ln).strip() or user.username
        if fn or ln:
            initials = ((fn[:1] or '') + (ln[:1] or '')).upper()
        else:
            initials = user.username[:2].upper()
        return {
            'id': user.pk,
            'name': name,
            'initials': initials,
        }

    @staticmethod
    def _build_lane(worker, local_now, shape):
        """Walk the worker's queue and emit bars in order.

        See docs/plans/2026-05-19-schedule-view-design.md §4 for the
        algorithm contract.
        """
        from apps.jobs.models import Task

        relevant_statuses = [
            Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS, Task.STATUS_BLOCKED,
        ]
        local_today = local_now.date()
        # Range covering "today" in local time, computed via timezone.make_aware
        # rather than `__date` so the lookup doesn't rely on MySQL's
        # CONVERT_TZ() (which silently returns NULL when its timezone tables
        # aren't loaded, swallowing the completed-today filter).
        today_start = timezone.make_aware(
            datetime.combine(local_today, time(0, 0)),
            local_now.tzinfo,
        )
        today_end = today_start + timedelta(days=1)

        tasks_qs = Task.objects.filter(
            assignee=worker,
        ).filter(
            Q(status__in=relevant_statuses) |
            Q(status=Task.STATUS_COMPLETE,
              blep__end_time__gte=today_start,
              blep__end_time__lt=today_end)
        ).select_related('job').distinct().order_by('worker_queue', 'pk')

        cursor = next_workable_moment(
            max(local_now, workday_start_on(local_today, shape)),
            shape,
        )
        bars = []

        # Cursor advancement rules differ by task kind:
        #
        # - Pending tasks cascade forward: cursor = forecast_end + buffer.
        # - Completed tasks set cursor to their actual_end + buffer, which
        #   may be EARLIER than the current cursor. This is intentional: a
        #   task that finished early opens its successor's slot earlier
        #   than the plan said it would, and the next pending task should
        #   land at the actual completion (even if that's before "now").
        # - In-progress tasks (anchored to bleps) advance the cursor
        #   MONOTONICALLY — max(current, effective_end + buffer). They
        #   represent work happening *now*; pending tasks already placed
        #   ahead of them in the queue must not be pulled back on top of
        #   them. If the active task is not first in the queue, this
        #   prevents the visual overlap.
        # - Blocked tasks don't move the cursor at all.

        for task in tasks_qs:
            bleps = list(task.blep_set.order_by('start_time'))
            if task.status == Task.STATUS_PENDING:
                bars.extend(ScheduleService._emit_forecast(task, cursor, shape))
                cursor = ScheduleService._advance_cursor_after_forecast(
                    cursor, task, shape,
                )
            elif task.status == Task.STATUS_IN_PROGRESS and bleps:
                active_bars, new_cursor = ScheduleService._emit_active(
                    task, bleps, local_now, cursor, shape,
                )
                bars.extend(active_bars)
                if new_cursor is not None and new_cursor > cursor:
                    cursor = new_cursor
            elif task.status == Task.STATUS_IN_PROGRESS:
                bars.extend(ScheduleService._emit_forecast(task, cursor, shape))
                cursor = ScheduleService._advance_cursor_after_forecast(
                    cursor, task, shape,
                )
            elif task.status == Task.STATUS_BLOCKED:
                if bleps:
                    hist_bars, _ignored = ScheduleService._emit_historical(
                        task, bleps, local_now, shape,
                    )
                    bars.extend(hist_bars)
                bars.append(ScheduleService._emit_parked(task, cursor, shape))
                # cursor unchanged — blocked tasks don't consume future time
            elif task.status == Task.STATUS_COMPLETE and bleps:
                hist_bars, new_cursor = ScheduleService._emit_historical(
                    task, bleps, local_now, shape, advance_cursor_from=cursor,
                )
                bars.extend(hist_bars)
                # Completed tasks may pull cursor backward intentionally.
                cursor = new_cursor

        return bars

    @staticmethod
    def _emit_forecast(task, cursor, shape):
        est = task.est_worker_time
        if not est or est <= timedelta(0):
            return []
        start = next_workable_moment(cursor, shape)
        end = add_work_time(start, est, shape)
        segments = segments_for(start, end, shape)
        return [ScheduleService._build_bar(
            task=task, kind='forecast',
            segments=segments, elapsed_minutes=0, is_running=False,
            est_layer_end=end, actual_layer_end=None,
        )]

    @staticmethod
    def _advance_cursor_after_forecast(cursor, task, shape):
        est = task.est_worker_time or timedelta(0)
        start = next_workable_moment(cursor, shape)
        end = add_work_time(start, est, shape)
        buf = timedelta(minutes=shape.task_buffer_minutes)
        return next_workable_moment(end + buf, shape)

    @staticmethod
    def _emit_active(task, bleps, local_now, cursor, shape):
        """Emit the active bar for an in-progress task with bleps. Returns
        (bars_list, new_cursor)."""
        anchor_start = bleps[0].start_time.astimezone(local_now.tzinfo)
        est = task.est_worker_time or timedelta(0)
        est_layer_end = add_work_time(anchor_start, est, shape)

        last_blep = bleps[-1]
        is_running = last_blep.end_time is None
        if is_running:
            dark_end_clock = local_now
        else:
            dark_end_clock = last_blep.end_time.astimezone(local_now.tzinfo)

        elapsed_minutes = 0
        for b in bleps:
            b_start = b.start_time.astimezone(local_now.tzinfo)
            b_end = (b.end_time or local_now).astimezone(local_now.tzinfo)
            elapsed_minutes += work_minutes_between(b_start, b_end, shape)

        effective_end = max(est_layer_end, dark_end_clock)
        segments = segments_for(anchor_start, effective_end, shape)

        bar = ScheduleService._build_bar(
            task=task, kind='active', segments=segments,
            elapsed_minutes=elapsed_minutes, is_running=is_running,
            est_layer_end=est_layer_end, actual_layer_end=dark_end_clock,
        )
        buf = timedelta(minutes=shape.task_buffer_minutes)
        new_cursor = next_workable_moment(effective_end + buf, shape)
        return [bar], new_cursor

    @staticmethod
    def _emit_historical(task, bleps, local_now, shape, advance_cursor_from=None):
        """Emit historical bar(s) for a task with bleps. For now: one bar
        spanning first_blep_start → last_blep_end (contiguous grouping is
        YAGNI for v1). Returns (bars, new_cursor_if_advance_requested)."""
        if not bleps:
            return [], advance_cursor_from
        first = bleps[0].start_time.astimezone(local_now.tzinfo)
        last_end_dt = bleps[-1].end_time or local_now
        last = last_end_dt.astimezone(local_now.tzinfo)
        segments = segments_for(first, last, shape)
        elapsed_minutes = 0
        for b in bleps:
            b_start = b.start_time.astimezone(local_now.tzinfo)
            b_end = (b.end_time or local_now).astimezone(local_now.tzinfo)
            elapsed_minutes += work_minutes_between(b_start, b_end, shape)
        # For completed/historical, light and dark layers are coextensive
        # at the actual span end.
        bar = ScheduleService._build_bar(
            task=task, kind='historical', segments=segments,
            elapsed_minutes=elapsed_minutes, is_running=False,
            est_layer_end=last, actual_layer_end=last,
        )
        if advance_cursor_from is None:
            return [bar], None
        buf = timedelta(minutes=shape.task_buffer_minutes)
        new_cursor = next_workable_moment(last + buf, shape)
        return [bar], new_cursor

    @staticmethod
    def _emit_parked(task, cursor, shape):
        """A blocked task's placeholder. Fixed minimal width (15 min of work
        time). Does not consume cursor time in the caller's cascade."""
        parked_start = next_workable_moment(cursor, shape)
        parked_end = add_work_time(parked_start, timedelta(minutes=15), shape)
        segments = segments_for(parked_start, parked_end, shape)
        return ScheduleService._build_bar(
            task=task, kind='parked', segments=segments,
            elapsed_minutes=0, is_running=False,
            est_layer_end=parked_end, actual_layer_end=None,
        )

    @staticmethod
    def _build_bar(*, task, kind, segments, elapsed_minutes,
                   is_running, est_layer_end, actual_layer_end):
        """Assemble the bar dict from raw segments and layer endpoints."""
        est_minutes = int(
            (task.est_worker_time or timedelta(0)).total_seconds() // 60
        )
        seg_dicts = []
        for seg_start, seg_end in segments:
            est_fill_to = None
            actual_fill_to = None
            if est_layer_end is not None and est_layer_end > seg_start:
                est_fill_to = min(est_layer_end, seg_end)
            if actual_layer_end is not None and actual_layer_end > seg_start:
                actual_fill_to = min(actual_layer_end, seg_end)
            seg_dicts.append({
                'start': seg_start.isoformat(),
                'end': seg_end.isoformat(),
                'est_fill_to': est_fill_to.isoformat() if est_fill_to else None,
                'actual_fill_to': actual_fill_to.isoformat() if actual_fill_to else None,
                'continues_left': False,
                'continues_right': False,
            })
        for i, seg in enumerate(seg_dicts):
            seg['continues_left'] = i > 0
            seg['continues_right'] = i < len(seg_dicts) - 1

        return {
            'task_id': task.pk,
            'job_id': task.job_id,
            'name': task.name,
            'status': task.status,
            'accent_color': task.job.accent_color,
            'est_minutes': est_minutes,
            'elapsed_minutes': elapsed_minutes,
            'is_running': is_running,
            'kind': kind,
            'segments': seg_dicts,
        }
