"""
Tests for the work_complete gate that blocks the Job transition when
task-less inventoried materials are still pending (net effective qty > 0).
"""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.expenses.models import Expense
from apps.inventory.models import PriceListItem, Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Job, Task
from apps.jobs.services import JobService, TaskLifecycleService

User = get_user_model()


class LooseMaterialWorkCompleteGateTest(TestCase):

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='WCG',
            email='wcg@example.com', work_number='555-0199',
        )
        cat = AccountingCategory.objects.create(name='WCG Cat', code='WCG1')
        self.pli = PriceListItem.objects.create(
            code='I-WCG', accounting_category=cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )
        self.job = Job.objects.create(
            job_number='JOB-WC-1', contact=self.contact,
            status=Job.STATUS_APPROVED,
        )

    def test_taskless_pending_inventoried_material_blocks_transition(self):
        """A pending task-less inventoried material prevents work_complete."""
        MaterialService.create_on_job(
            job=self.job, task=None, description='pending mat',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        with self.assertRaises(ValidationError):
            JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)

    def test_fully_restocked_expense_bound_does_not_block(self):
        """A task-less material with full restock (eff qty == 0) does not block."""
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='restocked mat',
            quantity=Decimal('2'), price_list_item=self.pli,
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
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        MaterialService.consume(m)
        # Should NOT raise
        JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_WORK_COMPLETE)

    def test_last_task_completion_autoadvance_blocked_by_loose_material(self):
        """Auto-advance from last task completion does not fire when loose materials are pending."""
        MaterialService.create_on_job(
            job=self.job, task=None, description='blocking mat',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        t = Task.objects.create(job=self.job, name='only task')
        # Drive task completion the same way production does.
        TaskLifecycleService.complete_task(t.pk)
        self.job.refresh_from_db()
        self.assertNotEqual(self.job.status, Job.STATUS_WORK_COMPLETE)
        # Job should still be approved
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)
