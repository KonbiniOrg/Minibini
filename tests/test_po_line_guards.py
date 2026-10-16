"""PO add-line guards (PO order flow §4.4): a comment line can't carry a
job; an explicit material_id must agree with the line's item; and a
provisional material on a catalog line is established onto that item
instead of minting a stray lot."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.inventory.models import InventoryItem, Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Job
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService


class _Base(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.update_or_create(
            key='default_material_markup_percent', defaults={'value': '25'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V',
                                   phones=[{'number': '5', 'label': 'work'}])
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business
        c.save()
        self.job = Job.objects.create(job_number='J-G', contact=c, description='j',
                                      status=Job.STATUS_APPROVED)
        self.cat = AccountingCategory.objects.get_or_create(
            code='MATG', defaults={'name': 'Material'})[0]
        self.ply = InventoryItem.objects.create(
            code='BBPLY.75', description='3/4 ply', purchase_price=Decimal('60.00'),
            selling_price=Decimal('80.00'), accounting_category=self.cat, units='sheet')
        self.mdf = InventoryItem.objects.create(
            code='MDF.75', description='3/4 mdf', purchase_price=Decimal('30.00'),
            selling_price=Decimal('40.00'), accounting_category=self.cat, units='sheet')
        self.po = PurchaseOrder.objects.create(business=self.business)


class CommentLineGuardTests(_Base):
    def test_comment_with_job_is_rejected_on_the_job_field(self):
        with self.assertRaises(ValidationError) as cm:
            PurchaseOrderService.add_line_item(
                self.po.pk, description='lead time 6 weeks', is_comment=True,
                qty=0, price=0, job=self.job.pk)
        self.assertIn('job', cm.exception.message_dict)
        self.assertEqual(Material.objects.filter(job=self.job).count(), 0)
        self.assertEqual(self.po.purchaseorderlineitem_set.count(), 0)

    def test_comment_with_material_id_is_rejected(self):
        mat = MaterialService.create_on_job(
            job=self.job, inventory_item=self.ply, quantity=Decimal('1'))
        with self.assertRaises(ValidationError) as cm:
            PurchaseOrderService.add_line_item(
                self.po.pk, description='note', is_comment=True, qty=0, price=0,
                material_id=mat.pk)
        self.assertIn('job', cm.exception.message_dict)

    def test_api_shape(self):
        user = User.objects.create_user('guard_admin', password='p', is_superuser=True)
        client = APIClient()
        client.force_authenticate(user)
        r = client.post(f'/api/purchase-orders/{self.po.pk}/line-items/', {
            'description': 'note', 'is_comment': True, 'qty': 0, 'price': 0,
            'units': 'none', 'job': self.job.pk}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('job', r.json())


class MaterialItemMismatchTests(_Base):
    def test_explicit_material_on_a_different_item_is_rejected(self):
        mat = MaterialService.create_on_job(
            job=self.job, inventory_item=self.ply, quantity=Decimal('2'))
        before = PurchaseOrderLineItem.objects.count()
        with self.assertRaises(ValidationError) as cm:
            PurchaseOrderService.add_line_item(
                self.po.pk, description='mdf', qty=Decimal('2'), price=Decimal('30.00'),
                inventory_item=self.mdf.pk, material_id=mat.pk)
        self.assertEqual(cm.exception.message_dict['material_id'],
                         ['This material needs BBPLY.75, not MDF.75.'])
        self.assertEqual(PurchaseOrderLineItem.objects.count(), before)
        mat.refresh_from_db()
        self.assertIsNone(mat.po_line_item_id)

    def test_pli_path_hits_the_same_guard(self):
        mat = MaterialService.create_on_job(
            job=self.job, inventory_item=self.ply, quantity=Decimal('2'))
        with self.assertRaises(ValidationError) as cm:
            PurchaseOrderService.add_line_item_from_pli(
                self.po.pk, self.mdf.pk, Decimal('2'), material_id=mat.pk)
        self.assertIn('material_id', cm.exception.message_dict)

    def test_matching_item_still_links(self):
        mat = MaterialService.create_on_job(
            job=self.job, inventory_item=self.ply, quantity=Decimal('2'))
        li = PurchaseOrderService.add_line_item_from_pli(
            self.po.pk, self.ply.pk, Decimal('2'), material_id=mat.pk)
        mat.refresh_from_db()
        self.assertEqual(mat.po_line_item_id, li.pk)


class ProvisionalEstablishTests(_Base):
    def test_catalog_line_establishes_provisional_material_onto_the_lines_item(self):
        prov = MaterialService.create_on_job(
            job=self.job, description='some ply', quantity=Decimal('2'),
            accounting_category=self.cat, units='sheet')
        self.assertIsNone(prov.inventory_item_id)
        lots_before = InventoryItem.objects.filter(code__startswith='LOT-').count()
        li = PurchaseOrderService.add_line_item(
            self.po.pk, description='3/4 ply', qty=Decimal('2'), price=Decimal('58.00'),
            inventory_item=self.ply.pk, material_id=prov.pk)
        prov.refresh_from_db()
        self.assertEqual(prov.inventory_item_id, self.ply.pk)
        self.assertEqual(prov.po_line_item_id, li.pk)
        self.assertEqual(prov.unit_cost, Decimal('58.00'))
        self.assertEqual(prov.cost_source, Material.COST_SOURCE_PO)
        self.assertEqual(InventoryItem.objects.filter(code__startswith='LOT-').count(), lots_before)
        li.refresh_from_db()
        self.assertEqual(li.inventory_item_id, self.ply.pk)

    def test_freeform_line_still_mints_a_lot_and_repoints_the_line(self):
        prov = MaterialService.create_on_job(
            job=self.job, description='custom bracket', quantity=Decimal('1'),
            accounting_category=self.cat, units='ea')
        li = PurchaseOrderService.add_line_item(
            self.po.pk, description='bracket', qty=Decimal('1'), price=Decimal('12.00'),
            material_id=prov.pk)
        prov.refresh_from_db()
        li.refresh_from_db()
        self.assertTrue(prov.inventory_item.code.startswith('LOT-'))
        self.assertEqual(li.inventory_item_id, prov.inventory_item_id)
