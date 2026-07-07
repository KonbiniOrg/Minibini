"""
Tests for the work_complete gate that blocks the Job transition when
task-less inventoried materials are still pending (quantity > 0).
"""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.expenses.models import Expense
from apps.inventory.models import InventoryItem, Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Job, Task, RateScheme
from apps.jobs.services import JobService, TaskLifecycleService

User = get_user_model()


class LooseMaterialWorkCompleteGateTest(TestCase):

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='WCG',
            email='wcg@example.com', work_number='555-0199',
        )
        cat = AccountingCategory.objects.create(name='WCG Cat', code='WCG1')
        self.scheme = RateScheme.objects.create(
            name='S-wcg', algorithm=RateScheme.ENTERED_QTY,
            rate=1, unit_label='ea', accounting_category=cat,
        )
        self.pli = InventoryItem.objects.create(
            code='I-WCG', accounting_category=cat,
            qty_on_hand=Decimal('10'),
        )
        self.job = Job.objects.create(
            job_number='JOB-WC-1', contact=self.contact,
            status=Job.STATUS_APPROVED,
        )
        # Walk to in_progress so tests can transition directly to work_complete.
        self.job.status = Job.STATUS_IN_PROGRESS
        self.job.save()

    def test_taskless_pending_inventoried_material_blocks_transition(self):
        """A pending task-less inventoried material prevents work_complete."""
        MaterialService.create_on_job(
            job=self.job, task=None, description='pending mat',
            quantity=Decimal('2'), inventory_item=self.pli,
        )
        with self.assertRaises(ValidationError):
            JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)

    def test_fully_restocked_expense_bound_does_not_block(self):
        """A task-less material with full restock (quantity == 0) does not block."""
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='restocked mat',
            quantity=Decimal('2'), inventory_item=self.pli,
        )
        user = User.objects.create_user(username='wcg_user', password='x')
        Expense.objects.create(
            entered_by=user,
            amount=Decimal('10'),
            purchased_on='2026-04-14',
            accounting_category=m.accounting_category or AccountingCategory.objects.first(),
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            material=m,
        )
        MaterialService.restock(m, Decimal('2'))
        # Should NOT raise
        JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_WORK_COMPLETE)

    def test_consuming_pending_unblocks(self):
        """Consuming a task-less material clears the gate."""
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='to consume',
            quantity=Decimal('2'), inventory_item=self.pli,
        )
        MaterialService.consume(m)
        # Should NOT raise
        JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_WORK_COMPLETE)

    def test_taskless_non_inventoried_pending_material_blocks_transition(self):
        """A pending task-less non-inventoried material also blocks work_complete."""
        cat = AccountingCategory.objects.first()
        non_inv_pli = InventoryItem.objects.create(
            code='NI-WCG', accounting_category=cat,
        )
        MaterialService.create_on_job(
            job=self.job, task=None, description='non-inv pending',
            quantity=Decimal('1'), inventory_item=non_inv_pli,
        )
        with self.assertRaises(ValidationError):
            JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)

    def test_consumed_no_item_does_not_block(self):
        """A consumed task-less material with no inventory item does not block
        work_complete. consume() now refuses provisional materials, so this
        state can only arise from legacy data; construct it directly to verify
        the gate keys on consumption_state (not inventory_item) and lets it
        through."""
        cat = AccountingCategory.objects.first()
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='no-item consumed',
            quantity=Decimal('1'), inventory_item=None,
            accounting_category=cat,
        )
        m.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        m.save(update_fields=['consumption_state'])
        JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_WORK_COMPLETE)

    def test_last_task_completion_autoadvance_blocked_by_loose_material(self):
        """Auto-advance to work_complete does not fire when loose materials are pending."""
        MaterialService.create_on_job(
            job=self.job, task=None, description='blocking mat',
            quantity=Decimal('2'), inventory_item=self.pli,
        )
        t = Task.objects.create(job=self.job, name='only task', rate_scheme=self.scheme)
        # Drive task completion the same way production does. The scheme is
        # entered_qty, so a quantity must be supplied to complete the task.
        TaskLifecycleService.complete_task(t.pk, add_qty=Decimal('1'))
        self.job.refresh_from_db()
        self.assertNotEqual(self.job.status, Job.STATUS_WORK_COMPLETE)
        # Job should be in_progress (setUp walks to in_progress; loose materials
        # block the auto-advance to work_complete, so it stops here).
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)
