from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import User
from apps.jobs.models import Blep, Job, Task
from apps.schedule.services import ScheduleService
from tests.base import BaseTestCase


class ScheduleAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_unauthenticated_blocked(self):
        response = self.client.get('/api/schedule/')
        self.assertIn(response.status_code, (401, 403))

    def test_authenticated_returns_envelope(self):
        user = User.objects.get(username='admin')
        self.client.force_authenticate(user=user)
        response = self.client.get('/api/schedule/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        for key in ('now', 'horizon_start', 'horizon_end', 'horizon_days',
                    'axis', 'days', 'jobs', 'workers'):
            self.assertIn(key, data)

    def test_days_param_respected(self):
        user = User.objects.get(username='admin')
        self.client.force_authenticate(user=user)
        response = self.client.get('/api/schedule/?days=2')
        self.assertEqual(response.json()['horizon_days'], 2)

    def test_days_param_clamped_high(self):
        user = User.objects.get(username='admin')
        self.client.force_authenticate(user=user)
        response = self.client.get('/api/schedule/?days=99')
        self.assertEqual(response.json()['horizon_days'], 14)

    def test_days_param_clamped_low(self):
        user = User.objects.get(username='admin')
        self.client.force_authenticate(user=user)
        response = self.client.get('/api/schedule/?days=0')
        self.assertEqual(response.json()['horizon_days'], 1)


class ScheduleOnHoldExclusionTest(BaseTestCase):
    """Tasks on on_hold jobs must not appear in the schedule output."""

    def _make_worker(self):
        return User.objects.create_user(
            username='worker_onhold_test',
            password='pass',
            first_name='Hold',
            last_name='Worker',
        )

    def _make_job(self, contact, *statuses):
        job = Job.objects.create(
            job_number=f'JOB-SCHED-ONHOLD-{timezone.now().timestamp()}',
            contact=contact,
            status=Job.STATUS_DRAFT,
        )
        for s in statuses:
            job.status = s
            job.save()
        return job

    def test_on_hold_job_task_worker_absent_from_schedule(self):
        """A worker whose only open task is on a held job must not
        appear in the schedule's workers list (no forecast while held)."""
        from apps.jobs.services import JobService
        contact = Job.objects.first().contact
        worker = self._make_worker()
        job = self._make_job(
            contact,
            Job.STATUS_SUBMITTED,
            Job.STATUS_APPROVED,
        )
        JobService.hold_job(job.pk, 'paused')
        job.refresh_from_db()
        Task.objects.create(
            name='Hold task',
            job=job,
            assignee=worker,
            status=Task.STATUS_PENDING,
            rate_scheme_id=1,
            est_worker_time=timedelta(hours=1),
        )
        result = ScheduleService.get_schedule(now=timezone.now())
        worker_ids = [w['user']['id'] for w in result['workers']]
        self.assertNotIn(worker.pk, worker_ids)

    def test_in_progress_job_task_worker_present_in_schedule(self):
        """A worker with an open task on an in_progress job DOES appear."""
        contact = Job.objects.first().contact
        worker2 = User.objects.create_user(
            username='worker_inprog_test',
            password='pass',
            first_name='Inprog',
            last_name='Worker',
        )
        job = self._make_job(
            contact,
            Job.STATUS_SUBMITTED,
            Job.STATUS_APPROVED,
            Job.STATUS_IN_PROGRESS,
        )
        Task.objects.create(
            name='Active task',
            job=job,
            assignee=worker2,
            status=Task.STATUS_PENDING,
            rate_scheme_id=1,
            est_worker_time=timedelta(hours=1),
        )
        result = ScheduleService.get_schedule(now=timezone.now())
        worker_ids = [w['user']['id'] for w in result['workers']]
        self.assertIn(worker2.pk, worker_ids)


class ScheduleWorkCompleteHistoryTest(BaseTestCase):
    """A work_complete job must drop off the chip strip, but the completed
    work it holds must still render in the worker's lane (so blep history
    survives, including when scrolling back). The chip strip mirrors the
    board's In Progress column (Job.status == in_progress); the lane shows
    all completed work regardless of job status."""

    def setUp(self):
        super().setUp()
        contact = Job.objects.first().contact
        self.worker = User.objects.create_user(
            username='worker_wc_test',
            password='pass',
            first_name='Done',
            last_name='Worker',
        )
        self.job = Job.objects.create(
            job_number=f'JOB-SCHED-WC-{timezone.now().timestamp()}',
            name='Finished Job',
            contact=contact,
            status=Job.STATUS_DRAFT,
        )
        for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                  Job.STATUS_IN_PROGRESS, Job.STATUS_WORK_COMPLETE):
            self.job.status = s
            self.job.save()
        self.task = Task.objects.create(
            name='Finished task',
            job=self.job,
            assignee=self.worker,
            status=Task.STATUS_COMPLETE,
            rate_scheme_id=1,
            est_worker_time=timedelta(hours=1),
        )
        now = timezone.now()
        Blep.objects.create(
            user=self.worker,
            task=self.task,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )

    def test_work_complete_job_absent_from_chip_strip(self):
        result = ScheduleService.get_schedule(now=timezone.now())
        job_ids = [j['job_id'] for j in result['jobs']]
        self.assertNotIn(self.job.pk, job_ids)

    def test_work_complete_task_present_in_worker_lane(self):
        result = ScheduleService.get_schedule(now=timezone.now())
        lane = next(
            (w for w in result['workers'] if w['user']['id'] == self.worker.pk),
            None,
        )
        self.assertIsNotNone(lane, 'worker lane should be present')
        bar_task_ids = [b['task_id'] for b in lane['bars']]
        self.assertIn(self.task.pk, bar_task_ids)

    def test_lane_bar_carries_job_number_and_name(self):
        """The bar is self-describing so the quick card doesn't need the job
        in the chip strip to show its number/name."""
        result = ScheduleService.get_schedule(now=timezone.now())
        lane = next(
            w for w in result['workers'] if w['user']['id'] == self.worker.pk
        )
        bar = next(b for b in lane['bars'] if b['task_id'] == self.task.pk)
        self.assertEqual(bar['job_number'], self.job.job_number)
        self.assertEqual(bar['job_name'], self.job.name)


class ScheduleForecastScopeTest(BaseTestCase):
    """Planned (forecast) work is scoped to in_progress jobs only — matching
    the board's In Progress column — and blocked tasks never forecast. Past
    work (actual bars) survives regardless of task/job status."""

    def setUp(self):
        super().setUp()
        self.contact = Job.objects.first().contact

    def _job(self, *statuses):
        job = Job.objects.create(
            job_number=f'JOB-SCHED-FS-{timezone.now().timestamp()}',
            name='Scope Job',
            contact=self.contact,
            status=Job.STATUS_DRAFT,
        )
        for s in statuses:
            job.status = s
            job.save()
        return job

    def _worker(self, username):
        return User.objects.create_user(
            username=username, password='pass',
            first_name=username, last_name='W',
        )

    def _task(self, job, worker, status, **extra):
        return Task.objects.create(
            name=f'{status} task',
            job=job,
            assignee=worker,
            status=status,
            rate_scheme_id=1,
            est_worker_time=timedelta(hours=1),
            **extra,
        )

    def _forecast_bars(self, result, worker, task):
        lane = next(
            (w for w in result['workers'] if w['user']['id'] == worker.pk), None
        )
        if lane is None:
            return []
        return [b for b in lane['bars']
                if b['task_id'] == task.pk and b['kind'] == 'forecast']

    def test_pending_task_on_approved_job_not_scheduled(self):
        """A pending task on an approved (not in_progress) job must not pull
        the worker onto the schedule nor the job into the chip strip."""
        worker = self._worker('fs_approved')
        job = self._job(Job.STATUS_SUBMITTED, Job.STATUS_APPROVED)
        task = self._task(job, worker, Task.STATUS_PENDING)

        result = ScheduleService.get_schedule(now=timezone.now())
        worker_ids = [w['user']['id'] for w in result['workers']]
        job_ids = [j['job_id'] for j in result['jobs']]
        self.assertNotIn(worker.pk, worker_ids)
        self.assertNotIn(job.pk, job_ids)

    def test_pending_task_on_in_progress_job_forecasts(self):
        """Sanity: a pending task on an in_progress job still forecasts."""
        worker = self._worker('fs_inprog')
        job = self._job(Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                        Job.STATUS_IN_PROGRESS)
        task = self._task(job, worker, Task.STATUS_PENDING)

        result = ScheduleService.get_schedule(now=timezone.now())
        job_ids = [j['job_id'] for j in result['jobs']]
        self.assertIn(job.pk, job_ids)
        self.assertEqual(len(self._forecast_bars(result, worker, task)), 1)

    def test_blocked_task_alone_not_scheduled(self):
        """A blocked task with no logged time must not pull the worker onto
        the schedule — blocked work has no place on the time axis."""
        worker = self._worker('fs_blocked')
        job = self._job(Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                        Job.STATUS_IN_PROGRESS)
        self._task(job, worker, Task.STATUS_BLOCKED, blocked_reason='waiting')

        result = ScheduleService.get_schedule(now=timezone.now())
        worker_ids = [w['user']['id'] for w in result['workers']]
        self.assertNotIn(worker.pk, worker_ids)

    def test_blocked_task_with_history_shows_actual_not_forecast(self):
        """A task worked then blocked keeps its past actual bars (history) but
        does not forecast forward."""
        worker = self._worker('fs_blocked_hist')
        job = self._job(Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                        Job.STATUS_IN_PROGRESS)
        task = self._task(job, worker, Task.STATUS_BLOCKED,
                          blocked_reason='stuck')
        now = timezone.now()
        Blep.objects.create(
            user=worker, task=task,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )

        result = ScheduleService.get_schedule(now=timezone.now())
        lane = next(
            (w for w in result['workers'] if w['user']['id'] == worker.pk), None
        )
        self.assertIsNotNone(lane, 'worker with past work should have a lane')
        kinds = {b['kind'] for b in lane['bars'] if b['task_id'] == task.pk}
        self.assertIn('actual', kinds)
        self.assertNotIn('forecast', kinds)


class ScheduleAllInProgressChipsTest(BaseTestCase):
    """The chip strip shows every in_progress job — matching the board's In
    Progress column — even ones with no assigned work (or no tasks at all).
    Lanes still only draw bars for jobs with actual/forecast work; a chip
    without bars is fine and mirrors the board."""

    def setUp(self):
        super().setUp()
        self.contact = Job.objects.first().contact

    def _in_progress_job(self):
        job = Job.objects.create(
            job_number=f'JOB-SCHED-ALL-{timezone.now().timestamp()}',
            name='Taskless Job',
            contact=self.contact,
            status=Job.STATUS_DRAFT,
        )
        for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                  Job.STATUS_IN_PROGRESS):
            job.status = s
            job.save()
        return job

    def test_in_progress_job_with_no_tasks_appears_in_chip_strip(self):
        job = self._in_progress_job()
        result = ScheduleService.get_schedule(now=timezone.now())
        job_ids = [j['job_id'] for j in result['jobs']]
        self.assertIn(job.pk, job_ids)

    def test_in_progress_job_with_only_unassigned_task_appears(self):
        job = self._in_progress_job()
        Task.objects.create(
            name='Unassigned', job=job, assignee=None,
            status=Task.STATUS_PENDING, rate_scheme_id=1,
            est_worker_time=timedelta(hours=1),
        )
        result = ScheduleService.get_schedule(now=timezone.now())
        job_ids = [j['job_id'] for j in result['jobs']]
        self.assertIn(job.pk, job_ids)


class ScheduleChipOrderTest(BaseTestCase):
    """The jobs payload (chip strip) is ordered by due_date, matching the
    board's In Progress column — the two reuse the same JobChipStrip and
    must present chips in the same order."""

    def setUp(self):
        super().setUp()
        self.contact = Job.objects.first().contact
        self.worker = User.objects.create_user(
            username='chip_order_w', password='pass',
            first_name='Chip', last_name='Order',
        )

    def _in_progress_job_with_task(self, due_date):
        job = Job.objects.create(
            job_number=f'JOB-SCHED-ORD-{timezone.now().timestamp()}',
            name='Order Job',
            contact=self.contact,
            due_date=due_date,
            status=Job.STATUS_DRAFT,
        )
        for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                  Job.STATUS_IN_PROGRESS):
            job.status = s
            job.save()
        Task.objects.create(
            name='Order task', job=job, assignee=self.worker,
            status=Task.STATUS_PENDING, rate_scheme_id=1,
            est_worker_time=timedelta(hours=1),
        )
        return job

    def test_jobs_payload_ordered_by_due_date(self):
        now = timezone.now()
        # Create the later-due job FIRST so it has the lower pk; without an
        # explicit order_by it would sort ahead of the earlier-due job.
        later = self._in_progress_job_with_task(now + timedelta(days=10))
        earlier = self._in_progress_job_with_task(now + timedelta(days=1))

        result = ScheduleService.get_schedule(now=timezone.now())
        ordered_ids = [j['job_id'] for j in result['jobs']
                       if j['job_id'] in (earlier.pk, later.pk)]
        self.assertEqual(ordered_ids, [earlier.pk, later.pk])


class ScheduleJobsPMNameTest(BaseTestCase):
    """jobs_payload must include project_manager_name."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        contact = Job.objects.first().contact
        self.worker = User.objects.create_user(
            username='worker_pm_test',
            password='pass',
            first_name='Test',
            last_name='Worker',
        )
        self.job = Job.objects.create(
            job_number=f'JOB-SCHED-PM-{timezone.now().timestamp()}',
            contact=contact,
            status=Job.STATUS_DRAFT,
        )
        for status in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS):
            self.job.status = status
            self.job.save()
        Task.objects.create(
            name='PM test task',
            job=self.job,
            assignee=self.worker,
            status=Task.STATUS_PENDING,
            rate_scheme_id=1,
            est_worker_time=timedelta(hours=1),
        )

    def test_schedule_jobs_include_pm_name(self):
        pm = User.objects.create_user(
            username='pm_erin', first_name='Erin', last_name='Evans', password='x'
        )
        self.job.project_manager = pm
        self.job.save()

        self.client.force_authenticate(user=User.objects.get(username='admin'))
        resp = self.client.get('/api/schedule/')
        self.assertEqual(resp.status_code, 200)
        match = [j for j in resp.data['jobs'] if j['job_id'] == self.job.pk]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]['project_manager_name'], 'Erin Evans')

    def test_schedule_jobs_pm_name_null_when_no_pm(self):
        self.job.project_manager = None
        self.job.save()

        self.client.force_authenticate(user=User.objects.get(username='admin'))
        resp = self.client.get('/api/schedule/')
        self.assertEqual(resp.status_code, 200)
        match = [j for j in resp.data['jobs'] if j['job_id'] == self.job.pk]
        self.assertEqual(len(match), 1)
        self.assertIsNone(match[0]['project_manager_name'])


class ScheduleWorkDrivenScopeTest(BaseTestCase):
    """Phase 1 (work-driven surfaces): assigned, still-planned pre-approval
    work forecasts and is flagged; held jobs keep their history bars but
    never forecast."""

    def setUp(self):
        super().setUp()
        self.contact = Job.objects.first().contact

    def _job(self, *statuses):
        job = Job.objects.create(
            job_number=f'JOB-SCHED-WD-{timezone.now().timestamp()}',
            name='WorkDriven Job',
            contact=self.contact,
            status=Job.STATUS_DRAFT,
        )
        for s in statuses:
            job.status = s
            job.save()
        return job

    def _worker(self, username):
        return User.objects.create_user(
            username=username, password='pass',
            first_name=username, last_name='W',
        )

    def _task(self, job, worker, status=Task.STATUS_PENDING, **extra):
        return Task.objects.create(
            name='WD task', job=job, assignee=worker, status=status,
            rate_scheme_id=1, est_worker_time=timedelta(hours=1), **extra,
        )

    def _lane(self, result, worker):
        return next(
            (w for w in result['workers'] if w['user']['id'] == worker.pk), None
        )

    def test_assigned_pending_task_on_draft_job_forecasts_flagged(self):
        worker = self._worker('wd_draft')
        job = self._job()  # stays draft
        task = self._task(job, worker)

        result = ScheduleService.get_schedule(now=timezone.now())
        lane = self._lane(result, worker)
        self.assertIsNotNone(lane)
        bars = [b for b in lane['bars'] if b['task_id'] == task.pk]
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]['kind'], 'forecast')
        self.assertTrue(bars[0]['pre_approval'])
        # The job also reaches the chip strip, flagged.
        chip = next(j for j in result['jobs'] if j['job_id'] == job.pk)
        self.assertTrue(chip['pre_approval'])

    def test_submitted_job_assigned_task_forecasts(self):
        worker = self._worker('wd_submitted')
        job = self._job(Job.STATUS_SUBMITTED)
        task = self._task(job, worker)
        result = ScheduleService.get_schedule(now=timezone.now())
        lane = self._lane(result, worker)
        self.assertIsNotNone(lane)
        self.assertEqual(
            [b['kind'] for b in lane['bars'] if b['task_id'] == task.pk],
            ['forecast'],
        )

    def test_unassigned_pre_approval_task_emits_nothing(self):
        worker = self._worker('wd_unassigned')
        job = self._job()
        Task.objects.create(
            name='Unassigned quote task', job=job, status=Task.STATUS_PENDING,
            rate_scheme_id=1,
        )
        result = ScheduleService.get_schedule(now=timezone.now())
        self.assertIsNone(self._lane(result, worker))
        self.assertNotIn(job.pk, [j['job_id'] for j in result['jobs']])

    def test_in_progress_bar_not_flagged_pre_approval(self):
        worker = self._worker('wd_plain')
        job = self._job(Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                        Job.STATUS_IN_PROGRESS)
        task = self._task(job, worker)
        result = ScheduleService.get_schedule(now=timezone.now())
        bar = next(b for b in self._lane(result, worker)['bars']
                   if b['task_id'] == task.pk)
        self.assertFalse(bar['pre_approval'])

    def test_chip_payload_carries_task_counts(self):
        """The chip hover popup renders the board JobCard progress bar, so
        the schedule's jobs payload must carry task_total/task_completed
        exactly like the board's get_approved_data."""
        worker = self._worker('wd_counts')
        job = self._job(Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                        Job.STATUS_IN_PROGRESS)
        self._task(job, worker, status=Task.STATUS_COMPLETE)
        self._task(job, worker, status=Task.STATUS_PENDING)
        # Cancelled tasks don't count (matches the board's aggregate).
        self._task(job, worker, status=Task.STATUS_CANCELLED)

        result = ScheduleService.get_schedule(now=timezone.now())
        chip = next(j for j in result['jobs'] if j['job_id'] == job.pk)
        self.assertEqual(chip['task_total'], 2)
        self.assertEqual(chip['task_completed'], 1)

    def test_held_job_history_renders_but_never_forecasts(self):
        """A held in_progress job: past bleps stay visible as actuals; the
        planned remainder emits no forecast while held."""
        from apps.jobs.services import JobService
        worker = self._worker('wd_held')
        job = self._job(Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                        Job.STATUS_IN_PROGRESS)
        task = self._task(job, worker, status=Task.STATUS_IN_PROGRESS)
        now = timezone.now()
        Blep.objects.create(
            user=worker, task=task,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )
        JobService.hold_job(job.pk, 'change order pending')

        result = ScheduleService.get_schedule(now=now)
        lane = self._lane(result, worker)
        self.assertIsNotNone(lane)
        kinds = [b['kind'] for b in lane['bars'] if b['task_id'] == task.pk]
        self.assertEqual(kinds, ['actual'])
        # The held in_progress job keeps its chip, flagged.
        chip = next(j for j in result['jobs'] if j['job_id'] == job.pk)
        self.assertTrue(chip['on_hold'])
        self.assertEqual(chip['hold_reason'], 'change order pending')
