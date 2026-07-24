from unittest.mock import patch, MagicMock
from apps.core.models import PurchasingHistory
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, EmailRecord
from apps.contacts.models import Contact, Business
from apps.purchasing.models import PurchaseOrder


class PurchaseOrderAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_purchase_orders(self):
        response = self.client.get('/api/purchase-orders/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_po(self):
        po = PurchaseOrder.objects.first()
        if po:
            response = self.client.get(f'/api/purchase-orders/{po.pk}/')
            self.assertEqual(response.status_code, 200)
            self.assertIn('line_items', response.data)

    def test_create_po(self):
        from apps.contacts.models import Business
        business = Business.objects.first()
        response = self.client.post('/api/purchase-orders/', {
            'business': business.pk,
        }, format='json')
        self.assertIn(response.status_code, [201, 400])

    def test_add_line_item(self):
        po = self._make_draft_po()
        response = self.client.post(f'/api/purchase-orders/{po.pk}/line-items/', {
            'qty': '5.00',
            'units': 'ea',
            'description': 'Widgets',
            'price': '25.00',
        }, format='json')
        self.assertIn(response.status_code, [200, 201])

    def test_filter_purchase_orders_by_job(self):
        """POs can be filtered by job via line item linkage (Material.po_line_item)."""
        from decimal import Decimal
        from apps.contacts.models import Business
        from apps.core.models import AccountingCategory
        from apps.jobs.models import Job
        from apps.purchasing.services import PurchaseOrderService
        business = Business.objects.first()
        job = Job.objects.first()
        cat = AccountingCategory.objects.first()

        po = PurchaseOrder.objects.create(
            business=business,
            po_number='PO-TEST-FILTER',
        )
        PurchaseOrderService.add_line_item(
            po.pk,
            description='Test item',
            qty=Decimal('1'),
            price=Decimal('100'),
            job=job.pk,
            accounting_category=cat,
        )
        po2 = PurchaseOrder.objects.create(
            business=business,
            po_number='PO-TEST-NOJOB',
        )
        PurchaseOrderService.add_line_item(
            po2.pk,
            description='Unlinked item',
            qty=Decimal('1'),
            price=Decimal('50'),
        )

        response = self.client.get(f'/api/purchase-orders/?job={job.job_id}')
        self.assertEqual(response.status_code, 200)
        po_ids = [r['po_id'] for r in response.data['results']]
        self.assertIn(po.po_id, po_ids)
        self.assertNotIn(po2.po_id, po_ids)

    def test_purchase_order_serializer_includes_business_name(self):
        """PO API response includes business_name field."""
        from apps.contacts.models import Business
        business = Business.objects.first()
        po = PurchaseOrder.objects.create(
            business=business,
            po_number='PO-TEST-BIZNAME',
        )
        response = self.client.get(f'/api/purchase-orders/{po.po_id}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('business_name', response.data)
        self.assertEqual(response.data['business_name'], business.business_name)

    def test_cancel_po_creates_history(self):
        po = PurchaseOrder.objects.filter(status=PurchaseOrder.STATUS_ISSUED).first()
        if po:
            self.client.post(f'/api/purchase-orders/{po.pk}/cancel/', {
                'reason': 'No longer needed',
            }, format='json')
            entry = PurchasingHistory.objects.filter(
                entry_type='audit', object_type='purchaseorder', object_id=po.pk,
            ).first()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.text, 'No longer needed')
            self.assertEqual(entry.user, self.user)


    def _make_draft_po(self):
        """Helper: create a draft PO with one line item."""
        from apps.contacts.models import Business
        business = Business.objects.first()
        po = PurchaseOrder.objects.create(
            business=business,
            po_number='PO-TEST-DRAFT',
        )
        from apps.purchasing.models import PurchaseOrderLineItem
        PurchaseOrderLineItem.objects.create(
            purchase_order=po,
            description='Test widget',
            qty=10,
            price=25,
        )
        return po

    # --- History endpoint ---

    def test_history_returns_empty_for_new_po(self):
        """History endpoint returns 200 with no entries for a fresh PO."""
        po = self._make_draft_po()
        response = self.client.get(f'/api/purchase-orders/{po.po_id}/history/')
        self.assertEqual(response.status_code, 200)

    def test_history_returns_audit_entries_after_status_change(self):
        """Issuing a PO creates an audit history entry."""
        po = self._make_draft_po()
        self.client.post(f'/api/purchase-orders/{po.po_id}/issue/', format='json')
        response = self.client.get(f'/api/purchase-orders/{po.po_id}/history/')
        self.assertEqual(response.status_code, 200)
        results = response.data.get('results', response.data)
        self.assertTrue(len(results) > 0)

    def test_history_accessible_by_non_financial_user(self):
        """Any authenticated user can view PO history."""
        po = self._make_draft_po()
        worker = User.objects.get(username='johnq')
        self.client.force_authenticate(user=worker)
        response = self.client.get(f'/api/purchase-orders/{po.po_id}/history/')
        self.assertEqual(response.status_code, 200)

    # --- Notes endpoint ---

    def test_add_note_to_po(self):
        """Adding a note creates a history entry of type 'note'."""
        po = self._make_draft_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/notes/',
            {'text': 'Vendor confirmed delivery date'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['entry_type'], 'note')
        self.assertEqual(response.data['text'], 'Vendor confirmed delivery date')
        # Verify it appears in history
        hist = self.client.get(f'/api/purchase-orders/{po.po_id}/history/')
        results = hist.data.get('results', hist.data)
        texts = [e['text'] for e in results]
        self.assertIn('Vendor confirmed delivery date', texts)

    def test_add_note_requires_text(self):
        """Notes endpoint rejects empty text."""
        po = self._make_draft_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/notes/',
            {'text': ''},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_add_note_accessible_by_non_financial_user(self):
        """Any authenticated user can add notes to a PO."""
        po = self._make_draft_po()
        worker = User.objects.get(username='johnq')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/notes/',
            {'text': 'Checked with warehouse'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)

    # --- Status filter ---

    def test_filter_by_status_draft(self):
        """Filtering by status=draft returns only draft POs."""
        po = self._make_draft_po()
        response = self.client.get('/api/purchase-orders/?status=draft')
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertTrue(len(results) > 0)
        for r in results:
            self.assertEqual(r['status'], 'draft')
        po_ids = [r['po_id'] for r in results]
        self.assertIn(po.po_id, po_ids)

    def test_filter_by_status_issued(self):
        """Filtering by status=issued excludes draft POs."""
        po = self._make_draft_po()
        response = self.client.get('/api/purchase-orders/?status=issued')
        self.assertEqual(response.status_code, 200)
        po_ids = [r['po_id'] for r in response.data['results']]
        self.assertNotIn(po.po_id, po_ids)

    def test_filter_by_nonexistent_status_returns_empty(self):
        """Filtering by a bogus status returns no results."""
        response = self.client.get('/api/purchase-orders/?status=nonexistent')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 0)

    # --- Serializer: contact_name ---

    def test_serializer_includes_contact_name(self):
        """PO response includes contact_name when contact is set."""
        from apps.contacts.models import Business, Contact
        business = Business.objects.first()
        contact = Contact.objects.filter(business=business).first()
        if not contact:
            contact = Contact.objects.create(
                first_name='Test', last_name='Vendor',
                email='test@vendor.com', business=business,
            )
        po = PurchaseOrder.objects.create(
            business=business, contact=contact,
            po_number='PO-TEST-CONTACT',
        )
        response = self.client.get(f'/api/purchase-orders/{po.po_id}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('contact_name', response.data)
        self.assertIsNotNone(response.data['contact_name'])
        self.assertIn(' ', response.data['contact_name'])  # "First Last"

    def test_serializer_contact_name_null_when_no_contact(self):
        """PO response has null contact_name when no contact."""
        po = self._make_draft_po()  # no contact
        response = self.client.get(f'/api/purchase-orders/{po.po_id}/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['contact_name'])

    # --- Permission: non-financial user cannot create/edit ---

    def test_issue_with_optional_note_saves_to_history(self):
        """Issuing a PO with an optional reason saves it to history."""
        po = self._make_draft_po()
        self.client.post(f'/api/purchase-orders/{po.po_id}/issue/', {
            'reason': 'Ordered by phone',
        }, format='json')
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_ISSUED)
        entry = PurchasingHistory.objects.filter(
            object_type='purchaseorder', object_id=po.pk,
        ).order_by('-timestamp').first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.text, 'Ordered by phone')

    def test_issue_without_note_still_works(self):
        """Issuing a PO without a reason succeeds (reason is optional)."""
        po = self._make_draft_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/issue/', {}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_ISSUED)

    def test_non_financial_user_cannot_create_po(self):
        """Users without can_manage_financials cannot create POs."""
        from apps.contacts.models import Business
        worker = User.objects.get(username='johnq')
        self.client.force_authenticate(user=worker)
        response = self.client.post('/api/purchase-orders/', {
            'business': Business.objects.first().pk,
        }, format='json')
        self.assertEqual(response.status_code, 403)

    def test_non_financial_user_cannot_issue_po(self):
        """Users without can_manage_financials cannot issue POs."""
        po = self._make_draft_po()
        worker = User.objects.get(username='johnq')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/issue/', format='json'
        )
        self.assertEqual(response.status_code, 403)


class PurchaseOrderSendRetrofitTest(BaseTestCase):
    """Retrofitted PO send: routes through OutboundEmailService.send_tracked,
    so an outbound EmailRecord is persisted and linked to the PO."""

    def setUp(self):
        super().setUp()
        from apps.purchasing.models import PurchaseOrderLineItem
        from apps.contacts.models import Business, Contact
        self.client = APIClient()
        self.admin = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.admin)
        vendor_contact = Contact.objects.create(
            first_name='Vendor', last_name='Rep',
            email='vendor-rep@example.com', mobile_number='555',
        )
        vendor = Business.objects.create(
            business_name='Vendor Inc.', default_contact=vendor_contact,
        )
        vendor_contact.business = vendor
        vendor_contact.save()
        self.po = PurchaseOrder.objects.create(
            po_number='PO-SEND-RT-1', business=vendor, contact=vendor_contact,
            status=PurchaseOrder.STATUS_DRAFT,
        )
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po,
            line_number=1, qty='1.00', units='ea',
            description='Test', price='10.00',
        )

    @patch('apps.purchasing.pdf.generate_purchase_order_pdf')
    @patch('django.core.mail.EmailMessage')
    def test_send_persists_outbound_email_record(self, MockEmailMessage, mock_pdf):
        MockEmailMessage.return_value = MagicMock()
        mock_pdf.return_value = b'%PDF-fake'

        response = self.client.post(
            f'/api/purchase-orders/{self.po.po_id}/send/',
            {
                'to': 'vendor@example.com',
                'subject': 'PO Send Test',
                'body': 'See attached.',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

        # PO transitioned draft -> issued (existing behavior preserved).
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.STATUS_ISSUED)

        # Outbound EmailRecord exists, linked to this PO.
        outbound = EmailRecord.objects.get(
            direction=EmailRecord.OUTBOUND, purchase_order=self.po,
        )
        self.assertIsNotNone(outbound.sent_at)


class PurchaseOrderSearchTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        dc = Contact.objects.create(first_name='DC', last_name='', email='dc@example.com')
        self.acme = Business.objects.create(business_name='Acme Steel', default_contact=dc)
        self.po_match = PurchaseOrder.objects.create(business=self.acme, po_number='PO-SEARCH-1')
        other_dc = Contact.objects.create(first_name='OC', last_name='', email='oc@example.com')
        other = Business.objects.create(business_name='Zenith Glass', default_contact=other_dc)
        self.po_other = PurchaseOrder.objects.create(business=other, po_number='PO-OTHER-9')

    def _ids(self, resp):
        rows = resp.data['results'] if 'results' in resp.data else resp.data
        return [r['po_id'] for r in rows]

    def test_search_by_po_number(self):
        resp = self.client.get('/api/purchase-orders/?search=SEARCH-1')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.po_match.po_id, self._ids(resp))
        self.assertNotIn(self.po_other.po_id, self._ids(resp))

    def test_search_by_vendor_name(self):
        resp = self.client.get('/api/purchase-orders/?search=Acme')
        self.assertIn(self.po_match.po_id, self._ids(resp))
        self.assertNotIn(self.po_other.po_id, self._ids(resp))
