from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, HistoryEntry
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
            entry = HistoryEntry.objects.filter(
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
