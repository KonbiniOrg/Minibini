"""Model-level tests for PO reconciliation (task-owned-money Phase 5, Task 1
port — schema + model layer only; PurchaseOrderService.reconcile() and the
API surface are Tasks 2-3, ported separately).

Covers:
- PurchaseOrder reconciliation fields (bill_total, vendor_invoice_ref,
  reconciled, reconciled_date) + PurchaseOrderLineItem fields (final_price,
  invoice_only) exist with the right defaults.
- PurchaseOrder.objects.awaiting_reconciliation() / is_awaiting_reconciliation
  membership matrix across all 5 statuses x reconciled.
- po_total (unchanged, all lines) / ordered_total (excludes invoice_only) /
  variance (bill_total - ordered_total, None pre-bill) math.
- PurchaseOrderLineItem.clean() task-link guard: job-bearing task accepted,
  a task without a job rejected (field-shaped ValidationError on 'task'),
  link stays optional, multiple lines on one PO may link tasks from
  different jobs. NOTE: per the outsourced-work port ruling, Task.parent_task
  is dormant on this branch (no code may read/write it) — the fees-era
  top-level/subtask branch of this check is deliberately NOT ported, and
  fees' subtask test cases are dropped accordingly.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, Task
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem


class POReconciliationTestBase(TestCase):
    """Shared setUp: a vendor Business + two Jobs (for multi-job link tests)."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Vendor',
            email='vendor@test.com', work_number='555-1234',
        )
        self.business = Business.objects.create(
            business_name='Test Vendor Co', business_phone='555-1234',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.cat = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False},
        )[0]
        self.customer = Contact.objects.create(
            first_name='Cust', last_name='Omer',
            email='cust@test.com', work_number='555-0000',
        )
        self.job_a = Job.objects.create(
            job_number='J-A', contact=self.customer, description='a',
            status=Job.STATUS_APPROVED,
        )
        self.job_b = Job.objects.create(
            job_number='J-B', contact=self.customer, description='b',
            status=Job.STATUS_APPROVED,
        )
        self.task_a = Task.objects.create(job=self.job_a, name='Outsourced work')
        self.task_b = Task.objects.create(job=self.job_b, name='Other job work')

    def _make_line(self, po, **kwargs):
        defaults = dict(
            purchase_order=po, description='Item',
            qty=Decimal('2.00'), price=Decimal('10.00'),
            accounting_category=self.cat,
        )
        defaults.update(kwargs)
        return PurchaseOrderLineItem.objects.create(**defaults)


class POReconciliationFieldsTest(POReconciliationTestBase):
    """New fields exist with the documented defaults."""

    def test_po_reconciliation_fields_default(self):
        po = PurchaseOrder.objects.create(business=self.business)
        self.assertIsNone(po.bill_total)
        self.assertEqual(po.vendor_invoice_ref, '')
        self.assertFalse(po.reconciled)
        self.assertIsNone(po.reconciled_date)

    def test_line_item_reconciliation_fields_default(self):
        po = PurchaseOrder.objects.create(business=self.business)
        li = self._make_line(po)
        self.assertIsNone(li.final_price)
        self.assertFalse(li.invoice_only)

    def test_po_reconciliation_fields_settable(self):
        from django.utils import timezone
        now = timezone.now()
        po = PurchaseOrder.objects.create(
            business=self.business,
            bill_total=Decimal('123.45'), vendor_invoice_ref='VEND-1',
            reconciled=True, reconciled_date=now,
        )
        po.refresh_from_db()
        self.assertEqual(po.bill_total, Decimal('123.45'))
        self.assertEqual(po.vendor_invoice_ref, 'VEND-1')
        self.assertTrue(po.reconciled)
        self.assertIsNotNone(po.reconciled_date)

    def test_line_item_final_price_and_invoice_only_settable(self):
        po = PurchaseOrder.objects.create(business=self.business)
        li = self._make_line(po, final_price=Decimal('9.99'), invoice_only=True)
        li.refresh_from_db()
        self.assertEqual(li.final_price, Decimal('9.99'))
        self.assertTrue(li.invoice_only)


class AwaitingReconciliationMembershipTest(POReconciliationTestBase):
    """Membership matrix: awaiting_reconciliation() / is_awaiting_reconciliation
    are true iff status == received_in_full AND reconciled is False —
    independent of how that state was reached."""

    def _make(self, status, reconciled):
        return PurchaseOrder.objects.create(
            business=self.business, status=status, reconciled=reconciled,
        )

    def test_draft_not_awaiting(self):
        po = self._make(PurchaseOrder.STATUS_DRAFT, False)
        self.assertFalse(po.is_awaiting_reconciliation)
        self.assertNotIn(po, PurchaseOrder.objects.awaiting_reconciliation())

    def test_issued_unreconciled_not_awaiting(self):
        po = self._make(PurchaseOrder.STATUS_ISSUED, False)
        self.assertFalse(po.is_awaiting_reconciliation)
        self.assertNotIn(po, PurchaseOrder.objects.awaiting_reconciliation())

    def test_partly_received_unreconciled_not_awaiting(self):
        po = self._make(PurchaseOrder.STATUS_PARTLY_RECEIVED, False)
        self.assertFalse(po.is_awaiting_reconciliation)
        self.assertNotIn(po, PurchaseOrder.objects.awaiting_reconciliation())

    def test_received_in_full_unreconciled_is_awaiting(self):
        po = self._make(PurchaseOrder.STATUS_RECEIVED_IN_FULL, False)
        self.assertTrue(po.is_awaiting_reconciliation)
        self.assertIn(po, PurchaseOrder.objects.awaiting_reconciliation())

    def test_received_in_full_reconciled_not_awaiting(self):
        po = self._make(PurchaseOrder.STATUS_RECEIVED_IN_FULL, True)
        self.assertFalse(po.is_awaiting_reconciliation)
        self.assertNotIn(po, PurchaseOrder.objects.awaiting_reconciliation())

    def test_cancelled_unreconciled_not_awaiting(self):
        po = self._make(PurchaseOrder.STATUS_CANCELLED, False)
        self.assertFalse(po.is_awaiting_reconciliation)
        self.assertNotIn(po, PurchaseOrder.objects.awaiting_reconciliation())

    def test_cancelled_reconciled_not_awaiting(self):
        po = self._make(PurchaseOrder.STATUS_CANCELLED, True)
        self.assertFalse(po.is_awaiting_reconciliation)
        self.assertNotIn(po, PurchaseOrder.objects.awaiting_reconciliation())

    def test_issued_reconciled_not_awaiting(self):
        """reconciled=True on a non-received-in-full PO is an odd combination
        but the filter must still evaluate on status, not just the flag."""
        po = self._make(PurchaseOrder.STATUS_ISSUED, True)
        self.assertFalse(po.is_awaiting_reconciliation)
        self.assertNotIn(po, PurchaseOrder.objects.awaiting_reconciliation())


class VarianceMathTest(POReconciliationTestBase):

    def test_po_total_includes_invoice_only_lines(self):
        """po_total is untouched by reconciliation — still all lines."""
        po = PurchaseOrder.objects.create(business=self.business)
        self._make_line(po, qty=Decimal('2.00'), price=Decimal('10.00'))
        self._make_line(po, qty=Decimal('1.00'), price=Decimal('15.00'), invoice_only=True)
        self.assertEqual(po.po_total, Decimal('35.00'))

    def test_ordered_total_excludes_invoice_only_lines(self):
        po = PurchaseOrder.objects.create(business=self.business)
        self._make_line(po, qty=Decimal('2.00'), price=Decimal('10.00'))
        self._make_line(po, qty=Decimal('1.00'), price=Decimal('15.00'), invoice_only=True)
        self.assertEqual(po.ordered_total, Decimal('20.00'))

    def test_ordered_total_with_no_invoice_only_lines_matches_po_total(self):
        po = PurchaseOrder.objects.create(business=self.business)
        self._make_line(po, qty=Decimal('3.00'), price=Decimal('5.00'))
        self.assertEqual(po.ordered_total, po.po_total)

    def test_variance_none_before_bill_total_set(self):
        po = PurchaseOrder.objects.create(business=self.business)
        self._make_line(po, qty=Decimal('1.00'), price=Decimal('10.00'))
        self.assertIsNone(po.variance)

    def test_variance_is_bill_total_minus_ordered_total(self):
        po = PurchaseOrder.objects.create(
            business=self.business, bill_total=Decimal('25.00'),
        )
        self._make_line(po, qty=Decimal('2.00'), price=Decimal('10.00'))
        self.assertEqual(po.variance, Decimal('5.00'))

    def test_variance_excludes_invoice_only_from_ordered_side(self):
        """A freight invoice_only line inflates bill_total but must not be
        double-counted on the ordered side — variance should reflect the
        genuine delta on the ordered lines only."""
        po = PurchaseOrder.objects.create(
            business=self.business, bill_total=Decimal('35.00'),
        )
        self._make_line(po, qty=Decimal('2.00'), price=Decimal('10.00'))
        self._make_line(po, qty=Decimal('1.00'), price=Decimal('15.00'), invoice_only=True)
        # ordered_total = 20.00; variance = 35.00 - 20.00 = 15.00 (the
        # freight shows up as variance, not silently absorbed).
        self.assertEqual(po.variance, Decimal('15.00'))


class TaskLinkValidationTest(POReconciliationTestBase):
    """PurchaseOrderLineItem.clean() task-link guard — job-bearing check only
    (the fees-era top-level/subtask branch is dropped; parent_task is
    dormant on this branch)."""

    def test_link_job_bearing_task_ok(self):
        po = PurchaseOrder.objects.create(business=self.business)
        li = PurchaseOrderLineItem(
            purchase_order=po, description='Outsourced',
            qty=Decimal('1.00'), price=Decimal('50.00'),
            accounting_category=self.cat, task=self.task_a,
        )
        li.full_clean()  # should not raise
        li.save()
        self.assertEqual(li.task_id, self.task_a.pk)

    def test_task_link_is_optional(self):
        po = PurchaseOrder.objects.create(business=self.business)
        li = PurchaseOrderLineItem(
            purchase_order=po, description='Material only',
            qty=Decimal('1.00'), price=Decimal('50.00'),
            accounting_category=self.cat,
        )
        li.full_clean()  # should not raise
        li.save()
        self.assertIsNone(li.task_id)

    def test_link_to_task_without_job_rejected(self):
        """Defense-in-depth: Task.job is a required FK at the DB level, so a
        persisted, job-less Task cannot exist in practice. This exercises
        the guard directly by mutating an in-memory (already-saved) Task's
        cached job_id — never persisted — to simulate the state the check
        guards against."""
        po = PurchaseOrder.objects.create(business=self.business)
        jobless_task = Task.objects.create(job=self.job_a, name='Will be detached')
        jobless_task.job_id = None  # in-memory only; not saved
        li = PurchaseOrderLineItem(
            purchase_order=po, description='Bad link',
            qty=Decimal('1.00'), price=Decimal('50.00'),
            accounting_category=self.cat, task=jobless_task,
        )
        with self.assertRaises(ValidationError) as ctx:
            li.full_clean()
        self.assertIn('task', ctx.exception.message_dict)

    def test_single_po_can_link_tasks_from_different_jobs(self):
        """PO lines may serve multiple jobs via different tasks (spec §7 rule 1)."""
        po = PurchaseOrder.objects.create(business=self.business)
        li_a = PurchaseOrderLineItem(
            purchase_order=po, description='For job A',
            qty=Decimal('1.00'), price=Decimal('50.00'),
            accounting_category=self.cat, task=self.task_a,
        )
        li_a.full_clean()
        li_a.save()
        li_b = PurchaseOrderLineItem(
            purchase_order=po, description='For job B',
            qty=Decimal('1.00'), price=Decimal('50.00'),
            accounting_category=self.cat, task=self.task_b,
        )
        li_b.full_clean()
        li_b.save()
        self.assertEqual(li_a.task.job_id, self.job_a.pk)
        self.assertEqual(li_b.task.job_id, self.job_b.pk)

    def test_task_and_inventory_item_exclusivity_still_enforced(self):
        """BaseLineItem.clean()'s pre-existing mutual-exclusivity check still
        fires — PurchaseOrderLineItem.clean() extends it, not replaces it."""
        from apps.inventory.models import InventoryItem
        po = PurchaseOrder.objects.create(business=self.business)
        item = InventoryItem.objects.create(
            code='WIDGET-1', accounting_category=self.cat,
        )
        li = PurchaseOrderLineItem(
            purchase_order=po, description='Both set',
            qty=Decimal('1.00'), price=Decimal('50.00'),
            accounting_category=self.cat, task=self.task_a,
            inventory_item=item,
        )
        with self.assertRaises(ValidationError):
            li.full_clean()
