"""
Tests for Task description field and decoupling task data from templates.

Tasks should have their own description field. When created from a template,
the description is copied from the template. After creation, the task's
description is independent of the template.
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.jobs.models import Job, EstWorksheet, Task, TaskTemplate, WorkOrderTemplate
from apps.contacts.models import Contact
from apps.core.models import LineItemType
from decimal import Decimal

User = get_user_model()


class TaskDescriptionModelTests(TestCase):
    """Test that Task has its own description field."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(
            job_number='JOB-DESC-001', contact=self.contact, status='approved'
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status='draft', version=1
        )

    def test_task_can_have_description(self):
        """Task should have a description field that can be set directly."""
        task = Task.objects.create(
            name='Described Task',
            description='This is a task description',
            est_worksheet=self.worksheet,
            units='hours',
            rate=Decimal('50.00'),
            est_qty=Decimal('2.00'),
        )
        task.refresh_from_db()
        self.assertEqual(task.description, 'This is a task description')

    def test_task_description_defaults_to_blank(self):
        """Task description should default to empty string."""
        task = Task.objects.create(
            name='No Description Task',
            est_worksheet=self.worksheet,
            units='hours',
            rate=Decimal('50.00'),
            est_qty=Decimal('2.00'),
        )
        task.refresh_from_db()
        self.assertEqual(task.description, '')


class TaskDescriptionFromTemplateTests(TestCase):
    """Test that description is copied from template when creating tasks."""

    def setUp(self):
        self.line_item_type = LineItemType.objects.create(name='Labor')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(
            job_number='JOB-DESC-002', contact=self.contact, status='approved'
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status='draft', version=1
        )
        self.task_template = TaskTemplate.objects.create(
            template_name='Painting',
            description='Apply two coats of primer and paint',
            units='sqft',
            rate=Decimal('3.50'),
            line_item_type=self.line_item_type,
        )

    def test_generate_task_copies_description_from_template(self):
        """TaskTemplate.generate_task() should copy description to the new task."""
        task = self.task_template.generate_task(
            self.worksheet, est_qty=Decimal('100.00')
        )
        self.assertEqual(task.description, 'Apply two coats of primer and paint')

    def test_add_task_from_template_view_copies_description(self):
        """Adding a task from template via the view should copy the description."""
        client = Client()
        user = User.objects.create_user(
            username='testuser', password='testpass', email='test@example.com'
        )
        client.login(username='testuser', password='testpass')

        url = reverse('jobs:task_add_from_template', args=[self.worksheet.est_worksheet_id])
        client.post(url, {
            'template': self.task_template.template_id,
            'est_qty': '50.0',
        })

        task = Task.objects.get(est_worksheet=self.worksheet)
        self.assertEqual(task.description, 'Apply two coats of primer and paint')


class TaskDescriptionInViewsTests(TestCase):
    """Test that description appears in task detail and edit views."""

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
            job_number='JOB-DESC-003', contact=self.contact, status='approved'
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status='draft', version=1
        )
        self.task = Task.objects.create(
            name='Detailed Task',
            description='Sand and finish hardwood floors',
            est_worksheet=self.worksheet,
            units='sqft',
            rate=Decimal('5.00'),
            est_qty=Decimal('200.00'),
        )

    def test_task_detail_shows_description(self):
        """Task detail page should display the task's description."""
        url = reverse('jobs:task_detail', args=[self.task.task_id])
        response = self.client.get(url)
        self.assertContains(response, 'Sand and finish hardwood floors')

    def test_task_edit_shows_description_field(self):
        """Task edit form should include the description field."""
        url = reverse('jobs:task_edit', args=[self.task.task_id])
        response = self.client.get(url)
        self.assertContains(response, 'Sand and finish hardwood floors')

    def test_task_edit_can_update_description(self):
        """Editing a task should allow updating the description."""
        url = reverse('jobs:task_edit', args=[self.task.task_id])
        response = self.client.post(url, {
            'name': 'Detailed Task',
            'description': 'Updated: sand, stain, and finish hardwood floors',
            'units': 'sqft',
            'rate': '5.00',
            'est_qty': '200.00',
        })
        self.assertRedirects(
            response,
            reverse('jobs:task_detail', args=[self.task.task_id])
        )
        self.task.refresh_from_db()
        self.assertEqual(self.task.description, 'Updated: sand, stain, and finish hardwood floors')


class WorksheetDescriptionFromTaskTests(TestCase):
    """Test that worksheet bundle table uses task's own description, not template's."""

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
            job_number='JOB-DESC-004', contact=self.contact, status='approved'
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status='draft', version=1
        )
        self.task = Task.objects.create(
            name='Task With Own Desc',
            description='My own description',
            est_worksheet=self.worksheet,
            units='hours',
            rate=Decimal('50.00'),
            est_qty=Decimal('2.00'),
        )

    def test_worksheet_detail_shows_task_own_description(self):
        """Worksheet detail should show the task's own description, not the template's."""
        url = reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        response = self.client.get(url)
        self.assertContains(response, 'My own description')


class TaskAddManualDescriptionTests(TestCase):
    """Test that manually adding a task supports description and uses consistent template."""

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
            job_number='JOB-DESC-005', contact=self.contact, status='approved'
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status='draft', version=1
        )

    def test_manual_add_form_includes_description_field(self):
        """The manual add task form should include a description field."""
        url = reverse('jobs:task_add_manual', args=[self.worksheet.est_worksheet_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'description')

    def test_manual_add_saves_description(self):
        """Manually adding a task with a description should save it."""
        url = reverse('jobs:task_add_manual', args=[self.worksheet.est_worksheet_id])
        response = self.client.post(url, {
            'name': 'Manual Task',
            'description': 'Do the thing carefully',
            'units': 'hours',
            'rate': '75.00',
            'est_qty': '3.0',
        })
        self.assertRedirects(
            response,
            reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        )
        task = Task.objects.get(est_worksheet=self.worksheet)
        self.assertEqual(task.description, 'Do the thing carefully')

    def test_manual_add_page_extends_base_template(self):
        """The manual add page should extend base.html like other pages."""
        url = reverse('jobs:task_add_manual', args=[self.worksheet.est_worksheet_id])
        response = self.client.get(url)
        # base.html renders the <title> tag via block
        self.assertContains(response, '<title>')
