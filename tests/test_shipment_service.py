from decimal import Decimal
from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable, Shipment, ShipmentItem
from apps.deliverables.services import ShipmentService
from apps.estimates.models import Estimate
from apps.jobs.models import Job


def _job_with_accepted_estimate(suffix=''):
    job = Job.objects.first()
    Estimate.objects.filter(job=job).delete()
    Estimate.objects.create(
        job=job, estimate_number=f'EST-S-{suffix or "1"}', version=1,
        status=Estimate.STATUS_ACCEPTED,
    )
    return job


class ShipmentCreateGatingTests(FixtureTestCase):

    def test_create_blocked_when_no_estimate(self):
        job = Job.objects.first()
        Estimate.objects.filter(job=job).delete()
        with self.assertRaises(ValidationError):
            ShipmentService.create(job_id=job.pk)

    def test_create_blocked_when_estimate_draft(self):
        job = Job.objects.first()
        Estimate.objects.filter(job=job).delete()
        Estimate.objects.create(
            job=job, estimate_number='EST-S-2', version=1,
            status=Estimate.STATUS_DRAFT,
        )
        with self.assertRaises(ValidationError):
            ShipmentService.create(job_id=job.pk)

    def test_create_blocked_when_estimate_open(self):
        job = Job.objects.first()
        Estimate.objects.filter(job=job).delete()
        Estimate.objects.create(
            job=job, estimate_number='EST-S-3', version=1,
            status=Estimate.STATUS_OPEN,
        )
        with self.assertRaises(ValidationError):
            ShipmentService.create(job_id=job.pk)

    def test_create_succeeds_when_estimate_accepted(self):
        job = _job_with_accepted_estimate()
        s = ShipmentService.create(job_id=job.pk)
        self.assertEqual(s.status, Shipment.STATUS_PREPARED)
        self.assertEqual(s.sequence, 1)

    def test_create_assigns_next_sequence(self):
        job = _job_with_accepted_estimate()
        ShipmentService.create(job_id=job.pk)
        ShipmentService.create(job_id=job.pk)
        third = ShipmentService.create(job_id=job.pk)
        self.assertEqual(third.sequence, 3)


class ShipmentItemTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = _job_with_accepted_estimate()
        self.d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        self.s = ShipmentService.create(job_id=self.job.pk)

    def test_add_item_within_remaining(self):
        item = ShipmentService.add_item(
            shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('10'),
        )
        self.assertEqual(item.qty, Decimal('10'))

    def test_add_item_zero_qty_rejected(self):
        with self.assertRaises(ValidationError):
            ShipmentService.add_item(
                shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('0'),
            )

    def test_add_item_negative_qty_rejected(self):
        with self.assertRaises(ValidationError):
            ShipmentService.add_item(
                shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('-1'),
            )

    def test_add_item_exceeding_remaining_rejected(self):
        with self.assertRaises(ValidationError):
            ShipmentService.add_item(
                shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('16'),
            )

    def test_add_item_accounts_for_other_shipments(self):
        ShipmentService.add_item(
            shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('10'),
        )
        s2 = ShipmentService.create(job_id=self.job.pk)
        ShipmentService.add_item(shipment=s2, deliverable_id=self.d.pk, qty=Decimal('5'))
        s3 = ShipmentService.create(job_id=self.job.pk)
        with self.assertRaises(ValidationError):
            ShipmentService.add_item(shipment=s3, deliverable_id=self.d.pk, qty=Decimal('1'))

    def test_add_item_to_picked_up_shipment_rejected(self):
        self.s.status = Shipment.STATUS_PICKED_UP
        self.s.save()
        with self.assertRaises(ValidationError):
            ShipmentService.add_item(
                shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('1'),
            )

    def test_update_item_within_bounds(self):
        item = ShipmentService.add_item(
            shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('5'),
        )
        updated = ShipmentService.update_item(item=item, qty=Decimal('7'))
        self.assertEqual(updated.qty, Decimal('7'))

    def test_update_item_to_exceed_remaining_rejected(self):
        item = ShipmentService.add_item(
            shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('5'),
        )
        with self.assertRaises(ValidationError):
            ShipmentService.update_item(item=item, qty=Decimal('16'))

    def test_remove_item_from_prepared(self):
        item = ShipmentService.add_item(
            shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('5'),
        )
        ShipmentService.remove_item(item=item)
        self.assertFalse(ShipmentItem.objects.filter(pk=item.pk).exists())

    def test_remove_item_from_picked_up_rejected(self):
        item = ShipmentService.add_item(
            shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('5'),
        )
        self.s.status = Shipment.STATUS_PICKED_UP
        self.s.save()
        with self.assertRaises(ValidationError):
            ShipmentService.remove_item(item=item)


class ShipmentTransitionTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = _job_with_accepted_estimate()
        self.s = ShipmentService.create(job_id=self.job.pk)

    def test_mark_picked_up_transitions(self):
        result = ShipmentService.mark_picked_up(self.s.pk)
        self.assertEqual(result.status, Shipment.STATUS_PICKED_UP)
        self.assertIsNotNone(result.picked_up_date)

    def test_mark_picked_up_idempotent_rejection(self):
        ShipmentService.mark_picked_up(self.s.pk)
        with self.assertRaises(ValidationError):
            ShipmentService.mark_picked_up(self.s.pk)

    def test_delete_prepared_empty(self):
        ShipmentService.delete(shipment=self.s)
        self.assertFalse(Shipment.objects.filter(pk=self.s.pk).exists())

    def test_delete_prepared_with_items_rejected(self):
        d = Deliverable.objects.create(
            job=self.job, description='X', qty_ordered=Decimal('1'), units='ea',
        )
        ShipmentService.add_item(shipment=self.s, deliverable_id=d.pk, qty=Decimal('1'))
        with self.assertRaises(ValidationError):
            ShipmentService.delete(shipment=self.s)

    def test_delete_picked_up_rejected(self):
        ShipmentService.mark_picked_up(self.s.pk)
        self.s.refresh_from_db()
        with self.assertRaises(ValidationError):
            ShipmentService.delete(shipment=self.s)


class PackingListPayloadTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = _job_with_accepted_estimate()
        self.d1 = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea', sort_order=10,
        )
        self.d2 = Deliverable.objects.create(
            job=self.job, description='Hardware kit', qty_ordered=Decimal('15'), units='kit', sort_order=20,
        )

    def test_payload_includes_all_deliverables_in_sort_order(self):
        s = ShipmentService.create(job_id=self.job.pk)
        ShipmentService.add_item(shipment=s, deliverable_id=self.d1.pk, qty=Decimal('10'))
        payload = ShipmentService.packing_list_payload(s)

        rows = payload['rows']
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['deliverable_id'], self.d1.pk)
        self.assertEqual(rows[1]['deliverable_id'], self.d2.pk)
        self.assertEqual(rows[0]['qty_this_shipment'], Decimal('10'))
        self.assertEqual(rows[1]['qty_this_shipment'], Decimal('0'))

    def test_previously_picked_up_only_counts_other_picked_up_shipments(self):
        s1 = ShipmentService.create(job_id=self.job.pk)
        ShipmentService.add_item(shipment=s1, deliverable_id=self.d1.pk, qty=Decimal('10'))
        ShipmentService.mark_picked_up(s1.pk)

        s2 = ShipmentService.create(job_id=self.job.pk)
        ShipmentService.add_item(shipment=s2, deliverable_id=self.d1.pk, qty=Decimal('5'))

        payload = ShipmentService.packing_list_payload(s2)
        row = next(r for r in payload['rows'] if r['deliverable_id'] == self.d1.pk)
        self.assertEqual(row['qty_previously_picked_up'], Decimal('10'))
        self.assertEqual(row['qty_this_shipment'], Decimal('5'))
        self.assertEqual(row['qty_remaining_after_this_shipment'], Decimal('0'))

    def test_previously_does_not_include_other_prepared_shipments(self):
        s1 = ShipmentService.create(job_id=self.job.pk)
        ShipmentService.add_item(shipment=s1, deliverable_id=self.d1.pk, qty=Decimal('7'))
        s2 = ShipmentService.create(job_id=self.job.pk)
        ShipmentService.add_item(shipment=s2, deliverable_id=self.d1.pk, qty=Decimal('5'))

        payload = ShipmentService.packing_list_payload(s2)
        row = next(r for r in payload['rows'] if r['deliverable_id'] == self.d1.pk)
        self.assertEqual(row['qty_previously_picked_up'], Decimal('0'))
