"""The invoice email carries QBO's hosted-invoice payment link via the
{payment_link} template placeholder, substituted at send time."""
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.services import InvoiceEmailService
from apps.jobs.models import Job
from apps.qbo.services import QBOInvoiceSyncService


class FetchInvoiceLinkTest(TestCase):
    def _client(self, payload):
        client = MagicMock()
        client.api_url = 'https://sandbox-quickbooks.api.intuit.com/v3'
        client.company_id = '9130'
        client.get.return_value = payload
        return client

    def test_returns_link(self):
        # QBO's raw JSON uses 'InvoiceLink' (capital I) despite docs/SDK
        # widely showing 'invoiceLink' — observed live in sandbox 2026-07-22.
        client = self._client(
            {'Invoice': {'Id': '42', 'InvoiceLink': 'https://pay.example/i/42'}})
        link = QBOInvoiceSyncService._fetch_invoice_link(client, '42')
        self.assertEqual(link, 'https://pay.example/i/42')
        url = client.get.call_args.args[0]
        self.assertIn('/invoice/42', url)
        params = client.get.call_args.kwargs.get('params')
        self.assertEqual(params.get('include'), 'invoiceLink')
        # invoiceLink is silently omitted without a minorversion >= 36 —
        # QBO returns the invoice fine, just without the link.
        self.assertGreaterEqual(int(params.get('minorversion')), 36)

    def test_returns_empty_when_absent(self):
        client = self._client({'Invoice': {'Id': '42'}})
        self.assertEqual(
            QBOInvoiceSyncService._fetch_invoice_link(client, '42'), '')

    def test_tolerates_lowercase_key(self):
        client = self._client(
            {'Invoice': {'Id': '42', 'invoiceLink': 'https://pay.example/i/42'}})
        self.assertEqual(
            QBOInvoiceSyncService._fetch_invoice_link(client, '42'),
            'https://pay.example/i/42')


class SendSubstitutesPaymentLinkTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(
            contact=self.contact, job_number='JOB-2026-0001',
        )
        self.category = AccountingCategory.objects.create(
            code='SVC', name='Service', taxable=True, qbo_item_id='55',
        )
        self.invoice = Invoice.objects.create(
            job=self.job, invoice_number='INV-PAY-1', qbo_id='42',
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice, description='Work', qty=Decimal('1'),
            price=Decimal('100.00'), accounting_category=self.category,
        )

    @patch('apps.core.services.OutboundEmailService.send_tracked')
    @patch('apps.qbo.services.QBOInvoiceSyncService._download_qbo_pdf', return_value=b'%PDF-q')
    @patch('apps.qbo.services.QBOInvoiceSyncService._fetch_invoice_link',
           return_value='https://pay.example/i/42')
    @patch('apps.qbo.services.QBOService.get_client')
    def test_placeholder_substituted_in_body_and_subject(
        self, mock_client, mock_link, mock_pdf, mock_send,
    ):
        mock_client.return_value = MagicMock()
        mock_send.return_value = MagicMock()
        InvoiceEmailService.send_invoice(
            self.invoice, to='jane@example.com',
            subject='Invoice ({payment_link})',
            body='Pay here: {payment_link}',
        )
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs['body'], 'Pay here: https://pay.example/i/42')
        self.assertEqual(kwargs['subject'],
                         'Invoice (https://pay.example/i/42)')

    @patch('apps.core.services.OutboundEmailService.send_tracked')
    @patch('apps.qbo.services.QBOInvoiceSyncService._download_qbo_pdf', return_value=b'%PDF-q')
    @patch('apps.qbo.services.QBOInvoiceSyncService._fetch_invoice_link',
           return_value='https://pay.example/i/42')
    @patch('apps.qbo.services.QBOService.get_client')
    def test_body_without_placeholder_unchanged(
        self, mock_client, mock_link, mock_pdf, mock_send,
    ):
        mock_client.return_value = MagicMock()
        mock_send.return_value = MagicMock()
        InvoiceEmailService.send_invoice(
            self.invoice, to='jane@example.com',
            subject='Invoice', body='No link here.',
        )
        self.assertEqual(mock_send.call_args.kwargs['body'], 'No link here.')

    def test_default_body_advertises_payment_link(self):
        self.assertIn('{payment_link}', InvoiceEmailService.DEFAULT_BODY)
