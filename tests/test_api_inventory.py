from decimal import Decimal
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.inventory.models import InventoryItem
from apps.core.models import AccountingCategory


class InventoryItemAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_inventory_items(self):
        response = self.client.get('/api/inventory/')
        self.assertEqual(response.status_code, 200)

    def test_create_inventory_item(self):
        response = self.client.post('/api/inventory/', {
            'code': 'API-TEST-001',
            'description': 'API test item',
            'units': 'ea',
            'purchase_price': '10.00',
            'selling_price': '20.00',
            'accounting_category': 901,
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_retrieve_inventory_item(self):
        pli = InventoryItem.objects.first()
        if pli:
            response = self.client.get(f'/api/inventory/{pli.pk}/')
            self.assertEqual(response.status_code, 200)

    def test_update_inventory_item(self):
        pli = InventoryItem.objects.first()
        if pli:
            response = self.client.patch(f'/api/inventory/{pli.pk}/', {
                'selling_price': '25.00',
            }, format='json')
            self.assertEqual(response.status_code, 200)


class InventorySearchTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        cat = AccountingCategory.objects.get(pk=901)
        self.match = InventoryItem.objects.create(
            code='BOLT-14', description='Hex bolt 1/4"',
            accounting_category=cat)
        self.other = InventoryItem.objects.create(
            code='SHEET-3', description='Aluminum sheet',
            accounting_category=cat)

    def _ids(self, resp):
        rows = resp.data['results'] if 'results' in resp.data else resp.data
        return [r['inventory_item_id'] for r in rows]

    def test_search_by_code(self):
        resp = self.client.get('/api/inventory/?search=BOLT')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.match.inventory_item_id, self._ids(resp))
        self.assertNotIn(self.other.inventory_item_id, self._ids(resp))

    def test_search_by_description(self):
        resp = self.client.get('/api/inventory/?search=Hex')
        self.assertIn(self.match.inventory_item_id, self._ids(resp))
        self.assertNotIn(self.other.inventory_item_id, self._ids(resp))

    def test_list_orders_alphabetically_by_code(self):
        """The main inventory list is browsed, not searched — alphabetical
        by code, regardless of stock level or age. (In-stock-first ranking
        was tried 2026-07-05 and reverted by RM.)"""
        cat = AccountingCategory.objects.get(pk=901)
        InventoryItem.objects.create(
            code='ZZZ-STOCKED', accounting_category=cat, units='ea',
            qty_on_hand=Decimal('5'))
        InventoryItem.objects.create(
            code='AAA-EMPTY', accounting_category=cat, units='ea')
        resp = self.client.get('/api/inventory/?page_size=100')
        codes = [r['code'] for r in resp.json()['results']]
        self.assertEqual(codes, sorted(codes))
        self.assertLess(codes.index('AAA-EMPTY'), codes.index('ZZZ-STOCKED'))


class InventoryStockOrderAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from apps.core.models import AppState, Configuration
        Configuration.objects.update_or_create(
            key='po_number_sequence',
            defaults={'value': 'PO-{year}-{counter:04d}'})
        AppState.objects.update_or_create(
            key='po_counter', defaults={'value': '0'})
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        cat = AccountingCategory.objects.get(pk=901)
        self.item = InventoryItem.objects.create(
            code='ORD-1', accounting_category=cat,
            purchase_price=Decimal('10'))

    def test_order_creates_po_and_returns_link_fields(self):
        resp = self.client.post(f'/api/inventory/{self.item.pk}/order/',
                                {'quantity': '4'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('po_id', resp.data)
        self.assertTrue(resp.data['po_number'])

    def test_order_appends_to_draft_when_po_id_given(self):
        first = self.client.post(f'/api/inventory/{self.item.pk}/order/',
                                 {'quantity': '1'}, format='json')
        po_id = first.data['po_id']
        resp = self.client.post(f'/api/inventory/{self.item.pk}/order/',
                                {'quantity': '2', 'po_id': po_id}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['po_id'], po_id)

    def test_order_requires_financials(self):
        plain = User.objects.create_user(username='noatom', password='x')
        client = APIClient()
        client.force_authenticate(user=plain)
        resp = client.post(f'/api/inventory/{self.item.pk}/order/',
                           {'quantity': '1'}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_order_rejects_missing_quantity(self):
        resp = self.client.post(f'/api/inventory/{self.item.pk}/order/',
                                {}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('quantity', resp.data)
