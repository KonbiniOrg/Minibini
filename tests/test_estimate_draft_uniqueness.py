"""Task 1 (bundling-in-task-view plan): one-draft-estimate-per-job is
enforced in Estimate.clean(), so every creation path (create_direct,
create_for_job, and any future caller) is bound automatically via
Estimate.save() -> full_clean(). Draft-vs-draft only: revise_estimate's
transient (open parent + draft child) moment must not trip it.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateService
from apps.jobs.services import JobService


class DraftEstimateUniquenessTests(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Drew', last_name='Draft', email='drew.draft@test.com',
        )

    def _make_job(self):
        return JobService.create_job(name='Draft Uniqueness Job', contact=self.contact)

    def test_second_draft_via_create_direct_is_refused(self):
        job = self._make_job()
        EstimateService.create_direct(job)
        with self.assertRaises(ValidationError) as ctx:
            EstimateService.create_direct(job, version=2)  # distinct version so
            # the (estimate_number, version) uniqueness check isn't what fires
        self.assertIn('already has a draft estimate', str(ctx.exception))

    def test_second_draft_via_create_for_job_is_refused(self):
        job = self._make_job()
        EstimateService.create_for_job(job.pk)
        with self.assertRaises(ValidationError):
            EstimateService.create_for_job(job.pk)

    def test_revise_open_estimate_still_works(self):
        # revise holds (open parent + draft child) transiently — must not trip.
        job = self._make_job()
        est = EstimateService.create_for_job(job.pk)
        EstimateLineItem.objects.create(
            estimate=est, description='Build widget',
            qty=Decimal('1'), units='each', price=Decimal('10.00'),
        )
        EstimateService.update_status(est.pk, Estimate.STATUS_OPEN)
        new = EstimateService.revise_estimate(est.pk)
        self.assertEqual(new.status, Estimate.STATUS_DRAFT)
        est.refresh_from_db()
        self.assertEqual(est.status, Estimate.STATUS_SUPERSEDED)

    def test_draft_can_still_be_edited_and_saved(self):
        # the check must exclude self — resaving the only draft is fine.
        job = self._make_job()
        est = EstimateService.create_for_job(job.pk)
        est.save()  # resaving the only draft must not raise
