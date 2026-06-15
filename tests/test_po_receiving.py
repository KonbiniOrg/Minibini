from decimal import Decimal
from apps.core.models import PurchasingHistory
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import AccountingCategory, User
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.contacts.models import Business, Contact
from apps.inventory.models import InventoryItem, InventoryAdjustment


class POReceivingTestBase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]

    def _make_issued_po(self, num_items=2, with_pli=False):
        business = Business.objects.first()
        po = PurchaseOrder.objects.create(
            business=business,
            po_number='PO-TEST-RECV',
            status=PurchaseOrder.STATUS_ISSUED,
        )
        pli = None
        if with_pli:
            pli = InventoryItem.objects.create(
                code='TEST-PLI-RECV',
                description='Test PLI',
                purchase_price=Decimal('10.00'),
                qty_on_hand=Decimal('0.00'),
                is_inventoried=True,
                accounting_category=self.category,
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
        entry = PurchasingHistory.objects.filter(
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
        entry = PurchasingHistory.objects.filter(
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

    def test_receive_overage_accepted(self):
        """Overage receipts are accepted — receiving against a line where
        qty_received + qty_cancelled already meets/exceeds qty just records
        the additional received quantity."""
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        li.qty_cancelled = li.qty
        li.save()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li.pk, 'qty_received': 5}]},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        li.refresh_from_db()
        self.assertEqual(li.qty_received, Decimal('5'))

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
        pli = InventoryItem.objects.get(code='TEST-PLI-RECV')
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
        pli = InventoryItem.objects.get(code='TEST-PLI-RECV')
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

    def test_cancel_unreceived_line_item(self):
        """Cancel a line with 0 received — qty_cancelled should equal qty."""
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': li.pk, 'note': 'Vendor out of stock'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        li.refresh_from_db()
        self.assertEqual(li.qty_cancelled, li.qty)

    def test_cancel_partially_received_line_item(self):
        """Cancel remaining on a partially received line."""
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        li.qty_received = Decimal('3.00')
        li.save()
        po.status = PurchaseOrder.STATUS_PARTLY_RECEIVED
        po.save()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': li.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        li.refresh_from_db()
        self.assertEqual(li.qty_cancelled, Decimal('7.00'))
        self.assertEqual(li.qty_received + li.qty_cancelled, li.qty)

    def test_cancel_line_creates_history(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': li.pk, 'note': 'Vendor out of stock'},
            format='json',
        )
        entry = PurchasingHistory.objects.filter(
            object_type='purchaseorder', object_id=po.pk,
            entry_type='action',
        ).first()
        self.assertIsNotNone(entry)
        self.assertIn('cancelled', entry.changes.get('_action', '').lower())
        self.assertEqual(entry.text, 'Vendor out of stock')

    def test_cancel_already_done_line_rejected(self):
        """Cannot cancel a line where qty_received + qty_cancelled == qty."""
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        li.qty_cancelled = li.qty
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

    def test_cancel_all_unreceived_lines_marks_received_if_others_done(self):
        """If the only outstanding line is cancelled, PO becomes received_in_full."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        items[0].qty_received = items[0].qty
        items[0].save()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_RECEIVED_IN_FULL)

    def test_cancel_all_lines_no_receipts_cancels_po(self):
        """If all lines are fully cancelled with nothing received, PO auto-cancels via cancel_po."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[0].pk},
            format='json',
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_CANCELLED)
        for li in PurchaseOrderLineItem.objects.filter(purchase_order=po):
            self.assertEqual(li.qty_cancelled, li.qty)


class ReverseReceiptTest(POReceivingTestBase):

    def test_reverse_receipt_resets_qty(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li.pk, 'qty_received': 5}]},
            format='json',
        )
        li.refresh_from_db()
        self.assertEqual(li.qty_received, Decimal('5.00'))
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': li.pk, 'note': 'Entered in error'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        li.refresh_from_db()
        self.assertEqual(li.qty_received, Decimal('0.00'))
        self.assertIsNone(li.received_by)
        self.assertIsNone(li.received_date)
        self.assertEqual(li.receipt_note, '')

    def test_reverse_receipt_updates_inventory(self):
        po = self._make_issued_po(with_pli=True)
        pli = InventoryItem.objects.get(code='TEST-PLI-RECV')
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
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': li.pk},
            format='json',
        )
        pli.refresh_from_db()
        self.assertEqual(pli.qty_on_hand, Decimal('0.00'))
        adjustments = InventoryAdjustment.objects.filter(price_list_item=pli)
        self.assertEqual(adjustments.count(), 2)
        reversal = adjustments.order_by('-pk').first()
        self.assertEqual(reversal.quantity_change, Decimal('-7.00'))
        self.assertIn('Reversed', reversal.reason)

    def test_reverse_receipt_clears_qty_cancelled(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li.pk, 'qty_received': 5}]},
            format='json',
        )
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': li.pk},
            format='json',
        )
        li.refresh_from_db()
        self.assertEqual(li.qty_cancelled, Decimal('5.00'))
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': li.pk},
            format='json',
        )
        li.refresh_from_db()
        self.assertEqual(li.qty_received, Decimal('0.00'))
        self.assertEqual(li.qty_cancelled, Decimal('0.00'))

    def test_reverse_receipt_creates_history(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li.pk, 'qty_received': 5}]},
            format='json',
        )
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': li.pk, 'note': 'Wrong item scanned'},
            format='json',
        )
        entries = PurchasingHistory.objects.filter(
            object_type='purchaseorder', object_id=po.pk,
            entry_type='action',
        ).order_by('-pk')
        reversal_entry = entries.first()
        self.assertIn('reversed', reversal_entry.changes.get('_action', '').lower())
        self.assertEqual(reversal_entry.text, 'Wrong item scanned')

    def test_reverse_receipt_no_qty_received_rejected(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': li.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_reverse_receipt_updates_po_status(self):
        po = self._make_issued_po(num_items=1)
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li.pk, 'qty_received': 5}]},
            format='json',
        )
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_PARTLY_RECEIVED)
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': li.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_ISSUED)

    def test_reverse_on_fully_received_po(self):
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        self.client.post(f'/api/purchase-orders/{po.po_id}/receive-all/')
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_RECEIVED_IN_FULL)
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': items[0].pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_PARTLY_RECEIVED)


class POStatusAutoTransitionTest(POReceivingTestBase):
    """Comprehensive tests for PO status auto-transitions across multi-line scenarios."""

    def test_receive_one_cancel_other_gives_received_in_full(self):
        """2 items: receive one fully, cancel the other → RECEIVED_IN_FULL."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': items[0].pk, 'qty_received': float(items[0].qty)}]},
            format='json',
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_RECEIVED_IN_FULL)

    def test_receive_one_cancel_other_then_reverse_gives_issued(self):
        """2 items: receive one, cancel other → RECEIVED_IN_FULL. Reverse receipt → ISSUED."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': items[0].pk, 'qty_received': float(items[0].qty)}]},
            format='json',
        )
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': items[0].pk},
            format='json',
        )
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_ISSUED)

    def test_partial_receive_cancel_other_gives_partly_received(self):
        """2 items: receive one partially, cancel the other → PARTLY_RECEIVED."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': items[0].pk, 'qty_received': 3}]},
            format='json',
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_PARTLY_RECEIVED)

    def test_partial_receive_cancel_other_then_reverse_gives_issued(self):
        """2 items: partial receive one, cancel other → PARTLY_RECEIVED. Reverse → ISSUED."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': items[0].pk, 'qty_received': 3}]},
            format='json',
        )
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': items[0].pk},
            format='json',
        )
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_ISSUED)

    def test_cancel_both_lines_cancels_po_with_line_items_set(self):
        """2 items: cancel both → CANCELLED. All line items have qty_cancelled == qty."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[0].pk},
            format='json',
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_CANCELLED)
        for li in PurchaseOrderLineItem.objects.filter(purchase_order=po):
            self.assertEqual(li.qty_cancelled, li.qty)

    def test_receive_all_then_reverse_one_gives_partly_received(self):
        """Receive all → RECEIVED_IN_FULL. Reverse one → PARTLY_RECEIVED."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        self.client.post(f'/api/purchase-orders/{po.po_id}/receive-all/')
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': items[0].pk},
            format='json',
        )
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_PARTLY_RECEIVED)

    def test_receive_all_then_reverse_all_gives_issued(self):
        """Receive all → RECEIVED_IN_FULL. Reverse both → ISSUED."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        self.client.post(f'/api/purchase-orders/{po.po_id}/receive-all/')
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': items[0].pk},
            format='json',
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_ISSUED)


class SerializerReceivingFieldsTest(POReceivingTestBase):

    def test_line_items_include_receiving_fields(self):
        po = self._make_issued_po()
        response = self.client.get(f'/api/purchase-orders/{po.po_id}/')
        li = response.data['line_items'][0]
        self.assertIn('qty_received', li)
        self.assertIn('received_date', li)
        self.assertIn('qty_cancelled', li)
        self.assertIn('receipt_note', li)
        self.assertIn('received_by_name', li)


class POStatusTransitionTest(POReceivingTestBase):

    def test_received_in_full_to_partly_received_allowed(self):
        """PO can go back to partly_received after receipt reversal."""
        po = self._make_issued_po()
        po.status = PurchaseOrder.STATUS_PARTLY_RECEIVED
        po.save()
        po.status = PurchaseOrder.STATUS_RECEIVED_IN_FULL
        po.save()
        po.status = PurchaseOrder.STATUS_PARTLY_RECEIVED
        po.full_clean()  # Should not raise

    def test_received_in_full_to_issued_allowed(self):
        """PO can go back to issued after all receipts reversed."""
        po = self._make_issued_po()
        po.status = PurchaseOrder.STATUS_PARTLY_RECEIVED
        po.save()
        po.status = PurchaseOrder.STATUS_RECEIVED_IN_FULL
        po.save()
        po.status = PurchaseOrder.STATUS_ISSUED
        po.full_clean()  # Should not raise

    def test_partly_received_to_cancelled_not_allowed(self):
        """PO cannot go from partly_received to cancelled directly."""
        po = self._make_issued_po()
        po.status = PurchaseOrder.STATUS_PARTLY_RECEIVED
        po.save()
        po.status = PurchaseOrder.STATUS_CANCELLED
        with self.assertRaises(ValidationError):
            po.full_clean()
