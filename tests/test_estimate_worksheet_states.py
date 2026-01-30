"""Tests for Estimate and EstWorksheet state transitions and version management."""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from apps.jobs.models import (
    Job, Estimate, EstWorksheet, Task, TaskTemplate, TaskMapping
)
from apps.jobs.services import EstimateGenerationService
from apps.contacts.models import Contact
from apps.core.models import Configuration


class EstimateStateTests(TestCase):
    """Test Estimate state transitions and version management."""

    def setUp(self):
        """Set up test data."""
        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        self.client = Client()

        # Create a test contact
        self.contact = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='test@example.com'
        )

        # Create a job
        self.job = Job.objects.create(
            job_number='TEST001',
            description='Test Job',
            contact=self.contact
        )

        # Create an estimate
        self.estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST001',
            version=1,
            status='draft'
        )

        # Create a worksheet linked to the estimate
        self.worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=self.estimate,
            status='draft',
            version=1
        )

    def test_mark_estimate_as_open(self):
        """Test marking a draft estimate as open."""
        url = reverse('jobs:estimate_mark_open', args=[self.estimate.estimate_id])
        response = self.client.post(url)

        # Reload from database
        self.estimate.refresh_from_db()
        self.worksheet.refresh_from_db()

        # Check estimate is now open
        self.assertEqual(self.estimate.status, 'open')

        # Check worksheet is now final
        self.assertEqual(self.worksheet.status, 'final')

    def test_cannot_mark_non_draft_estimate_as_open(self):
        """Test that only draft estimates can be marked as open."""
        # Set estimate to already be open
        self.estimate.status = 'open'
        self.estimate.save()

        url = reverse('jobs:estimate_mark_open', args=[self.estimate.estimate_id])
        response = self.client.post(url)

        # Reload from database
        self.estimate.refresh_from_db()

        # Status should remain open, not changed
        self.assertEqual(self.estimate.status, 'open')

    def test_estimate_version_increment(self):
        """Test that estimate versions increment correctly."""
        # Create a parent estimate
        parent_estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST002',
            version=1,
            status='open'
        )

        # Create a child estimate
        child_estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST002',
            version=2,
            status='draft'
        )

        # Set the parent relationship
        child_estimate.parent = parent_estimate
        child_estimate.save()

        self.assertEqual(child_estimate.version, 2)
        self.assertEqual(child_estimate.parent, parent_estimate)


class EstWorksheetStateTests(TestCase):
    """Test EstWorksheet state transitions and revision management."""

    def setUp(self):
        """Set up test data."""
        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        self.client = Client()

        # Create a test contact
        self.contact = Contact.objects.create(
            first_name='Test Contact 2',
            last_name='',
            email='test2@example.com'
        )

        # Create a job
        self.job = Job.objects.create(
            job_number='TEST002',
            description='Test Job 2',
            contact=self.contact
        )

        # Create a final worksheet (not draft)
        self.worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='final',
            version=1
        )

        # Create a task in the worksheet
        self.task = Task.objects.create(
            name='Test Task',
            est_worksheet=self.worksheet,
            est_qty=10.0,
            rate=100.0,
            units='hours'
        )

    def test_cannot_generate_estimate_from_non_draft_worksheet(self):
        """Test that estimates can only be generated from draft worksheets."""
        self.assertEqual(self.worksheet.status, 'final')

        # The template should not show the generate estimate option
        response = self.client.get(
            reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        )
        self.assertNotContains(response, 'Generate Estimate')
        self.assertContains(response, 'Revise Worksheet')

    def test_revise_worksheet_creates_new_draft(self):
        """Test that revising a worksheet creates a new draft version."""
        url = reverse('jobs:estworksheet_revise', args=[self.worksheet.est_worksheet_id])
        response = self.client.post(url)

        # Check that a new worksheet was created
        new_worksheet = EstWorksheet.objects.filter(
            parent=self.worksheet
        ).first()

        self.assertIsNotNone(new_worksheet)
        self.assertEqual(new_worksheet.status, 'draft')
        self.assertEqual(new_worksheet.version, 2)
        self.assertEqual(new_worksheet.parent, self.worksheet)

        # Check that parent was marked as superseded
        self.worksheet.refresh_from_db()
        self.assertEqual(self.worksheet.status, 'superseded')

    def test_revise_worksheet_copies_tasks(self):
        """Test that revising a worksheet copies all tasks to the new version."""
        url = reverse('jobs:estworksheet_revise', args=[self.worksheet.est_worksheet_id])
        response = self.client.post(url)

        # Get the new worksheet
        new_worksheet = EstWorksheet.objects.filter(
            parent=self.worksheet
        ).first()

        # Check that tasks were copied
        new_tasks = Task.objects.filter(est_worksheet=new_worksheet)
        self.assertEqual(new_tasks.count(), 1)

        new_task = new_tasks.first()
        self.assertEqual(new_task.name, self.task.name)
        self.assertEqual(new_task.est_qty, self.task.est_qty)
        self.assertEqual(new_task.rate, self.task.rate)
        self.assertEqual(new_task.units, self.task.units)

    def test_cannot_revise_draft_worksheet(self):
        """Test that draft worksheets cannot be revised."""
        # Create a draft worksheet
        draft_worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='draft',
            version=1
        )

        url = reverse('jobs:estworksheet_revise', args=[draft_worksheet.est_worksheet_id])
        response = self.client.post(url)

        # No new worksheet should be created
        new_worksheet = EstWorksheet.objects.filter(
            parent=draft_worksheet
        ).first()

        self.assertIsNone(new_worksheet)

        # Original should remain draft
        draft_worksheet.refresh_from_db()
        self.assertEqual(draft_worksheet.status, 'draft')

    def test_new_worksheet_not_linked_to_estimate(self):
        """Test that revised worksheet is not linked to parent's estimate."""
        # Create an estimate and link it to the worksheet
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST003',
            version=1,
            status='open'
        )
        self.worksheet.estimate = estimate
        self.worksheet.save()

        url = reverse('jobs:estworksheet_revise', args=[self.worksheet.est_worksheet_id])
        response = self.client.post(url)

        # Get the new worksheet
        new_worksheet = EstWorksheet.objects.filter(
            parent=self.worksheet
        ).first()

        # New worksheet should not be linked to any estimate
        self.assertIsNone(new_worksheet.estimate)


class EstimateGenerationServiceTests(TestCase):
    """Test EstimateGenerationService with parent/child relationships."""

    def setUp(self):
        """Set up test data."""
        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        # Create a test contact
        self.contact = Contact.objects.create(
            first_name='Test Contact 3',
            last_name='',
            email='test3@example.com'
        )

        # Create a job
        self.job = Job.objects.create(
            job_number='TEST003',
            description='Test Job 3',
            contact=self.contact
        )

        # Create task mapping for testing
        self.task_mapping = TaskMapping.objects.create(
            mapping_strategy='direct',
            task_type_id='TEST_TYPE',
            breakdown_of_task='Test task mapping'
        )

        # Create task template
        self.task_template = TaskTemplate.objects.create(
            template_name='Test Template',
            task_mapping=self.task_mapping,
            rate=100.0,
            units='hours'
        )

        self.service = EstimateGenerationService()

    def test_generate_estimate_from_revised_worksheet(self):
        """Test generating estimate from revised worksheet creates child estimate."""
        # Create parent worksheet with estimate
        parent_worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='final',
            version=1
        )
        task = Task.objects.create(
            name='Task',
            est_worksheet=parent_worksheet,
            template=self.task_template,
            est_qty=5.0,
            rate=50.0,
            units='hours'
        )

        # Generate parent estimate
        parent_estimate = self.service.generate_estimate_from_worksheet(parent_worksheet)
        parent_estimate.status = 'open'
        parent_estimate.save();
        parent_estimate_number = parent_estimate.estimate_number

        # Create child worksheet (revision)
        child_worksheet = EstWorksheet.objects.create(
            job=self.job,
            parent=parent_worksheet,
            status='draft',
            version=2
        )
        task2 = Task.objects.create(
            name='Task',
            est_worksheet=child_worksheet,
            template=self.task_template,
            est_qty=5.0,
            rate=50.0,
            units='hours'
        )

        # Generate child estimate
        child_estimate = self.service.generate_estimate_from_worksheet(child_worksheet)

        # Check relationships
        parent_estimate.refresh_from_db()
        self.assertEqual(child_estimate.parent, parent_estimate)
        self.assertEqual(child_estimate.estimate_number, parent_estimate_number)
        self.assertEqual(child_estimate.version, 2)

        # Check parent estimate is superseded
        self.assertEqual(parent_estimate.status, 'superseded')

    def test_generate_estimate_without_parent(self):
        """Test generating estimate from worksheet without parent."""
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='draft',
            version=1
        )

        task = Task.objects.create(
            name='Task',
            est_worksheet=worksheet,
            template=self.task_template,
            est_qty=5.0,
            rate=50.0,
            units='hours'
        )

        estimate = self.service.generate_estimate_from_worksheet(worksheet)

        # Check that no parent relationship exists
        self.assertIsNone(estimate.parent)
        self.assertEqual(estimate.version, 1)
        self.assertEqual(estimate.status, 'draft')


class IntegrationTests(TestCase):
    """Integration tests for the full workflow."""

    def setUp(self):
        """Set up test data."""
        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        self.client = Client()

        # Create a test contact
        self.contact = Contact.objects.create(
            first_name='Test Contact 4',
            last_name='',
            email='test4@example.com'
        )

        # Create a job
        self.job = Job.objects.create(
            job_number='TEST004',
            description='Integration Test Job',
            contact=self.contact
        )

        # Create task mapping
        self.task_mapping = TaskMapping.objects.create(
            mapping_strategy='direct',
            task_type_id='INTEGRATION_TEST',
            breakdown_of_task='Integration test task'
        )

        # Create task template
        self.task_template = TaskTemplate.objects.create(
            template_name='Integration Template',
            task_mapping=self.task_mapping,
            rate=100.0,
            units='hours'
        )

        self.service = EstimateGenerationService()

    def test_full_workflow(self):
        """Test the complete workflow from draft to revision."""
        # 1. Create initial draft worksheet
        worksheet_v1 = EstWorksheet.objects.create(
            job=self.job,
            status='draft',
            version=1
        )

        task_v1 = Task.objects.create(
            name='Task v1',
            est_worksheet=worksheet_v1,
            template=self.task_template,
            est_qty=5.0,
            rate=100.0,
            units='hours'
        )

        # 2. Generate estimate from worksheet
        estimate_v1 = self.service.generate_estimate_from_worksheet(worksheet_v1)
        self.assertEqual(estimate_v1.status, 'draft')
        self.assertEqual(estimate_v1.version, 1)

        # 3. Mark estimate as open
        url = reverse('jobs:estimate_mark_open', args=[estimate_v1.estimate_id])
        response = self.client.post(url)

        estimate_v1.refresh_from_db()
        worksheet_v1.refresh_from_db()

        self.assertEqual(estimate_v1.status, 'open')
        self.assertEqual(worksheet_v1.status, 'final')

        # 4. Revise the worksheet
        url = reverse('jobs:estworksheet_revise', args=[worksheet_v1.est_worksheet_id])
        response = self.client.post(url)

        worksheet_v2 = EstWorksheet.objects.filter(parent=worksheet_v1).first()
        self.assertIsNotNone(worksheet_v2)
        self.assertEqual(worksheet_v2.status, 'draft')
        self.assertEqual(worksheet_v2.version, 2)

        # 5. Generate new estimate from revised worksheet
        estimate_v2 = self.service.generate_estimate_from_worksheet(worksheet_v2)

        # Check versioning
        self.assertEqual(estimate_v2.estimate_number, estimate_v1.estimate_number)
        self.assertEqual(estimate_v2.version, 2)

        # Check parent is linked to child via parent field
        self.assertEqual(estimate_v2.parent, estimate_v1)

        # Check parent estimate is superseded
        estimate_v1.refresh_from_db()
        self.assertEqual(estimate_v1.status, 'superseded')

        # 6. Mark new estimate as open
        url = reverse('jobs:estimate_mark_open', args=[estimate_v2.estimate_id])
        response = self.client.post(url)

        estimate_v2.refresh_from_db()
        worksheet_v2.refresh_from_db()

        self.assertEqual(estimate_v2.status, 'open')
        self.assertEqual(worksheet_v2.status, 'final')