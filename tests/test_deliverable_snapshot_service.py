from decimal import Decimal
from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable, DeliverableSnapshot, Shipment, ShipmentItem
from apps.deliverables.services import DeliverableService
from apps.estimates.models import Estimate, ChangeOrder
from apps.jobs.models import Job


class SnapshotDocumentEstimateTests(FixtureTestCase):
    """snapshot_document(estimate=...) creates one snapshot row per live deliverable."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-SN-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.d_a = Deliverable.objects.create(
            job=self.job, description='Table', qty_ordered=Decimal('2'), units='ea', sort_order=10,
        )
        self.d_b = Deliverable.objects.create(
            job=self.job, description='Chair', qty_ordered=Decimal('4'), units='ea', sort_order=20,
        )

    def test_creates_one_snapshot_per_deliverable(self):
        snaps = DeliverableService.snapshot_document(estimate=self.est)
        self.assertEqual(len(snaps), 2)
        self.assertTrue(all(isinstance(s, DeliverableSnapshot) for s in snaps))

    def test_snapshot_copies_fields_correctly(self):
        snaps = DeliverableService.snapshot_document(estimate=self.est)
        by_desc = {s.description: s for s in snaps}

        table_snap = by_desc['Table']
        self.assertEqual(table_snap.qty_ordered, Decimal('2'))
        self.assertEqual(table_snap.units, 'ea')
        self.assertEqual(table_snap.sort_order, 10)
        self.assertEqual(table_snap.source_deliverable, self.d_a)
        self.assertEqual(table_snap.estimate, self.est)
        self.assertIsNone(table_snap.change_order)

        chair_snap = by_desc['Chair']
        self.assertEqual(chair_snap.qty_ordered, Decimal('4'))
        self.assertEqual(chair_snap.source_deliverable, self.d_b)

    def test_first_snapshot_gets_version_1(self):
        snaps = DeliverableService.snapshot_document(estimate=self.est)
        self.assertTrue(all(s.version == 1 for s in snaps))

    def test_idempotent_returns_same_rows(self):
        snaps_first = DeliverableService.snapshot_document(estimate=self.est)
        snaps_second = DeliverableService.snapshot_document(estimate=self.est)
        # Same number of rows — no duplicates created
        self.assertEqual(len(snaps_second), len(snaps_first))
        first_pks = {s.pk for s in snaps_first}
        second_pks = {s.pk for s in snaps_second}
        self.assertEqual(first_pks, second_pks)
        # DB count unchanged
        db_count = DeliverableSnapshot.objects.filter(estimate=self.est).count()
        self.assertEqual(db_count, 2)


class SnapshotDocumentVersioningTests(FixtureTestCase):
    """snapshot_document on a CO after an estimate snapshot gets version 2."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-SN2-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('6'), units='ea', sort_order=10,
        )
        self.co = ChangeOrder.objects.create(job=self.job, estimate=self.est)

    def test_co_snapshot_after_estimate_snapshot_gets_version_2(self):
        DeliverableService.snapshot_document(estimate=self.est)
        co_snaps = DeliverableService.snapshot_document(change_order=self.co)
        self.assertTrue(all(s.version == 2 for s in co_snaps))

    def test_estimate_snapshot_version_still_1_after_co_snapshotted(self):
        est_snaps = DeliverableService.snapshot_document(estimate=self.est)
        DeliverableService.snapshot_document(change_order=self.co)
        est_snaps_db = list(DeliverableSnapshot.objects.filter(estimate=self.est))
        self.assertTrue(all(s.version == 1 for s in est_snaps_db))


class SnapshotDocumentValidationTests(FixtureTestCase):
    """snapshot_document raises ValidationError when neither or both args supplied."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-SN3-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.co = ChangeOrder.objects.create(job=self.job, estimate=self.est)

    def test_neither_raises(self):
        with self.assertRaises(ValidationError):
            DeliverableService.snapshot_document()

    def test_both_raises(self):
        with self.assertRaises(ValidationError):
            DeliverableService.snapshot_document(estimate=self.est, change_order=self.co)


class RestoreLiveToSnapshotTests(FixtureTestCase):
    """restore_live_to_snapshot reconciles unanchored live rows back to the snapshot."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-RS-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        # Live deliverables at snapshot time
        self.d_a = Deliverable.objects.create(
            job=self.job, description='Table', qty_ordered=Decimal('10'), units='ea', sort_order=10,
        )
        self.d_b = Deliverable.objects.create(
            job=self.job, description='Chair', qty_ordered=Decimal('5'), units='ea', sort_order=20,
        )
        # Take the snapshot
        DeliverableService.snapshot_document(estimate=self.est)

    def test_restore_reverts_edited_qty(self):
        # Mutate A's qty directly (bypassing service guards intentionally)
        self.d_a.qty_ordered = Decimal('7')
        self.d_a.save()

        DeliverableService.restore_live_to_snapshot(estimate=self.est)

        self.d_a.refresh_from_db()
        self.assertEqual(self.d_a.qty_ordered, Decimal('10'))

    def test_restore_recreates_deleted_deliverable(self):
        # Delete B (simulating CO work that removed it)
        self.d_b.delete()

        DeliverableService.restore_live_to_snapshot(estimate=self.est)

        # B should exist again by description
        restored = Deliverable.objects.filter(job=self.job, description='Chair').first()
        self.assertIsNotNone(restored)
        self.assertEqual(restored.qty_ordered, Decimal('5'))

    def test_restore_deletes_post_snapshot_addition(self):
        # C added after the snapshot (simulating CO work that added a new row)
        Deliverable.objects.create(
            job=self.job, description='Bench', qty_ordered=Decimal('3'), units='ea', sort_order=30,
        )
        self.assertEqual(Deliverable.objects.filter(job=self.job).count(), 3)

        DeliverableService.restore_live_to_snapshot(estimate=self.est)

        # Only A and B should remain
        self.assertEqual(Deliverable.objects.filter(job=self.job).count(), 2)
        self.assertFalse(Deliverable.objects.filter(job=self.job, description='Bench').exists())

    def test_restore_all_three_mutations_together(self):
        """Full scenario: A edited, B deleted, C added -> restore leaves only A(10) and B(5)."""
        self.d_a.qty_ordered = Decimal('7')
        self.d_a.save()
        self.d_b.delete()
        Deliverable.objects.create(
            job=self.job, description='Bench', qty_ordered=Decimal('3'), units='ea', sort_order=30,
        )

        DeliverableService.restore_live_to_snapshot(estimate=self.est)

        deliverables = list(Deliverable.objects.filter(job=self.job).order_by('sort_order'))
        descriptions = [d.description for d in deliverables]
        self.assertIn('Table', descriptions)
        self.assertIn('Chair', descriptions)
        self.assertNotIn('Bench', descriptions)
        self.assertEqual(len(deliverables), 2)

        a = next(d for d in deliverables if d.description == 'Table')
        b = next(d for d in deliverables if d.description == 'Chair')
        self.assertEqual(a.qty_ordered, Decimal('10'))
        self.assertEqual(b.qty_ordered, Decimal('5'))


class RestoreAnchoredRowTests(FixtureTestCase):
    """Anchored (shipped) rows must NOT be touched by restore_live_to_snapshot."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-ANC-RS-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.d_a = Deliverable.objects.create(
            job=self.job, description='Table', qty_ordered=Decimal('10'), units='ea', sort_order=10,
        )
        # Take the snapshot before anchoring
        DeliverableService.snapshot_document(estimate=self.est)

        # Anchor A via a picked_up shipment
        shipment = Shipment.objects.create(
            job=self.job, sequence=1, status=Shipment.STATUS_PICKED_UP,
        )
        ShipmentItem.objects.create(shipment=shipment, deliverable=self.d_a, qty=Decimal('5'))

    def test_anchored_row_not_reverted_on_restore(self):
        # Directly edit A's qty after the snapshot and after it's anchored
        self.d_a.qty_ordered = Decimal('7')
        self.d_a.save()

        DeliverableService.restore_live_to_snapshot(estimate=self.est)

        self.d_a.refresh_from_db()
        # A is anchored, so the edited qty must be preserved (not reverted to 10)
        self.assertEqual(self.d_a.qty_ordered, Decimal('7'))

    def test_anchored_row_not_deleted_even_if_not_in_snapshot(self):
        """An anchored row added after the snapshot is left alone (not deleted)."""
        # Create a second deliverable after the snapshot and anchor it too
        d_extra = Deliverable.objects.create(
            job=self.job, description='Extra', qty_ordered=Decimal('2'), units='ea', sort_order=20,
        )
        shipment2 = Shipment.objects.create(
            job=self.job, sequence=2, status=Shipment.STATUS_PICKED_UP,
        )
        ShipmentItem.objects.create(shipment=shipment2, deliverable=d_extra, qty=Decimal('2'))

        DeliverableService.restore_live_to_snapshot(estimate=self.est)

        # d_extra is anchored, must survive even though it wasn't in the snapshot
        self.assertTrue(Deliverable.objects.filter(pk=d_extra.pk).exists())


class RestoreLiveValidationTests(FixtureTestCase):
    """restore_live_to_snapshot raises ValidationError when neither or both args supplied."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-RS-VAL-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.co = ChangeOrder.objects.create(job=self.job, estimate=self.est)

    def test_neither_raises(self):
        with self.assertRaises(ValidationError):
            DeliverableService.restore_live_to_snapshot()

    def test_both_raises(self):
        with self.assertRaises(ValidationError):
            DeliverableService.restore_live_to_snapshot(estimate=self.est, change_order=self.co)
