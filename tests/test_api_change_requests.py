from django.contrib.auth.models import Permission
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, Shift, ShiftChangeRequest


class ChangeRequestAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.worker = User.objects.create_user(username='cr_api_w', password='x')
        self.mgr = User.objects.create_user(username='cr_api_m', password='x')
        self.mgr.user_permissions.add(Permission.objects.get(
            codename='can_manage_time', content_type__app_label='core'))
        self.mgr = User.objects.get(pk=self.mgr.pk)
        self.now = timezone.now().replace(microsecond=0)

    def test_worker_files_shift_request(self):
        self.client.force_authenticate(user=self.worker)
        r = self.client.post('/api/shift-change-requests/', {
            'requested_start': (self.now - timedelta(hours=40)).isoformat(),
            'requested_end': (self.now - timedelta(hours=32)).isoformat(),
            'reason': 'forgot to clock in',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['status'], 'pending')

    def test_reason_required(self):
        self.client.force_authenticate(user=self.worker)
        r = self.client.post('/api/shift-change-requests/', {
            'requested_start': self.now.isoformat(),
            'requested_end': self.now.isoformat(), 'reason': '',
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_manager_approves(self):
        req = ShiftChangeRequest.objects.create(
            requester=self.worker,
            requested_start=self.now - timedelta(hours=40),
            requested_end=self.now - timedelta(hours=32), reason='x')
        self.client.force_authenticate(user=self.mgr)
        r = self.client.post(f'/api/shift-change-requests/{req.pk}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')

    def test_worker_cannot_approve(self):
        req = ShiftChangeRequest.objects.create(
            requester=self.worker, requested_start=self.now, requested_end=self.now, reason='x')
        self.client.force_authenticate(user=self.worker)
        r = self.client.post(f'/api/shift-change-requests/{req.pk}/approve/', {}, format='json')
        self.assertIn(r.status_code, (403, 401))
