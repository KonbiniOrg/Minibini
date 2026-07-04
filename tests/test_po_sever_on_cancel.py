from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Earmark, Material, InventoryItem
from apps.inventory.services import MaterialService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService, PurchaseOrderReceivingService
from apps.core.models import AccountingCategory, Configuration, User, AppState


class POSeverOnCancelTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.user = User.objects.create_user(username='u', password='p')
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        self.cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = InventoryItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.cat, is_catalog=True,
        )
        self.po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), inventory_item=self.pli.pk, job=self.job.pk,
        )

    def test_cancel_line_item_with_linked_pending_requires_sever_decision(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        with self.assertRaises(ValidationError):
            PurchaseOrderReceivingService.cancel_line_item(
                self.po, self.line.pk, note='',
            )

    def test_cancel_line_item_delete_deletes_material(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        mat_id = self.line.linked_material.pk
        PurchaseOrderReceivingService.cancel_line_item(
            self.po, self.line.pk, note='', sever_decision='delete',
        )
        self.assertFalse(Material.objects.filter(pk=mat_id).exists())

    def test_cancel_line_item_keep_preserves_material_unlinked(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        mat_id = self.line.linked_material.pk
        PurchaseOrderReceivingService.cancel_line_item(
            self.po, self.line.pk, note='', sever_decision='keep',
        )
        mat = Material.objects.get(pk=mat_id)
        self.assertIsNone(mat.po_line_item_id)

    def test_cancel_po_requires_decisions_for_linked_lines(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        with self.assertRaises(ValidationError):
            PurchaseOrderService.cancel_po(self.po.pk)

    def test_cancel_po_with_decisions_applies_them(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        mat_id = self.line.linked_material.pk
        PurchaseOrderService.cancel_po(
            self.po.pk, sever_decisions={self.line.pk: 'delete'},
        )
        self.assertFalse(Material.objects.filter(pk=mat_id).exists())
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.STATUS_CANCELLED)

    def test_delete_po_requires_decisions_for_linked_lines(self):
        with self.assertRaises(ValidationError):
            PurchaseOrderService.delete_po(self.po.pk)

    def test_delete_po_with_decisions_deletes_materials(self):
        mat_id = self.line.linked_material.pk
        PurchaseOrderService.delete_po(
            self.po.pk, sever_decisions={self.line.pk: 'delete'},
        )
        self.assertFalse(Material.objects.filter(pk=mat_id).exists())
        self.assertFalse(PurchaseOrder.objects.filter(pk=self.po.pk).exists())
