from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job, WorkOrder, Task, Blep


class BlepListAndRetrieveTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='T', work_order=self.wo)
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
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task_a = Task.objects.create(name='A', work_order=self.wo)
        self.task_b = Task.objects.create(name='B', work_order=self.wo)
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
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='T', work_order=self.wo)

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
