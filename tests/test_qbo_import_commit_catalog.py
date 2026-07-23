"""commit_catalog: inventory field-overwrites; service price updates go
through RateScheme supersession and repoint the ServiceItem."""
from decimal import Decimal

from django.test import TestCase

from apps.core.models import AccountingCategory
from apps.estimates.models import ServiceItem
from apps.inventory.models import InventoryItem
from apps.jobs.models import RateScheme
from apps.qbo.import_services import QBOImportCommitService


class CommitCatalogTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(code='MAT', name='Material')
        self.scheme = RateScheme.objects.create(
            name='CNC', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('95.0'), unit_label='ea',
            accounting_category=self.cat)

    def test_creates_inventory_and_service_items(self):
        result = QBOImportCommitService.commit_catalog([
            {'kind': 'inventory', 'action': 'create', 'qbo_id': '12',
             'code': 'Baltic Birch', 'description': '4x8',
             'selling_price': '85.0', 'purchase_price': '52.5',
             'units': 'none', 'accounting_category': self.cat.pk},
            {'kind': 'service', 'action': 'create', 'qbo_id': '11',
             'name': 'CNC Cutting', 'description': 'Hourly',
             'rate_scheme': self.scheme.pk},
        ])
        self.assertEqual(result, {'created': 2, 'updated': 0})
        item = InventoryItem.objects.get(qbo_id='12')
        self.assertEqual(item.code, 'Baltic Birch')
        self.assertEqual(item.selling_price, Decimal('85.0'))
        self.assertEqual(item.purchase_price, Decimal('52.5'))
        svc = ServiceItem.objects.get(qbo_id='11')
        self.assertEqual(svc.template_name, 'CNC Cutting')
        self.assertEqual(svc.rate_scheme, self.scheme)

    def test_inventory_update_overwrites_fields(self):
        InventoryItem.objects.create(
            code='PLY', qbo_id='12', selling_price=Decimal('80.00'),
            description='old', accounting_category=self.cat)
        result = QBOImportCommitService.commit_catalog([
            {'kind': 'inventory', 'action': 'update', 'qbo_id': '12',
             'code': 'PLY', 'description': 'new desc',
             'selling_price': '85.0', 'purchase_price': '52.5',
             'units': 'none', 'accounting_category': self.cat.pk},
        ])
        self.assertEqual(result['updated'], 1)
        item = InventoryItem.objects.get(qbo_id='12')
        self.assertEqual(item.selling_price, Decimal('85.0'))
        self.assertEqual(item.description, 'new desc')

    def test_service_price_update_supersedes_scheme(self):
        svc = ServiceItem.objects.create(
            template_name='CNC Cutting', rate_scheme=self.scheme, qbo_id='11')
        QBOImportCommitService.commit_catalog([
            {'kind': 'service', 'action': 'update', 'qbo_id': '11',
             'name': 'CNC Cutting', 'description': '',
             'rate': '110.0'},
        ])
        svc.refresh_from_db()
        self.scheme.refresh_from_db()
        self.assertIsNotNone(self.scheme.replaced_by_id)   # superseded
        self.assertEqual(svc.rate_scheme_id, self.scheme.replaced_by_id)
        self.assertEqual(svc.rate_scheme.rate, Decimal('110.0'))
