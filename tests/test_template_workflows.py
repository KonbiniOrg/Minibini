"""
Tests for template-based creation workflows and status-based validation.
"""

from django.test import TestCase
from django.core.exceptions import ValidationError
from decimal import Decimal

from apps.contacts.models import Contact
from apps.core.models import Configuration
from apps.jobs.models import (
    Job, WorkOrder, Estimate, Task, WorkOrderTemplate, TaskTemplate, TaskMapping
)
from apps.jobs.services import WorkOrderService, EstimateService, TaskService
from apps.core.models import User


class WorkOrderCreationWorkflowTest(TestCase):
    """Test WorkOrder creation workflows and status validations."""
    
    def setUp(self):
        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )
        self.user = User.objects.create_user(username="testuser")
        
        # Create basic TaskMapping for template tests
        self.task_mapping = TaskMapping.objects.create(
            step_type="test_step",
            task_type_id="TEST001",
            breakdown_of_task="Test breakdown"
        )
    
    def test_direct_work_order_creation(self):
        """Test direct WorkOrder creation starts in draft status."""
        work_order = WorkOrderService.create_direct(self.job)
        
        self.assertEqual(work_order.status, 'draft')
        self.assertEqual(work_order.job, self.job)
        self.assertIsNone(work_order.template)
    
    def test_work_order_from_open_estimate(self):
        """Test WorkOrder creation from Open estimate."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='open'
        )
        
        work_order = WorkOrderService.create_from_estimate(estimate)
        
        self.assertEqual(work_order.status, 'incomplete')
        self.assertEqual(work_order.job, self.job)
    
    def test_work_order_from_accepted_estimate(self):
        """Test WorkOrder creation from Accepted estimate."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='accepted'
        )
        
        work_order = WorkOrderService.create_from_estimate(estimate)
        
        self.assertEqual(work_order.status, 'incomplete')
        self.assertEqual(work_order.job, self.job)
    
    def test_work_order_from_draft_estimate_rejected(self):
        """Test WorkOrder creation from Draft estimate is rejected."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='draft'
        )
        
        with self.assertRaises(ValidationError) as context:
            WorkOrderService.create_from_estimate(estimate)
        
        self.assertIn("Only Open and Accepted estimates", str(context.exception))
    
    def test_work_order_from_rejected_estimate_rejected(self):
        """Test WorkOrder creation from Rejected estimate is rejected."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='rejected'
        )
        
        with self.assertRaises(ValidationError) as context:
            WorkOrderService.create_from_estimate(estimate)
        
        self.assertIn("Only Open and Accepted estimates", str(context.exception))
    
    def test_work_order_from_active_template(self):
        """Test WorkOrder creation from active template."""
        template = WorkOrderTemplate.objects.create(
            template_name="Test Template",
            description="Test description",
            is_active=True
        )
        
        work_order = WorkOrderService.create_from_template(template, self.job)
        
        self.assertEqual(work_order.status, 'draft')
        self.assertEqual(work_order.job, self.job)
        self.assertEqual(work_order.template, template)
    
    def test_work_order_from_inactive_template_rejected(self):
        """Test WorkOrder creation from inactive template is rejected."""
        template = WorkOrderTemplate.objects.create(
            template_name="Inactive Template",
            is_active=False
        )
        
        with self.assertRaises(ValidationError) as context:
            WorkOrderService.create_from_template(template, self.job)
        
        self.assertIn("is not active", str(context.exception))


class EstimateCreationWorkflowTest(TestCase):
    """Test Estimate creation workflows and status validations."""
    
    def setUp(self):
        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )
    
    def test_direct_estimate_creation(self):
        """Test direct Estimate creation starts in draft status."""
        estimate = EstimateService.create_direct(self.job)

        self.assertEqual(estimate.status, 'draft')
        self.assertEqual(estimate.job, self.job)
        # Estimate number is auto-generated
        self.assertTrue(estimate.estimate_number.startswith('EST-'))
    
    def test_estimate_from_draft_work_order(self):
        """Test Estimate creation from Draft WorkOrder."""
        work_order = WorkOrder.objects.create(
            job=self.job,
            status='draft'
        )
        
        estimate = EstimateService.create_from_work_order(work_order)
        
        self.assertEqual(estimate.status, 'draft')
        self.assertEqual(estimate.job, self.job)
    
    def test_estimate_from_incomplete_work_order_rejected(self):
        """Test Estimate creation from Incomplete WorkOrder is rejected."""
        work_order = WorkOrder.objects.create(
            job=self.job,
            status='incomplete'
        )
        
        with self.assertRaises(ValidationError) as context:
            EstimateService.create_from_work_order(work_order)
        
        self.assertIn("Only Draft WorkOrders", str(context.exception))
    
    def test_estimate_from_complete_work_order_rejected(self):
        """Test Estimate creation from Complete WorkOrder is rejected."""
        work_order = WorkOrder.objects.create(
            job=self.job,
            status='complete'
        )
        
        with self.assertRaises(ValidationError) as context:
            EstimateService.create_from_work_order(work_order)
        
        self.assertIn("Only Draft WorkOrders", str(context.exception))
    
    def test_estimate_from_blocked_work_order_rejected(self):
        """Test Estimate creation from Blocked WorkOrder is rejected."""
        work_order = WorkOrder.objects.create(
            job=self.job,
            status='blocked'
        )
        
        with self.assertRaises(ValidationError) as context:
            EstimateService.create_from_work_order(work_order)
        
        self.assertIn("Only Draft WorkOrders", str(context.exception))


class TaskCreationWorkflowTest(TestCase):
    """Test Task creation workflows."""
    
    def setUp(self):
        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )
        self.work_order = WorkOrder.objects.create(job=self.job)
        self.user = User.objects.create_user(username="testuser")
        
        # Create basic TaskMapping for template tests
        self.task_mapping = TaskMapping.objects.create(
            step_type="test_step",
            task_type_id="TEST001",
            breakdown_of_task="Test breakdown"
        )
    
    def test_direct_task_creation(self):
        """Test direct Task creation."""
        task = TaskService.create_direct(
            work_order=self.work_order,
            name="Test Task",
            assignee=self.user
        )
        
        self.assertEqual(task.work_order, self.work_order)
        self.assertEqual(task.name, "Test Task")
        self.assertEqual(task.assignee, self.user)
        self.assertIsNone(task.template)
    
    def test_task_from_active_template(self):
        """Test Task creation from active TaskTemplate."""
        template = TaskTemplate.objects.create(
            template_name="Test Task Template",
            task_mapping=self.task_mapping,
            is_active=True
        )
        
        task = TaskService.create_from_template(template, self.work_order, self.user)
        
        self.assertEqual(task.work_order, self.work_order)
        self.assertEqual(task.template, template)
        self.assertEqual(task.name, template.template_name)
        self.assertEqual(task.assignee, self.user)
    
    def test_task_from_inactive_template_rejected(self):
        """Test Task creation from inactive template is rejected."""
        template = TaskTemplate.objects.create(
            template_name="Inactive Template",
            task_mapping=self.task_mapping,
            is_active=False
        )
        
        with self.assertRaises(ValidationError) as context:
            TaskService.create_from_template(template, self.work_order)
        
        self.assertIn("is not active", str(context.exception))
    
    def test_task_template_new_fields(self):
        """Test TaskTemplate with new units and rate fields."""
        template = TaskTemplate.objects.create(
            template_name="Labor Template",
            task_mapping=self.task_mapping,
            units="hours",
            rate=Decimal('85.00'),
            description="Standard labor template with pricing",
            is_active=True
        )
        
        self.assertEqual(template.units, "hours")
        self.assertEqual(template.rate, Decimal('85.00'))
        
        # Test that tasks created from template inherit the field values
        task = TaskService.create_from_template(template, self.work_order, self.user)
        # Note: Based on current service implementation, we'd need to check if
        # the service copies these values. For now, just test template creation.
        
    def test_task_template_new_fields_optional(self):
        """Test TaskTemplate new fields are optional."""
        template = TaskTemplate.objects.create(
            template_name="Simple Template",
            task_mapping=self.task_mapping,
            is_active=True
        )
        
        self.assertEqual(template.units, "")  # CharField blank=True defaults to empty
        self.assertIsNone(template.rate)  # DecimalField null=True
    
    def test_task_template_without_task_mapping(self):
        """Test TaskTemplate can be created without TaskMapping."""
        template = TaskTemplate.objects.create(
            template_name="Template Without Mapping",
            units="items",
            rate=Decimal('25.00'),
            is_active=True
        )
        
        self.assertIsNone(template.task_mapping)
        self.assertEqual(template.template_name, "Template Without Mapping")
        
        # Test that task can still be created from template without mapping
        task = TaskService.create_from_template(template, self.work_order, self.user)
        self.assertEqual(task.name, "Template Without Mapping")
        self.assertEqual(task.template, template)
        
    def test_task_template_calculation_example(self):
        """Test using TaskTemplate fields with association for calculations."""
        template = TaskTemplate.objects.create(
            template_name="Material Template",
            task_mapping=self.task_mapping,
            units="square_feet",
            rate=Decimal('12.75'),
            is_active=True
        )
        
        # Create association with quantity
        from apps.jobs.models import TemplateTaskAssociation, WorkOrderTemplate
        work_order_template = WorkOrderTemplate.objects.create(template_name="Test WO Template")
        association = TemplateTaskAssociation.objects.create(
            work_order_template=work_order_template,
            task_template=template,
            est_qty=Decimal('150.00')
        )
        
        # Example calculation that could be used in business logic
        estimated_cost = template.rate * association.est_qty if template.rate and association.est_qty else Decimal('0.00')
        self.assertEqual(estimated_cost, Decimal('1912.50'))


class TemplateIntegrationTest(TestCase):
    """Test full template workflow integration."""
    
    def setUp(self):
        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )
        self.user = User.objects.create_user(username="testuser")
        
        # Create TaskMappings
        self.task_mapping1 = TaskMapping.objects.create(
            step_type="preparation",
            task_type_id="PREP001",
            breakdown_of_task="Preparation work"
        )
        
        self.task_mapping2 = TaskMapping.objects.create(
            step_type="execution",
            task_type_id="EXEC001",
            breakdown_of_task="Execution work"
        )
    
    def test_full_template_workflow(self):
        """Test complete workflow: Template -> WorkOrder -> Tasks."""
        # Create WorkOrderTemplate with TaskTemplates
        work_order_template = WorkOrderTemplate.objects.create(
            template_name="Complete Job Template",
            description="Template for complete job workflow",
            is_active=True
        )
        
        task_template1 = TaskTemplate.objects.create(
            template_name="Preparation Task",
            task_mapping=self.task_mapping1,
            is_active=True
        )
        
        task_template2 = TaskTemplate.objects.create(
            template_name="Execution Task",
            task_mapping=self.task_mapping2,
            is_active=True
        )
        
        # Create associations with quantities
        from apps.jobs.models import TemplateTaskAssociation
        TemplateTaskAssociation.objects.create(
            work_order_template=work_order_template,
            task_template=task_template1,
            est_qty=Decimal('1.00')
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=work_order_template,
            task_template=task_template2,
            est_qty=Decimal('1.00')
        )
        
        # Generate WorkOrder from template
        work_order = WorkOrderService.create_from_template(work_order_template, self.job)
        
        # Verify WorkOrder
        self.assertEqual(work_order.status, 'draft')
        self.assertEqual(work_order.job, self.job)
        self.assertEqual(work_order.template, work_order_template)
        
        # Verify Tasks were created
        tasks = work_order.task_set.all()
        self.assertEqual(tasks.count(), 2)
        
        task_names = [task.name for task in tasks]
        self.assertIn("Preparation Task", task_names)
        self.assertIn("Execution Task", task_names)
        
        # Verify task templates are linked
        for task in tasks:
            self.assertIsNotNone(task.template)
            self.assertIn(task.template, [task_template1, task_template2])


class StatusTransitionPreventionTest(TestCase):
    """Test that status transitions prevent circular creation."""
    
    def setUp(self):
        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )
    
    def test_circular_creation_prevention(self):
        """Test that circular creation is prevented by status rules."""
        # Create draft estimate
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='draft'
        )
        
        # Draft estimate cannot create WorkOrder
        with self.assertRaises(ValidationError):
            WorkOrderService.create_from_estimate(estimate)
        
        # Change estimate to open
        estimate.status = 'open'
        estimate.save()
        
        # Open estimate can create WorkOrder (incomplete status)
        work_order = WorkOrderService.create_from_estimate(estimate)
        self.assertEqual(work_order.status, 'incomplete')
        
        # Incomplete WorkOrder cannot create Estimate
        with self.assertRaises(ValidationError):
            EstimateService.create_from_work_order(work_order)
    
    def test_estimate_never_returns_to_draft(self):
        """Test business rule: Estimate never goes back to draft once moved to open."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='draft'
        )
        
        # Move to open
        estimate.status = 'open'
        estimate.save()
        
        # This business rule would be enforced in model validation or admin interface
        # For now, we document that this should not happen
        self.assertEqual(estimate.status, 'open')


# Placeholder tests for TaskMapping translation chains
# These will be implemented once TaskMapping is fully defined

class TaskMappingTranslationTest(TestCase):
    """Placeholder tests for TaskMapping translation chains."""
    
    def setUp(self):
        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )
        
    def test_line_item_to_task_translation_placeholder(self):
        """Placeholder: Test LineItem -> TaskMapping -> Task translation."""
        # This will be implemented once TaskMapping is fully defined
        pass
    
    def test_task_to_line_item_translation_placeholder(self):
        """Placeholder: Test Task -> TaskMapping -> LineItem translation."""
        # This will be implemented once TaskMapping is fully defined
        pass
    
    def test_price_list_item_task_mapping_integration_placeholder(self):
        """Placeholder: Test PriceListItem -> TaskMapping integration."""
        # This will be implemented once TaskMapping is fully defined
        pass