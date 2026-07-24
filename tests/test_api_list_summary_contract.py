"""Guards the dual contract of the invoice list endpoint.

The financials A/R list page opts into a lightweight "summary" mode
(`?summary=true`): a summary serializer (no nested line_items), a default
status=open filter, presets, and due-date ordering.

WITHOUT `?summary=true` the endpoint must preserve its ORIGINAL contract —
the full serializer (with `line_items`) and ALL statuses — because pre-existing
consumers depend on it:
  - `/api/invoices/?job=`  -> Job overview (JobDetailPage): needs line_items +
    all statuses (draft detection, billed/paid rollups).

Regression: a change that switched the list action to the summary serializer +
default-open filter unconditionally broke those consumers (Job overview showed
an invoice with no line items / no totals).

(The parallel /api/bills/ contract was retired with the Bill domain —
bills live in QBO now.)
"""
from decimal import Decimal
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job
from apps.invoicing.models import Invoice, InvoiceLineItem


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
