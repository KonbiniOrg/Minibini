from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job
from apps.contacts.models import Business
from apps.invoicing.models import Invoice, InvoiceLineItem


class InvoiceListAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()

    def _invoice(self, status=Invoice.STATUS_OPEN, sent_days_ago=10,
                 qty='2', price='50.00', paid=None):
        inv = Invoice.objects.create(job=self.job, status=status)
        if sent_days_ago is not None:
            inv.sent_date = timezone.now() - timedelta(days=sent_days_ago)
        if paid is not None:
            inv.qbo_amount_paid = Decimal(paid)
        inv.save()
        InvoiceLineItem.objects.create(
            invoice=inv, line_number=1, description='Work',
            qty=Decimal(qty), units='ea', price=Decimal(price),
        )
        return inv

    def test_list_returns_total_paid_balance_and_customer(self):
        inv = self._invoice(qty='2', price='50.00', paid='30.00')
        resp = self.client.get('/api/invoices/?summary=true&status=all')
        self.assertEqual(resp.status_code, 200)
        row = next(r for r in resp.data['results'] if r['invoice_id'] == inv.invoice_id)
        self.assertEqual(row['total'], '100.00')
        self.assertEqual(row['amount_paid'], '30.00')
        self.assertEqual(row['balance'], '70.00')
        self.assertIn('customer_name', row)
        self.assertIn('due_date', row)
        # list serializer is lightweight — no nested line_items
        self.assertNotIn('line_items', row)

    def test_null_qbo_amount_paid_treated_as_zero(self):
        inv = self._invoice(qty='1', price='40.00', paid=None)
        resp = self.client.get('/api/invoices/?summary=true&status=all')
        row = next(r for r in resp.data['results'] if r['invoice_id'] == inv.invoice_id)
        self.assertEqual(row['amount_paid'], '0.00')
        self.assertEqual(row['balance'], '40.00')

    def test_default_filter_is_open_plus_partly_paid(self):
        open_inv = self._invoice(status=Invoice.STATUS_OPEN)
        partly = self._invoice(status=Invoice.STATUS_PARTLY_PAID)
        draft = self._invoice(status=Invoice.STATUS_DRAFT, sent_days_ago=None)
        paid = self._invoice(status=Invoice.STATUS_PAID)
        resp = self.client.get('/api/invoices/?summary=true')  # no status param
        ids = {r['invoice_id'] for r in resp.data['results']}
        self.assertIn(open_inv.invoice_id, ids)
        self.assertIn(partly.invoice_id, ids)
        self.assertNotIn(draft.invoice_id, ids)
        self.assertNotIn(paid.invoice_id, ids)

    def test_status_paid_preset(self):
        paid = self._invoice(status=Invoice.STATUS_PAID)
        open_inv = self._invoice(status=Invoice.STATUS_OPEN)
        resp = self.client.get('/api/invoices/?summary=true&status=paid')
        ids = {r['invoice_id'] for r in resp.data['results']}
        self.assertIn(paid.invoice_id, ids)
        self.assertNotIn(open_inv.invoice_id, ids)

    def test_default_ordering_is_due_date_ascending(self):
        # earlier sent_date => earlier due_date => most overdue => first
        old = self._invoice(sent_days_ago=60)
        recent = self._invoice(sent_days_ago=5)
        resp = self.client.get('/api/invoices/?summary=true&status=open')
        ordered = [r['invoice_id'] for r in resp.data['results']]
        self.assertLess(ordered.index(old.invoice_id),
                        ordered.index(recent.invoice_id))

    def test_filter_by_business_rolls_up_contacts(self):
        contact = self.job.contact
        self.assertIsNotNone(contact)
        business = Business.objects.create(
            business_name='Test Rollup Co', default_contact=contact)
        contact.business = business
        contact.save()
        inv = self._invoice(status=Invoice.STATUS_OPEN)
        resp = self.client.get(
            f'/api/invoices/?summary=true&status=all&business={business.business_id}')
        ids = {r['invoice_id'] for r in resp.data['results']}
        self.assertIn(inv.invoice_id, ids)

    def test_filter_by_contact_exact(self):
        contact = self.job.contact
        inv = self._invoice(status=Invoice.STATUS_OPEN)
        resp = self.client.get(
            f'/api/invoices/?summary=true&status=all&contact={contact.contact_id}')
        ids = {r['invoice_id'] for r in resp.data['results']}
        self.assertIn(inv.invoice_id, ids)
