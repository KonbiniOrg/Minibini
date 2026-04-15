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

    def test_generate_estimate(self):
        ws = EstWorksheet.objects.filter(status=EstWorksheet.STATUS_DRAFT).first()
        if ws:
            response = self.client.post(f'/api/est-worksheets/{ws.pk}/generate-estimate/')
            self.assertIn(response.status_code, [200, 400])

    def test_generate_estimate_finalizes_worksheet(self):
        """Generating an estimate via API should finalize the worksheet."""
        from apps.core.models import AccountingCategory
        from apps.jobs.models import PlanTask
        from decimal import Decimal

        job = Job.objects.first()
        ws = EstWorksheet.objects.create(job=job, status=EstWorksheet.STATUS_DRAFT, version=1)
        category, _ = AccountingCategory.objects.get_or_create(
            code='LBR', defaults={'name': 'Labor'}
        )
        PlanTask.objects.create(
            est_worksheet=ws, name='Test Task', units='hours',
            rate=Decimal('50.00'), est_qty=Decimal('2.0'),
            accounting_category=category,
        )

        response = self.client.post(f'/api/est-worksheets/{ws.pk}/generate-estimate/')
        self.assertEqual(response.status_code, 200)

        ws.refresh_from_db()
        self.assertEqual(ws.status, EstWorksheet.STATUS_FINAL)

    def test_revise_worksheet(self):
        ws = EstWorksheet.objects.filter(status=EstWorksheet.STATUS_FINAL).first()
        if ws:
            response = self.client.post(f'/api/est-worksheets/{ws.pk}/revise/')
            self.assertEqual(response.status_code, 200)
