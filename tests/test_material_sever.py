from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Earmark, Material, PriceListItem
from apps.inventory.services import MaterialService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.core.models import AccountingCategory, Configuration


class MaterialSeverTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=cat, is_inventoried=True,
        )
        po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='x', qty=Decimal('5.00'), price=Decimal('1.00'),
        )
        # Material created via MaterialService.create_on_job so earmark is set
        self.material = MaterialService.create_on_job(
            job=self.job, price_list_item=self.pli, quantity=Decimal('5.00'),
        )
        self.material.po_line_item = self.line
        self.material.save(update_fields=['po_line_item'])

    def test_sever_keep_clears_fk_and_preserves_material(self):
        MaterialService.sever(self.material, 'keep')
        self.material.refresh_from_db()
        self.assertIsNone(self.material.po_line_item_id)
        self.assertEqual(self.material.quantity, Decimal('5.00'))
        # Earmark preserved
        earmark = Earmark.objects.filter(price_list_item=self.pli, job=self.job).first()
        self.assertIsNotNone(earmark)
        self.assertEqual(earmark.quantity, Decimal('5.00'))

    def test_sever_delete_removes_material_and_backs_out_earmark(self):
        material_id = self.material.pk
        MaterialService.sever(self.material, 'delete')
        self.assertFalse(Material.objects.filter(pk=material_id).exists())
        self.assertFalse(Earmark.objects.filter(price_list_item=self.pli, job=self.job).exists())

    def test_sever_raises_on_consumed_material(self):
        self.material.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        self.material.save(update_fields=['consumption_state'])
        with self.assertRaises(ValidationError):
            MaterialService.sever(self.material, 'keep')

    def test_sever_raises_on_unknown_decision(self):
        with self.assertRaises(ValidationError):
            MaterialService.sever(self.material, 'something-else')
