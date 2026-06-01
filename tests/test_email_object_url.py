from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.email_templates import build_object_url
from apps.core.models import Configuration
from apps.estimates.services import EstimateService
from apps.jobs.services import JobService


class BuildObjectUrlEstimateTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        Configuration.objects.update_or_create(
            key='our_public_url', defaults={'value': 'https://shop.example.com'})
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='URL Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)

    def test_estimate_url_uses_portal_token(self):
        url = build_object_url('estimate', self.est.estimate_id)
        self.assertEqual(
            url, f'https://shop.example.com/portal/?token={self.est.public_token}')

    def test_other_kinds_keep_stub(self):
        url = build_object_url('invoice', 42)
        self.assertEqual(url, 'https://shop.example.com/invoices/42')

    def test_estimate_without_token_falls_back_to_stub(self):
        self.est.public_token = None
        self.est.save(update_fields=['public_token'])
        url = build_object_url('estimate', self.est.estimate_id)
        self.assertEqual(
            url, f'https://shop.example.com/estimates/{self.est.estimate_id}')
