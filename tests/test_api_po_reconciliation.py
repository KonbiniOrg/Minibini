"""API tests for PO reconciliation (task-owned-money Phase 5, outsourced-work
port Task 3).

Covers:
- POST /api/purchase-orders/{id}/reconcile/: success shape (updated PO
  fields + rate_prompts + markup_applied), permission matrix, NotFound.
- PurchaseOrderSerializer: bill_total/vendor_invoice_ref/reconciled/
  reconciled_date/awaiting_reconciliation/variance.
- ?awaiting_reconciliation=true list filter.
- POLineItemSerializer: task/final_price/invoice_only exposure; task
  writable on line create (the create-path strip was removed).

NOTE: per the outsourced-work port ruling, Task.parent_task is dormant on
this branch (no code may read/write it) — fees' subtask test cases are
deliberately NOT ported; there is no top-level/subtask distinction here.

Re-shape (spec ruling 2): `compute_rate_prompts`'s `current_rate` is
`task.effective_rate()` (modifiers-aware), and each prompt carries a new
`has_active_modifiers` key — covered below against fees' raw-`task.rate`
behavior.
"""
from decimal import Decimal
from rest_framework.test import APIClient
from tests.base import BaseTestCase, grant_atoms
from apps.core.models import User, AccountingCategory
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job, Task
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService, PurchaseOrderReceivingService


class POReconciliationAPITestBase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.admin = User.objects.get(username='admin')
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
        self.job = Job.objects.create(
            job_number='J-RECON', contact=self.customer, description='a',
            status=Job.STATUS_APPROVED,
        )
        self.top_task = Task.objects.create(
            job=self.job, name='Outsourced work', rate=Decimal('100.00'),
        )

    def _make_issued_po(self, task=None):
        po = PurchaseOrder.objects.create(
            business=self.business, status=PurchaseOrder.STATUS_ISSUED,
        )
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='Item 1', qty=Decimal('2.00'),
            price=Decimal('10.00'), accounting_category=self.cat, task=task,
        )
        return po


class ReconcileEndpointTest(POReconciliationAPITestBase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.admin)

    def test_reconcile_success_updates_po_fields(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/',
            {
                'bill_total': '25.00',
                'vendor_invoice_ref': 'VEND-1',
                'line_finals': {str(li.pk): '12.00'},
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['bill_total'], '25.00')
        self.assertEqual(response.data['vendor_invoice_ref'], 'VEND-1')
        self.assertTrue(response.data['reconciled'])
        self.assertIsNotNone(response.data['reconciled_date'])
        li.refresh_from_db()
        self.assertEqual(li.final_price, Decimal('12.00'))

    def test_reconcile_response_includes_rate_prompts_and_markup_flag(self):
        po = self._make_issued_po(task=self.top_task)
        li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/',
            {'bill_total': '18.00', 'line_finals': {str(li.pk): '18.00'}},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('rate_prompts', response.data)
        self.assertIn('markup_applied', response.data)
        self.assertEqual(len(response.data['rate_prompts']), 1)
        prompt = response.data['rate_prompts'][0]
        self.assertEqual(prompt['task_id'], self.top_task.pk)
        self.assertEqual(prompt['task_name'], self.top_task.name)

    def test_reconcile_no_rate_prompt_without_final_price(self):
        po = self._make_issued_po(task=self.top_task)
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/',
            {'bill_total': '20.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['rate_prompts'], [])

    def test_reconcile_appended_lines_round_trip_drop_replace_keep(self):
        po = self._make_issued_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/',
            {
                'bill_total': '45.00',
                'appended_lines': [
                    {'description': 'Freight', 'qty': '1.00', 'price': '15.00',
                     'accounting_category': self.cat.pk},
                    {'description': 'Tax', 'qty': '1.00', 'price': '5.00',
                     'accounting_category': self.cat.pk},
                ],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        freight = PurchaseOrderLineItem.objects.get(purchase_order=po, description='Freight')
        tax = PurchaseOrderLineItem.objects.get(purchase_order=po, description='Tax')

        # Second call: drop Freight, keep+update Tax, add Handling.
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/',
            {
                'bill_total': '40.00',
                'appended_lines': [
                    {'line_item_id': tax.pk, 'description': 'Tax (corrected)',
                     'qty': '1.00', 'price': '5.00', 'accounting_category': self.cat.pk},
                    {'description': 'Handling', 'qty': '1.00', 'price': '3.00',
                     'accounting_category': self.cat.pk},
                ],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(PurchaseOrderLineItem.objects.filter(pk=freight.pk).exists())
        tax.refresh_from_db()
        self.assertEqual(tax.description, 'Tax (corrected)')
        self.assertTrue(
            PurchaseOrderLineItem.objects.filter(purchase_order=po, description='Handling').exists()
        )

    def test_reconcile_not_found(self):
        response = self.client.post(
            '/api/purchase-orders/999999/reconcile/', {'bill_total': '1.00'}, format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_reconcile_before_issue_rejected_field_shaped(self):
        po = PurchaseOrder.objects.create(business=self.business)  # draft
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='Item', qty=Decimal('1.00'),
            price=Decimal('5.00'), accounting_category=self.cat,
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/', {'bill_total': '5.00'}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_reconcile_bad_line_finals_shape_rejected(self):
        po = self._make_issued_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/',
            {'bill_total': '5.00', 'line_finals': {'not-an-int': '5.00'}},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('line_finals', response.data)

    def test_reconcile_malformed_bill_total_rejected_field_shaped(self):
        """A non-numeric bill_total must 400 with a field-shaped error, not
        500 — malformed input from an API caller is not a programming
        error."""
        po = self._make_issued_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/',
            {'bill_total': 'not-a-number'},
            format='json',
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('bill_total', response.data)

    def test_reconcile_malformed_line_finals_value_rejected_field_shaped(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/',
            {'bill_total': '5.00', 'line_finals': {str(li.pk): 'not-a-number'}},
            format='json',
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('line_finals', response.data)
        li.refresh_from_db()
        self.assertIsNone(li.final_price)

    def test_reconcile_malformed_appended_line_item_id_rejected_field_shaped(self):
        po = self._make_issued_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/',
            {
                'bill_total': '5.00',
                'appended_lines': [{
                    'line_item_id': 'not-an-id', 'description': 'Freight',
                    'qty': '1.00', 'price': '15.00',
                    'accounting_category': self.cat.pk,
                }],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('appended_lines', response.data)

    def test_reconcile_smuggled_qty_received_on_appended_line_rejected(self):
        """appended_lines is restricted to the whitelist `add_line_item`
        accepts — a caller cannot pre-seed a freshly-appended invoice_only
        line's receiving state through reconcile."""
        po = self._make_issued_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/',
            {
                'bill_total': '5.00',
                'appended_lines': [{
                    'description': 'Freight', 'qty': '1.00', 'price': '15.00',
                    'accounting_category': self.cat.pk, 'qty_received': '1.00',
                }],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('appended_lines', response.data)
        self.assertFalse(
            PurchaseOrderLineItem.objects.filter(
                purchase_order=po, description='Freight',
            ).exists()
        )


class RatePromptEffectiveRateAPITest(POReconciliationAPITestBase):
    """Re-shape (spec ruling 2): `current_rate` = `task.effective_rate()`
    (modifiers-aware), plus a new `has_active_modifiers` key — differs from
    fees, which read raw `task.rate`."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.admin)

    def test_rate_prompt_current_rate_reflects_active_modifiers(self):
        self.top_task.active_modifiers = [
            {'key': 'rush', 'label': 'Rush', 'percent': 50},
        ]
        self.top_task.save()
        po = self._make_issued_po(task=self.top_task)
        li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/',
            {'bill_total': '18.00', 'line_finals': {str(li.pk): '18.00'}},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        prompt = response.data['rate_prompts'][0]
        # effective_rate = 100.00 * 1.50 = 150.00, NOT the raw rate (100.00)
        self.assertEqual(Decimal(prompt['current_rate']), Decimal('150.00'))
        self.assertTrue(prompt['has_active_modifiers'])

    def test_rate_prompt_modifier_less_task_matches_fees_behavior(self):
        """No active_modifiers: effective_rate() equals the raw rate, so
        this case is indistinguishable from fees' `task.rate` reading."""
        po = self._make_issued_po(task=self.top_task)
        li = PurchaseOrderLineItem.objects.get(purchase_order=po)
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/',
            {'bill_total': '18.00', 'line_finals': {str(li.pk): '18.00'}},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        prompt = response.data['rate_prompts'][0]
        self.assertEqual(Decimal(prompt['current_rate']), Decimal('100.00'))
        self.assertFalse(prompt['has_active_modifiers'])


class CancelLineItemInvoiceOnlyGuardAPITest(POReconciliationAPITestBase):
    """POST /api/purchase-orders/{id}/cancel-line-item/ rejects an
    invoice_only target (task-owned-money Phase 5 hardening) — matches
    PurchaseOrderReceivingService.cancel_line_item's guard."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.admin)

    def test_cancel_line_item_on_invoice_only_line_rejected(self):
        po = self._make_issued_po()
        self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/',
            {
                'bill_total': '15.00',
                'appended_lines': [{
                    'description': 'Freight', 'qty': '1.00', 'price': '15.00',
                    'accounting_category': self.cat.pk,
                }],
            },
            format='json',
        )
        invoice_only_li = PurchaseOrderLineItem.objects.get(
            purchase_order=po, invoice_only=True,
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/cancel-line-item/',
            {'line_item_id': invoice_only_li.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400, response.data)


class ReconcilePermissionMatrixTest(POReconciliationAPITestBase):
    """The PO viewset's existing gate (apps/api/purchasing/views.py
    get_permissions): every action outside the IsAuthenticated-only list
    (list/retrieve/history/notes/send_defaults/receive*/cancel_line_item/
    reverse_receipt, plus GET line_items) requires CanManageFinancials —
    there is no CanManageJobsOrFinancials-style OR-permission for POs.
    `reconcile` is not in that safe list, so it follows the same
    financials-only convention as create/issue/etc."""

    def test_financials_only_user_can_reconcile(self):
        worker = User.objects.get(username='manager1')
        worker = grant_atoms(worker, 'can_manage_financials')
        self.client.force_authenticate(user=worker)
        po = self._make_issued_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/', {'bill_total': '5.00'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_worker_with_no_atoms_cannot_reconcile(self):
        worker = User.objects.get(username='johnq')
        self.client.force_authenticate(user=worker)
        po = self._make_issued_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/', {'bill_total': '5.00'}, format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_manage_jobs_only_user_cannot_reconcile(self):
        """can_manage_jobs alone does not grant PO write access — matches
        the existing convention (e.g. test_non_financial_user_cannot_create_po/
        _issue_po in test_api_purchasing.py)."""
        manager = User.objects.get(username='manager1')
        manager = grant_atoms(manager, 'can_manage_jobs')
        self.client.force_authenticate(user=manager)
        po = self._make_issued_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/', {'bill_total': '5.00'}, format='json',
        )
        self.assertEqual(response.status_code, 403)


class SerializerFieldsTest(POReconciliationAPITestBase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.admin)

    def test_detail_exposes_reconciliation_fields(self):
        po = self._make_issued_po()
        response = self.client.get(f'/api/purchase-orders/{po.pk}/')
        self.assertEqual(response.status_code, 200)
        for field in (
            'bill_total', 'vendor_invoice_ref', 'reconciled', 'reconciled_date',
            'awaiting_reconciliation', 'variance',
        ):
            self.assertIn(field, response.data)

    def test_variance_null_before_bill_total_recorded(self):
        po = self._make_issued_po()
        response = self.client.get(f'/api/purchase-orders/{po.pk}/')
        self.assertIsNone(response.data['variance'])

    def test_variance_excludes_invoice_only_lines_from_ordered_total(self):
        """variance = bill_total − ordered_total, where ordered_total sums
        only non-invoice_only lines (spec §7 rule 3 decision)."""
        po = self._make_issued_po()  # ordered: qty 2 @ 10.00 = 20.00
        self.client.post(
            f'/api/purchase-orders/{po.pk}/reconcile/',
            {
                'bill_total': '50.00',
                'appended_lines': [{
                    'description': 'Freight', 'qty': '1.00', 'price': '15.00',
                    'accounting_category': self.cat.pk,
                }],
            },
            format='json',
        )
        response = self.client.get(f'/api/purchase-orders/{po.pk}/')
        # ordered_total stays 20.00 (freight excluded); variance = 50 - 20 = 30.00
        self.assertEqual(response.data['variance'], '30.00')

    def test_awaiting_reconciliation_filter(self):
        po_awaiting = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.get(purchase_order=po_awaiting)
        PurchaseOrderReceivingService.receive_items(
            po_awaiting, [{'line_item_id': li.pk, 'qty_received': 2}], self.admin,
        )
        po_awaiting.refresh_from_db()
        self.assertEqual(po_awaiting.status, PurchaseOrder.STATUS_RECEIVED_IN_FULL)

        po_not_awaiting = self._make_issued_po()

        response = self.client.get('/api/purchase-orders/?awaiting_reconciliation=true')
        self.assertEqual(response.status_code, 200)
        ids = [r['po_id'] for r in response.data['results']]
        self.assertIn(po_awaiting.po_id, ids)
        self.assertNotIn(po_not_awaiting.po_id, ids)

    def test_line_payload_exposes_task_final_price_invoice_only(self):
        po = self._make_issued_po(task=self.top_task)
        response = self.client.get(f'/api/purchase-orders/{po.pk}/')
        line = response.data['line_items'][0]
        for field in ('task', 'final_price', 'invoice_only'):
            self.assertIn(field, line)
        self.assertEqual(line['task'], self.top_task.pk)
        self.assertFalse(line['invoice_only'])


class TaskLinkAPIWritableOnCreateTest(POReconciliationAPITestBase):
    """The line-create task-strip (`data.pop('task', None)`) was removed —
    `task` is writable on create the same way it already was on PATCH."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.admin)

    def _draft_po(self):
        return PurchaseOrder.objects.create(business=self.business)

    def test_task_writable_via_line_create(self):
        po = self._draft_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/line-items/',
            {
                'description': 'Outsourced', 'qty': '1.00', 'price': '50.00',
                'accounting_category': self.cat.pk, 'task': self.top_task.pk,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['task'], self.top_task.pk)
        li = PurchaseOrderLineItem.objects.get(pk=response.data['line_item_id'])
        self.assertEqual(li.task_id, self.top_task.pk)


class TerminalTaskRateExceptionAPITest(POReconciliationAPITestBase):
    """RM ruling 2026-09-21 (resolves LATER.md "rate-prompt Accept fails on
    complete tasks"), tightened same-day: PATCH
    /api/jobs/{job}/tasks/{id}/ {rate: ...} succeeds on a TERMINAL task
    (complete OR cancelled) when it is uninvoiced, PO-linked, AND the
    caller holds `can_manage_financials` — exactly the PATCH
    RatePromptDialog.svelte's Accept gesture sends (that dialog is already
    client-gated on `canManageFinancials`, so this makes the server match
    the real flow rather than being looser than it). Cancelled is included
    because a cancelled task's recorded actuals stay billable, so it
    carries the same reprice claim as a completed one.

    `self.admin` (used by most tests below) holds `can_manage_financials`
    directly in the fixture (not `is_superuser`), so the success cases
    below already exercise the financials arm for real, not via a
    superuser bypass — `test_..._by_financials_only_user_succeeds` adds a
    dedicated financials-only (no `can_manage_jobs`) user for a case that
    can't be confused with "admin can do everything anyway."

    The financials-only arm is narrower than the ordinary MONEY_FIELDS
    gate (manager atom OR the job's PM OR financials): a job's PM or a
    plain `can_manage_jobs` holder can write `rate` on this same task
    while it's open, but gets the ordinary terminal-freeze rejection once
    it's terminal — `test_..._by_manager_only_user_rejected` and
    `test_..._by_job_pm_without_financials_rejected` pin that.
    `test_pm_non_terminal_rate_patch_still_works` pins the unaffected
    normal path (PM writing `rate` on a still-open task).

    API-level coverage on top of the service-level matrix in
    TerminalTaskRateExceptionTest (tests/test_po_reconciliation.py)."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.admin)
        from django.contrib.auth.models import Permission
        self.financials_only_user = User.objects.create_user(
            username='api_rate_fin', password='x')
        self.financials_only_user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials'))
        self.financials_only_user = User.objects.get(pk=self.financials_only_user.pk)
        self.manager_only_user = User.objects.create_user(
            username='api_rate_mgr', password='x')
        self.manager_only_user.user_permissions.add(
            Permission.objects.get(codename='can_manage_jobs'))
        self.manager_only_user = User.objects.get(pk=self.manager_only_user.pk)
        self.job_pm_user = User.objects.create_user(
            username='api_rate_pm', password='x')
        self.job.project_manager = self.job_pm_user
        self.job.save(update_fields=['project_manager'])

    def _task_url(self):
        return f'/api/jobs/{self.job.pk}/tasks/{self.top_task.pk}/'

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

    def test_complete_po_linked_uninvoiced_rate_patch_by_financials_only_user_succeeds(self):
        """A dedicated financials-only user (no `can_manage_jobs`) — not
        `self.admin`, which holds every atom — proves the arm really is
        `can_manage_financials`, not incidentally satisfied by admin's
        other permissions."""
        self._make_issued_po(task=self.top_task)
        self.top_task.status = Task.STATUS_COMPLETE
        self.top_task.save(update_fields=['status'])
        self.client.force_authenticate(user=self.financials_only_user)
        response = self.client.patch(
            self._task_url(), data={'rate': '155.00'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.top_task.refresh_from_db()
        self.assertEqual(self.top_task.rate, Decimal('155.00'))

    def test_complete_po_linked_uninvoiced_rate_patch_by_manager_only_user_rejected(self):
        """A plain `can_manage_jobs` holder does NOT qualify for the
        exception -- ordinary terminal-freeze rejection, same as before
        the carve-out."""
        self._make_issued_po(task=self.top_task)
        self.top_task.status = Task.STATUS_COMPLETE
        self.top_task.save(update_fields=['status'])
        self.client.force_authenticate(user=self.manager_only_user)
        response = self.client.patch(
            self._task_url(), data={'rate': '155.00'}, format='json',
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('settled', str(response.data))

    def test_complete_po_linked_uninvoiced_rate_patch_by_job_pm_without_financials_rejected(self):
        """The job's own PM does NOT qualify either -- the exception is
        financials-only, not the ordinary manager-OR-PM-OR-financials
        MONEY_FIELDS gate."""
        self._make_issued_po(task=self.top_task)
        self.top_task.status = Task.STATUS_COMPLETE
        self.top_task.save(update_fields=['status'])
        self.client.force_authenticate(user=self.job_pm_user)
        response = self.client.patch(
            self._task_url(), data={'rate': '155.00'}, format='json',
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('settled', str(response.data))

    def test_pm_non_terminal_rate_patch_still_works(self):
        """Regression pin: the carve-out only narrows the TERMINAL-task
        path -- the job's PM can still write `rate` on a still-open
        (pending) task exactly as before, via the ordinary MONEY_FIELDS
        gate (CanManageJobOrPM)."""
        self.assertEqual(self.top_task.status, Task.STATUS_PENDING)
        self.client.force_authenticate(user=self.job_pm_user)
        response = self.client.patch(
            self._task_url(), data={'rate': '155.00'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.top_task.refresh_from_db()
        self.assertEqual(self.top_task.rate, Decimal('155.00'))

    def test_complete_po_linked_uninvoiced_rate_patch_succeeds(self):
        self._make_issued_po(task=self.top_task)
        self.top_task.status = Task.STATUS_COMPLETE
        self.top_task.save(update_fields=['status'])
        response = self.client.patch(
            self._task_url(), data={'rate': '155.00'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.top_task.refresh_from_db()
        self.assertEqual(self.top_task.rate, Decimal('155.00'))

    def test_complete_without_po_link_rate_patch_rejected(self):
        self.top_task.status = Task.STATUS_COMPLETE
        self.top_task.save(update_fields=['status'])
        response = self.client.patch(
            self._task_url(), data={'rate': '155.00'}, format='json',
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('settled', str(response.data))

    def test_cancelled_po_linked_uninvoiced_rate_patch_succeeds(self):
        self._make_issued_po(task=self.top_task)
        self.top_task.status = Task.STATUS_CANCELLED
        self.top_task.save(update_fields=['status'])
        response = self.client.patch(
            self._task_url(), data={'rate': '155.00'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.top_task.refresh_from_db()
        self.assertEqual(self.top_task.rate, Decimal('155.00'))

    def test_cancelled_without_po_link_rate_patch_rejected(self):
        self.top_task.status = Task.STATUS_CANCELLED
        self.top_task.save(update_fields=['status'])
        response = self.client.patch(
            self._task_url(), data={'rate': '155.00'}, format='json',
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('settled', str(response.data))

    def test_complete_po_linked_invoiced_rate_patch_rejected(self):
        self._make_issued_po(task=self.top_task)
        self.top_task.status = Task.STATUS_COMPLETE
        self.top_task.save(update_fields=['status'])
        self._mark_invoiced(self.top_task)
        response = self.client.patch(
            self._task_url(), data={'rate': '155.00'}, format='json',
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('settled', str(response.data))

    def test_complete_po_linked_uninvoiced_rate_plus_unit_label_rejected(self):
        self._make_issued_po(task=self.top_task)
        self.top_task.status = Task.STATUS_COMPLETE
        self.top_task.save(update_fields=['status'])
        response = self.client.patch(
            self._task_url(),
            data={'rate': '155.00', 'unit_label': 'hour'}, format='json',
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('settled', str(response.data))
