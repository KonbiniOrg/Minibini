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
            Configuration.objects.update_or_create(key=key, defaults={'value': value})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MAT')
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', phones=[{'number': '5', 'label': 'mobile'}])
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
        cs = MaterialService.create_on_job(
            job=self.job, description='cust', quantity=Decimal('1'),
            accounting_category=self.cat, units='ea', customer_supplied=True)
        with self.assertRaises(ValidationError):
            MaterialService.order(cs)

    def test_order_refuses_already_linked_material(self):
        MaterialService.order(self.material)  # first order succeeds
        with self.assertRaises(ValidationError):
            MaterialService.order(self.material)  # second refuses: already linked

    def test_order_refuses_appending_to_non_draft_po(self):
        po, _ = MaterialService.order(self.material)
        vendor_contact = Contact.objects.create(
            first_name='V', last_name='V', phones=[{'number': '6', 'label': 'mobile'}])
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

    def test_order_with_po_fields_and_line_overrides(self):
        vc = Contact.objects.create(
            first_name='V', last_name='V', email='vendor3@example.com', phones=[{'number': '6', 'label': 'mobile'}])
        business = Business.objects.create(business_name='Vendor Co', default_contact=vc)
        po, li = MaterialService.order(
            self.material, po_fields={'business': business},
            line={'qty': Decimal('5'), 'vendor_sku': 'ST-5', 'price': Decimal('70.00')})
        self.assertEqual(po.business_id, business.pk)
        self.assertEqual((li.qty, li.vendor_sku, li.price), (Decimal('5'), 'ST-5', Decimal('70.00')))
        self.material.refresh_from_db()
        self.assertEqual(self.material.unit_cost, Decimal('70.00'))

    def test_order_rolls_back_the_po_when_the_line_fails(self):
        from unittest.mock import patch
        before = PurchaseOrder.objects.count()
        with patch.object(PurchaseOrderService, 'add_line_item_from_pli',
                          side_effect=ValidationError('boom')):
            with self.assertRaises(ValidationError):
                MaterialService.order(self.material, po_fields={})
        self.assertEqual(PurchaseOrder.objects.count(), before)
        self.material.refresh_from_db()
        self.assertIsNone(self.material.po_line_item_id)


class OrderFromMaterialApiTests(APITestCase):
    """POST /api/materials/{id}/order/ — spec §4.2: exactly one of po_id / po,
    po.business required, line overrides, item fixed by the URL."""

    def setUp(self):
        for key, value in (('po_number_sequence', 'PO-{year}-{counter:04d}'),
                           ('default_material_markup_percent', '25')):
            Configuration.objects.get_or_create(key=key, defaults={'value': value})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MATAPI')
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='japi@d.com', phones=[{'number': '5', 'label': 'mobile'}])
        self.job = Job.objects.create(
            contact=contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0002')
        self.material = MaterialService.create_on_job(
            job=self.job, description='steel', quantity=Decimal('3'),
            unit_cost=Decimal('80.00'), accounting_category=self.cat, units='ea')
        vc = Contact.objects.create(
            first_name='V', last_name='V', email='vendor3@example.com', phones=[{'number': '6', 'label': 'mobile'}])
        self.business = Business.objects.create(business_name='Vendor Co', default_contact=vc)
        vc.business = self.business
        vc.save()
        self.vendor_contact = vc
        self.user = User.objects.create_user('order_fin_user', password='p')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials'))
        self.client.force_login(self.user)
        self.url = f'/api/materials/{self.material.pk}/order/'

    def test_po_mode_creates_vendored_po_with_line_and_links_material(self):
        resp = self.client.post(self.url, {
            'po': {'business': self.business.pk, 'contact': self.vendor_contact.pk,
                   'requested_date': '2026-10-20'},
            'line': {'qty': '4', 'price': '62.40', 'vendor_sku': 'ST-4',
                     'description': 'steel bar', 'units': 'ea'},
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        data = resp.json()
        po = PurchaseOrder.objects.get(pk=data['po_id'])
        self.assertEqual(po.business_id, self.business.pk)
        self.assertEqual(po.contact_id, self.vendor_contact.pk)
        self.assertEqual(po.requested_date.date().isoformat(), '2026-10-20')
        li = po.purchaseorderlineitem_set.get(pk=data['line_item_id'])
        self.assertEqual((li.qty, li.price, li.vendor_sku, li.description),
                         (Decimal('4'), Decimal('62.40'), 'ST-4', 'steel bar'))
        self.material.refresh_from_db()
        self.assertEqual(self.material.po_line_item_id, li.pk)
        self.assertEqual(self.material.unit_cost, Decimal('62.40'))
        self.assertEqual(self.material.cost_source, Material.COST_SOURCE_PO)

    def test_line_defaults_come_from_the_material_and_item(self):
        resp = self.client.post(self.url, {'po': {'business': self.business.pk}}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        li = PurchaseOrder.objects.get(pk=resp.json()['po_id']).purchaseorderlineitem_set.get()
        self.assertEqual(li.qty, Decimal('3'))
        self.assertEqual(li.price, Decimal('80.00'))
        self.assertEqual(li.vendor_sku, '')

    def test_po_id_mode_appends_to_that_draft(self):
        po = PurchaseOrderService.create_po(business=self.business)
        resp = self.client.post(self.url, {'po_id': po.pk, 'line': {'qty': '2'}}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['po_id'], po.pk)
        self.assertEqual(po.purchaseorderlineitem_set.get().qty, Decimal('2'))

    def test_both_or_neither_is_a_non_field_error(self):
        for body in ({}, {'po_id': 1, 'po': {'business': self.business.pk}}):
            resp = self.client.post(self.url, body, format='json')
            self.assertEqual(resp.status_code, 400, resp.content)
            self.assertIn('non_field_errors', resp.json())

    def test_po_mode_requires_business(self):
        resp = self.client.post(self.url, {'po': {}}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('business', resp.json()['po'])

    def test_contact_must_belong_to_the_vendor(self):
        stranger = Contact.objects.create(
            first_name='S', last_name='S', email='stranger3@example.com', phones=[{'number': '7', 'label': 'mobile'}])
        resp = self.client.post(self.url, {
            'po': {'business': self.business.pk, 'contact': stranger.pk}}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('contact', resp.json()['po'])

    def test_line_inventory_item_is_refused(self):
        resp = self.client.post(self.url, {
            'po': {'business': self.business.pk},
            'line': {'inventory_item': self.material.inventory_item_id}}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['line']['inventory_item'], ['Cannot change the item here.'])
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def test_order_api_rejects_zero_qty(self):
        resp = self.client.post(self.url, {
            'po': {'business': self.business.pk}, 'line': {'qty': '0'}}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('qty', resp.json()['line'])
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def test_order_api_inactive_vendor_lands_on_business_field(self):
        self.business.is_active = False
        self.business.save()
        resp = self.client.post(self.url, {'po': {'business': self.business.pk}}, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('business', resp.json())
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def test_non_draft_po_id_rejected(self):
        po = PurchaseOrderService.create_po(business=self.business)
        PurchaseOrderService.add_line_item_from_pli(
            po.pk, self.material.inventory_item_id, Decimal('1'))
        po.status = PurchaseOrder.STATUS_ISSUED
        po.save()
        resp = self.client.post(self.url, {'po_id': po.pk}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.json())

    def test_order_action_forbidden_without_financials_atom(self):
        worker = User.objects.create_user('order_worker', password='p')
        self.client.force_login(worker)
        resp = self.client.post(self.url, {'po': {'business': self.business.pk}}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_order_action_unauthenticated_rejected(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        resp = anon.post(self.url, {'po': {'business': self.business.pk}}, format='json')
        self.assertIn(resp.status_code, [401, 403])
