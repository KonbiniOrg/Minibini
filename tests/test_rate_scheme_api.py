from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.jobs.models import RateScheme
from tests.base import BaseTestCase

User = get_user_model()

class RateSchemeAPITest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin', password='testpass', is_staff=True)
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(codename='can_manage_config')
        self.admin.user_permissions.add(perm)
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.scheme = RateScheme.objects.create(
            name='Hourly Labor', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45.00'), unit_label='hour',
        )

    def test_list_requires_auth(self):
        resp = self.client.get('/api/rate-schemes/')
        self.assertEqual(resp.status_code, 403)

    def test_list_authenticated(self):
        self.client.login(username='worker', password='testpass')
        resp = self.client.get('/api/rate-schemes/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['results']), 1)

    def test_create_requires_config_perm(self):
        self.client.login(username='worker', password='testpass')
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'New Scheme', 'algorithm': 'flat_fee',
            'rate': '50.00', 'unit_label': 'job',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_create_with_config_perm(self):
        self.client.login(username='admin', password='testpass')
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'CNC Setup', 'algorithm': 'flat_fee',
            'rate': '50.00', 'unit_label': 'job',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['name'], 'CNC Setup')

    def test_create_with_modifiers(self):
        self.client.login(username='admin', password='testpass')
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'CNC Router', 'algorithm': 'entered_qty',
            'rate': '4.00', 'unit_label': 'minute',
            'modifiers': [{'key': 'messy', 'label': 'Messy', 'percent': 10}],
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(resp.json()['modifiers']), 1)

    def test_update(self):
        self.client.login(username='admin', password='testpass')
        resp = self.client.patch(
            f'/api/rate-schemes/{self.scheme.pk}/',
            {'rate': '50.00'}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['rate'], '50.00')

    def test_delete(self):
        self.client.login(username='admin', password='testpass')
        resp = self.client.delete(f'/api/rate-schemes/{self.scheme.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(RateScheme.objects.filter(pk=self.scheme.pk).exists())

    def test_retrieve(self):
        self.client.login(username='worker', password='testpass')
        resp = self.client.get(f'/api/rate-schemes/{self.scheme.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['name'], 'Hourly Labor')


class RateSchemeEditBlockTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import Permission
        self.user = User.objects.create_user('admin-edit', 'admin-edit@x.test', 'pw')
        perm = Permission.objects.get(codename='can_manage_config')
        self.user.user_permissions.add(perm)
        self.client.force_login(self.user)

    def _make_referenced_scheme(self):
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme, PlanTask, Job
        from apps.estimates.models import EstWorksheet
        from apps.contacts.models import Contact, Business
        # Real schema requires Business.business_name + default_contact FK,
        # and Contact.email. Build pair: Contact first, then Business with
        # default_contact, then attach business back to contact and save.
        ac = AccountingCategory.objects.create(code='X-eb', name='X-eb')
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-eb@l.test',
        )
        biz = Business.objects.create(
            business_name='B-eb', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        job = Job.objects.create(job_number='J-eb', contact=contact)
        ws = EstWorksheet.objects.create(job=job)
        s = RateScheme.objects.create(
            name='S-eb', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        PlanTask.objects.create(
            est_worksheet=ws, name='t', rate_scheme=s,
            estimated_billable_qty=Decimal('1'),
        )
        return s

    def test_patch_referenced_scheme_returns_409(self):
        s = self._make_referenced_scheme()
        resp = self.client.patch(
            f'/api/rate-schemes/{s.pk}/',
            {'rate': '99'}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 409)
        body = resp.json()
        self.assertIn('supersede_url', body)
        self.assertIn('reference_counts', body)
        self.assertEqual(body['reference_counts']['plan_task_count'], 1)

    def test_put_referenced_scheme_returns_409(self):
        # Verify the same behavior on PUT (full update), not just PATCH.
        from apps.core.models import AccountingCategory
        s = self._make_referenced_scheme()
        ac = AccountingCategory.objects.get(code='X-eb')
        resp = self.client.put(
            f'/api/rate-schemes/{s.pk}/',
            {
                'name': 'S-eb-changed', 'algorithm': 'flat_fee',
                'rate': '99', 'unit_label': 'ea',
                'accounting_category': ac.pk,
                'modifiers': [], 'description': '',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_patch_unreferenced_scheme_succeeds(self):
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme
        ac = AccountingCategory.objects.create(code='X-ok', name='X-ok')
        s = RateScheme.objects.create(
            name='S-ok', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        resp = self.client.patch(
            f'/api/rate-schemes/{s.pk}/',
            {'rate': '2'}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
