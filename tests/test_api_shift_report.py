from django.contrib.auth.models import Permission
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, Shift


class ShiftReportAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.worker = User.objects.create_user(username='rep_w', password='x')
        self.fin = User.objects.create_user(username='rep_fin', password='x')
        self.fin.user_permissions.add(Permission.objects.get(
            codename='can_manage_financials', content_type__app_label='core'))
        self.fin = User.objects.get(pk=self.fin.pk)
        self.now = timezone.now().replace(microsecond=0)
        Shift.objects.create(user=self.worker, start_time=self.now - timedelta(hours=8),
                             end_time=self.now - timedelta(hours=1))

    def test_financials_user_can_read_report(self):
        self.client.force_authenticate(user=self.fin)
        start = (self.now - timedelta(days=1)).date().isoformat()
        end = self.now.date().isoformat()
        r = self.client.get(f'/api/shifts/report/?start={start}&end={end}')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn('workers', r.data)

    def test_plain_user_denied(self):
        self.client.force_authenticate(user=self.worker)
        r = self.client.get('/api/shifts/report/?start=2026-05-01&end=2026-05-31')
        self.assertEqual(r.status_code, 403)
