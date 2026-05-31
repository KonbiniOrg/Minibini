from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift


class ShiftModelTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='shift_model_u', password='x')

    def test_is_open_when_end_time_is_null(self):
        s = Shift.objects.create(user=self.user, start_time=timezone.now())
        self.assertIsNone(s.end_time)
        self.assertTrue(s.is_open)

    def test_is_closed_when_end_time_set(self):
        s = Shift.objects.create(
            user=self.user,
            start_time=timezone.now() - timedelta(hours=8),
            end_time=timezone.now(),
        )
        self.assertFalse(s.is_open)

    def test_str_and_table(self):
        s = Shift.objects.create(user=self.user, start_time=timezone.now())
        self.assertIn(self.user.username, str(s))
        self.assertEqual(Shift._meta.db_table, 'shifts')
