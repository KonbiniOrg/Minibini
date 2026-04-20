"""
Tests for decoupling PlanTask from TaskTemplate.
Part 1: PlanTask.accounting_category field, copying at creation points, use in estimate generation.
Part 2: Line item type review at estimate generation.
"""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.db.models import ProtectedError

from apps.jobs.models import Job, PlanTask
from apps.estimates.models import TaskTemplate, WorkTemplate, TemplateTaskAssociation, EstWorksheet, Estimate, EstimateLineItem
from apps.jobs.services import TaskService
from apps.core.models import AccountingCategory, Configuration, User
from apps.contacts.models import Contact


class TaskAccountingCategoryFieldTests(TestCase):
    """Tests that PlanTask has a accounting_category FK field."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.lit = AccountingCategory.objects.create(name="Labor", code="LBR")

    def test_task_can_have_accounting_category(self):
        """PlanTask should have a accounting_category FK field."""
        task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name="Sand Surface",
            accounting_category=self.lit,
        )
        task.refresh_from_db()
        self.assertEqual(task.accounting_category, self.lit)

    def test_task_accounting_category_nullable(self):
        """PlanTask.accounting_category can be null (manual tasks, work order tasks)."""
        task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name="Manual PlanTask",
        )
        self.assertIsNone(task.accounting_category)

    def test_task_accounting_category_protected(self):
        """Cannot delete AccountingCategory if a PlanTask references it."""
        PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name="Sand",
            accounting_category=self.lit,
        )
        with self.assertRaises(ProtectedError):
            self.lit.delete()


class GenerateTaskCopiesAccountingCategoryTests(TestCase):
    """Tests that TaskTemplate.generate_task() copies accounting_category to the PlanTask."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.lit = AccountingCategory.objects.create(name="Labor", code="LBR")

    def test_generate_task_copies_accounting_category(self):
        """generate_task() should copy accounting_category from template to task."""
        tt = TaskTemplate.objects.create(
            template_name="Sand", rate=Decimal("50.00"), accounting_category=self.lit
        )
        task = tt.generate_task(self.worksheet, est_qty=Decimal("2.00"))
        self.assertEqual(task.accounting_category, self.lit)

    def test_generate_task_null_accounting_category(self):
        """generate_task() with template having no accounting_category produces task with null."""
        tt = TaskTemplate.objects.create(
            template_name="Check", rate=Decimal("0.00"), accounting_category=None
        )
        task = tt.generate_task(self.worksheet, est_qty=Decimal("1.00"))
        self.assertIsNone(task.accounting_category)

    def test_generate_tasks_for_worksheet_copies_accounting_category(self):
        """Full template generation copies accounting_category to each task."""
        wot = WorkTemplate.objects.create(template_name="Cabinet")
        tt = TaskTemplate.objects.create(
            template_name="Sand", rate=Decimal("50.00"), accounting_category=self.lit
        )
        TemplateTaskAssociation.objects.create(
            work_template=wot, task_template=tt,
            est_qty=Decimal("2.00")
        )
        tasks = wot.generate_tasks_for_worksheet(self.worksheet)
        self.assertEqual(tasks[0].accounting_category, self.lit)


class CopyPointsPreserveAccountingCategoryTests(TestCase):
    """Tests that all task-copying code preserves accounting_category."""

    def setUp(self):
        Configuration.objects.get_or_create(
            key='estimate_number_sequence',
            defaults={'value': 'EST-{year}-{counter:05d}'}
        )
        Configuration.objects.get_or_create(
            key='estimate_counter', defaults={'value': '0'}
        )
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.lit = AccountingCategory.objects.create(name="Labor", code="LBR")

    def test_create_new_version_copies_accounting_category(self):
        """EstWorksheet.create_new_version() should copy accounting_category to new tasks."""
        ws = EstWorksheet.objects.create(job=self.job)
        PlanTask.objects.create(
            est_worksheet=ws, name="Sand", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"), accounting_category=self.lit,
        )
        # Finalize the worksheet directly so create_new_version() is allowed
        ws.status = EstWorksheet.STATUS_FINAL
        ws.save()

        new_ws = ws.create_new_version()
        new_task = new_ws.plan_tasks.first()
        self.assertEqual(new_task.accounting_category, self.lit)

    def test_copy_worksheet_tasks_copies_accounting_category(self):
        """_copy_worksheet_tasks should copy accounting_category onto job tasks."""
        from apps.core.services import NumberGenerationService
        ws = EstWorksheet.objects.create(job=self.job)
        source_task = PlanTask.objects.create(
            est_worksheet=ws, name="Sand", rate=Decimal("50.00"),
            est_qty=Decimal("2.00"), accounting_category=self.lit,
        )
        # Create estimate and line item manually (no EstimateGenerationService)
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number=NumberGenerationService.generate_next_number('estimate'),
            version=1,
            status=Estimate.STATUS_DRAFT,
        )
        line_item = EstimateLineItem.objects.create(
            estimate=estimate,
            task=source_task,
            line_number=1,
            description="Sand",
            qty=Decimal("2.00"),
            units="hours",
            price=Decimal("50.00"),
            accounting_category=self.lit,
        )

        tasks = TaskService._copy_worksheet_tasks(line_item, self.job)
        self.assertEqual(tasks[0].accounting_category, self.lit)


class TaskDetailAccountingCategoryTests(TestCase):
    """Tests that task_detail shows accounting_category."""

    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass', is_superuser=True)
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.lit = AccountingCategory.objects.create(name="Labor", code="LBR")

    def test_task_detail_shows_accounting_category(self):
        """PlanTask detail should display accounting_category when set."""
        ws = EstWorksheet.objects.create(job=self.job)
        task = PlanTask.objects.create(
            est_worksheet=ws, name="Sand", accounting_category=self.lit,
        )
        url = reverse('jobs:task_detail', args=[task.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Labor")

    def test_task_detail_no_accounting_category(self):
        """PlanTask detail should handle missing accounting_category gracefully."""
        ws = EstWorksheet.objects.create(job=self.job)
        task = PlanTask.objects.create(
            est_worksheet=ws, name="Manual PlanTask",
        )
        url = reverse('jobs:task_detail', args=[task.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
