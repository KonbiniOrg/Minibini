"""Order-from-material: append to a chosen draft or start a vendor-less one
(spec Path 1). Service-level tests plus the API action + its permission gate."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APITestCase
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.inventory.models import Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Job
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import PurchaseOrderService
from django.contrib.auth.models import Permission


class OrderFromMaterialTests(TestCase):
    def setUp(self):
        for key, value in (('po_number_sequence', 'PO-{year}-{counter:04d}'),
                           ('default_material_markup_percent', '25')):
            Configuration.objects.create(key=key, value=value)
        AppState.objects.create(key='po_counter', value='0')
        self.cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MAT')
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='5')
        self.job = Job.objects.create(
            contact=contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001')
        self.material = MaterialService.create_on_job(
            job=self.job, description='steel', quantity=Decimal('3'),
            unit_cost=Decimal('80.00'), accounting_category=self.cat, units='ea')

    def test_order_creates_vendorless_draft_and_links(self):
        po, li = MaterialService.order(self.material)
        self.assertEqual(po.status, PurchaseOrder.STATUS_DRAFT)
        self.assertIsNone(po.business_id)
        self.assertEqual(li.inventory_item_id, self.material.inventory_item_id)
        self.assertEqual(li.qty, Decimal('3'))
        self.material.refresh_from_db()
        self.assertEqual(self.material.po_line_item_id, li.pk)

    def test_order_appends_to_given_draft(self):
        po, _ = MaterialService.order(self.material)
        m2 = MaterialService.create_on_job(
            job=self.job, description='rod', quantity=Decimal('1'),
            unit_cost=Decimal('10.00'), accounting_category=self.cat, units='ea')
        po2, li2 = MaterialService.order(m2, po=po)
        self.assertEqual(po2.pk, po.pk)
        self.assertEqual(po.purchaseorderlineitem_set.count(), 2)

    def test_order_refuses_provisional_material(self):
        prov = MaterialService.create_on_job(
            job=self.job, description='?', quantity=Decimal('1'),
            accounting_category=self.cat, units='ea')
        with self.assertRaises(ValidationError):
            MaterialService.order(prov)

    def test_order_refuses_non_pending_material(self):
        po, li = MaterialService.order(self.material)
        # Establish an unrelated pending material, consume it, then try to order.
        m2 = MaterialService.create_on_job(
            job=self.job, description='rod', quantity=Decimal('1'),
            unit_cost=Decimal('10.00'), accounting_category=self.cat, units='ea')
        m2.inventory_item.qty_on_hand = Decimal('5')
        m2.inventory_item.save(update_fields=['qty_on_hand'])
        MaterialService.consume(m2)
        with self.assertRaises(ValidationError):
            MaterialService.order(m2)

    def test_order_refuses_customer_supplied_material(self):
        # customer_supplied kwarg on create_on_job doesn't exist yet (Task 10);
        # set cost_source directly on a constructed material for this test.
        cs = MaterialService.create_on_job(
            job=self.job, description='cust', quantity=Decimal('1'),
            unit_cost=Decimal('0.00'), accounting_category=self.cat, units='ea')
        cs.cost_source = Material.COST_SOURCE_CUSTOMER
        cs.save(update_fields=['cost_source'])
        with self.assertRaises(ValidationError):
            MaterialService.order(cs)

    def test_order_refuses_already_linked_material(self):
        MaterialService.order(self.material)  # first order succeeds
        with self.assertRaises(ValidationError):
            MaterialService.order(self.material)  # second refuses: already linked

    def test_order_refuses_appending_to_non_draft_po(self):
        po, _ = MaterialService.order(self.material)
        vendor_contact = Contact.objects.create(
            first_name='V', last_name='V', mobile_number='6')
        business = Business.objects.create(
            business_name='Vendor Co', default_contact=vendor_contact)
        po.business = business
        po.status = PurchaseOrder.STATUS_ISSUED
        po.save()
        m2 = MaterialService.create_on_job(
            job=self.job, description='rod', quantity=Decimal('1'),
            unit_cost=Decimal('10.00'), accounting_category=self.cat, units='ea')
        with self.assertRaises(ValidationError):
            MaterialService.order(m2, po=po)


class OrderFromMaterialApiTests(APITestCase):
    def setUp(self):
        for key, value in (('po_number_sequence', 'PO-{year}-{counter:04d}'),
                           ('default_material_markup_percent', '25')):
            Configuration.objects.get_or_create(key=key, defaults={'value': value})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MATAPI')
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='japi@d.com', mobile_number='5')
        self.job = Job.objects.create(
            contact=contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0002')
        self.material = MaterialService.create_on_job(
            job=self.job, description='steel', quantity=Decimal('3'),
            unit_cost=Decimal('80.00'), accounting_category=self.cat, units='ea')
        self.user = User.objects.create_user('order_fin_user', password='p')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials'))
        self.client.force_login(self.user)

    def test_order_action_creates_draft_and_returns_po_fields(self):
        resp = self.client.post(
            f'/api/materials/{self.material.pk}/order/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertIsNotNone(data['po_id'])
        self.assertTrue(data['po_number'])
        self.material.refresh_from_db()
        self.assertIsNotNone(self.material.po_line_item_id)

    def test_order_action_appends_to_given_po_id(self):
        po = PurchaseOrderService.create_po()
        resp = self.client.post(
            f'/api/materials/{self.material.pk}/order/',
            {'po_id': po.pk}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['po_id'], po.pk)

    def test_order_action_forbidden_without_financials_atom(self):
        worker = User.objects.create_user('order_worker', password='p')
        self.client.force_login(worker)
        resp = self.client.post(
            f'/api/materials/{self.material.pk}/order/', {}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_order_action_unauthenticated_rejected(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        resp = anon.post(
            f'/api/materials/{self.material.pk}/order/', {}, format='json')
        self.assertIn(resp.status_code, [401, 403])
