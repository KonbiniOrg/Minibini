from decimal import Decimal
from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.deliverables.models import DeliverableSnapshot, Deliverable
from apps.estimates.models import Estimate, ChangeOrder
from apps.jobs.models import Job


class DeliverableSnapshotModelTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-DS-1', version=1, status=Estimate.STATUS_ACCEPTED,
        )

    def test_estimate_only_is_valid(self):
        snap = DeliverableSnapshot(
            estimate=self.est, version=1, description='Stool',
            qty_ordered=Decimal('10'), units='ea',
        )
        snap.full_clean()  # no raise

    def test_change_order_only_is_valid(self):
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        snap = DeliverableSnapshot(
            change_order=co, version=2, description='Stool',
            qty_ordered=Decimal('10'), units='ea',
        )
        snap.full_clean()  # no raise

    def test_neither_owner_is_invalid(self):
        snap = DeliverableSnapshot(version=1, description='x', qty_ordered=Decimal('1'), units='ea')
        with self.assertRaises(ValidationError):
            snap.full_clean()

    def test_both_owners_is_invalid(self):
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        snap = DeliverableSnapshot(
            estimate=self.est, change_order=co, version=1, description='x',
            qty_ordered=Decimal('1'), units='ea',
        )
        with self.assertRaises(ValidationError):
            snap.full_clean()
