from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import InventoryItem
from apps.purchasing.services import PurchaseOrderService
from apps.purchasing.models import PurchaseOrder
from apps.api.purchasing.serializers import POLineItemSerializer
from apps.core.models import AccountingCategory, Configuration, AppState


class POSerializerMaterialTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = InventoryItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=cat,
        )
        self.po = PurchaseOrder.objects.create(business=self.business)

    def test_linked_line_exposes_effective_job_and_material(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), inventory_item=self.pli.pk, job=self.job.pk,
        )
        data = POLineItemSerializer(line).data
        self.assertEqual(data['effective_job_id'], self.job.pk)
        self.assertEqual(data['effective_job_number'], self.job.job_number)
        self.assertIsNotNone(data['material'])
        self.assertEqual(data['material']['job_id'], self.job.pk)
        self.assertEqual(data['material']['quantity'], '5.00')

    def test_unlinked_line_has_null_material_and_null_effective_job(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), inventory_item=self.pli.pk,
        )
        data = POLineItemSerializer(line).data
        self.assertIsNone(data['effective_job_id'])
        self.assertIsNone(data['material'])

    def test_serializer_does_not_expose_job_field(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), inventory_item=self.pli.pk,
        )
        data = POLineItemSerializer(line).data
        self.assertNotIn('job', data)
