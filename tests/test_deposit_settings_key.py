from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import AccountingCategory, Configuration, User


class DepositSettingsKeyTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='cfg', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_config'))
        self.client = APIClient()
        self.client.login(username='cfg', password='pw')
        self.dep = AccountingCategory.objects.create(
            code='DEP', name='Deposits', taxable=False, is_deposit=True)
        self.std = AccountingCategory.objects.create(
            code='SVC', name='Service', taxable=True)

    def _patch(self, value):
        return self.client.patch('/api/settings/',
            {'default_deposit_accounting_category': value}, format='json')

    def test_roundtrip(self):
        resp = self._patch(str(self.dep.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            Configuration.objects.get(
                key='default_deposit_accounting_category').value,
            str(self.dep.pk))

    def test_rejects_non_deposit_category(self):
        resp = self._patch(str(self.std.pk))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('default_deposit_accounting_category', resp.json())

    def test_rejects_inactive(self):
        self.dep.is_active = False
        self.dep.save()
        self.assertEqual(self._patch(str(self.dep.pk)).status_code, 400)

    def test_rejects_unknown(self):
        self.assertEqual(self._patch('999999').status_code, 400)

    def test_blank_clears(self):
        self._patch(str(self.dep.pk))
        resp = self._patch('')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            Configuration.objects.get(
                key='default_deposit_accounting_category').value, '')
