"""
Tests for the EstWorksheet model.

The worksheet is decoupled from the estimate: it relates only to a job, carries
no status/version/parent, and its editability is derived from the job's live
estimate (see WorksheetService.is_editable, covered in test_estimates_services).
"""

from datetime import timedelta

from django.test import TestCase
from decimal import Decimal

from apps.contacts.models import Contact
from apps.jobs.models import Job, Task, PlanTask, ServicePrice
from apps.estimates.models import EstWorksheet
from apps.core.models import User, AccountingCategory


def _make_scheme(suffix):
    """Helper: create a minimal ServicePrice + AccountingCategory for tests."""
    ac = AccountingCategory.objects.create(code=f'ESTWS-{suffix}', name=f'estws-{suffix}')
    return ServicePrice.objects.create(
        name=f'S-estws-{suffix}', algorithm=ServicePrice.FLAT_FEE,
        rate=Decimal('1'), unit_label='ea', accounting_category=ac,
    )


class EstWorksheetModelTest(TestCase):
    """Test EstWorksheet model creation and basic functionality."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )
        self.user = User.objects.create_user(username="testuser")

    def test_estworksheet_creation(self):
        """A worksheet belongs to a job and carries no lifecycle fields."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        self.assertEqual(worksheet.job, self.job)
        self.assertIsNotNone(worksheet.created_date)

    def test_estworksheet_str_method(self):
        """Test EstWorksheet string representation."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        self.assertEqual(str(worksheet), f"EstWorksheet {worksheet.pk}")


class TaskWorkContainerTest(TestCase):
    """Test Task and PlanTask are type-separated by container (post-split)."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )
        self.user = User.objects.create_user(username="testuser")

    def test_task_with_job(self):
        """Test creating Task directly on a Job (post-WorkOrder-removal)."""
        scheme = _make_scheme('twj')
        task = Task.objects.create(
            job=self.job,
            name="Job Task",
            service_price=scheme,
        )

        self.assertEqual(task.job, self.job)

    def test_plan_task_with_estworksheet(self):
        """Test creating PlanTask on an EstWorksheet."""
        scheme = _make_scheme('ptws')
        worksheet = EstWorksheet.objects.create(job=self.job)

        task = PlanTask.objects.create(
            est_worksheet=worksheet,
            name="Worksheet Task",
            service_price=scheme,
            est_qty=Decimal('1'),
        )

        self.assertEqual(task.est_worksheet, worksheet)

    def test_worksheet_plan_tasks_accessor(self):
        """Test accessing plan tasks through EstWorksheet.plan_tasks."""
        scheme = _make_scheme('wpta')
        worksheet = EstWorksheet.objects.create(job=self.job)

        task1 = PlanTask.objects.create(
            est_worksheet=worksheet,
            name="Task 1",
            service_price=scheme,
            est_qty=Decimal('1'),
        )

        task2 = PlanTask.objects.create(
            est_worksheet=worksheet,
            name="Task 2",
            service_price=scheme,
            est_qty=Decimal('1'),
        )

        tasks = worksheet.plan_tasks.all()
        self.assertEqual(tasks.count(), 2)
        self.assertIn(task1, tasks)
        self.assertIn(task2, tasks)
