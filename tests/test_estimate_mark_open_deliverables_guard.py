from decimal import Decimal
from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable
from apps.core.models import AccountingCategory
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateService
from apps.jobs.models import Job


class EstimateMarkOpenDeliverablesGuardTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        Deliverable.objects.filter(job=self.job).delete()
        self.estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-G-1',
            version=1,
            status=Estimate.STATUS_DRAFT,
        )
        # Estimate.clean() requires at least one line item to leave draft.
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_number=1,
            description='Sample line item',
            qty=Decimal('1'),
            units='ea',
            price=Decimal('100'),
            accounting_category=AccountingCategory.objects.first(),  # hand-line needs an AC to send
        )

    def test_mark_open_blocked_without_deliverables(self):
        with self.assertRaises(ValidationError):
            EstimateService.mark_open(self.estimate.pk)
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, Estimate.STATUS_DRAFT)

    def test_mark_open_succeeds_with_deliverables(self):
        Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        EstimateService.mark_open(self.estimate.pk)
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, Estimate.STATUS_OPEN)
