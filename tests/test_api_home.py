from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from tests.base import FixtureTestCase
from apps.jobs.models import Blep, Job, Task, WorkOrder
from apps.contacts.models import Contact
from apps.core.models import Configuration

User = get_user_model()


class CurrentBlepEndpointTest(FixtureTestCase):
    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'},
        )
        self.contact = Contact.objects.first()
        self.user = User.objects.create_user(username='worker', password='testpass')
        self.client.login(username='worker', password='testpass')
        self.job = Job.objects.create(
            job_number='JOB-HOME-0001',
            name='Home Test Job',
            status='approved',
            contact=self.contact,
        )
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            name='Task A', work_order=self.wo, assignee=self.user,
            status=Task.STATUS_IN_PROGRESS,
        )

    def test_returns_null_when_no_open_blep(self):
        response = self.client.get('/api/bleps/current/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())

    def test_returns_open_blep_for_user(self):
        Blep.objects.create(
            user=self.user, task=self.task,
            start_time=timezone.now(),
        )
        response = self.client.get('/api/bleps/current/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNotNone(data)
        self.assertIn('id', data)
        self.assertIn('start_time', data)
        self.assertEqual(data['task']['id'], self.task.pk)
        self.assertEqual(data['task']['name'], 'Task A')
        self.assertEqual(data['job']['id'], self.job.pk)
        self.assertEqual(data['job']['job_number'], 'JOB-HOME-0001')
        self.assertEqual(data['work_order']['id'], self.wo.pk)

    def test_ignores_closed_bleps(self):
        now = timezone.now()
        Blep.objects.create(
            user=self.user, task=self.task,
            start_time=now - timedelta(hours=2), end_time=now - timedelta(hours=1),
        )
        response = self.client.get('/api/bleps/current/')
        self.assertIsNone(response.json())

    def test_ignores_other_users_bleps(self):
        other = User.objects.create_user(username='other', password='testpass')
        Blep.objects.create(
            user=other, task=self.task, start_time=timezone.now(),
        )
        response = self.client.get('/api/bleps/current/')
        self.assertIsNone(response.json())

    def test_returns_most_recent_when_multiple_open(self):
        now = timezone.now()
        Blep.objects.create(
            user=self.user, task=self.task,
            start_time=now - timedelta(hours=3),
        )
        newer_task = Task.objects.create(
            name='Task B', work_order=self.wo, assignee=self.user,
            status=Task.STATUS_IN_PROGRESS,
        )
        Blep.objects.create(
            user=self.user, task=newer_task,
            start_time=now - timedelta(minutes=5),
        )
        response = self.client.get('/api/bleps/current/')
        data = response.json()
        self.assertEqual(data['task']['id'], newer_task.pk)

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.get('/api/bleps/current/')
        self.assertEqual(response.status_code, 403)


class HomeEndpointTest(FixtureTestCase):
    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'},
        )
        self.contact = Contact.objects.first()
        self.user = User.objects.create_user(username='worker', password='testpass')
        self.other = User.objects.create_user(username='other', password='testpass')
        self.client.login(username='worker', password='testpass')
        self.job = Job.objects.create(
            job_number='JOB-HOME-A', name='Alpha Job',
            status='approved', contact=self.contact,
        )
        self.wo = WorkOrder.objects.create(job=self.job)

    def _make_task(self, name, status=Task.STATUS_PENDING, assignee=None,
                   worker_queue=None, work_order=None, est_worksheet=None):
        kwargs = {'name': name, 'status': status}
        if assignee is not None:
            kwargs['assignee'] = assignee
        if worker_queue is not None:
            kwargs['worker_queue'] = worker_queue
        if work_order is not None:
            kwargs['work_order'] = work_order
        if est_worksheet is not None:
            kwargs['est_worksheet'] = est_worksheet
        return Task.objects.create(**kwargs)

    def test_home_requires_authentication(self):
        self.client.logout()
        response = self.client.get('/api/home/')
        self.assertEqual(response.status_code, 403)

    def test_home_returns_shape(self):
        response = self.client.get('/api/home/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('assigned_tasks', data)
        self.assertIn('recent_jobs', data)

    def test_assigned_tasks_includes_only_work_order_tasks(self):
        self._make_task('WO task', assignee=self.user, worker_queue=1,
                        work_order=self.wo)
        # Create an EstWorksheet task assigned to the user — should be excluded
        from apps.estimates.models import EstWorksheet
        worksheet = EstWorksheet.objects.create(job=self.job)
        self._make_task('Worksheet task', assignee=self.user, worker_queue=1,
                        est_worksheet=worksheet)

        response = self.client.get('/api/home/')
        names = [t['name'] for t in response.json()['assigned_tasks']]
        self.assertIn('WO task', names)
        self.assertNotIn('Worksheet task', names)

    def test_assigned_tasks_excludes_completed_and_cancelled(self):
        self._make_task('Pending task', status=Task.STATUS_PENDING,
                        assignee=self.user, worker_queue=1, work_order=self.wo)
        self._make_task('Blocked task', status=Task.STATUS_BLOCKED,
                        assignee=self.user, worker_queue=2, work_order=self.wo)
        self._make_task('Done task', status=Task.STATUS_COMPLETE,
                        assignee=self.user, worker_queue=3, work_order=self.wo)
        self._make_task('Cancelled task', status=Task.STATUS_CANCELLED,
                        assignee=self.user, worker_queue=4, work_order=self.wo)

        response = self.client.get('/api/home/')
        names = [t['name'] for t in response.json()['assigned_tasks']]
        self.assertIn('Pending task', names)
        self.assertIn('Blocked task', names)
        self.assertNotIn('Done task', names)
        self.assertNotIn('Cancelled task', names)

    def test_assigned_tasks_excludes_other_users(self):
        self._make_task('Mine', assignee=self.user, worker_queue=1,
                        work_order=self.wo)
        self._make_task('Theirs', assignee=self.other, worker_queue=1,
                        work_order=self.wo)

        response = self.client.get('/api/home/')
        names = [t['name'] for t in response.json()['assigned_tasks']]
        self.assertEqual(names, ['Mine'])

    def test_assigned_tasks_ordered_by_worker_queue(self):
        self._make_task('Third', assignee=self.user, worker_queue=3,
                        work_order=self.wo)
        self._make_task('First', assignee=self.user, worker_queue=1,
                        work_order=self.wo)
        self._make_task('Second', assignee=self.user, worker_queue=2,
                        work_order=self.wo)

        response = self.client.get('/api/home/')
        names = [t['name'] for t in response.json()['assigned_tasks']]
        self.assertEqual(names, ['First', 'Second', 'Third'])

    def test_assigned_tasks_include_job_info(self):
        self._make_task('T', assignee=self.user, worker_queue=1,
                        work_order=self.wo)
        response = self.client.get('/api/home/')
        task_data = response.json()['assigned_tasks'][0]
        self.assertEqual(task_data['status'], Task.STATUS_PENDING)
        self.assertIn('job', task_data)
        self.assertEqual(task_data['job']['id'], self.job.pk)
        self.assertEqual(task_data['job']['job_number'], 'JOB-HOME-A')
        self.assertEqual(task_data['job']['name'], 'Alpha Job')
        self.assertIn('work_order', task_data)
        self.assertEqual(task_data['work_order']['id'], self.wo.pk)

    def test_recent_jobs_from_user_bleps(self):
        task = self._make_task('T', assignee=self.user, worker_queue=1,
                               work_order=self.wo)
        now = timezone.now()
        Blep.objects.create(user=self.user, task=task,
                            start_time=now - timedelta(hours=1),
                            end_time=now - timedelta(minutes=30))

        response = self.client.get('/api/home/')
        jobs = response.json()['recent_jobs']
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['id'], self.job.pk)
        self.assertEqual(jobs[0]['job_number'], 'JOB-HOME-A')
        self.assertIn('last_worked_at', jobs[0])

    def test_recent_jobs_excludes_other_users(self):
        task = self._make_task('T', work_order=self.wo)
        Blep.objects.create(user=self.other, task=task,
                            start_time=timezone.now())
        response = self.client.get('/api/home/')
        self.assertEqual(response.json()['recent_jobs'], [])

    def test_recent_jobs_distinct_and_ordered(self):
        job_b = Job.objects.create(
            job_number='JOB-HOME-B', name='Bravo', status='approved',
            contact=self.contact,
        )
        wo_b = WorkOrder.objects.create(job=job_b)
        task_a = self._make_task('A', work_order=self.wo)
        task_b = self._make_task('B', work_order=wo_b)

        now = timezone.now()
        # Older blep on job A
        Blep.objects.create(user=self.user, task=task_a,
                            start_time=now - timedelta(hours=5))
        # Two bleps on job B, one newer than job A's
        Blep.objects.create(user=self.user, task=task_b,
                            start_time=now - timedelta(hours=4))
        Blep.objects.create(user=self.user, task=task_b,
                            start_time=now - timedelta(minutes=10))

        response = self.client.get('/api/home/')
        jobs = response.json()['recent_jobs']
        self.assertEqual(len(jobs), 2)  # distinct
        self.assertEqual(jobs[0]['job_number'], 'JOB-HOME-B')  # most recent first
        self.assertEqual(jobs[1]['job_number'], 'JOB-HOME-A')

    def test_recent_jobs_limited_to_10(self):
        now = timezone.now()
        for i in range(12):
            j = Job.objects.create(
                job_number=f'JOB-LIM-{i:02d}', name=f'Job {i}',
                status='approved', contact=self.contact,
            )
            wo = WorkOrder.objects.create(job=j)
            t = self._make_task(f'T{i}', work_order=wo)
            Blep.objects.create(user=self.user, task=t,
                                start_time=now - timedelta(hours=i))
        response = self.client.get('/api/home/')
        self.assertEqual(len(response.json()['recent_jobs']), 10)
