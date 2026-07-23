"""Setup gates: pure live predicates over actual data (no flag)."""
from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, Configuration, User
from apps.core.setup_gates import gate_status
from apps.jobs.models import RateScheme


@override_settings(EMAIL_IMAP_SERVER=None, EMAIL_HOST_USER=None,
                   EMAIL_HOST_PASSWORD=None)
class GatePredicateTest(TestCase):
    def test_fresh_db_gate_states(self):
        areas = gate_status()['areas']
        self.assertFalse(areas['email']['available'])
        self.assertFalse(areas['catalog']['available'])
        self.assertFalse(areas['jobs']['available'])
        self.assertFalse(areas['estimates']['available'])
        self.assertFalse(areas['invoices']['available'])
        self.assertFalse(areas['purchasing']['available'])
        # Every unavailable area carries a non-empty unlock message.
        for area, state in areas.items():
            if not state['available']:
                self.assertTrue(state['message'], area)

    def test_contact_unlocks_jobs_estimates_invoices(self):
        Contact.objects.create(
            first_name='A', last_name='B', email='a@b.c',
            mobile_number='555-0000')
        areas = gate_status()['areas']
        self.assertTrue(areas['jobs']['available'])
        self.assertTrue(areas['estimates']['available'])
        self.assertTrue(areas['invoices']['available'])
        self.assertFalse(areas['purchasing']['available'])

    def test_catalog_needs_both_category_and_scheme(self):
        cat = AccountingCategory.objects.create(code='SVC', name='Service')
        self.assertFalse(gate_status()['areas']['catalog']['available'])
        RateScheme.objects.create(
            name='S-gate', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('1'), unit_label='ea', accounting_category=cat)
        self.assertTrue(gate_status()['areas']['catalog']['available'])

    def test_business_unlocks_purchasing(self):
        contact = Contact.objects.create(
            first_name='A', last_name='B', email='a@b.c',
            mobile_number='555-0000')
        Business.objects.create(business_name='Acme', default_contact=contact)
        self.assertTrue(gate_status()['areas']['purchasing']['available'])

    def test_email_gate_follows_email_configured(self):
        for key, value in (('email_imap_server', 'imap.x.com'),
                           ('email_address', 'a@x.com'),
                           ('email_password', 'p')):
            Configuration.objects.update_or_create(
                key=key, defaults={'value': value})
        self.assertTrue(gate_status()['areas']['email']['available'])

    def test_available_areas_have_empty_message(self):
        Contact.objects.create(
            first_name='A', last_name='B', email='a@b.c',
            mobile_number='555-0000')
        self.assertEqual(gate_status()['areas']['jobs']['message'], '')

    def test_last_pull_at_none_without_snapshot(self):
        self.assertIsNone(gate_status()['last_pull_at'])


class SetupStatusEndpointTest(TestCase):
    def test_requires_auth(self):
        resp = APIClient().get('/api/setup/status/')
        self.assertEqual(resp.status_code, 403)

    def test_shape(self):
        client = APIClient()
        client.force_authenticate(
            user=User.objects.create_user(username='u', password='x'))
        resp = client.get('/api/setup/status/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('areas', resp.data)
        self.assertIn('email', resp.data['areas'])
        self.assertIn('last_pull_at', resp.data)
