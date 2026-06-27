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
            code='BOLT-14', description='Hex bolt 1/4"', is_catalog=True,
            accounting_category=cat)
        self.other = InventoryItem.objects.create(
            code='SHEET-3', description='Aluminum sheet', is_catalog=True,
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


class InventoryIsCatalogFilterTest(BaseTestCase):
    """GET /api/inventory/?is_catalog=true|false filters by is_catalog flag."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        cat = AccountingCategory.objects.get(pk=901)
        self.catalog_item = InventoryItem.objects.create(
            code='CAT-001', description='Catalog widget', is_catalog=True,
            accounting_category=cat)
        self.lot_item = InventoryItem.objects.create(
            code='LOT-001', description='Transient lot', is_catalog=False,
            qty_on_hand='5.00',
            accounting_category=cat)

    def _ids(self, resp):
        rows = resp.data['results'] if 'results' in resp.data else resp.data
        return [r['inventory_item_id'] for r in rows]

    def test_is_catalog_true_returns_only_catalog(self):
        resp = self.client.get('/api/inventory/?is_catalog=true&include_finished=true')
        self.assertEqual(resp.status_code, 200)
        ids = self._ids(resp)
        self.assertIn(self.catalog_item.inventory_item_id, ids)
        self.assertNotIn(self.lot_item.inventory_item_id, ids)

    def test_is_catalog_false_returns_only_non_catalog(self):
        resp = self.client.get('/api/inventory/?is_catalog=false&include_finished=true')
        self.assertEqual(resp.status_code, 200)
        ids = self._ids(resp)
        self.assertNotIn(self.catalog_item.inventory_item_id, ids)
        self.assertIn(self.lot_item.inventory_item_id, ids)
