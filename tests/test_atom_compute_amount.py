from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.inventory.models import Material
from apps.jobs.models import Job, RateScheme


class MaterialComputeAmountTest(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Materials', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')

    def test_material_compute_amount(self):
        m = Material.objects.create(
            job=self.job, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('10.50'), accounting_category=self.cat,
        )
        self.assertEqual(m.compute_amount(), Decimal('31.50'))

    def test_compute_amount_ignores_active_modifiers(self):
        m = Material.objects.create(
            job=self.job, description='steel', quantity=Decimal('1'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )
        # Materials don't have modifiers; the parameter is accepted for uniform interface.
        self.assertEqual(m.compute_amount(active_modifiers=['rush']), Decimal('5'))


from apps.jobs.models import (
    Blep, RateScheme, Task,
)
from django.utils import timezone
from datetime import timedelta


class TaskComputeAmountTest(TestCase):
    """Task.compute_amount() covers all three RateScheme algorithms."""

    def setUp(self):
        from apps.core.models import User
        self.user = User.objects.create_user(username='compute_amount_user')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
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
            name='FlatFee', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('250'), unit_label='each', accounting_category=self.cat,
        )

    def test_task_elapsed_time(self):
        task = Task.objects.create(job=self.job, name='t', rate_scheme=self.scheme_time)
        now = timezone.now()
        Blep.objects.create(task=task, user=self.user, start_time=now - timedelta(hours=2), end_time=now)
        # 2 hours × $100 = $200
        self.assertEqual(task.compute_amount(), Decimal('200.00'))

    def test_task_entered_qty(self):
        task = Task.objects.create(
            job=self.job, name='t', actual_qty=Decimal('3'),
            rate_scheme=self.scheme_qty,
        )
        # 3 × $50 = $150
        self.assertEqual(task.compute_amount(), Decimal('150.00'))

    def test_compute_estimate_amount_bills_est_qty(self):
        """Estimate-side amount bills est_qty (not actuals)."""
        task = Task.objects.create(
            job=self.job, name='est', est_qty=Decimal('2.5'),
            rate_scheme=self.scheme_qty,
        )
        # 2.5 × $50 = $125.00
        self.assertEqual(task.compute_estimate_amount(), Decimal('125.00'))

    def test_compute_estimate_amount_quantized_to_two_places(self):
        """est_qty (2dp) × rate (2dp) yields a 4dp product that must round
        to cents."""
        scheme = RateScheme.objects.create(
            name='OddRate', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.07'), unit_label='piece',
            accounting_category=self.cat,
        )
        task = Task.objects.create(
            job=self.job, name='odd', est_qty=Decimal('1.03'),
            rate_scheme=scheme,
        )
        # 1.03 * 10.07 = 10.3721 -> 10.37
        result = task.compute_estimate_amount()
        self.assertEqual(result, Decimal('10.37'))
        self.assertEqual(result.as_tuple().exponent, -2)
