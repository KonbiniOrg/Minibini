from unittest.mock import patch, MagicMock
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, HistoryEntry, Configuration
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.contacts.models import Business, Contact


class POSendTestBase(BaseTestCase):
    """Base class with helper to create a draft PO with a line item."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def _make_draft_po(self, with_contact_email=True):
        business = Business.objects.first()
        contact = Contact.objects.filter(business=business).first()
        if not contact:
            contact = Contact.objects.create(
                first_name='Test', last_name='Vendor',
                email='vendor@example.com' if with_contact_email else '',
                business=business,
            )
        elif with_contact_email and not contact.email:
            contact.email = 'vendor@example.com'
            contact.save()
        po = PurchaseOrder.objects.create(
            business=business,
            contact=contact,
            po_number='PO-TEST-SEND',
        )
        PurchaseOrderLineItem.objects.create(
            purchase_order=po,
            description='Test widget',
            qty=10,
            price=25,
        )
        return po


class POPDFTest(POSendTestBase):
    """Test PO PDF generation."""

    def test_generate_pdf_returns_bytes(self):
        from apps.purchasing.pdf import generate_purchase_order_pdf
        po = self._make_draft_po()
        pdf_bytes = generate_purchase_order_pdf(po)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(len(pdf_bytes) > 0)
        # PDF files start with %PDF
        self.assertTrue(pdf_bytes[:5].startswith(b'%PDF'))

    def test_pdf_is_valid_pdf(self):
        from apps.purchasing.pdf import generate_purchase_order_pdf
        po = self._make_draft_po()
        pdf_bytes = generate_purchase_order_pdf(po)
        # Valid PDF header and trailer
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
        self.assertIn(b'%%EOF', pdf_bytes)


class POSendDefaultsTest(POSendTestBase):
    """Test the send-defaults endpoint."""

    def test_defaults_returns_contact_email(self):
        po = self._make_draft_po(with_contact_email=True)
        response = self.client.get(
            f'/api/purchase-orders/{po.po_id}/send-defaults/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['to'], po.contact.email)
        self.assertIn(po.po_number, response.data['subject'])
        self.assertIn(po.po_number, response.data['body'])

    def test_defaults_uses_custom_templates(self):
        Configuration.objects.create(
            key='po_email_subject_template',
            value='ORDER {po_number} for {vendor_name}',
        )
        Configuration.objects.create(
            key='po_email_body_template',
            value='Hi {vendor_name}, please process {po_number}.',
        )
        po = self._make_draft_po()
        response = self.client.get(
            f'/api/purchase-orders/{po.po_id}/send-defaults/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('ORDER PO-TEST-SEND', response.data['subject'])
        self.assertIn(po.business.business_name, response.data['subject'])
        self.assertIn(po.business.business_name, response.data['body'])

    def test_defaults_accessible_by_any_user(self):
        po = self._make_draft_po()
        worker = User.objects.get(username='johnq')
        self.client.force_authenticate(user=worker)
        response = self.client.get(
            f'/api/purchase-orders/{po.po_id}/send-defaults/'
        )
        self.assertEqual(response.status_code, 200)


class POSendEndpointTest(POSendTestBase):
    """Test the POST send endpoint."""

    @patch('apps.core.services.OutboundEmailService.send_tracked')
    @patch('apps.purchasing.pdf.generate_purchase_order_pdf')
    def test_send_draft_po_issues_and_sends(self, mock_pdf, mock_send):
        mock_pdf.return_value = b'%PDF-fake'
        po = self._make_draft_po()
        self.assertEqual(po.status, PurchaseOrder.STATUS_DRAFT)

        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/send/',
            {'to': 'vendor@example.com', 'subject': 'PO', 'body': 'Hi'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_ISSUED)

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        self.assertEqual(call_kwargs.kwargs['to'], ['vendor@example.com'])
        self.assertEqual(call_kwargs.kwargs['subject'], 'PO')
        # PDF attached
        attachments = call_kwargs.kwargs['attachments']
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0][0], 'PO-TEST-SEND.pdf')

    @patch('apps.core.services.OutboundEmailService.send_tracked')
    @patch('apps.purchasing.pdf.generate_purchase_order_pdf')
    def test_send_issued_po_resends_without_status_change(self, mock_pdf, mock_send):
        mock_pdf.return_value = b'%PDF-fake'
        po = self._make_draft_po()
        po.status = PurchaseOrder.STATUS_ISSUED
        po.save()

        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/send/',
            {'to': 'vendor@example.com', 'subject': 'PO', 'body': 'Resend'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_ISSUED)
        mock_send.assert_called_once()

    @patch('apps.core.services.OutboundEmailService.send_tracked')
    @patch('apps.purchasing.pdf.generate_purchase_order_pdf')
    def test_send_creates_history_entry(self, mock_pdf, mock_send):
        mock_pdf.return_value = b'%PDF-fake'
        po = self._make_draft_po()

        self.client.post(
            f'/api/purchase-orders/{po.po_id}/send/',
            {'to': 'vendor@example.com', 'subject': 'PO', 'body': 'Hi'},
            format='json',
        )

        entry = HistoryEntry.objects.filter(
            object_type='purchaseorder',
            object_id=po.pk,
            entry_type='action',
        ).first()
        self.assertIsNotNone(entry)
        self.assertIn('vendor@example.com', entry.changes.get('_action', ''))

    def test_send_requires_to_field(self):
        po = self._make_draft_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/send/',
            {'subject': 'PO', 'body': 'Hi'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('to', response.data)

    def test_send_requires_subject_field(self):
        po = self._make_draft_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/send/',
            {'to': 'vendor@example.com', 'body': 'Hi'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('subject', response.data)

    def test_send_rejected_for_cancelled_po(self):
        po = self._make_draft_po()
        po.status = PurchaseOrder.STATUS_ISSUED
        po.save()
        from apps.purchasing.services import PurchaseOrderService
        PurchaseOrderService.cancel_po(po.pk)

        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/send/',
            {'to': 'v@example.com', 'subject': 'PO', 'body': 'Hi'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_send_requires_financials_permission(self):
        po = self._make_draft_po()
        worker = User.objects.get(username='johnq')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/send/',
            {'to': 'v@example.com', 'subject': 'PO', 'body': 'Hi'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)
