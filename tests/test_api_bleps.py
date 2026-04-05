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
