"""PO Job/Task consolidation (RM 2026-09-21): a PO line either attributes
cost to a task (pure attribution -- no Material is created, inventory_item
stays null) or procures a material for a job (today's unchanged claim-or-
create / lot-minting flow) -- never both.

Pins the crash this consolidation replaces: the old two-picker LineItemForm
let a caller fill BOTH the legacy Job field and a Task link. The job field
drove MaterialService.resolve_or_create_for_line, which for a freeform hand
line mints a LOT-{pk} and repoints `line.inventory_item` at it -- tripping
BaseLineItem.clean's deep task/inventory_item XOR with a message about an
inventory item the user never chose. PurchaseOrderService._reject_task_with_
procurement now rejects task+job/material_id BEFORE any material machinery
runs, with a clear field-shaped error instead.
"""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job, Task
from apps.inventory.models import Material, InventoryItem
from apps.inventory.services import MaterialService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService
from apps.core.models import AccountingCategory, Configuration, AppState


class POLineTaskJobExclusivityTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j',
                                       status=Job.STATUS_APPROVED)
        self.task = Task.objects.create(job=self.job, name='Outsourced task')
        self.cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = InventoryItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.cat,
        )
        self.po = PurchaseOrder.objects.create(business=self.business)

    # -- add_line_item -----------------------------------------------

    def test_task_with_job_rejected_field_shaped_before_material_created(self):
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.add_line_item(
                self.po.pk, description='x', qty=Decimal('1.00'),
                price=Decimal('20.00'), task=self.task.pk, job=self.job.pk,
            )
        self.assertIn('task', ctx.exception.message_dict)
        self.assertEqual(Material.objects.count(), 0)
        self.assertEqual(PurchaseOrderLineItem.objects.count(), 0)

    def test_task_with_material_id_rejected(self):
        existing = MaterialService.create_on_job(
            job=self.job, inventory_item=self.pli, quantity=Decimal('3.00'),
        )
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.add_line_item(
                self.po.pk, description='x', qty=Decimal('1.00'),
                price=Decimal('20.00'), task=self.task.pk, material_id=existing.pk,
            )
        self.assertIn('task', ctx.exception.message_dict)
        self.assertEqual(PurchaseOrderLineItem.objects.count(), 0)

    def test_task_only_line_creates_no_material_and_leaves_inventory_item_null(self):
        """Pins the crash case dead: previously, filling the legacy Job
        field alongside a Task link on this exact kind of line reached
        MaterialService and minted a LOT, repointing inventory_item on a
        task-carrying line."""
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('1.00'),
            price=Decimal('20.00'), task=self.task.pk,
        )
        self.assertIsNone(line.inventory_item_id)
        self.assertIsNone(line.linked_material)
        self.assertEqual(Material.objects.count(), 0)

    # -- add_line_item_from_pli ----------------------------------------

    def test_add_line_item_from_pli_rejects_task_with_job(self):
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.add_line_item_from_pli(
                self.po.pk, self.pli.pk, Decimal('1.00'),
                job=self.job.pk, task=self.task.pk,
            )
        self.assertIn('task', ctx.exception.message_dict)
        self.assertEqual(Material.objects.count(), 0)
        self.assertEqual(PurchaseOrderLineItem.objects.count(), 0)

    def test_add_line_item_from_pli_rejects_task_with_material_id(self):
        existing = MaterialService.create_on_job(
            job=self.job, inventory_item=self.pli, quantity=Decimal('3.00'),
        )
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.add_line_item_from_pli(
                self.po.pk, self.pli.pk, Decimal('1.00'),
                material_id=existing.pk, task=self.task.pk,
            )
        self.assertIn('task', ctx.exception.message_dict)
        self.assertEqual(PurchaseOrderLineItem.objects.count(), 0)

    def test_add_line_item_from_pli_task_only_still_hits_deep_invariant(self):
        """Choosing an inventory item AND a task (no job/material_id) is
        not the confusing auto-minted-lot case -- the caller explicitly
        picked both -- so it's left to BaseLineItem.clean()'s existing,
        sensible task/inventory_item message rather than the new guard."""
        with self.assertRaises(ValidationError) as ctx:
            PurchaseOrderService.add_line_item_from_pli(
                self.po.pk, self.pli.pk, Decimal('1.00'), task=self.task.pk,
            )
        self.assertIn('LineItem cannot have both task and inventory_item', str(ctx.exception))
