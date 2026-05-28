"""Tests for the all-deliverables-shipped completion gate.

Covers:
  - Invoice-paid path does NOT auto-complete a job whose deliverables aren't
    all picked up yet.
  - Marking the final shipment picked up completes a job whose invoices are
    already all paid.
  - Invoice-paid path DOES complete a job whose deliverables are all shipped
    (i.e. the check fires when invoices resolve last).
  - Manual JobService.update_job with STATUS_COMPLETED raises ValidationError
    when deliverables aren't fully shipped.
  - A cancelled job with a paid invoice stays cancelled (unchanged behaviour).
  - Jobs with no deliverables still auto-complete on the invoice-paid path
    (all_deliverables_shipped → True trivially).
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import Configuration
from apps.deliverables.models import Deliverable, Shipment
from apps.deliverables.services import ShipmentService
from apps.estimates.models import Estimate
from apps.invoicing.models import Invoice
from apps.jobs.models import Job
from apps.jobs.services import JobService


def _setup_configs():
    """Ensure Configuration rows needed by NumberGenerationService exist."""
    Configuration.objects.get_or_create(
        key='invoice_number_sequence',
        defaults={'value': 'INV-{year}-{counter:04d}'},
    )
    Configuration.objects.get_or_create(
        key='invoice_counter',
        defaults={'value': '0'},
    )
    Configuration.objects.get_or_create(
        key='job_number_sequence',
        defaults={'value': 'JOB-{year}-{counter:04d}'},
    )
    Configuration.objects.get_or_create(
        key='job_counter',
        defaults={'value': '0'},
    )


def _make_job(contact, status=Job.STATUS_WORK_COMPLETE, suffix=''):
    """Create a Job and walk it to *status* via raw .save() (no service side-effects)."""
    idx = Job.objects.count()
    job = Job(
        job_number=f'J-CG-{idx}{suffix}',
        contact=contact,
        status=Job.STATUS_APPROVED,
    )
    job.save()
    path = [
        Job.STATUS_IN_PROGRESS,
        Job.STATUS_WORK_COMPLETE,
    ]
    for s in path:
        job.status = s
        job.save()
        if s == status:
            break
    return job


def _accepted_estimate(job, suffix=''):
    """Attach a fresh accepted Estimate to *job* (needed for shipment creation)."""
    Estimate.objects.filter(job=job).delete()
    idx = Estimate.objects.count()
    return Estimate.objects.create(
        job=job,
        estimate_number=f'EST-CG-{idx}{suffix}',
        version=1,
        status=Estimate.STATUS_ACCEPTED,
    )


def _pay_invoice(job):
    """Create an invoice and mark it paid (fires Invoice.save → _maybe_complete_job)."""
    idx = Invoice.objects.count()
    inv = Invoice.objects.create(
        job=job,
        invoice_number=f'INV-CG-{idx}',
        status=Invoice.STATUS_OPEN,
    )
    inv.status = Invoice.STATUS_PAID
    inv.save()
    return inv


def _make_shipment_picked_up(job, deliverable, qty):
    """Create a prepared shipment with one item, then mark it picked up."""
    shipment = ShipmentService.create(job_id=job.pk)
    ShipmentService.add_item(
        shipment=shipment,
        deliverable_id=deliverable.pk,
        qty=qty,
    )
    ShipmentService.mark_picked_up(shipment.pk)
    shipment.refresh_from_db()
    return shipment


class CompletionGateSetUp(TestCase):
    """Shared setUp for all completion gate tests."""

    def setUp(self):
        _setup_configs()
        self.contact = Contact.objects.create(
            first_name='Gate', last_name='Tester', email=f'gate{Contact.objects.count()}@test.com',
        )


class InvoicePaidDoesNotCompleteWhenDeliverableUnshipped(CompletionGateSetUp):
    """Paying all invoices should NOT complete the job if deliverables remain."""

    def setUp(self):
        super().setUp()
        self.job = _make_job(self.contact)
        _accepted_estimate(self.job)
        # One deliverable, NOT yet shipped
        self.deliverable = Deliverable.objects.create(
            job=self.job, description='Widget', qty_ordered=Decimal('5'), units='ea',
        )

    def test_job_stays_work_complete_when_invoice_paid_but_unshipped(self):
        _pay_invoice(self.job)
        self.job.refresh_from_db()
        self.assertEqual(
            self.job.status,
            Job.STATUS_WORK_COMPLETE,
            'Job should remain work_complete when deliverables are not fully shipped.',
        )


class ShipmentPickedUpCompletesFullyPaidJob(CompletionGateSetUp):
    """Marking the final shipment picked up should complete a job whose invoices are all paid."""

    def setUp(self):
        super().setUp()
        self.job = _make_job(self.contact)
        _accepted_estimate(self.job)
        self.deliverable = Deliverable.objects.create(
            job=self.job, description='Chair', qty_ordered=Decimal('3'), units='ea',
        )
        # Pay the invoice first — job should NOT complete yet
        _pay_invoice(self.job)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_WORK_COMPLETE)

    def test_final_shipment_pickup_completes_job(self):
        _make_shipment_picked_up(self.job, self.deliverable, Decimal('3'))
        self.job.refresh_from_db()
        self.assertEqual(
            self.job.status,
            Job.STATUS_COMPLETED,
            'Job should complete once the final shipment is picked up and all invoices are paid.',
        )


class InvoicePaidCompletesJobWhenAllDeliverableAlreadyShipped(CompletionGateSetUp):
    """When all deliverables are already shipped, paying the last invoice completes the job."""

    def setUp(self):
        super().setUp()
        self.job = _make_job(self.contact)
        _accepted_estimate(self.job)
        self.deliverable = Deliverable.objects.create(
            job=self.job, description='Table', qty_ordered=Decimal('2'), units='ea',
        )
        # Ship everything first
        _make_shipment_picked_up(self.job, self.deliverable, Decimal('2'))

    def test_job_completes_when_invoice_paid_after_all_shipped(self):
        _pay_invoice(self.job)
        self.job.refresh_from_db()
        self.assertEqual(
            self.job.status,
            Job.STATUS_COMPLETED,
            'Job should complete when all deliverables are already shipped and invoice is paid.',
        )


class ManualCompletionGate(CompletionGateSetUp):
    """update_job raises ValidationError when manually completing a job with unshipped deliverables."""

    def setUp(self):
        super().setUp()
        self.job = _make_job(self.contact)
        _accepted_estimate(self.job)
        self.deliverable = Deliverable.objects.create(
            job=self.job, description='Shelf', qty_ordered=Decimal('4'), units='ea',
        )

    def test_update_job_raises_when_deliverables_unshipped(self):
        with self.assertRaises(ValidationError) as ctx:
            JobService.update_job(self.job.pk, status=Job.STATUS_COMPLETED)
        self.assertIn('deliverables', str(ctx.exception).lower())

    def test_update_job_succeeds_when_all_deliverables_shipped(self):
        _make_shipment_picked_up(self.job, self.deliverable, Decimal('4'))
        # Should not raise
        job = JobService.update_job(self.job.pk, status=Job.STATUS_COMPLETED)
        self.assertEqual(job.status, Job.STATUS_COMPLETED)

    def test_cancel_unaffected_by_deliverable_gate(self):
        """Cancelling a job with unshipped deliverables must not raise."""
        job = JobService.update_job(self.job.pk, status=Job.STATUS_CANCELLED)
        self.assertEqual(job.status, Job.STATUS_CANCELLED)


class CancelledJobNotAutoCompleted(CompletionGateSetUp):
    """A cancelled job stays cancelled even when an invoice is paid."""

    def setUp(self):
        super().setUp()
        self.job = _make_job(self.contact, status=Job.STATUS_WORK_COMPLETE)
        # Cancel the job
        self.job.status = Job.STATUS_CANCELLED
        self.job.save()

    def test_cancelled_job_stays_cancelled_on_invoice_paid(self):
        _pay_invoice(self.job)
        self.job.refresh_from_db()
        self.assertEqual(
            self.job.status,
            Job.STATUS_CANCELLED,
            'A cancelled job must not be auto-completed by invoice payment.',
        )


class NoDeliverableJobCompletesOnPayment(CompletionGateSetUp):
    """Jobs with no deliverables still auto-complete when all invoices are paid."""

    def setUp(self):
        super().setUp()
        self.job = _make_job(self.contact)

    def test_no_deliverable_job_completes_on_invoice_paid(self):
        _pay_invoice(self.job)
        self.job.refresh_from_db()
        self.assertEqual(
            self.job.status,
            Job.STATUS_COMPLETED,
            'A job with no deliverables should auto-complete when all invoices are paid.',
        )
