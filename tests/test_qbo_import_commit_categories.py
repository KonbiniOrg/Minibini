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
             'unit_label': 'hour', 'accounting_category': self.cat.pk,
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
             'unit_label': 'hour', 'accounting_category': self.cat.pk,
             'qbo_item_id': '11', 'collapse_group': 'shop'},
        ])
        rows = QBOSuggestionService.suggestions('services')['rows']
        svc = next(r for r in rows if r['qbo_id'] == '11')
        # Name-matching would fail ('Shop rate' != 'CNC Cutting'); the
        # persisted mapping resolves it.
        self.assertEqual(svc['rate_scheme_default'], mapping['11'])

    def test_elapsed_row_normalizes_unit_to_hour(self):
        mapping = QBOImportCommitService.commit_schemes([
            {'name': 'Shop rate', 'rate': '95.0', 'algorithm': 'elapsed_time',
             'unit_label': 'ea', 'accounting_category': self.cat.pk,
             'qbo_item_id': '13', 'collapse_group': None},
        ])
        scheme = RateScheme.objects.get(pk=mapping['13'])
        self.assertEqual(scheme.unit_label, 'hour')

    def test_collapse_group_shares_one_scheme(self):
        mapping = QBOImportCommitService.commit_schemes([
            {'name': 'Shop rate', 'rate': '95.0', 'algorithm': 'elapsed_time',
             'unit_label': 'hour', 'accounting_category': self.cat.pk,
             'qbo_item_id': '11', 'collapse_group': 'shop'},
            {'name': 'CNC hourly', 'rate': '95.0', 'algorithm': 'elapsed_time',
             'unit_label': 'hour', 'accounting_category': self.cat.pk,
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


class CommitSchemesUpsertTest(TestCase):
    """Re-applying the panel must update mapped schemes, never duplicate."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(code='SVC', name='Service')
        store_snapshot()

    def _row(self, **overrides):
        row = {'name': 'Concrete', 'rate': '0', 'algorithm': 'entered_qty',
               'unit_label': 'ea', 'accounting_category': self.cat.pk,
               'qbo_item_id': '11', 'collapse_group': None}
        row.update(overrides)
        return row

    def test_recommit_updates_unreferenced_scheme_in_place(self):
        QBOImportCommitService.commit_schemes([self._row()])
        mapping = QBOImportCommitService.commit_schemes([
            self._row(rate='95.0', algorithm='elapsed_time',
                      unit_label='hour')])
        self.assertEqual(RateScheme.objects.count(), 1)
        scheme = RateScheme.objects.get()
        self.assertEqual(scheme.rate, Decimal('95.0'))
        self.assertEqual(scheme.algorithm, RateScheme.ELAPSED_TIME)
        self.assertEqual(scheme.unit_label, 'hour')
        self.assertEqual(mapping['11'], scheme.pk)

    def test_recommit_referenced_scheme_updates_in_place(self):
        """Task 4: presets are freely editable — a recommit with a changed
        price updates the existing scheme row (same pk), it does not create
        a new version. The ServiceItem's FK never needs repointing."""
        from apps.estimates.models import ServiceItem
        mapping = QBOImportCommitService.commit_schemes([
            self._row(rate='95.0')])
        old = RateScheme.objects.get(pk=mapping['11'])
        svc = ServiceItem.objects.create(
            template_name='Concrete', rate_scheme=old, qbo_id='11')
        mapping2 = QBOImportCommitService.commit_schemes([
            self._row(rate='110.0')])
        old.refresh_from_db()
        svc.refresh_from_db()
        self.assertEqual(mapping2['11'], old.pk)
        self.assertEqual(svc.rate_scheme_id, old.pk)
        self.assertEqual(svc.rate_scheme.rate, Decimal('110.0'))
        self.assertEqual(RateScheme.objects.count(), 1)

    def test_recommit_referenced_scheme_unchanged_is_noop(self):
        from apps.estimates.models import ServiceItem
        mapping = QBOImportCommitService.commit_schemes([
            self._row(rate='95.0')])
        old = RateScheme.objects.get(pk=mapping['11'])
        ServiceItem.objects.create(
            template_name='Concrete', rate_scheme=old, qbo_id='11')
        mapping2 = QBOImportCommitService.commit_schemes([self._row(rate='95.0')])
        old.refresh_from_db()
        self.assertEqual(mapping2['11'], old.pk)
        self.assertEqual(RateScheme.objects.count(), 1)

    def test_create_name_collision_is_contract_400_not_500(self):
        RateScheme.objects.create(
            name='Concrete', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50.0'), unit_label='ea',
            accounting_category=self.cat)
        with self.assertRaises(ValidationError) as ctx:
            QBOImportCommitService.commit_schemes([self._row()])
        self.assertIn('name', ctx.exception.message_dict)
        self.assertEqual(RateScheme.objects.count(), 1)


class CommitValidationTest(TestCase):
    def test_scheme_without_category_is_contract_400_not_500(self):
        from django.core.exceptions import ValidationError as DjangoVE
        cat_missing_row = [{'name': 'Orphan', 'rate': '10', 'algorithm':
                            'entered_qty', 'unit_label': 'ea',
                            'accounting_category': None,
                            'qbo_item_id': '99', 'collapse_group': None}]
        with self.assertRaises(DjangoVE) as ctx:
            QBOImportCommitService.commit_schemes(cat_missing_row)
        self.assertIn('accounting_category', ctx.exception.message_dict)
        self.assertEqual(RateScheme.objects.count(), 0)

    def test_catalog_service_without_scheme_rejected(self):
        from django.core.exceptions import ValidationError as DjangoVE
        with self.assertRaises(DjangoVE) as ctx:
            QBOImportCommitService.commit_catalog([
                {'kind': 'service', 'action': 'create', 'qbo_id': '11',
                 'name': 'CNC', 'description': '', 'rate_scheme': None}])
        self.assertIn('rate_scheme', ctx.exception.message_dict)
