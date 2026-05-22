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
        self.assertEqual(shape.lunch_start, time(12, 0))
        self.assertEqual(shape.lunch_end, time(13, 0))
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

    def test_crosses_lunch(self):
        _, bars = self._setup(120, weekday_target=2, hh=11, mm=0)
        segs = bars[0]['segments']
        self.assertEqual(len(segs), 2)
        self.assertTrue(segs[0]['continues_right'])
        self.assertTrue(segs[1]['continues_left'])

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

    def test_completed_today_emits_historical_and_pulls_next_earlier(self):
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
        now = t1_end + timedelta(minutes=30)

        data = ScheduleService.get_schedule(now=now)
        worker = next(w for w in data['workers'] if w['user']['id'] == user.pk)
        bars_by_task = {b['task_id']: b for b in worker['bars']}
        self.assertEqual(bars_by_task[task1.pk]['kind'], 'historical')
        t2_start = datetime.fromisoformat(
            bars_by_task[task2.pk]['segments'][0]['start']
        )
        expected = t1_end + timedelta(minutes=10)  # buffer
        self.assertEqual(t2_start, expected)


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
