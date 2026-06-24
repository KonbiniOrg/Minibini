"""
Tests for compute_adjustment_amount helper in apps.core.adjustments.

Covers:
  (a) Empty target-category set -> sum ALL non-adjustment siblings (15% of 140 = 21.00)
  (b) Target-category set filters to one category (15% of 100 = 15.00)
  (c) Negative percent (discount) -> negative dollar amount (-10% of 140 = -14.00)
  (d) Other adjustment siblings must NOT be included in the subtotal base
"""
from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory
from apps.jobs.models import ServicePrice


class AdjustmentFieldsTest(TestCase):
    def test_estimate_line_can_hold_adjustment_service(self):
        from apps.estimates.models import EstimateLineItem
        # field presence is the assertion; construction covered in later tasks
        self.assertTrue(hasattr(EstimateLineItem, 'adjustment_service'))
        self.assertTrue(hasattr(EstimateLineItem, 'adjustment_target_categories'))

    def test_invoice_line_can_hold_adjustment_service(self):
        from apps.invoicing.models import InvoiceLineItem
        self.assertTrue(hasattr(InvoiceLineItem, 'adjustment_service'))
        self.assertTrue(hasattr(InvoiceLineItem, 'adjustment_target_categories'))


class ComputeAdjustmentAmountTest(TestCase):

    def setUp(self):
        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        from apps.estimates.models import Estimate, EstimateLineItem

        self.labor = AccountingCategory.objects.create(code='LAB-adj', name='Labor-adj', taxable=False)
        self.materials = AccountingCategory.objects.create(code='MAT-adj', name='Materials-adj', taxable=False)

        contact = Contact.objects.create(
            first_name='Test', last_name='Adj', email='adj@test.com',
        )
        job = Job.objects.create(
            name='Adj Test Job', job_number='ADJ-001', status='approved',
            contact=contact,
        )
        # Create a draft estimate directly (skip status transition guards)
        self.est = Estimate.objects.create(
            job=job,
            estimate_number='EST-ADJ-1',
            version=1,
            status=Estimate.STATUS_DRAFT,
        )

        # Two base (non-adjustment) line items:
        #   line 1: qty=2, price=50 -> total 100 (labor)
        #   line 2: qty=1, price=40 -> total 40  (materials)
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=1,
            qty=Decimal('2'), price=Decimal('50.00'),
            accounting_category=self.labor,
        )
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=2,
            qty=Decimal('1'), price=Decimal('40.00'),
            accounting_category=self.materials,
        )

        # A 15% percentage ServicePrice (rush surcharge)
        self.rush_svc = ServicePrice.objects.create(
            name='Rush-adj', algorithm=ServicePrice.PERCENTAGE,
            rate=Decimal('15.00'), unit_label='%',
            accounting_category=self.labor,
        )

        # A -10% percentage ServicePrice (discount)
        self.discount_svc = ServicePrice.objects.create(
            name='Discount-adj', algorithm=ServicePrice.PERCENTAGE,
            rate=Decimal('-10.00'), unit_label='%',
            accounting_category=self.labor,
        )

    def _make_adj_line(self, svc, line_number):
        """Create an adjustment EstimateLineItem."""
        from apps.estimates.models import EstimateLineItem
        return EstimateLineItem.objects.create(
            estimate=self.est, line_number=line_number,
            qty=Decimal('1'), price=Decimal('0.00'),
            accounting_category=self.labor,
            adjustment_service=svc,
        )

    def test_compute_adjustment_all_lines(self):
        """Empty target set -> 15% of all non-adjustment siblings (100+40=140) = 21.00."""
        from apps.core.adjustments import compute_adjustment_amount
        from apps.estimates.models import EstimateLineItem

        adj = self._make_adj_line(self.rush_svc, 3)
        siblings = EstimateLineItem.objects.filter(estimate=self.est).exclude(pk=adj.pk)
        result = compute_adjustment_amount(adj, siblings)
        self.assertEqual(result, Decimal('21.00'))

    def test_compute_adjustment_category_filtered(self):
        """Target set = [labor] -> 15% of labor-only siblings (100) = 15.00."""
        from apps.core.adjustments import compute_adjustment_amount
        from apps.estimates.models import EstimateLineItem

        adj = self._make_adj_line(self.rush_svc, 3)
        adj.adjustment_target_categories.set([self.labor.pk])
        siblings = EstimateLineItem.objects.filter(estimate=self.est).exclude(pk=adj.pk)
        result = compute_adjustment_amount(adj, siblings)
        self.assertEqual(result, Decimal('15.00'))

    def test_compute_adjustment_negative_percent_discount(self):
        """-10% of all non-adjustment siblings (140) = -14.00."""
        from apps.core.adjustments import compute_adjustment_amount
        from apps.estimates.models import EstimateLineItem

        adj = self._make_adj_line(self.discount_svc, 3)
        siblings = EstimateLineItem.objects.filter(estimate=self.est).exclude(pk=adj.pk)
        result = compute_adjustment_amount(adj, siblings)
        self.assertEqual(result, Decimal('-14.00'))

    def test_compute_adjustment_skips_other_adjustments(self):
        """Another adjustment sibling must NOT be included in the subtotal base."""
        from apps.core.adjustments import compute_adjustment_amount
        from apps.estimates.models import EstimateLineItem

        # Add a first adjustment line (line 3) — also a sibling
        self._make_adj_line(self.rush_svc, 3)
        # The adjustment under test is line 4; all lines (1, 2, 3) are siblings
        adj = self._make_adj_line(self.rush_svc, 4)
        siblings = EstimateLineItem.objects.filter(estimate=self.est).exclude(pk=adj.pk)
        # line 3 is an adjustment so it must be excluded from the base; result = 15% of 140 = 21.00
        result = compute_adjustment_amount(adj, siblings)
        self.assertEqual(result, Decimal('21.00'))
