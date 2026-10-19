"""The manual "Release to floor" gesture (brought back 2026-10-18).

Auto-release (tests/test_auto_release.py) still walks an approved job to
in_progress on its own once the accepted estimate's checklist is fully
answered. But the checklist lives at the bottom of the estimate's edit page
and nothing on the job page points at it — so the header pill offers
"Release to floor" on every approved, non-held job again:

- `JobService.unanswered_line_count(job)` — how many plain hand lines on the
  job's accepted estimate(s) still owe a work decision.
- `JobService.release_to_floor(pk, decline_unanswered=False)` — approved ->
  in_progress. With unanswered lines it refuses unless `decline_unanswered`
  is set, in which case every unanswered line is marked work_declined (the
  reversible "no work needed" answer) in the same transaction. A job with no
  accepted estimate (hand-approved) simply releases.
- `POST /api/jobs/{id}/release-to-floor/` — two-phase like ConfirmDeleteMixin:
  without `?confirm=true` and with unanswered lines it returns
  `{'confirm_required': True, 'impact': {'unanswered_lines': N}}` and changes
  nothing; with `?confirm=true` (or nothing to confirm) it releases.

Object graphs mirror tests/test_auto_release.py (built directly, no
fixtures); acceptance drives the REAL draft -> open -> accepted walk so the
signal cascade fires and the job lands on `approved` honestly.
"""
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, User
from apps.estimates.models import Estimate, EstimateLineItem, ServiceItem
from apps.estimates.services import EstimateService
from apps.jobs.models import Job, RateScheme
from apps.jobs.services import JobService


class ReleaseToFloorBase(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(
            name='Labor', code='RTF-LAB', is_active=True,
        )
        self.contact = Contact.objects.create(
            first_name='R', last_name='F', email='rf@test.com',
            phones=[{'number': '555-0300', 'label': 'mobile'}],
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly-RTF', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100.00'), unit_label='hour', accounting_category=self.cat,
        )

    def _job(self, suffix, status=Job.STATUS_DRAFT):
        return Job.objects.create(
            contact=self.contact, job_number=f'JOB-RTF-{suffix}', status=status,
        )

    def _estimate(self, job, suffix):
        return Estimate.objects.create(
            job=job, estimate_number=f'EST-RTF-{suffix}', status=Estimate.STATUS_DRAFT,
        )

    def _plain_line(self, estimate, line_number, description='Plain hand line'):
        return EstimateLineItem.objects.create(
            estimate=estimate, line_number=line_number, description=description,
            qty=Decimal('1'), price=Decimal('50.00'), accounting_category=self.cat,
        )

    def _service_item_line(self, estimate, line_number):
        service_item = ServiceItem.objects.create(
            template_name=f'Svc {line_number}', rate_scheme=self.scheme,
        )
        return EstimateLineItem.objects.create(
            estimate=estimate, line_number=line_number, description='Deferred service',
            qty=Decimal('1'), price=Decimal('100.00'),
            accounting_category=self.cat, service_item=service_item,
        )

    def _accept(self, estimate):
        EstimateService.update_status(estimate.pk, Estimate.STATUS_OPEN)
        EstimateService.update_status(estimate.pk, Estimate.STATUS_ACCEPTED)
        estimate.refresh_from_db()
        return estimate

    def _approved_job_with_unanswered(self, suffix, n_unanswered=2):
        """An approved job whose accepted estimate has one catalog line
        (crystallized at accept) and `n_unanswered` plain hand lines."""
        job = self._job(suffix)
        estimate = self._estimate(job, suffix)
        self._service_item_line(estimate, 1)
        lines = [
            self._plain_line(estimate, i + 2, description=f'Hand line {i + 1}')
            for i in range(n_unanswered)
        ]
        self._accept(estimate)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_APPROVED)
        return job, estimate, lines


class UnansweredLineCountTest(ReleaseToFloorBase):
    def test_counts_unanswered_hand_lines_across_accepted_estimate(self):
        job, _estimate, _lines = self._approved_job_with_unanswered('CNT', n_unanswered=3)
        self.assertEqual(JobService.unanswered_line_count(job), 3)

    def test_zero_when_no_accepted_estimate(self):
        job = self._job('CNT0', status=Job.STATUS_APPROVED)
        estimate = self._estimate(job, 'CNT0')
        self._plain_line(estimate, 1)  # still draft — owes nothing yet
        self.assertEqual(JobService.unanswered_line_count(job), 0)


class ReleaseToFloorServiceTest(ReleaseToFloorBase):
    def test_refuses_with_unanswered_lines_unless_decline_requested(self):
        job, _estimate, lines = self._approved_job_with_unanswered('REF')
        with self.assertRaises(ValidationError):
            JobService.release_to_floor(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_APPROVED)
        for line in lines:
            line.refresh_from_db()
            self.assertFalse(line.work_declined)

    def test_decline_unanswered_declines_every_line_and_releases(self):
        job, _estimate, lines = self._approved_job_with_unanswered('DEC')
        JobService.release_to_floor(job.pk, decline_unanswered=True)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)
        for line in lines:
            line.refresh_from_db()
            self.assertTrue(line.work_declined)
        self.assertEqual(JobService.unanswered_line_count(job), 0)

    def test_declined_line_stays_reversible_afterwards(self):
        job, _estimate, lines = self._approved_job_with_unanswered('UNDO', n_unanswered=1)
        JobService.release_to_floor(job.pk, decline_unanswered=True)
        # The per-line Undo on the estimate still works: un-declining via the
        # normal update_line_item carve-out is accepted (job already
        # in_progress, so auto-release is a no-op and nothing raises).
        EstimateService.update_line_item(lines[0].pk, work_declined=False)
        lines[0].refresh_from_db()
        self.assertFalse(lines[0].work_declined)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)

    def test_releases_directly_when_no_accepted_estimate(self):
        job = self._job('HAND', status=Job.STATUS_APPROVED)
        JobService.release_to_floor(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)

    def test_refuses_held_job(self):
        job = self._job('HELD', status=Job.STATUS_APPROVED)
        JobService.hold_job(job.pk, 'waiting on material')
        with self.assertRaises(ValidationError):
            JobService.release_to_floor(job.pk, decline_unanswered=True)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_APPROVED)
        self.assertTrue(job.on_hold)

    def test_refuses_non_approved_job(self):
        job = self._job('DRAFT')
        with self.assertRaises(ValidationError):
            JobService.release_to_floor(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_DRAFT)


class ReleaseToFloorApiTest(ReleaseToFloorBase):
    def setUp(self):
        super().setUp()
        self.manager = User.objects.create_user(username='rtf_mgr', password='x')
        self.manager.user_permissions.add(
            Permission.objects.get(codename='can_manage_jobs'))
        self.manager = User.objects.get(pk=self.manager.pk)
        self.client = APIClient()
        self.client.force_authenticate(user=self.manager)

    def _url(self, job, confirm=False):
        return f'/api/jobs/{job.pk}/release-to-floor/' + ('?confirm=true' if confirm else '')

    def test_first_call_reports_impact_without_mutating(self):
        job, _estimate, lines = self._approved_job_with_unanswered('API1', n_unanswered=3)
        r = self.client.post(self._url(job), {}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.assertTrue(r.data['confirm_required'])
        self.assertEqual(r.data['impact'], {'unanswered_lines': 3})
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_APPROVED)
        for line in lines:
            line.refresh_from_db()
            self.assertFalse(line.work_declined)

    def test_confirmed_call_declines_and_releases(self):
        job, _estimate, lines = self._approved_job_with_unanswered('API2')
        r = self.client.post(self._url(job, confirm=True), {}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.assertIn('message', r.data)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)
        for line in lines:
            line.refresh_from_db()
            self.assertTrue(line.work_declined)

    def test_nothing_to_confirm_releases_on_first_call(self):
        job = self._job('API3', status=Job.STATUS_APPROVED)
        r = self.client.post(self._url(job), {}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.assertNotIn('confirm_required', r.data)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)

    def test_non_approved_job_is_a_400(self):
        job = self._job('API4')
        r = self.client.post(self._url(job, confirm=True), {}, format='json')
        self.assertEqual(r.status_code, 400, getattr(r, 'data', None))
        self.assertIn('detail', r.data)

    def test_plain_worker_is_forbidden(self):
        job = self._job('API5', status=Job.STATUS_APPROVED)
        worker = User.objects.create_user(username='rtf_worker', password='x')
        client = APIClient()
        client.force_authenticate(user=worker)
        r = client.post(self._url(job, confirm=True), {}, format='json')
        self.assertEqual(r.status_code, 403, getattr(r, 'data', None))
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_APPROVED)
