from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import WorkOrder, Job


class WorkOrderAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_work_orders(self):
        response = self.client.get('/api/work-orders/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_work_order(self):
        wo = WorkOrder.objects.first()
        if wo:
            response = self.client.get(f'/api/work-orders/{wo.pk}/')
            self.assertEqual(response.status_code, 200)

    def test_create_work_order(self):
        job = Job.objects.first()
        response = self.client.post('/api/work-orders/', {
            'job': job.pk,
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_complete_work_order(self):
        wo = WorkOrder.objects.filter(status='incomplete').first()
        if wo:
            response = self.client.post(f'/api/work-orders/{wo.pk}/complete/')
            self.assertEqual(response.status_code, 200)

    def test_block_requires_reason(self):
        wo = WorkOrder.objects.first()
        if wo:
            response = self.client.post(f'/api/work-orders/{wo.pk}/block/', {}, format='json')
            self.assertEqual(response.status_code, 400)

    def test_list_tasks(self):
        wo = WorkOrder.objects.first()
        if wo:
            response = self.client.get(f'/api/work-orders/{wo.pk}/tasks/')
            self.assertEqual(response.status_code, 200)
