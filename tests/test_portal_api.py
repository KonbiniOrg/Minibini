from decimal import Decimal
from django.test import Client, TestCase

from apps.contacts.models import Contact
from apps.core.models import Configuration
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateService
from apps.jobs.models import Job
from apps.jobs.services import JobService


class PortalApiTest(TestCase):
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

    def test_get_open_estimate_no_auth(self):
        r = self.http.get(f'/api/portal/estimates/{self.token}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'open')
        self.assertEqual(r.json()['actions'], ['accept', 'reject'])

    def test_get_unknown_token_not_available(self):
        r = self.http.get('/api/portal/estimates/nope-not-a-token/')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()['detail'], 'Not available.')

    def test_accept_transitions_and_advances_job(self):
        r = self.http.post(f'/api/portal/estimates/{self.token}/accept/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'accepted')
        self.est.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.est.status, Estimate.STATUS_ACCEPTED)
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    def test_post_unknown_token_not_available(self):
        r = self.http.post('/api/portal/estimates/nope-not-a-token/accept/')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()['detail'], 'Not available.')

    def test_reject_transitions_and_rejects_job(self):
        r = self.http.post(
            f'/api/portal/estimates/{self.token}/reject/',
            data={'reason': 'Too costly'}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.est.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.est.status, Estimate.STATUS_REJECTED)
        self.assertEqual(self.job.status, Job.STATUS_REJECTED)

    def test_accept_on_already_terminal_is_noop(self):
        EstimateService.update_status(self.est.pk, Estimate.STATUS_ACCEPTED)
        r = self.http.post(f'/api/portal/estimates/{self.token}/accept/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'accepted')

    def test_get_draft_token_not_available(self):
        # Revising the open estimate yields a fresh draft (one tree per job).
        draft = EstimateService.revise_estimate(self.est.pk)
        draft.refresh_from_db()
        r = self.http.get(f'/api/portal/estimates/{draft.public_token}/')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()['detail'], 'Not available.')
