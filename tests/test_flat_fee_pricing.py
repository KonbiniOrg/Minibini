"""Per-item priced flat fees with quantity.

flat_fee billing now means "fixed unit price x estimated quantity". The unit
price rides on the atom (TaskTemplate -> PlanTask -> Task) in the
active_modifiers JSON field as {'flat_fee_price': <str>}; the RateScheme.rate
is only a fallback. See docs/designs/estimates-and-prices.md.
"""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError

from apps.jobs.models import Task, PlanTask, RateScheme, Job
from apps.estimates.models import EstWorksheet, TaskTemplate
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory


class FlatFeePricingTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Flat')
        contact = Contact.objects.create(first_name='A', last_name='B')
        biz = Business.objects.create(business_name='Acme', default_contact=contact)
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(
            job_number='JOB-FF-1', contact=contact, status=Job.STATUS_DRAFT,
        )
        # Shared flat-fee scheme; rate is the fallback default only.
        self.flat = RateScheme.objects.create(
            name='Flat Fee', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('5.00'), unit_label='unit',
            accounting_category=self.ac,
        )

    # --- RateScheme math ---

    def test_effective_rate_uses_flat_fee_price_from_modifiers(self):
        rate = self.flat.effective_rate({'flat_fee_price': '30.00'})
        self.assertEqual(rate, Decimal('30.00'))

    def test_effective_rate_falls_back_to_scheme_rate(self):
        self.assertEqual(self.flat.effective_rate(), Decimal('5.00'))
        self.assertEqual(self.flat.effective_rate([]), Decimal('5.00'))

    def test_compute_charge_flat_fee_multiplies_price_by_qty(self):
        charge = self.flat.compute_charge(Decimal('50'), {'flat_fee_price': '1.00'})
        self.assertEqual(charge, Decimal('50.00'))

    def test_get_actual_qty_flat_fee_returns_est_qty(self):
        task = Task.objects.create(
            job=self.job, name='Tap', rate_scheme=self.flat,
            active_modifiers={'flat_fee_price': '1.00'}, est_qty=Decimal('50'),
        )
        self.assertEqual(self.flat.get_actual_qty(task), Decimal('50'))

    # --- compute_amount on the atoms ---

    def test_task_compute_amount_flat_fee_priced_and_quantified(self):
        task = Task.objects.create(
            job=self.job, name='Tap holes', rate_scheme=self.flat,
            active_modifiers={'flat_fee_price': '1.00'}, est_qty=Decimal('50'),
        )
        self.assertEqual(task.compute_amount(), Decimal('50.00'))

    def test_plan_task_compute_amount_flat_fee_priced_and_quantified(self):
        ws = EstWorksheet.objects.create(job=self.job)
        pt = PlanTask.objects.create(
            est_worksheet=ws, name='Tap', rate_scheme=self.flat,
            active_modifiers={'flat_fee_price': '2.00'}, est_qty=Decimal('10'),
        )
        self.assertEqual(pt.compute_amount(), Decimal('20.00'))

    # --- price carries through templates and carry-over ---

    def test_template_generate_task_carries_flat_fee_price(self):
        tmpl = TaskTemplate.objects.create(
            template_name='Tap', rate_scheme=self.flat,
            default_active_modifiers={'flat_fee_price': '1.00'},
            default_billable_qty=Decimal('25'),
        )
        task = tmpl.generate_task(self.job, est_qty=Decimal('25'))
        self.assertEqual(task.active_modifiers, {'flat_fee_price': '1.00'})
        self.assertEqual(task.compute_amount(), Decimal('25.00'))

    def test_plan_task_carry_over_preserves_flat_fee_price(self):
        ws = EstWorksheet.objects.create(job=self.job)
        pt = PlanTask.objects.create(
            est_worksheet=ws, name='Tap', rate_scheme=self.flat,
            active_modifiers={'flat_fee_price': '3.00'}, est_qty=Decimal('7'),
        )
        from apps.jobs.services import JobService
        JobService.materialize_worksheet_onto_job(self.job, ws)
        task = Task.objects.get(source_plan_task=pt)
        self.assertEqual(task.active_modifiers, {'flat_fee_price': '3.00'})
        self.assertEqual(task.compute_amount(), Decimal('21.00'))

    # --- TaskTemplate validation ---

    def test_clean_rejects_flat_fee_template_without_price(self):
        tmpl = TaskTemplate(
            template_name='Tap', rate_scheme=self.flat,
            default_active_modifiers=[], default_billable_qty=Decimal('1'),
        )
        with self.assertRaises(ValidationError):
            tmpl.full_clean()

    def test_clean_rejects_flat_fee_template_with_zero_price(self):
        tmpl = TaskTemplate(
            template_name='Tap', rate_scheme=self.flat,
            default_active_modifiers={'flat_fee_price': '0'},
            default_billable_qty=Decimal('1'),
        )
        with self.assertRaises(ValidationError):
            tmpl.full_clean()

    def test_clean_allows_flat_fee_template_with_price(self):
        tmpl = TaskTemplate(
            template_name='Tap', rate_scheme=self.flat,
            default_active_modifiers={'flat_fee_price': '1.00'},
            default_billable_qty=Decimal('1'),
        )
        tmpl.full_clean()  # must not raise

    def test_clean_allows_non_flat_template_with_modifier_keys(self):
        elapsed = RateScheme.objects.create(
            name='Hourly FF', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50.00'), unit_label='hour',
            modifiers=[{'key': 'rush', 'label': 'Rush', 'percent': 10}],
            accounting_category=self.ac,
        )
        tmpl = TaskTemplate(
            template_name='Work', rate_scheme=elapsed,
            default_active_modifiers=['rush'], default_billable_qty=Decimal('1'),
        )
        tmpl.full_clean()  # must not raise
