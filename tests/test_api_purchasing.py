from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, HistoryEntry
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

    def test_cancel_po_creates_history(self):
        po = PurchaseOrder.objects.filter(status='issued').first()
        if po:
            self.client.post(f'/api/purchase-orders/{po.pk}/cancel/', {
                'reason': 'No longer needed',
            }, format='json')
            entry = HistoryEntry.objects.filter(
                entry_type='audit', object_type='purchaseorder', object_id=po.pk,
            ).first()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.text, 'No longer needed')
            self.assertEqual(entry.user, self.user)


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

    def test_cancel_bill_creates_history(self):
        bill = Bill.objects.filter(status='received').first()
        if bill:
            self.client.post(f'/api/bills/{bill.pk}/cancel/', {
                'reason': 'Duplicate entry',
            }, format='json')
            entry = HistoryEntry.objects.filter(
                entry_type='audit', object_type='bill', object_id=bill.pk,
            ).first()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.text, 'Duplicate entry')
            self.assertEqual(entry.user, self.user)
