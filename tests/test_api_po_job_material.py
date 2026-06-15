from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Material, InventoryItem
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import PurchaseOrderService
from apps.core.models import AccountingCategory, Configuration, User, AppState
from django.contrib.auth.models import Permission


class APIPOJobMaterialTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.user = User.objects.create_user(username='u', password='p')
        perm = Permission.objects.get(codename='can_manage_financials')
        self.user.user_permissions.add(perm)
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        self.cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = InventoryItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.cat, is_inventoried=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.po = PurchaseOrder.objects.create(business=self.business)

    def _post_line(self, **data):
        return self.client.post(
            f'/api/purchase-orders/{self.po.pk}/line-items/',
            data=data, format='json',
        )

    def test_post_line_with_job_creates_material(self):
        r = self._post_line(
            description='x', qty='5.00', price='1.00',
            price_list_item=self.pli.pk, job=self.job.pk,
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Material.objects.filter(job=self.job, po_line_item__isnull=False).count(), 1)

    def test_patch_line_change_job_requires_sever_decision(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        other_job = Job.objects.create(job_number='J-2', contact=self.job.contact, description='o')
        r = self.client.patch(
            f'/api/purchase-orders/{self.po.pk}/line-items/{line.pk}/',
            data={'job': other_job.pk}, format='json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn('sever_decision', r.json().get('detail', ''))

    def test_patch_line_change_job_with_delete_succeeds(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        other_job = Job.objects.create(job_number='J-2', contact=self.job.contact, description='o')
        r = self.client.patch(
            f'/api/purchase-orders/{self.po.pk}/line-items/{line.pk}/',
            data={'job': other_job.pk, 'sever_decision': 'delete'}, format='json',
        )
        self.assertEqual(r.status_code, 200)
        line.refresh_from_db()
        self.assertEqual(line.linked_material.job_id, other_job.pk)

    def test_cancel_line_item_requires_sever_decision(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        r = self.client.post(
            f'/api/purchase-orders/{self.po.pk}/cancel-line-item/',
            data={'line_item_id': line.pk}, format='json',
        )
        self.assertEqual(r.status_code, 400)

    def test_cancel_po_requires_sever_decisions(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        r = self.client.post(
            f'/api/purchase-orders/{self.po.pk}/cancel/',
            data={'reason': 'oops'}, format='json',
        )
        self.assertEqual(r.status_code, 400)

    def test_delete_draft_po_requires_sever_decisions(self):
        PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        r = self.client.delete(f'/api/purchase-orders/{self.po.pk}/?confirm=true')
        self.assertEqual(r.status_code, 400)

    def test_po_list_filtered_by_job_returns_pos_for_that_job(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        other_job = Job.objects.create(job_number='J-2', contact=self.job.contact, description='o')
        r = self.client.get(f'/api/purchase-orders/?job={self.job.pk}')
        self.assertEqual(r.status_code, 200)
        ids = [po['po_id'] for po in r.json()['results']]
        self.assertIn(self.po.pk, ids)
        r2 = self.client.get(f'/api/purchase-orders/?job={other_job.pk}')
        ids2 = [po['po_id'] for po in r2.json()['results']]
        self.assertNotIn(self.po.pk, ids2)
