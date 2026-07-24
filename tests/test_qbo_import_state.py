"""Per-area dismissal state + pull/dismiss endpoints + diff summary."""
import json
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Business, Contact, PaymentTerms
from apps.core.models import Configuration, User
from apps.inventory.models import InventoryItem
from apps.core.models import AccountingCategory
from apps.qbo.import_services import (
    QBOImportState, QBOImportSummary, QBOSnapshotService,
)

SNAPSHOT = {
    'version': 1, 'fetched_at': '2026-07-23T20:00:00+00:00',
    'items': [
        {'qbo_id': '11', 'name': 'CNC Cutting', 'type': 'Service',
         'unit_price': '95.0', 'description': '', 'income_account_id': '4000',
         'income_account_name': 'Service Income', 'expense_account_id': '',
         'purchase_cost': '0', 'taxable': True},
        {'qbo_id': '12', 'name': 'Baltic Birch', 'type': 'NonInventory',
         'unit_price': '85.0', 'description': '4x8', 'income_account_id': '4100',
         'income_account_name': 'Sales of Product', 'expense_account_id': '5000',
         'purchase_cost': '52.5', 'taxable': True},
    ],
    'income_accounts': [
        {'qbo_id': '4000', 'name': 'Service Income', 'type': 'Income'},
        {'qbo_id': '4100', 'name': 'Sales of Product', 'type': 'Income'},
    ],
    'expense_accounts': [{'qbo_id': '5000', 'name': 'COGS',
                          'type': 'Cost of Goods Sold'}],
    'customers': [{'qbo_id': '71', 'display_name': 'Acme Corp',
                   'company_name': 'Acme Corp', 'given_name': 'Jo',
                   'family_name': 'Acme', 'email': 'jo@acme.com',
                   'phone': '', 'term_qbo_id': '3'}],
    'vendors': [{'qbo_id': '81', 'display_name': 'Moore Newton',
                 'company_name': 'Moore Newton', 'email': '', 'phone': ''}],
    'terms': [{'qbo_id': '3', 'name': 'Net 30', 'due_days': 30}],
}


def store_snapshot():
    Configuration.objects.update_or_create(
        key=QBOSnapshotService.KEY,
        defaults={'value': json.dumps(SNAPSHOT)})


class ImportStateTest(TestCase):
    def test_dismiss_roundtrip(self):
        self.assertEqual(QBOImportState.dismissed(), {})
        QBOImportState.dismiss('inventory')
        self.assertEqual(QBOImportState.dismissed(), {'inventory': True})
        QBOImportState.undismiss('inventory')
        self.assertEqual(QBOImportState.dismissed(), {})

    def test_unknown_area_rejected(self):
        with self.assertRaises(ValueError):
            QBOImportState.dismiss('bogus')


class DiffSummaryTest(TestCase):
    def test_counts_new_vs_imported(self):
        store_snapshot()
        InventoryItem.objects.create(
            code='PLY', qbo_id='12',
            accounting_category=AccountingCategory.objects.create(
                code='MAT', name='Material'))
        PaymentTerms.objects.create(name='Net 30', qbo_id='3')
        summary = QBOImportSummary.diff_summary()
        self.assertEqual(summary['items'], {'total': 2, 'imported': 1, 'new': 1})
        self.assertEqual(summary['terms'], {'total': 1, 'imported': 1, 'new': 0})
        self.assertEqual(summary['customers']['new'], 1)
        self.assertEqual(summary['vendors']['new'], 1)


class PullEndpointTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.config_user = User.objects.create_user(username='cfg', password='x')
        self.config_user.user_permissions.add(
            Permission.objects.get(codename='can_manage_config'))
        self.jobs_user = User.objects.create_user(username='jobs', password='x')
        self.jobs_user.user_permissions.add(
            Permission.objects.get(codename='can_manage_jobs'))

    def _pull(self, user, area):
        self.client.force_authenticate(user=user)
        with patch('apps.qbo.import_services.QBOSnapshotService.pull',
                   return_value=SNAPSHOT), \
             patch('apps.api.qbo_import.views.QBOService.get_client',
                   return_value=object()):
            return self.client.post('/api/qbo/import/pull/', {'area': area},
                                    format='json')

    def test_pull_requires_area_permission(self):
        resp = self._pull(self.jobs_user, 'categories')
        self.assertEqual(resp.status_code, 403)
        resp = self._pull(self.config_user, 'categories')
        self.assertEqual(resp.status_code, 200)

    def test_contacts_area_allows_jobs_permission(self):
        resp = self._pull(self.jobs_user, 'contacts')
        self.assertEqual(resp.status_code, 200)

    def test_pull_returns_summary_and_clears_own_dismissal_only(self):
        QBOImportState.dismiss('categories')
        QBOImportState.dismiss('contacts')
        resp = self._pull(self.config_user, 'categories')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['fetched_at'], SNAPSHOT['fetched_at'])
        self.assertIn('summary', resp.data)
        dismissed = QBOImportState.dismissed()
        self.assertNotIn('categories', dismissed)   # own flag cleared
        self.assertIn('contacts', dismissed)        # others sticky

    def test_pull_without_connection_400(self):
        self.client.force_authenticate(user=self.config_user)
        with patch('apps.api.qbo_import.views.QBOService.get_client',
                   return_value=None):
            resp = self.client.post('/api/qbo/import/pull/',
                                    {'area': 'categories'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['detail'], 'No active QBO connection.')

    def test_dismiss_endpoint(self):
        self.client.force_authenticate(user=self.config_user)
        resp = self.client.post('/api/qbo/import/dismiss/',
                                {'area': 'schemes'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('schemes', QBOImportState.dismissed())
