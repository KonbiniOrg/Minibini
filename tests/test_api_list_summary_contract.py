"""Guards the dual contract of the invoice/bill list endpoints.

The financials A/R and A/P list pages opt into a lightweight "summary" mode
(`?summary=true`): a summary serializer (no nested line_items), a default
status=open filter, presets, and due-date ordering.

WITHOUT `?summary=true` the endpoints must preserve their ORIGINAL contract —
the full serializer (with `line_items`) and ALL statuses — because pre-existing
consumers depend on it:
  - `/api/invoices/?job=`  -> Job overview (JobDetailPage): needs line_items +
    all statuses (draft detection, billed/paid rollups).
  - `/api/bills/?business=` / `?contact=` / bare -> Business/Contact detail bill
    panels and the email-associate-bill picker.

Regression: a change that switched the list action to the summary serializer +
default-open filter unconditionally broke those consumers (Job overview showed
an invoice with no line items / no totals).
"""
from decimal import Decimal
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.contacts.models import Business
from apps.purchasing.models import Bill, BillLineItem


class InvoiceListContractTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.job = Job.objects.first()

    def _invoice(self, status, qty, price):
        inv = Invoice.objects.create(job=self.job, status=status)
        InvoiceLineItem.objects.create(
            invoice=inv, line_number=1, description='Work',
            qty=Decimal(qty), units='ea', price=Decimal(price))
        return inv

    def test_job_scoped_default_returns_full_serializer_and_all_statuses(self):
        """The Job-overview contract: no ?summary -> line_items present, every
        status visible (not filtered to open)."""
        draft = self._invoice(Invoice.STATUS_DRAFT, '2', '100.00')
        paid = self._invoice(Invoice.STATUS_PAID, '1', '50.00')
        open_inv = self._invoice(Invoice.STATUS_OPEN, '1', '25.00')

        resp = self.client.get(f'/api/invoices/?job={self.job.job_id}')
        self.assertEqual(resp.status_code, 200)
        rows = {r['invoice_id']: r for r in resp.data['results']}

        # All statuses present (NOT filtered down to open).
        for inv in (draft, paid, open_inv):
            self.assertIn(inv.invoice_id, rows,
                          f'{inv.status} invoice missing from job-scoped list')

        # Full serializer: line_items present and populated.
        self.assertIn('line_items', rows[draft.invoice_id])
        self.assertEqual(len(rows[draft.invoice_id]['line_items']), 1)
        self.assertEqual(rows[draft.invoice_id]['line_items'][0]['price'], '100.00')

    def test_summary_mode_is_lightweight_and_defaults_open(self):
        """The financials A/R contract: ?summary=true -> no line_items, default
        filter is open(+partly-paid)."""
        draft = self._invoice(Invoice.STATUS_DRAFT, '2', '100.00')
        open_inv = self._invoice(Invoice.STATUS_OPEN, '1', '25.00')

        resp = self.client.get('/api/invoices/?summary=true')
        self.assertEqual(resp.status_code, 200)
        ids = {r['invoice_id'] for r in resp.data['results']}
        self.assertIn(open_inv.invoice_id, ids)
        self.assertNotIn(draft.invoice_id, ids)  # default-open excludes draft
        row = next(r for r in resp.data['results']
                   if r['invoice_id'] == open_inv.invoice_id)
        self.assertNotIn('line_items', row)       # summary serializer
        self.assertIn('balance', row)


class BillListContractTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.vendor = Business.objects.first()

    def _bill(self, status, qty, price, number):
        bill = Bill.objects.create(
            business=self.vendor, vendor_invoice_number=number, status=status)
        BillLineItem.objects.create(
            bill=bill, line_number=1, description='Parts',
            qty=Decimal(qty), units='ea', price=Decimal(price))
        return bill

    def test_business_scoped_default_returns_full_serializer_and_all_statuses(self):
        """Business/Contact detail + email-associate contract: no ?summary ->
        line_items present, every status visible."""
        draft = self._bill(Bill.STATUS_DRAFT, '2', '25.00', 'V-D')
        paid = self._bill(Bill.STATUS_PAID_IN_FULL, '1', '10.00', 'V-P')
        received = self._bill(Bill.STATUS_RECEIVED, '1', '5.00', 'V-R')

        resp = self.client.get(f'/api/bills/?business={self.vendor.business_id}')
        self.assertEqual(resp.status_code, 200)
        rows = {r['bill_id']: r for r in resp.data['results']}
        for bill in (draft, paid, received):
            self.assertIn(bill.bill_id, rows,
                          f'{bill.status} bill missing from business-scoped list')
        self.assertIn('line_items', rows[draft.bill_id])
        self.assertEqual(len(rows[draft.bill_id]['line_items']), 1)

    def test_summary_mode_is_lightweight_and_defaults_open(self):
        draft = self._bill(Bill.STATUS_DRAFT, '2', '25.00', 'V-SD')
        received = self._bill(Bill.STATUS_RECEIVED, '1', '5.00', 'V-SR')

        resp = self.client.get('/api/bills/?summary=true')
        self.assertEqual(resp.status_code, 200)
        ids = {r['bill_id'] for r in resp.data['results']}
        self.assertIn(received.bill_id, ids)
        self.assertNotIn(draft.bill_id, ids)  # default-open excludes draft
        row = next(r for r in resp.data['results']
                   if r['bill_id'] == received.bill_id)
        self.assertNotIn('line_items', row)
        self.assertIn('balance', row)
