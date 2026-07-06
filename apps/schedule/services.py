"""ScheduleService — produces the per-worker time-axis layout for the
schedule view. No DB writes; only reads Tasks, Bleps, Jobs, Users, and
Configuration."""
import json
import logging
from datetime import datetime, time, timedelta
from typing import Optional

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from apps.core.models import Configuration
from apps.schedule.calendar_arithmetic import (
    WeekEnvelope, add_work_time, day_segments_clamped, next_workable_moment,
    segments_for, shift_working_days, work_minutes_between,
)

logger = logging.getLogger(__name__)

# An unfinished task always forecasts at least this much, so overrun-but-open
# work (logged >= estimate) and tiny/zero-estimate tasks still show a slot in
# the worker's queue, keeping the schedule in sync with the job board.
MIN_FORECAST = timedelta(minutes=10)


# Configuration keys + defaults. Defaults are written into Configuration on
# first read (mirrors the email_retention_days pattern in apps/core/services.py).
CONFIG_DEFAULTS = {
    'schedule_week_envelope': json.dumps(WeekEnvelope.default().to_json()),
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


def load_shop_envelope() -> WeekEnvelope:
    """Read the shop's weekly envelope from Configuration (the configurable
    work week). Falls back to the built-in default on unparseable data —
    the schedule page must never 500 over a bad config row."""
    raw = _read_config('schedule_week_envelope')
    try:
        return WeekEnvelope.from_json(json.loads(raw))
    except (ValueError, TypeError) as exc:
        logger.warning('Bad schedule_week_envelope config (%s); using default', exc)
        return WeekEnvelope.default()


def load_buffer_minutes() -> int:
    try:
        return int(_read_config('schedule_task_buffer_minutes'))
    except (TypeError, ValueError):
        return 10


def resolve_envelope(user, shop_env: WeekEnvelope) -> WeekEnvelope:
    """A worker uses their own envelope if set, else the shop's. Malformed
    stored JSON falls back to the shop default (and logs) — never 500s."""
    raw = getattr(user, 'schedule_envelope', None)
    if raw is None:
        return shop_env
    try:
        return WeekEnvelope.from_json(raw)
    except (ValueError, TypeError) as exc:
        logger.warning(
            'Bad schedule_envelope on user %s (%s); using shop default',
            user.pk, exc,
        )
        return shop_env


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
        shop_env = load_shop_envelope()
        buffer_minutes = load_buffer_minutes()
        days_n = load_horizon_days(horizon_days)

        # Horizon window: `offset` working days from today gives the window's
        # first day; from there we walk forward including `days_n` WORKING
        # days. Working-day counting and offset stepping use the SHOP
        # envelope's calendar (deterministic for everyone); a day the shop
        # skips still renders full-width if any displayed worker works it
        # (is_working is finalized after the worker set below). Non-working
        # days are included for visual continuity — they render as thin
        # strips — but don't count toward the horizon. A span cap keeps a
        # large N over a long non-working stretch from running away.
        #   offset == 0  → window starts today (default)
        #   offset < 0   → scroll into the past
        #   offset > 0   → scroll into the future
        tz = timezone.get_current_timezone()
        local_now = now.astimezone(tz)
        local_today = local_now.date()
        start_date = shift_working_days(local_today, offset, shop_env)
        horizon_start = timezone.make_aware(
            datetime.combine(start_date, time(0, 0)), tz,
        )

        MAX_SPAN_DAYS = 31
        days = []
        day_dates = []
        d = start_date
        working_seen = 0
        span = 0
        # Always advance at least one day past the last counted working day so
        # the horizon_end bound sits cleanly after the visible range.
        while working_seen < days_n and span < MAX_SPAN_DAYS:
            working = shop_env.is_working_day(d)
            days.append({
                'date': d.isoformat(),
                'is_working': working,  # widened below by worker envelopes
                'label': d.strftime('%a · %b %d'),
            })
            day_dates.append(d)
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

        # Planned-work statuses. Blocked is intentionally excluded — a blocked
        # task can't be worked now and has no ETA, so it never forecasts (its
        # past actuals still surface via the blep-history path). Planned work
        # and worker selection are work-driven: unheld in_progress jobs PLUS
        # unheld pre-approval (draft/submitted) jobs — matching the board's
        # In Progress column and the chip strip (assignment is the deliberate
        # act that puts quote-stage work on the schedule). `approved` stays
        # excluded: release-to-floor is the forecast gate. History paths
        # (completed-with-blep, open/in-window bleps) are unrestricted — past
        # work happened and renders even on a held job.
        relevant_statuses = [
            Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS,
        ]
        work_active_job_statuses = [
            Job.STATUS_IN_PROGRESS, Job.STATUS_DRAFT, Job.STATUS_SUBMITTED,
        ]
        worker_ids = set(Task.objects.filter(
            assignee__isnull=False,
            status__in=relevant_statuses,
            job__status__in=work_active_job_statuses,
            job__on_hold=False,
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

        # Resolve every displayed worker's envelope once; the page axis is
        # the union of their working hours over the visible days, widened by
        # the off-hours blep rule. A day the shop skips renders full-width
        # when any displayed worker works it.
        worker_envs = {w.pk: resolve_envelope(w, shop_env) for w in workers}
        axis_start, axis_end = ScheduleService._compute_axis(
            shop_env, worker_envs.values(), day_dates, window_bleps, local_now,
        )
        for i, day_date in enumerate(day_dates):
            if not days[i]['is_working']:
                days[i]['is_working'] = any(
                    env.is_working_day(day_date) for env in worker_envs.values()
                )

        # Jobs for the JobChipStrip at top = the job board's In Progress column.
        # Reuse the board's own definition of that set so the two can never
        # drift: every in_progress job (minus unpaid sub-statuses), in due_date
        # order. This is deliberately broader than the lane bars — a job appears
        # as a chip even with no assigned work or no tasks at all (the board
        # shows those with a 'needs-tasks' sub-status). Completed work on a
        # now-finished (work_complete) job still renders in the lanes below (its
        # bars are self-describing), but that job is not in_progress, so it's not
        # on the strip. Both the board's ApprovedArea and the schedule render the
        # same JobChipStrip, which sorts nothing, so the order must match too.
        from apps.jobs.services import BoardService
        jobs = BoardService.in_progress_column_jobs()
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
                'pre_approval': j.status in (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED),
                'on_hold': j.on_hold,
                'hold_reason': j.hold_reason,
                'accent_color': j.accent_color,
                'contact_id': j.contact_id,
                'contact_name': contact_name,
                'project_manager_name': (
                    (j.project_manager.get_full_name() or j.project_manager.username)
                    if j.project_manager_id else None
                ),
                'due_date': j.due_date.isoformat() if j.due_date else None,
            })

        worker_lanes = []
        for worker in workers:
            env = worker_envs[worker.pk]
            bars = ScheduleService._build_lane(
                worker, local_now, env, buffer_minutes,
                axis_start, axis_end,
                today_start_local, today_end_local,
            )
            worker_lanes.append({
                'user': ScheduleService._serialize_user(worker),
                # The lane's resolved working intervals per visible day —
                # drives the per-lane off-envelope shading. Parallel to days[].
                'envelope_by_day': [
                    [[s.strftime('%H:%M'), e.strftime('%H:%M')]
                     for s, e in env.intervals_on(day_date)]
                    for day_date in day_dates
                ],
                'bars': bars,
            })

        axis_payload = {
            'start': axis_start.strftime('%H:%M'),
            'end': axis_end.strftime('%H:%M'),
            'task_buffer_minutes': buffer_minutes,
        }
        return {
            'now': local_now.isoformat(),
            'horizon_start': horizon_start.isoformat(),
            'horizon_end': horizon_end.isoformat(),
            'horizon_days': days_n,
            'offset': offset,
            # `axis` is the page display axis: union of displayed workers'
            # envelope hours over the visible days, widened for off-hours
            # logged work. Off-envelope shading is per-lane (envelope_by_day).
            'axis': axis_payload,
            # LEGACY alias mirroring `axis` — the SPA still reads day_shape;
            # removed when the frontend switches to `axis` (Task 19).
            'day_shape': {
                'workday_start': axis_payload['start'],
                'workday_end': axis_payload['end'],
                'task_buffer_minutes': buffer_minutes,
                'config_workday_start': axis_payload['start'],
                'config_workday_end': axis_payload['end'],
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
    def _compute_axis(shop_env, worker_envs, day_dates, bleps, local_now):
        """The page display axis (rule 2 of the overnight-compression rules):
        the union of the displayed workers' envelope hours across the visible
        days, widened (floor/ceil to the hour) for any work — running OR
        already logged — that fell outside those hours in the window. A
        running blep also reserves room for its estimate projection. Work
        that crosses midnight never drags the axis (its off-axis remainder
        clips with a zigzag instead — rule 3, day_segments_clamped). Returns
        an (axis_start, axis_end) time pair.

        Baseline fallbacks: with no workers (or all-off envelopes on the
        visible days) the shop's weekly hours anchor the axis; a fully-off
        shop falls back to 08:00–17:00 so the page always has an axis.
        """
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

        # Envelope union over the visible days.
        starts, ends = [], []
        envs = list(worker_envs) or [shop_env]
        for env in envs:
            for d in day_dates:
                for int_start, int_end in env.intervals_on(d):
                    starts.append(int_start)
                    ends.append(int_end)
        if not starts:
            # Nothing works these days — anchor on the shop's weekly hours.
            for intervals in shop_env.days:
                for int_start, int_end in intervals:
                    starts.append(int_start)
                    ends.append(int_end)
        base_start = min(starts) if starts else time(8, 0)
        base_end = max(ends) if ends else time(17, 0)

        earliest = base_start
        latest = base_end
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
        # envelope-union hours. Rounding the unchanged bounds would invent a
        # spurious off-hours margin (e.g. 08:30 floored to 08:00 with no
        # early work), shading every day's start grey for no reason.
        axis_start = floor_hour(earliest) if earliest < base_start else base_start
        axis_end = ceil_hour(latest) if latest > base_end else base_end
        return axis_start, axis_end

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
    def _build_lane(worker, local_now, env, buffer_minutes,
                    axis_start, axis_end, window_start, window_end):
        """Walk the worker's queue and emit bars in order.

        `env` is THIS worker's resolved weekly envelope — it drives the
        cursor and forecast cascade so pending work never lands outside
        their working intervals. `axis_start`/`axis_end` are the page
        display axis (times); actual bars clamp to it with clip flags
        (day_segments_clamped) and are never split by envelope gaps.

        `window_start` / `window_end` bound the visible horizon; completed
        tasks are included when a blep ended inside that window. See
        docs/designs/schedule.md §3 for the algorithm contract.
        """
        from apps.jobs.models import Task, Job, Blep

        relevant_statuses = [
            Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS,
        ]
        work_active_job_statuses = [
            Job.STATUS_IN_PROGRESS, Job.STATUS_DRAFT, Job.STATUS_SUBMITTED,
        ]

        # The worker's lane covers three task sets:
        #  - PLANNED: tasks assigned to them in a planned status (pending/
        #    in_progress) on an unheld work-active job (in_progress, or
        #    pre-approval draft/submitted) — these forecast forward, scoped
        #    exactly like the chip strip / board In Progress set.
        #  - HISTORY: completed tasks assigned to them with a blep ending in
        #    the window — past work on any job (incl. work_complete and held
        #    jobs), so finished and scrolled-back history survives.
        #  - BLEPPED: tasks they have a blep on (open, or ending in the window)
        #    even if they're not the assignee — concurrent/joined/taken-over
        #    work (and a worked-then-blocked task's past actuals land here).
        planned_ids = set(Task.objects.filter(
            assignee=worker,
            status__in=relevant_statuses,
            job__status__in=work_active_job_statuses,
            job__on_hold=False,
        ).values_list('pk', flat=True))
        history_ids = set(Task.objects.filter(
            assignee=worker,
            status=Task.STATUS_COMPLETE,
            blep__end_time__gte=window_start,
            blep__end_time__lt=window_end,
        ).values_list('pk', flat=True))
        blepped_ids = set(Blep.objects.filter(user=worker).filter(
            Q(end_time__isnull=True) |
            Q(end_time__gte=window_start, end_time__lt=window_end)
        ).values_list('task_id', flat=True))
        task_ids = planned_ids | history_ids | blepped_ids

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
        # A worker whose envelope has no working time at all never forecasts
        # (their actuals still render); next_workable_moment raises for that
        # envelope, so guard it once here.
        can_forecast = any(env.days)
        cursor = next_workable_moment(local_now, env) if can_forecast else None
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
                    task, group, local_now, axis_start, axis_end, total_elapsed,
                ))

            # Future: the assignee's own remaining estimate, floored so an
            # overrun-but-open or tiny task still holds a slot in the queue.
            # Only the PLANNED set forecasts forward — a blocked task or a
            # held job's task (reached here via the blep-history paths) shows
            # its actuals but never a forecast, and a completed task emits
            # actuals only.
            if is_assignee and task.pk in planned_ids and can_forecast:
                worked = ScheduleService._elapsed_worktime(bleps, local_now, env)
                remaining = (task.est_worker_time or timedelta(0)) - worked
                forecast_bars, cursor = ScheduleService._emit_forecast(
                    task, cursor, env, buffer_minutes,
                    duration=max(remaining, MIN_FORECAST),
                    elapsed_minutes=total_elapsed,
                )
                bars.extend(forecast_bars)

        return bars

    @staticmethod
    def _elapsed_worktime(bleps, local_now, env):
        """Total work-time the worker has logged across `bleps` (counted
        against their own envelope)."""
        total = timedelta(0)
        for b in bleps:
            bs = b.start_time.astimezone(local_now.tzinfo)
            be = (b.end_time or local_now).astimezone(local_now.tzinfo)
            total += timedelta(minutes=work_minutes_between(bs, be, env))
        return total

    @staticmethod
    def _emit_forecast(task, cursor, env, buffer_minutes,
                       duration=None, elapsed_minutes=0):
        """Light forecast bar from `cursor`, plus the advanced cursor (end +
        buffer). `duration` overrides the task's full estimate (the remaining
        time on a partly-worked task). Returns (bars, new_cursor); with no
        positive duration there's no bar, but the cursor still steps past the
        buffer. Forecast segments split at envelope gaps as well as
        overnights — same zigzag mechanism."""
        est = duration if duration is not None else task.est_worker_time
        start = next_workable_moment(cursor, env)
        buf = timedelta(minutes=buffer_minutes)
        if not est or est <= timedelta(0):
            return [], next_workable_moment(start + buf, env)
        end = add_work_time(start, est, env)
        segments = [
            {'start': s, 'end': e, 'clipped_left': False, 'clipped_right': False}
            for s, e in segments_for(start, end, env)
        ]
        bar = ScheduleService._build_bar(
            task=task, kind='forecast', segments=segments,
            elapsed_minutes=elapsed_minutes, is_running=False,
        )
        return [bar], next_workable_moment(end + buf, env)

    @staticmethod
    def _emit_actual(task, group, local_now, axis_start, axis_end,
                     elapsed_minutes):
        """A dark `actual` bar for one contiguous work session (immutable past
        work). The session holding an open blep ends at now and is flagged
        running. Actuals split only at midnight and clamp to the display axis
        with clip flags — never split or clipped by envelope gaps; a fully
        off-axis or zero-width session still renders a one-minute sliver
        (day_segments_clamped's visibility rule)."""
        start = group[0].start_time.astimezone(local_now.tzinfo)
        is_running = group[-1].end_time is None
        end_dt = local_now if is_running else group[-1].end_time
        end = end_dt.astimezone(local_now.tzinfo)
        segments = day_segments_clamped(start, end, axis_start, axis_end)
        return ScheduleService._build_bar(
            task=task, kind='actual', segments=segments,
            elapsed_minutes=elapsed_minutes, is_running=is_running,
        )

    @staticmethod
    def _build_bar(*, task, kind, segments, elapsed_minutes, is_running):
        """Assemble the bar dict. Each bar is a single solid colour by kind
        (`forecast` light, `actual` dark); segments carry their interval and
        the zigzag continuation flags. `segments` is a list of dicts with
        start/end datetimes and clipped_left/right booleans; a segment
        continues when it was clipped at the axis edge OR has a sibling on
        that side (multi-piece splits)."""
        est_minutes = int(
            (task.est_worker_time or timedelta(0)).total_seconds() // 60
        )
        seg_dicts = []
        for seg in segments:
            seg_dicts.append({
                'start': seg['start'].isoformat(),
                'end': seg['end'].isoformat(),
                'continues_left': seg.get('clipped_left', False),
                'continues_right': seg.get('clipped_right', False),
            })
        for i, seg in enumerate(seg_dicts):
            seg['continues_left'] = seg['continues_left'] or i > 0
            seg['continues_right'] = (
                seg['continues_right'] or i < len(seg_dicts) - 1
            )

        from apps.jobs.models import Job
        return {
            'task_id': task.pk,
            'job_id': task.job_id,
            # Job number/name travel on the bar so a completed bar can show its
            # job in the quick card without the job being in the chip strip
            # (work_complete jobs are dropped from the strip but keep their bars).
            'job_number': getattr(task.job, 'job_number', '') or '',
            'job_name': getattr(task.job, 'name', '') or '',
            # Quote-stage work renders with a distinct treatment.
            'pre_approval': task.job.status in (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED),
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
