from decimal import Decimal
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, HistoryEntry
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.contacts.models import Business, Contact
from apps.inventory.models import PriceListItem, InventoryAdjustment


class POReceivingTestBase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def _make_issued_po(self, num_items=2, with_pli=False):
        business = Business.objects.first()
        po = PurchaseOrder.objects.create(
            business=business,
            po_number='PO-TEST-RECV',
            status=PurchaseOrder.STATUS_ISSUED,
        )
        pli = None
        if with_pli:
            pli = PriceListItem.objects.create(
                code='TEST-PLI-RECV',
                description='Test PLI',
                purchase_price=Decimal('10.00'),
                qty_on_hand=Decimal('0.00'),
                is_inventoried=True,
            )
        for i in range(num_items):
            PurchaseOrderLineItem.objects.create(
                purchase_order=po,
                description=f'Item {i + 1}',
                qty=Decimal('10.00'),
                price=Decimal('25.00'),
                price_list_item=pli if (with_pli and i == 0) else None,
            )
        return po


class ReceiveAllTest(POReceivingTestBase):

    def test_receive_all_marks_fully_received(self):
        po = self._make_issued_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive-all/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_RECEIVED_IN_FULL)

    def test_receive_all_sets_qty_on_all_lines(self):
        po = self._make_issued_po()
        self.client.post(f'/api/purchase-orders/{po.po_id}/receive-all/')
        for li in PurchaseOrderLineItem.objects.filter(purchase_order=po):
            self.assertEqual(li.qty_received, li.qty)
            self.assertIsNotNone(li.received_date)
            self.assertEqual(li.received_by, self.user)

    def test_receive_all_creates_history(self):
        po = self._make_issued_po()
        self.client.post(f'/api/purchase-orders/{po.po_id}/receive-all/')
        entry = HistoryEntry.objects.filter(
            object_type='purchaseorder', object_id=po.pk,
            entry_type='action',
        ).first()
        self.assertIsNotNone(entry)
        self.assertIn('received', entry.changes.get('_action', '').lower())

    def test_receive_all_rejected_on_draft(self):
        business = Business.objects.first()
        po = PurchaseOrder.objects.create(
            business=business,
            po_number='PO-TEST-DRAFT-RECV',
            status=PurchaseOrder.STATUS_DRAFT,
        )
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='Item', qty=10, price=25,
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive-all/'
        )
        self.assertEqual(response.status_code, 400)

    def test_receive_all_any_user_can_receive(self):
        po = self._make_issued_po()
        worker = User.objects.get(username='johnq')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive-all/'
        )
        self.assertEqual(response.status_code, 200)


class ReceiveItemsTest(POReceivingTestBase):

    def test_receive_partial_sets_partly_received(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li.pk, 'qty_received': 5}]},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_PARTLY_RECEIVED)
        li.refresh_from_db()
        self.assertEqual(li.qty_received, Decimal('5.00'))

    def test_receive_with_note(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li.pk, 'qty_received': 3, 'note': 'Box damaged'}]},
            format='json',
        )
        li.refresh_from_db()
        self.assertEqual(li.receipt_note, 'Box damaged')
        entry = HistoryEntry.objects.filter(
            object_type='purchaseorder', object_id=po.pk,
            entry_type='action',
        ).first()
        self.assertIn('Box damaged', entry.text)

    def test_receive_all_items_fully_transitions_to_received(self):
        po = self._make_issued_po(num_items=2)
        items = [
            {'line_item_id': li.pk, 'qty_received': float(li.qty)}
            for li in PurchaseOrderLineItem.objects.filter(purchase_order=po)
        ]
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': items},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_RECEIVED_IN_FULL)

    def test_receive_cancelled_line_rejected(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        li.cancelled = True
        li.save()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li.pk, 'qty_received': 5}]},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_receive_requires_items(self):
        po = self._make_issued_po()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {},
            format='json',
        )
        self.assertEqual(response.status_code, 400)


class InventoryIntegrationTest(POReceivingTestBase):

    def test_receive_updates_qty_on_hand(self):
        po = self._make_issued_po(with_pli=True)
        pli = PriceListItem.objects.get(code='TEST-PLI-RECV')
        self.assertEqual(pli.qty_on_hand, Decimal('0.00'))

        li = PurchaseOrderLineItem.objects.filter(
            purchase_order=po, price_list_item=pli,
        ).first()
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li.pk, 'qty_received': 7}]},
            format='json',
        )
        pli.refresh_from_db()
        self.assertEqual(pli.qty_on_hand, Decimal('7.00'))

    def test_receive_creates_inventory_adjustment(self):
        po = self._make_issued_po(with_pli=True)
        pli = PriceListItem.objects.get(code='TEST-PLI-RECV')
        li = PurchaseOrderLineItem.objects.filter(
            purchase_order=po, price_list_item=pli,
        ).first()
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li.pk, 'qty_received': 7}]},
            format='json',
        )
        adj = InventoryAdjustment.objects.filter(price_list_item=pli).first()
        self.assertIsNotNone(adj)
        self.assertEqual(adj.quantity_change, Decimal('7.00'))
        self.assertIn(po.po_number, adj.reason)

    def test_non_pli_line_does_not_create_adjustment(self):
        po = self._make_issued_po(with_pli=True)
        li_no_pli = PurchaseOrderLineItem.objects.filter(
            purchase_order=po, price_list_item__isnull=True,
        ).first()
        adj_count_before = InventoryAdjustment.objects.count()
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li_no_pli.pk, 'qty_received': 5}]},
            format='json',
        )
        self.assertEqual(InventoryAdjustment.objects.count(), adj_count_before)


class CancelLineItemTest(POReceivingTestBase):

    def test_cancel_line_item(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': li.pk, 'note': 'Vendor out of stock'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        li.refresh_from_db()
        self.assertTrue(li.cancelled)

    def test_cancel_line_creates_history(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': li.pk, 'note': 'Vendor out of stock'},
            format='json',
        )
        entry = HistoryEntry.objects.filter(
            object_type='purchaseorder', object_id=po.pk,
            entry_type='action',
        ).first()
        self.assertIsNotNone(entry)
        self.assertIn('cancelled', entry.changes.get('_action', '').lower())
        self.assertEqual(entry.text, 'Vendor out of stock')

    def test_cancel_all_unreceived_lines_marks_received_if_others_done(self):
        """If the only unreceived line is cancelled, PO becomes received_in_full."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        # Receive first item fully
        items[0].qty_received = items[0].qty
        items[0].save()
        # Cancel second item
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_RECEIVED_IN_FULL)

    def test_cancel_already_cancelled_rejected(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        li.cancelled = True
        li.save()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': li.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_cancel_fully_received_rejected(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        li.qty_received = li.qty
        li.save()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': li.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)


class SerializerReceivingFieldsTest(POReceivingTestBase):

    def test_line_items_include_receiving_fields(self):
        po = self._make_issued_po()
        response = self.client.get(f'/api/purchase-orders/{po.po_id}/')
        li = response.data['line_items'][0]
        self.assertIn('qty_received', li)
        self.assertIn('received_date', li)
        self.assertIn('cancelled', li)
        self.assertIn('receipt_note', li)
        self.assertIn('received_by_name', li)
