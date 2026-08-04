"""Tests for PO reconciliation (task-owned-money Phase 5, Task 1: schema +
reconciliation core — spec §7 rules 1 and 3).

Covers:
- PurchaseOrderService.reconcile(): happy path, re-reconcile overwrite,
  reconcile-before-issue rejection, per-line final_price validation
  (must belong to the PO), appended invoice_only lines.
- invoice_only lines excluded from receiving-completeness logic.
- PurchaseOrderLineItem.clean() task-link validation: top-level required
  (subtask rejected), job-bearing, link optional, multi-job POs allowed.
- PurchaseOrder.objects.awaiting_reconciliation() / is_awaiting_reconciliation
  membership matrix.
"""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError

from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory
from apps.core.services import NotFoundError
from apps.jobs.models import Job, Task
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService, PurchaseOrderReceivingService


class POReconciliationTestBase(TestCase):
    """Shared setUp: a vendor Business + two Jobs (for multi-job link tests)."""
    fixtures = ['unit_test_data.json']

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
        self.top_task = Task.objects.create(job=self.job_a, name='Outsourced work')
        self.sub_task = Task.objects.create(
            job=self.job_a, name='Sub of outsourced work', parent_task=self.top_task,
        )
        self.other_job_task = Task.objects.create(job=self.job_b, name='Other job work')

    def _make_issued_po(self, num_items=1, task=None):
        po = PurchaseOrder.objects.create(
            business=self.business, status=PurchaseOrder.STATUS_ISSUED,
        )
        for i in range(num_items):
            PurchaseOrderLineItem.objects.create(
                purchase_order=po,
                description=f'Item {i + 1}',
                qty=Decimal('2.00'),
                price=Decimal('10.00'),
                accounting_category=self.cat,
                task=task if i == 0 else None,
            )
        return po


class ReconcileHappyPathTest(POReconciliationTestBase):

    def test_reconcile_sets_totals_ref_state_and_date(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        result = PurchaseOrderService.reconcile(
            po.pk,
            bill_total=Decimal('25.00'),
            vendor_invoice_ref='VEND-INV-1',
            line_finals={li.pk: Decimal('12.00')},
        )
        self.assertEqual(result.bill_total, Decimal('25.00'))
        self.assertEqual(result.vendor_invoice_ref, 'VEND-INV-1')
        self.assertTrue(result.reconciled)
        self.assertIsNotNone(result.reconciled_date)
        li.refresh_from_db()
        self.assertEqual(li.final_price, Decimal('12.00'))

    def test_reconcile_does_not_change_po_status(self):
        """Reconciliation is not part of the PO status lifecycle."""
        po = self._make_issued_po()
        PurchaseOrderService.reconcile(po.pk, bill_total=Decimal('20.00'))
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_ISSUED)

    def test_reconcile_line_final_null_means_as_ordered(self):
        """A line never mentioned in line_finals keeps final_price null."""
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        PurchaseOrderService.reconcile(po.pk, bill_total=Decimal('20.00'))
        li.refresh_from_db()
        self.assertIsNone(li.final_price)

    def test_reconcile_not_found_raises(self):
        with self.assertRaises(NotFoundError):
            PurchaseOrderService.reconcile(999999, bill_total=Decimal('1.00'))


class ReconcileReReconcileTest(POReconciliationTestBase):

    def test_re_reconcile_overwrites_po_level_fields(self):
        po = self._make_issued_po()
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('20.00'), vendor_invoice_ref='FIRST',
        )
        first = PurchaseOrder.objects.get(pk=po.pk)
        first_date = first.reconciled_date

        result = PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('30.00'), vendor_invoice_ref='SECOND',
        )
        self.assertEqual(result.bill_total, Decimal('30.00'))
        self.assertEqual(result.vendor_invoice_ref, 'SECOND')
        self.assertTrue(result.reconciled)
        self.assertGreaterEqual(result.reconciled_date, first_date)

    def test_re_reconcile_overwrites_line_final_price(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('20.00'), line_finals={li.pk: Decimal('11.00')},
        )
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('22.00'), line_finals={li.pk: Decimal('13.00')},
        )
        li.refresh_from_db()
        self.assertEqual(li.final_price, Decimal('13.00'))

    def test_re_reconcile_with_smaller_line_finals_reverts_omitted_line(self):
        """REPLACE semantics, not merge: a later reconcile call with a
        smaller line_finals set is the new complete statement of which
        lines carry a final price — an omitted line's final_price reverts
        to None (as ordered), even though a previous call had set it."""
        po = self._make_issued_po(num_items=2)
        li_a, li_b = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('40.00'),
            line_finals={li_a.pk: Decimal('11.00'), li_b.pk: Decimal('9.00')},
        )
        li_a.refresh_from_db()
        li_b.refresh_from_db()
        self.assertEqual(li_a.final_price, Decimal('11.00'))
        self.assertEqual(li_b.final_price, Decimal('9.00'))

        # Second call only mentions li_a — li_b must revert to None.
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('35.00'),
            line_finals={li_a.pk: Decimal('12.00')},
        )
        li_a.refresh_from_db()
        li_b.refresh_from_db()
        self.assertEqual(li_a.final_price, Decimal('12.00'))
        self.assertIsNone(li_b.final_price)

    def test_re_reconcile_with_no_line_finals_clears_all_ordered_lines(self):
        po = self._make_issued_po(num_items=2)
        li_a, li_b = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('40.00'),
            line_finals={li_a.pk: Decimal('11.00'), li_b.pk: Decimal('9.00')},
        )
        PurchaseOrderService.reconcile(po.pk, bill_total=Decimal('20.00'))
        li_a.refresh_from_db()
        li_b.refresh_from_db()
        self.assertIsNone(li_a.final_price)
        self.assertIsNone(li_b.final_price)

    def test_re_reconcile_does_not_auto_clear_untargeted_invoice_only_line(self):
        """invoice_only lines are excluded from the REPLACE-clearing sweep
        — one keeps whatever final_price it has unless a later call
        explicitly targets it in line_finals."""
        po = self._make_issued_po()
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('30.00'),
            appended_lines=[{
                'description': 'Freight', 'qty': Decimal('1.00'),
                'price': Decimal('15.00'), 'accounting_category': self.cat.pk,
            }],
        )
        invoice_only_li = PurchaseOrderLineItem.objects.get(
            purchase_order=po, invoice_only=True,
        )
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('30.00'),
            line_finals={invoice_only_li.pk: Decimal('18.00')},
        )
        invoice_only_li.refresh_from_db()
        self.assertEqual(invoice_only_li.final_price, Decimal('18.00'))

        # A later call that omits it must NOT clear it back to None.
        PurchaseOrderService.reconcile(po.pk, bill_total=Decimal('30.00'))
        invoice_only_li.refresh_from_db()
        self.assertEqual(invoice_only_li.final_price, Decimal('18.00'))


class ReconcileBeforeIssueTest(POReconciliationTestBase):

    def test_reconcile_before_issue_rejected(self):
        po = PurchaseOrder.objects.create(business=self.business)  # draft
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='Item', qty=Decimal('1.00'),
            price=Decimal('5.00'), accounting_category=self.cat,
        )
        self.assertEqual(po.status, PurchaseOrder.STATUS_DRAFT)
        with self.assertRaises(ValidationError):
            PurchaseOrderService.reconcile(po.pk, bill_total=Decimal('5.00'))

    def test_reconcile_allowed_once_issued(self):
        po = self._make_issued_po()
        # Should not raise.
        PurchaseOrderService.reconcile(po.pk, bill_total=Decimal('20.00'))
        po.refresh_from_db()
        self.assertTrue(po.reconciled)

    def test_reconcile_allowed_on_cancelled_po(self):
        """A vendor bill can still land for whatever actually shipped
        before cancellation — reconcile is not gated on PO status beyond
        excluding draft."""
        po = self._make_issued_po()
        PurchaseOrderService.cancel_po(po.pk)
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_CANCELLED)

        result = PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('18.00'), vendor_invoice_ref='CANCELLED-PO-INV',
        )
        self.assertTrue(result.reconciled)
        self.assertEqual(result.bill_total, Decimal('18.00'))
        self.assertEqual(result.status, PurchaseOrder.STATUS_CANCELLED)


class ReconcileLineFinalsValidationTest(POReconciliationTestBase):

    def test_line_final_for_line_on_another_po_rejected(self):
        po1 = self._make_issued_po()
        po2 = self._make_issued_po()
        other_li = PurchaseOrderLineItem.objects.get(purchase_order=po2)
        with self.assertRaises(ValidationError):
            PurchaseOrderService.reconcile(
                po1.pk, bill_total=Decimal('20.00'),
                line_finals={other_li.pk: Decimal('9.00')},
            )

    def test_line_final_for_nonexistent_line_rejected(self):
        po = self._make_issued_po()
        with self.assertRaises(ValidationError):
            PurchaseOrderService.reconcile(
                po.pk, bill_total=Decimal('20.00'),
                line_finals={999999: Decimal('9.00')},
            )

    def test_rejected_line_final_does_not_partially_apply(self):
        """A bad line_finals entry aborts the whole call — no partial writes."""
        po = self._make_issued_po(num_items=2)
        lines = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        good_li, bad_li_other_po = lines[0], PurchaseOrderLineItem.objects.get(
            purchase_order=self._make_issued_po(),
        )
        with self.assertRaises(ValidationError):
            PurchaseOrderService.reconcile(
                po.pk, bill_total=Decimal('20.00'),
                line_finals={
                    good_li.pk: Decimal('9.00'),
                    bad_li_other_po.pk: Decimal('1.00'),
                },
            )
        po.refresh_from_db()
        good_li.refresh_from_db()
        self.assertFalse(po.reconciled)
        self.assertIsNone(good_li.final_price)


class InvoiceOnlyReceivingCompletenessTest(POReconciliationTestBase):

    def test_appended_invoice_only_line_excluded_from_receiving_completeness(self):
        """An invoice_only line appended at reconcile time must never block
        (or knock out of) received_in_full — it was never ordered/received."""
        po = self._make_issued_po()
        ordinary_li = PurchaseOrderLineItem.objects.get(purchase_order=po)

        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('35.00'),
            appended_lines=[{
                'description': 'Freight', 'qty': Decimal('1.00'),
                'price': Decimal('15.00'), 'accounting_category': self.cat.pk,
            }],
        )
        invoice_only_li = PurchaseOrderLineItem.objects.get(
            purchase_order=po, invoice_only=True,
        )
        self.assertEqual(invoice_only_li.qty_received, Decimal('0.00'))

        from apps.core.models import User
        user = User.objects.get(username='admin')
        PurchaseOrderReceivingService.receive_all(po, user)

        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_RECEIVED_IN_FULL)

        ordinary_li.refresh_from_db()
        self.assertEqual(ordinary_li.qty_received, ordinary_li.qty)

        invoice_only_li.refresh_from_db()
        self.assertEqual(invoice_only_li.qty_received, Decimal('0.00'))

    def test_receiving_against_invoice_only_line_rejected(self):
        po = self._make_issued_po()
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('15.00'),
            appended_lines=[{
                'description': 'Freight', 'qty': Decimal('1.00'),
                'price': Decimal('15.00'), 'accounting_category': self.cat.pk,
            }],
        )
        invoice_only_li = PurchaseOrderLineItem.objects.get(
            purchase_order=po, invoice_only=True,
        )
        from apps.core.models import User
        user = User.objects.get(username='admin')
        with self.assertRaises(ValidationError):
            PurchaseOrderReceivingService.receive_items(
                po, [{'line_item_id': invoice_only_li.pk, 'qty_received': 1}], user,
            )

    def test_appended_invoice_only_line_does_not_revert_status_on_recompute(self):
        """Direct exercise of the internal status recompute: an unreceived
        invoice_only line must not pull a received_in_full PO back down."""
        po = self._make_issued_po()
        ordinary_li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        from apps.core.models import User
        user = User.objects.get(username='admin')
        PurchaseOrderReceivingService.receive_items(
            po, [{'line_item_id': ordinary_li.pk, 'qty_received': 2}], user,
        )
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_RECEIVED_IN_FULL)

        PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='Freight', qty=Decimal('1.00'),
            price=Decimal('15.00'), accounting_category=self.cat,
            invoice_only=True,
        )
        PurchaseOrderReceivingService._update_po_status(po)
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_RECEIVED_IN_FULL)


class TaskLinkValidationTest(POReconciliationTestBase):

    def test_link_top_level_job_bearing_task_ok(self):
        po = PurchaseOrder.objects.create(business=self.business)  # draft
        li = PurchaseOrderService.add_line_item(
            po.pk, description='Outsourced', qty=Decimal('1.00'),
            price=Decimal('50.00'), accounting_category=self.cat.pk,
            task=self.top_task.pk,
        )
        self.assertEqual(li.task_id, self.top_task.pk)

    def test_link_subtask_rejected_on_create(self):
        po = PurchaseOrder.objects.create(business=self.business)  # draft
        with self.assertRaises(ValidationError):
            PurchaseOrderService.add_line_item(
                po.pk, description='Outsourced', qty=Decimal('1.00'),
                price=Decimal('50.00'), accounting_category=self.cat.pk,
                task=self.sub_task.pk,
            )

    def test_link_subtask_rejected_on_update(self):
        po = PurchaseOrder.objects.create(business=self.business)  # draft
        li = PurchaseOrderService.add_line_item(
            po.pk, description='Outsourced', qty=Decimal('1.00'),
            price=Decimal('50.00'), accounting_category=self.cat.pk,
        )
        with self.assertRaises(ValidationError):
            PurchaseOrderService.update_line_item(li.pk, task=self.sub_task.pk)

    def test_task_link_is_optional(self):
        po = PurchaseOrder.objects.create(business=self.business)  # draft
        li = PurchaseOrderService.add_line_item(
            po.pk, description='Material only', qty=Decimal('1.00'),
            price=Decimal('50.00'), accounting_category=self.cat.pk,
        )
        self.assertIsNone(li.task_id)

    def test_single_po_can_link_tasks_from_different_jobs(self):
        """PO lines may serve multiple jobs via different tasks (spec §7 rule 1)."""
        po = PurchaseOrder.objects.create(business=self.business)  # draft
        li_a = PurchaseOrderService.add_line_item(
            po.pk, description='For job A', qty=Decimal('1.00'),
            price=Decimal('50.00'), accounting_category=self.cat.pk,
            task=self.top_task.pk,
        )
        li_b = PurchaseOrderService.add_line_item(
            po.pk, description='For job B', qty=Decimal('1.00'),
            price=Decimal('50.00'), accounting_category=self.cat.pk,
            task=self.other_job_task.pk,
        )
        self.assertEqual(li_a.task.job_id, self.job_a.pk)
        self.assertEqual(li_b.task.job_id, self.job_b.pk)

    def test_appended_reconcile_line_task_link_validated(self):
        po = self._make_issued_po()
        with self.assertRaises(ValidationError):
            PurchaseOrderService.reconcile(
                po.pk, bill_total=Decimal('10.00'),
                appended_lines=[{
                    'description': 'Bad link', 'qty': Decimal('1.00'),
                    'price': Decimal('5.00'), 'accounting_category': self.cat.pk,
                    'task': self.sub_task.pk,
                }],
            )
        self.assertFalse(
            PurchaseOrderLineItem.objects.filter(
                purchase_order=po, description='Bad link',
            ).exists()
        )

    def test_appended_reconcile_line_top_level_task_ok(self):
        po = self._make_issued_po()
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('10.00'),
            appended_lines=[{
                'description': 'Outsourced extra', 'qty': Decimal('1.00'),
                'price': Decimal('5.00'), 'accounting_category': self.cat.pk,
                'task': self.top_task.pk,
            }],
        )
        li = PurchaseOrderLineItem.objects.get(
            purchase_order=po, description='Outsourced extra',
        )
        self.assertTrue(li.invoice_only)
        self.assertEqual(li.task_id, self.top_task.pk)


class AwaitingReconciliationMembershipTest(POReconciliationTestBase):

    def test_draft_po_not_awaiting(self):
        po = PurchaseOrder.objects.create(business=self.business)
        self.assertFalse(po.is_awaiting_reconciliation)
        self.assertNotIn(po, PurchaseOrder.objects.awaiting_reconciliation())

    def test_issued_not_received_not_awaiting(self):
        po = self._make_issued_po()
        self.assertFalse(po.is_awaiting_reconciliation)
        self.assertNotIn(po, PurchaseOrder.objects.awaiting_reconciliation())

    def test_partly_received_not_awaiting(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        from apps.core.models import User
        user = User.objects.get(username='admin')
        PurchaseOrderReceivingService.receive_items(
            po, [{'line_item_id': li.pk, 'qty_received': 1}], user,
        )
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_PARTLY_RECEIVED)
        self.assertFalse(po.is_awaiting_reconciliation)
        self.assertNotIn(po, PurchaseOrder.objects.awaiting_reconciliation())

    def test_received_in_full_unreconciled_is_awaiting(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        from apps.core.models import User
        user = User.objects.get(username='admin')
        PurchaseOrderReceivingService.receive_all(po, user)
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_RECEIVED_IN_FULL)
        self.assertTrue(po.is_awaiting_reconciliation)
        self.assertIn(po, PurchaseOrder.objects.awaiting_reconciliation())

    def test_received_in_full_reconciled_not_awaiting(self):
        po = self._make_issued_po()
        from apps.core.models import User
        user = User.objects.get(username='admin')
        PurchaseOrderReceivingService.receive_all(po, user)
        PurchaseOrderService.reconcile(po.pk, bill_total=Decimal('20.00'))
        po.refresh_from_db()
        self.assertFalse(po.is_awaiting_reconciliation)
        self.assertNotIn(po, PurchaseOrder.objects.awaiting_reconciliation())

    def test_cancelled_not_awaiting(self):
        po = self._make_issued_po()
        PurchaseOrderService.cancel_po(po.pk)
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_CANCELLED)
        self.assertFalse(po.is_awaiting_reconciliation)
        self.assertNotIn(po, PurchaseOrder.objects.awaiting_reconciliation())

    def test_reconcile_reactivates_awaiting_state_when_unreconciled_again(self):
        """Re-reconcile is not an 'unreconcile' path (none exists in Phase 5
        Task 1) — reconciled stays True once set, so the PO does not return
        to awaiting_reconciliation on a second reconcile call."""
        po = self._make_issued_po()
        from apps.core.models import User
        user = User.objects.get(username='admin')
        PurchaseOrderReceivingService.receive_all(po, user)
        PurchaseOrderService.reconcile(po.pk, bill_total=Decimal('20.00'))
        PurchaseOrderService.reconcile(po.pk, bill_total=Decimal('25.00'))
        po.refresh_from_db()
        self.assertTrue(po.reconciled)
        self.assertFalse(po.is_awaiting_reconciliation)
