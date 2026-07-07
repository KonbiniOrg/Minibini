"""A material added to (or moved onto) an already-started task gets consumed.

Consumption is normally a one-shot side effect of the pending → in_progress
promotion (`_promote_pending_task`), so a material attached *after* the task
started used to stay pending forever — never decrementing stock, never
billable (billable ⟺ consumed).

Rule delivered here: on add (`MaterialService.create_on_job`) or reassign
(`MaterialService.assign_task`) to an `in_progress` task, the material is
consumed immediately — unless the stock physically isn't there (PLI with
insufficient QOH), in which case it stays pending so the procure-via-PO flow
(add shortfall material → order → receive) keeps working.
"""
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.inventory.models import InventoryItem, Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Job, RateScheme, Task


class LateMaterialConsumptionBase(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='lm', code='LM1')
        self.scheme = RateScheme.objects.create(
            name='S-lm', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('1'), unit_label='ea', accounting_category=self.cat,
        )
        self.contact = Contact.objects.create(
            first_name='Late', last_name='Add', email='late@test.com',
        )
        self.job = Job.objects.create(
            job_number='JOB-LM-1', contact=self.contact,
            status=Job.STATUS_IN_PROGRESS,
        )
        self.task = Task.objects.create(
            job=self.job, name='started', rate_scheme=self.scheme,
            status=Task.STATUS_IN_PROGRESS,
        )
        self.pli = InventoryItem.objects.create(
            code='LM-I', accounting_category=self.cat,
            qty_on_hand=Decimal('10'),
        )


class CreateOnStartedTaskTest(LateMaterialConsumptionBase):

    def test_stocked_material_added_to_in_progress_task_is_consumed(self):
        m = MaterialService.create_on_job(
            job=self.job, task=self.task, description='late sheet',
            quantity=Decimal('3'), inventory_item=self.pli,
        )
        m.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('7'))

    def test_provisional_material_added_to_in_progress_task_stays_pending(self):
        # A provisional (no lot, sell-only) material added late stays pending:
        # consume() refuses provisional materials, and the late-add sweep mirrors
        # the understock rule — in-flight pricing is a legitimate pending state
        # that must not block the add. It consumes once priced + received.
        m = MaterialService.create_on_job(
            job=self.job, task=self.task, description='special finish',
            quantity=Decimal('1'), sell_price=Decimal('30.00'),
            accounting_category=self.cat,
        )
        m.refresh_from_db()
        self.assertIsNone(m.inventory_item_id)
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)

    def test_understocked_material_stays_pending_for_procurement(self):
        # Not enough on hand: the add succeeds and the material stays pending
        # (the order-it-via-PO flow needs the pending row to anchor the line).
        m = MaterialService.create_on_job(
            job=self.job, task=self.task, description='shortfall',
            quantity=Decimal('99'), inventory_item=self.pli,
        )
        m.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('10'))

    def test_material_added_to_pending_task_stays_pending(self):
        pending_task = Task.objects.create(
            job=self.job, name='not started', rate_scheme=self.scheme,
        )
        m = MaterialService.create_on_job(
            job=self.job, task=pending_task, description='normal add',
            quantity=Decimal('2'), inventory_item=self.pli,
        )
        m.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)

    def test_taskless_material_stays_pending(self):
        m = MaterialService.create_on_job(
            job=self.job, description='loose', quantity=Decimal('2'),
            inventory_item=self.pli,
        )
        m.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)


class AssignToStartedTaskTest(LateMaterialConsumptionBase):

    def test_reassign_to_in_progress_task_consumes(self):
        m = MaterialService.create_on_job(
            job=self.job, description='loose then assigned',
            quantity=Decimal('2'), inventory_item=self.pli,
        )
        MaterialService.assign_task(m, self.task)
        m.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('8'))

    def test_reassign_understocked_stays_pending(self):
        m = MaterialService.create_on_job(
            job=self.job, description='big loose',
            quantity=Decimal('99'), inventory_item=self.pli,
        )
        MaterialService.assign_task(m, self.task)
        m.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)

    def test_reassign_to_pending_task_stays_pending(self):
        pending_task = Task.objects.create(
            job=self.job, name='not started 2', rate_scheme=self.scheme,
        )
        m = MaterialService.create_on_job(
            job=self.job, description='loose 2',
            quantity=Decimal('2'), inventory_item=self.pli,
        )
        MaterialService.assign_task(m, pending_task)
        m.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
