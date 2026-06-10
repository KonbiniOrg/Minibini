"""Tests for the portal "Request changes" customer-initiated revision flow.

Spec: docs/plans/2026-06-03-portal-request-changes.md
"""
from decimal import Decimal
from apps.core.models import JobHistory

from django.core.exceptions import ValidationError
from django.test import Client, TestCase

from apps.contacts.models import Contact
from apps.core.models import Configuration, HistoryEntry
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateService
from apps.jobs.models import Job
from apps.jobs.services import JobService


class JobSubmittedToDraftTransitionTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='T', last_name='X', email='t@x.com')
        self.job = JobService.create_job(name='J', contact=self.contact)

    def test_submitted_to_draft_is_now_valid(self):
        JobService.update_status(self.job.pk, Job.STATUS_SUBMITTED)
        # Should not raise: re-quoting sends a submitted job back to draft.
        JobService.update_status(self.job.pk, Job.STATUS_DRAFT)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_DRAFT)

    def test_submitted_to_in_progress_still_invalid(self):
        JobService.update_status(self.job.pk, Job.STATUS_SUBMITTED)
        with self.assertRaises(ValidationError):
            JobService.update_status(self.job.pk, Job.STATUS_IN_PROGRESS)


class RequestChangesServiceTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='API Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Work', qty=Decimal('1'),
            price=Decimal('100.00'))
        # Sending the estimate auto-advances the job to submitted (signal).
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

    def _actor(self, reason='please cut line 1'):
        return {'contact_id': self.contact.pk, 'email': self.contact.email,
                'reason': reason}

    def test_returns_new_draft_revision(self):
        new_est = EstimateService.request_changes(self.est.pk, self._actor())
        self.assertEqual(new_est.status, Estimate.STATUS_DRAFT)
        self.assertEqual(new_est.version, self.est.version + 1)

    def test_supersedes_the_parent(self):
        EstimateService.request_changes(self.est.pk, self._actor())
        self.est.refresh_from_db()
        self.assertEqual(self.est.status, Estimate.STATUS_SUPERSEDED)

    def test_reverts_job_to_draft(self):
        EstimateService.request_changes(self.est.pk, self._actor())
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_DRAFT)

    def test_carries_line_items_to_revision(self):
        new_est = EstimateService.request_changes(self.est.pk, self._actor())
        descriptions = list(
            EstimateLineItem.objects.filter(estimate=new_est)
            .values_list('description', flat=True))
        self.assertEqual(descriptions, ['Work'])

    def test_records_comment_as_customer_action_history(self):
        EstimateService.request_changes(
            self.est.pk, self._actor(reason='need it 2 weeks sooner'))
        entry = JobHistory.objects.filter(
            object_type='estimate', object_id=self.est.pk,
            entry_type='action', user__isnull=True,
        ).order_by('-pk').first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.text, 'need it 2 weeks sooner')
        self.assertEqual(
            entry.changes.get('_action'), 'Changes requested via customer link')
        self.assertEqual(entry.changes.get('contact_id'), self.contact.pk)


class PortalRequestChangesTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.http = Client()  # deliberately unauthenticated
        Configuration.objects.update_or_create(
            key='business_email', defaults={'value': 'office@shop.com'})
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='API Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Work', qty=Decimal('1'),
            price=Decimal('100.00'))
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        self.est.refresh_from_db()
        self.token = self.est.public_token

    def test_open_estimate_exposes_request_changes_action(self):
        r = self.http.get(f'/api/portal/estimates/{self.token}/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('request_changes', r.json()['actions'])

    def test_request_changes_revises_and_reverts(self):
        r = self.http.post(
            f'/api/portal/estimates/{self.token}/request-changes/',
            data={'reason': 'cut line 1'}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.est.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.est.status, Estimate.STATUS_SUPERSEDED)
        self.assertEqual(self.job.status, Job.STATUS_DRAFT)
        # A fresh draft revision exists for the job.
        self.assertTrue(
            Estimate.objects.filter(
                job=self.job, status=Estimate.STATUS_DRAFT,
                version=self.est.version + 1).exists())

    def test_request_changes_stores_comment(self):
        self.http.post(
            f'/api/portal/estimates/{self.token}/request-changes/',
            data={'reason': 'cut line 1'}, content_type='application/json')
        entry = JobHistory.objects.filter(
            object_type='estimate', object_id=self.est.pk,
            entry_type='action').order_by('-pk').first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.text, 'cut line 1')

    def test_request_changes_on_non_open_is_noop(self):
        # Take it to accepted first; a later request-changes must not revise.
        EstimateService.update_status(self.est.pk, Estimate.STATUS_ACCEPTED)
        r = self.http.post(
            f'/api/portal/estimates/{self.token}/request-changes/',
            data={'reason': 'late'}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(
            Estimate.objects.filter(job=self.job, status=Estimate.STATUS_DRAFT).exists())

    def test_request_changes_unknown_token_404(self):
        r = self.http.post(
            '/api/portal/estimates/nope-not-a-token/request-changes/',
            data={'reason': 'x'}, content_type='application/json')
        self.assertEqual(r.status_code, 404)


class JobChangeRequestBannerTest(TestCase):
    """The job detail API surfaces the latest customer change-request comment so
    the SPA can show a banner over the auto-staged draft."""
    fixtures = ['unit_test_data.json']

    def setUp(self):
        from rest_framework.test import APIClient
        from apps.core.models import User
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Work', qty=Decimal('1'),
            price=Decimal('100.00'))
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)

    def test_no_change_request_is_null(self):
        r = self.client.get(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data['latest_change_request'])

    def test_surfaces_latest_change_request_comment(self):
        EstimateService.request_changes(
            self.est.pk,
            {'contact_id': self.contact.pk, 'email': self.contact.email,
             'reason': 'cut line 1 and rush it'})
        r = self.client.get(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.data['latest_change_request'])
        self.assertEqual(
            r.data['latest_change_request']['text'], 'cut line 1 and rush it')
