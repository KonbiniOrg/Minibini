"""complete_task refuses while the task has unconsumed (pending) materials.

RM rule (2026-07-04): a completed task can never blep again, so nothing would
ever consume a leftover pending material — it would sit unbillable forever
(the same bug family the blep-start sweep fixed). Completion therefore stops
with: "if the material was used, consume it by hand, otherwise release it."
Consumed and released materials don't block.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.inventory.models import InventoryItem, Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Job, RateScheme, Task
from apps.jobs.services import TaskLifecycleService


class CompleteTaskMaterialGuardTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='ctg', code='CTG')
        self.scheme = RateScheme.objects.create(
            name='S-ctg', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea', accounting_category=self.cat,
        )
        self.contact = Contact.objects.create(
            first_name='Comp', last_name='Guard', email='ctg@test.com',
        )
        self.job = Job.objects.create(
            job_number='JOB-CTG-1', contact=self.contact,
            status=Job.STATUS_IN_PROGRESS,
        )
        self.pli = InventoryItem.objects.create(
            code='CTG-I', accounting_category=self.cat,
            qty_on_hand=Decimal('10.00'),
        )

    def _task(self, status=Task.STATUS_PENDING):
        t = Task(
            job=self.job, name='t', status=status,
            actual_qty=Decimal('1'),
        )
        t.stamp_from_scheme(self.scheme)
        t.save()
        return t

    def _pending_material(self, task):
        m = Material(
            job=self.job, task=task, description='m',
            quantity=Decimal('2.00'), inventory_item=self.pli,
            accounting_category=self.cat,
        )
        m.save()
        return m

    def test_pending_task_with_pending_material_refuses_completion(self):
        task = self._task()
        self._pending_material(task)
        with self.assertRaises(ValidationError) as ctx:
            TaskLifecycleService.complete_task(task.pk, add_qty=Decimal('0'))
        self.assertIn('consume it by hand', str(ctx.exception))
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_PENDING)

    def test_in_progress_task_with_pending_material_refuses_completion(self):
        task = self._task(status=Task.STATUS_IN_PROGRESS)
        self._pending_material(task)
        with self.assertRaises(ValidationError):
            TaskLifecycleService.complete_task(task.pk, add_qty=Decimal('0'))

    def test_out_of_stock_pending_material_raises_stock_message_first(self):
        # "Consume it by hand" is a dead end when the lot lacks stock —
        # MaterialService.consume would refuse. The guard reports the stock
        # shortage first so the human isn't sent down an impossible path.
        task = self._task()
        m = self._pending_material(task)
        self.pli.qty_on_hand = Decimal('1.00')  # needs 2, only 1 on hand
        self.pli.save()
        with self.assertRaises(ValidationError) as ctx:
            TaskLifecycleService.complete_task(task.pk, add_qty=Decimal('0'))
        msg = str(ctx.exception)
        self.assertIn('not in stock', msg)
        self.assertNotIn('consume it by hand', msg)

    def test_provisional_pending_material_raises_stock_message_first(self):
        # Provisional (no lot) can't be consumed either — same stock-first rule.
        task = self._task()
        Material.objects.create(
            job=self.job, task=task, description='prov',
            quantity=Decimal('1.00'), accounting_category=self.cat,
        )
        with self.assertRaises(ValidationError) as ctx:
            TaskLifecycleService.complete_task(task.pk, add_qty=Decimal('0'))
        msg = str(ctx.exception)
        self.assertIn('not in stock', msg)
        self.assertNotIn('consume it by hand', msg)

    def test_consumed_material_does_not_block(self):
        task = self._task()
        m = self._pending_material(task)
        MaterialService.consume(m)
        TaskLifecycleService.complete_task(task.pk, add_qty=Decimal('0'))
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_COMPLETE)

    def test_released_material_does_not_block(self):
        task = self._task()
        m = self._pending_material(task)
        # Restocking the full quantity is the release path; make the material
        # referenced first so it survives as `released` (a bare unreferenced
        # one would be deleted — which also unblocks).
        from apps.estimates.models import (
            Estimate, EstimateLineItem, EstimateLineItemSource,
        )
        est = Estimate.objects.create(
            job=self.job, estimate_number='EST-CTG-1',
            status=Estimate.STATUS_ACCEPTED,
        )
        line = EstimateLineItem.objects.create(
            estimate=est, line_number=1, description='claim',
            qty=Decimal('1'), price=Decimal('10.00'),
            accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=line,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=m.pk,
        )
        MaterialService.restock(m, m.quantity)
        m.refresh_from_db()
        self.assertEqual(m.consumption_state,
                         Material.CONSUMPTION_STATE_RELEASED)
        TaskLifecycleService.complete_task(task.pk, add_qty=Decimal('0'))
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_COMPLETE)

    def test_no_materials_completes_fine(self):
        task = self._task()
        TaskLifecycleService.complete_task(task.pk, add_qty=Decimal('0'))
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_COMPLETE)
