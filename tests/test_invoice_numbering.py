"""QBO assigns invoice numbers. Drafts have no invoice_number (NULL) and
display a placeholder identity; the push writes QBO's DocNumber back."""
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.services import InvoiceEmailService
from apps.jobs.models import Job


class DraftNumberingTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(
            contact=self.contact, job_number='JOB-2026-0001',
        )
        self.job2 = Job.objects.create(
            contact=self.contact, job_number='JOB-2026-0002',
        )

    def test_new_draft_has_no_invoice_number(self):
        inv = Invoice.objects.create(job=self.job)
        self.assertIsNone(inv.invoice_number)

    def test_display_number_placeholder_for_draft(self):
        inv = Invoice.objects.create(job=self.job)
        self.assertEqual(inv.display_number, 'Draft — JOB-2026-0001')

    def test_display_number_uses_real_number_when_set(self):
        inv = Invoice.objects.create(job=self.job, invoice_number='1042')
        self.assertEqual(inv.display_number, '1042')

    def test_two_unnumbered_drafts_coexist(self):
        Invoice.objects.create(job=self.job)
        inv2 = Invoice.objects.create(job=self.job2)
        self.assertIsNone(inv2.invoice_number)
        self.assertEqual(Invoice.objects.count(), 2)

    def test_str_uses_display_number(self):
        inv = Invoice.objects.create(job=self.job)
        self.assertEqual(str(inv), 'Invoice Draft — JOB-2026-0001')


class DocNumberWritebackTest(TestCase):
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
        self.invoice = Invoice.objects.create(job=self.job)
        InvoiceLineItem.objects.create(
            invoice=self.invoice, description='Work', qty=Decimal('1'),
            price=Decimal('100.00'), accounting_category=self.category,
        )
        # Push path needs a QBO customer id on the business/contact chain.
        self.contact.qbo_customer_id = '77'
        self.contact.save()

    def _send(self, subject='S', body='B', **extra_patches):
        with patch('apps.core.services.OutboundEmailService.send_tracked') as mock_send, \
             patch('apps.qbo.services.QBOInvoiceSyncService._download_qbo_pdf', return_value=b'%PDF-q'), \
             patch('apps.qbo.services.QBOInvoiceSyncService._fetch_invoice_link', return_value='https://pay/1'), \
             patch('apps.qbo.services.QBOInvoiceSyncService._mark_as_sent'), \
             patch('apps.qbo.services.QBOInvoiceSyncService._build_qbo_invoice') as mock_build, \
             patch('apps.qbo.services.QBOService.get_client') as mock_client:
            mock_client.return_value = MagicMock()
            mock_send.return_value = MagicMock()
            qbo_invoice = MagicMock()
            qbo_invoice.Id = '42'
            qbo_invoice.DocNumber = '1042'
            qbo_invoice.save = MagicMock()
            mock_build.return_value = qbo_invoice
            fetched = extra_patches.pop('fetched', None)
            if fetched is not None:
                with patch('quickbooks.objects.invoice.Invoice.get',
                           return_value=fetched):
                    InvoiceEmailService.send_invoice(
                        self.invoice, to='jane@example.com',
                        subject=subject, body=body,
                    )
            else:
                InvoiceEmailService.send_invoice(
                    self.invoice, to='jane@example.com',
                    subject=subject, body=body,
                )
            return mock_send

    def test_push_writes_back_doc_number(self):
        self._send()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.invoice_number, '1042')
        self.assertEqual(self.invoice.qbo_id, '42')

    def test_attachment_is_qbo_invoice_pdf_only(self):
        mock_send = self._send()
        filenames = [a[0] for a in mock_send.call_args.kwargs['attachments']]
        self.assertEqual(filenames, ['Invoice-1042.pdf'])

    def test_retry_backfills_doc_number_from_qbo(self):
        self.invoice.qbo_id = '42'
        self.invoice.save()
        fetched = MagicMock()
        fetched.DocNumber = '1042'
        self._send(fetched=fetched)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.invoice_number, '1042')

    def test_send_substitutes_number_tokens_at_send_time(self):
        """{document_number}/{invoice_number} survive the compose dialog as
        literal tokens (the draft has no number yet) and are substituted
        with QBO's DocNumber during the send."""
        mock_send = self._send(
            subject='Invoice {document_number} for JOB-2026-0001',
            body='Invoice {invoice_number} attached.',
        )
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs['subject'], 'Invoice 1042 for JOB-2026-0001')
        self.assertEqual(kwargs['body'], 'Invoice 1042 attached.')


class EmailDefaultsDraftTest(TestCase):
    def setUp(self):
        contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(
            contact=contact, job_number='JOB-2026-0001',
        )
        self.invoice = Invoice.objects.create(job=self.job)

    def test_defaults_keep_number_tokens_literal(self):
        """The number doesn't exist at compose time — the tokens survive
        into the dialog and are substituted at send (like {payment_link})."""
        defaults = InvoiceEmailService.get_email_defaults(self.invoice)
        self.assertIn('{document_number}', defaults['subject'])
        self.assertNotIn('Draft —', defaults['subject'])
