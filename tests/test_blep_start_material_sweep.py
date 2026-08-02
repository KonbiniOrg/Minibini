"""Blep start sweeps the task's pending materials (consume-at-blep-start).

The rule set (2026-07-04 design conversation):
1. Material added to a started task while IN STOCK → consumes immediately
   (consume_if_task_started — covered in test_late_material_consumption).
2. Added while OUT of stock → stays pending, and then:
   a. the next blep is PREVENTED (work can't continue without the material —
      same coaching error the first-blep promotion path raises), or
   b. the stock arrives and the next blep's sweep consumes it.
The no-next-blep worry doesn't exist: an after-the-fact "we used more" add is
an in-stock case and consumed at add.

Applies to live starts (start_work) and hand-added bleps (create_historical)
alike — a blep means work is happening, whichever way it's recorded.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Shift, User
from apps.inventory.models import InventoryItem, Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Blep, Job, RateScheme, Task
from apps.jobs.services import BlepService, TaskLifecycleService

from datetime import timedelta


class BlepStartSweepBase(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='bss', code='BSS')
        self.scheme = RateScheme.objects.create(
            name='S-bss', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50'), unit_label='hour', accounting_category=self.cat,
        )
        self.contact = Contact.objects.create(
            first_name='Blep', last_name='Sweep', email='bss@test.com',
        )
        self.job = Job.objects.create(
            job_number='JOB-BSS-1', contact=self.contact,
            status=Job.STATUS_IN_PROGRESS,
        )
        self.task = Task.objects.create(
            job=self.job, name='started', rate_scheme=self.scheme,
            status=Task.STATUS_IN_PROGRESS,
        )
        self.worker = User.objects.create_user(username='bss_worker', password='x')
        now = timezone.now()
        # OPEN shift (worker on the clock): a closed future-ending shift would
        # trip the per-user no-overlap rule when start_work auto-clocks in; an
        # open shift is reused by ensure_open_shift and encloses closed bleps
        # (its end is unbounded).
        Shift.objects.create(
            user=self.worker,
            start_time=now - timedelta(days=1),
        )
        self.pli = InventoryItem.objects.create(
            code='BSS-I', accounting_category=self.cat,
            qty_on_hand=Decimal('0.00'),
        )

    def _shortfall_material(self, qty='3.00'):
        """A pending material the stock can't cover (added while out of stock,
        so consume-on-add left it pending)."""
        return MaterialService.create_on_job(
            job=self.job, task=self.task, description='awaited stock',
            quantity=Decimal(qty), inventory_item=self.pli,
        )


class StartWorkSweepTest(BlepStartSweepBase):

    def test_blep_prevented_while_material_out_of_stock(self):
        material = self._shortfall_material()
        with self.assertRaises(ValidationError):
            TaskLifecycleService.start_work(self.task.pk, self.worker)
        self.assertFalse(Blep.objects.filter(task=self.task).exists())
        material.refresh_from_db()
        self.assertEqual(material.consumption_state,
                         Material.CONSUMPTION_STATE_PENDING)

    def test_blep_consumes_after_stock_arrives(self):
        material = self._shortfall_material()
        self.pli.qty_on_hand = Decimal('5.00')
        self.pli.save(update_fields=['qty_on_hand'])
        result = TaskLifecycleService.start_work(self.task.pk, self.worker)
        self.assertIn('blep', result)
        material.refresh_from_db()
        self.assertEqual(material.consumption_state,
                         Material.CONSUMPTION_STATE_CONSUMED)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('2.00'))

    def test_blep_on_task_with_no_pending_materials_unaffected(self):
        result = TaskLifecycleService.start_work(self.task.pk, self.worker)
        self.assertIn('blep', result)


class CreateHistoricalSweepTest(BlepStartSweepBase):

    def _times(self):
        now = timezone.now()
        return now - timedelta(hours=2), now - timedelta(hours=1)

    def test_hand_added_blep_prevented_while_out_of_stock(self):
        self._shortfall_material()
        start, end = self._times()
        with self.assertRaises(ValidationError):
            BlepService.create_historical(self.worker, self.task, start, end)
        self.assertFalse(Blep.objects.filter(task=self.task).exists())

    def test_hand_added_blep_consumes_arrived_stock(self):
        material = self._shortfall_material()
        self.pli.qty_on_hand = Decimal('5.00')
        self.pli.save(update_fields=['qty_on_hand'])
        start, end = self._times()
        BlepService.create_historical(self.worker, self.task, start, end)
        material.refresh_from_db()
        self.assertEqual(material.consumption_state,
                         Material.CONSUMPTION_STATE_CONSUMED)
