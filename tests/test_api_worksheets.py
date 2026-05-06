from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.estimates.models import EstWorksheet
from apps.jobs.models import Job


class WorksheetAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_worksheets(self):
        response = self.client.get('/api/est-worksheets/')
        self.assertEqual(response.status_code, 200)

    def test_create_worksheet(self):
        job = Job.objects.first()
        response = self.client.post('/api/est-worksheets/', {
            'job': job.pk,
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_retrieve_worksheet(self):
        ws = EstWorksheet.objects.first()
        if ws:
            response = self.client.get(f'/api/est-worksheets/{ws.pk}/')
            self.assertEqual(response.status_code, 200)

    def test_list_tasks(self):
        ws = EstWorksheet.objects.first()
        if ws:
            response = self.client.get(f'/api/est-worksheets/{ws.pk}/tasks/')
            self.assertEqual(response.status_code, 200)

    def test_revise_worksheet(self):
        ws = EstWorksheet.objects.filter(status=EstWorksheet.STATUS_FINAL).first()
        if ws:
            response = self.client.post(f'/api/est-worksheets/{ws.pk}/revise/')
            self.assertEqual(response.status_code, 200)

    def test_delete_worksheet_without_estimate(self):
        job = Job.objects.first()
        ws = EstWorksheet.objects.create(job=job)
        response = self.client.delete(f'/api/est-worksheets/{ws.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('message', response.json())
        self.assertFalse(EstWorksheet.objects.filter(pk=ws.pk).exists())

    def test_delete_worksheet_refused_when_estimate_linked(self):
        from apps.estimates.services import EstimateWizardService
        job = Job.objects.first()
        ws = EstWorksheet.objects.create(job=job)
        EstimateWizardService.open_for_worksheet(ws)
        ws.refresh_from_db()
        self.assertIsNotNone(ws.estimate_id)
        response = self.client.delete(f'/api/est-worksheets/{ws.pk}/')
        self.assertEqual(response.status_code, 400)
        self.assertIn('detail', response.json())
        self.assertTrue(EstWorksheet.objects.filter(pk=ws.pk).exists())
