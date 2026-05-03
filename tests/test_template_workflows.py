"""
Tests for template-based creation workflows and status-based validation.

After WorkOrder removal, WorkOrderService is gone; Tasks are created directly
against a Job. These tests cover the surviving Task/Template workflows.
"""

from django.test import TestCase
from django.core.exceptions import ValidationError
from decimal import Decimal

from apps.contacts.models import Contact
from apps.core.models import Configuration, AccountingCategory
from apps.jobs.models import Job, Task, RateScheme
from apps.estimates.models import Estimate, EstimateLineItem, WorkTemplate, TaskTemplate
from apps.jobs.services import TaskService
from apps.estimates.services import EstimateService
from apps.core.models import User


def _seed_numbering():
    Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
    Configuration.objects.create(key='job_counter', value='0')
    Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
    Configuration.objects.create(key='estimate_counter', value='0')
    Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
    Configuration.objects.create(key='invoice_counter', value='0')
    Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
    Configuration.objects.create(key='po_counter', value='0')


class EstimateCreationWorkflowTest(TestCase):
    """Test Estimate creation workflows and status validations."""

    def setUp(self):
        _seed_numbering()
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )

    def test_direct_estimate_creation(self):
        """Test direct Estimate creation starts in draft status."""
        estimate = EstimateService.create_direct(self.job)

        self.assertEqual(estimate.status, Estimate.STATUS_DRAFT)
        self.assertEqual(estimate.job, self.job)
        self.assertTrue(estimate.estimate_number.startswith('EST-'))


class TaskCreationWorkflowTest(TestCase):
    """Test Task creation workflows against a Job."""

    def setUp(self):
        _seed_numbering()
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )
        self.user = User.objects.create_user(username="testuser")
        self.ac = AccountingCategory.objects.create(code='X-tw', name='X-tw')
        self.scheme = RateScheme.objects.create(
            name='S-tw', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )

    def test_direct_task_creation(self):
        """Test direct Task creation on a Job."""
        task = TaskService.create_direct(
            job=self.job,
            name="Test Task",
            assignee=self.user,
            rate_scheme_id=self.scheme.pk,
        )

        self.assertEqual(task.job, self.job)
        self.assertEqual(task.name, "Test Task")
        self.assertEqual(task.assignee, self.user)

    def test_task_from_active_template(self):
        """Test Task creation from active TaskTemplate."""
        template = TaskTemplate.objects.create(
            template_name="Test Task Template",
            rate_scheme=self.scheme,
            default_billable_qty=Decimal('1.00'),
            is_active=True
        )

        task = TaskService.create_from_template(template, self.job, self.user)

        self.assertEqual(task.job, self.job)
        self.assertEqual(task.name, template.template_name)
        self.assertEqual(task.assignee, self.user)

    def test_task_from_inactive_template_rejected(self):
        """Test Task creation from inactive template is rejected."""
        template = TaskTemplate.objects.create(
            template_name="Inactive Template",
            rate_scheme=self.scheme,
            default_billable_qty=Decimal('1.00'),
            is_active=False
        )

        with self.assertRaises(ValidationError) as context:
            TaskService.create_from_template(template, self.job)

        self.assertIn("is not active", str(context.exception))

    def test_task_template_new_fields(self):
        """Test TaskTemplate with new units and rate fields."""
        template = TaskTemplate.objects.create(
            template_name="Labor Template",
            units="hours",
            rate=Decimal('85.00'),
            rate_scheme=self.scheme,
            default_billable_qty=Decimal('1.00'),
            description="Standard labor template with pricing",
            is_active=True
        )

        self.assertEqual(template.units, "hours")
        self.assertEqual(template.rate, Decimal('85.00'))

        # Sanity check: can create task from this template
        TaskService.create_from_template(template, self.job, self.user)

    def test_task_template_new_fields_optional(self):
        """Test TaskTemplate new fields are optional."""
        template = TaskTemplate.objects.create(
            template_name="Simple Template",
            rate_scheme=self.scheme,
            default_billable_qty=Decimal('1.00'),
            is_active=True
        )

        self.assertEqual(template.units, "none")
        self.assertIsNone(template.rate)

    def test_task_template_calculation_example(self):
        """Test using TaskTemplate fields with association for calculations."""
        template = TaskTemplate.objects.create(
            template_name="Material Template",
            units="sq ft",
            rate=Decimal('12.75'),
            rate_scheme=self.scheme,
            default_billable_qty=Decimal('1.00'),
            is_active=True
        )

        from apps.estimates.models import TemplateTaskAssociation, WorkTemplate
        work_template = WorkTemplate.objects.create(template_name="Test WO Template")
        association = TemplateTaskAssociation.objects.create(
            work_template=work_template,
            task_template=template,
            est_qty=Decimal('150.00')
        )

        estimated_cost = template.rate * association.est_qty if template.rate and association.est_qty else Decimal('0.00')
        self.assertEqual(estimated_cost, Decimal('1912.50'))
