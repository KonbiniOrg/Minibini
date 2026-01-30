from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import timedelta
from decimal import Decimal
from apps.jobs.models import Job, Estimate, WorkOrder, Task, Blep, TaskMapping, WorkOrderTemplate, TaskTemplate
from apps.contacts.models import Contact
from apps.core.models import User


class JobModelTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')

    def test_job_creation(self):
        job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job description",
            status='draft'
        )
        self.assertEqual(job.job_number, "JOB001")
        self.assertEqual(job.contact, self.contact)
        self.assertEqual(job.description, "Test job description")
        self.assertEqual(job.status, 'draft')
        self.assertIsNotNone(job.created_date)

    def test_job_str_method(self):
        job = Job.objects.create(
            job_number="JOB002",
            contact=self.contact
        )
        self.assertEqual(str(job), "JOB002")

    def test_job_default_values(self):
        job = Job.objects.create(
            job_number="JOB003",
            contact=self.contact
        )
        self.assertEqual(job.status, 'draft')
        self.assertIsNone(job.completed_date)
        self.assertIsNone(job.due_date)

    def test_job_status_choices(self):
        statuses = ['draft', 'submitted', 'approved', 'rejected', 'completed', 'cancelled']
        for status in statuses:
            job = Job.objects.create(
                job_number=f"JOB_{status}",
                contact=self.contact,
                status=status
            )
            self.assertEqual(job.status, status)

    def test_job_with_completed_date(self):
        completion_time = timezone.now()
        job = Job.objects.create(
            job_number="JOB004",
            contact=self.contact,
            completed_date=completion_time,
            status='completed'
        )
        self.assertEqual(job.completed_date, completion_time)

    def test_job_creation_timestamp_is_current(self):
        """Test that a new Job is always created with a current timestamp"""
        before_creation = timezone.now()
        job = Job.objects.create(
            job_number="JOB_TIMESTAMP",
            contact=self.contact
        )
        after_creation = timezone.now()

        # Check that created_date is between the before and after times
        self.assertGreaterEqual(job.created_date, before_creation)
        self.assertLessEqual(job.created_date, after_creation)

    def test_job_default_status_is_draft(self):
        """Test that a new Job always starts in Draft state by default"""
        job = Job.objects.create(
            job_number="JOB_DEFAULT_STATUS",
            contact=self.contact
        )
        self.assertEqual(job.status, 'draft')

    def test_job_requires_contact(self):
        """Test that a Job must have a Contact associated with it"""
        # Attempting to create a job without a contact should fail
        with self.assertRaises(ValidationError):
            Job.objects.create(
                job_number="JOB_NO_CONTACT"
                # contact is deliberately missing
            )

    def test_job_contact_cannot_be_none(self):
        """Test that a Job's contact field cannot be None"""
        with self.assertRaises(ValidationError):
            Job.objects.create(
                job_number="JOB_NULL_CONTACT",
                contact=None
            )

    def test_job_minimal_creation_requirements(self):
        """Test that only job_number and contact are required for Job creation"""
        # This should succeed with just job_number and contact
        job = Job.objects.create(
            job_number="JOB_MINIMAL",
            contact=self.contact
        )

        # Verify defaults are applied
        self.assertEqual(job.status, 'draft')
        self.assertIsNotNone(job.created_date)
        self.assertIsNone(job.due_date)
        self.assertIsNone(job.completed_date)
        self.assertEqual(job.customer_po_number, '')
        self.assertEqual(job.description, '')

    def test_job_with_due_date(self):
        """Test that a Job can have an optional due date"""
        due_date = timezone.now() + timedelta(days=7)
        job = Job.objects.create(
            job_number="JOB_WITH_DUE",
            contact=self.contact,
            due_date=due_date
        )
        self.assertEqual(job.due_date, due_date)


class EstimateModelTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact
        )

    def test_estimate_creation(self):
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            version=2,
            status='open'
        )
        self.assertEqual(estimate.job, self.job)
        self.assertEqual(estimate.estimate_number, "EST001")
        self.assertEqual(estimate.version, 2)
        self.assertEqual(estimate.status, 'open')

    def test_estimate_str_method(self):
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST002"
        )
        self.assertEqual(str(estimate), "Estimate EST002")

    def test_estimate_defaults(self):
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST003"
        )
        self.assertEqual(estimate.version, 1)
        self.assertEqual(estimate.status, 'draft')

    def test_estimate_status_choices(self):
        statuses = ['draft', 'open', 'accepted', 'rejected']
        for status in statuses:
            estimate = Estimate.objects.create(
                job=self.job,
                estimate_number=f"EST_{status}",
                status=status
            )
            self.assertEqual(estimate.status, status)

    def test_estimate_superseded_sets_closed_date_not_superseded_date(self):
        """
        Test that when an estimate is superseded, closed_date is set.
        The field 'superseded_date' was renamed to 'closed_date' in migration 0014.
        Code should use 'closed_date', not the old 'superseded_date' field name.
        """
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST_SUPERSEDE_TEST",
            status='open'
        )

        # Verify the model doesn't have superseded_date as a DB field
        field_names = [f.name for f in Estimate._meta.get_fields()]
        self.assertNotIn('superseded_date', field_names,
            "Estimate model should not have 'superseded_date' field - it was renamed to 'closed_date'")
        self.assertIn('closed_date', field_names,
            "Estimate model should have 'closed_date' field")

        # Transition to superseded
        estimate.status = 'superseded'
        estimate.save()

        # Reload and verify closed_date is set
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, 'superseded')
        self.assertIsNotNone(estimate.closed_date,
            "closed_date should be set when estimate is superseded")


class WorkOrderModelTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact
        )
        self.work_order = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.work_order,
            name="Parent Task",
        )

    def test_work_order_creation(self):
        work_order = WorkOrder.objects.create(
            job=self.job,
            status='blocked',
        )
        self.assertEqual(work_order.job, self.job)
        self.assertEqual(work_order.status, 'blocked')

    def test_work_order_str_method(self):
        work_order = WorkOrder.objects.create(job=self.job)
        self.assertEqual(str(work_order), f"Work Order {work_order.pk}")

    def test_work_order_defaults(self):
        work_order = WorkOrder.objects.create(job=self.job)
        # when a WorkOrder is created based on an existing Estimate it will change to status 'incomplete' before saving
        self.assertEqual(work_order.status, 'draft')

    def test_work_order_status_choices(self):
        statuses = ['incomplete', 'blocked', 'complete']
        for status in statuses:
            work_order = WorkOrder.objects.create(
                job=self.job,
                status=status
            )
            self.assertEqual(work_order.status, status)


class TaskModelTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact
        )
        self.work_order = WorkOrder.objects.create(job=self.job)
        self.user = User.objects.create_user(username="testuser")

    def test_task_creation(self):
        parent_task = Task.objects.create(
            work_order=self.work_order,
            name="Parent Task",
        )
        task = Task.objects.create(
            parent_task=parent_task,
            assignee=self.user,
            work_order=self.work_order,
            name="Installation Task",
        )
        self.assertEqual(task.parent_task, parent_task)
        self.assertEqual(task.assignee, self.user)
        self.assertEqual(task.work_order, self.work_order)
        self.assertEqual(task.name, "Installation Task")

    def test_task_str_method(self):
        task = Task.objects.create(
            work_order=self.work_order,
            name="Test Task",
        )
        self.assertEqual(str(task), "Test Task")

    def test_task_optional_fields(self):
        task = Task.objects.create(
            work_order=self.work_order,
            name="Basic Task",
        )
        self.assertIsNone(task.parent_task)
        self.assertIsNone(task.assignee)

    def test_task_new_fields(self):
        """Test the new units, rate, and est_qty fields on Task."""
        task = Task.objects.create(
            work_order=self.work_order,
            name="Labor Task",
            units="hours",
            rate=Decimal('75.50'),
            est_qty=Decimal('8.00')
        )
        self.assertEqual(task.units, "hours")
        self.assertEqual(task.rate, Decimal('75.50'))
        self.assertEqual(task.est_qty, Decimal('8.00'))

    def test_task_new_fields_optional(self):
        """Test that new fields are optional on Task."""
        task = Task.objects.create(
            work_order=self.work_order,
            name="Simple Task"
        )
        self.assertEqual(task.units, "")  # CharField blank=True defaults to empty string
        self.assertIsNone(task.rate)  # DecimalField null=True
        self.assertIsNone(task.est_qty)  # DecimalField null=True

    def test_task_calculated_total(self):
        """Test calculating total from rate and est_qty."""
        task = Task.objects.create(
            work_order=self.work_order,
            name="Material Task",
            units="sheets",
            rate=Decimal('45.00'),
            est_qty=Decimal('10.00')
        )
        # While we don't have a calculated field, this tests the values can be used for calculations
        expected_total = task.rate * task.est_qty if task.rate and task.est_qty else Decimal('0.00')
        self.assertEqual(expected_total, Decimal('450.00'))


class BlepModelTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact
        )
        self.work_order = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.work_order,
            name="Test Task",
        )
        self.user = User.objects.create_user(username="testuser")

    def test_blep_creation(self):
        start_time = timezone.now()
        end_time = start_time + timedelta(hours=2)

        blep = Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=start_time,
            end_time=end_time
        )
        self.assertEqual(blep.user, self.user)
        self.assertEqual(blep.task, self.task)
        self.assertEqual(blep.start_time, start_time)
        self.assertEqual(blep.end_time, end_time)

    def test_blep_str_method(self):
        blep = Blep.objects.create(task=self.task)
        self.assertEqual(str(blep), f"Blep {blep.pk} for Task {self.task.pk}")

class TaskMappingModelTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact
        )
        self.work_order = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.work_order,
            name="Test Task",
        )

    def test_task_mapping_creation(self):
        mapping = TaskMapping.objects.create(
            step_type="labor",
            mapping_strategy="direct",
            task_type_id="PREP_001",
            breakdown_of_task="Detailed breakdown of preparation steps"
        )
        self.assertEqual(mapping.step_type, "labor")
        self.assertEqual(mapping.mapping_strategy, "direct")
        self.assertEqual(mapping.task_type_id, "PREP_001")
        self.assertEqual(mapping.breakdown_of_task, "Detailed breakdown of preparation steps")

    def test_task_mapping_str_method(self):
        mapping = TaskMapping.objects.create(
            step_type="labor",
            mapping_strategy="bundle_to_product",
            task_type_id="EXEC_001"
        )
        self.assertEqual(str(mapping), "EXEC_001 - ")

    def test_task_mapping_optional_breakdown(self):
        mapping = TaskMapping.objects.create(
            step_type="material",
            mapping_strategy="direct",
            task_type_id="COMP_001"
        )
        self.assertEqual(mapping.breakdown_of_task, "")

    def test_task_mapping_template_relationship(self):
        """Test TaskMapping used as template via TaskTemplate."""
        mapping = TaskMapping.objects.create(
            step_type="labor",
            mapping_strategy="direct",
            task_type_id="GEN_001",
            breakdown_of_task="General task mapping template"
        )

        template = TaskTemplate.objects.create(
            template_name="General Task Template",
            task_mapping=mapping
        )

        self.assertEqual(template.task_mapping, mapping)
        self.assertEqual(mapping.step_type, "labor")


class WorkOrderTemplateModelTest(TestCase):
    def test_work_order_template_creation(self):
        template = WorkOrderTemplate.objects.create(
            template_name="Standard Installation",
            description="Standard installation workflow template",
            is_active=True
        )
        self.assertEqual(template.template_name, "Standard Installation")
        self.assertEqual(template.description, "Standard installation workflow template")
        self.assertTrue(template.is_active)
        self.assertIsNotNone(template.created_date)

    def test_work_order_template_str_method(self):
        template = WorkOrderTemplate.objects.create(
            template_name="Maintenance Template"
        )
        self.assertEqual(str(template), "Maintenance Template")

    def test_work_order_template_defaults(self):
        template = WorkOrderTemplate.objects.create(
            template_name="Basic Template"
        )
        self.assertTrue(template.is_active)  # Default should be True
        self.assertEqual(template.description, "")  # CharField blank=True defaults to empty

    def test_work_order_template_inactive(self):
        template = WorkOrderTemplate.objects.create(
            template_name="Inactive Template",
            is_active=False
        )
        self.assertFalse(template.is_active)


class TaskTemplateModelTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact
        )
        self.work_order = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.work_order,
            name="Test Task",
        )
        self.task_mapping = TaskMapping.objects.create(
            step_type="labor",
            mapping_strategy="direct",
            task_type_id="TEST001"
        )
        self.work_order_template = WorkOrderTemplate.objects.create(
            template_name="Test WO Template"
        )

    def test_task_template_creation(self):
        template = TaskTemplate.objects.create(
            template_name="Electrical Installation",
            description="Standard electrical installation task",
            units="outlets",
            rate=Decimal('45.00'),
            task_mapping=self.task_mapping,
            is_active=True
        )

        # Create association with quantity
        from apps.jobs.models import TemplateTaskAssociation
        association = TemplateTaskAssociation.objects.create(
            work_order_template=self.work_order_template,
            task_template=template,
            est_qty=Decimal('12.00')
        )

        self.assertEqual(template.template_name, "Electrical Installation")
        self.assertEqual(template.description, "Standard electrical installation task")
        self.assertEqual(template.units, "outlets")
        self.assertEqual(template.rate, Decimal('45.00'))
        self.assertEqual(template.task_mapping, self.task_mapping)
        self.assertIn(self.work_order_template, template.work_order_templates.all())
        self.assertEqual(association.est_qty, Decimal('12.00'))
        self.assertTrue(template.is_active)
        self.assertIsNotNone(template.created_date)

    def test_task_template_str_method(self):
        template = TaskTemplate.objects.create(
            template_name="Plumbing Setup",
            task_mapping=self.task_mapping
        )
        self.assertEqual(str(template), "Plumbing Setup")

    def test_task_template_defaults(self):
        template = TaskTemplate.objects.create(
            template_name="Default Template",
            task_mapping=self.task_mapping
        )
        self.assertTrue(template.is_active)
        self.assertEqual(template.description, "")
        self.assertEqual(template.units, "")
        self.assertIsNone(template.rate)
        self.assertEqual(template.work_order_templates.count(), 0)

    def test_task_template_without_task_mapping(self):
        """Test TaskTemplate can be created without TaskMapping."""
        template = TaskTemplate.objects.create(
            template_name="Template Without Mapping",
            description="Template without task mapping",
            units="hours",
            rate=Decimal('50.00')
        )
        self.assertIsNone(template.task_mapping)
        self.assertEqual(template.template_name, "Template Without Mapping")
        self.assertEqual(template.units, "hours")
        self.assertEqual(template.rate, Decimal('50.00'))

    def test_task_template_new_fields_optional(self):
        """Test that new pricing fields are optional."""
        template = TaskTemplate.objects.create(
            template_name="Simple Template",
            task_mapping=self.task_mapping
        )
        self.assertEqual(template.units, "")
        self.assertIsNone(template.rate)

    def test_task_template_pricing_calculation(self):
        """Test using TaskTemplate fields with association quantities for cost calculations."""
        template = TaskTemplate.objects.create(
            template_name="Material Template",
            task_mapping=self.task_mapping,
            units="square_feet",
            rate=Decimal('15.25')
        )

        # Create association with quantity
        from apps.jobs.models import TemplateTaskAssociation
        association = TemplateTaskAssociation.objects.create(
            work_order_template=self.work_order_template,
            task_template=template,
            est_qty=Decimal('200.00')
        )

        estimated_cost = template.rate * association.est_qty if template.rate and association.est_qty else Decimal('0.00')
        self.assertEqual(estimated_cost, Decimal('3050.00'))

    def test_task_template_without_work_order_template(self):
        """Test TaskTemplate can exist without WorkOrderTemplate."""
        template = TaskTemplate.objects.create(
            template_name="Standalone Template",
            task_mapping=self.task_mapping
        )
        self.assertEqual(template.work_order_templates.count(), 0)
        self.assertEqual(template.task_mapping, self.task_mapping)

    def test_template_task_association_sort_order(self):
        """Test that TaskTemplates added to WorkOrderTemplate maintain sort order."""
        from apps.jobs.models import TemplateTaskAssociation

        # Create multiple task templates
        task_template1 = TaskTemplate.objects.create(
            template_name="First Task",
            task_mapping=self.task_mapping
        )
        task_template2 = TaskTemplate.objects.create(
            template_name="Second Task",
            task_mapping=self.task_mapping
        )
        task_template3 = TaskTemplate.objects.create(
            template_name="Third Task",
            task_mapping=self.task_mapping
        )

        # Add them to the work order template with specific sort orders
        association1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.work_order_template,
            task_template=task_template1,
            est_qty=Decimal('1.00'),
            sort_order=1
        )
        association2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.work_order_template,
            task_template=task_template2,
            est_qty=Decimal('2.00'),
            sort_order=2
        )
        association3 = TemplateTaskAssociation.objects.create(
            work_order_template=self.work_order_template,
            task_template=task_template3,
            est_qty=Decimal('3.00'),
            sort_order=3
        )

        # Query associations ordered by sort_order
        ordered_associations = TemplateTaskAssociation.objects.filter(
            work_order_template=self.work_order_template
        ).order_by('sort_order')

        # Verify the order is maintained
        self.assertEqual(ordered_associations[0].task_template, task_template1)
        self.assertEqual(ordered_associations[1].task_template, task_template2)
        self.assertEqual(ordered_associations[2].task_template, task_template3)

        # Verify sort_order values
        self.assertEqual(ordered_associations[0].sort_order, 1)
        self.assertEqual(ordered_associations[1].sort_order, 2)
        self.assertEqual(ordered_associations[2].sort_order, 3)

    def test_template_task_association_auto_increment_sort_order(self):
        """Test that sort_order auto-increments when adding tasks sequentially."""
        from apps.jobs.models import TemplateTaskAssociation
        from django.db import models as db_models

        # Create multiple task templates
        task_templates = []
        for i in range(5):
            template = TaskTemplate.objects.create(
                template_name=f"Task {i+1}",
                task_mapping=self.task_mapping
            )
            task_templates.append(template)

        # Add them simulating the view logic for auto-incrementing sort_order
        for i, task_template in enumerate(task_templates):
            # Get the next sort_order value (as done in the view)
            max_sort_order = TemplateTaskAssociation.objects.filter(
                work_order_template=self.work_order_template
            ).aggregate(db_models.Max('sort_order'))['sort_order__max']
            next_sort_order = (max_sort_order or 0) + 1

            TemplateTaskAssociation.objects.create(
                work_order_template=self.work_order_template,
                task_template=task_template,
                est_qty=Decimal('1.00'),
                sort_order=next_sort_order
            )

        # Verify all tasks have incrementing sort_order values
        associations = TemplateTaskAssociation.objects.filter(
            work_order_template=self.work_order_template
        ).order_by('sort_order')

        self.assertEqual(associations.count(), 5)
        for i, association in enumerate(associations):
            self.assertEqual(association.sort_order, i + 1)
            self.assertEqual(association.task_template.template_name, f"Task {i+1}")
