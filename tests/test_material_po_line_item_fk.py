from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Material, PriceListItem
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.core.models import AccountingCategory, Configuration


class MaterialPOLineItemFKTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.contact = Contact.objects.create(first_name='V', last_name='Vendor', work_number='555')
        self.business = Business.objects.create(business_name='Vendor Inc', default_contact=self.contact)
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(job_number='J-1', contact=self.contact, description='j')
        self.category = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='BOLT', description='bolt', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.category,
        )

    def test_material_has_nullable_po_line_item_fk(self):
        mat = Material.objects.create(job=self.job, quantity=Decimal('5.00'),
                                      accounting_category=self.category)
        self.assertIsNone(mat.po_line_item)

    def test_material_can_link_to_po_line(self):
        po = PurchaseOrder.objects.create(business=self.business)
        line = PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='x', qty=Decimal('5.00'), price=Decimal('1.00'),
        )
        mat = Material.objects.create(
            job=self.job, quantity=Decimal('5.00'), po_line_item=line,
            accounting_category=self.category,
        )
        mat.refresh_from_db()
        self.assertEqual(mat.po_line_item_id, line.pk)

    def test_po_line_item_linked_material_property_returns_material(self):
        po = PurchaseOrder.objects.create(business=self.business)
        line = PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='x', qty=Decimal('5.00'), price=Decimal('1.00'),
        )
        mat = Material.objects.create(
            job=self.job, quantity=Decimal('5.00'), po_line_item=line,
            accounting_category=self.category,
        )
        self.assertEqual(line.linked_material, mat)

    def test_po_line_item_linked_material_property_returns_none_when_absent(self):
        po = PurchaseOrder.objects.create(business=self.business)
        line = PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='x', qty=Decimal('5.00'), price=Decimal('1.00'),
        )
        self.assertIsNone(line.linked_material)
