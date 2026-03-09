from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.inventory.models import PriceListItem


class PriceListItemAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_price_list_items(self):
        response = self.client.get('/api/price-list-items/')
        self.assertEqual(response.status_code, 200)

    def test_create_price_list_item(self):
        response = self.client.post('/api/price-list-items/', {
            'code': 'API-TEST-001',
            'description': 'API test item',
            'units': 'ea',
            'purchase_price': '10.00',
            'selling_price': '20.00',
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_retrieve_price_list_item(self):
        pli = PriceListItem.objects.first()
        if pli:
            response = self.client.get(f'/api/price-list-items/{pli.pk}/')
            self.assertEqual(response.status_code, 200)

    def test_update_price_list_item(self):
        pli = PriceListItem.objects.first()
        if pli:
            response = self.client.patch(f'/api/price-list-items/{pli.pk}/', {
                'selling_price': '25.00',
            }, format='json')
            self.assertEqual(response.status_code, 200)
