from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job, Task
from apps.inventory.models import Earmark, Material, InventoryItem
from apps.inventory.services import MaterialService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService
from apps.core.models import AccountingCategory, Configuration, AppState


class POChangeLineJobTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job_a = Job.objects.create(job_number='J-A', contact=c, description='a',
                                        status=Job.STATUS_APPROVED)
        self.job_b = Job.objects.create(job_number='J-B', contact=c, description='b',
                                        status=Job.STATUS_APPROVED)
        self.cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = InventoryItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.cat,
        )
        self.po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), inventory_item=self.pli.pk, job=self.job_a.pk,
        )
        self.assertIsNotNone(self.line.linked_material)

    def test_change_job_with_delete_removes_old_material_and_creates_new(self):
        PurchaseOrderService.change_line_job(self.line.pk, self.job_b.pk, sever_decision='delete')
        self.line.refresh_from_db()
        # Old material gone
        self.assertFalse(Earmark.objects.filter(inventory_item=self.pli, job=self.job_a).exists())
        # New material linked on job_b
        new_mat = self.line.linked_material
        self.assertIsNotNone(new_mat)
        self.assertEqual(new_mat.job_id, self.job_b.pk)
        self.assertEqual(new_mat.quantity, Decimal('5.00'))
        ea = Earmark.objects.filter(inventory_item=self.pli, job=self.job_b).first()
        self.assertEqual(ea.quantity, Decimal('5.00'))

    def test_change_job_with_keep_preserves_old_material_unlinked(self):
        original_mat_id = self.line.linked_material.pk
        PurchaseOrderService.change_line_job(self.line.pk, self.job_b.pk, sever_decision='keep')
        # Old material still on job_a, unlinked
        old = Material.objects.get(pk=original_mat_id)
        self.assertEqual(old.job_id, self.job_a.pk)
        self.assertIsNone(old.po_line_item_id)
        self.assertEqual(Earmark.objects.get(inventory_item=self.pli, job=self.job_a).quantity, Decimal('5.00'))
        # New material on job_b
        self.line.refresh_from_db()
        new_mat = self.line.linked_material
        self.assertEqual(new_mat.job_id, self.job_b.pk)

    def test_change_job_missing_sever_decision_raises(self):
        with self.assertRaises(ValidationError):
            PurchaseOrderService.change_line_job(self.line.pk, self.job_b.pk)

    def test_change_job_with_consumed_material_raises(self):
        mat = self.line.linked_material
        mat.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        mat.save(update_fields=['consumption_state'])
        with self.assertRaises(ValidationError):
            PurchaseOrderService.change_line_job(self.line.pk, self.job_b.pk, sever_decision='delete')

    def test_change_job_to_none_unlinks(self):
        PurchaseOrderService.change_line_job(self.line.pk, None, sever_decision='delete')
        self.line.refresh_from_db()
        self.assertIsNone(self.line.linked_material)

    def test_change_job_on_issued_po_works_if_material_pending(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        PurchaseOrderService.change_line_job(self.line.pk, self.job_b.pk, sever_decision='delete')
        self.line.refresh_from_db()
        self.assertEqual(self.line.linked_material.job_id, self.job_b.pk)

    def test_change_job_raises_on_cancelled_po(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        self.po.status = PurchaseOrder.STATUS_CANCELLED
        self.po.save()
        with self.assertRaises(ValidationError):
            PurchaseOrderService.change_line_job(self.line.pk, self.job_b.pk, sever_decision='delete')


class POChangeLineJobOnTaskLineTest(TestCase):
    """PO Job/Task consolidation (RM 2026-09-21), the `change_line_job`
    half of the fix: PurchaseOrderDetail.svelte's edit row rendered an
    unconditional JobPicker for EVERY draft-PO line, including
    task-carrying ones. Picking a job there PATCHed {job}, dispatching to
    the (until now) unguarded `change_line_job` ->
    MaterialService.resolve_or_create_for_line -> _apply_po_line_cost,
    which mints a lot and repoints `inventory_item` via a raw
    `.save(update_fields=[...])` that bypasses `full_clean()` -- silently
    persisting the exact task+inventory_item invalid state this whole
    consolidation exists to prevent."""

    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j',
                                       status=Job.STATUS_APPROVED)
        self.task = Task.objects.create(job=self.job, name='Outsourced task')
        self.po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('1.00'),
            price=Decimal('20.00'), task=self.task.pk,
        )

    def test_change_job_on_task_line_rejected_field_shaped(self):
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.change_line_job(self.line.pk, self.job.pk)
        self.assertIn('job', ctx.exception.message_dict)

    def test_change_job_on_task_line_creates_no_material_or_lot(self):
        with self.assertRaises(ValidationError):
            PurchaseOrderService.change_line_job(self.line.pk, self.job.pk)
        self.line.refresh_from_db()
        self.assertIsNone(self.line.inventory_item_id)
        self.assertIsNone(self.line.linked_material)
        self.assertEqual(Material.objects.count(), 0)
        self.assertEqual(
            InventoryItem.objects.filter(code__startswith='LOT-').count(), 0)

    def test_change_job_to_none_on_task_line_is_a_harmless_noop(self):
        # Clearing the job (new_job_id=None) on a task line is not the
        # invalid combination -- it's already a no-op since a task-carrying
        # line never has a linked Material to unlink in the first place.
        PurchaseOrderService.change_line_job(self.line.pk, None)
        self.line.refresh_from_db()
        self.assertIsNone(self.line.inventory_item_id)
        self.assertEqual(Material.objects.count(), 0)
