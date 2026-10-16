"""PO order flow §6: creating a PO opens to the jobs atom (not a PM alone);
ordering a material opens to the PM of its job; every PO-level write opens
to the jobs atom and to the PM of any job linked to a line on that PO —
and that access drops as soon as the link does. reconcile stays
financials-only. `can_manage` on the PO and material serializers follows
the same rule."""
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.services import EmailService
from apps.core.models import AccountingCategory, AppState, Configuration, EmailRecord, User
from apps.inventory.models import InventoryItem
from apps.inventory.services import MaterialService
from apps.jobs.models import Job, RateScheme, Task
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import PurchaseOrderService
from tests.base import grant_atoms


class _Base(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='po_number_sequence', defaults={'value': 'PO-{year}-{counter:04d}'})
        Configuration.objects.update_or_create(
            key='default_material_markup_percent', defaults={'value': '25'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Materials', code='MATPERM')
        vc = Contact.objects.create(first_name='V', last_name='V', email='vendor6@example.com',
                                    phones=[{'number': '5', 'label': 'work'}])
        self.business = Business.objects.create(business_name='Vendor', default_contact=vc)
        vc.business = self.business
        vc.save()
        cust = Contact.objects.create(first_name='C', last_name='C', email='cust6@example.com',
                                      phones=[{'number': '1', 'label': 'work'}])
        self.pm = User.objects.create_user('pm_a', password='p')
        self.other_pm = User.objects.create_user('pm_b', password='p')
        self.fin = grant_atoms(User.objects.create_user('fin', password='p'), 'can_manage_financials')
        self.jobs = grant_atoms(User.objects.create_user('jobs', password='p'), 'can_manage_jobs')
        self.worker = User.objects.create_user('worker', password='p')
        self.job_a = Job.objects.create(job_number='J-A', contact=cust, description='a',
                                        status=Job.STATUS_APPROVED, project_manager=self.pm)
        self.job_b = Job.objects.create(job_number='J-B', contact=cust, description='b',
                                        status=Job.STATUS_APPROVED, project_manager=self.other_pm)
        self.item = InventoryItem.objects.create(
            code='PERM-1', description='x', accounting_category=self.cat,
            purchase_price=Decimal('5.00'), units='ea')
        self.material = MaterialService.create_on_job(
            job=self.job_a, inventory_item=self.item, description='x',
            quantity=Decimal('2'), unit_cost=Decimal('5.00'),
            accounting_category=self.cat, units='ea')
        self.client = APIClient()

    def _as(self, user):
        self.client.force_authenticate(user)

    def _po_body(self):
        return {'po': {'business': self.business.pk}}

    def _linked_po(self):
        """A draft PO whose one line is linked to job A's material (as fin)."""
        self._as(self.fin)
        r = self.client.post(f'/api/materials/{self.material.pk}/order/',
                             self._po_body(), format='json')
        assert r.status_code == 201, r.content
        return r.json()['po_id'], r.json()['line_item_id']


class PoCreatePermissionTests(_Base):
    def test_jobs_atom_can_create_po(self):
        self._as(self.jobs)
        r = self.client.post('/api/purchase-orders/', {'business': self.business.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_pm_alone_cannot_create_po(self):
        self._as(self.pm)
        r = self.client.post('/api/purchase-orders/', {'business': self.business.pk}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_worker_cannot_create_po(self):
        self._as(self.worker)
        r = self.client.post('/api/purchase-orders/', {'business': self.business.pk}, format='json')
        self.assertEqual(r.status_code, 403)


class OrderPermissionTests(_Base):
    def test_pm_of_the_materials_job_can_order_it(self):
        self._as(self.pm)
        r = self.client.post(f'/api/materials/{self.material.pk}/order/', self._po_body(), format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_pm_of_another_job_cannot_order_it(self):
        self._as(self.other_pm)
        r = self.client.post(f'/api/materials/{self.material.pk}/order/', self._po_body(), format='json')
        self.assertEqual(r.status_code, 403)

    def test_jobs_atom_can_order_stock_but_a_pm_cannot(self):
        body = {**self._po_body(), 'line': {'qty': '1'}}
        self._as(self.jobs)
        self.assertEqual(self.client.post(f'/api/inventory/{self.item.pk}/order/', body, format='json').status_code, 201)
        self._as(self.pm)
        self.assertEqual(self.client.post(f'/api/inventory/{self.item.pk}/order/', body, format='json').status_code, 403)

    def test_pm_cannot_append_to_an_unlinked_draft(self):
        po = PurchaseOrderService.create_po(business=self.business)
        self._as(self.pm)
        r = self.client.post(f'/api/materials/{self.material.pk}/order/',
                             {'po_id': po.pk}, format='json')
        self.assertEqual(r.status_code, 403, r.content)
        self.assertEqual(po.purchaseorderlineitem_set.count(), 0)

    def test_pm_can_append_to_a_draft_already_linked_to_their_job(self):
        po_id, _ = self._linked_po()
        second = MaterialService.create_on_job(
            job=self.job_a, inventory_item=self.item, description='y',
            quantity=Decimal('1'), unit_cost=Decimal('5.00'),
            accounting_category=self.cat, units='ea')
        self._as(self.pm)
        r = self.client.post(f'/api/materials/{second.pk}/order/',
                             {'po_id': po_id}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_jobs_atom_can_append_to_any_draft(self):
        po = PurchaseOrderService.create_po(business=self.business)
        self._as(self.jobs)
        r = self.client.post(f'/api/materials/{self.material.pk}/order/',
                             {'po_id': po.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_jobs_atom_can_create_po_from_email_and_read_sender_info(self):
        email = EmailRecord.objects.create(message_id='<perm-po@example.com>')
        self._as(self.jobs)
        r = self.client.post(f'/api/emails/{email.pk}/create-po/',
                             {'vendor_business_id': self.business.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self._as(self.fin)
        with patch.object(EmailService, 'get_email_content', return_value=None):
            r = self.client.get(f'/api/emails/{email.pk}/sender-info/')
        self.assertNotEqual(r.status_code, 403)   # 503 (no cached content) is fine here


class PoWritePermissionTests(_Base):
    def test_non_numeric_pk_denies_instead_of_500(self):
        self._as(self.pm)
        r = self.client.patch('/api/purchase-orders/abc/', {'requested_date': '2026-11-01'}, format='json')
        self.assertIn(r.status_code, (403, 404))

    def test_config_atom_cannot_create_po_or_order_stock(self):
        cfg = grant_atoms(User.objects.create_user('cfg', password='p'), 'can_manage_config')
        self._as(cfg)
        r = self.client.post('/api/purchase-orders/', {'business': self.business.pk}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.client.post(f'/api/inventory/{self.item.pk}/order/',
                             {'po': {'business': self.business.pk}, 'line': {'qty': '1'}}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_pm_linked_via_material_can_write_the_po(self):
        po_id, _ = self._linked_po()
        self._as(self.pm)
        r = self.client.patch(f'/api/purchase-orders/{po_id}/', {'requested_date': '2026-11-01'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.post(f'/api/purchase-orders/{po_id}/line-items/',
                             {'description': 'extra', 'qty': 1, 'price': '1.00'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_pm_linked_via_task_can_write_the_po(self):
        scheme = RateScheme.objects.create(
            name='Perm Scheme', algorithm=RateScheme.ELAPSED_TIME, rate=Decimal('10.00'),
            unit_label='hour', accounting_category=self.cat)
        task = Task(job=self.job_a, name='Outsourced', sort_order=0)
        task.stamp_from_scheme(scheme)
        task.save()
        po = PurchaseOrderService.create_po(business=self.business)
        PurchaseOrderService.add_line_item(po.pk, description='outsourced', qty=1,
                                           price=Decimal('10.00'), task=task.pk)
        self._as(self.pm)
        r = self.client.patch(f'/api/purchase-orders/{po.pk}/', {'requested_date': '2026-11-01'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_unlinked_pm_and_worker_are_denied(self):
        po_id, _ = self._linked_po()
        for user in (self.other_pm, self.worker):
            self._as(user)
            r = self.client.patch(f'/api/purchase-orders/{po_id}/', {'requested_date': '2026-11-01'}, format='json')
            self.assertEqual(r.status_code, 403, user.username)

    def test_access_drops_after_the_linking_line_is_deleted(self):
        po_id, li = self._linked_po()
        self._as(self.pm)
        r = self.client.delete(f'/api/purchase-orders/{po_id}/line-items/{li}/')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.patch(f'/api/purchase-orders/{po_id}/', {'requested_date': '2026-11-01'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_access_drops_after_the_line_is_unjobbed(self):
        po_id, li = self._linked_po()
        self._as(self.pm)
        r = self.client.patch(f'/api/purchase-orders/{po_id}/line-items/{li}/',
                              {'job': None, 'sever_decision': 'keep'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.patch(f'/api/purchase-orders/{po_id}/', {'requested_date': '2026-11-01'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_jobs_atom_can_issue_and_delete(self):
        po_id, _ = self._linked_po()
        self._as(self.jobs)
        self.assertEqual(self.client.post(f'/api/purchase-orders/{po_id}/issue/', {}, format='json').status_code, 200)
        po2 = PurchaseOrderService.create_po(business=self.business)
        self.assertEqual(self.client.delete(f'/api/purchase-orders/{po2.pk}/?confirm=true').status_code, 200)

    def test_reconcile_stays_financials_only(self):
        po_id, _ = self._linked_po()
        for user in (self.jobs, self.pm):
            self._as(user)
            r = self.client.post(f'/api/purchase-orders/{po_id}/reconcile/', {}, format='json')
            self.assertEqual(r.status_code, 403, user.username)
        self._as(self.fin)
        r = self.client.post(f'/api/purchase-orders/{po_id}/reconcile/', {}, format='json')
        self.assertNotEqual(r.status_code, 403)


class CanManageFlagTests(_Base):
    def test_po_can_manage_follows_the_link(self):
        po_id, li = self._linked_po()
        expected = {self.pm: True, self.other_pm: False, self.worker: False,
                    self.jobs: True, self.fin: True}
        for user, flag in expected.items():
            self._as(user)
            self.assertEqual(self.client.get(f'/api/purchase-orders/{po_id}/').json()['can_manage'],
                             flag, user.username)
        self._as(self.fin)
        self.client.delete(f'/api/purchase-orders/{po_id}/line-items/{li}/')
        self._as(self.pm)
        self.assertFalse(self.client.get(f'/api/purchase-orders/{po_id}/').json()['can_manage'])

    def test_material_can_manage_for_the_jobs_pm(self):
        self._as(self.pm)
        self.assertTrue(self.client.get(f'/api/materials/{self.material.pk}/').json()['can_manage'])
        self.assertTrue(self.client.get(f'/api/jobs/{self.job_a.pk}/').json()['materials'][0]['can_manage'])
        self._as(self.other_pm)
        self.assertFalse(self.client.get(f'/api/materials/{self.material.pk}/').json()['can_manage'])
