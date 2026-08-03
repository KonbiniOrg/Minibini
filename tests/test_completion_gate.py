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
from apps.core.models import AccountingCategory, Configuration
from apps.deliverables.models import Deliverable, Shipment
from apps.deliverables.services import ShipmentService
from apps.estimates.models import Estimate
from apps.invoicing.models import Invoice
from apps.invoicing.services import InvoiceService
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


def _open_invoice(job):
    """Create an open (unresolved) invoice — does not fire the completion gate."""
    idx = Invoice.objects.count()
    return Invoice.objects.create(
        job=job,
        invoice_number=f'INV-CG-{idx}',
        status=Invoice.STATUS_OPEN,
    )


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


class InvoiceCancelCompletesJob(CompletionGateSetUp):
    """Cancelling the last unresolved invoice should fire the completion gate.

    A cancelled invoice counts as resolved (JobService.maybe_complete_if_resolved),
    so cancelling the only open invoice on an all-shipped job must complete it.
    This exercises the cancel path routing through Invoice.save() rather than a
    bypassing QuerySet.update().
    """

    def setUp(self):
        super().setUp()
        self.job = _make_job(self.contact)
        self.invoice = _open_invoice(self.job)
        # No deliverables -> all_deliverables_shipped is trivially True.

    def test_cancelling_last_invoice_completes_job(self):
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_WORK_COMPLETE)
        InvoiceService.cancel(self.invoice.pk, reason='Customer withdrew')
        self.job.refresh_from_db()
        self.assertEqual(
            self.job.status,
            Job.STATUS_COMPLETED,
            'Cancelling the last unresolved invoice should complete an all-shipped job.',
        )

    def test_cancel_does_not_complete_when_another_invoice_open(self):
        other = _open_invoice(self.job)
        InvoiceService.cancel(self.invoice.pk, reason='Replaced')
        self.job.refresh_from_db()
        self.assertEqual(
            self.job.status,
            Job.STATUS_WORK_COMPLETE,
            'Job must stay work_complete while another invoice is still open.',
        )
        # Resolving the remaining invoice then completes the job.
        other.status = Invoice.STATUS_PAID
        other.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_COMPLETED)


class InProgressJobNotAutoCompleted(CompletionGateSetUp):
    """A job whose work isn't finished must not auto-complete on invoice resolution.

    Only ``work_complete`` means the work is done. An ``in_progress`` job may
    still have open tasks (a follow-up to send plans, a post-job meeting), so
    paying its invoice — even with every deliverable shipped — must leave it
    in_progress. Same reasoning covers a deposit invoice paid before any work.
    """

    def setUp(self):
        super().setUp()
        self.job = _make_job(self.contact, status=Job.STATUS_IN_PROGRESS)
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)

    def test_in_progress_job_stays_open_when_invoice_paid(self):
        # No deliverables -> all_deliverables_shipped is trivially True, so only
        # the work-stage guard stands between this and an (incorrect) completion.
        _pay_invoice(self.job)
        self.job.refresh_from_db()
        self.assertEqual(
            self.job.status,
            Job.STATUS_IN_PROGRESS,
            'An in_progress job must not auto-complete on a paid invoice.',
        )

    def test_deposit_invoice_paid_before_work_does_not_complete(self):
        """A deposit paid up front (job in_progress) must not close the job."""
        deposit = _open_invoice(self.job)
        deposit.status = Invoice.STATUS_PAID
        deposit.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)

    def test_completes_only_once_work_complete(self):
        """Once the job legitimately reaches work_complete, resolving the
        invoice completes it (confirms the guard isn't over-blocking)."""
        inv = _open_invoice(self.job)
        # Work finishes -> job reaches work_complete (no auto-complete fires here).
        self.job.status = Job.STATUS_WORK_COMPLETE
        self.job.save()
        inv.status = Invoice.STATUS_PAID
        inv.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_COMPLETED)


class WorkFinishedButStrandedInProgress(CompletionGateSetUp):
    """The loose-material-stranded case (the acrylic flow): a job whose tasks
    are ALL terminal but that never reached work_complete because a loose
    pending material blocked the transition. The unattended completion path
    must release the material and complete the job — that release is the whole
    reason release_loose_materials exists. Distinct from an in_progress job
    with OPEN tasks, which must stay open (WorkStageGuard above)."""

    def setUp(self):
        super().setUp()
        from apps.jobs.models import RateScheme, Task
        self.job = _make_job(self.contact, status=Job.STATUS_IN_PROGRESS)
        cat = AccountingCategory.objects.create(
            name=f'GateCat{AccountingCategory.objects.count()}', is_active=True,
            code=f'GC{AccountingCategory.objects.count()}')
        scheme = RateScheme.objects.create(
            name='Gate hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=cat)
        self.task = Task(
            job=self.job, name='Done work',
            status=Task.STATUS_COMPLETE)
        self.task.stamp_from_scheme(scheme)
        self.task.save()
        # The loose pending material that stranded the job in in_progress.
        from apps.inventory.services import MaterialService
        self.material = MaterialService.create_on_job(
            job=self.job, description='loose acrylic', quantity=Decimal('1'),
            sell_price=Decimal('50.00'), accounting_category=cat, units='ea')

    def test_stranded_job_completes_and_deletes_unclaimed_loose_material(self):
        _pay_invoice(self.job)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_COMPLETED)
        # Unclaimed loose material is scratch paper — the restock-to-zero rule
        # deletes it on release (deletion doctrine).
        from apps.inventory.models import Material
        self.assertFalse(Material.objects.filter(pk=self.material.pk).exists())

    def test_stranded_job_completes_and_releases_claimed_loose_material(self):
        # The acrylic flow proper: the loose material backs an accepted
        # estimate line, so release keeps it as job history.
        from apps.estimates.models import (
            Estimate, EstimateLineItem, EstimateLineItemSource,
        )
        from apps.inventory.models import Material
        est = _accepted_estimate(self.job)
        line = EstimateLineItem.objects.create(
            estimate=est, description='loose acrylic', qty=Decimal('1'),
            price=Decimal('50.00'))
        EstimateLineItemSource.objects.create(
            estimate_line_item=line,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=self.material.pk)
        _pay_invoice(self.job)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_COMPLETED)
        self.material.refresh_from_db()
        self.assertEqual(
            self.material.consumption_state,
            Material.CONSUMPTION_STATE_RELEASED)
        self.assertEqual(line.sources.get().resolve().pk, self.material.pk)

    def test_open_task_still_blocks_even_with_material_resolved(self):
        from apps.jobs.models import RateScheme, Task
        t = Task(
            job=self.job, name='Still open', status=Task.STATUS_PENDING)
        t.stamp_from_scheme(self.task.source_scheme)
        t.save()
        _pay_invoice(self.job)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)

    def test_taskless_job_does_not_auto_complete_from_in_progress(self):
        """No recorded work at all -> 'work finished' can't be claimed."""
        from apps.jobs.models import Task
        Task.objects.filter(job=self.job).delete()
        from apps.inventory.models import Material
        Material.objects.filter(job=self.job).delete()
        _pay_invoice(self.job)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)


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
