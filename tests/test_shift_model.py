from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift


class ShiftModelTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='shift_model_u', password='x')

    def test_open_shift_has_null_end(self):
        s = Shift.objects.create(user=self.user, start_time=timezone.now())
        self.assertIsNone(s.end_time)
        self.assertTrue(Shift.objects.filter(user=self.user, end_time__isnull=True).exists())

    def test_str_and_table(self):
        s = Shift.objects.create(user=self.user, start_time=timezone.now())
        self.assertIn(self.user.username, str(s))
        self.assertEqual(Shift._meta.db_table, 'shifts')
