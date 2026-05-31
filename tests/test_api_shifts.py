from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, Shift


class ShiftAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.create_user(username='api_shift_u', password='x')
        self.client.force_authenticate(user=self.user)

    def test_clock_in_then_active_then_clock_out(self):
        r = self.client.post('/api/shifts/clock-in/', {}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        a = self.client.get('/api/shifts/active/')
        self.assertEqual(a.status_code, 200)
        self.assertIsNotNone(a.data['shift'])
        r2 = self.client.post('/api/shifts/clock-out/', {}, format='json')
        self.assertEqual(r2.status_code, 200, r2.data)
        a2 = self.client.get('/api/shifts/active/')
        self.assertIsNone(a2.data['shift'])

    def test_double_clock_in_400(self):
        self.client.post('/api/shifts/clock-in/', {}, format='json')
        r = self.client.post('/api/shifts/clock-in/', {}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_list_own_shifts_with_since(self):
        Shift.objects.create(user=self.user, start_time=timezone.now() - timedelta(hours=2),
                             end_time=timezone.now() - timedelta(hours=1))
        since = (timezone.now() - timedelta(days=1)).isoformat()
        r = self.client.get(f'/api/shifts/?user=me&since={since}')
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.data.get('results', r.data)), 1)

    def test_patch_recent_own_shift(self):
        s = Shift.objects.create(user=self.user, start_time=timezone.now() - timedelta(hours=3),
                                 end_time=timezone.now() - timedelta(hours=1))
        new_start = (timezone.now() - timedelta(hours=4)).isoformat()
        r = self.client.patch(f'/api/shifts/{s.pk}/',
                              {'start_time': new_start,
                               'end_time': s.end_time.isoformat()}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
