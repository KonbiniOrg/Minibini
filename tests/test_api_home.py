from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from tests.base import FixtureTestCase
from apps.jobs.models import Blep, Job, Task
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
        self.task = Task.objects.create(
            name='Task A', job=self.job, assignee=self.user,
            est_worker_time=timedelta(hours=1),
            status=Task.STATUS_IN_PROGRESS, rate_scheme_id=1,
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
        self.assertNotIn('work_order', data)

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
            name='Task B', job=self.job, assignee=self.user,
            est_worker_time=timedelta(hours=1),
            status=Task.STATUS_IN_PROGRESS, rate_scheme_id=1,
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

    def _make_task(self, name, status=Task.STATUS_PENDING, assignee=None,
                   worker_queue=None, job=None):
        kwargs = {'name': name, 'status': status, 'job': job or self.job, 'rate_scheme_id': 1}
        if assignee is not None:
            kwargs['assignee'] = assignee
            kwargs['est_worker_time'] = timedelta(hours=1)
        if worker_queue is not None:
            kwargs['worker_queue'] = worker_queue
        return Task.objects.create(**kwargs)

    def test_home_requires_authentication(self):
        self.client.logout()
        response = self.client.get('/api/home/')
        self.assertEqual(response.status_code, 403)

    def _blep(self, task, user, start, end=None):
        return Blep.objects.create(user=user, task=task,
                                   start_time=start, end_time=end)

    def test_home_returns_shape(self):
        response = self.client.get('/api/home/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('current_tasks', data)
        self.assertIn('recent_tasks', data)
        self.assertIn('recent_days', data)
        # Retired keys must be gone.
        self.assertNotIn('assigned_tasks', data)
        self.assertNotIn('recent_jobs', data)

    def test_recent_days_reads_activity_recent_days(self):
        """The home lists' look-back window comes from activity_recent_days
        (same key as the Activity page; default 5 when unset)."""
        Configuration.objects.filter(key='activity_recent_days').delete()
        response = self.client.get('/api/home/')
        self.assertEqual(response.json()['recent_days'], 5)

        Configuration.objects.update_or_create(
            key='activity_recent_days', defaults={'value': '3'},
        )
        response = self.client.get('/api/home/')
        self.assertEqual(response.json()['recent_days'], 3)

    # --- current_tasks -----------------------------------------------------

    def test_current_tasks_includes_my_assigned(self):
        self._make_task('Mine', assignee=self.user, worker_queue=1)
        data = self.client.get('/api/home/').json()['current_tasks']
        by_name = {t['name']: t for t in data}
        self.assertIn('Mine', by_name)
        self.assertTrue(by_name['Mine']['assigned_to_me'])

    def test_current_tasks_excludes_completed_and_cancelled(self):
        self._make_task('Pending task', status=Task.STATUS_PENDING,
                        assignee=self.user, worker_queue=1)
        self._make_task('Blocked task', status=Task.STATUS_BLOCKED,
                        assignee=self.user, worker_queue=2)
        self._make_task('Done task', status=Task.STATUS_COMPLETE,
                        assignee=self.user, worker_queue=3)
        self._make_task('Cancelled task', status=Task.STATUS_CANCELLED,
                        assignee=self.user, worker_queue=4)

        names = [t['name'] for t in self.client.get('/api/home/').json()['current_tasks']]
        self.assertIn('Pending task', names)
        self.assertIn('Blocked task', names)
        self.assertNotIn('Done task', names)
        self.assertNotIn('Cancelled task', names)

    def test_current_tasks_excludes_unrelated_other_user_tasks(self):
        """A task assigned to someone else that I have never worked stays out."""
        self._make_task('Mine', assignee=self.user, worker_queue=1)
        self._make_task('Theirs', assignee=self.other, worker_queue=1)

        names = [t['name'] for t in self.client.get('/api/home/').json()['current_tasks']]
        self.assertEqual(names, ['Mine'])

    def test_current_tasks_mine_ordered_by_worker_queue(self):
        self._make_task('Third', assignee=self.user, worker_queue=3)
        self._make_task('First', assignee=self.user, worker_queue=1)
        self._make_task('Second', assignee=self.user, worker_queue=2)

        names = [t['name'] for t in self.client.get('/api/home/').json()['current_tasks']]
        self.assertEqual(names, ['First', 'Second', 'Third'])

    def test_current_tasks_include_job_info_and_flag(self):
        self._make_task('T', assignee=self.user, worker_queue=1)
        task_data = self.client.get('/api/home/').json()['current_tasks'][0]
        self.assertEqual(task_data['status'], Task.STATUS_PENDING)
        self.assertTrue(task_data['assigned_to_me'])
        self.assertEqual(task_data['job']['id'], self.job.pk)
        self.assertEqual(task_data['job']['job_number'], 'JOB-HOME-A')
        self.assertEqual(task_data['job']['name'], 'Alpha Job')
        self.assertNotIn('work_order', task_data)

    def test_current_tasks_includes_others_task_with_my_open_blep_at_bottom(self):
        """A task assigned to another worker that I have an OPEN blep on shows
        up flagged not-mine and sorted after my own tasks."""
        self._make_task('Mine', assignee=self.user, worker_queue=1)
        theirs = self._make_task('Theirs', assignee=self.other, worker_queue=1)
        self._blep(theirs, self.user, timezone.now())  # open (no end)

        data = self.client.get('/api/home/').json()['current_tasks']
        names = [t['name'] for t in data]
        self.assertEqual(names, ['Mine', 'Theirs'])  # others last
        by_name = {t['name']: t for t in data}
        self.assertFalse(by_name['Theirs']['assigned_to_me'])

    def test_current_tasks_includes_others_task_with_recent_blep_windowed(self):
        """A recent (but closed) blep on someone else's task pulls it in only
        while it is inside the look-back window."""
        theirs = self._make_task('Theirs', assignee=self.other, worker_queue=1)
        now = timezone.now()
        self._blep(theirs, self.user,
                   now - timedelta(days=10), now - timedelta(days=10) + timedelta(hours=1))

        Configuration.objects.filter(key='activity_recent_days').delete()
        names = [t['name'] for t in self.client.get('/api/home/').json()['current_tasks']]
        self.assertNotIn('Theirs', names)  # default 5-day window

        Configuration.objects.update_or_create(
            key='activity_recent_days', defaults={'value': '30'})
        names = [t['name'] for t in self.client.get('/api/home/').json()['current_tasks']]
        self.assertIn('Theirs', names)

    # --- recent_tasks (completed) -----------------------------------------

    def test_recent_tasks_completed_with_my_blep(self):
        done = self._make_task('Done', status=Task.STATUS_COMPLETE, assignee=self.user)
        now = timezone.now()
        self._blep(done, self.user, now - timedelta(hours=1), now - timedelta(minutes=30))

        data = self.client.get('/api/home/').json()['recent_tasks']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['name'], 'Done')
        self.assertEqual(data[0]['status'], Task.STATUS_COMPLETE)
        self.assertIsNotNone(data[0]['last_worked_at'])

    def test_recent_tasks_excludes_incomplete(self):
        """A task I worked recently but have NOT completed belongs in
        current_tasks, not recent_tasks."""
        t = self._make_task('WIP', status=Task.STATUS_IN_PROGRESS, assignee=self.user)
        self._blep(t, self.user, timezone.now() - timedelta(hours=1))
        names = [x['name'] for x in self.client.get('/api/home/').json()['recent_tasks']]
        self.assertEqual(names, [])

    def test_recent_tasks_excludes_other_users(self):
        done = self._make_task('Done', status=Task.STATUS_COMPLETE)
        self._blep(done, self.other, timezone.now() - timedelta(hours=1))
        self.assertEqual(self.client.get('/api/home/').json()['recent_tasks'], [])

    def test_recent_tasks_ordered_by_last_worked_desc(self):
        older = self._make_task('Older', status=Task.STATUS_COMPLETE, assignee=self.user)
        newer = self._make_task('Newer', status=Task.STATUS_COMPLETE, assignee=self.user)
        now = timezone.now()
        self._blep(older, self.user, now - timedelta(hours=5), now - timedelta(hours=4))
        self._blep(newer, self.user, now - timedelta(hours=2), now - timedelta(hours=1))
        names = [t['name'] for t in self.client.get('/api/home/').json()['recent_tasks']]
        self.assertEqual(names, ['Newer', 'Older'])

    def test_recent_tasks_windowed(self):
        done = self._make_task('Done', status=Task.STATUS_COMPLETE, assignee=self.user)
        self._blep(done, self.user,
                   timezone.now() - timedelta(days=10),
                   timezone.now() - timedelta(days=10) + timedelta(hours=1))

        Configuration.objects.filter(key='activity_recent_days').delete()
        self.assertEqual(self.client.get('/api/home/').json()['recent_tasks'], [])

        Configuration.objects.update_or_create(
            key='activity_recent_days', defaults={'value': '30'})
        names = [t['name'] for t in self.client.get('/api/home/').json()['recent_tasks']]
        self.assertEqual(names, ['Done'])

    def test_recent_tasks_limited_to_10(self):
        now = timezone.now()
        for i in range(12):
            t = self._make_task(f'Done {i:02d}', status=Task.STATUS_COMPLETE,
                                 assignee=self.user)
            self._blep(t, self.user, now - timedelta(hours=i + 1),
                       now - timedelta(hours=i))
        self.assertEqual(len(self.client.get('/api/home/').json()['recent_tasks']), 10)

    def test_recent_logins_scoped_windowed_ordered(self):
        """recent_logins: own events only, inside activity_recent_days,
        newest first. (setUp's client.login records one live event.)"""
        from apps.core.models import LoginEvent
        now = timezone.now()
        old = LoginEvent.objects.create(user=self.user)
        LoginEvent.objects.filter(pk=old.pk).update(
            timestamp=now - timedelta(days=10))
        LoginEvent.objects.create(user=self.other)  # not ours

        response = self.client.get('/api/home/')
        data = response.json()
        logins = data['recent_logins']
        # Only the live setUp login survives: the 10-day-old event is outside
        # the default 5-day window, the other user's event is not ours.
        self.assertEqual(len(logins), 1)
        self.assertIn('timestamp', logins[0])
        self.assertIn('ip_address', logins[0])

        Configuration.objects.update_or_create(
            key='activity_recent_days', defaults={'value': '30'},
        )
        logins = self.client.get('/api/home/').json()['recent_logins']
        self.assertEqual(len(logins), 2)
        stamps = [l['timestamp'] for l in logins]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
