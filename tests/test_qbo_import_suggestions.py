"""QBOSuggestionService: live snapshot-vs-database diffs per panel area."""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.contacts.models import Business, Contact, PaymentTerms
from apps.core.models import AccountingCategory
from apps.estimates.models import ServiceItem
from apps.inventory.models import InventoryItem
from apps.jobs.models import RateScheme
from apps.qbo.import_services import (
    QBOImportState, QBOSuggestionService, QBOSnapshotService,
)
from tests.test_qbo_import_state import SNAPSHOT, store_snapshot


class ShortCircuitTest(TestCase):
    def test_no_snapshot_returns_empty(self):
        out = QBOSuggestionService.suggestions('categories')
        self.assertEqual(out, {'dismissed': False, 'fetched_at': None,
                               'rows': []})

    def test_dismissed_area_skips_snapshot_parse(self):
        store_snapshot()
        QBOImportState.dismiss('categories')
        with patch.object(QBOSnapshotService, 'load') as mock_load:
            out = QBOSuggestionService.suggestions('categories')
        mock_load.assert_not_called()
        self.assertTrue(out['dismissed'])
        self.assertEqual(out['rows'], [])


class CategorySuggestionTest(TestCase):
    def setUp(self):
        store_snapshot()

    def test_clusters_and_itemless_accounts(self):
        rows = QBOSuggestionService.suggestions('categories')['rows']
        by_account = {r['income_account']['qbo_id']: r for r in rows}
        # 4000 (1 service item), 4100 (1 noninventory item) — no itemless
        # accounts in the fixture beyond these two.
        self.assertEqual(set(by_account), {'4000', '4100'})
        svc = by_account['4000']
        self.assertEqual(svc['member_count'], 1)
        self.assertEqual(svc['suggested']['name'], 'Service Income')
        self.assertTrue(svc['suggested']['code'])
        self.assertTrue(svc['suggested']['taxable'])
        self.assertEqual(svc['fallback_item_options'],
                         [{'qbo_id': '11', 'name': 'CNC Cutting'}])
        self.assertEqual(svc['fallback_item_default'], '11')
        self.assertEqual(svc['expense_account_default'], '')
        self.assertEqual(svc['state'], 'new')
        # 4100's sole member is two-sided → expense default derived.
        self.assertEqual(by_account['4100']['expense_account_default'], '5000')

    def test_itemless_income_account_offered(self):
        snap = dict(SNAPSHOT)
        snap['income_accounts'] = SNAPSHOT['income_accounts'] + [
            {'qbo_id': '4200', 'name': 'Shipping Income', 'type': 'Income'}]
        with patch.object(QBOSnapshotService, 'load', return_value=snap):
            rows = QBOSuggestionService.suggestions('categories')['rows']
        shipping = next(r for r in rows
                        if r['income_account']['qbo_id'] == '4200')
        self.assertEqual(shipping['member_count'], 0)
        self.assertEqual(shipping['fallback_item_options'], [])

    def test_cluster_with_existing_category_marked_imported(self):
        AccountingCategory.objects.create(
            code='SVC', name='Service', qbo_item_id='11')
        rows = QBOSuggestionService.suggestions('categories')['rows']
        svc = next(r for r in rows if r['income_account']['qbo_id'] == '4000')
        self.assertEqual(svc['state'], 'imported')


class SchemeSuggestionTest(TestCase):
    def setUp(self):
        store_snapshot()
        self.cat = AccountingCategory.objects.create(
            code='SVC', name='Service', qbo_item_id='11')

    def test_one_row_per_service_item_with_resolved_category(self):
        rows = QBOSuggestionService.suggestions('schemes')['rows']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['qbo_item_id'], '11')
        self.assertEqual(row['name'], 'CNC Cutting')
        self.assertEqual(row['rate'], '95.0')
        self.assertEqual(row['algorithm_default'], 'entered_qty')
        self.assertEqual(row['unit_default'], 'ea')
        self.assertEqual(row['category'], self.cat.pk)  # via fallback-item chain
        self.assertEqual(row['price_group'], '95.0')
        self.assertEqual(row['state'], 'new')

    def test_unresolvable_category_is_none(self):
        self.cat.qbo_item_id = ''
        self.cat.save()
        rows = QBOSuggestionService.suggestions('schemes')['rows']
        self.assertIsNone(rows[0]['category'])

    def test_imported_state_via_serviceitem_qbo_id(self):
        scheme = RateScheme.objects.create(
            name='CNC', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('95.0'), unit_label='ea',
            accounting_category=self.cat)
        ServiceItem.objects.create(
            template_name='CNC Cutting', rate_scheme=scheme, qbo_id='11')
        rows = QBOSuggestionService.suggestions('schemes')['rows']
        self.assertEqual(rows[0]['state'], 'imported')

    def test_committed_scheme_marks_row_imported_via_map(self):
        # Scheme commit persists the map; the panel must treat mapped rows
        # as imported even before the catalog commit creates ServiceItems.
        from apps.qbo.import_services import (
            QBOImportCommitService, QBOImportState)
        QBOImportCommitService.commit_schemes([
            {'name': 'Concrete', 'rate': '95.0', 'algorithm': 'entered_qty',
             'unit_label': 'ea', 'accounting_category': self.cat.pk,
             'qbo_item_id': '11', 'collapse_group': None}])
        QBOImportState.undismiss('schemes')   # simulate a re-pull
        rows = QBOSuggestionService.suggestions('schemes')['rows']
        self.assertEqual(rows[0]['state'], 'imported')

    def test_mapped_but_deleted_scheme_reverts_to_new(self):
        from apps.qbo.import_services import (
            QBOImportCommitService, QBOImportState)
        QBOImportCommitService.commit_schemes([
            {'name': 'Concrete', 'rate': '95.0', 'algorithm': 'entered_qty',
             'unit_label': 'ea', 'accounting_category': self.cat.pk,
             'qbo_item_id': '11', 'collapse_group': None}])
        RateScheme.objects.get(name='Concrete').delete()
        QBOImportState.undismiss('schemes')
        rows = QBOSuggestionService.suggestions('schemes')['rows']
        self.assertEqual(rows[0]['state'], 'new')


class CatalogSuggestionTest(TestCase):
    def setUp(self):
        store_snapshot()
        self.cat = AccountingCategory.objects.create(
            code='MAT', name='Material', qbo_item_id='12')

    def test_inventory_and_service_rows(self):
        out = QBOSuggestionService.suggestions('catalog')['rows']
        inv = [r for r in out if r['kind'] == 'inventory']
        svc = [r for r in out if r['kind'] == 'service']
        self.assertEqual(len(inv), 1)
        self.assertEqual(len(svc), 1)
        row = inv[0]
        self.assertEqual(row['qbo_id'], '12')
        self.assertEqual(row['code_suggestion'], 'Baltic Birch')
        self.assertEqual(row['selling_price'], '85.0')
        self.assertEqual(row['purchase_price'], '52.5')
        self.assertEqual(row['category'], self.cat.pk)
        self.assertEqual(row['state'], 'new')

    def test_code_suggestion_uniquified(self):
        InventoryItem.objects.create(
            code='Baltic Birch', accounting_category=self.cat)
        out = QBOSuggestionService.suggestions('catalog')['rows']
        row = next(r for r in out if r['qbo_id'] == '12')
        self.assertEqual(row['code_suggestion'], 'Baltic Birch-2')

    def test_changed_means_qbo_drifted_from_fingerprint_not_konbini(self):
        # Imported with QBO price 85 on record; QBO now says 90 → changed.
        InventoryItem.objects.create(
            code='PLY', qbo_id='12', selling_price=Decimal('80.00'),
            description='4x8', accounting_category=self.cat)
        from apps.core.models import Configuration
        import json
        Configuration.objects.update_or_create(
            key='qbo_import_catalog_fingerprints',
            defaults={'value': json.dumps({'12': {
                'name': 'Baltic Birch', 'description': '4x8',
                'unit_price': '85.0', 'purchase_cost': '52.5'}})})
        out = QBOSuggestionService.suggestions('catalog')['rows']
        row = next(r for r in out if r['qbo_id'] == '12')
        self.assertEqual(row['state'], 'imported')   # QBO matches fingerprint
        snap = dict(SNAPSHOT)
        snap['items'] = [dict(i, unit_price='90.0') if i['qbo_id'] == '12'
                         else i for i in SNAPSHOT['items']]
        with patch.object(QBOSnapshotService, 'load', return_value=snap):
            out = QBOSuggestionService.suggestions('catalog')['rows']
        row = next(r for r in out if r['qbo_id'] == '12')
        self.assertEqual(row['state'], 'changed')

    def test_divergent_scheme_rate_is_not_changed(self):
        # The user deliberately bound the item to a scheme with a different
        # rate at import; konbini divergence is NOT QBO drift.
        scheme = RateScheme.objects.create(
            name='Shop rate', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('80.00'), unit_label='ea',
            accounting_category=self.cat)
        from apps.qbo.import_services import QBOImportCommitService
        QBOImportCommitService.commit_catalog([
            {'kind': 'service', 'action': 'create', 'qbo_id': '11',
             'name': 'CNC Cutting', 'description': '',
             'rate_scheme': scheme.pk}])
        out = QBOSuggestionService.suggestions('catalog')['rows']
        row = next(r for r in out if r['qbo_id'] == '11')
        self.assertEqual(row['state'], 'imported')

    def test_empty_qbo_description_does_not_flag_changed(self):
        # Commit stores the description fallback (name); the diff must not
        # read that as drift against QBO's empty description.
        snap = dict(SNAPSHOT)
        snap['items'] = [dict(i, description='') if i['qbo_id'] == '12'
                         else i for i in SNAPSHOT['items']]
        from apps.qbo.import_services import QBOImportCommitService
        with patch.object(QBOSnapshotService, 'load', return_value=snap):
            QBOImportCommitService.commit_catalog([
                {'kind': 'inventory', 'action': 'create', 'qbo_id': '12',
                 'code': 'Baltic Birch', 'description': 'Baltic Birch',
                 'selling_price': '85.0', 'purchase_price': '52.5',
                 'units': 'none', 'accounting_category': self.cat.pk}])
            out = QBOSuggestionService.suggestions('catalog')['rows']
        row = next(r for r in out if r['qbo_id'] == '12')
        self.assertEqual(row['state'], 'imported')

    def test_legacy_import_without_fingerprint_reads_imported(self):
        # Pre-fingerprint imports (no stored baseline) must not churn as
        # 'changed' against live konbini values.
        InventoryItem.objects.create(
            code='PLY', qbo_id='12', selling_price=Decimal('80.00'),
            description='old', accounting_category=self.cat)
        scheme = RateScheme.objects.create(
            name='CNC', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('80.00'), unit_label='ea',
            accounting_category=self.cat)
        ServiceItem.objects.create(
            template_name='CNC Cutting', rate_scheme=scheme, qbo_id='11')
        out = QBOSuggestionService.suggestions('catalog')['rows']
        self.assertTrue(all(r['state'] == 'imported' for r in out))


class ContactsSuggestionTest(TestCase):
    def setUp(self):
        store_snapshot()

    def test_sublists_and_states(self):
        out = QBOSuggestionService.suggestions('contacts')['rows']
        kinds = {r['kind'] for r in out}
        self.assertEqual(kinds, {'customer', 'vendor', 'term'})
        self.assertTrue(all(r['state'] == 'new' for r in out))

    def test_imported_and_changed_customers(self):
        contact = Contact.objects.create(
            first_name='Jo', last_name='Acme', email='old@acme.com',
            mobile_number='555')
        Business.objects.create(
            business_name='Acme Corp', default_contact=contact,
            qbo_customer_id='71')
        out = QBOSuggestionService.suggestions('contacts')['rows']
        cust = next(r for r in out if r['kind'] == 'customer')
        self.assertEqual(cust['state'], 'changed')  # email drifted

    def test_merge_hint_for_same_named_customer_vendor(self):
        snap = dict(SNAPSHOT)
        snap['vendors'] = [{'qbo_id': '82', 'display_name': 'Acme Corp',
                            'company_name': 'Acme Corp', 'email': '',
                            'phone': ''}]
        with patch.object(QBOSnapshotService, 'load', return_value=snap):
            out = QBOSuggestionService.suggestions('contacts')['rows']
        vend = next(r for r in out if r['kind'] == 'vendor')
        self.assertTrue(vend['merge_hint'])


class SuggestionsEndpointTest(TestCase):
    def test_endpoint_shape_and_permission(self):
        from django.contrib.auth.models import Permission
        from rest_framework.test import APIClient
        from apps.core.models import User
        store_snapshot()
        client = APIClient()
        user = User.objects.create_user(username='cfg2', password='x')
        client.force_authenticate(user=user)
        resp = client.get('/api/qbo/import/suggestions/categories/')
        self.assertEqual(resp.status_code, 403)
        user.user_permissions.add(
            Permission.objects.get(codename='can_manage_config'))
        user = User.objects.get(pk=user.pk)  # refresh perm cache
        client.force_authenticate(user=user)
        resp = client.get('/api/qbo/import/suggestions/categories/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('rows', resp.data)
