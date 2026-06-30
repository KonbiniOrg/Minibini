"""B6 — merge (manual consolidation)."""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from django.contrib.auth.models import Permission
from apps.core.models import AccountingCategory, User, InventoryHistory
from apps.contacts.models import Contact
from apps.jobs.models import Job, Task, RateScheme
from apps.inventory.models import InventoryItem, Earmark, Material
from apps.inventory.services import InventoryService


class MergeServiceTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.contact = Contact.objects.create(first_name='A', last_name='B')
        self.job = Job.objects.create(job_number='J-MRG-1', contact=self.contact)
        self.keep = InventoryItem.objects.create(
            code='KEEP', description='grey felt', units='sheet',
            qty_on_hand=Decimal('2.00'), qty_sold=Decimal('1.00'),
            is_catalog=True, accounting_category=self.cat)
        self.discard = InventoryItem.objects.create(
            code='DISC', description='gray felt 1/4', units='sheet',
            qty_on_hand=Decimal('3.00'), qty_sold=Decimal('4.00'),
            is_catalog=False, accounting_category=self.cat)

    def test_merge_folds_qoh_and_aggregates(self):
        InventoryService.merge(self.keep.pk, self.discard.pk)
        self.keep.refresh_from_db()
        self.assertEqual(self.keep.qty_on_hand, Decimal('5.00'))   # 2 + 3
        self.assertEqual(self.keep.qty_sold, Decimal('5.00'))      # 1 + 4
        self.assertFalse(InventoryItem.objects.filter(pk=self.discard.pk).exists())

    def test_merge_repoints_materials(self):
        scheme = RateScheme.objects.create(
            name='S', algorithm=RateScheme.ENTERED_QTY, rate=1, unit_label='ea',
            accounting_category=self.cat)
        task = Task.objects.create(job=self.job, name='t', rate_scheme=scheme)
        m = Material.objects.create(
            job=self.job, task=task, inventory_item=self.discard,
            description='x', quantity=Decimal('1'))
        InventoryService.merge(self.keep.pk, self.discard.pk)
        m.refresh_from_db()
        self.assertEqual(m.inventory_item_id, self.keep.pk)

    def test_merge_sum_collapses_colliding_earmarks(self):
        Earmark.objects.create(inventory_item=self.keep, job=self.job, quantity=Decimal('2'))
        Earmark.objects.create(inventory_item=self.discard, job=self.job, quantity=Decimal('3'))
        InventoryService.merge(self.keep.pk, self.discard.pk)
        ems = Earmark.objects.filter(inventory_item=self.keep, job=self.job)
        self.assertEqual(ems.count(), 1)
        self.assertEqual(ems.first().quantity, Decimal('5'))  # 2 + 3 collapsed

    def test_merge_repoints_noncolliding_earmark(self):
        other_job = Job.objects.create(job_number='J-MRG-2', contact=self.contact)
        Earmark.objects.create(inventory_item=self.discard, job=other_job, quantity=Decimal('3'))
        InventoryService.merge(self.keep.pk, self.discard.pk)
        self.assertTrue(Earmark.objects.filter(
            inventory_item=self.keep, job=other_job).exists())

    def test_merge_unit_mismatch_blocked(self):
        self.discard.units = 'foot'
        self.discard.save()
        with self.assertRaises(ValidationError):
            InventoryService.merge(self.keep.pk, self.discard.pk)

    def test_merge_catalog_discard_blocked(self):
        self.discard.is_catalog = True
        self.discard.save()
        with self.assertRaises(ValidationError):
            InventoryService.merge(self.keep.pk, self.discard.pk)

    def test_merge_applies_overrides_including_discard_code(self):
        # Retain the discard's description and code on keep (discard is deleted
        # first, so the code is free).
        InventoryService.merge(
            self.keep.pk, self.discard.pk,
            overrides={'description': 'gray felt 1/4', 'code': 'DISC'})
        self.keep.refresh_from_db()
        self.assertEqual(self.keep.description, 'gray felt 1/4')
        self.assertEqual(self.keep.code, 'DISC')

    def test_merge_repoints_protected_refs_and_deletes_discard(self):
        """The critical case: a discard referenced by PROTECT FKs (a PO line
        item and a template-material association) must have those refs repointed
        so the discard can be deleted without ProtectedError."""
        from apps.contacts.models import Business
        from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
        from apps.estimates.models import WorkTemplate
        from apps.inventory.models import TemplateMaterialAssociation
        biz = Business.objects.create(business_name='V', default_contact=self.contact)
        po = PurchaseOrder.objects.create(
            business=biz, po_number='PO-MRG', status=PurchaseOrder.STATUS_DRAFT)
        poli = PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='x', qty=Decimal('1'),
            price=Decimal('1'), inventory_item=self.discard)
        wt = WorkTemplate.objects.create(template_name='WT-MRG')
        tma = TemplateMaterialAssociation.objects.create(
            work_template=wt, inventory_item=self.discard, quantity=Decimal('1'))

        # Would raise ProtectedError if any PROTECT ref were left dangling.
        InventoryService.merge(self.keep.pk, self.discard.pk)

        self.assertFalse(InventoryItem.objects.filter(pk=self.discard.pk).exists())
        poli.refresh_from_db()
        tma.refresh_from_db()
        self.assertEqual(poli.inventory_item_id, self.keep.pk)
        self.assertEqual(tma.inventory_item_id, self.keep.pk)

    def test_merge_records_both_history_entries(self):
        InventoryService.merge(self.keep.pk, self.discard.pk)
        keep_in = InventoryHistory.objects.filter(
            object_type='inventoryitem', object_id=self.keep.pk,
            entry_type='action')
        disc_out = InventoryHistory.objects.filter(
            object_type='inventoryitem', object_id=self.discard.pk,
            entry_type='action')
        self.assertTrue(keep_in.exists())
        self.assertTrue(disc_out.exists())
        self.assertEqual(disc_out.first().changes['merged_into'], 'KEEP')


class MergeEndpointTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.cat = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.keep = InventoryItem.objects.create(
            code='K', units='ea', qty_on_hand=Decimal('1.00'),
            is_catalog=True, accounting_category=self.cat)
        self.discard = InventoryItem.objects.create(
            code='D', units='ea', qty_on_hand=Decimal('1.00'),
            is_catalog=False, accounting_category=self.cat)
        u = User.objects.create(username='merge_fin')
        u.user_permissions.add(Permission.objects.get(codename='can_manage_financials'))
        self.client.force_authenticate(User.objects.get(pk=u.pk))

    def test_merge_endpoint_happy(self):
        resp = self.client.post('/api/inventory/merge/', {
            'keep_id': self.keep.pk, 'discard_id': self.discard.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.keep.refresh_from_db()
        self.assertEqual(self.keep.qty_on_hand, Decimal('2.00'))

    def test_merge_endpoint_missing_ids(self):
        resp = self.client.post('/api/inventory/merge/', {
            'keep_id': self.keep.pk}, format='json')
        self.assertEqual(resp.status_code, 400)
