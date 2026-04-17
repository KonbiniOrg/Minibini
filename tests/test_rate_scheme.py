from decimal import Decimal
from unittest.mock import MagicMock, patch
from tests.base import BaseTestCase
from apps.jobs.models import RateScheme


class RateSchemeModelTest(BaseTestCase):
    """Test creation of RateScheme instances for all 3 algorithm types."""

    def test_create_elapsed_time_scheme(self):
        scheme = RateScheme.objects.create(
            name='Standard Labor',
            description='Billed per hour worked',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('75.00'),
            unit_label='hour',
        )
        self.assertEqual(scheme.name, 'Standard Labor')
        self.assertEqual(scheme.algorithm, RateScheme.ELAPSED_TIME)
        self.assertEqual(scheme.rate, Decimal('75.00'))
        self.assertEqual(scheme.unit_label, 'hour')
        self.assertIsNone(scheme.minimum_charge)
        self.assertEqual(scheme.modifiers, [])

    def test_create_entered_qty_scheme_with_modifiers(self):
        modifiers = [
            {'key': 'messy', 'label': 'Messy job', 'percent': 10},
            {'key': 'doublestick', 'label': 'Double-stick tape', 'percent': 5},
        ]
        scheme = RateScheme.objects.create(
            name='Vinyl Application',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='sq ft',
            minimum_charge=Decimal('20.00'),
            modifiers=modifiers,
        )
        self.assertEqual(scheme.algorithm, RateScheme.ENTERED_QTY)
        self.assertEqual(len(scheme.modifiers), 2)
        self.assertEqual(scheme.modifiers[0]['key'], 'messy')
        self.assertEqual(scheme.minimum_charge, Decimal('20.00'))

    def test_create_flat_fee_scheme(self):
        scheme = RateScheme.objects.create(
            name='Setup Fee',
            algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('50.00'),
            unit_label='job',
        )
        self.assertEqual(scheme.algorithm, RateScheme.FLAT_FEE)
        self.assertEqual(str(scheme), 'Setup Fee')

    def test_name_unique(self):
        RateScheme.objects.create(
            name='Unique Scheme',
            algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('10.00'),
            unit_label='job',
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            RateScheme.objects.create(
                name='Unique Scheme',
                algorithm=RateScheme.FLAT_FEE,
                rate=Decimal('10.00'),
                unit_label='job',
            )


class RateSchemeComputeTest(BaseTestCase):
    """Test compute methods on RateScheme."""

    def setUp(self):
        super().setUp()
        self.modifiers = [
            {'key': 'messy', 'label': 'Messy job', 'percent': 10},
            {'key': 'doublestick', 'label': 'Double-stick tape', 'percent': 5},
        ]
        self.scheme = RateScheme.objects.create(
            name='Vinyl Application',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='sq ft',
            minimum_charge=Decimal('20.00'),
            modifiers=self.modifiers,
        )
        self.flat_scheme = RateScheme.objects.create(
            name='Setup Fee',
            algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('50.00'),
            unit_label='job',
        )

    def test_effective_rate_no_modifiers(self):
        result = self.scheme.effective_rate()
        self.assertEqual(result, Decimal('4.00'))

    def test_effective_rate_one_modifier(self):
        # $4.00 + 10% = $4.40
        result = self.scheme.effective_rate(active_modifiers=['messy'])
        self.assertEqual(result, Decimal('4.40'))

    def test_effective_rate_stacking_modifiers(self):
        # $4.00 + 10% + 5% = $4.00 * 1.15 = $4.60
        result = self.scheme.effective_rate(active_modifiers=['messy', 'doublestick'])
        self.assertEqual(result, Decimal('4.60'))

    def test_compute_charge_basic(self):
        # 30 sq ft × $4.00 = $120.00 (above minimum of $20)
        result = self.scheme.compute_charge(Decimal('30'))
        self.assertEqual(result, Decimal('120.00'))

    def test_compute_charge_with_modifiers(self):
        # 30 × $4.60 = $138.00
        result = self.scheme.compute_charge(Decimal('30'), active_modifiers=['messy', 'doublestick'])
        self.assertEqual(result, Decimal('138.00'))

    def test_compute_charge_minimum_applies(self):
        # 1 × $4.00 = $4.00, but minimum is $20.00
        result = self.scheme.compute_charge(Decimal('1'))
        self.assertEqual(result, Decimal('20.00'))

    def test_compute_charge_minimum_not_applied_when_exceeded(self):
        # 10 × $4.00 = $40.00, minimum is $20.00 → $40.00
        result = self.scheme.compute_charge(Decimal('10'))
        self.assertEqual(result, Decimal('40.00'))

    def test_flat_fee_effective_rate(self):
        result = self.flat_scheme.effective_rate()
        self.assertEqual(result, Decimal('50.00'))

    def test_flat_fee_compute_charge(self):
        result = self.flat_scheme.compute_charge(Decimal('1'))
        self.assertEqual(result, Decimal('50.00'))

    def test_get_actual_qty_elapsed_time(self):
        from datetime import datetime, timedelta
        from django.utils import timezone as tz

        labor_scheme = RateScheme.objects.create(
            name='Labor Rate',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('75.00'),
            unit_label='hour',
        )

        # Mock a task with bleps totaling 2 hours (7200 seconds)
        blep1 = MagicMock()
        blep1.elapsed = timedelta(seconds=3600)  # 1 hour
        blep2 = MagicMock()
        blep2.elapsed = timedelta(seconds=3600)  # 1 hour

        task = MagicMock()
        task.blep_set.all.return_value = [blep1, blep2]

        result = labor_scheme.get_actual_qty(task)
        self.assertEqual(result, Decimal('2'))

    def test_get_actual_qty_entered_qty(self):
        charge = MagicMock()
        charge.actuals = {'qty': 25}
        task = MagicMock()
        task.charge = charge

        result = self.scheme.get_actual_qty(task)
        self.assertEqual(result, 25)

    def test_get_actual_qty_flat_fee(self):
        task = MagicMock()
        result = self.flat_scheme.get_actual_qty(task)
        self.assertEqual(result, Decimal('1'))

    def test_get_modifier_inputs(self):
        result = self.scheme.get_modifier_inputs()
        self.assertEqual(result, self.modifiers)
        # Should be a copy (list), not the same object reference check not required
        self.assertIsInstance(result, list)
