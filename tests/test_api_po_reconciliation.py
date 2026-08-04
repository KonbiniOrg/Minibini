"""API tests for PO reconciliation (task-owned-money Phase 5, Task 2).

Covers:
- POST /api/purchase-orders/{id}/reconcile/: success shape (updated PO
  fields + rate_prompts + markup_applied), permission matrix, NotFound.
- PurchaseOrderSerializer: bill_total/vendor_invoice_ref/reconciled/
  reconciled_date/awaiting_reconciliation/variance.
- ?awaiting_reconciliation=true list filter.
- POLineItemSerializer: task/final_price/invoice_only exposure; task
  writable on line create with field-shaped validation (subtask → 400).
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
        self.sub_task = Task.objects.create(
            job=self.job, name='Sub of outsourced work', parent_task=self.top_task,
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
        only non-invoice_only lines (spec §7 rule 3 / Task 2 decision)."""
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


class TaskLinkAPIValidationTest(POReconciliationAPITestBase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.admin)

    def _draft_po(self):
        return PurchaseOrder.objects.create(business=self.business)

    def test_link_top_level_task_via_line_create(self):
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

    def test_link_subtask_via_line_create_rejected_field_shaped(self):
        po = self._draft_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.pk}/line-items/',
            {
                'description': 'Outsourced', 'qty': '1.00', 'price': '50.00',
                'accounting_category': self.cat.pk, 'task': self.sub_task.pk,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('task', response.data)

    def test_link_subtask_via_line_patch_rejected_field_shaped(self):
        po = self._draft_po()
        li = PurchaseOrderService.add_line_item(
            po.pk, description='Outsourced', qty=Decimal('1.00'),
            price=Decimal('50.00'), accounting_category=self.cat.pk,
        )
        response = self.client.patch(
            f'/api/purchase-orders/{po.pk}/line-items/{li.pk}/',
            {'task': self.sub_task.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('task', response.data)
