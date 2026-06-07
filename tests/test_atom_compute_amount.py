from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.models import EstWorksheet
from apps.inventory.models import Material, PlanMaterial
from apps.jobs.models import Job, RateScheme
from tests.base import FixtureTestCase


class MaterialComputeAmountTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Materials', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)

    def test_material_compute_amount(self):
        m = Material.objects.create(
            job=self.job, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('10.50'), accounting_category=self.cat,
        )
        self.assertEqual(m.compute_amount(), Decimal('31.50'))

    def test_plan_material_compute_amount(self):
        pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('2'),
            sell_price=Decimal('5.00'), accounting_category=self.cat,
        )
        self.assertEqual(pm.compute_amount(), Decimal('10.00'))

    def test_compute_amount_ignores_active_modifiers(self):
        m = Material.objects.create(
            job=self.job, description='steel', quantity=Decimal('1'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )
        # Materials don't have modifiers; the parameter is accepted for uniform interface.
        self.assertEqual(m.compute_amount(active_modifiers=['rush']), Decimal('5'))


from apps.jobs.models import (
    Blep, PlanTask, RateScheme, Task,
)
from django.utils import timezone
from datetime import timedelta


class TaskComputeAmountTest(TestCase):
    """Task.compute_amount() covers all three RateScheme algorithms."""

    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001')
        self.scheme_time = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.scheme_qty = RateScheme.objects.create(
            name='PerItem', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50'), unit_label='item', accounting_category=self.cat,
        )
        self.scheme_flat = RateScheme.objects.create(
            name='FlatFee', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('250'), unit_label='each', accounting_category=self.cat,
        )

    def test_task_elapsed_time(self):
        task = Task.objects.create(job=self.job, name='t', rate_scheme=self.scheme_time)
        now = timezone.now()
        Blep.objects.create(task=task, start_time=now - timedelta(hours=2), end_time=now)
        # 2 hours × $100 = $200
        self.assertEqual(task.compute_amount(), Decimal('200.00'))

    def test_task_entered_qty(self):
        task = Task.objects.create(
            job=self.job, name='t', actual_qty=Decimal('3'),
            rate_scheme=self.scheme_qty,
        )
        # 3 × $50 = $150
        self.assertEqual(task.compute_amount(), Decimal('150.00'))

    def test_task_flat_fee(self):
        task = Task.objects.create(job=self.job, name='t', rate_scheme=self.scheme_flat)
        self.assertEqual(task.compute_amount(), Decimal('250.00'))



class PlanTaskComputeAmountTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        job = Job.objects.first()
        self.ws = EstWorksheet.objects.create(job=job)

    def test_compute_amount_with_scheme(self):
        from apps.core.models import AccountingCategory
        ac = AccountingCategory.objects.first()
        scheme = RateScheme.objects.create(
            name='Test Hourly', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('60.00'), unit_label='hour',
            accounting_category=ac,
        )
        pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Test',
            rate_scheme=scheme,
            active_modifiers=[],
            est_qty=Decimal('2.5'),
        )
        self.assertEqual(pt.compute_amount(), Decimal('150.00'))

    def test_compute_amount_quantized_to_two_places(self):
        """compute_amount rounds to cents. est_qty (2dp) x rate (2dp) yields
        a 4dp product that would otherwise surface raw in worksheet totals."""
        from apps.core.models import AccountingCategory
        ac = AccountingCategory.objects.first()
        scheme = RateScheme.objects.create(
            name='Odd Plan Rate', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.07'), unit_label='piece',
            accounting_category=ac,
        )
        pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Odd',
            rate_scheme=scheme, active_modifiers=[],
            est_qty=Decimal('1.03'),
        )
        # 1.03 * 10.07 = 10.3721 -> 10.37
        result = pt.compute_amount()
        self.assertEqual(result, Decimal('10.37'))
        self.assertEqual(result.as_tuple().exponent, -2)

    def test_compute_amount_without_scheme_returns_zero(self):
        # Build an unsaved instance — DB+full_clean now forbid persisting
        # a PlanTask without rate_scheme/est_qty, but the helper still has
        # a guard for the in-memory case.
        pt = PlanTask(est_worksheet=self.ws, name='Bare')
        self.assertEqual(pt.compute_amount(), Decimal('0.00'))
