"""
Tests for ChangeOrderService lifecycle: create, update_status (accept/reject),
seed_new, discard_draft, and related side effects.
"""
from decimal import Decimal
from apps.core.models import AccountingCategory, JobHistory
from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import (
    Estimate, EstimateLineItem, ChangeOrder, ChangeOrderLineItem,
    ChangeOrderLineItemSource,
)
from apps.estimates.services import ChangeOrderWizardService
from apps.deliverables.models import Deliverable, DeliverableSnapshot
from apps.jobs.models import Job, RateScheme, Task
from apps.inventory.models import InventoryItem, Material


def _advance_job_to_on_hold(job):
    """Draft → submitted → approved, then hold (on_hold flag)."""
    from apps.jobs.services import JobService
    for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
        job.status = s
        job.save()
    JobService.hold_job(job.pk, 'CO editing')
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
        # A bare add line needs an AC to pass the send guard (the category
        # rides the line onto the agreement and its invoice copy).
        # 901 = 'SVC' in unit_test_data.json.
        accounting_category_id=901,
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
        from apps.jobs.services import JobService
        # Release the hold — the job stays approved underneath.
        JobService.release_job(self.job.pk)
        self.job.refresh_from_db()
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
    """update_status(accepted) advances job to approved, writes history, and
    crystallizes the CO's deltas onto the Job's atoms (full coverage in
    tests/test_change_order_acceptance.py)."""

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

    def test_accept_clears_hold_and_preserves_status(self):
        from apps.estimates.change_order_service import ChangeOrderService
        co = ChangeOrderService.create(job_id=self.job.pk)
        _add_co_line(co)
        ChangeOrderService.mark_open(co.pk)
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_ACCEPTED)

        self.job.refresh_from_db()
        self.assertFalse(self.job.on_hold)
        self.assertEqual(self.job.hold_reason, '')
        # Held from approved → still approved underneath.
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    def test_accept_resumes_in_progress_job_directly(self):
        """⚠ Behavior change vs the status model: a job held from in_progress
        goes straight back to in_progress on CO acceptance — no second
        release-to-floor step."""
        from apps.estimates.change_order_service import ChangeOrderService
        from apps.jobs.services import JobService
        # Rebuild the hold from in_progress.
        JobService.release_job(self.job.pk)
        JobService.update_job(self.job.pk, status=Job.STATUS_IN_PROGRESS)
        JobService.hold_job(self.job.pk, 'CO editing')
        co = ChangeOrderService.create(job_id=self.job.pk)
        _add_co_line(co)
        ChangeOrderService.mark_open(co.pk)
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_ACCEPTED)

        self.job.refresh_from_db()
        self.assertFalse(self.job.on_hold)
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)

    def test_accept_writes_history_entry(self):
        from apps.estimates.change_order_service import ChangeOrderService
        co = ChangeOrderService.create(job_id=self.job.pk)
        _add_co_line(co)
        ChangeOrderService.mark_open(co.pk)

        history_before = JobHistory.objects.filter(object_type='changeorder').count()
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_ACCEPTED)

        history_after = JobHistory.objects.filter(object_type='changeorder').count()
        self.assertGreater(history_after, history_before)

    def test_accept_leaves_bare_add_line_document_only(self):
        """A bare add line stays a document-only line at acceptance: no
        Task, no Material, no source row."""
        from apps.estimates.change_order_service import ChangeOrderService
        from apps.estimates.models import ChangeOrderLineItemSource
        task_count_before = Task.objects.count()
        mat_count_before = Material.objects.count()

        co = ChangeOrderService.create(job_id=self.job.pk)
        li = _add_co_line(co)
        ChangeOrderService.mark_open(co.pk)
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_ACCEPTED)

        self.assertFalse(
            ChangeOrderLineItemSource.objects.filter(
                change_order_line_item=li).exists())
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
        self.assertTrue(self.job.on_hold)


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
            accounting_category_id=901,
        )
        ChangeOrderService.mark_open(co_src.pk)
        ChangeOrderService.update_status(co_src.pk, ChangeOrder.STATUS_REJECTED)

        co_new = ChangeOrderService.seed_new(co_src.pk)
        src_count = ChangeOrderLineItem.objects.filter(change_order=co_src).count()
        new_count = ChangeOrderLineItem.objects.filter(change_order=co_new).count()
        self.assertEqual(src_count, 2)
        self.assertEqual(new_count, 2)

    def test_seed_new_from_rejected_co_with_authored_claim_arrives_claimless(self):
        """Rejection already released the source line's authored claim
        (DEAD_DOCUMENT_STATUSES), so the seeded copy — default
        move_claims=False — must not carry any source rows either."""
        from apps.estimates.change_order_service import ChangeOrderService
        cat = AccountingCategory.objects.create(
            code='LAB-COSREJ', name='Labor-COSREJ', taxable=False)
        scheme = RateScheme.objects.create(
            name='Hourly-COSREJ', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50'), unit_label='hour', accounting_category=cat,
        )
        task = Task(job=self.job, name='Extra', est_qty=Decimal('1'))
        task.stamp_from_scheme(scheme)
        task.save()

        co_src = ChangeOrderService.create(job_id=self.job.pk)
        ChangeOrderWizardService.add_atoms_to_new_line_item(
            co_src, [{'type': 'task', 'id': task.pk}])
        ChangeOrderService.mark_open(co_src.pk)
        ChangeOrderService.update_status(co_src.pk, ChangeOrder.STATUS_REJECTED)

        self.assertEqual(
            ChangeOrderLineItemSource.objects.filter(source_pk=task.pk).count(), 0,
            'Rejection should already have released the claim.',
        )

        co_new = ChangeOrderService.seed_new(co_src.pk)
        new_li = ChangeOrderLineItem.objects.get(change_order=co_new)
        self.assertEqual(new_li.sources.count(), 0)


class ChangeOrderServiceSeedNewAdjustmentTests(FixtureTestCase):
    """seed_new preserves the adjustment triple on a copied REPLACE line, so
    the copy stays a real adjustment amendment (Task 6 shape) instead of
    silently reverting to a plain replace."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.labor = AccountingCategory.objects.create(
            code='LAB-SEEDADJ', name='Labor-SeedAdj', taxable=False)
        self.materials = AccountingCategory.objects.create(
            code='MAT-SEEDADJ', name='Materials-SeedAdj', taxable=False)
        self.est = _make_accepted_estimate(self.job, number='EST-SEEDADJ-1')
        self.li_labor = EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, description='Labor',
            qty=Decimal('1'), price=Decimal('100.00'), accounting_category=self.labor,
        )
        self.li_materials = EstimateLineItem.objects.create(
            estimate=self.est, line_number=2, description='Materials',
            qty=Decimal('1'), price=Decimal('40.00'), accounting_category=self.materials,
        )
        self.scheme = RateScheme.objects.create(
            name='Rush-SeedAdj', algorithm=RateScheme.PERCENTAGE, rate=Decimal('10.00'),
            unit_label='%', accounting_category=self.labor,
        )
        self.adj = EstimateLineItem.objects.create(
            estimate=self.est, line_number=3, description='Rush 10%',
            qty=Decimal('1'), price=Decimal('14.00'), units='pct',
            accounting_category=self.labor,
            adjustment_service=self.scheme, adjustment_percent=Decimal('10.00'),
        )
        _advance_job_to_on_hold(self.job)

    def test_seed_new_preserves_adjustment_triple_and_recomputes_price(self):
        co_src = ChangeOrderService.create(job_id=self.job.pk)
        replace_li = ChangeOrderService.add_line_item(
            co_src.pk, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.adj.pk, adjustment_percent='5.00',
        )
        self.assertEqual(replace_li.price, Decimal('7.00'))  # 5% of 140
        ChangeOrderService.mark_open(co_src.pk)
        ChangeOrderService.update_status(co_src.pk, ChangeOrder.STATUS_REJECTED)

        co_new = ChangeOrderService.seed_new(co_src.pk)
        new_li = ChangeOrderLineItem.objects.get(
            change_order=co_new, action=ChangeOrderLineItem.ACTION_REPLACE)

        self.assertEqual(new_li.adjustment_service_id, self.scheme.pk)
        self.assertEqual(new_li.adjustment_percent, Decimal('5.00'))
        self.assertEqual(
            {c.pk for c in new_li.adjustment_target_categories.all()},
            {c.pk for c in self.adj.adjustment_target_categories.all()},
        )
        # Recomputed against the new CO's own amended basis — same 140 total
        # (no accepted COs exist yet), so still 5% = 7.00.
        self.assertEqual(new_li.price, Decimal('7.00'))


class ChangeOrderServiceSeedNewFromAcceptedTests(FixtureTestCase):
    """Standalone seed_new (move_claims=False, the default) on an ACCEPTED
    CO must leave that CO's claims exactly where they are — they're the
    agreement record — and the seeded copy must arrive claimless."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job, number='EST-COS-ACC-1')
        self.d_a = Deliverable.objects.create(
            job=self.job, description='Part', qty_ordered=Decimal('1'), units='ea', sort_order=10,
        )
        self.cat = AccountingCategory.objects.create(
            code='LAB-COSACC', name='Labor-COSACC', taxable=False)
        self.scheme = RateScheme.objects.create(
            name='Hourly-COSACC', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50'), unit_label='hour', accounting_category=self.cat,
        )
        self.task = Task(job=self.job, name='Extra cut', est_qty=Decimal('1'))
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()
        _advance_job_to_on_hold(self.job)

    def test_standalone_seed_new_from_accepted_co_leaves_claims_in_place(self):
        co = ChangeOrderService.create(job_id=self.job.pk)
        li = ChangeOrderWizardService.add_atoms_to_new_line_item(
            co, [{'type': 'task', 'id': self.task.pk}])
        ChangeOrderService.mark_open(co.pk)
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_ACCEPTED)

        co_new = ChangeOrderService.seed_new(co.pk)

        li.refresh_from_db()
        self.assertEqual(li.sources.count(), 1)
        self.assertEqual(li.sources.first().source_pk, self.task.pk)

        new_li = ChangeOrderLineItem.objects.get(change_order=co_new)
        self.assertEqual(new_li.sources.count(), 0)


class SeedNewNormalizesLegacyReplaceDescriptorTests(FixtureTestCase):
    """A legacy ACTION_REPLACE line carrying a crystallization descriptor
    (created before ChangeOrderLineItem.clean() forbade it — e.g. via a
    direct .objects.create() bypassing full_clean) must not propagate the
    violation into a seeded copy: seed_new strips the descriptor so the
    copy is a valid bare replace."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job, number='EST-LEGACY-1')
        self.d_a = Deliverable.objects.create(
            job=self.job, description='Part', qty_ordered=Decimal('1'), units='ea', sort_order=10,
        )
        self.cat = AccountingCategory.objects.create(
            code='LAB-LEGACY', name='Labor-Legacy', taxable=False)
        self.target = EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, description='Old work',
            qty=Decimal('1'), price=Decimal('100.00'), accounting_category=self.cat,
        )
        _advance_job_to_on_hold(self.job)

    def test_legacy_replace_descriptor_copy_is_normalized(self):
        co_src = ChangeOrderService.create(job_id=self.job.pk)
        pli = InventoryItem.objects.create(
            code='PLY-LEGACY', accounting_category=self.cat,
            qty_on_hand=Decimal('10'), purchase_price=Decimal('5'),
            selling_price=Decimal('12.00'), units='ea',
        )
        # Legacy row: predates the clean() rule forbidding a descriptor on a
        # replace line. BaseLineItem.save() always full_cleans, so simulate
        # the pre-rule persisted row with bulk_create (skips save()/clean()
        # entirely) rather than the normal ORM write path.
        ChangeOrderLineItem.objects.bulk_create([ChangeOrderLineItem(
            change_order=co_src, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.target, description='New work',
            qty=Decimal('1'), price=Decimal('120.00'), line_number=1,
            accounting_category=self.cat, inventory_item=pli,
        )])
        ChangeOrderService.mark_open(co_src.pk)
        ChangeOrderService.update_status(co_src.pk, ChangeOrder.STATUS_REJECTED)

        co_new = ChangeOrderService.seed_new(co_src.pk)
        new_li = ChangeOrderLineItem.objects.get(change_order=co_new)

        self.assertIsNone(new_li.inventory_item_id)
        self.assertIsNone(new_li.service_item_id)
        self.assertFalse(new_li.is_material)
        new_li.full_clean()  # must not raise


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


class OnHoldExitGuardTests(FixtureTestCase):
    """Releasing the hold (JobService.release_job) — and cancelling while
    held — must be blocked while a live (draft/open) CO exists."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job)
        self.d_a = Deliverable.objects.create(
            job=self.job, description='Widget', qty_ordered=Decimal('1'), units='ea', sort_order=10,
        )
        _advance_job_to_on_hold(self.job)

    def _make_draft_co(self):
        from apps.estimates.change_order_service import ChangeOrderService
        return ChangeOrderService.create(job_id=self.job.pk)

    def _make_open_co(self):
        from apps.estimates.change_order_service import ChangeOrderService
        co = ChangeOrderService.create(job_id=self.job.pk)
        _add_co_line(co)
        ChangeOrderService.mark_open(co.pk)
        co.refresh_from_db()
        return co

    # --- rejection cases: draft CO blocks release and cancel ---

    def test_draft_co_blocks_release(self):
        from apps.jobs.services import JobService
        self._make_draft_co()
        with self.assertRaises(ValidationError) as ctx:
            JobService.release_job(self.job.pk)
        self.assertIn('change order', str(ctx.exception).lower())

    def test_draft_co_blocks_transition_to_cancelled(self):
        from apps.jobs.services import JobService
        self._make_draft_co()
        with self.assertRaises(ValidationError) as ctx:
            JobService.update_job(self.job.pk, status=Job.STATUS_CANCELLED)
        self.assertIn('change order', str(ctx.exception).lower())

    # --- rejection cases: open CO blocks release ---

    def test_open_co_blocks_release(self):
        from apps.jobs.services import JobService
        self._make_open_co()
        with self.assertRaises(ValidationError) as ctx:
            JobService.release_job(self.job.pk)
        self.assertIn('change order', str(ctx.exception).lower())

    # --- allowed cases: no live CO means release is permitted ---

    def test_no_co_allows_release(self):
        from apps.jobs.services import JobService
        # No CO created — the hold releases freely; status was preserved.
        JobService.release_job(self.job.pk)
        self.job.refresh_from_db()
        self.assertFalse(self.job.on_hold)
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    def test_accepted_co_allows_release(self):
        """A job whose only CO is already accepted (terminal) can be re-held
        and released freely."""
        from apps.estimates.change_order_service import ChangeOrderService
        from apps.jobs.services import JobService
        co = self._make_open_co()
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_ACCEPTED)
        # Accept cleared the hold; re-hold to test the guard in isolation.
        self.job.refresh_from_db()
        JobService.hold_job(self.job.pk, 'second thoughts')

        # The CO is accepted (terminal) — release should be allowed.
        JobService.release_job(self.job.pk)
        self.job.refresh_from_db()
        self.assertFalse(self.job.on_hold)

    # --- regression: accept-driven un-hold still works ---

    def test_accept_co_clears_hold_despite_guard(self):
        """When a CO is accepted, _handle_accepted clears the hold. The guard
        must NOT block this, because the CO is already terminal (accepted) at
        that point."""
        from apps.estimates.change_order_service import ChangeOrderService
        co = self._make_open_co()
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_ACCEPTED)

        self.job.refresh_from_db()
        self.assertFalse(
            self.job.on_hold,
            'Accepting a CO must still clear the hold.',
        )
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)
