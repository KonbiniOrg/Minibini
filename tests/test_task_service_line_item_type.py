"""Tests for TaskService.create_line_item_from_task line_item_type handling."""

from django.test import TestCase
from decimal import Decimal

from apps.jobs.models import (
    Job, Estimate, Task, WorkOrder, TaskMapping, TaskTemplate
)
from apps.jobs.services import TaskService
from apps.contacts.models import Contact
from apps.core.models import LineItemType


class TestCreateLineItemFromTaskLineItemType(TestCase):
    """Test that create_line_item_from_task properly sets line_item_type."""

    def setUp(self):
        """Set up test data."""
        self.contact = Contact.objects.create(
            first_name='Test',
            last_name='Contact',
            email='test@example.com'
        )
        self.job = Job.objects.create(
            job_number='TEST-001',
            contact=self.contact
        )
        self.estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-001',
            version=1,
            status='draft'
        )
        self.work_order = WorkOrder.objects.create(
            job=self.job,
            status='draft'
        )

        # Get or create a LineItemType
        self.service_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )

    def test_line_item_type_from_task_mapping(self):
        """Test that line_item_type is set from task's template mapping."""
        # Create a TaskMapping with output_line_item_type
        mapping = TaskMapping.objects.create(
            task_type_id='TEST-MAPPING',
            step_type='labor',
            mapping_strategy='direct',
            output_line_item_type=self.service_type
        )

        # Create a TaskTemplate linked to the mapping
        template = TaskTemplate.objects.create(
            template_name='Test Template',
            task_mapping=mapping,
            units='hours',
            rate=Decimal('50.00')
        )

        # Create a Task with the template
        task = Task.objects.create(
            work_order=self.work_order,
            name='Test Task',
            template=template,
            units='hours',
            rate=Decimal('50.00'),
            est_qty=Decimal('2.00')
        )

        # Create line item from task
        line_item = TaskService.create_line_item_from_task(task, self.estimate)

        # Verify line_item_type was set from mapping
        self.assertEqual(line_item.line_item_type, self.service_type)

    def test_line_item_without_template_gets_default_type(self):
        """Test that tasks without templates get a default line_item_type."""
        # Create a Task without a template
        task = Task.objects.create(
            work_order=self.work_order,
            name='Manual Task',
            units='hours',
            rate=Decimal('25.00'),
            est_qty=Decimal('1.00')
        )

        # Create line item from task
        line_item = TaskService.create_line_item_from_task(task, self.estimate)

        # Should have SOME line_item_type (not None) - the default
        self.assertIsNotNone(line_item.line_item_type)
