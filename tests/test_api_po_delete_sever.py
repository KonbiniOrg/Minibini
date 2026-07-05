from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Material, InventoryItem
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService
from apps.core.models import AccountingCategory, Configuration, User, AppState
from django.contrib.auth.models import Permission


class APIPODeleteSeverTest(TestCase):
    """Deleting a draft PO whose line is linked to a pending Material, with a
    per-line sever decision sent through the API (JSON → string keys)."""

    def setUp(self):
        Configuration.objects.get_or_create(
            key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.user = User.objects.create_user(username='u', password='p')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials'))
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business
        c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        self.cat = AccountingCategory.objects.get_or_create(
            code='MAT', defaults={'name': 'Material'})[0]
        self.pli = InventoryItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.cat)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), inventory_item=self.pli.pk, job=self.job.pk)

    def test_delete_with_keep_keeps_material(self):
        # The dialog emits {line_item_id: decision}; JSON makes the key a STRING.
        resp = self.client.delete(
            f'/api/purchase-orders/{self.po.pk}/?confirm=true',
            data={'sever_decisions': {str(self.line.pk): 'keep'}}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(PurchaseOrder.objects.filter(pk=self.po.pk).exists())
        # 'keep' means the Material stays on the job, unlinked from the PO line.
        mat = Material.objects.filter(job=self.job).first()
        self.assertIsNotNone(mat)
        self.assertIsNone(mat.po_line_item_id)

    def test_delete_with_delete_removes_material(self):
        resp = self.client.delete(
            f'/api/purchase-orders/{self.po.pk}/?confirm=true',
            data={'sever_decisions': {str(self.line.pk): 'delete'}}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(Material.objects.filter(job=self.job).exists())
