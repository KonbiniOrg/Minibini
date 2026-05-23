from datetime import datetime, time, timedelta

from django.utils import timezone as dj_tz

from tests.base import BaseTestCase
from apps.core.models import Configuration, User
from apps.contacts.models import Contact
from apps.jobs.models import Job, Task, Blep, RateScheme
from apps.jobs.services import JobService
from apps.schedule.services import (
    CONFIG_DEFAULTS,
    ScheduleService,
    load_day_shape,
    load_horizon_days,
)


def date_at_weekday(weekday_target):
    """Return the next date >= today whose weekday() == target (Mon=0, ..., Fri=4)."""
    from datetime import timedelta as _td
    today = dj_tz.localdate()
    delta = (weekday_target - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + _td(days=delta)


def local_dt(d, hh, mm):
    tz = dj_tz.get_current_timezone()
    return dj_tz.make_aware(datetime.combine(d, time(hh, mm)), tz)


def _seed_user_with_pending_task(est_minutes=120, name='J-101 fab',
                                  username='ws_user'):
    """Create (or get) a user and a pending task assigned to them."""
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={'first_name': 'Wendy', 'last_name': 'Smith'},
    )
    contact = Contact.objects.first()
    job = JobService.create_job(contact=contact, description='Test job')
    rs = RateScheme.objects.first()
    task = Task.objects.create(
        job=job, assignee=user, rate_scheme=rs,
        name=name, est_worker_time=timedelta(minutes=est_minutes),
        worker_queue=1, status=Task.STATUS_PENDING,
    )
    return user, task


class LoadDayShapeTest(BaseTestCase):

    def test_defaults_written_on_first_read(self):
        Configuration.objects.filter(key__startswith='schedule_').delete()
        shape = load_day_shape()
        # Trigger the horizon read too so every default lands.
        load_horizon_days()
        self.assertEqual(shape.workday_start, time(8, 0))
        self.assertEqual(shape.workday_end, time(17, 0))
        self.assertEqual(shape.task_buffer_minutes, 10)
        for key in CONFIG_DEFAULTS:
            self.assertTrue(
                Configuration.objects.filter(key=key).exists(),
                f"{key} not persisted",
            )


class LoadHorizonDaysTest(BaseTestCase):

    def test_default(self):
        Configuration.objects.filter(key='schedule_horizon_days').delete()
        self.assertEqual(load_horizon_days(), 3)

    def test_override(self):
        self.assertEqual(load_horizon_days(5), 5)

    def test_clamps_low(self):
        self.assertEqual(load_horizon_days(0), 1)
        self.assertEqual(load_horizon_days(-5), 1)

    def test_clamps_high(self):
        self.assertEqual(load_horizon_days(99), 14)


class HorizonCountsWorkingDaysTest(BaseTestCase):
    """horizon_days counts WORKING days. Non-working days (weekends) are
    included for display but don't consume the count."""

    def test_friday_plus_3_working_days_spans_the_weekend(self):
        # Find a Friday for "now".
        from datetime import timedelta as _td
        d = dj_tz.localdate()
        while d.weekday() != 4:  # Friday
            d += _td(days=1)
        now = local_dt(d, 9, 0)

        data = ScheduleService.get_schedule(now=now, horizon_days=3)
        days = data['days']
        working = [day for day in days if day['is_working']]
        nonworking = [day for day in days if not day['is_working']]

        # Exactly 3 working days counted.
        self.assertEqual(len(working), 3)
        # The intervening Saturday and Sunday appear as non-working.
        self.assertEqual(len(nonworking), 2)
        # First day is the Friday itself.
        self.assertEqual(days[0]['date'], d.isoformat())
        # Total list = Fri, Sat, Sun, Mon, Tue = 5 days.
        self.assertEqual(len(days), 5)

    def test_midweek_plus_3_has_no_weekend(self):
        from datetime import timedelta as _td
        d = dj_tz.localdate()
        while d.weekday() != 0:  # Monday
            d += _td(days=1)
        now = local_dt(d, 9, 0)

        data = ScheduleService.get_schedule(now=now, horizon_days=3)
        days = data['days']
        # Mon, Tue, Wed — all working, no weekend in the span.
        self.assertEqual(len(days), 3)
        self.assertTrue(all(day['is_working'] for day in days))


class OffHoursInProgressTest(BaseTestCase):
    """In-progress work outside configured hours widens the display axis
    (day_shape), but forecasts still respect the configured workday."""

    def test_early_blep_extends_workday_start_but_not_forecasts(self):
        user, active = _seed_user_with_pending_task(
            est_minutes=120, name='Early', username='early_user',
        )
        rs = RateScheme.objects.first()
        pending = Task.objects.create(
            job=active.job, assignee=user, rate_scheme=rs,
            name='Later', est_worker_time=timedelta(minutes=60),
            worker_queue=2, status=Task.STATUS_PENDING,
        )
        d = date_at_weekday(2)
        # Worker started at 07:00 — before the configured 08:00 start.
        start = local_dt(d, 7, 0)
        active.status = Task.STATUS_IN_PROGRESS; active.save()
        Blep.objects.create(user=user, task=active, start_time=start, end_time=None)
        now = local_dt(d, 7, 30)  # 30 min in, still before configured start

        data = ScheduleService.get_schedule(now=now)
        # Display axis widened to 07:00.
        self.assertEqual(data['day_shape']['workday_start'], '07:00')

        worker = next(w for w in data['workers'] if w['user']['id'] == user.pk)
        bars = {(b['task_id'], b['kind']): b for b in worker['bars']}

        # Active bar starts at the actual 07:00 (not clamped to 08:00).
        active_bar = bars[(active.pk, 'active')]
        active_first = datetime.fromisoformat(active_bar['segments'][0]['start'])
        self.assertEqual(active_first.hour, 7)

        # The pending forecast still starts no earlier than the configured
        # 08:00 — off-hours work doesn't drag scheduling into the early hours.
        pending_bar = bars[(pending.pk, 'forecast')]
        pending_first = datetime.fromisoformat(pending_bar['segments'][0]['start'])
        self.assertGreaterEqual(pending_first.hour, 8)


class HorizonOffsetTest(BaseTestCase):
    """offset scrolls the window by working days from today."""

    def test_future_offset_starts_window_ahead(self):
        from apps.schedule.calendar_arithmetic import shift_working_days
        d = dj_tz.localdate()
        while d.weekday() != 0:  # Monday
            d += timedelta(days=1)
        now = local_dt(d, 9, 0)

        data = ScheduleService.get_schedule(now=now, horizon_days=2, offset=2)
        expected_start = shift_working_days(d, 2)  # Wed
        self.assertEqual(data['days'][0]['date'], expected_start.isoformat())
        self.assertEqual(data['offset'], 2)

    def test_past_offset_starts_window_behind(self):
        from apps.schedule.calendar_arithmetic import shift_working_days
        d = dj_tz.localdate()
        while d.weekday() != 2:  # Wednesday
            d += timedelta(days=1)
        now = local_dt(d, 9, 0)

        data = ScheduleService.get_schedule(now=now, horizon_days=1, offset=-2)
        expected_start = shift_working_days(d, -2)  # Monday
        self.assertEqual(data['days'][0]['date'], expected_start.isoformat())


class ScheduleServiceEmptyTest(BaseTestCase):
    """No assigned tasks anywhere → empty workers list."""

    def test_empty_world(self):
        Task.objects.update(assignee=None)
        data = ScheduleService.get_schedule(now=dj_tz.now())
        self.assertEqual(data['workers'], [])
        self.assertIn('day_shape', data)
        self.assertIn('days', data)
        self.assertIn('jobs', data)


class PendingTaskTest(BaseTestCase):

    def test_one_pending_task_emits_forecast(self):
        user, task = _seed_user_with_pending_task()
        now = local_dt(date_at_weekday(2), 9, 0)  # Wed 9am
        data = ScheduleService.get_schedule(now=now)
        worker = next(w for w in data['workers'] if w['user']['id'] == user.pk)
        bars = worker['bars']
        forecasts = [b for b in bars if b['kind'] == 'forecast']
        self.assertEqual(len(forecasts), 1)
        self.assertEqual(forecasts[0]['task_id'], task.pk)
        self.assertEqual(forecasts[0]['est_minutes'], 120)
        self.assertEqual(forecasts[0]['elapsed_minutes'], 0)
        self.assertEqual(len(forecasts[0]['segments']), 1)


class PendingTaskCrossingsTest(BaseTestCase):

    def _setup(self, est_minutes, weekday_target, hh, mm):
        user, task = _seed_user_with_pending_task(est_minutes=est_minutes)
        now = local_dt(date_at_weekday(weekday_target), hh, mm)
        data = ScheduleService.get_schedule(now=now)
        worker = next(w for w in data['workers'] if w['user']['id'] == user.pk)
        return data, worker['bars']

    def test_midday_span_is_one_segment(self):
        # The workday is continuous (no lunch); a task spanning midday stays
        # a single segment.
        _, bars = self._setup(120, weekday_target=2, hh=11, mm=0)
        segs = bars[0]['segments']
        self.assertEqual(len(segs), 1)

    def test_crosses_overnight(self):
        _, bars = self._setup(180, weekday_target=1, hh=15, mm=0)
        segs = bars[0]['segments']
        self.assertEqual(len(segs), 2)

    def test_crosses_weekend(self):
        _, bars = self._setup(180, weekday_target=4, hh=15, mm=0)
        segs = bars[0]['segments']
        self.assertEqual(len(segs), 2)


class InProgressTaskTest(BaseTestCase):

    def test_in_progress_with_running_blep_emits_active_bar(self):
        user, task = _seed_user_with_pending_task(est_minutes=180)
        task.status = Task.STATUS_IN_PROGRESS
        task.save()
        d = date_at_weekday(2)
        start = local_dt(d, 9, 0)
        Blep.objects.create(user=user, task=task, start_time=start, end_time=None)
        now = start + timedelta(hours=1)

        data = ScheduleService.get_schedule(now=now)
        worker = next(w for w in data['workers'] if w['user']['id'] == user.pk)
        actives = [b for b in worker['bars'] if b['kind'] == 'active']
        self.assertEqual(len(actives), 1)
        bar = actives[0]
        self.assertTrue(bar['is_running'])
        self.assertEqual(bar['est_minutes'], 180)
        self.assertEqual(bar['elapsed_minutes'], 60)
        self.assertEqual(len(bar['segments']), 1)
        seg = bar['segments'][0]
        self.assertIsNotNone(seg['est_fill_to'])
        self.assertIsNotNone(seg['actual_fill_to'])


class OverrunCascadeTest(BaseTestCase):

    def test_overrun_pushes_next_task_later(self):
        user, task1 = _seed_user_with_pending_task(est_minutes=60, name='T1')
        task1.status = Task.STATUS_IN_PROGRESS
        task1.save()
        rs = RateScheme.objects.first()
        task2 = Task.objects.create(
            job=task1.job, assignee=user, rate_scheme=rs,
            name='T2', est_worker_time=timedelta(minutes=60),
            worker_queue=2, status=Task.STATUS_PENDING,
        )
        d = date_at_weekday(2)
        t1_start = local_dt(d, 9, 0)
        Blep.objects.create(user=user, task=task1, start_time=t1_start, end_time=None)
        now = t1_start + timedelta(hours=2)  # 2h elapsed on a 1h estimate

        data = ScheduleService.get_schedule(now=now)
        worker = next(w for w in data['workers'] if w['user']['id'] == user.pk)
        t2 = next(b for b in worker['bars'] if b['task_id'] == task2.pk)
        self.assertEqual(t2['kind'], 'forecast')
        t2_start = datetime.fromisoformat(t2['segments'][0]['start'])
        self.assertGreaterEqual(t2_start, now)


class CompletedEarlyTest(BaseTestCase):

    def test_completed_early_pulls_next_up_but_not_before_now(self):
        # T1 estimated 2h, started 09:00, finished early at 10:00. The plan
        # said T2 would start ~11:00; finishing early frees the slot. But by
        # the time we render it's 10:30, and T2 (pending, not started) can't
        # forecast before now — so it lands at 10:30, not at 10:10 (the
        # completed end + buffer, which is in the past).
        user, task1 = _seed_user_with_pending_task(est_minutes=120, name='T1')
        rs = RateScheme.objects.first()
        task2 = Task.objects.create(
            job=task1.job, assignee=user, rate_scheme=rs,
            name='T2', est_worker_time=timedelta(minutes=60),
            worker_queue=2, status=Task.STATUS_PENDING,
        )
        d = date_at_weekday(2)
        t1_start = local_dt(d, 9, 0)
        t1_end = t1_start + timedelta(minutes=60)  # took 1h, est was 2h
        task1.status = Task.STATUS_IN_PROGRESS; task1.save()
        task1.status = Task.STATUS_COMPLETE; task1.save()
        Blep.objects.create(user=user, task=task1, start_time=t1_start, end_time=t1_end)
        now = t1_end + timedelta(minutes=30)  # 10:30

        data = ScheduleService.get_schedule(now=now)
        worker = next(w for w in data['workers'] if w['user']['id'] == user.pk)
        bars_by_task = {b['task_id']: b for b in worker['bars']}
        self.assertEqual(bars_by_task[task1.pk]['kind'], 'historical')
        t2_start = datetime.fromisoformat(
            bars_by_task[task2.pk]['segments'][0]['start']
        )
        # Floored at now, not the completed end + buffer (10:10, in the past).
        self.assertEqual(t2_start, now)

    def test_early_offhours_completion_does_not_push_pending_before_now(self):
        # The reported case: a worker did early off-hours work (07:00–07:30),
        # completed the task, and it's now 09:00. The pending task must not
        # render behind the now line.
        user, task1 = _seed_user_with_pending_task(est_minutes=60, name='Early1')
        rs = RateScheme.objects.first()
        task2 = Task.objects.create(
            job=task1.job, assignee=user, rate_scheme=rs,
            name='Early2', est_worker_time=timedelta(minutes=60),
            worker_queue=2, status=Task.STATUS_PENDING,
        )
        d = date_at_weekday(2)
        t1_start = local_dt(d, 7, 0)
        t1_end = local_dt(d, 7, 30)
        task1.status = Task.STATUS_IN_PROGRESS; task1.save()
        task1.status = Task.STATUS_COMPLETE; task1.save()
        Blep.objects.create(user=user, task=task1, start_time=t1_start, end_time=t1_end)
        now = local_dt(d, 9, 0)

        data = ScheduleService.get_schedule(now=now)
        worker = next(w for w in data['workers'] if w['user']['id'] == user.pk)
        t2 = next(b for b in worker['bars'] if b['task_id'] == task2.pk)
        t2_start = datetime.fromisoformat(t2['segments'][0]['start'])
        self.assertGreaterEqual(t2_start, now)


class BlockedTaskTest(BaseTestCase):

    def test_blocked_task_emits_parked_and_does_not_consume_cursor(self):
        user, task1 = _seed_user_with_pending_task(est_minutes=60, name='T1 blocked')
        # pending → in_progress → blocked
        task1.status = Task.STATUS_IN_PROGRESS; task1.save()
        task1.status = Task.STATUS_BLOCKED; task1.save()
        rs = RateScheme.objects.first()
        task2 = Task.objects.create(
            job=task1.job, assignee=user, rate_scheme=rs,
            name='T2', est_worker_time=timedelta(minutes=60),
            worker_queue=2, status=Task.STATUS_PENDING,
        )
        now = local_dt(date_at_weekday(2), 9, 0)

        data = ScheduleService.get_schedule(now=now)
        worker = next(w for w in data['workers'] if w['user']['id'] == user.pk)
        bars_by = {(b['task_id'], b['kind']): b for b in worker['bars']}
        self.assertIn((task1.pk, 'parked'), bars_by)
        t2_start = datetime.fromisoformat(
            bars_by[(task2.pk, 'forecast')]['segments'][0]['start']
        )
        self.assertEqual(t2_start, now)


class HistoricalShowsEstimateTest(BaseTestCase):
    """Completed (historical) bars show the full estimate as the light
    layer and the actuals as the dark layer — never truncating the
    estimate to the actual span."""

    def _completed_task(self, est_minutes, actual_minutes, username):
        user, task = _seed_user_with_pending_task(
            est_minutes=est_minutes, name='C', username=username,
        )
        d = date_at_weekday(2)
        start = local_dt(d, 9, 0)
        end = start + timedelta(minutes=actual_minutes)
        task.status = Task.STATUS_IN_PROGRESS; task.save()
        task.status = Task.STATUS_COMPLETE; task.save()
        Blep.objects.create(user=user, task=task, start_time=start, end_time=end)
        now = end + timedelta(minutes=30)
        data = ScheduleService.get_schedule(now=now)
        worker = next(w for w in data['workers'] if w['user']['id'] == user.pk)
        bar = next(b for b in worker['bars'] if b['task_id'] == task.pk)
        return bar

    def test_early_finish_shows_estimate_past_actuals(self):
        # est 60m, took 30m → light (est) ends after dark (actual).
        bar = self._completed_task(60, 30, 'hist_early')
        self.assertEqual(bar['kind'], 'historical')
        seg = bar['segments'][-1]
        est_end = datetime.fromisoformat(seg['est_fill_to'])
        actual_end = datetime.fromisoformat(seg['actual_fill_to'])
        self.assertGreater(est_end, actual_end)

    def test_overrun_shows_actuals_past_estimate(self):
        # est 30m, took 60m → dark (actual) ends after light (est).
        bar = self._completed_task(30, 60, 'hist_over')
        seg = bar['segments'][-1]
        est_end = datetime.fromisoformat(seg['est_fill_to'])
        actual_end = datetime.fromisoformat(seg['actual_fill_to'])
        self.assertGreater(actual_end, est_end)


class OnBehalfApearsOnScheduleTest(BaseTestCase):
    """A blep started on a worker's behalf must render in that worker's
    lane, exactly as a self-started blep would."""

    def _grant_manage_time(self, user):
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(
            codename='can_manage_time', content_type__app_label='core',
        )
        user.user_permissions.add(perm)
        return User.objects.get(pk=user.pk)

    def test_on_behalf_start_shows_in_target_lane(self):
        from unittest.mock import patch
        from apps.jobs.services import TaskLifecycleService
        worker, task = _seed_user_with_pending_task(
            est_minutes=120, name='OBsched', username='ob_sched_worker',
        )
        # Approve the job so start_work is allowed.
        job = task.job
        for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
            job.status = s
            job.save()
        manager = self._grant_manage_time(
            User.objects.create_user(username='ob_sched_mgr', password='x')
        )

        d = date_at_weekday(2)
        start = local_dt(d, 9, 0)
        with patch('django.utils.timezone.now', return_value=start):
            TaskLifecycleService.start_work(task.pk, manager, on_behalf_of=worker)

        later = local_dt(d, 9, 30)
        data = ScheduleService.get_schedule(now=later)
        lanes = {w['user']['id']: w for w in data['workers']}
        self.assertIn(worker.pk, lanes, "worker should have a lane")
        bars = [b for b in lanes[worker.pk]['bars'] if b['task_id'] == task.pk]
        self.assertTrue(bars, "on-behalf task should appear in the worker's lane")


class FourTaskWorkerWithActiveBlepTest(BaseTestCase):
    """Reproduce the reported state: a worker assigned 4 tasks — 2 pending,
    1 completed (closed blep today), 1 in-progress with an open blep started
    ~15 min ago. All four should appear in the lane."""

    def test_active_assigned_task_appears(self):
        worker, t_active = _seed_user_with_pending_task(
            est_minutes=120, name='Active', username='four_worker',
        )
        job = t_active.job
        rs = RateScheme.objects.first()
        t_done = Task.objects.create(
            job=job, assignee=worker, rate_scheme=rs, name='Done',
            est_worker_time=timedelta(minutes=60), worker_queue=2,
            status=Task.STATUS_COMPLETE,
        )
        t_p1 = Task.objects.create(
            job=job, assignee=worker, rate_scheme=rs, name='P1',
            est_worker_time=timedelta(minutes=60), worker_queue=3,
            status=Task.STATUS_PENDING,
        )
        t_p2 = Task.objects.create(
            job=job, assignee=worker, rate_scheme=rs, name='P2',
            est_worker_time=timedelta(minutes=60), worker_queue=4,
            status=Task.STATUS_PENDING,
        )

        d = date_at_weekday(2)
        # Active task: in_progress, open blep started 15 min before "now".
        Task.objects.filter(pk=t_active.pk).update(status=Task.STATUS_IN_PROGRESS)
        now = local_dt(d, 14, 0)
        Blep.objects.create(
            user=worker, task=t_active,
            start_time=local_dt(d, 13, 45), end_time=None,
        )
        # Completed task: closed blep earlier today (in window).
        Blep.objects.create(
            user=worker, task=t_done,
            start_time=local_dt(d, 9, 0), end_time=local_dt(d, 10, 0),
        )

        data = ScheduleService.get_schedule(now=now)
        lane = next(w for w in data['workers'] if w['user']['id'] == worker.pk)
        present = {b['task_id'] for b in lane['bars']}
        # Build a readable failure message listing what rendered.
        summary = [(b['task_id'], b['kind'], len(b['segments'])) for b in lane['bars']]
        self.assertIn(
            t_active.pk, present,
            f"active task missing. bars={summary}; "
            f"active={t_active.pk} done={t_done.pk} p1={t_p1.pk} p2={t_p2.pk}",
        )


class PausedInProgressTaskTest(BaseTestCase):
    """A task started then abandoned for another (in_progress, only a closed
    blep) must not stamp a full estimate bar onto its brief past blep — that
    overlaps the actually-active task. It forecasts the remaining estimate
    ahead instead, leaving the active task fully visible."""

    def test_paused_task_does_not_overlap_active_task(self):
        worker, t_active = _seed_user_with_pending_task(
            est_minutes=60, name='Active', username='paused_worker',
        )
        job = t_active.job
        rs = RateScheme.objects.first()
        t_paused = Task.objects.create(
            job=job, assignee=worker, rate_scheme=rs, name='Paused',
            est_worker_time=timedelta(minutes=60), worker_queue=2,
            status=Task.STATUS_IN_PROGRESS,
        )
        Task.objects.filter(pk=t_active.pk).update(status=Task.STATUS_IN_PROGRESS)

        d = date_at_weekday(2)
        # Paused: a 34-second closed blep, then the worker switched to active.
        Blep.objects.create(
            user=worker, task=t_paused,
            start_time=local_dt(d, 9, 0),
            end_time=local_dt(d, 9, 0) + timedelta(seconds=34),
        )
        # Active: open blep started right after.
        Blep.objects.create(
            user=worker, task=t_active,
            start_time=local_dt(d, 9, 0) + timedelta(seconds=34), end_time=None,
        )
        now = local_dt(d, 9, 30)

        data = ScheduleService.get_schedule(now=now)
        lane = next(w for w in data['workers'] if w['user']['id'] == worker.pk)

        active_bar = next(b for b in lane['bars']
                          if b['task_id'] == t_active.pk and b['kind'] == 'active')
        # The paused task forecasts AHEAD (a forecast bar), not an active bar
        # anchored to its past blep.
        paused_forecast = next(
            (b for b in lane['bars']
             if b['task_id'] == t_paused.pk and b['kind'] == 'forecast'), None,
        )
        self.assertIsNotNone(paused_forecast, "paused task should forecast ahead")
        self.assertFalse(
            any(b['task_id'] == t_paused.pk and b['kind'] == 'active'
                for b in lane['bars']),
            "paused task should not render as an active bar",
        )
        # The paused forecast starts at/after the active task's end (no overlap).
        active_end = max(datetime.fromisoformat(s['end'])
                         for s in active_bar['segments'])
        forecast_start = datetime.fromisoformat(paused_forecast['segments'][0]['start'])
        self.assertGreaterEqual(forecast_start, active_end)


class OverworkedPausedTaskTest(BaseTestCase):
    """A worked-past-estimate task that isn't marked complete (in_progress,
    one closed blep, no remaining) must still show its planned time as the
    est-vs-actual historical — the overrun must not suppress it."""

    def test_overworked_paused_task_shows_estimate_layer(self):
        worker, task = _seed_user_with_pending_task(
            est_minutes=60, name='Overrun', username='overrun_worker',
        )
        Task.objects.filter(pk=task.pk).update(status=Task.STATUS_IN_PROGRESS)
        d = date_at_weekday(2)
        # Worked 2x the estimate (120 min on a 60-min estimate), then stopped.
        Blep.objects.create(
            user=worker, task=task,
            start_time=local_dt(d, 9, 0), end_time=local_dt(d, 11, 0),
        )
        now = local_dt(d, 11, 30)

        data = ScheduleService.get_schedule(now=now)
        lane = next(w for w in data['workers'] if w['user']['id'] == worker.pk)
        bars = [b for b in lane['bars'] if b['task_id'] == task.pk]
        self.assertTrue(bars, "overworked paused task should still appear")
        hist = next(b for b in bars if b['kind'] == 'historical')
        # The estimate (light) layer is present and ends BEFORE the actuals
        # (dark), i.e. the overrun shows.
        seg = hist['segments'][0]
        self.assertIsNotNone(seg['est_fill_to'], "planned time (estimate) should show")
        est_end = datetime.fromisoformat(seg['est_fill_to'])
        actual_end = datetime.fromisoformat(seg['actual_fill_to'])
        self.assertGreater(actual_end, est_end)


class FreshNonAssigneeBlepTest(BaseTestCase):
    """A just-started blep by a NON-assignee (no estimate layer) must still
    render — without an estimate to extend the bar, a zero-elapsed blep
    would otherwise collapse to no segments and be invisible."""

    def test_fresh_non_assignee_blep_renders(self):
        assignee, task = _seed_user_with_pending_task(
            est_minutes=120, name='FNA', username='fna_assignee',
        )
        Task.objects.filter(pk=task.pk).update(status=Task.STATUS_IN_PROGRESS)
        helper = User.objects.create_user(username='fna_helper', password='x')

        d = date_at_weekday(2)
        start = local_dt(d, 9, 0)
        Blep.objects.create(user=helper, task=task, start_time=start, end_time=None)

        # View at the same instant the blep started — zero elapsed.
        data = ScheduleService.get_schedule(now=start)
        lanes = {w['user']['id']: w for w in data['workers']}
        self.assertIn(helper.pk, lanes, "helper should have a lane")
        bars = [b for b in lanes[helper.pk]['bars'] if b['task_id'] == task.pk]
        self.assertTrue(bars, "fresh non-assignee blep should render a bar")
        self.assertTrue(bars[0]['segments'], "bar should have at least one segment")


class ConcurrentBlepsTest(BaseTestCase):
    """Two workers blepping the same task each see it in their own lane,
    anchored to their own bleps. The non-assignee shows up too."""

    def test_both_workers_show_the_shared_task(self):
        assignee, task = _seed_user_with_pending_task(
            est_minutes=120, name='Shared', username='owner_a',
        )
        other = User.objects.create_user(username='joiner_b', password='x')
        task.status = Task.STATUS_IN_PROGRESS
        task.save()

        d = date_at_weekday(2)
        a_start = local_dt(d, 9, 0)
        b_start = local_dt(d, 9, 10)
        Blep.objects.create(user=assignee, task=task, start_time=a_start, end_time=None)
        Blep.objects.create(user=other, task=task, start_time=b_start, end_time=None)
        now = local_dt(d, 9, 30)

        data = ScheduleService.get_schedule(now=now)
        lanes = {w['user']['id']: w for w in data['workers']}
        self.assertIn(assignee.pk, lanes)
        self.assertIn(other.pk, lanes)

        a_bar = next(b for b in lanes[assignee.pk]['bars']
                     if b['task_id'] == task.pk and b['kind'] == 'active')
        b_bar = next(b for b in lanes[other.pk]['bars']
                     if b['task_id'] == task.pk and b['kind'] == 'active')

        # Each lane's bar is anchored to that worker's own blep start.
        a_first = datetime.fromisoformat(a_bar['segments'][0]['start'])
        b_first = datetime.fromisoformat(b_bar['segments'][0]['start'])
        self.assertEqual(a_first, a_start)
        self.assertEqual(b_first, b_start)

        # The assignee's bar carries the estimate (light layer); the
        # non-assignee's shows only their actuals (no estimate layer).
        self.assertTrue(any(s['est_fill_to'] for s in a_bar['segments']))
        self.assertTrue(all(s['est_fill_to'] is None for s in b_bar['segments']))


class CompletedPlusActiveOrderingTest(BaseTestCase):
    """When a worker has BOTH a completed task and a currently-active task,
    the pending task that follows must not be drawn on top of the active.
    Completed tasks are processed before active (regardless of queue order),
    so the cursor sequence is past → present → future."""

    def test_pending_after_completed_plus_active_lands_after_active(self):
        user, completed = _seed_user_with_pending_task(
            est_minutes=30, name='Completed', username='copa_user',
        )
        rs = RateScheme.objects.first()
        # Build out the queue
        active = Task.objects.create(
            job=completed.job, assignee=user, rate_scheme=rs,
            name='Active', est_worker_time=timedelta(minutes=60),
            worker_queue=2, status=Task.STATUS_PENDING,
        )
        next_pending = Task.objects.create(
            job=completed.job, assignee=user, rate_scheme=rs,
            name='Next', est_worker_time=timedelta(minutes=60),
            worker_queue=3, status=Task.STATUS_PENDING,
        )

        # Drive completed → done with a blep, and active → in_progress with
        # a running blep.
        d = date_at_weekday(2)
        c_start = local_dt(d, 9, 0)
        c_end = c_start + timedelta(minutes=30)
        completed.status = Task.STATUS_IN_PROGRESS; completed.save()
        completed.status = Task.STATUS_COMPLETE; completed.save()
        Blep.objects.create(user=user, task=completed,
                            start_time=c_start, end_time=c_end)

        a_start = c_end + timedelta(minutes=10)  # 09:40
        active.status = Task.STATUS_IN_PROGRESS; active.save()
        Blep.objects.create(user=user, task=active, start_time=a_start, end_time=None)

        # "now" mid-way through the active task
        now = a_start + timedelta(minutes=20)  # 10:00, active running

        data = ScheduleService.get_schedule(now=now)
        worker = next(w for w in data['workers'] if w['user']['id'] == user.pk)
        bars = {b['task_id']: b for b in worker['bars']}

        active_bar = bars[active.pk]
        next_bar = bars[next_pending.pk]
        # Active's segment ends at active_start + est = 09:40 + 60 = 10:40.
        # Next pending must START at or after active end + buffer = 10:50,
        # NOT at completed's end + buffer (09:40), which would overlap.
        active_end = datetime.fromisoformat(active_bar['segments'][-1]['end'])
        next_start = datetime.fromisoformat(next_bar['segments'][0]['start'])
        self.assertGreaterEqual(next_start, active_end)


class YesterdayCompletedExcludedTest(BaseTestCase):

    def test_yesterday_completed_not_in_schedule(self):
        from apps.schedule.calendar_arithmetic import is_working_day as _iwd

        user, task = _seed_user_with_pending_task(est_minutes=60)
        task.status = Task.STATUS_IN_PROGRESS; task.save()
        task.status = Task.STATUS_COMPLETE; task.save()
        d_today = date_at_weekday(2)
        d_yesterday = d_today - timedelta(days=1)
        while not _iwd(d_yesterday):
            d_yesterday -= timedelta(days=1)
        b_start = local_dt(d_yesterday, 9, 0)
        b_end = b_start + timedelta(minutes=60)
        Blep.objects.create(user=user, task=task, start_time=b_start, end_time=b_end)

        now = local_dt(d_today, 9, 0)
        data = ScheduleService.get_schedule(now=now)
        workers = [w for w in data['workers'] if w['user']['id'] == user.pk]
        self.assertEqual(workers, [])
