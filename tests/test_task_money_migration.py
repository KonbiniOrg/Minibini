from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, RateScheme, Task
from apps.jobs.task_money_backfill import backfill_task_money  # helper the data migration calls


class TaskMoneyBackfillTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Shop', code='SHOP')
        self.scheme = RateScheme.objects.create(
            name='Shop rate', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('95.00'), unit_label='hour',
            modifiers=[{'key': 'rush', 'label': 'Rush', 'percent': 50}],
            accounting_category=self.ac)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@taskmoney.test')
        self.job = Job.objects.create(
            name='J', job_number='TM-1', contact=self.contact)
        self.task = Task.objects.create(
            job=self.job, name='Cut', source_scheme=self.scheme,
            active_modifiers=['rush'])

    def test_backfill_copies_scheme_values_and_resolves_modifiers(self):
        # Simulate pre-backfill state: money fields empty, modifiers still keys.
        Task.objects.filter(pk=self.task.pk).update(
            rate=None, unit_label='none', accounting_category=None,
            qty_source=Task.QTY_ENTERED, active_modifiers=['rush'])
        backfill_task_money(Task, RateScheme)
        t = Task.objects.get(pk=self.task.pk)
        self.assertEqual(t.rate, Decimal('95.00'))
        self.assertEqual(t.unit_label, 'hour')
        self.assertEqual(t.qty_source, Task.QTY_ELAPSED)
        self.assertEqual(t.accounting_category_id, self.ac.pk)
        self.assertEqual(t.active_modifiers,
                         [{'key': 'rush', 'label': 'Rush', 'percent': 50}])

    def test_backfill_skips_percentage_scheme_task_and_reports_count(self):
        """A task pointing at a percentage-algorithm scheme is a historical
        anomaly the current guards (stamp_from_scheme/RateScheme.clean)
        forbid going forward — Task.qty_source has no 'percentage' choice,
        so blindly copying scheme.algorithm would persist an out-of-choices
        value. QuerySet.update bypasses Task.full_clean/save to construct
        that anomaly (stamp_from_scheme itself raises ValueError for a
        percentage scheme, so it can't be reached the normal way)."""
        pct_scheme = RateScheme.objects.create(
            name='Rush pct', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='%',
            accounting_category=self.ac)
        Task.objects.filter(pk=self.task.pk).update(
            source_scheme=pct_scheme, rate=Decimal('95.00'),
            unit_label='hour', qty_source=Task.QTY_ELAPSED,
            accounting_category=self.ac, active_modifiers=[])
        before = Task.objects.get(pk=self.task.pk)
        skipped = backfill_task_money(Task, RateScheme)
        self.assertEqual(skipped, 1)
        after = Task.objects.get(pk=self.task.pk)
        self.assertEqual(after.rate, before.rate)
        self.assertEqual(after.unit_label, before.unit_label)
        self.assertEqual(after.qty_source, before.qty_source)
        self.assertEqual(after.accounting_category_id, before.accounting_category_id)
        self.assertEqual(after.active_modifiers, before.active_modifiers)
