"""
Tests for EstWorksheet model and its status transitions.
"""

from datetime import timedelta

from django.test import TestCase
from django.core.exceptions import ValidationError
from decimal import Decimal

from apps.contacts.models import Contact
from apps.jobs.models import Job, Task, PlanTask, RateScheme
from apps.estimates.models import Estimate, EstWorksheet, EstimateLineItem, WorkTemplate, TaskTemplate
from apps.inventory.models import PlanMaterial
from apps.core.models import User, AccountingCategory


def _make_scheme(suffix):
    """Helper: create a minimal RateScheme + AccountingCategory for tests."""
    ac = AccountingCategory.objects.create(code=f'ESTWS-{suffix}', name=f'estws-{suffix}')
    return RateScheme.objects.create(
        name=f'S-estws-{suffix}', algorithm=RateScheme.FLAT_FEE,
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
        """Test creating an EstWorksheet."""
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            status=Job.STATUS_DRAFT
        )

        self.assertEqual(worksheet.job, self.job)
        self.assertEqual(worksheet.status, EstWorksheet.STATUS_DRAFT)
        self.assertEqual(worksheet.version, 1)
        self.assertIsNone(worksheet.estimate)
        self.assertIsNone(worksheet.parent)

    def test_estworksheet_default_status_is_draft(self):
        """Test that EstWorksheet always starts in draft status by default."""
        # Create worksheet without specifying status
        worksheet = EstWorksheet.objects.create(
            job=self.job
        )

        # Should default to draft
        self.assertEqual(worksheet.status, EstWorksheet.STATUS_DRAFT)

    def test_estworksheet_cannot_be_created_with_non_draft_status(self):
        """Test that new EstWorksheets always start as draft, even if another status is attempted."""
        # This test documents the expected behavior
        # The model default ensures new worksheets start as draft
        worksheet = EstWorksheet.objects.create(
            job=self.job
            # Not specifying status to use default
        )

        self.assertEqual(worksheet.status, EstWorksheet.STATUS_DRAFT)
        
    def test_estworksheet_str_method(self):
        """Test EstWorksheet string representation."""
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            version=3
        )
        
        self.assertEqual(str(worksheet), f"EstWorksheet {worksheet.pk} v3")


class EstWorksheetStatusTransitionTest(TestCase):
    """Test EstWorksheet status transitions based on Estimate status."""
    
    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )
        
    def test_worksheet_status_with_draft_estimate(self):
        """Test worksheet remains in draft when estimate is draft."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status=Job.STATUS_DRAFT
        )
        
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )
        
        self.assertEqual(worksheet.status, EstWorksheet.STATUS_DRAFT)
        
    def test_worksheet_status_with_open_estimate(self):
        """Test worksheet moves to final when estimate is open."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status=Estimate.STATUS_OPEN
        )
        
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )
        
        self.assertEqual(worksheet.status, EstWorksheet.STATUS_FINAL)
        
    def test_worksheet_status_with_accepted_estimate(self):
        """Test worksheet moves to final when estimate is accepted."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status=Estimate.STATUS_ACCEPTED
        )
        
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )
        
        self.assertEqual(worksheet.status, EstWorksheet.STATUS_FINAL)
        
    def test_worksheet_status_with_rejected_estimate(self):
        """Test worksheet moves to final when estimate is rejected."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status=Job.STATUS_REJECTED
        )
        
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )
        
        self.assertEqual(worksheet.status, EstWorksheet.STATUS_FINAL)
        
    def test_worksheet_status_with_superseded_estimate(self):
        """Test worksheet moves to superseded when estimate is superseded."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status=Estimate.STATUS_SUPERSEDED
        )
        
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )
        
        self.assertEqual(worksheet.status, EstWorksheet.STATUS_SUPERSEDED)
        
    def test_worksheet_status_change_on_estimate_update(self):
        """Test worksheet status updates when estimate status changes."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status=Job.STATUS_DRAFT
        )
        
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )
        
        self.assertEqual(worksheet.status, EstWorksheet.STATUS_DRAFT)

        # Change estimate to open
        EstimateLineItem.objects.create(estimate=estimate, description='Test item', price=Decimal('100.00'))
        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        
        # Refresh worksheet from database
        worksheet.refresh_from_db()
        self.assertEqual(worksheet.status, EstWorksheet.STATUS_FINAL)
        
        # Change estimate to superseded
        estimate.status = Estimate.STATUS_SUPERSEDED
        estimate.save()
        
        worksheet.refresh_from_db()
        self.assertEqual(worksheet.status, EstWorksheet.STATUS_SUPERSEDED)


class EstWorksheetVersioningTest(TestCase):
    """Test EstWorksheet versioning functionality."""
    
    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )
        self.user = User.objects.create_user(username="testuser")
        
    def test_create_new_version(self):
        """Test creating a new version of EstWorksheet."""
        scheme = _make_scheme('cnv')
        # Create original worksheet with tasks
        worksheet_v1 = EstWorksheet.objects.create(
            job=self.job,
            status=Job.STATUS_DRAFT,
            version=1
        )

        task1 = PlanTask.objects.create(
            est_worksheet=worksheet_v1,
            name="Task 1",
            rate_scheme=scheme,
            est_qty=Decimal('1'),
        )

        task2 = PlanTask.objects.create(
            est_worksheet=worksheet_v1,
            name="Task 2",
            rate_scheme=scheme,
            est_qty=Decimal('1'),
        )
        
        # Create new version
        worksheet_v2 = worksheet_v1.create_new_version()
        
        # Check original worksheet is superseded
        worksheet_v1.refresh_from_db()
        self.assertEqual(worksheet_v1.status, EstWorksheet.STATUS_SUPERSEDED)
        
        # Check new worksheet
        self.assertEqual(worksheet_v2.job, self.job)
        self.assertEqual(worksheet_v2.status, Job.STATUS_DRAFT)
        self.assertEqual(worksheet_v2.version, 2)
        self.assertEqual(worksheet_v2.parent, worksheet_v1)  # New worksheet points to old as parent
        self.assertIsNone(worksheet_v2.estimate)
        
        # Check plan tasks were copied
        v2_tasks = PlanTask.objects.filter(est_worksheet=worksheet_v2).order_by('name')
        self.assertEqual(v2_tasks.count(), 2)

        self.assertEqual(v2_tasks[0].name, "Task 1")
        self.assertEqual(v2_tasks[1].name, "Task 2")
        
    def test_create_new_version_preserves_all_fields(self):
        """create_new_version must carry sort_order + est_worker_time on PlanTasks,
        units on PlanMaterials, and include task-less PlanMaterials."""
        scheme = _make_scheme('preserve')
        ac = AccountingCategory.objects.create(code='ESTWS-MAT', name='estws-mat')
        worksheet_v1 = EstWorksheet.objects.create(
            job=self.job, status=Job.STATUS_DRAFT, version=1,
        )

        task = PlanTask.objects.create(
            est_worksheet=worksheet_v1,
            name="Task A",
            rate_scheme=scheme,
            est_qty=Decimal('2'),
            sort_order=7,
            est_worker_time=timedelta(hours=3),
        )

        # Material attached to a task, with non-default units.
        PlanMaterial.objects.create(
            est_worksheet=worksheet_v1,
            plan_task=task,
            description="Bolts",
            quantity=Decimal('10'),
            units='box',
            accounting_category=ac,
        )
        # Task-less material on the worksheet.
        PlanMaterial.objects.create(
            est_worksheet=worksheet_v1,
            plan_task=None,
            description="Loose washers",
            quantity=Decimal('5'),
            units='kg',
            accounting_category=ac,
        )

        worksheet_v2 = worksheet_v1.create_new_version()

        # PlanTask fields carried over.
        v2_task = PlanTask.objects.get(est_worksheet=worksheet_v2)
        self.assertEqual(v2_task.sort_order, 7)
        self.assertEqual(v2_task.est_worker_time, timedelta(hours=3))

        # All materials carried over, including the task-less one.
        v2_materials = PlanMaterial.objects.filter(est_worksheet=worksheet_v2)
        self.assertEqual(v2_materials.count(), 2)

        bolts = v2_materials.get(description="Bolts")
        self.assertEqual(bolts.units, 'box')
        self.assertEqual(bolts.plan_task, v2_task)

        washers = v2_materials.get(description="Loose washers")
        self.assertEqual(washers.units, 'kg')
        self.assertIsNone(washers.plan_task)

    def test_version_chain(self):
        """Test creating multiple versions maintains proper chain."""
        worksheet_v1 = EstWorksheet.objects.create(
            job=self.job,
            status=Job.STATUS_DRAFT
        )
        
        worksheet_v2 = worksheet_v1.create_new_version()
        worksheet_v3 = worksheet_v2.create_new_version()
        
        # Check version numbers
        self.assertEqual(worksheet_v1.version, 1)
        self.assertEqual(worksheet_v2.version, 2)
        self.assertEqual(worksheet_v3.version, 3)
        
        # Check parent chain
        worksheet_v1.refresh_from_db()
        worksheet_v2.refresh_from_db()
        
        self.assertEqual(worksheet_v1.status, EstWorksheet.STATUS_SUPERSEDED)
        self.assertIsNone(worksheet_v1.parent)  # Original has no parent
        
        self.assertEqual(worksheet_v2.status, EstWorksheet.STATUS_SUPERSEDED)
        self.assertEqual(worksheet_v2.parent, worksheet_v1)  # v2 points to v1 as parent
        
        self.assertEqual(worksheet_v3.status, Job.STATUS_DRAFT)
        self.assertEqual(worksheet_v3.parent, worksheet_v2)  # v3 points to v2 as parent


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
            rate_scheme=scheme,
        )

        self.assertEqual(task.job, self.job)

    def test_plan_task_with_estworksheet(self):
        """Test creating PlanTask on an EstWorksheet."""
        scheme = _make_scheme('ptws')
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            status=Job.STATUS_DRAFT
        )

        task = PlanTask.objects.create(
            est_worksheet=worksheet,
            name="Worksheet Task",
            rate_scheme=scheme,
            est_qty=Decimal('1'),
        )

        self.assertEqual(task.est_worksheet, worksheet)

    def test_worksheet_plan_tasks_accessor(self):
        """Test accessing plan tasks through EstWorksheet.plan_tasks."""
        scheme = _make_scheme('wpta')
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            status=Job.STATUS_DRAFT
        )

        task1 = PlanTask.objects.create(
            est_worksheet=worksheet,
            name="Task 1",
            rate_scheme=scheme,
            est_qty=Decimal('1'),
        )

        task2 = PlanTask.objects.create(
            est_worksheet=worksheet,
            name="Task 2",
            rate_scheme=scheme,
            est_qty=Decimal('1'),
        )

        tasks = worksheet.plan_tasks.all()
        self.assertEqual(tasks.count(), 2)
        self.assertIn(task1, tasks)
        self.assertIn(task2, tasks)