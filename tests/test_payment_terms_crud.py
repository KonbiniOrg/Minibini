"""PaymentTerms CRUD endpoints (Settings → Business terms manager).

Reads stay IsAuthenticated (the BusinessForm assignment select); writes
require can_manage_config (the Settings surface's atom). Deletes are
two-phase (ConfirmDeleteMixin) because Business.terms is SET_NULL.
"""
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Business, Contact, PaymentTerms
from apps.core.models import User


def _client(username, *codenames):
    user = User.objects.create_user(username=username, password='x')
    for codename in codenames:
        user.user_permissions.add(
            Permission.objects.get(codename=codename))
    client = APIClient()
    client.force_authenticate(user=User.objects.get(pk=user.pk))
    return client


def _business(name, terms=None):
    contact = Contact.objects.create(
        first_name='A', last_name=name,
        email=f'{name.lower()}@example.com')
    return Business.objects.create(
        business_name=name, default_contact=contact, terms=terms)


class PaymentTermsPermissionTest(TestCase):
    def test_reads_open_writes_config_gated(self):
        PaymentTerms.objects.create(name='Net 30', days=30)
        plain = _client('plain')
        self.assertEqual(plain.get('/api/payment-terms/').status_code, 200)
        resp = plain.post('/api/payment-terms/',
                          {'name': 'Net 45', 'days': 45}, format='json')
        self.assertEqual(resp.status_code, 403)
        cfg = _client('cfg', 'can_manage_config')
        resp = cfg.post('/api/payment-terms/',
                        {'name': 'Net 45', 'days': 45}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)


class PaymentTermsCrudTest(TestCase):
    def setUp(self):
        self.client = _client('cfg2', 'can_manage_config')

    def test_create_shape_and_optional_days(self):
        resp = self.client.post('/api/payment-terms/',
                                {'name': 'Due on receipt'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['name'], 'Due on receipt')
        self.assertIsNone(resp.data['days'])
        self.assertEqual(resp.data['business_count'], 0)
        self.assertEqual(resp.data['qbo_id'], '')

    def test_name_required(self):
        resp = self.client.post('/api/payment-terms/',
                                {'name': '', 'days': 10}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('name', resp.data)

    def test_duplicate_name_case_insensitive(self):
        PaymentTerms.objects.create(name='Net 30', days=30)
        resp = self.client.post('/api/payment-terms/',
                                {'name': 'net 30', 'days': 30}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('name', resp.data)

    def test_update_and_self_exclusion(self):
        term = PaymentTerms.objects.create(name='Net 30', days=30)
        resp = self.client.patch(f'/api/payment-terms/{term.pk}/',
                                 {'name': 'Net 30', 'days': 35},
                                 format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        term.refresh_from_db()
        self.assertEqual(term.days, 35)

    def test_qbo_id_is_read_only(self):
        term = PaymentTerms.objects.create(name='Net 30', days=30,
                                           qbo_id='3')
        self.client.patch(f'/api/payment-terms/{term.pk}/',
                          {'qbo_id': '99'}, format='json')
        term.refresh_from_db()
        self.assertEqual(term.qbo_id, '3')

    def test_business_count_annotated_on_list(self):
        term = PaymentTerms.objects.create(name='Net 30', days=30)
        _business('Acme', terms=term)
        _business('Bmce', terms=term)
        resp = self.client.get('/api/payment-terms/')
        row = next(r for r in resp.data if r['name'] == 'Net 30')
        self.assertEqual(row['business_count'], 2)


class PaymentTermsDeleteTest(TestCase):
    def setUp(self):
        self.client = _client('cfg3', 'can_manage_config')
        self.term = PaymentTerms.objects.create(name='Net 30', days=30)
        self.business = _business('Acme', terms=self.term)

    def test_first_delete_reports_impact(self):
        resp = self.client.delete(f'/api/payment-terms/{self.term.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['confirm_required'])
        self.assertEqual(resp.data['impact']['businesses'], 1)
        self.assertTrue(
            PaymentTerms.objects.filter(pk=self.term.pk).exists())

    def test_confirmed_delete_clears_businesses(self):
        resp = self.client.delete(
            f'/api/payment-terms/{self.term.pk}/?confirm=true')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('message', resp.data)
        self.assertFalse(
            PaymentTerms.objects.filter(pk=self.term.pk).exists())
        self.business.refresh_from_db()
        self.assertIsNone(self.business.terms)
