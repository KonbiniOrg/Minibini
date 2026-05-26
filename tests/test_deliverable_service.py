from decimal import Decimal
from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable, Shipment, ShipmentItem
from apps.deliverables.services import DeliverableService
from apps.estimates.models import Estimate
from apps.jobs.models import Job


class DeliverableEditabilityTests(FixtureTestCase):
    """is_editable / editability_reason across estimate states."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()

    def test_editable_when_no_estimate(self):
        self.assertTrue(DeliverableService.is_editable(self.job))
        self.assertIsNone(DeliverableService.editability_reason(self.job))

    def test_editable_when_estimate_is_draft(self):
        Estimate.objects.create(
            job=self.job,
            estimate_number='EST-X-1',
            version=1,
            status=Estimate.STATUS_DRAFT,
        )
        self.assertTrue(DeliverableService.is_editable(self.job))
        self.assertIsNone(DeliverableService.editability_reason(self.job))

    def test_not_editable_when_estimate_is_open(self):
        Estimate.objects.create(
            job=self.job,
            estimate_number='EST-X-2',
            version=1,
            status=Estimate.STATUS_OPEN,
        )
        self.assertFalse(DeliverableService.is_editable(self.job))
        self.assertEqual(DeliverableService.editability_reason(self.job), 'estimate_sent')

    def test_not_editable_when_estimate_is_accepted(self):
        Estimate.objects.create(
            job=self.job,
            estimate_number='EST-X-3',
            version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.assertFalse(DeliverableService.is_editable(self.job))
        self.assertEqual(DeliverableService.editability_reason(self.job), 'estimate_accepted')

    def test_editable_again_after_rejected_estimate(self):
        Estimate.objects.create(
            job=self.job,
            estimate_number='EST-X-4',
            version=1,
            status=Estimate.STATUS_REJECTED,
        )
        self.assertTrue(DeliverableService.is_editable(self.job))


class DeliverableCRUDTests(FixtureTestCase):
    """create / update / delete / reorder, all gated by editability."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()

    def test_create_when_editable(self):
        d = DeliverableService.create(
            job_id=self.job.pk,
            description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        self.assertEqual(d.job, self.job)
        self.assertEqual(d.description, 'Stool')

    def test_create_blocked_when_estimate_open(self):
        Estimate.objects.create(
            job=self.job, estimate_number='EST-Y-1', version=1,
            status=Estimate.STATUS_OPEN,
        )
        with self.assertRaises(ValidationError):
            DeliverableService.create(
                job_id=self.job.pk,
                description='Stool', qty_ordered=Decimal('15'), units='ea',
            )

    def test_create_blocked_when_estimate_accepted(self):
        Estimate.objects.create(
            job=self.job, estimate_number='EST-Y-2', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        with self.assertRaises(ValidationError):
            DeliverableService.create(
                job_id=self.job.pk,
                description='Stool', qty_ordered=Decimal('15'), units='ea',
            )

    def test_update_when_editable(self):
        d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        updated = DeliverableService.update(deliverable=d, description='Walnut stool')
        self.assertEqual(updated.description, 'Walnut stool')

    def test_update_blocked_when_estimate_accepted(self):
        d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        Estimate.objects.create(
            job=self.job, estimate_number='EST-Y-3', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        with self.assertRaises(ValidationError):
            DeliverableService.update(deliverable=d, qty_ordered=Decimal('20'))

    def test_delete_when_editable_renumbers_siblings(self):
        a = Deliverable.objects.create(job=self.job, description='A', qty_ordered=Decimal('1'), units='ea', sort_order=10)
        b = Deliverable.objects.create(job=self.job, description='B', qty_ordered=Decimal('1'), units='ea', sort_order=20)
        c = Deliverable.objects.create(job=self.job, description='C', qty_ordered=Decimal('1'), units='ea', sort_order=30)

        DeliverableService.delete(deliverable=b)

        remaining = list(Deliverable.objects.filter(job=self.job).order_by('sort_order'))
        self.assertEqual([r.pk for r in remaining], [a.pk, c.pk])
        self.assertEqual(remaining[0].sort_order, 10)
        self.assertEqual(remaining[1].sort_order, 20)

    def test_reorder_assigns_sequential_sort_orders(self):
        a = Deliverable.objects.create(job=self.job, description='A', qty_ordered=Decimal('1'), units='ea', sort_order=10)
        b = Deliverable.objects.create(job=self.job, description='B', qty_ordered=Decimal('1'), units='ea', sort_order=20)
        c = Deliverable.objects.create(job=self.job, description='C', qty_ordered=Decimal('1'), units='ea', sort_order=30)

        DeliverableService.reorder(job=self.job, ordered_ids=[c.pk, a.pk, b.pk])

        retrieved = list(Deliverable.objects.filter(job=self.job).order_by('sort_order'))
        self.assertEqual([r.pk for r in retrieved], [c.pk, a.pk, b.pk])


class ComputeFulfillmentTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        Estimate.objects.create(
            job=self.job, estimate_number='EST-CF-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )

    def test_no_shipments_remaining_equals_ordered(self):
        f = DeliverableService.compute_fulfillment(self.d)
        self.assertEqual(f['qty_ordered'], Decimal('15'))
        self.assertEqual(f['qty_picked_up'], Decimal('0'))
        self.assertEqual(f['qty_prepped'], Decimal('0'))
        self.assertEqual(f['qty_remaining'], Decimal('15'))

    def test_picked_up_reduces_remaining(self):
        s = Shipment.objects.create(job=self.job, sequence=1, status=Shipment.STATUS_PICKED_UP)
        ShipmentItem.objects.create(shipment=s, deliverable=self.d, qty=Decimal('10'))
        f = DeliverableService.compute_fulfillment(self.d)
        self.assertEqual(f['qty_picked_up'], Decimal('10'))
        self.assertEqual(f['qty_remaining'], Decimal('5'))

    def test_prepared_counts_separately(self):
        s_done = Shipment.objects.create(job=self.job, sequence=1, status=Shipment.STATUS_PICKED_UP)
        ShipmentItem.objects.create(shipment=s_done, deliverable=self.d, qty=Decimal('7'))
        s_prep = Shipment.objects.create(job=self.job, sequence=2, status=Shipment.STATUS_PREPARED)
        ShipmentItem.objects.create(shipment=s_prep, deliverable=self.d, qty=Decimal('3'))

        f = DeliverableService.compute_fulfillment(self.d)
        self.assertEqual(f['qty_picked_up'], Decimal('7'))
        self.assertEqual(f['qty_prepped'], Decimal('3'))
        self.assertEqual(f['qty_remaining'], Decimal('5'))


class AllDeliverablesShippedTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        Estimate.objects.create(
            job=self.job, estimate_number='EST-AS-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('10'), units='ea',
        )

    def test_false_when_nothing_shipped(self):
        self.assertFalse(DeliverableService.all_deliverables_shipped(self.job))

    def test_false_when_partially_picked_up(self):
        s = Shipment.objects.create(job=self.job, sequence=1, status=Shipment.STATUS_PICKED_UP)
        ShipmentItem.objects.create(shipment=s, deliverable=self.d, qty=Decimal('6'))
        self.assertFalse(DeliverableService.all_deliverables_shipped(self.job))

    def test_false_when_prepared_but_not_picked_up(self):
        s = Shipment.objects.create(job=self.job, sequence=1, status=Shipment.STATUS_PREPARED)
        ShipmentItem.objects.create(shipment=s, deliverable=self.d, qty=Decimal('10'))
        self.assertFalse(DeliverableService.all_deliverables_shipped(self.job))

    def test_true_when_fully_picked_up(self):
        s = Shipment.objects.create(job=self.job, sequence=1, status=Shipment.STATUS_PICKED_UP)
        ShipmentItem.objects.create(shipment=s, deliverable=self.d, qty=Decimal('10'))
        self.assertTrue(DeliverableService.all_deliverables_shipped(self.job))

    def test_true_when_multiple_deliverables_all_picked_up(self):
        d2 = Deliverable.objects.create(
            job=self.job, description='Table', qty_ordered=Decimal('2'), units='ea',
        )
        s = Shipment.objects.create(job=self.job, sequence=1, status=Shipment.STATUS_PICKED_UP)
        ShipmentItem.objects.create(shipment=s, deliverable=self.d, qty=Decimal('10'))
        ShipmentItem.objects.create(shipment=s, deliverable=d2, qty=Decimal('2'))
        self.assertTrue(DeliverableService.all_deliverables_shipped(self.job))

    def test_false_when_one_of_several_unshipped(self):
        Deliverable.objects.create(
            job=self.job, description='Table', qty_ordered=Decimal('2'), units='ea',
        )
        s = Shipment.objects.create(job=self.job, sequence=1, status=Shipment.STATUS_PICKED_UP)
        ShipmentItem.objects.create(shipment=s, deliverable=self.d, qty=Decimal('10'))
        self.assertFalse(DeliverableService.all_deliverables_shipped(self.job))

    def test_true_when_no_deliverables(self):
        Deliverable.objects.filter(job=self.job).delete()
        self.assertTrue(DeliverableService.all_deliverables_shipped(self.job))
