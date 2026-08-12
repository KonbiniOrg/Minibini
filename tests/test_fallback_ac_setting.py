"""fallback_accounting_category — Configuration key + settings API +
AccountingCategoryViewSet `?exclude_fallback=true` picker-exclusion param.

Phase 3 Task 1 of the nullable-AC plan: this is the Configuration key
contract every later task in the phase reads.
"""
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import AccountingCategory, Configuration, User


class FallbackAccountingCategorySettingsKeyTest(TestCase):
    """Settings PATCH/GET round-trip and validation for the
    `fallback_accounting_category` key, mirroring
    `default_deposit_accounting_category` / `default_material_accounting_category`."""

    def setUp(self):
        self.user = User.objects.create_user(username='cfg', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_config'))
        self.client = APIClient()
        self.client.login(username='cfg', password='pw')
        self.cat = AccountingCategory.objects.create(
            code='SVC', name='Service', taxable=True)
        self.dep = AccountingCategory.objects.create(
            code='DEP', name='Deposits', taxable=False, is_deposit=True)

    def _patch(self, value):
        return self.client.patch('/api/settings/',
            {'fallback_accounting_category': value}, format='json')

    def test_roundtrip(self):
        resp = self._patch(str(self.cat.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            Configuration.objects.get(
                key='fallback_accounting_category').value,
            str(self.cat.pk))

    def test_blank_clears(self):
        self._patch(str(self.cat.pk))
        resp = self._patch('')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            Configuration.objects.get(
                key='fallback_accounting_category').value, '')

    def test_rejects_non_id(self):
        resp = self._patch('not-an-id')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('fallback_accounting_category', resp.json())

    def test_rejects_unknown(self):
        resp = self._patch('999999')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('fallback_accounting_category', resp.json())

    def test_rejects_inactive(self):
        self.cat.is_active = False
        self.cat.save()
        resp = self._patch(str(self.cat.pk))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('fallback_accounting_category', resp.json())

    def test_rejects_deposit_flagged_category(self):
        resp = self._patch(str(self.dep.pk))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('fallback_accounting_category', resp.json())

    def test_get_exposes_key(self):
        self._patch(str(self.cat.pk))
        resp = self.client.get('/api/settings/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json().get('fallback_accounting_category'), str(self.cat.pk))


class ExcludeFallbackQueryParamTest(TestCase):
    """`GET /api/accounting-categories/?exclude_fallback=true` omits the
    category currently designated as the fallback."""

    def setUp(self):
        self.user = User.objects.create_user(username='cfg2', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_config'))
        self.client = APIClient()
        self.client.login(username='cfg2', password='pw')
        self.fallback_cat = AccountingCategory.objects.create(
            code='FBK', name='Fallback Category', taxable=True)
        self.other_cat = AccountingCategory.objects.create(
            code='OTH', name='Other Category', taxable=True)

    def _names(self, resp):
        data = resp.json()
        rows = data.get('results') if isinstance(data, dict) else data
        return [r['name'] for r in rows]

    def _set_fallback(self, cat):
        Configuration.objects.update_or_create(
            key='fallback_accounting_category', defaults={'value': str(cat.pk)})

    def test_excludes_designated_fallback_when_param_set(self):
        self._set_fallback(self.fallback_cat)
        resp = self.client.get('/api/accounting-categories/?exclude_fallback=true')
        self.assertEqual(resp.status_code, 200)
        names = self._names(resp)
        self.assertNotIn('Fallback Category', names)
        self.assertIn('Other Category', names)

    def test_includes_fallback_when_param_absent(self):
        self._set_fallback(self.fallback_cat)
        resp = self.client.get('/api/accounting-categories/')
        self.assertEqual(resp.status_code, 200)
        names = self._names(resp)
        self.assertIn('Fallback Category', names)

    def test_param_is_noop_when_no_key_configured(self):
        Configuration.objects.filter(key='fallback_accounting_category').delete()
        resp = self.client.get('/api/accounting-categories/?exclude_fallback=true')
        self.assertEqual(resp.status_code, 200)
        names = self._names(resp)
        self.assertIn('Fallback Category', names)
        self.assertIn('Other Category', names)


class IsFallbackSerializerFieldTest(TestCase):
    """`is_fallback` on AccountingCategorySerializer marks exactly the
    Configuration-designated row (and is False for every row when no
    fallback is configured) — the mechanism the SPA now uses to filter
    picker `<select>` options client-side while keeping name-lookup paths
    (which read the unfiltered list) intact."""

    def setUp(self):
        self.user = User.objects.create_user(username='cfg3', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_config'))
        self.client = APIClient()
        self.client.login(username='cfg3', password='pw')
        self.fallback_cat = AccountingCategory.objects.create(
            code='FBK2', name='Fallback Category 2', taxable=True)
        self.other_cat = AccountingCategory.objects.create(
            code='OTH2', name='Other Category 2', taxable=True)

    def _rows(self, resp):
        data = resp.json()
        return data.get('results') if isinstance(data, dict) else data

    def test_marks_exactly_the_designated_row(self):
        Configuration.objects.update_or_create(
            key='fallback_accounting_category',
            defaults={'value': str(self.fallback_cat.pk)})
        resp = self.client.get('/api/accounting-categories/')
        self.assertEqual(resp.status_code, 200)
        by_id = {r['id']: r['is_fallback'] for r in self._rows(resp)}
        self.assertTrue(by_id[self.fallback_cat.pk])
        self.assertFalse(by_id[self.other_cat.pk])

    def test_all_false_when_no_key_configured(self):
        Configuration.objects.filter(key='fallback_accounting_category').delete()
        resp = self.client.get('/api/accounting-categories/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            all(not r['is_fallback'] for r in self._rows(resp)))

    def test_retrieve_marks_the_designated_row(self):
        Configuration.objects.update_or_create(
            key='fallback_accounting_category',
            defaults={'value': str(self.fallback_cat.pk)})
        resp = self.client.get(
            f'/api/accounting-categories/{self.fallback_cat.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['is_fallback'])
