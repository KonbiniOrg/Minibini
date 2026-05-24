"""ScheduleService — produces the per-worker time-axis layout for the
schedule view. No DB writes; only reads Tasks, Bleps, Jobs, Users, and
Configuration."""
from dataclasses import replace
from datetime import datetime, time, timedelta
from typing import Optional

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from apps.core.models import Configuration
from apps.schedule.calendar_arithmetic import (
    DayShape, add_work_time, is_working_day, next_workable_moment,
    segments_for, shift_working_days, work_minutes_between, workday_start_on,
)

# An unfinished task always forecasts at least this much, so overrun-but-open
# work (logged >= estimate) and tiny/zero-estimate tasks still show a slot in
# the worker's queue, keeping the schedule in sync with the job board.
MIN_FORECAST = timedelta(minutes=10)


# Configuration keys + defaults. Defaults are written into Configuration on
# first read (mirrors the email_retention_days pattern in apps/core/services.py).
CONFIG_DEFAULTS = {
    'schedule_workday_start': '08:00',
    'schedule_workday_end': '17:00',
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
    """Read the schedule's day shape from Configuration. The workday is
    continuous (no lunch break — that returns with per-worker lunch)."""
    workday_start = _parse_hhmm(_read_config('schedule_workday_start'))
    workday_end = _parse_hhmm(_read_config('schedule_workday_end'))
    buffer_min = int(_read_config('schedule_task_buffer_minutes'))

    return DayShape(
        workday_start=workday_start,
        workday_end=workday_end,
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
    def get_schedule(now: datetime, horizon_days: Optional[int] = None,
                     offset: int = 0) -> dict:
        from apps.jobs.models import Task, Job, Blep

        User = get_user_model()
        shape = load_day_shape()
        days_n = load_horizon_days(horizon_days)

        # Horizon window: `offset` working days from today gives the window's
        # first day; from there we walk forward including `days_n` WORKING
        # days. Non-working days (weekends now; holidays later) are still
        # included for visual continuity — they render as thin strips — but
        # don't count toward the horizon. A span cap keeps a large N over a
        # long non-working stretch from running away.
        #   offset == 0  → window starts today (default)
        #   offset < 0   → scroll into the past
        #   offset > 0   → scroll into the future
        tz = timezone.get_current_timezone()
        local_now = now.astimezone(tz)
        local_today = local_now.date()
        start_date = shift_working_days(local_today, offset)
        horizon_start = timezone.make_aware(
            datetime.combine(start_date, time(0, 0)), tz,
        )

        MAX_SPAN_DAYS = 31
        days = []
        d = start_date
        working_seen = 0
        span = 0
        # Always advance at least one day past the last counted working day so
        # the horizon_end bound sits cleanly after the visible range.
        while working_seen < days_n and span < MAX_SPAN_DAYS:
            working = is_working_day(d)
            days.append({
                'date': d.isoformat(),
                'is_working': working,
                'label': d.strftime('%a · %b %d'),
            })
            if working:
                working_seen += 1
            d += timedelta(days=1)
            span += 1
        # `d` now points at the day after the last included day.
        horizon_end = timezone.make_aware(
            datetime.combine(d, time(0, 0)), tz,
        )

        # Completed tasks are included when their bleps fall inside the
        # visible window [horizon_start, horizon_end). For the default (today)
        # window this resolves to "completed today"; scrolling into the past
        # surfaces what was completed then. Half-open ranges avoid `__date`
        # lookups (MySQL CONVERT_TZ needs its tz tables loaded; without them
        # `__date` returns NULL and matches nothing).
        today_start_local = horizon_start
        today_end_local = horizon_end

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
        # Plus anyone with a blep open now or ending in the window, even if
        # they aren't the task's assignee — concurrent / joined / taken-over
        # work must surface in each contributing worker's lane.
        blep_worker_ids = set(Blep.objects.filter(
            user__isnull=False,
        ).filter(
            Q(end_time__isnull=True) |
            Q(end_time__gte=today_start_local, end_time__lt=today_end_local)
        ).values_list('user_id', flat=True))
        worker_ids |= blep_worker_ids

        workers = User.objects.filter(pk__in=worker_ids).order_by(
            'first_name', 'last_name',
        )

        # Display shape: the visible time axis. Equal to the configured
        # workday, EXCEPT widened to cover any work — running OR already
        # logged — that fell outside configured hours within the visible
        # window, so off-hours bars aren't clamped to the edges and hidden.
        # Forecasts and the cascade keep using the configured `shape` so
        # pending work is never scheduled off-hours; only the axis and the
        # actual/active bars use `display_shape`.
        # Closed bleps count when they end inside the window; an open (running)
        # blep counts only once the window has begun — otherwise a window
        # scrolled into the future would widen for work happening now that
        # renders nowhere in it.
        in_window = Q(end_time__gte=horizon_start)
        if local_now >= horizon_start:
            in_window |= Q(end_time__isnull=True)
        window_bleps = list(Blep.objects.filter(
            user_id__in=worker_ids,
            start_time__lt=horizon_end,
        ).filter(in_window).select_related('task'))
        display_shape = ScheduleService._extend_shape_for_window(
            shape, window_bleps, local_now,
        )

        # Jobs in play (for the JobChipStrip at top)
        job_ids = set(Task.objects.filter(
            assignee_id__in=worker_ids,
            status__in=relevant_statuses + [Task.STATUS_COMPLETE],
        ).values_list('job_id', flat=True))
        # Include jobs of tasks worked in the window (covers tasks a worker
        # blepped on but isn't assigned to).
        job_ids |= set(Task.objects.filter(
            blep__user__isnull=False,
        ).filter(
            Q(blep__end_time__isnull=True) |
            Q(blep__end_time__gte=today_start_local, blep__end_time__lt=today_end_local)
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
            bars = ScheduleService._build_lane(
                worker, local_now, shape, display_shape,
                today_start_local, today_end_local,
            )
            worker_lanes.append({
                'user': ScheduleService._serialize_user(worker),
                'bars': bars,
            })

        return {
            'now': local_now.isoformat(),
            'horizon_start': horizon_start.isoformat(),
            'horizon_end': horizon_end.isoformat(),
            'horizon_days': days_n,
            'offset': offset,
            # day_shape carries the DISPLAY shape (possibly widened for
            # off-hours in-progress work). The frontend axis maps from this.
            # config_workday_* are the configured hours so the frontend can
            # shade the off-hours margins between configured and display.
            'day_shape': {
                'workday_start': display_shape.workday_start.strftime('%H:%M'),
                'workday_end': display_shape.workday_end.strftime('%H:%M'),
                'task_buffer_minutes': display_shape.task_buffer_minutes,
                'config_workday_start': shape.workday_start.strftime('%H:%M'),
                'config_workday_end': shape.workday_end.strftime('%H:%M'),
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
    def _extend_shape_for_window(shape, bleps, local_now):
        """Return `shape` widened so its workday covers any work — running OR
        already logged — that fell outside configured hours within the visible
        window. Without this, off-hours portions of bars get clamped to the
        configured edges and vanish. A running blep also reserves room for its
        estimate projection. Earliest start floors to the hour; latest end
        ceils to the hour. Work that crosses midnight only extends the early
        edge (its far end is left alone, so one all-nighter can't blow the axis
        open). Returns `shape` unchanged when all work fell inside configured
        hours."""
        def floor_hour(t):
            return time(t.hour, 0)

        def ceil_hour(t):
            if t.minute == 0 and t.second == 0 and t.microsecond == 0:
                return time(t.hour, 0)
            if t.hour >= 23:
                # Can't represent 24:00 in a `time`; run the axis to the last
                # minute of the day so near-midnight work is still covered.
                return time(23, 59)
            return time(t.hour + 1, 0)

        earliest = shape.workday_start
        latest = shape.workday_end
        for b in bleps:
            start = b.start_time.astimezone(local_now.tzinfo)
            running = b.end_time is None
            end = local_now if running else b.end_time.astimezone(local_now.tzinfo)

            if start.time() < earliest:
                earliest = start.time()
            # Only let the late edge grow from work ending on its own start
            # date — a blep spanning midnight shouldn't drag the day open to
            # its far end.
            if end.date() == start.date() and end.time() > latest:
                latest = end.time()
            # A running blep also reserves room for its estimate projection
            # (the active bar's light layer), same single-day guard.
            if running:
                est = (b.task.est_worker_time or timedelta(0)) if b.task_id else timedelta(0)
                proj_end = start + est
                if proj_end.date() == start.date() and proj_end.time() > latest:
                    latest = proj_end.time()

        # Only round (and thus widen) when work actually fell outside the
        # configured hours. Rounding the unchanged config bounds would invent
        # a spurious off-hours margin (e.g. 08:30 floored to 08:00 with no
        # early work), shading every day's start grey for no reason.
        new_start = floor_hour(earliest) if earliest < shape.workday_start else shape.workday_start
        new_end = ceil_hour(latest) if latest > shape.workday_end else shape.workday_end
        if new_start == shape.workday_start and new_end == shape.workday_end:
            return shape
        return replace(shape, workday_start=new_start, workday_end=new_end)

    @staticmethod
    def _group_bleps(bleps):
        """Split bleps (already sorted by start) into contiguous work sessions.
        A new session begins whenever a blep starts after the previous one
        ended (a gap). Back-to-back bleps merge. Returns a list of blep lists."""
        groups = []
        current = []
        prev_end = None
        for b in bleps:
            if current and prev_end is not None and b.start_time > prev_end:
                groups.append(current)
                current = []
            current.append(b)
            # An open blep has no end (it's the running last one); floor on its
            # start so a following blep — if any — would split off.
            prev_end = b.end_time or b.start_time
        if current:
            groups.append(current)
        return groups

    @staticmethod
    def _build_lane(worker, local_now, shape, display_shape,
                    window_start, window_end):
        """Walk the worker's queue and emit bars in order.

        `shape` is the configured workday — it drives the cursor and forecast
        cascade so pending work never lands off-hours. `display_shape` is the
        (possibly widened) visible axis — active and historical bars are
        positioned with it so in-progress off-hours work renders. They are
        the same object unless an in-progress task runs outside configured
        hours.

        `window_start` / `window_end` bound the visible horizon; completed
        tasks are included when a blep ended inside that window. See
        docs/designs/schedule.md §3 for the algorithm contract.
        """
        from apps.jobs.models import Task, Blep

        relevant_statuses = [
            Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS, Task.STATUS_BLOCKED,
        ]

        # The worker's lane covers two task sets:
        #  - tasks ASSIGNED to them (their queue): relevant statuses, plus
        #    completed tasks with a blep ending in the window.
        #  - tasks they have a BLEP on (open, or ending in the window) even
        #    if they're not the assignee — concurrent/joined/taken-over work.
        assigned_ids = set(Task.objects.filter(
            assignee=worker,
        ).filter(
            Q(status__in=relevant_statuses) |
            Q(status=Task.STATUS_COMPLETE,
              blep__end_time__gte=window_start,
              blep__end_time__lt=window_end)
        ).values_list('pk', flat=True))
        blepped_ids = set(Blep.objects.filter(user=worker).filter(
            Q(end_time__isnull=True) |
            Q(end_time__gte=window_start, end_time__lt=window_end)
        ).values_list('task_id', flat=True))
        task_ids = assigned_ids | blepped_ids

        tasks_qs = Task.objects.filter(
            pk__in=task_ids,
        ).select_related('job').order_by('worker_queue', 'pk')

        # Pure worker_queue order — exactly the job board's order. Actual
        # pieces are wall-clock-anchored and forecasts always start at/after
        # now, so order only affects the forecast cascade; no phase grouping is
        # needed (the running task is promoted to worker_queue=1, so its
        # remaining-forecast still lands first).
        tasks = sorted(
            tasks_qs,
            key=lambda t: (
                t.worker_queue if t.worker_queue is not None else 9999,
                t.pk,
            ),
        )

        # The cascade always anchors to "now" (today), independent of the
        # scroll window — pending work is planned from the present forward.
        local_today = local_now.date()
        now_floor = next_workable_moment(
            max(local_now, workday_start_on(local_today, shape)),
            shape,
        )
        cursor = now_floor
        bars = []

        # Past = dark `actual` pieces (one per contiguous blep session); future
        # = light `forecast` (the remaining estimate, floored at MIN_FORECAST
        # while unfinished). The now-line divides them: actuals are wall-clock-
        # anchored and <= now; forecasts cascade from `cursor` in queue order
        # and are >= now. So the cursor only positions forecasts, and no two
        # bars in a lane can overlap.
        for task in tasks:
            # Only THIS worker's bleps drive their lane's bars.
            bleps = list(task.blep_set.filter(user=worker).order_by('start_time'))
            is_assignee = task.assignee_id == worker.pk
            # Total logged time, raw (matches Blep.elapsed / the task page);
            # carried on every one of the task's bars.
            total_elapsed = sum(
                int(((b.end_time or local_now) - b.start_time).total_seconds()) // 60
                for b in bleps
            )

            # Past: one dark actual piece per contiguous work session. The
            # session holding an open blep ends at now and is flagged running.
            for group in ScheduleService._group_bleps(bleps):
                bars.append(ScheduleService._emit_actual(
                    task, group, local_now, display_shape, total_elapsed,
                ))

            # Future: the assignee's own remaining estimate, floored so an
            # overrun-but-open or tiny task still holds a slot in the queue.
            if is_assignee and task.status != Task.STATUS_COMPLETE:
                worked = ScheduleService._elapsed_worktime(bleps, local_now, shape)
                remaining = (task.est_worker_time or timedelta(0)) - worked
                forecast_bars, cursor = ScheduleService._emit_forecast(
                    task, cursor, shape,
                    duration=max(remaining, MIN_FORECAST),
                    elapsed_minutes=total_elapsed,
                )
                bars.extend(forecast_bars)

        return bars

    @staticmethod
    def _elapsed_worktime(bleps, local_now, shape):
        """Total work-time the worker has logged across `bleps`."""
        total = timedelta(0)
        for b in bleps:
            bs = b.start_time.astimezone(local_now.tzinfo)
            be = (b.end_time or local_now).astimezone(local_now.tzinfo)
            total += timedelta(minutes=work_minutes_between(bs, be, shape))
        return total

    @staticmethod
    def _emit_forecast(task, cursor, shape, duration=None, elapsed_minutes=0):
        """Light forecast bar from `cursor`, plus the advanced cursor (end +
        buffer). `duration` overrides the task's full estimate (the remaining
        time on a partly-worked task). Returns (bars, new_cursor); with no
        positive duration there's no bar, but the cursor still steps past the
        buffer."""
        est = duration if duration is not None else task.est_worker_time
        start = next_workable_moment(cursor, shape)
        buf = timedelta(minutes=shape.task_buffer_minutes)
        if not est or est <= timedelta(0):
            return [], next_workable_moment(start + buf, shape)
        end = add_work_time(start, est, shape)
        segments = segments_for(start, end, shape)
        bar = ScheduleService._build_bar(
            task=task, kind='forecast', segments=segments,
            elapsed_minutes=elapsed_minutes, is_running=False,
        )
        return [bar], next_workable_moment(end + buf, shape)

    @staticmethod
    def _emit_actual(task, group, local_now, pshape, elapsed_minutes):
        """A dark `actual` bar for one contiguous work session (immutable past
        work). The session holding an open blep ends at now and is flagged
        running. `pshape` is the display axis (widened for off-hours work). A
        zero-width session — a blep viewed the instant it started — still
        renders a one-minute sliver so it's visible."""
        start = group[0].start_time.astimezone(local_now.tzinfo)
        is_running = group[-1].end_time is None
        end_dt = local_now if is_running else group[-1].end_time
        end = end_dt.astimezone(local_now.tzinfo)
        segments = segments_for(start, end, pshape)
        if not segments:
            segments = [(start, start + timedelta(minutes=1))]
        return ScheduleService._build_bar(
            task=task, kind='actual', segments=segments,
            elapsed_minutes=elapsed_minutes, is_running=is_running,
        )

    @staticmethod
    def _build_bar(*, task, kind, segments, elapsed_minutes, is_running):
        """Assemble the bar dict. Each bar is a single solid colour by kind
        (`forecast` light, `actual` dark); segments carry only their interval
        and the zigzag continuation flags."""
        est_minutes = int(
            (task.est_worker_time or timedelta(0)).total_seconds() // 60
        )
        seg_dicts = []
        for seg_start, seg_end in segments:
            seg_dicts.append({
                'start': seg_start.isoformat(),
                'end': seg_end.isoformat(),
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
            'blocked_reason': task.blocked_reason or '',
            'accent_color': task.job.accent_color,
            'est_minutes': est_minutes,
            'elapsed_minutes': elapsed_minutes,
            'is_running': is_running,
            'kind': kind,
            'segments': seg_dicts,
        }
