"""Direct Job→Approved is gated behind estimate acceptance.

If a job has ANY estimate (any status, dead ones included), the job may only
reach `approved` via estimate acceptance — a bare status edit bypasses
crystallization and leaves the estimate's customer-response clock ticking.
A job with no estimate at all can still be hand-approved (estimate-less jobs
are a supported flow). System paths (the acceptance signal, duplicate-as-
approved) pass `system_transition=True` through JobService.
"""
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import User
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateService
from apps.jobs.models import Job
from apps.jobs.services import JobService


class DirectApprovalGuardTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555',
        )
        self.job = Job.objects.create(contact=self.contact, job_number='JOB-2026-0100')
        JobService.update_job(self.job.pk, status=Job.STATUS_SUBMITTED)

    def _estimate(self, status, number='EST-G1'):
        return Estimate.objects.create(
            job=self.job, estimate_number=number, version=1, status=status,
            expiration_date=timezone.now(),
        )

    def test_direct_approval_blocked_when_open_estimate_exists(self):
        self._estimate(Estimate.STATUS_OPEN)
        with self.assertRaises(ValidationError):
            JobService.update_job(self.job.pk, status=Job.STATUS_APPROVED)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

    def test_direct_approval_blocked_even_by_dead_estimate(self):
        # "Any estimate at all" blocks — once the job is on the estimate road,
        # approval goes through a (possibly revised) estimate.
        self._estimate(Estimate.STATUS_EXPIRED)
        with self.assertRaises(ValidationError):
            JobService.update_job(self.job.pk, status=Job.STATUS_APPROVED)

    def test_direct_approval_allowed_with_no_estimates(self):
        JobService.update_job(self.job.pk, status=Job.STATUS_APPROVED)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    def test_acceptance_still_approves_job(self):
        est = self._estimate(Estimate.STATUS_OPEN)
        EstimateService.update_status(est.pk, Estimate.STATUS_ACCEPTED)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)


class DirectApprovalApiTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='A', last_name='B', email='a@b.com', mobile_number='555',
        )
        self.job = Job.objects.create(contact=self.contact, job_number='JOB-2026-0101')
        JobService.update_job(self.job.pk, status=Job.STATUS_SUBMITTED)
        self.user = User.objects.create_user(username='apr_mgr', password='x')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_jobs'))
        self.user = User.objects.get(pk=self.user.pk)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_patch_approved_blocked_with_estimate(self):
        Estimate.objects.create(
            job=self.job, estimate_number='EST-G2', version=1,
            status=Estimate.STATUS_OPEN, expiration_date=timezone.now(),
        )
        r = self.client.patch(f'/api/jobs/{self.job.pk}/',
                              {'status': 'approved'}, format='json')
        self.assertEqual(r.status_code, 400, getattr(r, 'data', None))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

    def test_patch_approved_allowed_without_estimate(self):
        r = self.client.patch(f'/api/jobs/{self.job.pk}/',
                              {'status': 'approved'}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    def test_detail_exposes_has_estimates(self):
        r = self.client.get(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertIs(r.data['has_estimates'], False)
        Estimate.objects.create(
            job=self.job, estimate_number='EST-G3', version=1,
            status=Estimate.STATUS_DRAFT, expiration_date=timezone.now(),
        )
        r2 = self.client.get(f'/api/jobs/{self.job.pk}/')
        self.assertIs(r2.data['has_estimates'], True)
