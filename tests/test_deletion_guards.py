"""Rule-1 deletion guards — delete only the unreferenced.

Doctrine (docs/plans/2026-07-03-deletion-doctrine-named-events.md): hard
deletion is mistake correction and is legitimate only while nothing references
the row. Committed records are retired by named events instead:

- Fee: refuse while claimed (any lens) or invoiced — the removal of an agreed
  charge is a change order, not a delete.
- Task: refuse while claimed by a NON-DRAFT document or invoiced; draft claims
  stay deletable ("remove it from the line first" remains available).
- Blep: refuse when the blep's task is invoiced — billed actuals are frozen.
  Estimate claims never block (estimates bill est_qty, bleps don't move it).
- Expense reject: refuse while the expense's material is claimed — extends the
  existing consumed-guard, so reject's delete is always Rule-1-legal.
- Job: destroy refuses when the job has bleps, invoices, or any non-draft
  estimate/CO — cancel instead. Unworked draft quotes still hard-delete.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource
from apps.expenses.models import Expense
from apps.expenses.services import ExpenseService
from apps.inventory.models import InventoryItem, Material
from apps.inventory.services import MaterialService
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.jobs.models import Blep, Fee, Job, RateScheme, Task
from apps.jobs.services import BlepService, FeeService, JobService, TaskService


class DeletionGuardBase(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(
            name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-2026-0001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.manager = User.objects.create_user(username='mgr', password='x')
        from django.contrib.auth.models import Permission
        self.manager.user_permissions.add(Permission.objects.get(
            codename='can_manage_time', content_type__app_label='core'))
        self.manager = User.objects.get(pk=self.manager.pk)

    def _estimate(self, status=Estimate.STATUS_DRAFT, number='EST-1'):
        return Estimate.objects.create(
            job=self.job, estimate_number=number, status=status)

    def _claim(self, estimate, source_type, pk):
        line = EstimateLineItem.objects.create(
            estimate=estimate, description='claimed', qty=Decimal('1'),
            price=Decimal('10.00'), accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=line, source_type=source_type, source_pk=pk)
        return line

    def _invoice_claim(self, source_type, pk):
        invoice = Invoice.objects.create(
            job=self.job, invoice_number=f'INV-{source_type}-{pk}')
        inv_li = InvoiceLineItem.objects.create(
            invoice=invoice, description='x', qty=Decimal('1'),
            price=Decimal('10.00'), accounting_category=self.cat,
        )
        return InvoiceLineItemSource.objects.create(
            invoice_line_item=inv_li, source_type=source_type, source_pk=pk)

    def _fee(self):
        return Fee.objects.create(
            job=self.job, description='fee', quantity=Decimal('1'),
            unit_rate=Decimal('25.00'), accounting_category=self.cat,
        )

    def _task(self):
        t = Task(
            job=self.job, name='Cutting',
            est_qty=Decimal('2'),
        )
        t.stamp_from_scheme(self.scheme)
        t.save()
        return t


class FeeDeletionGuardTests(DeletionGuardBase):

    def test_unreferenced_fee_deletes(self):
        fee = self._fee()
        FeeService.delete(fee.pk)
        self.assertFalse(Fee.objects.filter(pk=fee.pk).exists())

    def test_estimate_claimed_fee_refuses_even_on_draft(self):
        fee = self._fee()
        self._claim(self._estimate(), EstimateLineItemSource.SOURCE_FEE, fee.pk)
        with self.assertRaises(ValidationError) as ctx:
            FeeService.delete(fee.pk)
        self.assertIn('change order', str(ctx.exception).lower())
        self.assertTrue(Fee.objects.filter(pk=fee.pk).exists())

    def test_invoiced_fee_refuses(self):
        fee = self._fee()
        self._invoice_claim(InvoiceLineItemSource.SOURCE_FEE, fee.pk)
        with self.assertRaises(ValidationError):
            FeeService.delete(fee.pk)


class TaskDeletionGuardTests(DeletionGuardBase):

    def test_unreferenced_task_deletes(self):
        task = self._task()
        TaskService.delete_task(task.pk)
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())

    def test_draft_estimate_claim_still_deletable(self):
        task = self._task()
        self._claim(self._estimate(), EstimateLineItemSource.SOURCE_TASK, task.pk)
        TaskService.delete_task(task.pk)
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())

    def test_sent_estimate_claim_refuses(self):
        task = self._task()
        self._claim(
            self._estimate(status=Estimate.STATUS_OPEN),
            EstimateLineItemSource.SOURCE_TASK, task.pk)
        with self.assertRaises(ValidationError) as ctx:
            TaskService.delete_task(task.pk)
        self.assertIn('cancel', str(ctx.exception).lower())
        self.assertTrue(Task.objects.filter(pk=task.pk).exists())

    def test_invoiced_task_refuses(self):
        task = self._task()
        self._invoice_claim(InvoiceLineItemSource.SOURCE_TASK, task.pk)
        with self.assertRaises(ValidationError):
            TaskService.delete_task(task.pk)


class BlepDeletionGuardTests(DeletionGuardBase):

    def _blep(self, task):
        now = timezone.now()
        return Blep.objects.create(
            user=self.manager, task=task, start_time=now, end_time=now)

    def test_blep_on_invoiced_task_refuses_even_for_manager(self):
        task = self._task()
        blep = self._blep(task)
        self._invoice_claim(InvoiceLineItemSource.SOURCE_TASK, task.pk)
        with self.assertRaises(Exception):
            BlepService.delete(blep, self.manager)
        self.assertTrue(Blep.objects.filter(pk=blep.pk).exists())

    def _past_blep(self, task):
        """A closed blep safely in the past, inside an enclosing shift.

        Both matter for the edit tests: the future-end check and the
        shift-enclosure check would otherwise raise first and mask whether the
        invoiced-freeze is the thing doing the refusing.
        """
        from apps.core.models import Shift
        now = timezone.now().replace(microsecond=0)
        Shift.objects.create(
            user=self.manager,
            start_time=now - timezone.timedelta(hours=4),
            end_time=now - timezone.timedelta(minutes=15))
        return Blep.objects.create(
            user=self.manager, task=task,
            start_time=now - timezone.timedelta(hours=3),
            end_time=now - timezone.timedelta(hours=2))

    def test_blep_edit_on_invoiced_task_refuses_even_for_manager(self):
        # Same reasoning as delete: widening or narrowing a blep under an
        # invoiced task silently moves the actuals behind a number already
        # charged. Editing is not a lesser act than deleting here.
        task = self._task()
        blep = self._past_blep(task)
        self._invoice_claim(InvoiceLineItemSource.SOURCE_TASK, task.pk)
        original_end = blep.end_time
        with self.assertRaises(ValidationError) as ctx:
            BlepService.update(
                blep, self.manager,
                end_time=original_end + timezone.timedelta(hours=1))
        # Assert the REASON, not merely that something raised — the
        # future-end and job-status checks would also raise here.
        self.assertIn('frozen', str(ctx.exception))
        blep.refresh_from_db()
        self.assertEqual(blep.end_time, original_end)

    def test_blep_edit_on_uninvoiced_complete_task_allowed(self):
        # The freeze keys on INVOICED, not on complete: a finished but
        # unbilled task's time stays correctable.
        task = self._task()
        task.status = Task.STATUS_COMPLETE
        task.save()
        blep = self._past_blep(task)
        new_end = blep.end_time + timezone.timedelta(minutes=30)
        BlepService.update(blep, self.manager, end_time=new_end)
        blep.refresh_from_db()
        self.assertEqual(blep.end_time, new_end)

    def test_blep_edit_on_estimate_claimed_task_allowed(self):
        # Estimate claims never freeze time — estimates bill est_qty.
        task = self._task()
        blep = self._past_blep(task)
        self._claim(
            self._estimate(status=Estimate.STATUS_OPEN),
            EstimateLineItemSource.SOURCE_TASK, task.pk)
        new_end = blep.end_time + timezone.timedelta(minutes=30)
        BlepService.update(blep, self.manager, end_time=new_end)
        blep.refresh_from_db()
        self.assertEqual(blep.end_time, new_end)

    def test_blep_on_estimate_claimed_task_deletes(self):
        # Estimate claims don't freeze time — estimates bill est_qty.
        task = self._task()
        blep = self._blep(task)
        self._claim(
            self._estimate(status=Estimate.STATUS_OPEN),
            EstimateLineItemSource.SOURCE_TASK, task.pk)
        BlepService.delete(blep, self.manager)
        self.assertFalse(Blep.objects.filter(pk=blep.pk).exists())


class ExpenseRejectGuardTests(DeletionGuardBase):

    def _expense_with_material(self):
        material = MaterialService.create_on_job(
            job=self.job, description='bought', quantity=Decimal('2'),
            sell_price=Decimal('50.00'), accounting_category=self.cat,
            units='ea',
        )
        expense = Expense.objects.create(
            entered_by=self.manager, purchased_by=self.manager,
            amount=Decimal('80.00'), purchased_on=timezone.now().date(),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            job=self.job, material=material,
        )
        return expense, material

    def test_reject_refuses_while_material_claimed(self):
        expense, material = self._expense_with_material()
        self._claim(
            self._estimate(), EstimateLineItemSource.SOURCE_MATERIAL, material.pk)
        with self.assertRaises(ValidationError):
            ExpenseService.reject(expense=expense, actor=self.manager)
        self.assertTrue(Material.objects.filter(pk=material.pk).exists())

    def test_reject_deletes_unclaimed_material(self):
        expense, material = self._expense_with_material()
        ExpenseService.reject(expense=expense, actor=self.manager)
        self.assertFalse(Material.objects.filter(pk=material.pk).exists())


class JobDeletionGuardTests(DeletionGuardBase):

    def test_unworked_job_is_deletable(self):
        JobService.assert_job_deletable(self.job)  # no raise

    def test_job_with_bleps_refuses(self):
        task = self._task()
        now = timezone.now()
        Blep.objects.create(
            user=self.manager, task=task, start_time=now, end_time=now)
        with self.assertRaises(ValidationError) as ctx:
            JobService.assert_job_deletable(self.job)
        self.assertIn('cancel', str(ctx.exception).lower())

    def test_job_with_invoice_refuses(self):
        Invoice.objects.create(job=self.job, invoice_number='INV-J-1')
        with self.assertRaises(ValidationError):
            JobService.assert_job_deletable(self.job)

    def test_job_with_sent_estimate_refuses(self):
        self._estimate(status=Estimate.STATUS_OPEN)
        with self.assertRaises(ValidationError):
            JobService.assert_job_deletable(self.job)

    def test_job_with_draft_estimate_is_deletable(self):
        self._estimate(status=Estimate.STATUS_DRAFT)
        JobService.assert_job_deletable(self.job)  # no raise

    def test_destroy_endpoint_refuses_worked_job(self):
        from rest_framework.test import APIClient
        from django.contrib.auth.models import Permission
        task = self._task()
        now = timezone.now()
        Blep.objects.create(
            user=self.manager, task=task, start_time=now, end_time=now)
        mgr = User.objects.create_user(username='jobmgr', password='x')
        mgr.user_permissions.add(Permission.objects.get(
            codename='can_manage_jobs', content_type__app_label='core'))
        client = APIClient()
        client.force_authenticate(user=User.objects.get(pk=mgr.pk))
        resp = client.delete(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Job.objects.filter(pk=self.job.pk).exists())
