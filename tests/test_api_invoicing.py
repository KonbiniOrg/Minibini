from unittest.mock import patch, MagicMock
from apps.core.models import JobHistory
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, EmailRecord
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.jobs.models import Job


class InvoiceAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_invoices(self):
        response = self.client.get('/api/invoices/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_invoice(self):
        invoice = Invoice.objects.first()
        if invoice:
            response = self.client.get(f'/api/invoices/{invoice.pk}/')
            self.assertEqual(response.status_code, 200)
            self.assertIn('line_items', response.data)

    def test_add_line_item(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        invoice = Invoice.objects.create(
            job=job, invoice_number='INV-TEST-LI', status=Invoice.STATUS_DRAFT,
        )
        response = self.client.post(f'/api/invoices/{invoice.pk}/line-items/', {
            'qty': '1.00',
            'units': 'hours',
            'description': 'Consulting',
            'price': '150.00',
        }, format='json')
        self.assertIn(response.status_code, [200, 201])

    def test_cancel_invoice_requires_reason(self):
        invoice = Invoice.objects.first()
        if invoice:
            response = self.client.post(f'/api/invoices/{invoice.pk}/cancel/', {}, format='json')
            self.assertEqual(response.status_code, 400)

    def test_cancel_invoice_creates_history(self):
        invoice = Invoice.objects.filter(status='active').first()
        if invoice:
            self.client.post(f'/api/invoices/{invoice.pk}/cancel/', {
                'reason': 'Billed in error',
            }, format='json')
            entry = JobHistory.objects.filter(
                entry_type='audit', object_type='invoice', object_id=invoice.pk,
            ).first()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.text, 'Billed in error')
            self.assertEqual(entry.user, self.user)

    def test_discard_draft_returns_200_with_message(self):
        job = Job.objects.first()
        invoice = Invoice.objects.create(
            job=job, invoice_number='INV-DISCARD-001', status=Invoice.STATUS_DRAFT,
        )
        pk = invoice.pk
        response = self.client.delete(f'/api/invoices/{pk}/?confirm=true')
        self.assertEqual(response.status_code, 200)
        self.assertIn('message', response.data)
        self.assertFalse(Invoice.objects.filter(pk=pk).exists())

    def test_discard_non_draft_returns_400(self):
        job = Job.objects.first()
        invoice = Invoice.objects.create(
            job=job, invoice_number='INV-DISCARD-002', status=Invoice.STATUS_DRAFT,
        )
        Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.STATUS_OPEN)
        response = self.client.delete(f'/api/invoices/{invoice.pk}/?confirm=true')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())

    def test_due_date_and_is_late_for_unsent_invoice(self):
        job = Job.objects.first()
        invoice = Invoice.objects.create(
            job=job, invoice_number='INV-DUE-001', status=Invoice.STATUS_DRAFT,
        )
        response = self.client.get(f'/api/invoices/{invoice.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['due_date'])
        self.assertFalse(response.data['is_late'])

    def test_due_date_30_days_after_sent_and_late_when_unpaid(self):
        from datetime import timedelta
        from django.utils import timezone
        job = Job.objects.first()
        invoice = Invoice.objects.create(
            job=job, invoice_number='INV-DUE-002', status=Invoice.STATUS_OPEN,
        )
        sent = timezone.now() - timedelta(days=45)
        Invoice.objects.filter(pk=invoice.pk).update(sent_date=sent)
        response = self.client.get(f'/api/invoices/{invoice.pk}/')
        body = response.json()
        expected_due = (sent + timedelta(days=30)).date().isoformat()
        self.assertEqual(body['due_date'], expected_due)
        self.assertTrue(body['is_late'])

    def test_paid_invoice_is_not_late(self):
        from datetime import timedelta
        from django.utils import timezone
        job = Job.objects.first()
        invoice = Invoice.objects.create(
            job=job, invoice_number='INV-DUE-003', status=Invoice.STATUS_PAID,
        )
        sent = timezone.now() - timedelta(days=45)
        Invoice.objects.filter(pk=invoice.pk).update(sent_date=sent)
        response = self.client.get(f'/api/invoices/{invoice.pk}/')
        self.assertFalse(response.json()['is_late'])


class InvoiceSendTest(BaseTestCase):
    """New /api/invoices/{id}/send-defaults/ + /send/ endpoints. The send
    orchestrates QBO push (if qbo_id not already set), PDF rendering, and
    OutboundEmailService.send_tracked."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.admin = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.admin)
        self.job = Job.objects.first()
        from decimal import Decimal
        self.invoice = Invoice.objects.create(
            job=self.job, invoice_number='INV-SEND-001',
            status=Invoice.STATUS_DRAFT,
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=Decimal('1.00'),
            price=Decimal('100.00'), description='Test',
        )

    def test_send_defaults_returns_form_prefills(self):
        response = self.client.get(f'/api/invoices/{self.invoice.pk}/send-defaults/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('to', response.data)
        self.assertIn('subject', response.data)
        self.assertIn('body', response.data)
        self.assertIn('attachments_preview', response.data)
        # Two auto-attached PDFs: the QBO invoice + the local Job Statement.
        filenames = [a['filename'] for a in response.data['attachments_preview']]
        self.assertEqual(len(filenames), 2)

    @patch('apps.qbo.services.QBOService.get_client')
    @patch('apps.qbo.services.QBOInvoiceSyncService._build_qbo_invoice')
    @patch('apps.qbo.services.QBOInvoiceSyncService._mark_as_sent')
    @patch('apps.qbo.services.QBOInvoiceSyncService._download_qbo_pdf')
    @patch('apps.invoicing.pdf.generate_job_statement_pdf')
    @patch('django.core.mail.EmailMessage')
    def test_send_happy_path(
        self, MockEmailMessage, mock_stmt_pdf, mock_dl_pdf, mock_mark,
        mock_build, mock_get_client,
    ):
        MockEmailMessage.return_value = MagicMock()
        mock_stmt_pdf.return_value = b'%PDF-stmt'
        mock_dl_pdf.return_value = b'%PDF-qbo'
        qbo_invoice = MagicMock()
        qbo_invoice.Id = '42'
        qbo_invoice.save = MagicMock(return_value=qbo_invoice)
        mock_build.return_value = qbo_invoice
        mock_get_client.return_value = MagicMock()

        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/send/',
            {
                'to': 'customer@example.com',
                'subject': 'Invoice INV-SEND-001',
                'body': 'Pay link inside.',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.STATUS_OPEN)
        self.assertEqual(self.invoice.qbo_id, '42')

        outbound = EmailRecord.objects.get(
            direction=EmailRecord.OUTBOUND, job=self.job,
        )
        self.assertIsNotNone(outbound.sent_at)

    @patch('apps.qbo.services.QBOService.get_client')
    @patch('apps.qbo.services.QBOInvoiceSyncService._build_qbo_invoice')
    @patch('apps.qbo.services.QBOInvoiceSyncService._mark_as_sent')
    @patch('apps.qbo.services.QBOInvoiceSyncService._download_qbo_pdf')
    @patch('apps.invoicing.pdf.generate_job_statement_pdf')
    @patch('django.core.mail.EmailMessage')
    def test_send_with_qbo_id_set_skips_qbo_push(
        self, MockEmailMessage, mock_stmt_pdf, mock_dl_pdf, mock_mark,
        mock_build, mock_get_client,
    ):
        """Retry: qbo_id already set means skip the QBO push step (fixes
        the duplicate-push bug in the old code)."""
        self.invoice.qbo_id = '99'
        self.invoice.save()

        MockEmailMessage.return_value = MagicMock()
        mock_stmt_pdf.return_value = b'%PDF-stmt'
        mock_dl_pdf.return_value = b'%PDF-qbo'
        mock_get_client.return_value = MagicMock()

        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/send/',
            {'to': 'customer@example.com', 'subject': 'X', 'body': 'X'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

        # The build-QBO-invoice path should NOT have been called.
        mock_build.assert_not_called()
        mock_mark.assert_not_called()

        # PDF download still happens; outbound EmailRecord still created.
        mock_dl_pdf.assert_called_once()
        outbound = EmailRecord.objects.get(
            direction=EmailRecord.OUTBOUND, job=self.job,
        )
        self.assertIsNotNone(outbound.sent_at)

    def test_send_missing_to_returns_400(self):
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/send/',
            {'subject': 'X', 'body': 'X'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
