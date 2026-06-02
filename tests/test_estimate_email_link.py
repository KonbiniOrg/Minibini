from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import Configuration
from apps.estimates.services import EstimateEmailService, EstimateService
from apps.jobs.services import JobService


class EstimateEmailLinkTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        # Exercise the code DEFAULT_BODY (no saved Configuration override).
        Configuration.objects.filter(
            key='estimate_email_body_template').delete()
        Configuration.objects.update_or_create(
            key='our_public_url',
            defaults={'value': 'https://shop.example.com'})
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='Link Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)

    def test_default_body_includes_portal_link(self):
        defaults = EstimateEmailService.get_email_defaults(self.est)
        self.assertIn(
            f'https://shop.example.com/portal/?token={self.est.public_token}',
            defaults['body'])
