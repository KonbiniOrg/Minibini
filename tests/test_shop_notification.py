from django.core import mail
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import Configuration
from apps.estimates.services import EstimateEmailService
from apps.estimates.services import EstimateService
from apps.jobs.services import JobService


class ShopNotificationTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='Notify Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)

    def test_notifies_business_email_when_set(self):
        Configuration.objects.update_or_create(
            key='business_email', defaults={'value': 'office@shop.com'})
        EstimateEmailService.notify_shop_of_decision(self.est, 'accepted')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('office@shop.com', mail.outbox[0].to)
        self.assertIn(self.est.estimate_number, mail.outbox[0].subject)

    def test_skips_when_unset(self):
        Configuration.objects.filter(key='business_email').delete()
        EstimateEmailService.notify_shop_of_decision(self.est, 'accepted')
        self.assertEqual(len(mail.outbox), 0)

    def test_never_raises_on_send_failure(self):
        from unittest.mock import patch
        Configuration.objects.update_or_create(
            key='business_email', defaults={'value': 'office@shop.com'})
        with patch('django.core.mail.send_mail',
                   side_effect=Exception('SMTP down')):
            # Must not raise — the customer's action already committed.
            EstimateEmailService.notify_shop_of_decision(
                self.est, 'declined', reason='Budget')
        self.assertEqual(len(mail.outbox), 0)

    def test_skips_when_blank(self):
        Configuration.objects.update_or_create(
            key='business_email', defaults={'value': '   '})
        EstimateEmailService.notify_shop_of_decision(self.est, 'accepted')
        self.assertEqual(len(mail.outbox), 0)

    def test_reason_included_in_body(self):
        Configuration.objects.update_or_create(
            key='business_email', defaults={'value': 'office@shop.com'})
        EstimateEmailService.notify_shop_of_decision(
            self.est, 'declined', reason='Too expensive')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Too expensive', mail.outbox[0].body)
