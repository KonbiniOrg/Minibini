from django.test import TestCase
from django.utils import timezone
from apps.contacts.models import Contact, Business
from apps.core.models import HistoryEntry
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateService
from apps.jobs.models import Job
from apps.jobs.services import JobService


class EstimateDeathRejectsJobTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555',
        )
        self.business = Business.objects.create(
            business_name='Acme', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(contact=self.contact, job_number='JOB-2026-0001')
        JobService.update_job(self.job.pk, status=Job.STATUS_SUBMITTED)

    def _open_estimate(self, number, expiration=None):
        return Estimate.objects.create(
            job=self.job, estimate_number=number, version=1,
            status=Estimate.STATUS_OPEN,
            expiration_date=expiration or timezone.now(),
        )

    def test_decline_rejects_job(self):
        est = self._open_estimate('EST-1')
        EstimateService.update_status(est.pk, Estimate.STATUS_REJECTED)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_REJECTED)
        self.assertTrue(HistoryEntry.objects.filter(
            object_type='job', object_id=self.job.pk,
            changes__status__new=Job.STATUS_REJECTED,
        ).exists())

    def test_expiry_rejects_job(self):
        est = self._open_estimate('EST-2')
        EstimateService.update_status(est.pk, Estimate.STATUS_EXPIRED)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_REJECTED)

    def test_superseded_does_not_reject_job(self):
        # Only expired/rejected reject the job; other open transitions must not.
        est = self._open_estimate('EST-3')
        EstimateService.update_status(est.pk, Estimate.STATUS_SUPERSEDED)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)
