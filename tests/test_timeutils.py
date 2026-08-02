from datetime import timedelta
from decimal import Decimal
from django.test import SimpleTestCase
from apps.core.timeutils import timedelta_to_hours


class TimedeltaToHoursTest(SimpleTestCase):
    def test_converts_and_is_none_safe(self):
        self.assertIsNone(timedelta_to_hours(None))
        self.assertEqual(timedelta_to_hours(timedelta(hours=1, minutes=30)),
                         Decimal('1.5'))
        self.assertEqual(
            timedelta_to_hours(timedelta(minutes=50)).quantize(Decimal('0.01')),
            Decimal('0.83'))
