from decimal import Decimal
from django.test import TestCase

from apps.jobs.models import Task, RateScheme, Blep, Job
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory


class TaskComputeAmountTest(TestCase):
    """Task takes over compute_amount / effective_rate / effective_accounting_category
    that previously lived on TaskCharge."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Labor')
        # Business/Contact have circular FK; create Contact first, then Business
        # with default_contact=contact, then link contact back. (See B0 test.)
        contact = Contact.objects.create(first_name='A', last_name='B')
        biz = Business.objects.create(business_name='Acme', default_contact=contact)
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(
            job_number='JOB-2026-0001', contact=contact, status=Job.STATUS_DRAFT,
        )

    def test_compute_amount_flat_fee(self):
        scheme = RateScheme.objects.create(
            name='Setup', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('100.00'), unit_label='job',
            accounting_category=self.ac,
        )
        task = Task.objects.create(
            job=self.job, name='Setup',
            rate_scheme=scheme, active_modifiers=[],
        )
        self.assertEqual(task.compute_amount(), Decimal('100.00'))

    def test_compute_amount_entered_qty(self):
        scheme = RateScheme.objects.create(
            name='Pieces', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('5.00'), unit_label='piece',
            accounting_category=self.ac,
        )
        task = Task.objects.create(
            job=self.job, name='Polish',
            rate_scheme=scheme, active_modifiers=[],
            actual_qty=Decimal('12'),
        )
        self.assertEqual(task.compute_amount(), Decimal('60.00'))

    def test_compute_amount_quantized_to_two_places(self):
        """compute_amount rounds to cents. qty (2dp) x rate (2dp) yields a
        4dp product; the raw value would surface on the task detail page."""
        scheme = RateScheme.objects.create(
            name='Odd Rate', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.07'), unit_label='piece',
            accounting_category=self.ac,
        )
        task = Task.objects.create(
            job=self.job, name='Polish',
            rate_scheme=scheme, active_modifiers=[],
            actual_qty=Decimal('1.03'),
        )
        # 1.03 * 10.07 = 10.3721 -> 10.37
        result = task.compute_amount()
        self.assertEqual(result, Decimal('10.37'))
        self.assertEqual(result.as_tuple().exponent, -2)

    def test_effective_accounting_category_reads_from_scheme(self):
        scheme = RateScheme.objects.create(
            name='Setup', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('100.00'), unit_label='job',
            accounting_category=self.ac,
        )
        task = Task.objects.create(
            job=self.job, name='Setup', rate_scheme=scheme,
        )
        self.assertEqual(task.effective_accounting_category, self.ac)

    def test_effective_rate_applies_modifiers(self):
        scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50.00'), unit_label='hour',
            modifiers=[{'key': 'rush', 'label': 'Rush', 'percent': 20}],
            accounting_category=self.ac,
        )
        task = Task.objects.create(
            job=self.job, name='Rushy',
            rate_scheme=scheme, active_modifiers=['rush'],
        )
        self.assertEqual(task.effective_rate(), Decimal('60.00'))
