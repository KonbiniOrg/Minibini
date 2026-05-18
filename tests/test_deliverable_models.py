from decimal import Decimal
from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable
from apps.jobs.models import Job


class DeliverableModelTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.assertIsNotNone(self.job, 'Fixture must include at least one Job.')

    def test_create_basic_deliverable(self):
        d = Deliverable.objects.create(
            job=self.job,
            description='Walnut stool',
            qty_ordered=Decimal('15'),
            units='ea',
        )
        self.assertEqual(d.job, self.job)
        self.assertEqual(d.description, 'Walnut stool')
        self.assertEqual(d.qty_ordered, Decimal('15'))
        self.assertEqual(d.units, 'ea')
        self.assertIsNotNone(d.sort_order)

    def test_sort_order_auto_assigns_on_save(self):
        a = Deliverable.objects.create(
            job=self.job, description='A', qty_ordered=Decimal('1'), units='ea',
        )
        b = Deliverable.objects.create(
            job=self.job, description='B', qty_ordered=Decimal('1'), units='ea',
        )
        c = Deliverable.objects.create(
            job=self.job, description='C', qty_ordered=Decimal('1'), units='ea',
        )
        self.assertLess(a.sort_order, b.sort_order)
        self.assertLess(b.sort_order, c.sort_order)

    def test_default_ordering_is_sort_order(self):
        a = Deliverable.objects.create(
            job=self.job, description='A', qty_ordered=Decimal('1'), units='ea',
            sort_order=20,
        )
        b = Deliverable.objects.create(
            job=self.job, description='B', qty_ordered=Decimal('1'), units='ea',
            sort_order=10,
        )
        retrieved = list(Deliverable.objects.filter(job=self.job))
        self.assertEqual(retrieved[0].pk, b.pk)
        self.assertEqual(retrieved[1].pk, a.pk)

    def test_db_table_name(self):
        self.assertEqual(Deliverable._meta.db_table, 'deliverables')

    def test_qty_ordered_supports_decimals(self):
        d = Deliverable.objects.create(
            job=self.job, description='Plywood sheet', qty_ordered=Decimal('2.5'),
            units='sheet',
        )
        d.refresh_from_db()
        self.assertEqual(d.qty_ordered, Decimal('2.50'))
