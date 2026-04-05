"""Tests for CRUD operations for EstWorksheet and Task creation."""

from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.jobs.models import Job, Task, PlanTask
from apps.estimates.models import Estimate, EstWorksheet, TaskTemplate, EstimateLineItem, WorkOrderTemplate
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory


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
        self.task_template = TaskTemplate.objects.create(
            template_name='Test Template',
            rate=100.0,
            units='hours'
        )

        # Create WorkOrderTemplate for the from-template tests
        self.work_order_template = WorkOrderTemplate.objects.create(
            template_name='Test Work Order Template',
            description='Test template for work orders'
        )

    # Removed standalone estworksheet_create tests - view removed, worksheets are now only created from the Job page


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
            status=Job.STATUS_DRAFT,
            version=1
        )

        # Create task mapping and template
        self.task_template = TaskTemplate.objects.create(
            template_name='Test Template',
            rate=100.0,
            units='hours'
        )

    def test_add_task_from_template_get(self):
        """Test GET request to add task from template form."""
        url = reverse('estimates:task_add_from_template', args=[self.worksheet.est_worksheet_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Task from Template')

    def test_add_task_from_template_post(self):
        """Test POST request to add task from template."""
        url = reverse('estimates:task_add_from_template', args=[self.worksheet.est_worksheet_id])
        data = {
            'template': self.task_template.template_id,
            'est_qty': 5.0
        }
        response = self.client.post(url, data)

        # Check redirect after successful creation
        self.assertEqual(response.status_code, 302)

        # Check task was created
        task = PlanTask.objects.filter(est_worksheet=self.worksheet).first()
        self.assertIsNotNone(task)
        self.assertEqual(task.est_qty, 5.0)
        self.assertEqual(task.rate, self.task_template.rate)
        self.assertEqual(task.units, self.task_template.units)

    def test_add_task_manual_get(self):
        """Test GET request to add task manually form."""
        url = reverse('estimates:task_add_manual', args=[self.worksheet.est_worksheet_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Task Manually')

    def test_add_task_manual_post(self):
        """Test POST request to add task manually."""
        url = reverse('estimates:task_add_manual', args=[self.worksheet.est_worksheet_id])
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
        task = PlanTask.objects.filter(est_worksheet=self.worksheet).first()
        self.assertIsNotNone(task)
        self.assertEqual(task.name, 'Manual Task')
        self.assertEqual(task.est_qty, 10.0)
        self.assertEqual(task.rate, 75.0)
        self.assertEqual(task.units, 'hours')


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
            status=Job.STATUS_DRAFT
        )

    def test_add_line_item_get(self):
        """Test GET request to add line item form."""
        url = reverse('estimates:estimate_add_line_item', args=[self.estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Line Item')

    def test_add_line_item_post(self):
        """Test POST request to add line item."""
        # Get or create a line item type for the test
        service_type, _ = AccountingCategory.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False, 'is_active': True}
        )
        url = reverse('estimates:estimate_add_line_item', args=[self.estimate.estimate_id])
        data = {
            'description': 'Test Line Item',
            'qty': 5.0,
            'price': 100.0,
            'units': 'ea',
            'accounting_category': service_type.pk,
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
        self.assertEqual(line_item.price, 100.0)
        self.assertEqual(line_item.units, 'ea')

    def test_update_status_get(self):
        """Test GET request to update status form."""
        url = reverse('estimates:estimate_update_status', args=[self.estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Update Estimate Status')

    def test_update_status_post(self):
        """Test POST request to update status."""
        EstimateLineItem.objects.create(estimate=self.estimate, description='Test item', price=Decimal('100.00'))
        url = reverse('estimates:estimate_update_status', args=[self.estimate.estimate_id])
        data = {
            'status': Estimate.STATUS_OPEN
        }
        response = self.client.post(url, data)

        # Check redirect after successful update
        self.assertEqual(response.status_code, 302)

        # Check status was updated
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, Estimate.STATUS_OPEN)

    def test_update_status_invalid_transition(self):
        """Test that invalid status transitions are handled."""
        # Set estimate to open (superseded isn't allowed directly after draft)
        EstimateLineItem.objects.create(estimate=self.estimate, description='Test item', price=Decimal('100.00'))
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()

        url = reverse('estimates:estimate_update_status', args=[self.estimate.estimate_id])
        data = {
            'status': Estimate.STATUS_DRAFT
        }
        response = self.client.post(url, data)

        # Status should not change for invalid transitions
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, Estimate.STATUS_OPEN)


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
            status=Estimate.STATUS_OPEN
        )

        # Create child estimate
        self.child_estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST001',
            version=2,
            status=Job.STATUS_DRAFT,
            parent=self.parent_estimate
        )

        # Create parent worksheet
        self.parent_worksheet = EstWorksheet.objects.create(
            job=self.job,
            status=EstWorksheet.STATUS_FINAL,
            version=1
        )

        # Create child worksheet
        self.child_worksheet = EstWorksheet.objects.create(
            job=self.job,
            status=Job.STATUS_DRAFT,
            version=2,
            parent=self.parent_worksheet
        )

    def test_estimate_shows_parent_link(self):
        """Test that child estimate shows link to parent."""
        url = reverse('estimates:estimate_detail', args=[self.child_estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Parent Estimate:')
        self.assertContains(response, f'EST001 (v{self.parent_estimate.version})')

    def test_estimate_shows_child_links(self):
        """Test that parent estimate shows links to children."""
        # Verify the relationship exists
        self.assertEqual(self.child_estimate.parent, self.parent_estimate)
        self.assertTrue(self.parent_estimate.children.exists())

        url = reverse('estimates:estimate_detail', args=[self.parent_estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Child Estimates:')
        self.assertContains(response, f'EST001 (v{self.child_estimate.version})')

    def test_worksheet_shows_parent_link(self):
        """Test that child worksheet shows link to parent."""
        url = reverse('estimates:estworksheet_detail', args=[self.child_worksheet.est_worksheet_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Parent Worksheet:')
        self.assertContains(response, f'Worksheet (v{self.parent_worksheet.version})')

    def test_worksheet_shows_child_links(self):
        """Test that parent worksheet shows links to children."""
        url = reverse('estimates:estworksheet_detail', args=[self.parent_worksheet.est_worksheet_id])
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
            status=EstWorksheet.STATUS_SUPERSEDED
        )

        # Create superseded worksheet
        self.superseded_worksheet = EstWorksheet.objects.create(
            job=self.job,
            status=EstWorksheet.STATUS_SUPERSEDED,
            version=1
        )

    def test_superseded_estimate_has_styling(self):
        """Test that superseded estimate has greyed out styling."""
        url = reverse('estimates:estimate_detail', args=[self.superseded_estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="superseded"')

    def test_superseded_worksheet_has_styling(self):
        """Test that superseded worksheet has greyed out styling."""
        url = reverse('estimates:estworksheet_detail', args=[self.superseded_worksheet.est_worksheet_id])
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
            status=Estimate.STATUS_DRAFT
        )

        url = reverse('estimates:estimate_detail', args=[estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        # Header should not have superseded class
        content = response.content.decode()
        self.assertNotIn('<h2 class="superseded"', content)
        self.assertNotIn('<table border="1" class="superseded"', content)