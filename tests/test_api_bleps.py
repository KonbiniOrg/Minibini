from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job, Task, Blep


class BlepListAndRetrieveTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job)
        self.blep = Blep.objects.create(
            task=self.task, user=self.user, start_time=timezone.now(),
        )

    def test_list_bleps(self):
        resp = self.client.get('/api/bleps/')
        self.assertEqual(resp.status_code, 200)
        ids = [b['blep_id'] for b in resp.data['results']]
        self.assertIn(self.blep.blep_id, ids)

    def test_retrieve_blep(self):
        resp = self.client.get(f'/api/bleps/{self.blep.blep_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['blep_id'], self.blep.blep_id)
        self.assertEqual(resp.data['task'], self.task.pk)

    def test_retrieve_blep_includes_job_info(self):
        """Serializer exposes job_id, job_number, job_name via task.job."""
        resp = self.client.get(f'/api/bleps/{self.blep.blep_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['job_id'], self.job.pk)
        self.assertEqual(resp.data['job_number'], self.job.job_number)
        self.assertEqual(resp.data['job_name'], self.job.name)

    def test_list_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get('/api/bleps/')
        self.assertIn(resp.status_code, [401, 403])


class BlepListFiltersTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.admin = User.objects.get(username='admin')
        self.worker = User.objects.create_user(username='worker', password='x')
        self.client.force_authenticate(user=self.admin)
        self.job = Job.objects.first()
        self.task_a = Task.objects.create(name='A', job=self.job)
        self.task_b = Task.objects.create(name='B', job=self.job)
        now = timezone.now()
        self.old = Blep.objects.create(
            task=self.task_a, user=self.admin,
            start_time=now - timedelta(days=10), end_time=now - timedelta(days=10, hours=-1),
        )
        self.recent_admin = Blep.objects.create(
            task=self.task_a, user=self.admin, start_time=now - timedelta(hours=2),
        )
        self.recent_worker = Blep.objects.create(
            task=self.task_b, user=self.worker, start_time=now - timedelta(hours=1),
        )

    def _ids(self, resp):
        return {b['blep_id'] for b in resp.data['results']}

    def test_filter_user_me(self):
        resp = self.client.get('/api/bleps/?user=me')
        self.assertEqual(resp.status_code, 200)
        ids = self._ids(resp)
        self.assertEqual(ids, {self.old.blep_id, self.recent_admin.blep_id})

    def test_filter_user_by_id(self):
        resp = self.client.get(f'/api/bleps/?user={self.worker.pk}')
        self.assertEqual(self._ids(resp), {self.recent_worker.blep_id})

    def test_filter_task(self):
        resp = self.client.get(f'/api/bleps/?task={self.task_b.pk}')
        self.assertEqual(self._ids(resp), {self.recent_worker.blep_id})

    def test_filter_since(self):
        cutoff = (timezone.now() - timedelta(days=1)).isoformat()
        resp = self.client.get('/api/bleps/', {'since': cutoff})
        self.assertEqual(
            self._ids(resp),
            {self.recent_admin.blep_id, self.recent_worker.blep_id},
        )

    def test_filters_combine(self):
        cutoff = (timezone.now() - timedelta(days=1)).isoformat()
        resp = self.client.get('/api/bleps/', {'user': 'me', 'since': cutoff})
        self.assertEqual(self._ids(resp), {self.recent_admin.blep_id})


class BlepCreateAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.create_user(username='worker1_create', password='x')
        self.other = User.objects.create_user(username='worker2', password='x')
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job)

    def _payload(self, hours_ago=2, duration_hours=1, user=None, task=None):
        now = timezone.now()
        start = now - timedelta(hours=hours_ago)
        end = start + timedelta(hours=duration_hours)
        data = {
            'task': (task or self.task).pk,
            'start_time': start.isoformat(),
            'end_time': end.isoformat(),
        }
        if user is not None:
            data['user'] = user.pk
        return data

    def test_create_historical_for_self(self):
        resp = self.client.post('/api/bleps/', self._payload(), format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['user'], self.user.pk)

    def test_create_defaults_user_to_self_when_omitted(self):
        payload = self._payload()
        payload.pop('user', None)
        resp = self.client.post('/api/bleps/', payload, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['user'], self.user.pk)

    def test_create_for_other_user_without_manage_time_denied(self):
        resp = self.client.post('/api/bleps/',
                                 self._payload(user=self.other), format='json')
        self.assertEqual(resp.status_code, 403)

    def test_create_older_than_24h_without_manage_time_denied(self):
        resp = self.client.post('/api/bleps/',
                                 self._payload(hours_ago=48, duration_hours=1),
                                 format='json')
        self.assertEqual(resp.status_code, 403)

    def test_create_overlap_returns_400(self):
        first = self.client.post('/api/bleps/', self._payload(hours_ago=3, duration_hours=2),
                                  format='json')
        self.assertEqual(first.status_code, 201)
        resp = self.client.post('/api/bleps/',
                                 self._payload(hours_ago=2, duration_hours=1),
                                 format='json')
        self.assertEqual(resp.status_code, 400)


from django.contrib.auth.models import Permission


class BlepUpdateAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.create_user(username='worker1_update_api', password='x')
        self.manager = User.objects.create_user(username='m', password='x')
        perm = Permission.objects.get(codename='can_manage_time', content_type__app_label='core')
        self.manager.user_permissions.add(perm)
        self.manager = User.objects.get(pk=self.manager.pk)
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job)

    def _blep(self, user, hours_ago_start=2, hours_ago_end=1):
        now = timezone.now()
        return Blep.objects.create(
            task=self.task, user=user,
            start_time=now - timedelta(hours=hours_ago_start),
            end_time=now - timedelta(hours=hours_ago_end),
        )

    def test_patch_own_recent_blep(self):
        blep = self._blep(self.user)
        self.client.force_authenticate(user=self.user)
        new_end = (blep.end_time + timedelta(minutes=10)).isoformat()
        resp = self.client.patch(
            f'/api/bleps/{blep.blep_id}/',
            {'end_time': new_end}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        blep.refresh_from_db()

    def test_patch_old_blep_as_non_manager_denied(self):
        blep = self._blep(self.user, 48, 47)
        self.client.force_authenticate(user=self.user)
        resp = self.client.patch(
            f'/api/bleps/{blep.blep_id}/',
            {'end_time': (blep.end_time + timedelta(minutes=5)).isoformat()},
            format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_patch_old_blep_as_manager(self):
        blep = self._blep(self.user, 48, 47)
        self.client.force_authenticate(user=self.manager)
        resp = self.client.patch(
            f'/api/bleps/{blep.blep_id}/',
            {'end_time': (blep.end_time + timedelta(minutes=5)).isoformat()},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)


class BlepDeleteAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.create_user(username='worker1_delete_api', password='x')
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job)

    def test_delete_own_recent_blep(self):
        now = timezone.now()
        blep = Blep.objects.create(
            task=self.task, user=self.user,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )
        self.client.force_authenticate(user=self.user)
        resp = self.client.delete(f'/api/bleps/{blep.blep_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Blep.objects.filter(pk=blep.blep_id).exists())

    def test_delete_old_blep_non_manager_denied(self):
        now = timezone.now()
        blep = Blep.objects.create(
            task=self.task, user=self.user,
            start_time=now - timedelta(hours=48),
            end_time=now - timedelta(hours=47),
        )
        self.client.force_authenticate(user=self.user)
        resp = self.client.delete(f'/api/bleps/{blep.blep_id}/')
        self.assertEqual(resp.status_code, 403)


class TaskRetrieveAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        self.task = Task.objects.create(
            name='T', description='desc', job=self.job,
            units='hours', rate='10.00', est_qty='1',
        )

    def test_retrieve_task(self):
        resp = self.client.get(f'/api/tasks/{self.task.pk}/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['task_id'], self.task.pk)
        self.assertEqual(resp.data['name'], 'T')
        self.assertIn('job', resp.data)
        self.assertEqual(resp.data['job']['id'], self.job.pk)
