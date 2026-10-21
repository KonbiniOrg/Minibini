from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient
from apps.core.models import User
from apps.jobs.models import Job
from tests.base import BaseTestCase
from tests.test_contacts_status import make_business, make_job


class ArchivedStatusModelTest(TestCase):
    def setUp(self):
        _, self.contact, _ = make_business('ArcCo', n_contacts=1)

    def test_archived_is_a_choice(self):
        self.assertIn(('archived', 'Archived'), Job.JOB_STATUS_CHOICES)
        self.assertEqual(Job.STATUS_ARCHIVED, 'archived')

    def test_groupings_membership(self):
        self.assertEqual(Job.PRE_APPROVAL_STATUSES, frozenset({'draft', 'submitted'}))
        self.assertEqual(Job.CLOSED_STATUSES, frozenset({'completed', 'rejected', 'cancelled', 'archived'}))
        self.assertEqual(Job.WORK_FROZEN_STATUSES, Job.CLOSED_STATUSES | {'work_complete'})

    def test_create_at_archived_with_explicit_dates_is_allowed(self):
        from django.utils import timezone
        when = timezone.now()
        job = Job.objects.create(job_number='ARC-1', contact=self.contact,
                                 status=Job.STATUS_ARCHIVED, start_date=when, completed_date=when)
        job.refresh_from_db()
        self.assertEqual(job.status, 'archived')
        self.assertEqual(job.completed_date, when)

    def test_no_transition_into_archived(self):
        for status in (Job.STATUS_DRAFT, Job.STATUS_COMPLETED, Job.STATUS_CANCELLED):
            job = make_job(self.contact, status)
            job.status = Job.STATUS_ARCHIVED
            with self.assertRaises(ValidationError):
                job.save()

    def test_no_transition_out_of_archived(self):
        job = Job.objects.create(job_number='ARC-2', contact=self.contact, status=Job.STATUS_ARCHIVED)
        for status in (Job.STATUS_DRAFT, Job.STATUS_IN_PROGRESS, Job.STATUS_COMPLETED):
            job.status = status
            with self.assertRaises(ValidationError):
                job.save()
            job.refresh_from_db()


class ArchivedStatusAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        _, self.contact, _ = make_business('ArcApi', n_contacts=1)

    def test_patch_to_archived_is_refused(self):
        job = make_job(self.contact, Job.STATUS_COMPLETED)
        r = self.client.patch(f'/api/jobs/{job.pk}/', {'status': 'archived'}, format='json')
        self.assertEqual(r.status_code, 400, r.data)

    def test_status_actions_refused_on_archived(self):
        job = Job.objects.create(job_number='ARC-3', contact=self.contact, status=Job.STATUS_ARCHIVED)
        for action in ('complete', 'cancel', 'reopen'):
            r = self.client.post(f'/api/jobs/{job.pk}/{action}/', {}, format='json')
            self.assertEqual(r.status_code, 400, (action, r.data))
