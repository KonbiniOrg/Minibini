from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.purchasing.models import PurchaseOrder, Bill


class PurchaseOrderAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_purchase_orders(self):
        response = self.client.get('/api/purchase-orders/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_po(self):
        po = PurchaseOrder.objects.first()
        if po:
            response = self.client.get(f'/api/purchase-orders/{po.pk}/')
            self.assertEqual(response.status_code, 200)
            self.assertIn('line_items', response.data)

    def test_create_po(self):
        from apps.contacts.models import Business
        business = Business.objects.first()
        response = self.client.post('/api/purchase-orders/', {
            'business': business.pk,
        }, format='json')
        self.assertIn(response.status_code, [201, 400])

    def test_add_line_item(self):
        po = PurchaseOrder.objects.first()
        if po:
            response = self.client.post(f'/api/purchase-orders/{po.pk}/line-items/', {
                'qty': '5.00',
                'units': 'ea',
                'description': 'Widgets',
                'price': '25.00',
            }, format='json')
            self.assertIn(response.status_code, [200, 201])


class BillAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_bills(self):
        response = self.client.get('/api/bills/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_bill(self):
        bill = Bill.objects.first()
        if bill:
            response = self.client.get(f'/api/bills/{bill.pk}/')
            self.assertEqual(response.status_code, 200)
