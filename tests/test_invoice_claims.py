from decimal import Decimal
from tests.base import BaseTestCase
from apps.invoicing.claims import InvoiceClaimService
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.jobs.models import Job


class InvoiceClaimServiceTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()

    def _make_invoice_line_with_source(self, job, source_type, source_pk, status):
        inv = Invoice.objects.create(job=job, status=status)
        li = InvoiceLineItem.objects.create(
            invoice=inv, description='x', qty=Decimal('1'),
            units='none', price=Decimal('5.00'),
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=li, source_type=source_type, source_pk=source_pk,
        )
        return inv

    def test_is_invoiced_true_for_live_source(self):
        self._make_invoice_line_with_source(
            self.job, InvoiceLineItemSource.SOURCE_TASK, 4242, Invoice.STATUS_DRAFT,
        )
        self.assertTrue(
            InvoiceClaimService.is_invoiced(InvoiceLineItemSource.SOURCE_TASK, 4242)
        )

    def test_is_invoiced_false_when_only_cancelled(self):
        self._make_invoice_line_with_source(
            self.job, InvoiceLineItemSource.SOURCE_TASK, 4243, Invoice.STATUS_CANCELLED,
        )
        self.assertFalse(
            InvoiceClaimService.is_invoiced(InvoiceLineItemSource.SOURCE_TASK, 4243)
        )

    def test_claims_for_job_keys_and_excludes_cancelled(self):
        self._make_invoice_line_with_source(
            self.job, InvoiceLineItemSource.SOURCE_MATERIAL, 11, Invoice.STATUS_DRAFT,
        )
        self._make_invoice_line_with_source(
            self.job, InvoiceLineItemSource.SOURCE_TASK, 22, Invoice.STATUS_CANCELLED,
        )
        claims = InvoiceClaimService.claims_for_job(self.job)
        self.assertIn((InvoiceLineItemSource.SOURCE_MATERIAL, 11), claims)
        self.assertNotIn((InvoiceLineItemSource.SOURCE_TASK, 22), claims)
        ref = claims[(InvoiceLineItemSource.SOURCE_MATERIAL, 11)]
        self.assertEqual(set(ref.keys()), {'invoice_id', 'invoice_number'})
