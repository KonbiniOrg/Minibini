"""
Tests for ChangeOrderService lifecycle: create, update_status (accept/reject),
seed_new, discard_draft, and related side effects.
"""
from decimal import Decimal
from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.estimates.models import Estimate, EstimateLineItem, ChangeOrder, ChangeOrderLineItem
from apps.deliverables.models import Deliverable, DeliverableSnapshot
from apps.jobs.models import Job, Task
from apps.inventory.models import Material
from apps.core.models import HistoryEntry


def _advance_job_to_on_hold(job):
    """Advance a draft job through submitted -> approved -> on_hold."""
    job.status = Job.STATUS_SUBMITTED
    job.save()
    job.status = Job.STATUS_APPROVED
    job.save()
    job.status = Job.STATUS_ON_HOLD
    job.save()
    job.refresh_from_db()


def _make_accepted_estimate(job, number='EST-COS-1'):
    return Estimate.objects.create(
        job=job, estimate_number=number, version=1,
        status=Estimate.STATUS_ACCEPTED,
    )


def _add_co_line(co):
    return ChangeOrderLineItem.objects.create(
        change_order=co,
        action=ChangeOrderLineItem.ACTION_ADD,
        description='Extra scope',
        qty=1,
        price=Decimal('250'),
        line_number=1,
    )


class ChangeOrderServiceCreateTests(FixtureTestCase):
    """ChangeOrderService.create() guards and Trigger 1 (snapshot prior agreement)."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        # Ensure no leftover estimates on this job (fixture has a draft one)
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job)
        # Live deliverables to snapshot
        self.d_a = Deliverable.objects.create(
            job=self.job, description='Panel A', qty_ordered=Decimal('5'), units='ea', sort_order=10,
        )
        self.d_b = Deliverable.objects.create(
            job=self.job, description='Panel B', qty_ordered=Decimal('3'), units='ea', sort_order=20,
        )
        _advance_job_to_on_hold(self.job)

    def test_create_raises_when_job_not_on_hold(self):
        from apps.estimates.change_order_service import ChangeOrderService
        # Move job back to approved (on_hold -> approved is valid)
        self.job.status = Job.STATUS_APPROVED
        self.job.save()
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.create(job_id=self.job.pk)
        self.assertIn('on hold', str(ctx.exception).lower())

    def test_create_returns_draft_change_order(self):
        from apps.estimates.change_order_service import ChangeOrderService
        co = ChangeOrderService.create(job_id=self.job.pk)
        self.assertIsNotNone(co.pk)
        self.assertEqual(co.status, ChangeOrder.STATUS_DRAFT)
        self.assertEqual(co.job, self.job)
        self.assertEqual(co.estimate, self.est)

    def test_create_triggers_snapshot_of_accepted_estimate(self):
        """Trigger 1: create() snapshots the prior agreement (accepted estimate here)."""
        from apps.estimates.change_order_service import ChangeOrderService
        ChangeOrderService.create(job_id=self.job.pk)
        snaps = list(DeliverableSnapshot.objects.filter(estimate=self.est))
        self.assertEqual(len(snaps), 2, 'Expected one snapshot per live deliverable')

    def test_create_raises_when_no_accepted_estimate(self):
        from apps.estimates.change_order_service import ChangeOrderService
        # Remove the accepted estimate
        self.est.delete()
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.create(job_id=self.job.pk)
        self.assertIn('accepted estimate', str(ctx.exception).lower())

    def test_create_trigger1_uses_latest_accepted_co_when_one_exists(self):
        """If an accepted CO already exists for the estimate, Trigger 1 snapshots that CO,
        not the accepted estimate (so we capture the most-recent agreed scope)."""
        from apps.estimates.change_order_service import ChangeOrderService
        # Build and accept the first CO manually
        co1 = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        _add_co_line(co1)
        co1.status = ChangeOrder.STATUS_OPEN
        co1.save()
        co1.status = ChangeOrder.STATUS_ACCEPTED
        co1.save()

        # Now create a second CO via the service
        ChangeOrderService.create(job_id=self.job.pk)
        # Snapshot should be attached to co1 (the latest accepted CO), not the estimate
        co1_snaps = list(DeliverableSnapshot.objects.filter(change_order=co1))
        self.assertGreaterEqual(len(co1_snaps), 1)


class ChangeOrderServiceAcceptTests(FixtureTestCase):
    """update_status(accepted) advances job to approved, writes history, leaves Tasks+Materials alone."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job)
        # Need at least one deliverable for snapshot (Trigger 1 runs on create)
        self.d_a = Deliverable.objects.create(
            job=self.job, description='Unit', qty_ordered=Decimal('1'), units='ea', sort_order=10,
        )
        _advance_job_to_on_hold(self.job)

    def test_accept_advances_job_to_approved(self):
        from apps.estimates.change_order_service import ChangeOrderService
        co = ChangeOrderService.create(job_id=self.job.pk)
        _add_co_line(co)
        ChangeOrderService.mark_open(co.pk)
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_ACCEPTED)

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    def test_accept_writes_history_entry(self):
        from apps.estimates.change_order_service import ChangeOrderService
        co = ChangeOrderService.create(job_id=self.job.pk)
        _add_co_line(co)
        ChangeOrderService.mark_open(co.pk)

        history_before = HistoryEntry.objects.filter(object_type='change_order').count()
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_ACCEPTED)

        history_after = HistoryEntry.objects.filter(object_type='change_order').count()
        self.assertGreater(history_after, history_before)

    def test_accept_does_not_create_tasks_or_materials(self):
        from apps.estimates.change_order_service import ChangeOrderService
        task_count_before = Task.objects.count()
        mat_count_before = Material.objects.count()

        co = ChangeOrderService.create(job_id=self.job.pk)
        _add_co_line(co)
        ChangeOrderService.mark_open(co.pk)
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_ACCEPTED)

        self.assertEqual(Task.objects.count(), task_count_before)
        self.assertEqual(Material.objects.count(), mat_count_before)


class ChangeOrderServiceRejectTests(FixtureTestCase):
    """update_status(rejected) creates a CO snapshot (Trigger 2) and leaves job on_hold."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job)
        self.d_a = Deliverable.objects.create(
            job=self.job, description='Widget', qty_ordered=Decimal('2'), units='ea', sort_order=10,
        )
        _advance_job_to_on_hold(self.job)

    def test_reject_creates_co_snapshot(self):
        """Trigger 2: rejecting a CO snapshots the CO proposal."""
        from apps.estimates.change_order_service import ChangeOrderService
        co = ChangeOrderService.create(job_id=self.job.pk)
        _add_co_line(co)
        ChangeOrderService.mark_open(co.pk)
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_REJECTED)

        snaps = list(DeliverableSnapshot.objects.filter(change_order=co))
        self.assertGreaterEqual(len(snaps), 1, 'Expected snapshot rows attached to the rejected CO')

    def test_reject_leaves_job_on_hold(self):
        from apps.estimates.change_order_service import ChangeOrderService
        co = ChangeOrderService.create(job_id=self.job.pk)
        _add_co_line(co)
        ChangeOrderService.mark_open(co.pk)
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_REJECTED)

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_ON_HOLD)


class ChangeOrderServiceSeedNewTests(FixtureTestCase):
    """seed_new() creates a new draft CO copying all line items from a terminal source CO."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job)
        self.d_a = Deliverable.objects.create(
            job=self.job, description='Part', qty_ordered=Decimal('1'), units='ea', sort_order=10,
        )
        _advance_job_to_on_hold(self.job)

    def test_seed_new_from_rejected_co(self):
        from apps.estimates.change_order_service import ChangeOrderService
        # Create, populate, open, and reject a CO
        co_src = ChangeOrderService.create(job_id=self.job.pk)
        _add_co_line(co_src)
        ChangeOrderService.mark_open(co_src.pk)
        ChangeOrderService.update_status(co_src.pk, ChangeOrder.STATUS_REJECTED)

        # Seed a new draft from the rejected one
        co_new = ChangeOrderService.seed_new(co_src.pk)

        self.assertNotEqual(co_new.pk, co_src.pk)
        self.assertEqual(co_new.status, ChangeOrder.STATUS_DRAFT)
        self.assertEqual(co_new.parent, co_src)

    def test_seed_new_copies_line_items(self):
        from apps.estimates.change_order_service import ChangeOrderService
        co_src = ChangeOrderService.create(job_id=self.job.pk)
        _add_co_line(co_src)
        # Add a second line
        ChangeOrderLineItem.objects.create(
            change_order=co_src, action=ChangeOrderLineItem.ACTION_ADD,
            description='Another item', qty=2, price=Decimal('75'), line_number=2,
        )
        ChangeOrderService.mark_open(co_src.pk)
        ChangeOrderService.update_status(co_src.pk, ChangeOrder.STATUS_REJECTED)

        co_new = ChangeOrderService.seed_new(co_src.pk)
        src_count = ChangeOrderLineItem.objects.filter(change_order=co_src).count()
        new_count = ChangeOrderLineItem.objects.filter(change_order=co_new).count()
        self.assertEqual(src_count, 2)
        self.assertEqual(new_count, 2)


class ChangeOrderServiceDiscardDraftTests(FixtureTestCase):
    """discard_draft() deletes draft COs and refuses to delete non-draft ones."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job)
        self.d_a = Deliverable.objects.create(
            job=self.job, description='Piece', qty_ordered=Decimal('1'), units='ea', sort_order=10,
        )
        _advance_job_to_on_hold(self.job)

    def test_discard_draft_deletes_co(self):
        from apps.estimates.change_order_service import ChangeOrderService
        co = ChangeOrderService.create(job_id=self.job.pk)
        co_pk = co.pk
        ChangeOrderService.discard_draft(co_pk)
        self.assertFalse(ChangeOrder.objects.filter(pk=co_pk).exists())

    def test_discard_non_draft_raises(self):
        from apps.estimates.change_order_service import ChangeOrderService
        co = ChangeOrderService.create(job_id=self.job.pk)
        _add_co_line(co)
        ChangeOrderService.mark_open(co.pk)
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.discard_draft(co.pk)
        self.assertIn('draft', str(ctx.exception).lower())
