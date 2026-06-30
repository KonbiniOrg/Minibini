from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Earmark, Material, InventoryItem
from apps.inventory.services import MaterialService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService
from apps.core.models import AccountingCategory, Configuration, AppState


class POAddLineItemWithJobTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j',
                                      status=Job.STATUS_APPROVED)
        self.cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = InventoryItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.cat, is_catalog=True,
        )
        self.po = PurchaseOrder.objects.create(business=self.business)

    def test_add_line_item_with_job_creates_and_links_material(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk,
            description='x',
            qty=Decimal('5.00'),
            price=Decimal('1.00'),
            inventory_item=self.pli.pk,
            job=self.job.pk,
        )
        mat = line.linked_material
        self.assertIsNotNone(mat)
        self.assertEqual(mat.job_id, self.job.pk)
        self.assertEqual(mat.quantity, Decimal('5.00'))
        self.assertEqual(mat.inventory_item_id, self.pli.pk)
        earmark = Earmark.objects.filter(inventory_item=self.pli, job=self.job).first()
        self.assertEqual(earmark.quantity, Decimal('5.00'))

    def test_add_line_item_with_material_id_links_explicitly(self):
        existing = MaterialService.create_on_job(
            job=self.job, inventory_item=self.pli, quantity=Decimal('3.00'),
        )
        line = PurchaseOrderService.add_line_item(
            self.po.pk,
            description='x',
            qty=Decimal('5.00'),
            price=Decimal('1.00'),
            inventory_item=self.pli.pk,
            material_id=existing.pk,
        )
        self.assertEqual(line.linked_material.pk, existing.pk)

    def test_add_line_item_without_job_creates_no_material(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk,
            description='x',
            qty=Decimal('5.00'),
            price=Decimal('1.00'),
            inventory_item=self.pli.pk,
        )
        self.assertIsNone(line.linked_material)
        self.assertFalse(Material.objects.filter(po_line_item=line).exists())

    def test_add_line_item_pli_less_with_job_creates_pli_less_material(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk,
            description='Custom service',
            qty=Decimal('1.00'),
            price=Decimal('500.00'),
            accounting_category=self.cat.pk,
            job=self.job.pk,
        )
        mat = line.linked_material
        self.assertIsNotNone(mat)
        self.assertIsNone(mat.inventory_item_id)
        self.assertEqual(mat.description, 'Custom service')
        self.assertEqual(mat.quantity, Decimal('1.00'))
        self.assertEqual(mat.unit_cost, Decimal('500.00'))

    def test_add_line_item_with_invalid_job_raises(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.add_line_item(
                self.po.pk,
                description='x',
                qty=Decimal('5.00'),
                price=Decimal('1.00'),
                inventory_item=self.pli.pk,
                job=999999,  # nonexistent
            )
        self.assertIn('Job 999999 not found', str(ctx.exception))

    def test_add_line_item_with_invalid_material_id_raises(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.add_line_item(
                self.po.pk,
                description='x',
                qty=Decimal('5.00'),
                price=Decimal('1.00'),
                inventory_item=self.pli.pk,
                material_id=999999,  # nonexistent
            )
        self.assertIn('Material 999999 not found', str(ctx.exception))
