from datetime import timedelta
from apps.core.models import JobHistory
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from apps.contacts.models import Contact, Business
from apps.core.models import ScheduledProcessRun
from apps.estimates.models import Estimate
from apps.jobs.models import Job
from apps.jobs.services import JobService


class MarkEstimatesExpiredCommandTest(TestCase):
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

    def _open(self, number, sent_days_ago, valid_days):
        now = timezone.now()
        est = Estimate.objects.create(
            job=self.job, estimate_number=number, version=1,
            status=Estimate.STATUS_OPEN,
            sent_date=now - timedelta(days=sent_days_ago),
            expiration_date=now - timedelta(days=sent_days_ago) + timedelta(days=valid_days),
        )
        return est

    def test_expires_past_due_open_estimate_and_rejects_job(self):
        est = self._open('EST-1', sent_days_ago=40, valid_days=30)  # expired 10 days ago
        call_command('mark_estimates_expired')
        est.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(est.status, Estimate.STATUS_EXPIRED)
        self.assertEqual(self.job.status, Job.STATUS_REJECTED)
        self.assertTrue(JobHistory.objects.filter(
            object_type='estimate', object_id=est.pk,
            changes__status__new=Estimate.STATUS_EXPIRED,
        ).exists())

    def test_future_expiration_untouched(self):
        est = self._open('EST-2', sent_days_ago=1, valid_days=30)  # expires in ~29 days
        call_command('mark_estimates_expired')
        est.refresh_from_db()
        self.assertEqual(est.status, Estimate.STATUS_OPEN)

    def test_null_expiration_skipped_and_counted(self):
        Estimate.objects.create(
            job=self.job, estimate_number='EST-3', version=1,
            status=Estimate.STATUS_OPEN, expiration_date=None,
        )
        call_command('mark_estimates_expired')
        run = ScheduledProcessRun.objects.get(process_name='mark_estimates_expired')
        self.assertEqual(run.summary['skipped_no_expiry'], 1)
        self.assertEqual(run.summary['expired'], 0)

    def test_idempotent(self):
        self._open('EST-4', sent_days_ago=40, valid_days=30)
        call_command('mark_estimates_expired')
        call_command('mark_estimates_expired')  # must not error
        self.assertEqual(
            Estimate.objects.filter(status=Estimate.STATUS_EXPIRED).count(), 1
        )

    def test_expiring_sibling_does_not_reject_approved_job(self):
        JobService.update_job(self.job.pk, status=Job.STATUS_APPROVED)
        est = self._open('EST-APV', sent_days_ago=40, valid_days=30)
        call_command('mark_estimates_expired')
        est.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(est.status, Estimate.STATUS_EXPIRED)
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)
        run = ScheduledProcessRun.objects.get(process_name='mark_estimates_expired')
        self.assertEqual(run.outcome, 'ok')           # guard no-ops cleanly → no errors
        self.assertEqual(run.summary['expired'], 1)
