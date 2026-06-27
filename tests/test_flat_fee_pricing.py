"""Per-item priced flat fees with quantity.

flat_fee billing means "fixed unit price x estimated quantity". The unit
price lives on RateScheme.rate. See docs/designs/estimates-and-prices.md.
"""
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import Task, PlanTask, RateScheme, Job
from apps.estimates.models import EstWorksheet
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory


class FlatFeePricingTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Svc', code='SVC')
        contact = Contact.objects.create(first_name='A', last_name='B')
        biz = Business.objects.create(business_name='Acme', default_contact=contact)
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(
            job_number='JOB-FF-1', contact=contact, status=Job.STATUS_DRAFT,
        )
        # Shared flat-fee scheme; price comes from rate (Phase 1).
        self.flat = RateScheme.objects.create(
            name='Flat Fee', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('5.00'), unit_label='unit',
            accounting_category=self.ac,
        )

    def test_flat_fee_effective_rate_is_rate(self):
        svc = RateScheme.objects.create(
            name='Tap a hole', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1.00'), unit_label='hole', accounting_category=self.ac,
        )
        # active_modifiers is ignored for flat_fee; price comes from rate.
        self.assertEqual(svc.effective_rate([]), Decimal('1.00'))
        self.assertEqual(svc.effective_rate(['anything']), Decimal('1.00'))

    def test_flat_fee_ignores_active_modifiers_price(self):
        """Phase 1: flat-fee price lives on rate; a legacy flat_fee_price dict is ignored."""
        svc = RateScheme.objects.create(
            name='Setup', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('50.00'), unit_label='job', accounting_category=self.ac,
        )
        # Old code returned Decimal('999.00') here (from _flat_fee_price).
        # New code ignores the dict and returns self.rate.
        self.assertEqual(svc.effective_rate({'flat_fee_price': '999.00'}), Decimal('50.00'))

    def test_flat_fee_compute_charge(self):
        svc = RateScheme.objects.create(
            name='Coat plywood', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('30.00'), unit_label='sheet', accounting_category=self.ac,
        )
        self.assertEqual(svc.compute_charge(Decimal('3'), []), Decimal('90.00'))

    # --- get_actual_qty ---

    def test_get_actual_qty_flat_fee_returns_est_qty(self):
        task = Task.objects.create(
            job=self.job, name='Tap', rate_scheme=self.flat,
            est_qty=Decimal('50'),
        )
        self.assertEqual(self.flat.get_actual_qty(task), Decimal('50'))

    def test_get_actual_qty_flat_fee_falls_back_to_one(self):
        task = Task.objects.create(
            job=self.job, name='Tap (no qty)', rate_scheme=self.flat,
        )
        self.assertEqual(self.flat.get_actual_qty(task), Decimal('1'))

    # --- compute_amount on the atoms ---

    def test_task_compute_amount_flat_fee_price_on_rate(self):
        task = Task.objects.create(
            job=self.job, name='Tap holes', rate_scheme=self.flat,
            est_qty=Decimal('50'),
        )
        # rate=5.00 * est_qty=50 = 250.00
        self.assertEqual(task.compute_amount(), Decimal('250.00'))

    def test_plan_task_compute_amount_flat_fee_price_on_rate(self):
        ws = EstWorksheet.objects.create(job=self.job)
        pt = PlanTask.objects.create(
            est_worksheet=ws, name='Tap', rate_scheme=self.flat,
            est_qty=Decimal('10'),
        )
        # rate=5.00 * est_qty=10 = 50.00
        self.assertEqual(pt.compute_amount(), Decimal('50.00'))
