"""Portal must respect JOB status, not just estimate status.

An estimate can legitimately be `open` (customer hasn't acted) while the shop
independently moves the job (cancel, reject, manual approve, reopen). In those
cases the customer portal must not offer Accept/Request-changes/Decline, and
must show a read-only "not open for response" message. No estimate status is
mutated from the job side.

Spec discussion: this session. Wording is fixed (see CLOSED_MESSAGE).
"""
from decimal import Decimal
from django.test import Client, TestCase

from apps.contacts.models import Contact
from apps.core.models import Configuration
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateService
from apps.jobs.models import Job
from apps.jobs.services import JobService


CLOSED_MESSAGE = (
    'This estimate is not open for response.  Please contact us for further '
    'information.'
)


class PortalJobStatusGateTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.http = Client()  # unauthenticated
        Configuration.objects.update_or_create(
            key='business_email', defaults={'value': 'office@shop.com'})
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Work', qty=Decimal('1'),
            price=Decimal('100.00'), units='ea')
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        self.est.refresh_from_db()
        self.job.refresh_from_db()
        self.token = self.est.public_token
        assert self.job.status == Job.STATUS_SUBMITTED

    def _advance_job(self, status):
        JobService.update_status(self.job.pk, status)
        self.job.refresh_from_db()

    # --- actionable: open + submitted ---

    def test_open_submitted_is_actionable(self):
        r = self.http.get(f'/api/portal/estimates/{self.token}/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['actionable'])
        self.assertEqual(
            r.json()['actions'], ['accept', 'request_changes', 'reject'])
        self.assertIsNone(r.json()['closed_message'])

    # --- not actionable: open estimate but job advanced/closed ---

    def test_open_but_job_approved_is_not_actionable(self):
        self._advance_job(Job.STATUS_APPROVED)
        r = self.http.get(f'/api/portal/estimates/{self.token}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'open')  # estimate untouched
        self.assertFalse(r.json()['actionable'])
        self.assertEqual(r.json()['actions'], [])
        self.assertEqual(r.json()['closed_message'], CLOSED_MESSAGE)

    def test_open_but_job_cancelled_is_not_actionable(self):
        # Reachable: submitted -> approved -> cancelled, estimate stays open.
        self._advance_job(Job.STATUS_APPROVED)
        self._advance_job(Job.STATUS_CANCELLED)
        r = self.http.get(f'/api/portal/estimates/{self.token}/')
        self.assertEqual(r.json()['closed_message'], CLOSED_MESSAGE)
        self.assertEqual(r.json()['actions'], [])

    # --- POST handlers must also refuse server-side (stale tab) ---

    def test_accept_is_noop_when_job_not_submitted(self):
        self._advance_job(Job.STATUS_APPROVED)
        r = self.http.post(f'/api/portal/estimates/{self.token}/accept/')
        self.assertEqual(r.status_code, 200)
        self.est.refresh_from_db()
        self.assertEqual(self.est.status, Estimate.STATUS_OPEN)  # not accepted

    def test_reject_is_noop_when_job_not_submitted(self):
        self._advance_job(Job.STATUS_APPROVED)
        r = self.http.post(
            f'/api/portal/estimates/{self.token}/reject/',
            data={'reason': 'x'}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.est.refresh_from_db()
        self.assertEqual(self.est.status, Estimate.STATUS_OPEN)

    def test_request_changes_is_noop_when_job_not_submitted(self):
        self._advance_job(Job.STATUS_APPROVED)
        r = self.http.post(
            f'/api/portal/estimates/{self.token}/request-changes/',
            data={'reason': 'x'}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.est.refresh_from_db()
        self.assertEqual(self.est.status, Estimate.STATUS_OPEN)
        self.assertFalse(
            Estimate.objects.filter(
                job=self.job, status=Estimate.STATUS_DRAFT).exists())


class PortalSupersededCurrentTokenTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.http = Client()
        Configuration.objects.update_or_create(
            key='business_email', defaults={'value': 'office@shop.com'})
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='Job', contact=self.contact)
        self.v1 = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=self.v1, description='Work', qty=Decimal('1'),
            price=Decimal('100.00'), units='ea')
        EstimateService.update_status(self.v1.pk, Estimate.STATUS_OPEN)

    def test_superseded_points_to_latest_non_draft(self):
        v2 = EstimateService.revise_estimate(self.v1.pk)  # v1 superseded, v2 draft
        EstimateService.update_status(v2.pk, Estimate.STATUS_OPEN)  # v2 now open
        v2.refresh_from_db()
        self.v1.refresh_from_db()
        r = self.http.get(f'/api/portal/estimates/{self.v1.public_token}/')
        self.assertEqual(r.json()['status'], 'superseded')
        self.assertEqual(r.json()['current_token'], v2.public_token)

    def test_superseded_with_only_a_draft_successor_has_no_link(self):
        EstimateService.revise_estimate(self.v1.pk)  # v1 superseded, v2 draft (unsent)
        self.v1.refresh_from_db()
        r = self.http.get(f'/api/portal/estimates/{self.v1.public_token}/')
        self.assertEqual(r.json()['status'], 'superseded')
        # Don't link the customer to an unviewable draft.
        self.assertIsNone(r.json()['current_token'])
