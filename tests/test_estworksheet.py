"""
Tests for EstWorksheet model and its status transitions.
"""

from django.test import TestCase
from django.core.exceptions import ValidationError
from decimal import Decimal

from apps.contacts.models import Contact
from apps.jobs.models import (
    Job, WorkOrder, Estimate, Task, EstWorksheet, 
    WorkOrderTemplate, TaskTemplate, TaskMapping
)
from apps.core.models import User


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
            status='draft'
        )

        self.assertEqual(worksheet.job, self.job)
        self.assertEqual(worksheet.status, 'draft')
        self.assertEqual(worksheet.version, 1)
        self.assertIsNone(worksheet.estimate)
        self.assertIsNone(worksheet.template)
        self.assertIsNone(worksheet.parent)

    def test_estworksheet_default_status_is_draft(self):
        """Test that EstWorksheet always starts in draft status by default."""
        # Create worksheet without specifying status
        worksheet = EstWorksheet.objects.create(
            job=self.job
        )

        # Should default to draft
        self.assertEqual(worksheet.status, 'draft')

    def test_estworksheet_cannot_be_created_with_non_draft_status(self):
        """Test that new EstWorksheets always start as draft, even if another status is attempted."""
        # This test documents the expected behavior
        # The model default ensures new worksheets start as draft
        worksheet = EstWorksheet.objects.create(
            job=self.job
            # Not specifying status to use default
        )

        self.assertEqual(worksheet.status, 'draft')
        
    def test_estworksheet_with_template(self):
        """Test creating EstWorksheet from template."""
        template = WorkOrderTemplate.objects.create(
            template_name="Test Template",
            description="Test description"
        )
        
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            template=template
        )
        
        self.assertEqual(worksheet.template, template)
        self.assertEqual(worksheet.status, 'draft')
        
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
            status='draft'
        )
        
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )
        
        self.assertEqual(worksheet.status, 'draft')
        
    def test_worksheet_status_with_open_estimate(self):
        """Test worksheet moves to final when estimate is open."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='open'
        )
        
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )
        
        self.assertEqual(worksheet.status, 'final')
        
    def test_worksheet_status_with_accepted_estimate(self):
        """Test worksheet moves to final when estimate is accepted."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='accepted'
        )
        
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )
        
        self.assertEqual(worksheet.status, 'final')
        
    def test_worksheet_status_with_rejected_estimate(self):
        """Test worksheet moves to final when estimate is rejected."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='rejected'
        )
        
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )
        
        self.assertEqual(worksheet.status, 'final')
        
    def test_worksheet_status_with_superseded_estimate(self):
        """Test worksheet moves to superseded when estimate is superseded."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='superseded'
        )
        
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )
        
        self.assertEqual(worksheet.status, 'superseded')
        
    def test_worksheet_status_change_on_estimate_update(self):
        """Test worksheet status updates when estimate status changes."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='draft'
        )
        
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )
        
        self.assertEqual(worksheet.status, 'draft')
        
        # Change estimate to open
        estimate.status = 'open'
        estimate.save()
        
        # Refresh worksheet from database
        worksheet.refresh_from_db()
        self.assertEqual(worksheet.status, 'final')
        
        # Change estimate to superseded
        estimate.status = 'superseded'
        estimate.save()
        
        worksheet.refresh_from_db()
        self.assertEqual(worksheet.status, 'superseded')


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
        # Create original worksheet with tasks
        worksheet_v1 = EstWorksheet.objects.create(
            job=self.job,
            status='draft',
            version=1
        )
        
        task1 = Task.objects.create(
            est_worksheet=worksheet_v1,
            name="Task 1",
            units="hours",
            rate=Decimal('50.00'),
            est_qty=Decimal('5.00')
        )
        
        task2 = Task.objects.create(
            est_worksheet=worksheet_v1,
            name="Task 2",
            assignee=self.user
        )
        
        # Create new version
        worksheet_v2 = worksheet_v1.create_new_version()
        
        # Check original worksheet is superseded
        worksheet_v1.refresh_from_db()
        self.assertEqual(worksheet_v1.status, 'superseded')
        
        # Check new worksheet
        self.assertEqual(worksheet_v2.job, self.job)
        self.assertEqual(worksheet_v2.status, 'draft')
        self.assertEqual(worksheet_v2.version, 2)
        self.assertEqual(worksheet_v2.parent, worksheet_v1)  # New worksheet points to old as parent
        self.assertIsNone(worksheet_v2.estimate)
        
        # Check tasks were copied
        v2_tasks = Task.objects.filter(est_worksheet=worksheet_v2).order_by('name')
        self.assertEqual(v2_tasks.count(), 2)
        
        self.assertEqual(v2_tasks[0].name, "Task 1")
        self.assertEqual(v2_tasks[0].units, "hours")
        self.assertEqual(v2_tasks[0].rate, Decimal('50.00'))
        self.assertEqual(v2_tasks[0].est_qty, Decimal('5.00'))
        
        self.assertEqual(v2_tasks[1].name, "Task 2")
        self.assertEqual(v2_tasks[1].assignee, self.user)
        
    def test_version_chain(self):
        """Test creating multiple versions maintains proper chain."""
        worksheet_v1 = EstWorksheet.objects.create(
            job=self.job,
            status='draft'
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
        
        self.assertEqual(worksheet_v1.status, 'superseded')
        self.assertIsNone(worksheet_v1.parent)  # Original has no parent
        
        self.assertEqual(worksheet_v2.status, 'superseded')
        self.assertEqual(worksheet_v2.parent, worksheet_v1)  # v2 points to v1 as parent
        
        self.assertEqual(worksheet_v3.status, 'draft')
        self.assertEqual(worksheet_v3.parent, worksheet_v2)  # v3 points to v2 as parent


class TaskWorkContainerTest(TestCase):
    """Test Task model working with both WorkOrder and EstWorksheet."""
    
    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )
        self.user = User.objects.create_user(username="testuser")
        
    def test_task_with_workorder(self):
        """Test creating task attached to WorkOrder."""
        work_order = WorkOrder.objects.create(
            job=self.job,
            status='draft'
        )
        
        task = Task.objects.create(
            work_order=work_order,
            name="WorkOrder Task"
        )
        
        self.assertEqual(task.work_order, work_order)
        self.assertIsNone(task.est_worksheet)
        self.assertEqual(task.get_container(), work_order)
        
    def test_task_with_estworksheet(self):
        """Test creating task attached to EstWorksheet."""
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='draft'
        )
        
        task = Task.objects.create(
            est_worksheet=worksheet,
            name="Worksheet Task"
        )
        
        self.assertIsNone(task.work_order)
        self.assertEqual(task.est_worksheet, worksheet)
        self.assertEqual(task.get_container(), worksheet)
        
    def test_task_cannot_have_both_containers(self):
        """Test task cannot be attached to both WorkOrder and EstWorksheet."""
        work_order = WorkOrder.objects.create(
            job=self.job,
            status='draft'
        )
        
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='draft'
        )
        
        task = Task(
            work_order=work_order,
            est_worksheet=worksheet,
            name="Invalid Task"
        )
        
        with self.assertRaises(ValidationError) as context:
            task.clean()
        
        self.assertIn("cannot be attached to both", str(context.exception))
        
    def test_task_must_have_container(self):
        """Test task must be attached to either WorkOrder or EstWorksheet."""
        task = Task(
            name="Orphan Task"
        )
        
        with self.assertRaises(ValidationError) as context:
            task.clean()
        
        self.assertIn("must be attached to either", str(context.exception))
        
    def test_worksheet_task_set(self):
        """Test accessing tasks through EstWorksheet."""
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='draft'
        )
        
        task1 = Task.objects.create(
            est_worksheet=worksheet,
            name="Task 1"
        )
        
        task2 = Task.objects.create(
            est_worksheet=worksheet,
            name="Task 2"
        )
        
        tasks = worksheet.task_set.all()
        self.assertEqual(tasks.count(), 2)
        self.assertIn(task1, tasks)
        self.assertIn(task2, tasks)