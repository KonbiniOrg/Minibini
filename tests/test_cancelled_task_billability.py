"""Cancelled tasks' recorded actuals are billable (plan C3).

Terminal — not complete — is the billability line: the invoice source
pool includes cancelled tasks (flagged so the biller makes a conscious
choice), while non-terminal tasks stay not_billable. The estimate pool
excludes cancelled tasks entirely: estimates project planned work.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.contacts.models import Contact
from apps.core.models import User, AccountingCategory
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateWizardService
from apps.invoicing.models import Invoice
from apps.invoicing.services import InvoiceWizardService
from apps.jobs.models import Job, Task, Blep, RateScheme


class CancelledTaskBillabilityTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='billuser', password='x')
        self.contact = Contact.objects.create(first_name='B', last_name='L')
        self.job = Job.objects.create(
            job_number='BIL-001', name='Billability Job', contact=self.contact,
        )
        ac = AccountingCategory.objects.create(code='BIL', name='Bill AC')
        self.hourly = RateScheme.objects.create(
            name='S-bill-hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('60'), unit_label='hour', accounting_category=ac,
        )
        self.qty_scheme = RateScheme.objects.create(
            name='S-bill-qty', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4'), unit_label='piece', accounting_category=ac,
        )

    def _cancelled_task(self, scheme, hours=None, actual_qty=None):
        task = Task(
            job=self.job, name='Killed',
            actual_qty=actual_qty,
        )
        task.stamp_from_scheme(scheme)
        task.save()
        if hours:
            now = timezone.now()
            Blep.objects.create(
                task=task, user=self.user,
                start_time=now - timedelta(hours=hours), end_time=now,
            )
        Task.objects.filter(pk=task.pk).update(status=Task.STATUS_CANCELLED)
        task.refresh_from_db()
        return task

    def _invoice_pool_entry(self, task):
        invoice = Invoice.objects.create(
            job=self.job, invoice_number=f'INV-BIL-{task.pk}',
        )
        pool = InvoiceWizardService.get_source_pool(invoice)
        for task_group in pool['tasks']:
            for atom in task_group['atoms']:
                if atom['type'] == 'task' and atom['id'] == task.pk:
                    return atom
        return None

    def test_cancelled_task_with_time_is_billable_in_invoice_pool(self):
        task = self._cancelled_task(self.hourly, hours=2)
        atom = self._invoice_pool_entry(task)
        self.assertIsNotNone(
            atom, 'cancelled task missing from the invoice pool')
        self.assertEqual(atom['state'], 'available')
        self.assertEqual(Decimal(str(atom['amount'])), Decimal('120.00'))

    def test_cancelled_pool_entry_is_flagged(self):
        task = self._cancelled_task(self.hourly, hours=1)
        atom = self._invoice_pool_entry(task)
        self.assertTrue(atom.get('task_cancelled'))

    def test_complete_pool_entry_is_not_flagged(self):
        task = Task(
            job=self.job, name='Done',
        )
        task.stamp_from_scheme(self.hourly)
        task.save()
        now = timezone.now()
        Blep.objects.create(
            task=task, user=self.user,
            start_time=now - timedelta(hours=1), end_time=now,
        )
        Task.objects.filter(pk=task.pk).update(status=Task.STATUS_COMPLETE)
        atom = self._invoice_pool_entry(task)
        self.assertEqual(atom['state'], 'available')
        self.assertFalse(atom.get('task_cancelled'))

    def test_in_progress_task_stays_not_billable(self):
        task = Task(
            job=self.job, name='Working',
        )
        task.stamp_from_scheme(self.hourly)
        task.save()
        Task.objects.filter(pk=task.pk).update(status=Task.STATUS_IN_PROGRESS)
        atom = self._invoice_pool_entry(task)
        self.assertEqual(atom['state'], 'not_billable')
        self.assertEqual(atom['not_billable_reason'], 'task_incomplete')

    def test_cancelled_entered_qty_task_bills_actual_qty(self):
        task = self._cancelled_task(self.qty_scheme, actual_qty=Decimal('30'))
        atom = self._invoice_pool_entry(task)
        self.assertEqual(atom['state'], 'available')
        self.assertEqual(Decimal(str(atom['amount'])), Decimal('120.00'))

    def test_cancelled_task_with_no_actuals_is_billable_at_zero(self):
        task = self._cancelled_task(self.hourly)
        atom = self._invoice_pool_entry(task)
        self.assertEqual(atom['state'], 'available')
        self.assertEqual(Decimal(str(atom['amount'])), Decimal('0.00'))

    def test_estimate_pool_excludes_cancelled_tasks(self):
        task = self._cancelled_task(self.hourly, hours=2)
        estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-BIL-1',
        )
        pool = EstimateWizardService.get_source_pool(estimate)
        task_ids = [a['id'] for a in pool['atoms'] if a['type'] == 'task']
        self.assertNotIn(task.pk, task_ids)
