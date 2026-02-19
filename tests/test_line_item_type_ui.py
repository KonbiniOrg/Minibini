"""
Tests that line_item_type is displayed and editable in all relevant UI views.
"""

from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from apps.jobs.models import Job, EstWorksheet, Task, TaskTemplate
from apps.contacts.models import Contact
from apps.core.models import LineItemType

User = get_user_model()


class TaskDetailLineItemTypeDisplayTests(TestCase):
    """Test that task_detail always shows line_item_type row."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser', password='testpass', email='test@example.com'
        )
        self.client.login(username='testuser', password='testpass')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(
            job_number='JOB-LIT-001', contact=self.contact, status='approved'
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status='draft', version=1
        )
        self.lit, _ = LineItemType.objects.get_or_create(code='SVC', defaults={'name': 'Service'})

    def test_detail_shows_line_item_type_when_set(self):
        """Task detail should display the line item type name when set."""
        task = Task.objects.create(
            name='Task With Type', est_worksheet=self.worksheet,
            units='hours', rate=Decimal('50.00'), est_qty=Decimal('2.00'),
            line_item_type=self.lit,
        )
        url = reverse('jobs:task_detail', args=[task.task_id])
        response = self.client.get(url)
        self.assertContains(response, 'Line Item Type')
        self.assertContains(response, 'Service')

    def test_detail_shows_line_item_type_row_when_null(self):
        """Task detail should always show the Line Item Type row, even when null."""
        task = Task.objects.create(
            name='Task No Type', est_worksheet=self.worksheet,
            units='hours', rate=Decimal('50.00'), est_qty=Decimal('2.00'),
        )
        url = reverse('jobs:task_detail', args=[task.task_id])
        response = self.client.get(url)
        self.assertContains(response, 'Line Item Type')


class TaskEditLineItemTypeTests(TestCase):
    """Test that task edit form includes line_item_type field."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser', password='testpass', email='test@example.com'
        )
        self.client.login(username='testuser', password='testpass')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(
            job_number='JOB-LIT-002', contact=self.contact, status='approved'
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status='draft', version=1
        )
        self.lit_svc, _ = LineItemType.objects.get_or_create(code='SVC', defaults={'name': 'Service'})
        self.lit_prd, _ = LineItemType.objects.get_or_create(code='PRD', defaults={'name': 'Product'})

    def test_edit_form_shows_line_item_type_field(self):
        """Task edit form should include a line_item_type dropdown."""
        task = Task.objects.create(
            name='Editable Task', est_worksheet=self.worksheet,
            units='hours', rate=Decimal('50.00'), est_qty=Decimal('2.00'),
        )
        url = reverse('jobs:task_edit', args=[task.task_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'line_item_type')

    def test_edit_post_can_set_line_item_type(self):
        """POST on task edit should be able to set line_item_type."""
        task = Task.objects.create(
            name='Task', est_worksheet=self.worksheet,
            units='hours', rate=Decimal('50.00'), est_qty=Decimal('2.00'),
        )
        url = reverse('jobs:task_edit', args=[task.task_id])
        response = self.client.post(url, {
            'name': 'Task',
            'units': 'hours',
            'rate': '50.00',
            'est_qty': '2.00',
            'line_item_type': self.lit_svc.pk,
        })
        self.assertRedirects(response, reverse('jobs:task_detail', args=[task.task_id]))
        task.refresh_from_db()
        self.assertEqual(task.line_item_type, self.lit_svc)

    def test_edit_post_can_change_line_item_type(self):
        """POST on task edit should be able to change line_item_type."""
        task = Task.objects.create(
            name='Task', est_worksheet=self.worksheet,
            units='hours', rate=Decimal('50.00'), est_qty=Decimal('2.00'),
            line_item_type=self.lit_svc,
        )
        url = reverse('jobs:task_edit', args=[task.task_id])
        response = self.client.post(url, {
            'name': 'Task',
            'units': 'hours',
            'rate': '50.00',
            'est_qty': '2.00',
            'line_item_type': self.lit_prd.pk,
        })
        self.assertRedirects(response, reverse('jobs:task_detail', args=[task.task_id]))
        task.refresh_from_db()
        self.assertEqual(task.line_item_type, self.lit_prd)

    def test_edit_post_can_clear_line_item_type(self):
        """POST on task edit should be able to clear line_item_type."""
        task = Task.objects.create(
            name='Task', est_worksheet=self.worksheet,
            units='hours', rate=Decimal('50.00'), est_qty=Decimal('2.00'),
            line_item_type=self.lit_svc,
        )
        url = reverse('jobs:task_edit', args=[task.task_id])
        response = self.client.post(url, {
            'name': 'Task',
            'units': 'hours',
            'rate': '50.00',
            'est_qty': '2.00',
            'line_item_type': '',
        })
        self.assertRedirects(response, reverse('jobs:task_detail', args=[task.task_id]))
        task.refresh_from_db()
        self.assertIsNone(task.line_item_type)


class TaskAddManualLineItemTypeTests(TestCase):
    """Test that the manual task add form includes line_item_type."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser', password='testpass', email='test@example.com'
        )
        self.client.login(username='testuser', password='testpass')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(
            job_number='JOB-LIT-003', contact=self.contact, status='approved'
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status='draft', version=1
        )
        self.lit, _ = LineItemType.objects.get_or_create(code='SVC', defaults={'name': 'Service'})

    def test_add_manual_form_shows_line_item_type(self):
        """Manual task add form should include line_item_type field."""
        url = reverse('jobs:task_add_manual', args=[self.worksheet.est_worksheet_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'line_item_type')

    def test_add_manual_post_with_line_item_type(self):
        """POST on manual add should create task with line_item_type."""
        url = reverse('jobs:task_add_manual', args=[self.worksheet.est_worksheet_id])
        response = self.client.post(url, {
            'name': 'New Manual Task',
            'units': 'hours',
            'rate': '40.00',
            'est_qty': '3.00',
            'line_item_type': self.lit.pk,
        })
        self.assertRedirects(
            response,
            reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        )
        task = Task.objects.get(name='New Manual Task')
        self.assertEqual(task.line_item_type, self.lit)


class TaskTemplateFormLineItemTypeTests(TestCase):
    """Test that TaskTemplate create/edit forms include line_item_type."""

    def setUp(self):
        self.client = Client()
        self.lit, _ = LineItemType.objects.get_or_create(code='SVC', defaults={'name': 'Service'})
        self.lit2, _ = LineItemType.objects.get_or_create(code='PRD', defaults={'name': 'Product'})

    def test_create_form_shows_line_item_type(self):
        """TaskTemplate create form should include line_item_type field."""
        url = reverse('jobs:add_task_template_standalone')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'line_item_type')

    def test_create_post_with_line_item_type(self):
        """POST to create TaskTemplate should save line_item_type."""
        url = reverse('jobs:add_task_template_standalone')
        response = self.client.post(url, {
            'template_name': 'New Template',
            'description': 'Test',
            'units': 'hours',
            'rate': '50.00',
            'line_item_type': self.lit.pk,
        })
        self.assertRedirects(response, reverse('jobs:task_template_list'))
        tt = TaskTemplate.objects.get(template_name='New Template')
        self.assertEqual(tt.line_item_type, self.lit)

    def test_edit_form_shows_line_item_type(self):
        """TaskTemplate edit form should include line_item_type field."""
        tt = TaskTemplate.objects.create(
            template_name='Existing', units='hours', rate=Decimal('50.00'),
            line_item_type=self.lit,
        )
        url = reverse('jobs:task_template_edit', args=[tt.template_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'line_item_type')

    def test_edit_post_can_change_line_item_type(self):
        """POST on TaskTemplate edit should update line_item_type."""
        tt = TaskTemplate.objects.create(
            template_name='Existing', units='hours', rate=Decimal('50.00'),
            line_item_type=self.lit,
        )
        url = reverse('jobs:task_template_edit', args=[tt.template_id])
        response = self.client.post(url, {
            'template_name': 'Existing',
            'description': '',
            'units': 'hours',
            'rate': '50.00',
            'line_item_type': self.lit2.pk,
        })
        self.assertRedirects(response, reverse('jobs:task_template_list'))
        tt.refresh_from_db()
        self.assertEqual(tt.line_item_type, self.lit2)


class TaskTemplateListLineItemTypeTests(TestCase):
    """Test that TaskTemplate list shows line_item_type column."""

    def setUp(self):
        self.client = Client()
        self.lit, _ = LineItemType.objects.get_or_create(code='SVC', defaults={'name': 'Service'})

    def test_list_shows_line_item_type_column(self):
        """TaskTemplate list should have a Line Item Type column header."""
        TaskTemplate.objects.create(
            template_name='Test Template', units='hours',
            rate=Decimal('50.00'), line_item_type=self.lit,
        )
        url = reverse('jobs:task_template_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Line Item Type')

    def test_list_shows_line_item_type_value(self):
        """TaskTemplate list should display the line item type name."""
        TaskTemplate.objects.create(
            template_name='Test Template', units='hours',
            rate=Decimal('50.00'), line_item_type=self.lit,
        )
        url = reverse('jobs:task_template_list')
        response = self.client.get(url)
        self.assertContains(response, 'Service')
