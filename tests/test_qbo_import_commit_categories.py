"""commit_categories / commit_schemes: user-confirmed rows become models."""
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import AccountingCategory, User
from apps.jobs.models import RateScheme
from apps.qbo.import_services import QBOImportCommitService, QBOImportState
from tests.test_qbo_import_state import store_snapshot


class CommitCategoriesTest(TestCase):
    def test_creates_categories(self):
        created = QBOImportCommitService.commit_categories([
            {'name': 'Service', 'code': 'SVC', 'taxable': True,
             'qbo_item_id': '11', 'qbo_expense_account_id': ''},
            {'name': 'Shipping', 'code': 'SHIP', 'taxable': False,
             'qbo_item_id': '', 'qbo_expense_account_id': '5000'},
        ])
        self.assertEqual(len(created), 2)
        svc = AccountingCategory.objects.get(code='SVC')
        self.assertTrue(svc.taxable)
        self.assertEqual(svc.qbo_item_id, '11')
        ship = AccountingCategory.objects.get(code='SHIP')
        self.assertEqual(ship.qbo_expense_account_id, '5000')

    def test_duplicate_code_atomic_rollback(self):
        AccountingCategory.objects.create(code='SVC', name='Existing')
        with self.assertRaises(ValidationError):
            QBOImportCommitService.commit_categories([
                {'name': 'New OK', 'code': 'OK1', 'taxable': True,
                 'qbo_item_id': '', 'qbo_expense_account_id': ''},
                {'name': 'Dupe', 'code': 'SVC', 'taxable': True,
                 'qbo_item_id': '', 'qbo_expense_account_id': ''},
            ])
        self.assertFalse(
            AccountingCategory.objects.filter(code='OK1').exists())

    def test_auto_dismiss_when_diff_empties(self):
        store_snapshot()
        QBOImportCommitService.commit_categories([
            {'name': 'Service Income', 'code': 'SI', 'taxable': True,
             'qbo_item_id': '11', 'qbo_expense_account_id': ''},
            {'name': 'Sales of Product', 'code': 'SP', 'taxable': True,
             'qbo_item_id': '12', 'qbo_expense_account_id': '5000'},
        ])
        self.assertIn('categories', QBOImportState.dismissed())


class CommitSchemesTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(code='SVC', name='Service')

    def test_one_scheme_per_row(self):
        mapping = QBOImportCommitService.commit_schemes([
            {'name': 'CNC Cutting', 'rate': '95.0', 'algorithm': 'entered_qty',
             'unit_label': 'ea', 'accounting_category': self.cat.pk,
             'qbo_item_id': '11', 'collapse_group': None},
            {'name': 'Finishing', 'rate': '80.0', 'algorithm': 'elapsed_time',
             'unit_label': 'hours', 'accounting_category': self.cat.pk,
             'qbo_item_id': '12', 'collapse_group': None},
        ])
        self.assertEqual(RateScheme.objects.count(), 2)
        cnc = RateScheme.objects.get(name='CNC Cutting')
        self.assertEqual(cnc.rate, Decimal('95.0'))
        self.assertEqual(mapping['11'], cnc.pk)
        self.assertEqual(
            RateScheme.objects.get(pk=mapping['12']).algorithm,
            RateScheme.ELAPSED_TIME)

    def test_scheme_mapping_feeds_catalog_defaults(self):
        from tests.test_qbo_import_state import store_snapshot
        from apps.qbo.import_services import QBOSuggestionService
        store_snapshot()
        mapping = QBOImportCommitService.commit_schemes([
            {'name': 'Shop rate', 'rate': '95.0', 'algorithm': 'elapsed_time',
             'unit_label': 'hours', 'accounting_category': self.cat.pk,
             'qbo_item_id': '11', 'collapse_group': 'shop'},
        ])
        rows = QBOSuggestionService.suggestions('catalog')['rows']
        svc = next(r for r in rows if r['qbo_id'] == '11')
        # Name-matching would fail ('Shop rate' != 'CNC Cutting'); the
        # persisted mapping resolves it.
        self.assertEqual(svc['rate_scheme_default'], mapping['11'])

    def test_collapse_group_shares_one_scheme(self):
        mapping = QBOImportCommitService.commit_schemes([
            {'name': 'Shop rate', 'rate': '95.0', 'algorithm': 'elapsed_time',
             'unit_label': 'hours', 'accounting_category': self.cat.pk,
             'qbo_item_id': '11', 'collapse_group': 'shop'},
            {'name': 'CNC hourly', 'rate': '95.0', 'algorithm': 'elapsed_time',
             'unit_label': 'hours', 'accounting_category': self.cat.pk,
             'qbo_item_id': '12', 'collapse_group': 'shop'},
        ])
        self.assertEqual(RateScheme.objects.count(), 1)
        scheme = RateScheme.objects.get()
        self.assertEqual(scheme.name, 'Shop rate')  # first row names it
        self.assertEqual(mapping['11'], scheme.pk)
        self.assertEqual(mapping['12'], scheme.pk)


class CommitEndpointsTest(TestCase):
    def test_categories_endpoint_permission_and_shape(self):
        client = APIClient()
        user = User.objects.create_user(username='cfg3', password='x')
        user.user_permissions.add(
            Permission.objects.get(codename='can_manage_config'))
        client.force_authenticate(user=User.objects.get(pk=user.pk))
        resp = client.post('/api/qbo/import/commit/categories/', {
            'rows': [{'name': 'Service', 'code': 'SVC', 'taxable': True,
                      'qbo_item_id': '', 'qbo_expense_account_id': ''}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['created'], 1)
        self.assertTrue(
            AccountingCategory.objects.filter(code='SVC').exists())
