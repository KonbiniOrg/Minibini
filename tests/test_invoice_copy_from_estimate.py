"""
Tests for InvoiceService.copy_from_estimate and the copy-from-estimate action.

Covers:
- Accepted estimate with base + adjustment line → invoice gets matching lines;
  the adjustment line carries adjustment_service; agreement-adjustments reports
  already_added (no double-copy).
- 400 when the invoice already has a line.
- 400 when another non-cancelled invoice exists for the job.
- InvoiceSerializer.job_has_other_invoices: true with a sibling invoice, false otherwise.
"""
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import User, Configuration, AppState, AccountingCategory
from apps.contacts.models import Contact
from apps.jobs.models import Job, RateScheme
from apps.estimates.models import Estimate, EstimateLineItem
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.services import InvoiceService


class InvoiceCopyFromEstimateServiceTest(TestCase):
    """Unit tests for InvoiceService.copy_from_estimate."""

    def setUp(self):
        Configuration.objects.create(
            key='invoice_number_sequence', value='INV-{year}-{counter:04d}',
        )
        AppState.objects.create(key='invoice_counter', value='0')

        self.cat = AccountingCategory.objects.create(
            code='LAB-CF', name='Labor-CF', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='Copy', last_name='Test', email='copy@test.com',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-CF-0001',
        )

        # An accepted estimate with a base line ($100) and a 10% adjustment.
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-CF-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, qty=Decimal('2'),
            units='hr', description='Labor hours', price=Decimal('50.00'),
            accounting_category=self.cat,
        )
        self.rush_svc = RateScheme.objects.create(
            name='Rush-CF', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%',
            accounting_category=self.cat,
        )
        # The estimate's adjustment line (10% of 100 = 10).
        self.adj_line = EstimateLineItem.objects.create(
            estimate=self.est, line_number=2, qty=Decimal('1'),
            units='%', description='Rush 10%', price=Decimal('10.00'),
            adjustment_service=self.rush_svc,
            adjustment_percent=self.rush_svc.rate,
        )
        # Add a target category for the adjustment.
        self.adj_line.adjustment_target_categories.set([self.cat])

        # A fresh draft invoice for the job.
        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT,
        )

    def test_copy_creates_base_and_adjustment_lines(self):
        """copy_from_estimate creates matching lines for base + adjustment."""
        created = InvoiceService.copy_from_estimate(self.invoice)
        self.assertEqual(created, 2)

        lines = list(
            InvoiceLineItem.objects.filter(invoice=self.invoice).order_by('line_number')
        )
        self.assertEqual(len(lines), 2)

        # Base line.
        base = lines[0]
        self.assertEqual(base.line_number, 1)
        self.assertEqual(base.description, 'Labor hours')
        self.assertEqual(base.qty, Decimal('2'))
        self.assertEqual(base.price, Decimal('50.00'))
        self.assertEqual(base.units, 'hr')
        self.assertEqual(base.accounting_category_id, self.cat.pk)
        self.assertIsNone(base.adjustment_service_id)

        # Adjustment line.
        adj = lines[1]
        self.assertEqual(adj.line_number, 2)
        self.assertEqual(adj.adjustment_service_id, self.rush_svc.pk)
        # target categories should be set.
        self.assertIn(
            self.cat.pk,
            list(adj.adjustment_target_categories.values_list('pk', flat=True)),
        )

    def test_copy_carries_adjustment_percent_snapshot(self):
        """copy_from_estimate carries the estimate line's adjustment_percent
        snapshot onto the invoice line — not a fresh read of the scheme's
        current rate. Changing the preset afterward must not move the
        already-copied invoice line."""
        InvoiceService.copy_from_estimate(self.invoice)
        adj = InvoiceLineItem.objects.get(
            invoice=self.invoice, adjustment_service=self.rush_svc,
        )
        self.assertEqual(adj.adjustment_percent, Decimal('10.00'))

        # Editing the preset after the copy must not retroactively change
        # the snapshot already carried onto the invoice line.
        self.rush_svc.rate = Decimal('77.00')
        self.rush_svc.save()
        adj.refresh_from_db()
        self.assertEqual(adj.adjustment_percent, Decimal('10.00'))

    def test_adjustment_line_is_already_added_after_copy(self):
        """After copy, agreement-adjustments should see the copied adjustment as already_added."""
        from apps.estimates.agreement import compose_agreement
        InvoiceService.copy_from_estimate(self.invoice)

        existing_svc_ids = set(
            InvoiceLineItem.objects
            .filter(invoice=self.invoice, adjustment_service__isnull=False)
            .values_list('adjustment_service_id', flat=True)
        )
        agreement = compose_agreement(self.invoice.job)
        adj_lines = [l for l in agreement['lines'] if l.get('is_adjustment')]
        self.assertEqual(len(adj_lines), 1)
        self.assertIn(adj_lines[0]['adjustment_service_id'], existing_svc_ids)

    def test_copy_creates_no_source_rows_for_plain_lines(self):
        """A plain hand line copies as a bare invoice line — no
        InvoiceLineItemSource row of any kind is created."""
        from apps.invoicing.models import InvoiceLineItemSource
        InvoiceService.copy_from_estimate(self.invoice)
        self.assertFalse(
            InvoiceLineItemSource.objects.filter(
                invoice_line_item__invoice=self.invoice,
            ).exists()
        )

    def test_copy_ignores_legacy_fee_source_row(self):
        """A legacy SOURCE_FEE row on an estimate hand-line no longer
        transits into an invoice fee claim — the source_fee_id channel is
        gone. The document line still copies; the Fee is simply not
        claimed."""
        from apps.estimates.models import EstimateLineItemSource
        from apps.invoicing.models import InvoiceLineItemSource
        from apps.jobs.models import Fee

        hand_line = EstimateLineItem.objects.create(
            estimate=self.est, line_number=3, qty=Decimal('1'),
            units='ea', description='Rush handling', price=Decimal('75.00'),
            accounting_category=self.cat,
        )
        fee = Fee.objects.create(
            job=self.job, description='Rush handling', quantity=Decimal('1'),
            unit_rate=Decimal('75.00'), accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=hand_line,
            source_type=EstimateLineItemSource.SOURCE_FEE,
            source_pk=fee.pk,
        )

        created = InvoiceService.copy_from_estimate(self.invoice)
        self.assertEqual(created, 3)
        self.assertFalse(
            InvoiceLineItemSource.objects.filter(
                source_type=InvoiceLineItemSource.SOURCE_FEE,
            ).exists()
        )

    def test_400_when_invoice_already_has_lines(self):
        """copy_from_estimate raises ValidationError when invoice already has lines."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1, qty=Decimal('1'),
            units='ea', description='Existing line', price=Decimal('99.00'),
        )
        with self.assertRaises(ValidationError):
            InvoiceService.copy_from_estimate(self.invoice)

    def test_400_when_another_non_cancelled_invoice_exists(self):
        """copy_from_estimate raises ValidationError when another non-cancelled invoice exists."""
        # Change the current draft to open (simulate a sent invoice).
        # We need a second invoice — first mark the original as open by direct update,
        # then create a new draft.
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.STATUS_OPEN)
        self.invoice.refresh_from_db()

        second_invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT,
        )
        with self.assertRaises(ValidationError):
            InvoiceService.copy_from_estimate(second_invoice)

    def test_no_error_when_only_cancelled_sibling_exists(self):
        """copy_from_estimate succeeds when the only other invoice is cancelled."""
        # Change the current invoice to cancelled.
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.STATUS_CANCELLED)

        # Create a fresh draft.
        new_invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT,
        )
        created = InvoiceService.copy_from_estimate(new_invoice)
        self.assertEqual(created, 2)


class InvoiceCopyFromEstimateAPITest(TestCase):
    """API tests for POST /api/invoices/{id}/copy-from-estimate/."""

    def setUp(self):
        Configuration.objects.create(
            key='invoice_number_sequence', value='INV-{year}-{counter:04d}',
        )
        AppState.objects.create(key='invoice_counter', value='0')

        self.cat = AccountingCategory.objects.create(
            code='LAB-API', name='Labor-API', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='Api', last_name='Test', email='api@test.com',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-CF-API-001',
        )

        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-CF-API-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, qty=Decimal('1'),
            units='ea', description='Base', price=Decimal('200.00'),
            accounting_category=self.cat,
        )
        self.rush_svc = RateScheme.objects.create(
            name='Rush-API', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('15.00'), unit_label='%',
            accounting_category=self.cat,
        )
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=2, qty=Decimal('1'),
            units='%', description='Rush 15%', price=Decimal('30.00'),
            adjustment_service=self.rush_svc,
            adjustment_percent=self.rush_svc.rate,
        )

        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT,
        )

        self.user = User.objects.create_user(username='fin-api', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials')
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_copy_from_estimate_success(self):
        """POST copy-from-estimate → 200 with created count."""
        resp = self.client.post(
            f'/api/invoices/{self.invoice.pk}/copy-from-estimate/',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['created'], 2)

        lines = list(
            InvoiceLineItem.objects.filter(invoice=self.invoice).order_by('line_number')
        )
        self.assertEqual(len(lines), 2)
        self.assertIsNone(lines[0].adjustment_service_id)
        self.assertEqual(lines[1].adjustment_service_id, self.rush_svc.pk)

    def test_copy_from_estimate_dedup_agreement_adjustments(self):
        """After copy, agreement-adjustments endpoint reports already_added=True."""
        self.client.post(f'/api/invoices/{self.invoice.pk}/copy-from-estimate/')
        resp = self.client.get(f'/api/invoices/{self.invoice.pk}/agreement-adjustments/')
        self.assertEqual(resp.status_code, 200, resp.data)
        adjustments = resp.data['adjustments']
        self.assertEqual(len(adjustments), 1)
        self.assertTrue(adjustments[0]['already_added'])

    def test_400_already_has_lines(self):
        """copy-from-estimate returns 400 when invoice already has lines."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1, qty=Decimal('1'),
            units='ea', description='Existing', price=Decimal('5.00'),
        )
        resp = self.client.post(
            f'/api/invoices/{self.invoice.pk}/copy-from-estimate/',
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('detail', resp.data)

    def test_400_sibling_non_cancelled_invoice(self):
        """copy-from-estimate returns 400 when another non-cancelled invoice exists."""
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.STATUS_OPEN)
        second = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        resp = self.client.post(
            f'/api/invoices/{second.pk}/copy-from-estimate/',
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn('detail', resp.data)


class InvoiceJobHasOtherInvoicesSerializerTest(TestCase):
    """Tests for InvoiceSerializer.job_has_other_invoices field."""

    def setUp(self):
        Configuration.objects.create(
            key='invoice_number_sequence', value='INV-{year}-{counter:04d}',
        )
        AppState.objects.create(key='invoice_counter', value='0')

        self.contact = Contact.objects.create(
            first_name='Ser', last_name='Test', email='ser@test.com',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-SER-001',
        )

        self.user = User.objects.create_user(username='fin-ser', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials')
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_no_sibling_returns_false(self):
        """job_has_other_invoices is false when this is the only invoice."""
        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        resp = self.client.get(f'/api/invoices/{invoice.pk}/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(resp.data['job_has_other_invoices'])

    def test_sibling_non_cancelled_returns_true(self):
        """job_has_other_invoices is true when a non-cancelled sibling exists."""
        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        # Change to open to allow creating a second invoice.
        Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.STATUS_OPEN)
        second = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

        resp = self.client.get(f'/api/invoices/{second.pk}/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data['job_has_other_invoices'])

    def test_cancelled_sibling_returns_false(self):
        """job_has_other_invoices is false when the only sibling is cancelled."""
        invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.STATUS_CANCELLED)
        second = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

        resp = self.client.get(f'/api/invoices/{second.pk}/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(resp.data['job_has_other_invoices'])
