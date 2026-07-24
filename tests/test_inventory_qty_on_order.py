"""InventoryItem.qty_on_order — outstanding stock already on open POs.

Per item: Σ max(qty − qty_received − qty_cancelled, 0) over its PO lines on
non-cancelled POs — the same outstanding calc MaterialSerializer does for a
single PO-linked material, aggregated across all POs. Surfaced on the
inventory list so "order more or wait?" is answerable from the list.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.inventory.models import InventoryItem
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem


class QtyOnOrderTest(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(key='po_number_sequence', defaults={'value': 'PO-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='qoo', code='QOO')
        contact = Contact.objects.create(first_name='V', last_name='C')
        self.vendor = Business.objects.create(
            business_name='Vendor Co', default_contact=contact)
        self.item = InventoryItem.objects.create(
            code='QOO-I', accounting_category=self.cat,
            qty_on_hand=Decimal('1.00'),
        )

    def _po(self, status=PurchaseOrder.STATUS_ISSUED, number='PO-1'):
        return PurchaseOrder.objects.create(
            business=self.vendor, status=status, po_number=number,
        )

    def _line(self, po, qty, received='0.00', cancelled='0.00'):
        return PurchaseOrderLineItem.objects.create(
            purchase_order=po, inventory_item=self.item,
            description='stock', qty=Decimal(qty),
            price=Decimal('10.00'),
            qty_received=Decimal(received), qty_cancelled=Decimal(cancelled),
            accounting_category=self.cat,
        )

    def test_sums_outstanding_across_open_pos(self):
        self._line(self._po(number='PO-A'), '5.00', received='2.00')      # 3 outstanding
        self._line(self._po(number='PO-B'), '4.00', cancelled='1.00')     # 3 outstanding
        self.assertEqual(self.item.qty_on_order, Decimal('6.00'))

    def test_cancelled_po_excluded(self):
        self._line(self._po(status=PurchaseOrder.STATUS_CANCELLED,
                            number='PO-C'), '9.00')
        self.assertEqual(self.item.qty_on_order, Decimal('0.00'))

    def test_over_received_line_floors_at_zero(self):
        # One over-received line must not eat another line's outstanding qty.
        self._line(self._po(number='PO-D'), '2.00', received='5.00')      # floor 0
        self._line(self._po(number='PO-E'), '3.00')                       # 3
        self.assertEqual(self.item.qty_on_order, Decimal('3.00'))

    def test_no_po_lines_is_zero(self):
        self.assertEqual(self.item.qty_on_order, Decimal('0.00'))

    def test_list_endpoint_exposes_qty_on_order(self):
        self._line(self._po(number='PO-F'), '5.00', received='2.00')
        client = APIClient()
        client.force_authenticate(
            user=User.objects.create_user(username='qoo_viewer', password='x'))
        resp = client.get('/api/inventory/')
        self.assertEqual(resp.status_code, 200)
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        mine = next(r for r in rows
                    if r['inventory_item_id'] == self.item.inventory_item_id)
        self.assertEqual(Decimal(mine['qty_on_order']), Decimal('3.00'))
