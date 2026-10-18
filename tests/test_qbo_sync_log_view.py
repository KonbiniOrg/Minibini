"""
Tests for GET /api/qbo/sync-log/ — the read-only, paginated QBOSyncLog
listing behind the Settings → QBO Log tab.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase

from apps.qbo.models import QBOSyncLog

User = get_user_model()


def _user_with(username, codename):
    user = User.objects.create_user(username=username, password='testpass')
    perm = Permission.objects.get(codename=codename, content_type__app_label='core')
    user.user_permissions.add(perm)
    return User.objects.get(pk=user.pk)  # re-fetch to clear the perm cache


class QBOSyncLogViewTest(TestCase):
    URL = '/api/qbo/sync-log/'

    def setUp(self):
        self.http = Client()
        self.config_user = _user_with('cfg', 'can_manage_config')
        self.fin_user = _user_with('fin', 'can_manage_financials')
        self.actor = User.objects.create_user(
            username='actor', password='testpass', first_name='Ada', last_name='Lovelace',
        )

    def _log(self, **overrides):
        fields = dict(
            entity_type='expense', entity_id=7, qbo_entity_type='Purchase',
            qbo_entity_id='Q7', action='create', status='success',
            error_message='', triggered_by=self.actor,
        )
        fields.update(overrides)
        return QBOSyncLog.objects.create(**fields)

    # --- permissions ---

    def test_requires_authentication(self):
        r = self.http.get(self.URL)
        self.assertIn(r.status_code, (401, 403))

    def test_no_atom_is_forbidden(self):
        unpriv = User.objects.create_user(username='unpriv', password='testpass')
        self.http.force_login(unpriv)
        self.assertEqual(self.http.get(self.URL).status_code, 403)

    def test_config_atom_allowed(self):
        self.http.force_login(self.config_user)
        self.assertEqual(self.http.get(self.URL).status_code, 200)

    def test_financials_atom_allowed(self):
        self.http.force_login(self.fin_user)
        self.assertEqual(self.http.get(self.URL).status_code, 200)

    # --- shape ---

    def test_row_shape(self):
        log = self._log(status='failed', qbo_entity_id='', error_message='QBO timeout')
        self.http.force_login(self.config_user)
        data = self.http.get(self.URL).json()
        self.assertEqual(data['count'], 1)
        row = data['results'][0]
        self.assertEqual(row['id'], log.pk)
        self.assertEqual(row['entity_type'], 'expense')
        self.assertEqual(row['entity_id'], 7)
        self.assertEqual(row['qbo_entity_type'], 'Purchase')
        self.assertEqual(row['qbo_entity_id'], '')
        self.assertEqual(row['action'], 'create')
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['error_message'], 'QBO timeout')
        self.assertEqual(row['triggered_by_name'], 'Ada Lovelace')
        self.assertIn('synced_at', row)

    def test_triggered_by_none_for_cron_rows(self):
        self._log(triggered_by=None)
        self.http.force_login(self.config_user)
        row = self.http.get(self.URL).json()['results'][0]
        self.assertIsNone(row['triggered_by_name'])

    def test_newest_first(self):
        first = self._log(entity_id=1)
        second = self._log(entity_id=2)
        self.http.force_login(self.config_user)
        ids = [r['id'] for r in self.http.get(self.URL).json()['results']]
        self.assertEqual(ids, [second.pk, first.pk])

    # --- pagination ---

    def test_paginated_at_25(self):
        for i in range(30):
            self._log(entity_id=i)
        self.http.force_login(self.config_user)
        data = self.http.get(self.URL).json()
        self.assertEqual(data['count'], 30)
        self.assertEqual(len(data['results']), 25)
        self.assertIsNotNone(data['next'])
        page2 = self.http.get(self.URL, {'page': 2}).json()
        self.assertEqual(len(page2['results']), 5)

    # --- filters ---

    def test_filter_by_status(self):
        self._log(status='success')
        failed = self._log(status='failed', error_message='boom')
        self.http.force_login(self.config_user)
        data = self.http.get(self.URL, {'status': 'failed'}).json()
        self.assertEqual([r['id'] for r in data['results']], [failed.pk])

    def test_filter_by_entity_type(self):
        self._log(entity_type='expense')
        inv = self._log(entity_type='invoice', qbo_entity_type='Invoice')
        self.http.force_login(self.config_user)
        data = self.http.get(self.URL, {'entity_type': 'invoice'}).json()
        self.assertEqual([r['id'] for r in data['results']], [inv.pk])

    def test_blank_filters_are_ignored(self):
        self._log()
        self.http.force_login(self.config_user)
        data = self.http.get(self.URL, {'status': '', 'entity_type': ''}).json()
        self.assertEqual(data['count'], 1)
