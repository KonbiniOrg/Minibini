"""Tests for PO reconciliation (task-owned-money Phase 5, outsourced-work
port).

Task 1 (model layer, schema): fields, awaiting_reconciliation() membership
matrix, po_total/ordered_total/variance math, PurchaseOrderLineItem.clean()
task-link guard.

Task 2 (this addition — service layer): `PurchaseOrderService.reconcile()`
(happy path, re-reconcile overwrite/REPLACE semantics, pre-issue rejection,
line_finals ownership validation, appended_lines append-only mirror +
whitelist, malformed-input coercion), receiving-flow invoice_only exclusions
(`_update_po_status`, `receive_all`, direct-receive rejection,
`cancel_line_item` rejection), `PurchaseOrderService._default_markup_percent`,
and the `add_line_item` invoice_only-smuggling guard (spec ruling 4).

NOTE: per the outsourced-work port ruling, Task.parent_task is dormant on
this branch (no code may read/write it) — the fees-era top-level/subtask
branch of the task-link check, and all of fees' subtask test cases
(including the appended-lines subtask-rejection case), are deliberately NOT
ported. `PurchaseOrderService.compute_rate_prompts` and its tests are Task 3
scope (API surface) and are not ported here.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, User
from apps.core.services import NotFoundError
from apps.jobs.models import Job, Task
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService, PurchaseOrderReceivingService


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
        self.worker = User.objects.create(username='worker')

    def _make_line(self, po, **kwargs):
        defaults = dict(
            purchase_order=po, description='Item',
            qty=Decimal('2.00'), price=Decimal('10.00'),
            accounting_category=self.cat,
        )
        defaults.update(kwargs)
        return PurchaseOrderLineItem.objects.create(**defaults)

    def _make_issued_po(self, num_items=1, task=None):
        """An ISSUED PO with `num_items` ordinary lines (task attributed to
        the first line only, mirroring fees' helper). Created directly with
        status=ISSUED (new instance — PurchaseOrder.clean()'s
        line-item-count/transition checks only run on updates, not create,
        so this is safe with zero lines at creation time)."""
        po = PurchaseOrder.objects.create(
            business=self.business, status=PurchaseOrder.STATUS_ISSUED,
        )
        for i in range(num_items):
            self._make_line(
                po, description=f'Item {i + 1}',
                task=task if i == 0 else None,
            )
        return po


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
        """invoice_only lines are excluded from the line_finals
        REPLACE-clearing sweep — one keeps whatever final_price it has
        unless a later call explicitly targets it in line_finals.

        NOTE: a *separate* mechanism — the `appended_lines` append-only
        mirror — deletes an invoice_only line outright if a later call
        doesn't re-send its id in `appended_lines` at all (see
        AppendedLinesCarryNoteTest). To isolate the line_finals-only
        behavior this test is about, every call below re-sends the line via
        `appended_lines` so it survives for reasons unrelated to
        line_finals."""
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
        keep_alive = {
            'line_item_id': invoice_only_li.pk, 'description': 'Freight',
            'qty': Decimal('1.00'), 'price': Decimal('15.00'),
            'accounting_category': self.cat.pk,
        }
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('30.00'),
            line_finals={invoice_only_li.pk: Decimal('18.00')},
            appended_lines=[keep_alive],
        )
        invoice_only_li.refresh_from_db()
        self.assertEqual(invoice_only_li.final_price, Decimal('18.00'))

        # A later call that re-sends it (keeping it alive) but omits it
        # from line_finals must NOT clear its final_price back to None.
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('30.00'), appended_lines=[keep_alive],
        )
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


class ReconcileInputCoercionTest(POReconciliationTestBase):
    """Malformed vendor-bill input (non-numeric bill_total/line_finals
    values, non-integer appended-line ids) is arbitrary caller input, not a
    programming error — it must raise a field-shaped ValidationError, never
    500 on a bare Decimal()/int() conversion. (Not present as a distinct
    test class in fees' test_po_reconciliation.py — the coercion code is
    ported from fees' services.py verbatim, but its own unit coverage there
    lives only at the API layer, which is Task 3 scope. Added here so the
    ported coercion branch has direct service-level coverage.)"""

    def test_non_numeric_bill_total_rejected(self):
        po = self._make_issued_po()
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.reconcile(po.pk, bill_total='not-a-number')
        self.assertIn('bill_total', ctx.exception.message_dict)

    def test_non_numeric_line_final_value_rejected(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.reconcile(
                po.pk, bill_total=Decimal('10.00'),
                line_finals={li.pk: 'garbage'},
            )
        self.assertIn('line_finals', ctx.exception.message_dict)

    def test_non_integer_appended_line_item_id_rejected(self):
        po = self._make_issued_po()
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.reconcile(
                po.pk, bill_total=Decimal('10.00'),
                appended_lines=[{
                    'line_item_id': 'garbage', 'description': 'Freight',
                    'qty': Decimal('1.00'), 'price': Decimal('5.00'),
                    'accounting_category': self.cat.pk,
                }],
            )
        self.assertIn('appended_lines', ctx.exception.message_dict)


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

        PurchaseOrderReceivingService.receive_all(po, self.worker)

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
        with self.assertRaises(ValidationError):
            PurchaseOrderReceivingService.receive_items(
                po, [{'line_item_id': invoice_only_li.pk, 'qty_received': 1}], self.worker,
            )

    def test_appended_invoice_only_line_does_not_revert_status_on_recompute(self):
        """Direct exercise of the internal status recompute: an unreceived
        invoice_only line must not pull a received_in_full PO back down."""
        po = self._make_issued_po()
        ordinary_li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        PurchaseOrderReceivingService.receive_items(
            po, [{'line_item_id': ordinary_li.pk, 'qty_received': 2}], self.worker,
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


class AppendedLineTaskLinkValidationTest(POReconciliationTestBase):
    """The appended-lines path routes every write through
    PurchaseOrderLineItem.full_clean(), so the job-bearing task-link guard
    (Task 1's clean()) applies to reconcile-appended lines too. Only the
    positive case is exercised here — the negative case (a task without a
    job) is already covered at the model level in
    TaskLinkValidationTest.test_link_to_task_without_job_rejected; the
    fees-era subtask-rejection twin of this test is dropped per the
    excision rule."""

    def test_appended_reconcile_line_job_bearing_task_ok(self):
        po = self._make_issued_po()
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('10.00'),
            appended_lines=[{
                'description': 'Outsourced extra', 'qty': Decimal('1.00'),
                'price': Decimal('5.00'), 'accounting_category': self.cat.pk,
                'task': self.task_a.pk,
            }],
        )
        li = PurchaseOrderLineItem.objects.get(
            purchase_order=po, description='Outsourced extra',
        )
        self.assertTrue(li.invoice_only)
        self.assertEqual(li.task_id, self.task_a.pk)


class AwaitingReconciliationServiceFlowTest(POReconciliationTestBase):
    """Same membership rule as the model-level
    AwaitingReconciliationMembershipTest, but exercised end-to-end through
    the actual receiving/reconcile services rather than by setting `status`
    /`reconciled` directly — proves the wiring, not just the property."""

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
        PurchaseOrderReceivingService.receive_items(
            po, [{'line_item_id': li.pk, 'qty_received': 1}], self.worker,
        )
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_PARTLY_RECEIVED)
        self.assertFalse(po.is_awaiting_reconciliation)
        self.assertNotIn(po, PurchaseOrder.objects.awaiting_reconciliation())

    def test_received_in_full_unreconciled_is_awaiting(self):
        po = self._make_issued_po()
        PurchaseOrderReceivingService.receive_all(po, self.worker)
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_RECEIVED_IN_FULL)
        self.assertTrue(po.is_awaiting_reconciliation)
        self.assertIn(po, PurchaseOrder.objects.awaiting_reconciliation())

    def test_received_in_full_reconciled_not_awaiting(self):
        po = self._make_issued_po()
        PurchaseOrderReceivingService.receive_all(po, self.worker)
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

    def test_reconcile_does_not_reactivate_awaiting_state(self):
        """Re-reconcile is not an 'unreconcile' path — reconciled stays True
        once set, so the PO does not return to awaiting_reconciliation on a
        second reconcile call."""
        po = self._make_issued_po()
        PurchaseOrderReceivingService.receive_all(po, self.worker)
        PurchaseOrderService.reconcile(po.pk, bill_total=Decimal('20.00'))
        PurchaseOrderService.reconcile(po.pk, bill_total=Decimal('25.00'))
        po.refresh_from_db()
        self.assertTrue(po.reconciled)
        self.assertFalse(po.is_awaiting_reconciliation)


class AppendedLinesCarryNoteTest(POReconciliationTestBase):
    """`appended_lines` is an append-only MIRROR of the bill's invoice_only
    detail, not additive: a re-reconcile that drops a previously-appended
    line deletes it; re-sending a line's id updates it in place; omitting an
    id creates a new line. Covers drop/replace/keep."""

    def test_omitted_appended_line_is_dropped(self):
        po = self._make_issued_po()
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('30.00'),
            appended_lines=[{
                'description': 'Freight', 'qty': Decimal('1.00'),
                'price': Decimal('15.00'), 'accounting_category': self.cat.pk,
            }],
        )
        freight = PurchaseOrderLineItem.objects.get(purchase_order=po, invoice_only=True)

        # Second reconcile omits it entirely.
        PurchaseOrderService.reconcile(po.pk, bill_total=Decimal('20.00'))

        self.assertFalse(
            PurchaseOrderLineItem.objects.filter(pk=freight.pk).exists()
        )
        self.assertFalse(
            PurchaseOrderLineItem.objects.filter(purchase_order=po, invoice_only=True).exists()
        )

    def test_omitted_appended_line_delete_renumbers_survivors(self):
        """Dropped invoice_only lines go through LineItemService.delete_line_item_with_renumber
        (repo law) — surviving lines' line_number stays contiguous."""
        po = self._make_issued_po(num_items=1)
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('45.00'),
            appended_lines=[
                {'description': 'Freight', 'qty': Decimal('1.00'),
                 'price': Decimal('15.00'), 'accounting_category': self.cat.pk},
                {'description': 'Tax', 'qty': Decimal('1.00'),
                 'price': Decimal('5.00'), 'accounting_category': self.cat.pk},
            ],
        )
        freight = PurchaseOrderLineItem.objects.get(purchase_order=po, description='Freight')
        tax = PurchaseOrderLineItem.objects.get(purchase_order=po, description='Tax')

        # Drop Freight (first-appended), keep Tax.
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('30.00'),
            appended_lines=[{'line_item_id': tax.pk, 'description': 'Tax',
                              'qty': Decimal('1.00'), 'price': Decimal('5.00'),
                              'accounting_category': self.cat.pk}],
        )
        self.assertFalse(PurchaseOrderLineItem.objects.filter(pk=freight.pk).exists())
        remaining_numbers = sorted(
            PurchaseOrderLineItem.objects.filter(purchase_order=po)
            .values_list('line_number', flat=True)
        )
        self.assertEqual(remaining_numbers, list(range(1, len(remaining_numbers) + 1)))

    def test_resent_appended_line_id_updates_in_place(self):
        po = self._make_issued_po()
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('30.00'),
            appended_lines=[{
                'description': 'Freight', 'qty': Decimal('1.00'),
                'price': Decimal('15.00'), 'accounting_category': self.cat.pk,
            }],
        )
        freight = PurchaseOrderLineItem.objects.get(purchase_order=po, invoice_only=True)

        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('40.00'),
            appended_lines=[{
                'line_item_id': freight.pk, 'description': 'Freight (corrected)',
                'qty': Decimal('1.00'), 'price': Decimal('25.00'),
                'accounting_category': self.cat.pk,
            }],
        )
        freight.refresh_from_db()
        self.assertEqual(freight.description, 'Freight (corrected)')
        self.assertEqual(freight.price, Decimal('25.00'))
        # Same row — not deleted and recreated.
        self.assertEqual(
            PurchaseOrderLineItem.objects.filter(purchase_order=po, invoice_only=True).count(),
            1,
        )

    def test_kept_and_new_appended_lines_together(self):
        po = self._make_issued_po()
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('30.00'),
            appended_lines=[{
                'description': 'Freight', 'qty': Decimal('1.00'),
                'price': Decimal('15.00'), 'accounting_category': self.cat.pk,
            }],
        )
        freight = PurchaseOrderLineItem.objects.get(purchase_order=po, invoice_only=True)

        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('50.00'),
            appended_lines=[
                {'line_item_id': freight.pk, 'description': 'Freight',
                 'qty': Decimal('1.00'), 'price': Decimal('15.00'),
                 'accounting_category': self.cat.pk},
                {'description': 'Handling', 'qty': Decimal('1.00'),
                 'price': Decimal('5.00'), 'accounting_category': self.cat.pk},
            ],
        )
        invoice_only_descriptions = set(
            PurchaseOrderLineItem.objects.filter(purchase_order=po, invoice_only=True)
            .values_list('description', flat=True)
        )
        self.assertEqual(invoice_only_descriptions, {'Freight', 'Handling'})

    def test_appended_line_id_from_another_po_rejected(self):
        po = self._make_issued_po()
        other_po = self._make_issued_po()
        PurchaseOrderService.reconcile(
            other_po.pk, bill_total=Decimal('10.00'),
            appended_lines=[{
                'description': 'Freight', 'qty': Decimal('1.00'),
                'price': Decimal('5.00'), 'accounting_category': self.cat.pk,
            }],
        )
        other_freight = PurchaseOrderLineItem.objects.get(
            purchase_order=other_po, invoice_only=True,
        )
        with self.assertRaises(ValidationError):
            PurchaseOrderService.reconcile(
                po.pk, bill_total=Decimal('20.00'),
                appended_lines=[{
                    'line_item_id': other_freight.pk, 'description': 'Freight',
                    'qty': Decimal('1.00'), 'price': Decimal('5.00'),
                    'accounting_category': self.cat.pk,
                }],
            )

    def test_appended_line_id_referencing_ordinary_line_rejected(self):
        """An id in appended_lines must reference an existing invoice_only
        line — an ordinary (ordered) line's id is not a valid target."""
        po = self._make_issued_po()
        ordinary_li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        with self.assertRaises(ValidationError):
            PurchaseOrderService.reconcile(
                po.pk, bill_total=Decimal('20.00'),
                appended_lines=[{
                    'line_item_id': ordinary_li.pk, 'description': 'Not invoice-only',
                    'qty': Decimal('1.00'), 'price': Decimal('5.00'),
                    'accounting_category': self.cat.pk,
                }],
            )


class AppendedLinesWhitelistTest(POReconciliationTestBase):
    """`appended_lines` entries are restricted to the fields
    `add_line_item` itself accepts — a caller cannot smuggle
    receiving-state fields (qty_received, line_number, received_by, ...) or
    an explicit `invoice_only` through a reconcile call. `invoice_only` is
    always set server-side."""

    def test_smuggled_qty_received_rejected(self):
        po = self._make_issued_po()
        with self.assertRaises(ValidationError):
            PurchaseOrderService.reconcile(
                po.pk, bill_total=Decimal('20.00'),
                appended_lines=[{
                    'description': 'Freight', 'qty': Decimal('1.00'),
                    'price': Decimal('15.00'), 'accounting_category': self.cat.pk,
                    'qty_received': Decimal('1.00'),
                }],
            )
        self.assertFalse(
            PurchaseOrderLineItem.objects.filter(
                purchase_order=po, description='Freight',
            ).exists()
        )

    def test_smuggled_line_number_rejected(self):
        po = self._make_issued_po()
        with self.assertRaises(ValidationError):
            PurchaseOrderService.reconcile(
                po.pk, bill_total=Decimal('20.00'),
                appended_lines=[{
                    'description': 'Freight', 'qty': Decimal('1.00'),
                    'price': Decimal('15.00'), 'accounting_category': self.cat.pk,
                    'line_number': 99,
                }],
            )

    def test_smuggled_invoice_only_false_rejected(self):
        """invoice_only is always set server-side — an explicit value
        (even a no-op True, or an attempted False) in the payload is
        rejected like any other unknown field."""
        po = self._make_issued_po()
        with self.assertRaises(ValidationError):
            PurchaseOrderService.reconcile(
                po.pk, bill_total=Decimal('20.00'),
                appended_lines=[{
                    'description': 'Freight', 'qty': Decimal('1.00'),
                    'price': Decimal('15.00'), 'accounting_category': self.cat.pk,
                    'invoice_only': False,
                }],
            )

    def test_allowed_fields_still_accepted(self):
        """Whitelisted fields (including optional task link) still work."""
        po = self._make_issued_po()
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('20.00'),
            appended_lines=[{
                'description': 'Outsourced extra', 'qty': Decimal('1.00'),
                'units': 'ea', 'price': Decimal('15.00'),
                'accounting_category': self.cat.pk, 'task': self.task_a.pk,
            }],
        )
        li = PurchaseOrderLineItem.objects.get(
            purchase_order=po, description='Outsourced extra',
        )
        self.assertTrue(li.invoice_only)
        self.assertEqual(li.task_id, self.task_a.pk)


class CancelLineItemInvoiceOnlyGuardTest(POReconciliationTestBase):
    """PurchaseOrderReceivingService.cancel_line_item must reject an
    invoice_only line — it was never ordered/received, so "cancel the
    remaining quantity" is meaningless for it."""

    def test_cancel_invoice_only_line_rejected(self):
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
        with self.assertRaises(ValidationError):
            PurchaseOrderReceivingService.cancel_line_item(po, invoice_only_li.pk)
        invoice_only_li.refresh_from_db()
        self.assertEqual(invoice_only_li.qty_cancelled, Decimal('0.00'))

    def test_cancel_ordinary_line_still_works(self):
        po = self._make_issued_po()
        ordinary_li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        PurchaseOrderReceivingService.cancel_line_item(po, ordinary_li.pk)
        ordinary_li.refresh_from_db()
        self.assertEqual(ordinary_li.qty_cancelled, ordinary_li.qty)


class DefaultMarkupPercentTest(POReconciliationTestBase):
    """PurchaseOrderService._default_markup_percent() — Configuration
    lookup used by Task 3's compute_rate_prompts (not ported here). Returns
    (percent: Decimal|None, found: bool); (None, False) whenever the config
    row is missing or unparseable, never a bare 500."""

    def test_missing_config_returns_none_and_false(self):
        from apps.core.models import Configuration
        Configuration.objects.filter(key='default_material_markup_percent').delete()
        percent, found = PurchaseOrderService._default_markup_percent()
        self.assertIsNone(percent)
        self.assertFalse(found)

    def test_present_config_returns_decimal_and_true(self):
        from apps.core.models import Configuration
        Configuration.objects.update_or_create(
            key='default_material_markup_percent', defaults={'value': '35'},
        )
        percent, found = PurchaseOrderService._default_markup_percent()
        self.assertEqual(percent, Decimal('35'))
        self.assertTrue(found)

    def test_unparseable_config_returns_none_and_false(self):
        from apps.core.models import Configuration
        Configuration.objects.update_or_create(
            key='default_material_markup_percent', defaults={'value': 'not-a-number'},
        )
        percent, found = PurchaseOrderService._default_markup_percent()
        self.assertIsNone(percent)
        self.assertFalse(found)


class AddLineItemInvoiceOnlyGuardTest(POReconciliationTestBase):
    """Spec ruling 4 / fees' LATER item 3: the ordinary manual line-create
    path (`PurchaseOrderService.add_line_item`, the service behind
    `POST /api/purchase-orders/{id}/line-items/`) must refuse a
    caller-supplied `invoice_only` — that field is reconciliation-owned and
    is only ever set server-side by `reconcile()`'s appended_lines path.
    Without this guard a caller could POST `invoice_only: true` directly on
    an ordinary manual line, bypassing the receiving/reconcile machinery
    entirely."""

    def test_add_line_item_rejects_invoice_only_true(self):
        po = PurchaseOrder.objects.create(business=self.business)  # draft
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.add_line_item(
                po.pk, description='Sneaky', qty=Decimal('1.00'),
                price=Decimal('5.00'), accounting_category=self.cat.pk,
                invoice_only=True,
            )
        self.assertIn('invoice_only', ctx.exception.message_dict)
        self.assertFalse(
            PurchaseOrderLineItem.objects.filter(purchase_order=po).exists()
        )

    def test_add_line_item_rejects_invoice_only_false(self):
        """Rejected outright like any other unexpected field — even a
        no-op `False` is refused, matching the appended_lines whitelist's
        stance (AppendedLinesWhitelistTest.test_smuggled_invoice_only_false_rejected)."""
        po = PurchaseOrder.objects.create(business=self.business)  # draft
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.add_line_item(
                po.pk, description='Sneaky', qty=Decimal('1.00'),
                price=Decimal('5.00'), accounting_category=self.cat.pk,
                invoice_only=False,
            )
        self.assertIn('invoice_only', ctx.exception.message_dict)

    def test_add_line_item_without_invoice_only_still_works(self):
        po = PurchaseOrder.objects.create(business=self.business)  # draft
        li = PurchaseOrderService.add_line_item(
            po.pk, description='Ordinary', qty=Decimal('1.00'),
            price=Decimal('5.00'), accounting_category=self.cat.pk,
        )
        self.assertFalse(li.invoice_only)

    def test_add_line_item_rejects_final_price(self):
        """final_price is reconciliation-owned too (spec ruling 4 /
        final-review item 2) — a manual line-create must not be able to
        pre-seed it, matching the invoice_only guard's stance."""
        po = PurchaseOrder.objects.create(business=self.business)  # draft
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.add_line_item(
                po.pk, description='Sneaky', qty=Decimal('1.00'),
                price=Decimal('5.00'), accounting_category=self.cat.pk,
                final_price=Decimal('4.00'),
            )
        self.assertIn('final_price', ctx.exception.message_dict)
        self.assertFalse(
            PurchaseOrderLineItem.objects.filter(purchase_order=po).exists()
        )


class UpdateLineItemGuardTest(POReconciliationTestBase):
    """Final-review item 1: `PurchaseOrderService.update_line_item` is the
    service behind the line-item PATCH endpoint
    (`apps/api/purchasing/views.py::line_item_detail`), which passes raw
    `request.data` straight through — the serializer's read-only
    declaration on `invoice_only`/`final_price` never applies because the
    view bypasses serializer validation entirely on write. Both fields are
    reconciliation-owned (set only by `reconcile()`), so the guard has to
    live in the service, mirroring `add_line_item`'s existing guard."""

    def test_update_line_item_rejects_invoice_only(self):
        po = PurchaseOrder.objects.create(business=self.business)  # draft
        li = self._make_line(po)
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.update_line_item(li.pk, invoice_only=True)
        self.assertIn('invoice_only', ctx.exception.message_dict)
        li.refresh_from_db()
        self.assertFalse(li.invoice_only)

    def test_update_line_item_rejects_final_price(self):
        po = PurchaseOrder.objects.create(business=self.business)  # draft
        li = self._make_line(po)
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.update_line_item(li.pk, final_price=Decimal('4.00'))
        self.assertIn('final_price', ctx.exception.message_dict)
        li.refresh_from_db()
        self.assertIsNone(li.final_price)

    def test_update_line_item_without_reconciliation_fields_still_works(self):
        po = PurchaseOrder.objects.create(business=self.business)  # draft
        li = self._make_line(po)
        updated = PurchaseOrderService.update_line_item(
            li.pk, description='Renamed', price=Decimal('12.34'),
        )
        self.assertEqual(updated.description, 'Renamed')
        self.assertEqual(updated.price, Decimal('12.34'))


class RatePromptsTest(POReconciliationTestBase):
    """PurchaseOrderService.compute_rate_prompts (spec §7 rule 4,
    task-owned-money Phase 5 / outsourced-work port Task 3).

    Re-shape (spec ruling 2, differs from fees): `current_rate` is
    `task.effective_rate()` (modifiers-aware), not raw `task.rate`, and
    each prompt carries a new `has_active_modifiers` key.
    """

    def _mark_invoiced(self, task):
        from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
        inv = Invoice.objects.create(job=task.job, status=Invoice.STATUS_DRAFT)
        li = InvoiceLineItem.objects.create(
            invoice=inv, description='x', qty=Decimal('1'),
            units='none', price=Decimal('5.00'),
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=li, source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=task.pk,
        )

    def setUp(self):
        super().setUp()
        self.task_a.rate = Decimal('100.00')
        self.task_a.save()

    def test_no_prompt_when_no_final_price(self):
        po = self._make_issued_po(task=self.task_a)
        PurchaseOrderService.reconcile(po.pk, bill_total=Decimal('20.00'))
        prompts, _ = PurchaseOrderService.compute_rate_prompts(po)
        self.assertEqual(prompts, [])

    def test_no_prompt_when_task_already_invoiced(self):
        po = self._make_issued_po(task=self.task_a)
        li = PurchaseOrderLineItem.objects.get(purchase_order=po, task=self.task_a)
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('20.00'), line_finals={li.pk: Decimal('18.00')},
        )
        self._mark_invoiced(self.task_a)
        prompts, _ = PurchaseOrderService.compute_rate_prompts(po)
        self.assertEqual(prompts, [])

    def test_prompt_for_clean_final_on_uninvoiced_task(self):
        po = self._make_issued_po(task=self.task_a)
        li = PurchaseOrderLineItem.objects.get(purchase_order=po, task=self.task_a)
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('20.00'), line_finals={li.pk: Decimal('18.00')},
        )
        prompts, markup_applied = PurchaseOrderService.compute_rate_prompts(po)
        self.assertEqual(len(prompts), 1)
        prompt = prompts[0]
        self.assertEqual(prompt['task_id'], self.task_a.pk)
        self.assertEqual(prompt['task_name'], self.task_a.name)
        # No `default_material_markup_percent` Configuration row in this
        # (non-fixture) test — markup_applied is False and the suggestion
        # is the bare final_price.
        self.assertEqual(prompt['current_rate'], Decimal('100.00'))
        self.assertFalse(markup_applied)
        self.assertEqual(prompt['suggested_rate'], Decimal('18.00'))
        self.assertFalse(prompt['has_active_modifiers'])

    def test_markup_applied_flag_matches_configuration_presence(self):
        from apps.core.models import Configuration
        po = self._make_issued_po(task=self.task_a)
        li = PurchaseOrderLineItem.objects.get(purchase_order=po, task=self.task_a)
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('20.00'), line_finals={li.pk: Decimal('18.00')},
        )
        Configuration.objects.update_or_create(
            key='default_material_markup_percent', defaults={'value': '50'},
        )
        prompts, markup_applied = PurchaseOrderService.compute_rate_prompts(po)
        self.assertTrue(markup_applied)
        self.assertEqual(prompts[0]['suggested_rate'], Decimal('27.00'))

        Configuration.objects.filter(key='default_material_markup_percent').delete()
        prompts, markup_applied = PurchaseOrderService.compute_rate_prompts(po)
        self.assertFalse(markup_applied)
        self.assertEqual(prompts[0]['suggested_rate'], Decimal('18.00'))

    def test_no_prompt_without_task_link(self):
        po = self._make_issued_po()  # no task
        li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('20.00'), line_finals={li.pk: Decimal('18.00')},
        )
        prompts, _ = PurchaseOrderService.compute_rate_prompts(po)
        self.assertEqual(prompts, [])

    def test_current_rate_reflects_active_modifiers_not_raw_rate(self):
        """The outsourced-work port re-shape: `current_rate` must be
        `task.effective_rate()`, not `task.rate` — a task with an active
        modifier shows the modifier-adjusted rate, and `has_active_modifiers`
        is true."""
        self.task_a.active_modifiers = [
            {'key': 'rush', 'label': 'Rush', 'percent': 50},
        ]
        self.task_a.save()
        po = self._make_issued_po(task=self.task_a)
        li = PurchaseOrderLineItem.objects.get(purchase_order=po, task=self.task_a)
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('20.00'), line_finals={li.pk: Decimal('18.00')},
        )
        prompts, _ = PurchaseOrderService.compute_rate_prompts(po)
        self.assertEqual(len(prompts), 1)
        # effective_rate = 100.00 * 1.50 = 150.00, NOT the raw rate (100.00)
        self.assertEqual(prompts[0]['current_rate'], Decimal('150.00'))
        self.assertTrue(prompts[0]['has_active_modifiers'])

    def test_modifier_less_task_matches_fees_behavior(self):
        """No active_modifiers: effective_rate() equals the raw rate, so
        this case is indistinguishable from fees' `task.rate` reading."""
        po = self._make_issued_po(task=self.task_a)
        li = PurchaseOrderLineItem.objects.get(purchase_order=po, task=self.task_a)
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('20.00'), line_finals={li.pk: Decimal('18.00')},
        )
        prompts, _ = PurchaseOrderService.compute_rate_prompts(po)
        self.assertEqual(prompts[0]['current_rate'], self.task_a.rate)
        self.assertFalse(prompts[0]['has_active_modifiers'])

    def test_prompt_still_offered_for_cancelled_task(self):
        """RM ruling 2026-09-21: a cancelled task's recorded actuals stay
        billable (terminal, not complete, is the billability line), so its
        rate stays meaningful — compute_rate_prompts does NOT skip it. The
        natural filter is already the flow: a prompt only exists when the
        line got a final_price, i.e. the vendor actually billed it."""
        po = self._make_issued_po(task=self.task_a)
        li = PurchaseOrderLineItem.objects.get(purchase_order=po, task=self.task_a)
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('20.00'), line_finals={li.pk: Decimal('18.00')},
        )
        self.task_a.status = Task.STATUS_CANCELLED
        self.task_a.save(update_fields=['status'])
        prompts, _ = PurchaseOrderService.compute_rate_prompts(po)
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0]['task_id'], self.task_a.pk)

    def test_prompt_still_offered_for_complete_task(self):
        """A COMPLETE task is NOT skipped — that is the whole point of the
        RM ruling's carve-out (JobService.update_task allows the resulting
        rate-only PATCH on a complete, uninvoiced, PO-linked task)."""
        po = self._make_issued_po(task=self.task_a)
        li = PurchaseOrderLineItem.objects.get(purchase_order=po, task=self.task_a)
        PurchaseOrderService.reconcile(
            po.pk, bill_total=Decimal('20.00'), line_finals={li.pk: Decimal('18.00')},
        )
        self.task_a.status = Task.STATUS_COMPLETE
        self.task_a.save(update_fields=['status'])
        prompts, _ = PurchaseOrderService.compute_rate_prompts(po)
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0]['task_id'], self.task_a.pk)


class TerminalTaskRateExceptionTest(POReconciliationTestBase):
    """RM ruling 2026-09-21 (resolves LATER.md "rate-prompt Accept fails on
    complete tasks"), tightened same-day: TaskService.update_task's
    terminal freeze gets one narrow exception — a `rate`-only write on a
    TERMINAL (complete OR cancelled) task is permitted when the task is
    not claimed by any invoice, has at least one linked
    PurchaseOrderLineItem, AND the caller holds `can_manage_financials`.
    Cancelled is included because a cancelled task's recorded actuals stay
    billable (terminal, not complete, is the billability line — see
    invoicing-and-expenses.md), so a cancelled outsourced task the vendor
    partially performed and billed has the same legitimate reprice claim
    as a completed one. The financials-only arm is deliberate and
    NARROWER than the ordinary MONEY_FIELDS gate (manager atom OR PM OR
    financials): repricing settled work is a reconciliation act (the
    vendor bill is a financials event) — a job's PM or a plain
    `can_manage_jobs` holder does NOT qualify here, even though either
    could write `rate` on the same task while it was still open.
    Service-layer coverage of the condition itself; the API-level matrix
    in TerminalTaskRateExceptionAPITest (tests/test_api_po_reconciliation.py)
    covers the same arm through the real request/permission stack.
    """

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import Permission
        self.financials_user = User.objects.create_user(
            username='svc_rate_fin', password='x')
        self.financials_user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials'))
        self.financials_user = User.objects.get(pk=self.financials_user.pk)
        self.manager_user = User.objects.create_user(
            username='svc_rate_mgr', password='x')
        self.manager_user.user_permissions.add(
            Permission.objects.get(codename='can_manage_jobs'))
        self.manager_user = User.objects.get(pk=self.manager_user.pk)

    def _mark_invoiced(self, task):
        from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
        inv = Invoice.objects.create(job=task.job, status=Invoice.STATUS_DRAFT)
        li = InvoiceLineItem.objects.create(
            invoice=inv, description='x', qty=Decimal('1'),
            units='none', price=Decimal('5.00'),
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=li, source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=task.pk,
        )

    def test_complete_po_linked_uninvoiced_rate_write_by_financials_succeeds(self):
        from apps.jobs.services import TaskService
        self._make_line(self._make_issued_po(), task=self.task_a)
        self.task_a.status = Task.STATUS_COMPLETE
        self.task_a.save(update_fields=['status'])
        updated = TaskService.update_task(
            self.task_a.pk, user=self.financials_user, rate=Decimal('55.00'))
        self.assertEqual(updated.rate, Decimal('55.00'))

    def test_complete_po_linked_uninvoiced_rate_write_by_manager_only_rejected(self):
        """The exception is financials-only — a plain `can_manage_jobs`
        holder does NOT qualify, even though they could write `rate` on
        this same task while it was still open."""
        from apps.jobs.services import TaskService
        self._make_line(self._make_issued_po(), task=self.task_a)
        self.task_a.status = Task.STATUS_COMPLETE
        self.task_a.save(update_fields=['status'])
        with self.assertRaises(ValidationError) as cm:
            TaskService.update_task(
                self.task_a.pk, user=self.manager_user, rate=Decimal('55.00'))
        self.assertIn('settled', str(cm.exception))

    def test_complete_po_linked_uninvoiced_rate_write_without_user_rejected(self):
        """No actor to check `can_manage_financials` against -- the
        exception fails closed rather than defaulting open."""
        from apps.jobs.services import TaskService
        self._make_line(self._make_issued_po(), task=self.task_a)
        self.task_a.status = Task.STATUS_COMPLETE
        self.task_a.save(update_fields=['status'])
        with self.assertRaises(ValidationError) as cm:
            TaskService.update_task(self.task_a.pk, rate=Decimal('55.00'))
        self.assertIn('settled', str(cm.exception))

    def test_complete_without_po_link_rejected(self):
        from apps.jobs.services import TaskService
        self.task_a.status = Task.STATUS_COMPLETE
        self.task_a.save(update_fields=['status'])
        with self.assertRaises(ValidationError) as cm:
            TaskService.update_task(
                self.task_a.pk, user=self.financials_user, rate=Decimal('55.00'))
        self.assertIn('settled', str(cm.exception))

    def test_cancelled_po_linked_uninvoiced_rate_write_by_financials_succeeds(self):
        """Cancelled is included, not just complete: a cancelled task's
        recorded actuals stay billable, so the same reprice exception
        applies."""
        from apps.jobs.services import TaskService
        self._make_line(self._make_issued_po(), task=self.task_a)
        self.task_a.status = Task.STATUS_CANCELLED
        self.task_a.save(update_fields=['status'])
        updated = TaskService.update_task(
            self.task_a.pk, user=self.financials_user, rate=Decimal('55.00'))
        self.assertEqual(updated.rate, Decimal('55.00'))

    def test_cancelled_po_linked_uninvoiced_rate_write_by_manager_only_rejected(self):
        from apps.jobs.services import TaskService
        self._make_line(self._make_issued_po(), task=self.task_a)
        self.task_a.status = Task.STATUS_CANCELLED
        self.task_a.save(update_fields=['status'])
        with self.assertRaises(ValidationError) as cm:
            TaskService.update_task(
                self.task_a.pk, user=self.manager_user, rate=Decimal('55.00'))
        self.assertIn('settled', str(cm.exception))

    def test_cancelled_without_po_link_rejected(self):
        from apps.jobs.services import TaskService
        self.task_a.status = Task.STATUS_CANCELLED
        self.task_a.save(update_fields=['status'])
        with self.assertRaises(ValidationError) as cm:
            TaskService.update_task(
                self.task_a.pk, user=self.financials_user, rate=Decimal('55.00'))
        self.assertIn('settled', str(cm.exception))

    def test_cancelled_po_linked_but_invoiced_rejected(self):
        from apps.jobs.services import TaskService
        self._make_line(self._make_issued_po(), task=self.task_a)
        self.task_a.status = Task.STATUS_CANCELLED
        self.task_a.save(update_fields=['status'])
        self._mark_invoiced(self.task_a)
        with self.assertRaises(ValidationError) as cm:
            TaskService.update_task(
                self.task_a.pk, user=self.financials_user, rate=Decimal('55.00'))
        self.assertIn('settled', str(cm.exception))

    def test_complete_po_linked_but_invoiced_rejected(self):
        from apps.jobs.services import TaskService
        self._make_line(self._make_issued_po(), task=self.task_a)
        self.task_a.status = Task.STATUS_COMPLETE
        self.task_a.save(update_fields=['status'])
        self._mark_invoiced(self.task_a)
        with self.assertRaises(ValidationError) as cm:
            TaskService.update_task(
                self.task_a.pk, user=self.financials_user, rate=Decimal('55.00'))
        self.assertIn('settled', str(cm.exception))

    def test_complete_po_linked_uninvoiced_but_extra_money_field_rejected(self):
        """The exception is rate-ONLY — a request that also touches another
        money field (e.g. unit_label alongside rate) is rejected in full,
        not partially applied."""
        from apps.jobs.services import TaskService
        self._make_line(self._make_issued_po(), task=self.task_a)
        self.task_a.status = Task.STATUS_COMPLETE
        self.task_a.save(update_fields=['status'])
        with self.assertRaises(ValidationError) as cm:
            TaskService.update_task(
                self.task_a.pk, user=self.financials_user,
                rate=Decimal('55.00'), unit_label='hour')
        self.assertIn('settled', str(cm.exception))

    def test_complete_po_linked_uninvoiced_non_rate_money_field_rejected(self):
        """A write that touches only a DIFFERENT money field (not rate) on
        an otherwise-qualifying task is still rejected — the carve-out is
        specifically for `rate`, not the whole money block."""
        from apps.jobs.services import TaskService
        self._make_line(self._make_issued_po(), task=self.task_a)
        self.task_a.status = Task.STATUS_COMPLETE
        self.task_a.save(update_fields=['status'])
        with self.assertRaises(ValidationError) as cm:
            TaskService.update_task(
                self.task_a.pk, user=self.financials_user, unit_label='hour')
        self.assertIn('settled', str(cm.exception))
