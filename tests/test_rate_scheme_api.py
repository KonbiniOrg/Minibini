from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.jobs.models import RateScheme

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
