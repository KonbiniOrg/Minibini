"""Tests for Estimate and EstWorksheet state transitions and version management."""

from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from apps.jobs.models import Job, PlanTask
from apps.estimates.models import Estimate, EstWorksheet, EstimateLineItem, TaskTemplate
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
            status=Job.STATUS_DRAFT
        )

        # Create a worksheet linked to the estimate
        self.worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=self.estimate,
            status=Estimate.STATUS_DRAFT,
            version=1
        )

    def test_mark_estimate_as_open(self):
        """Test marking a draft estimate as open."""
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Test item',
            price=Decimal('100.00'),
        )
        url = reverse('estimates:estimate_mark_open', args=[self.estimate.estimate_id])
        response = self.client.post(url)

        # Reload from database
        self.estimate.refresh_from_db()
        self.worksheet.refresh_from_db()

        # Check estimate is now open
        self.assertEqual(self.estimate.status, Estimate.STATUS_OPEN)

        # Check worksheet is now final
        self.assertEqual(self.worksheet.status, EstWorksheet.STATUS_FINAL)

    def test_cannot_mark_non_draft_estimate_as_open(self):
        """Test that only draft estimates can be marked as open."""
        # Set estimate to already be open
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Test item',
            price=Decimal('100.00'),
        )
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()

        url = reverse('estimates:estimate_mark_open', args=[self.estimate.estimate_id])
        response = self.client.post(url)

        # Reload from database
        self.estimate.refresh_from_db()

        # Status should remain open, not changed
        self.assertEqual(self.estimate.status, Estimate.STATUS_OPEN)

    def test_estimate_version_increment(self):
        """Test that estimate versions increment correctly."""
        # Create a parent estimate
        parent_estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST002',
            version=1,
            status=Estimate.STATUS_OPEN
        )

        # Create a child estimate
        child_estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST002',
            version=2,
            status=Job.STATUS_DRAFT
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
            status=EstWorksheet.STATUS_FINAL,
            version=1
        )

        # Create a task in the worksheet
        self.task = PlanTask.objects.create(
            name='Test Task',
            est_worksheet=self.worksheet,
            est_qty=10.0,
            rate=100.0,
            units='hours'
        )

    def test_cannot_generate_estimate_from_non_draft_worksheet(self):
        """Test that estimates can only be generated from draft worksheets."""
        self.assertEqual(self.worksheet.status, EstWorksheet.STATUS_FINAL)

        # The template should not show the generate estimate option
        response = self.client.get(
            reverse('estimates:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        )
        self.assertNotContains(response, 'Generate Estimate')
        self.assertContains(response, 'Revise Worksheet')

    def test_revise_worksheet_creates_new_draft(self):
        """Test that revising a worksheet creates a new draft version."""
        url = reverse('estimates:estworksheet_revise', args=[self.worksheet.est_worksheet_id])
        response = self.client.post(url)

        # Check that a new worksheet was created
        new_worksheet = EstWorksheet.objects.filter(
            parent=self.worksheet
        ).first()

        self.assertIsNotNone(new_worksheet)
        self.assertEqual(new_worksheet.status, EstWorksheet.STATUS_DRAFT)
        self.assertEqual(new_worksheet.version, 2)
        self.assertEqual(new_worksheet.parent, self.worksheet)

        # Check that parent was marked as superseded
        self.worksheet.refresh_from_db()
        self.assertEqual(self.worksheet.status, EstWorksheet.STATUS_SUPERSEDED)

    def test_revise_worksheet_copies_tasks(self):
        """Test that revising a worksheet copies all tasks to the new version."""
        url = reverse('estimates:estworksheet_revise', args=[self.worksheet.est_worksheet_id])
        response = self.client.post(url)

        # Get the new worksheet
        new_worksheet = EstWorksheet.objects.filter(
            parent=self.worksheet
        ).first()

        # Check that tasks were copied
        new_tasks = PlanTask.objects.filter(est_worksheet=new_worksheet)
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
            status=Job.STATUS_DRAFT,
            version=1
        )

        url = reverse('estimates:estworksheet_revise', args=[draft_worksheet.est_worksheet_id])
        response = self.client.post(url)

        # No new worksheet should be created
        new_worksheet = EstWorksheet.objects.filter(
            parent=draft_worksheet
        ).first()

        self.assertIsNone(new_worksheet)

        # Original should remain draft
        draft_worksheet.refresh_from_db()
        self.assertEqual(draft_worksheet.status, Estimate.STATUS_DRAFT)

    def test_new_worksheet_not_linked_to_estimate(self):
        """Test that revised worksheet is not linked to parent's estimate."""
        # Create an estimate and link it to the worksheet
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST003',
            version=1,
            status=Estimate.STATUS_OPEN
        )
        self.worksheet.estimate = estimate
        self.worksheet.save()

        url = reverse('estimates:estworksheet_revise', args=[self.worksheet.est_worksheet_id])
        response = self.client.post(url)

        # Get the new worksheet
        new_worksheet = EstWorksheet.objects.filter(
            parent=self.worksheet
        ).first()

        # New worksheet should not be linked to any estimate
        self.assertIsNone(new_worksheet.estimate)