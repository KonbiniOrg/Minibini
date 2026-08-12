from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, JobHistory
from apps.deliverables.models import Deliverable
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateService
from apps.jobs.models import Job
from apps.jobs.services import JobService


class UnexpireEstimateTest(TestCase):
    """EstimateService.unexpire reactivates a lapsed estimate IN PLACE
    (expired -> open, same estimate/job — no duplication) and walks its job
    rejected -> submitted, mirroring the reverse of the auto-expiry signal."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com',
            mobile_number='555-0100',
        )
        self.ac = AccountingCategory.objects.create(
            code='SVC', name='Services', taxable=True,
        )
        self.job = JobService.create_job(name='Widget Job', contact=self.contact)
        Deliverable.objects.create(
            job=self.job, description='One widget',
            qty_ordered=Decimal('1'), units='each',
        )
        self.est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Build widget',
            qty=Decimal('2'), units='each', price=Decimal('50.00'),
            accounting_category=self.ac,
        )
        EstimateService.mark_open(self.est.pk)
        self.est.refresh_from_db()  # pick up sent_date/expiration_date from mark_open

        # Simulate the mark_estimates_expired sweep: open -> expired, which
        # (per the existing signal) rejects the still-submitted job.
        self.est.status = Estimate.STATUS_EXPIRED
        self.est.save()
        self.job.refresh_from_db()
        self.est.refresh_from_db()

    def test_setup_sanity_job_rejected_estimate_expired(self):
        self.assertEqual(self.job.status, Job.STATUS_REJECTED)
        self.assertEqual(self.est.status, Estimate.STATUS_EXPIRED)
        self.assertIsNotNone(self.job.completed_date)
        self.assertIsNotNone(self.est.closed_date)

    def test_only_expired_estimates_can_be_unexpired(self):
        other_job = JobService.create_job(name='Other Job', contact=self.contact)
        draft_est = EstimateService.create_for_job(other_job.pk)
        with self.assertRaises(ValidationError):
            EstimateService.unexpire(draft_est.pk)

    def test_unexpire_flips_estimate_open_and_job_submitted_in_place(self):
        result = EstimateService.unexpire(self.est.pk)
        self.assertEqual(result.pk, self.est.pk)
        self.assertEqual(result.status, Estimate.STATUS_OPEN)

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

    def test_unexpire_gives_a_fresh_expiration_window(self):
        old_expiration = self.est.expiration_date
        result = EstimateService.unexpire(self.est.pk)
        self.assertGreater(result.expiration_date, timezone.now())
        self.assertGreater(result.expiration_date, old_expiration)

    def test_unexpire_clears_closed_date_and_completed_date(self):
        result = EstimateService.unexpire(self.est.pk)
        self.assertIsNone(result.closed_date)
        self.job.refresh_from_db()
        self.assertIsNone(self.job.completed_date)

    def test_unexpire_preserves_line_items_unchanged(self):
        EstimateService.unexpire(self.est.pk)
        lines = list(EstimateLineItem.objects.filter(estimate=self.est))
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].description, 'Build widget')
        self.assertEqual(lines[0].price, Decimal('50.00'))

    def test_unexpire_does_not_create_a_new_job_or_estimate(self):
        jobs_before = Job.objects.count()
        estimates_before = Estimate.objects.count()
        EstimateService.unexpire(self.est.pk)
        self.assertEqual(Job.objects.count(), jobs_before)
        self.assertEqual(Estimate.objects.count(), estimates_before)

    def test_unexpire_records_history_on_the_job(self):
        EstimateService.unexpire(self.est.pk)
        self.assertTrue(JobHistory.objects.filter(
            object_type='job', object_id=self.job.pk,
            changes__status__new=Job.STATUS_SUBMITTED,
        ).exists())

    def test_unexpire_leaves_an_approved_job_untouched(self):
        """Mirrors mark_estimates_expired's 'expiring sibling does not reject
        approved job' guard, in reverse: if the job already advanced past
        rejected some other way, unexpiring the dead estimate must not pull
        it backwards."""
        JobService.update_job(self.job.pk, status=Job.STATUS_SUBMITTED,
                              system_transition=True)
        JobService.update_job(self.job.pk, status=Job.STATUS_APPROVED,
                              system_transition=True)
        EstimateService.unexpire(self.est.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)
