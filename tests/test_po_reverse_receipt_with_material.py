from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Earmark, Material, PriceListItem
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService, PurchaseOrderReceivingService
from apps.core.models import AccountingCategory, Configuration, User, AppState


class POReverseReceiptWithMaterialTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.user = User.objects.create_user(username='u', password='p')
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=cat, is_inventoried=True,
            qty_on_hand=Decimal('0.00'),
        )
        self.po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        PurchaseOrderReceivingService.receive_items(
            self.po, [{'line_item_id': self.line.pk, 'qty_received': Decimal('5.00')}], self.user,
        )

    def test_reverse_receipt_with_pending_material_leaves_it_alone(self):
        mat = self.line.linked_material
        original_qty = mat.quantity
        original_earmark = Earmark.objects.get(price_list_item=self.pli, job=self.job).quantity
        PurchaseOrderReceivingService.reverse_receipt(self.po, self.line.pk, self.user, note='')
        mat.refresh_from_db()
        self.assertEqual(mat.quantity, original_qty)
        self.assertEqual(
            Earmark.objects.get(price_list_item=self.pli, job=self.job).quantity,
            original_earmark,
        )
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('0.00'))
        self.line.refresh_from_db()
        self.assertEqual(self.line.qty_received, Decimal('0.00'))

    def test_reverse_receipt_raises_if_material_consumed(self):
        mat = self.line.linked_material
        mat.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        mat.save(update_fields=['consumption_state'])
        with self.assertRaises(ValidationError):
            PurchaseOrderReceivingService.reverse_receipt(self.po, self.line.pk, self.user, note='')
