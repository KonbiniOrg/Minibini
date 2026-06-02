from django.test import TestCase

from apps.contacts.models import Contact
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateService
from apps.jobs.services import JobService


class EstimatePublicTokenTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer',
            email='pat@acme.com', work_number='555-0000',
        )
        self.job = JobService.create_job(name='Token Job', contact=self.contact)

    def test_token_minted_on_create(self):
        est = EstimateService.create_for_job(self.job.pk)
        self.assertTrue(est.public_token)
        self.assertGreaterEqual(len(est.public_token), 20)

    def test_token_is_stable_across_saves(self):
        est = EstimateService.create_for_job(self.job.pk)
        token = est.public_token
        # Re-save without touching the token; the not-self.pk guard must
        # leave the existing token unchanged.
        est.save()
        est.refresh_from_db()
        self.assertEqual(est.public_token, token)

    def test_two_estimates_get_distinct_tokens(self):
        a = EstimateService.create_for_job(self.job.pk)
        job2 = JobService.create_job(name='Token Job 2', contact=self.contact)
        b = EstimateService.create_for_job(job2.pk)
        self.assertNotEqual(a.public_token, b.public_token)
