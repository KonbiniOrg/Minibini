from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import InventoryItem
from apps.purchasing.services import PurchaseOrderService
from apps.purchasing.models import PurchaseOrder
from apps.core.models import AccountingCategory, Configuration, User, AppState


class JobMaterialSerializerPOFieldsTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.user = User.objects.create_user(username='u', password='p')
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
        self.line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), inventory_item=self.pli.pk, job=self.job.pk,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_material_payload_exposes_po_fields(self):
        r = self.client.get(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(r.status_code, 200)
        mats = r.json()['materials']
        linked = [m for m in mats if m.get('po_line_item_id')]
        self.assertEqual(len(linked), 1)
        mat = linked[0]
        self.assertEqual(mat['po_line_item_id'], self.line.pk)
        self.assertEqual(mat['po_id'], self.po.pk)
        self.assertEqual(mat['po_number'], self.po.po_number)
        self.assertEqual(mat['po_status'], self.po.status)


class MaterialQtyOnHandTest(TestCase):
    """qty_on_hand for an inventoried, non-PO material reports the PLI's real QOH
    — not the material's required quantity (which hid physical shortfalls)."""

    def setUp(self):
        from apps.inventory.models import Material
        cat = AccountingCategory.objects.get_or_create(
            code='MAT2', defaults={'name': 'Material'})[0]
        contact = Contact.objects.create(first_name='C', last_name='C', work_number='9')
        self.job = Job.objects.create(job_number='J-QOH', contact=contact, description='j')
        self.pli = InventoryItem.objects.create(
            code='INV', description='inv', accounting_category=cat,
            is_catalog=True, qty_on_hand=Decimal('5.00'))
        self.mat = Material.objects.create(
            job=self.job, accounting_category=cat, description='widget',
            quantity=Decimal('8.00'), inventory_item=self.pli)

    def test_qty_on_hand_is_pli_qoh_not_material_quantity(self):
        from apps.api.inventory.serializers import MaterialSerializer
        data = MaterialSerializer(self.mat).data
        self.assertEqual(data['qty_on_hand'], '5.00')   # PLI QOH, not 8
        self.assertEqual(str(self.mat.quantity), '8.00')  # required still 8

    def test_tasks_serializer_also_exposes_qty_on_hand(self):
        """The per-task MaterialSerializer (which feeds the task-list TaskTree)
        must report the same QOH so the 'Actual' column shows real stock."""
        from apps.api.tasks.serializers import MaterialSerializer as TasksMaterialSerializer
        data = TasksMaterialSerializer(self.mat).data
        self.assertEqual(data['qty_on_hand'], '5.00')

    def test_tasks_serializer_qty_on_hand_zero_for_freeform(self):
        """A freeform (no inventory item) material has no stock concept -> 0."""
        from apps.inventory.models import Material
        from apps.api.tasks.serializers import MaterialSerializer as TasksMaterialSerializer
        freeform = Material.objects.create(
            job=self.job, accounting_category=self.pli.accounting_category,
            description='freeform', quantity=Decimal('2.00'),
        )
        data = TasksMaterialSerializer(freeform).data
        self.assertEqual(data['qty_on_hand'], '0')
