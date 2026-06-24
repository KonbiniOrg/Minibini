"""Per-item priced flat fees with quantity.

flat_fee billing means "fixed unit price x estimated quantity". The unit
price lives on ServicePrice.rate. See docs/designs/estimates-and-prices.md.
"""
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import ServicePrice
from apps.core.models import AccountingCategory


class FlatFeePricingTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Svc', code='SVC')

    def test_flat_fee_effective_rate_is_rate(self):
        svc = ServicePrice.objects.create(
            name='Tap a hole', algorithm=ServicePrice.FLAT_FEE,
            rate=Decimal('1.00'), unit_label='hole', accounting_category=self.ac,
        )
        # active_modifiers is ignored for flat_fee; price comes from rate.
        self.assertEqual(svc.effective_rate([]), Decimal('1.00'))
        self.assertEqual(svc.effective_rate(['anything']), Decimal('1.00'))

    def test_flat_fee_compute_charge(self):
        svc = ServicePrice.objects.create(
            name='Coat plywood', algorithm=ServicePrice.FLAT_FEE,
            rate=Decimal('30.00'), unit_label='sheet', accounting_category=self.ac,
        )
        self.assertEqual(svc.compute_charge(Decimal('3'), []), Decimal('90.00'))
