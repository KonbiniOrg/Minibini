from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import Configuration, AppState
from apps.jobs.models import Job


class JobInProgressStateTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )

    def test_status_in_progress_constant_exists(self):
        self.assertEqual(Job.STATUS_IN_PROGRESS, 'in_progress')

    def test_in_progress_in_choices(self):
        choices = dict(Job.JOB_STATUS_CHOICES)
        self.assertIn(Job.STATUS_IN_PROGRESS, choices)

    def test_approved_can_transition_to_in_progress(self):
        job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        job.status = Job.STATUS_SUBMITTED
        job.save()
        job.status = Job.STATUS_APPROVED
        job.save()
        job.status = Job.STATUS_IN_PROGRESS
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)

    def test_in_progress_can_transition_to_work_complete(self):
        job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        job.status = Job.STATUS_SUBMITTED
        job.save()
        job.status = Job.STATUS_APPROVED
        job.save()
        job.status = Job.STATUS_IN_PROGRESS
        job.save()
        job.status = Job.STATUS_WORK_COMPLETE
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_WORK_COMPLETE)

    def test_in_progress_can_be_cancelled(self):
        job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        job.status = Job.STATUS_SUBMITTED
        job.save()
        job.status = Job.STATUS_APPROVED
        job.save()
        job.status = Job.STATUS_IN_PROGRESS
        job.save()
        job.status = Job.STATUS_CANCELLED
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_CANCELLED)

    def test_approved_can_no_longer_jump_to_work_complete(self):
        # Old transition approved → work_complete is removed; must go via in_progress
        job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        job.status = Job.STATUS_SUBMITTED
        job.save()
        job.status = Job.STATUS_APPROVED
        job.save()
        job.status = Job.STATUS_WORK_COMPLETE
        with self.assertRaises(ValidationError):
            job.save()
