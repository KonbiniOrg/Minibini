from decimal import Decimal
from django.db import IntegrityError
from django.db import transaction
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable, Shipment, ShipmentItem
from apps.jobs.models import Job


class ShipmentModelTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.deliverable = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )

    def test_default_status_is_prepared(self):
        s = Shipment.objects.create(job=self.job, sequence=1)
        self.assertEqual(s.status, 'prepared')
        self.assertIsNotNone(s.prepared_date)
        self.assertIsNone(s.picked_up_date)

    def test_unique_sequence_per_job(self):
        Shipment.objects.create(job=self.job, sequence=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Shipment.objects.create(job=self.job, sequence=1)

    def test_db_table_name(self):
        self.assertEqual(Shipment._meta.db_table, 'shipments')

    def test_default_ordering_is_sequence(self):
        b = Shipment.objects.create(job=self.job, sequence=20)
        a = Shipment.objects.create(job=self.job, sequence=10)
        retrieved = list(Shipment.objects.filter(job=self.job))
        self.assertEqual(retrieved[0].pk, a.pk)
        self.assertEqual(retrieved[1].pk, b.pk)


class ShipmentItemModelTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.deliverable = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        self.shipment = Shipment.objects.create(job=self.job, sequence=1)

    def test_create_item(self):
        item = ShipmentItem.objects.create(
            shipment=self.shipment, deliverable=self.deliverable, qty=Decimal('5'),
        )
        self.assertEqual(item.shipment, self.shipment)
        self.assertEqual(item.deliverable, self.deliverable)
        self.assertEqual(item.qty, Decimal('5'))

    def test_unique_shipment_deliverable_pair(self):
        ShipmentItem.objects.create(
            shipment=self.shipment, deliverable=self.deliverable, qty=Decimal('5'),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ShipmentItem.objects.create(
                    shipment=self.shipment, deliverable=self.deliverable, qty=Decimal('3'),
                )

    def test_db_table_name(self):
        self.assertEqual(ShipmentItem._meta.db_table, 'shipment_items')
