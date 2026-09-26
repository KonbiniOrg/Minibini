"""Inventory rows are shop history — never auto-collected.

Deletion doctrine (2026-07-03): write-off and consume leave the row in place;
hard deletion is reserved for the never-referenced via the delete endpoint's
guard. This retired the old collect_if_finished auto-delete."""
from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, Task, RateScheme
from apps.inventory.models import InventoryItem, Material
from apps.inventory.services import InventoryService, MaterialService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem


class CollectIfFinishedTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.contact = Contact.objects.create(first_name='A', last_name='B')
        self.job = Job.objects.create(job_number='J-COL-1', contact=self.contact)

    def _item(self, **kw):
        d = dict(accounting_category=self.cat)
        d.update(kw)
        return InventoryItem.objects.create(**d)

    def _po_line_referencing(self, item):
        biz = Business.objects.create(business_name='V', default_contact=self.contact)
        po = PurchaseOrder.objects.create(
            business=biz, po_number='PO-COL', status=PurchaseOrder.STATUS_DRAFT)
        return PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='x', qty=Decimal('1'),
            price=Decimal('1'), inventory_item=item)

    # --- write-off ---

    def test_writeoff_unreferenced_lot_keeps_row(self):
        it = self._item(code='W1', qty_on_hand=Decimal('3.00'))
        InventoryService.write_off(it)
        it.refresh_from_db()
        self.assertEqual(it.qty_on_hand, Decimal('0.00'))
        self.assertTrue(InventoryItem.objects.filter(pk=it.pk).exists())

    def test_delete_endpoint_refuses_referenced_item(self):
        from rest_framework.test import APIClient
        from django.contrib.auth.models import Permission
        from apps.core.models import User
        it = self._item(code='DEL1', qty_on_hand=Decimal('1.00'))
        Material.objects.create(
            job=self.job, description='uses it', quantity=Decimal('1.00'),
            inventory_item=it)
        user = User.objects.create_user(username='findel', password='x')
        user.user_permissions.add(Permission.objects.get(
            codename='can_manage_financials', content_type__app_label='core'))
        client = APIClient()
        client.force_authenticate(user=User.objects.get(pk=user.pk))
        resp = client.delete(f'/api/inventory/{it.pk}/')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertTrue(InventoryItem.objects.filter(pk=it.pk).exists())

    def test_delete_endpoint_allows_never_referenced_item(self):
        from rest_framework.test import APIClient
        from django.contrib.auth.models import Permission
        from apps.core.models import User
        it = self._item(code='DEL2', qty_on_hand=Decimal('0.00'))
        user = User.objects.create_user(username='findel2', password='x')
        user.user_permissions.add(Permission.objects.get(
            codename='can_manage_financials', content_type__app_label='core'))
        client = APIClient()
        client.force_authenticate(user=User.objects.get(pk=user.pk))
        resp = client.delete(f'/api/inventory/{it.pk}/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(InventoryItem.objects.filter(pk=it.pk).exists())

    def test_writeoff_referenced_lot_survives(self):
        it = self._item(code='W2', qty_on_hand=Decimal('3.00'))
        self._po_line_referencing(it)
        InventoryService.write_off(it)
        self.assertTrue(InventoryItem.objects.filter(pk=it.pk).exists())

    def test_partial_writeoff_unreferenced_lot_is_not_collected(self):
        it = self._item(code='W4', qty_on_hand=Decimal('3.00'))
        InventoryService.write_off(it, Decimal('1.00'))  # 3 -> 2, still has stock
        self.assertTrue(InventoryItem.objects.filter(pk=it.pk).exists())
        it.refresh_from_db()
        self.assertEqual(it.qty_on_hand, Decimal('2.00'))

    def test_writeoff_empties_but_survives(self):
        it = self._item(code='W3', qty_on_hand=Decimal('3.00'))
        InventoryService.write_off(it)
        it.refresh_from_db()
        self.assertEqual(it.qty_on_hand, Decimal('0.00'))  # emptied, not deleted
        self.assertTrue(InventoryItem.objects.filter(pk=it.pk).exists())

    # --- consume must NOT delete (reversibility) ---

    def test_consume_does_not_delete_so_unconsume_works(self):
        scheme = RateScheme.objects.create(
            name='S', algorithm=RateScheme.ENTERED_QTY, rate=1, unit_label='ea',
            accounting_category=self.cat)
        task = Task(job=self.job, name='t')
        task.stamp_from_scheme(scheme)
        task.save()
        it = self._item(code='C1', qty_on_hand=Decimal('5.00'))
        m = Material.objects.create(
            job=self.job, task=task, inventory_item=it,
            description='x', quantity=Decimal('5.00'))
        MaterialService.consume(m)
        # Lot is now QOH 0 + no earmark + reference-free, but must survive so
        # unconsume() can restore it.
        self.assertTrue(InventoryItem.objects.filter(pk=it.pk).exists())
        MaterialService.unconsume(m)
        it.refresh_from_db()
        self.assertEqual(it.qty_on_hand, Decimal('5.00'))
