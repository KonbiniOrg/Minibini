"""Task-owned-money Phase 1, Task 2: Task computes its own price from its
own fields (qty_source/rate/unit_label/accounting_category/active_modifiers)
— no RateScheme involved. Mirrors the setUp shape of
tests.test_task_money_migration.TaskMoneyBackfillTest, minus the scheme."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, User
from apps.jobs.models import Blep, Job, Task


class TaskMoneyComputeTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Shop', code='SHOP')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@taskmoneycompute.test')
        self.job = Job.objects.create(
            name='J', job_number='TMC-1', contact=self.contact)

    def test_effective_rate_from_task_fields(self):
        t = Task.objects.create(
            job=self.job, name='X', qty_source=Task.QTY_ENTERED,
            rate=Decimal('100.00'), unit_label='ea', accounting_category=self.ac,
            active_modifiers=[{'key': 'rush', 'label': 'Rush', 'percent': 50}])
        self.assertEqual(t.effective_rate(), Decimal('150.00'))

    def test_effective_rate_none_rate_is_zero(self):
        t = Task.objects.create(job=self.job, name='X', rate=None,
                                accounting_category=self.ac)
        self.assertEqual(t.effective_rate(), Decimal('0.00'))

    def test_entered_qty_amounts(self):
        t = Task.objects.create(
            job=self.job, name='X', qty_source=Task.QTY_ENTERED,
            rate=Decimal('10.00'), unit_label='ea', accounting_category=self.ac,
            est_qty=Decimal('5'), actual_qty=Decimal('4'))
        self.assertEqual(t.compute_estimate_amount(), Decimal('50.00'))
        self.assertEqual(t.compute_amount(), Decimal('40.00'))

    def test_elapsed_actual_qty_sums_bleps(self):
        user = User.objects.create_user(username='task_money_compute_user')
        t = Task.objects.create(
            job=self.job, name='X', qty_source=Task.QTY_ELAPSED,
            rate=Decimal('60.00'), unit_label='hour', accounting_category=self.ac)
        now = timezone.now()
        Blep.objects.create(
            task=t, user=user, start_time=now - timedelta(minutes=90), end_time=now)
        self.assertEqual(t.get_actual_qty(), Decimal('1.50'))
