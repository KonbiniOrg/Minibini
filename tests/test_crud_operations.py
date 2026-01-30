"""Tests for CRUD operations for EstWorksheet and Task creation."""

from django.test import TestCase, Client
from django.urls import reverse
from apps.jobs.models import (
    Job, Estimate, EstWorksheet, Task, TaskTemplate, TaskMapping,
    EstimateLineItem, WorkOrderTemplate
)
from apps.contacts.models import Contact


class EstWorksheetCRUDTests(TestCase):
    """Test CRUD operations for EstWorksheet creation."""

    def setUp(self):
        """Set up test data."""
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

        # Create task mapping and template for testing
        self.task_mapping = TaskMapping.objects.create(
            mapping_strategy='direct',
            task_type_id='TEST_TYPE',
            breakdown_of_task='Test task mapping'
        )

        self.task_template = TaskTemplate.objects.create(
            template_name='Test Template',
            task_mapping=self.task_mapping,
            rate=100.0,
            units='hours'
        )

        # Create WorkOrderTemplate for the from-template tests
        self.work_order_template = WorkOrderTemplate.objects.create(
            template_name='Test Work Order Template',
            description='Test template for work orders'
        )

    def test_create_estworksheet_get(self):
        """Test GET request to create EstWorksheet form."""
        url = reverse('jobs:estworksheet_create')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create New EstWorksheet')

    def test_create_estworksheet_post(self):
        """Test POST request to create new EstWorksheet."""
        url = reverse('jobs:estworksheet_create')
        data = {
            'job': self.job.job_id,
            'status': 'draft'
        }
        response = self.client.post(url, data)

        # Check redirect after successful creation
        self.assertEqual(response.status_code, 302)

        # Check worksheet was created
        worksheet = EstWorksheet.objects.filter(job=self.job).first()
        self.assertIsNotNone(worksheet)
        self.assertEqual(worksheet.status, 'draft')
        self.assertEqual(worksheet.version, 1)

    # Removed tests for estworksheet_create_from_template - functionality merged into estworksheet_create_for_job


class TaskCRUDTests(TestCase):
    """Test CRUD operations for Task creation."""

    def setUp(self):
        """Set up test data."""
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

        # Create a worksheet
        self.worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='draft',
            version=1
        )

        # Create task mapping and template
        self.task_mapping = TaskMapping.objects.create(
            mapping_strategy='direct',
            task_type_id='TEST_TYPE',
            breakdown_of_task='Test task mapping'
        )

        self.task_template = TaskTemplate.objects.create(
            template_name='Test Template',
            task_mapping=self.task_mapping,
            rate=100.0,
            units='hours'
        )

    def test_add_task_from_template_get(self):
        """Test GET request to add task from template form."""
        url = reverse('jobs:task_add_from_template', args=[self.worksheet.est_worksheet_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Task from Template')

    def test_add_task_from_template_post(self):
        """Test POST request to add task from template."""
        url = reverse('jobs:task_add_from_template', args=[self.worksheet.est_worksheet_id])
        data = {
            'template': self.task_template.template_id,
            'est_qty': 5.0
        }
        response = self.client.post(url, data)

        # Check redirect after successful creation
        self.assertEqual(response.status_code, 302)

        # Check task was created
        task = Task.objects.filter(est_worksheet=self.worksheet).first()
        self.assertIsNotNone(task)
        self.assertEqual(task.template, self.task_template)
        self.assertEqual(task.est_qty, 5.0)
        self.assertEqual(task.rate, self.task_template.rate)
        self.assertEqual(task.units, self.task_template.units)

    def test_add_task_manual_get(self):
        """Test GET request to add task manually form."""
        url = reverse('jobs:task_add_manual', args=[self.worksheet.est_worksheet_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Task Manually')

    def test_add_task_manual_post(self):
        """Test POST request to add task manually."""
        url = reverse('jobs:task_add_manual', args=[self.worksheet.est_worksheet_id])
        data = {
            'name': 'Manual Task',
            'est_qty': 10.0,
            'rate': 75.0,
            'units': 'hours',
            'est_worksheet': self.worksheet.est_worksheet_id
        }
        response = self.client.post(url, data)

        # Check redirect after successful creation
        self.assertEqual(response.status_code, 302)

        # Check task was created
        task = Task.objects.filter(est_worksheet=self.worksheet).first()
        self.assertIsNotNone(task)
        self.assertEqual(task.name, 'Manual Task')
        self.assertEqual(task.est_qty, 10.0)
        self.assertEqual(task.rate, 75.0)
        self.assertEqual(task.units, 'hours')
        self.assertIsNone(task.template)


class EstimateCRUDTests(TestCase):
    """Test CRUD operations for Estimate line items and status updates."""

    def setUp(self):
        """Set up test data."""
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

    def test_add_line_item_get(self):
        """Test GET request to add line item form."""
        url = reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Line Item')

    def test_add_line_item_post(self):
        """Test POST request to add line item."""
        url = reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id])
        data = {
            'description': 'Test Line Item',
            'qty': 5.0,
            'price_currency': 100.0,
            'units': 'each',
            'manual_submit': 'Add Manual Line Item'
        }
        response = self.client.post(url, data)

        # Check redirect after successful creation
        self.assertEqual(response.status_code, 302)

        # Check line item was created
        line_item = EstimateLineItem.objects.filter(estimate=self.estimate).first()
        self.assertIsNotNone(line_item)
        self.assertEqual(line_item.description, 'Test Line Item')
        self.assertEqual(line_item.qty, 5.0)
        self.assertEqual(line_item.price_currency, 100.0)
        self.assertEqual(line_item.units, 'each')

    def test_update_status_get(self):
        """Test GET request to update status form."""
        url = reverse('jobs:estimate_update_status', args=[self.estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Update Estimate Status')

    def test_update_status_post(self):
        """Test POST request to update status."""
        url = reverse('jobs:estimate_update_status', args=[self.estimate.estimate_id])
        data = {
            'status': 'open'
        }
        response = self.client.post(url, data)

        # Check redirect after successful update
        self.assertEqual(response.status_code, 302)

        # Check status was updated
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, 'open')

    def test_update_status_invalid_transition(self):
        """Test that invalid status transitions are handled."""
        # Set estimate to open (superseded isn't allowed directly after draft)
        self.estimate.status = 'open'
        self.estimate.save()

        url = reverse('jobs:estimate_update_status', args=[self.estimate.estimate_id])
        data = {
            'status': 'draft'
        }
        response = self.client.post(url, data)

        # Status should not change for invalid transitions
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, 'open')


class NavigationLinksTests(TestCase):
    """Test parent/child navigation links in templates."""

    def setUp(self):
        """Set up test data."""
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

        # Create parent estimate
        self.parent_estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST001',
            version=1,
            status='open'
        )

        # Create child estimate
        self.child_estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST001',
            version=2,
            status='draft',
            parent=self.parent_estimate
        )

        # Create parent worksheet
        self.parent_worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='final',
            version=1
        )

        # Create child worksheet
        self.child_worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='draft',
            version=2,
            parent=self.parent_worksheet
        )

    def test_estimate_shows_parent_link(self):
        """Test that child estimate shows link to parent."""
        url = reverse('jobs:estimate_detail', args=[self.child_estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Parent Estimate:')
        self.assertContains(response, f'EST001 (v{self.parent_estimate.version})')

    def test_estimate_shows_child_links(self):
        """Test that parent estimate shows links to children."""
        # Verify the relationship exists
        self.assertEqual(self.child_estimate.parent, self.parent_estimate)
        self.assertTrue(self.parent_estimate.children.exists())

        url = reverse('jobs:estimate_detail', args=[self.parent_estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Child Estimates:')
        self.assertContains(response, f'EST001 (v{self.child_estimate.version})')

    def test_worksheet_shows_parent_link(self):
        """Test that child worksheet shows link to parent."""
        url = reverse('jobs:estworksheet_detail', args=[self.child_worksheet.est_worksheet_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Parent Worksheet:')
        self.assertContains(response, f'Worksheet (v{self.parent_worksheet.version})')

    def test_worksheet_shows_child_links(self):
        """Test that parent worksheet shows links to children."""
        url = reverse('jobs:estworksheet_detail', args=[self.parent_worksheet.est_worksheet_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Child Worksheets:')
        self.assertContains(response, f'Worksheet (v{self.child_worksheet.version})')


class SupersededStylingTests(TestCase):
    """Test superseded styling is applied correctly."""

    def setUp(self):
        """Set up test data."""
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

        # Create superseded estimate
        self.superseded_estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST001',
            version=1,
            status='superseded'
        )

        # Create superseded worksheet
        self.superseded_worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='superseded',
            version=1
        )

    def test_superseded_estimate_has_styling(self):
        """Test that superseded estimate has greyed out styling."""
        url = reverse('jobs:estimate_detail', args=[self.superseded_estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="superseded"')

    def test_superseded_worksheet_has_styling(self):
        """Test that superseded worksheet has greyed out styling."""
        url = reverse('jobs:estworksheet_detail', args=[self.superseded_worksheet.est_worksheet_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="superseded"')

    def test_non_superseded_has_no_styling(self):
        """Test that non-superseded items don't have styling."""
        # Create non-superseded estimate
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST002',
            version=1,
            status='draft'
        )

        url = reverse('jobs:estimate_detail', args=[estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        # Header should not have superseded class
        content = response.content.decode()
        self.assertNotIn('<h2 class="superseded"', content)
        self.assertNotIn('<table border="1" class="superseded"', content)