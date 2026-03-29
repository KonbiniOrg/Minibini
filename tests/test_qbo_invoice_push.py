from unittest.mock import patch, MagicMock, ANY
from decimal import Decimal
from django.test import TestCase
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration, AccountingCategory
from apps.qbo.services import QBOInvoiceSyncService
from apps.qbo.models import QBOSyncLog


class InvoiceQBOFieldsTest(TestCase):
    """Test QBO tracking fields on Invoice model."""

    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme Corp', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(job_number='JOB-2026-0001', contact=self.contact)

    def test_invoice_has_qbo_id(self):
        inv = Invoice.objects.create(job=self.job)
        self.assertEqual(inv.qbo_id, '')

    def test_invoice_has_qbo_payment_status(self):
        inv = Invoice.objects.create(job=self.job)
        self.assertEqual(inv.qbo_payment_status, '')

    def test_invoice_has_qbo_amount_paid(self):
        inv = Invoice.objects.create(job=self.job)
        self.assertIsNone(inv.qbo_amount_paid)

    def test_invoice_can_store_qbo_data(self):
        inv = Invoice.objects.create(job=self.job)
        inv.qbo_id = '12345'
        inv.qbo_payment_status = 'Paid'
        inv.qbo_amount_paid = 4250.00
        inv.save()
        inv.refresh_from_db()
        self.assertEqual(inv.qbo_id, '12345')
        self.assertEqual(inv.qbo_payment_status, 'Paid')
        self.assertEqual(inv.qbo_amount_paid, 4250.00)

    def test_customer_business_chain(self):
        """Can traverse Invoice → Job → Contact → Business."""
        inv = Invoice.objects.create(job=self.job)
        business = inv.job.contact.business
        self.assertEqual(business.business_name, 'Acme Corp')


class QBOInvoicePushTest(TestCase):
    """Test pushing an invoice to QBO."""

    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.cat_cnc = AccountingCategory.objects.create(
            code='CNC', name='CNC Machining', taxable=True,
            qbo_item_id='100',
        )
        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme Corp', default_contact=self.contact,
            qbo_customer_id='42',
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(contact=self.contact, job_number='JOB-2026-0001')
        self.invoice = Invoice.objects.create(job=self.job)
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=1, price=Decimal('500.00'),
            description='CNC work', accounting_category=self.cat_cnc,
        )

    @patch('apps.qbo.services.QBOService.get_client')
    @patch('apps.invoicing.pdf.generate_job_statement_pdf')
    def test_push_invoice_stores_qbo_id(self, mock_pdf, mock_get_client):
        """push_invoice creates QBO invoice and stores the ID."""
        mock_pdf.return_value = b'%PDF-fake'
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_qbo_invoice = MagicMock()
        mock_qbo_invoice.Id = '999'
        mock_qbo_invoice.save = MagicMock(return_value=mock_qbo_invoice)

        with patch('apps.qbo.services.QBOInvoiceSyncService._build_qbo_invoice',
                   return_value=mock_qbo_invoice):
            with patch('apps.qbo.services.QBOInvoiceSyncService._attach_pdf'):
                with patch('apps.qbo.services.QBOInvoiceSyncService._send_invoice'):
                    QBOInvoiceSyncService.push_invoice(
                        self.invoice,
                        send_to='john@example.com',
                    )

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.qbo_id, '999')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_invoice_skips_if_already_synced(self, mock_get_client):
        """push_invoice returns existing ID if already synced."""
        self.invoice.qbo_id = '999'
        self.invoice.save()

        result = QBOInvoiceSyncService.push_invoice(self.invoice, send_to='x@x.com')
        self.assertEqual(result, '999')
        mock_get_client.assert_not_called()

    @patch('apps.qbo.services.QBOService.get_client')
    @patch('apps.invoicing.pdf.generate_job_statement_pdf')
    def test_push_invoice_logs_success(self, mock_pdf, mock_get_client):
        """push_invoice creates a sync log entry on success."""
        mock_pdf.return_value = b'%PDF-fake'
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_qbo_invoice = MagicMock()
        mock_qbo_invoice.Id = '999'
        mock_qbo_invoice.save = MagicMock(return_value=mock_qbo_invoice)

        with patch('apps.qbo.services.QBOInvoiceSyncService._build_qbo_invoice',
                   return_value=mock_qbo_invoice):
            with patch('apps.qbo.services.QBOInvoiceSyncService._attach_pdf'):
                with patch('apps.qbo.services.QBOInvoiceSyncService._send_invoice'):
                    QBOInvoiceSyncService.push_invoice(
                        self.invoice, send_to='john@example.com',
                    )

        log = QBOSyncLog.objects.get(entity_type='invoice')
        self.assertEqual(log.status, 'success')
        self.assertEqual(log.qbo_entity_id, '999')

    def test_push_invoice_requires_customer_synced(self):
        """push_invoice raises if customer business has no qbo_customer_id."""
        self.business.qbo_customer_id = ''
        self.business.save()

        with self.assertRaises(ValueError) as ctx:
            QBOInvoiceSyncService.push_invoice(self.invoice, send_to='x@x.com')
        self.assertIn('customer', str(ctx.exception).lower())

    def test_push_invoice_requires_connection(self):
        """push_invoice raises if no active QBO connection."""
        with self.assertRaises(ValueError):
            QBOInvoiceSyncService.push_invoice(self.invoice, send_to='x@x.com')
