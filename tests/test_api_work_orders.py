from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, HistoryEntry
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

    def test_complete_work_order_requires_reason(self):
        wo = WorkOrder.objects.filter(status='incomplete').first()
        if wo:
            response = self.client.post(f'/api/work-orders/{wo.pk}/complete/', {}, format='json')
            self.assertEqual(response.status_code, 400)
            self.assertIn('reason', response.data)

    def test_complete_work_order_with_reason(self):
        wo = WorkOrder.objects.filter(status='incomplete').first()
        if wo:
            response = self.client.post(f'/api/work-orders/{wo.pk}/complete/', {
                'reason': 'All tasks finished',
            }, format='json')
            self.assertEqual(response.status_code, 200)
            wo.refresh_from_db()
            self.assertEqual(wo.status, 'complete')

    def test_complete_creates_history(self):
        wo = WorkOrder.objects.filter(status='incomplete').first()
        if wo:
            self.client.post(f'/api/work-orders/{wo.pk}/complete/', {
                'reason': 'All work done',
            }, format='json')
            entry = HistoryEntry.objects.filter(
                entry_type='audit', object_type='workorder', object_id=wo.pk,
            ).first()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.text, 'All work done')
            self.assertEqual(entry.user, self.user)

    def test_block_requires_reason(self):
        wo = WorkOrder.objects.first()
        if wo:
            response = self.client.post(f'/api/work-orders/{wo.pk}/block/', {}, format='json')
            self.assertEqual(response.status_code, 400)

    def test_block_creates_history(self):
        wo = WorkOrder.objects.filter(status='incomplete').first()
        if wo:
            self.client.post(f'/api/work-orders/{wo.pk}/block/', {
                'reason': 'Waiting on parts',
            }, format='json')
            entry = HistoryEntry.objects.filter(
                entry_type='audit', object_type='workorder', object_id=wo.pk,
            ).first()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.text, 'Waiting on parts')

    def test_reopen_creates_history(self):
        wo = WorkOrder.objects.filter(status='incomplete').first()
        if wo:
            # Block it first
            self.client.post(f'/api/work-orders/{wo.pk}/block/', {
                'reason': 'temp',
            }, format='json')
            # Reopen
            self.client.post(f'/api/work-orders/{wo.pk}/reopen/', {
                'reason': 'Parts arrived',
            }, format='json')
            entry = HistoryEntry.objects.filter(
                entry_type='audit', object_type='workorder', object_id=wo.pk,
                text='Parts arrived',
            ).first()
            self.assertIsNotNone(entry)

    def test_list_tasks(self):
        wo = WorkOrder.objects.first()
        if wo:
            response = self.client.get(f'/api/work-orders/{wo.pk}/tasks/')
            self.assertEqual(response.status_code, 200)
