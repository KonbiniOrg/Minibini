"""
Test that tasks cannot be added to non-draft worksheets.
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.jobs.models import Job, EstWorksheet, Task, TaskTemplate, TaskMapping
from apps.contacts.models import Contact
from decimal import Decimal

User = get_user_model()


class WorksheetTaskRestrictionTests(TestCase):
    """Test that task additions are restricted for non-draft worksheets."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass',
            email='test@example.com'
        )
        self.client.login(username='testuser', password='testpass')

        # Create contact
        self.contact = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='contact@test.com'
        )

        # Create job
        self.job = Job.objects.create(
            job_number='JOB-TEST-001',
            contact=self.contact,
            status='approved'
        )

        # Create task mapping for test
        self.task_mapping = TaskMapping.objects.create(
            step_type='labor',
            mapping_strategy='direct',
            task_type_id='TEST',
            breakdown_of_task='Test task',
            line_item_name='Test Labor',
            line_item_description='Test labor description'
        )

        # Create task template
        self.task_template = TaskTemplate.objects.create(
            template_name='Test Template',
            task_mapping=self.task_mapping,
            units='hours',
            rate=Decimal('50.00')
        )

        # Create worksheets in different states
        self.draft_worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='draft',
            version=1
        )

        self.final_worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='final',
            version=2
        )

        self.superseded_worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='superseded',
            version=3
        )

    def test_can_add_task_to_draft_worksheet(self):
        """Test that tasks can be added to draft worksheets (control test)."""
        url = reverse('jobs:task_add_from_template', args=[self.draft_worksheet.est_worksheet_id])

        # POST to add task
        response = self.client.post(url, {
            'template': self.task_template.template_id,
            'est_qty': '2.0'
        })

        # Should redirect to worksheet detail
        self.assertRedirects(
            response,
            reverse('jobs:estworksheet_detail', args=[self.draft_worksheet.est_worksheet_id])
        )

        # Verify task was created
        tasks = Task.objects.filter(est_worksheet=self.draft_worksheet)
        self.assertEqual(tasks.count(), 1)

        task = tasks.first()
        self.assertEqual(task.template, self.task_template)
        self.assertEqual(task.est_qty, Decimal('2.0'))

    def test_cannot_add_task_from_template_to_final_worksheet(self):
        """Test that adding task from template to final worksheet is rejected."""
        url = reverse('jobs:task_add_from_template', args=[self.final_worksheet.est_worksheet_id])

        # Attempt to add task via POST
        response = self.client.post(url, {
            'template': self.task_template.template_id,
            'est_qty': '2.0'
        })

        # Should redirect back to worksheet detail
        self.assertRedirects(
            response,
            reverse('jobs:estworksheet_detail', args=[self.final_worksheet.est_worksheet_id])
        )

        # Check for error message
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any('Cannot add tasks to a final worksheet' in str(m) for m in messages))

        # Verify no task was created
        tasks = Task.objects.filter(est_worksheet=self.final_worksheet)
        self.assertEqual(tasks.count(), 0)

    def test_cannot_add_task_from_template_to_superseded_worksheet(self):
        """Test that adding task from template to superseded worksheet is rejected."""
        url = reverse('jobs:task_add_from_template', args=[self.superseded_worksheet.est_worksheet_id])

        # Attempt to add task via POST
        response = self.client.post(url, {
            'template': self.task_template.template_id,
            'est_qty': '2.0'
        })

        # Should redirect back to worksheet detail
        self.assertRedirects(
            response,
            reverse('jobs:estworksheet_detail', args=[self.superseded_worksheet.est_worksheet_id])
        )

        # Check for error message
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any('Cannot add tasks to a superseded worksheet' in str(m) for m in messages))

        # Verify no task was created
        tasks = Task.objects.filter(est_worksheet=self.superseded_worksheet)
        self.assertEqual(tasks.count(), 0)

    def test_cannot_add_task_manually_to_final_worksheet(self):
        """Test that adding task manually to final worksheet is rejected."""
        url = reverse('jobs:task_add_manual', args=[self.final_worksheet.est_worksheet_id])

        # Attempt to add task via POST
        response = self.client.post(url, {
            'name': 'Manual Task',
            'units': 'hours',
            'rate': '75.00',
            'est_qty': '3.0',
            'est_worksheet': self.final_worksheet.est_worksheet_id
        })

        # Should redirect back to worksheet detail
        self.assertRedirects(
            response,
            reverse('jobs:estworksheet_detail', args=[self.final_worksheet.est_worksheet_id])
        )

        # Check for error message
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any('Cannot add tasks to a final worksheet' in str(m) for m in messages))

        # Verify no task was created
        tasks = Task.objects.filter(est_worksheet=self.final_worksheet)
        self.assertEqual(tasks.count(), 0)

    def test_cannot_add_task_manually_to_superseded_worksheet(self):
        """Test that adding task manually to superseded worksheet is rejected."""
        url = reverse('jobs:task_add_manual', args=[self.superseded_worksheet.est_worksheet_id])

        # Attempt to add task via POST
        response = self.client.post(url, {
            'name': 'Manual Task',
            'units': 'hours',
            'rate': '75.00',
            'est_qty': '3.0',
            'est_worksheet': self.superseded_worksheet.est_worksheet_id
        })

        # Should redirect back to worksheet detail
        self.assertRedirects(
            response,
            reverse('jobs:estworksheet_detail', args=[self.superseded_worksheet.est_worksheet_id])
        )

        # Check for error message
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any('Cannot add tasks to a superseded worksheet' in str(m) for m in messages))

        # Verify no task was created
        tasks = Task.objects.filter(est_worksheet=self.superseded_worksheet)
        self.assertEqual(tasks.count(), 0)

    def test_get_request_rejected_for_final_worksheet_template_addition(self):
        """Test that GET request for task template addition is rejected for final worksheet."""
        url = reverse('jobs:task_add_from_template', args=[self.final_worksheet.est_worksheet_id])

        # Attempt GET request
        response = self.client.get(url)

        # Should redirect back to worksheet detail
        self.assertRedirects(
            response,
            reverse('jobs:estworksheet_detail', args=[self.final_worksheet.est_worksheet_id])
        )

        # Check for error message
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any('Cannot add tasks to a final worksheet' in str(m) for m in messages))

    def test_get_request_rejected_for_final_worksheet_manual_addition(self):
        """Test that GET request for manual task addition is rejected for final worksheet."""
        url = reverse('jobs:task_add_manual', args=[self.final_worksheet.est_worksheet_id])

        # Attempt GET request
        response = self.client.get(url)

        # Should redirect back to worksheet detail
        self.assertRedirects(
            response,
            reverse('jobs:estworksheet_detail', args=[self.final_worksheet.est_worksheet_id])
        )

        # Check for error message
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any('Cannot add tasks to a final worksheet' in str(m) for m in messages))

    def test_task_addition_links_hidden_for_final_worksheet(self):
        """Test that task addition links are hidden for final worksheets in the UI."""
        url = reverse('jobs:estworksheet_detail', args=[self.final_worksheet.est_worksheet_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check that task addition links are not present
        self.assertNotContains(response, 'Add Task from Template')
        self.assertNotContains(response, 'Add Task Manually')

        # Check that restriction message is shown
        self.assertContains(response, 'Tasks cannot be added to a final worksheet')

    def test_task_addition_links_hidden_for_superseded_worksheet(self):
        """Test that task addition links are hidden for superseded worksheets in the UI."""
        url = reverse('jobs:estworksheet_detail', args=[self.superseded_worksheet.est_worksheet_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check that task addition links are not present
        self.assertNotContains(response, 'Add Task from Template')
        self.assertNotContains(response, 'Add Task Manually')

        # Check that restriction message is shown
        self.assertContains(response, 'Tasks cannot be added to a superseded worksheet')

    def test_task_addition_links_visible_for_draft_worksheet(self):
        """Test that task addition links are visible for draft worksheets (control test)."""
        url = reverse('jobs:estworksheet_detail', args=[self.draft_worksheet.est_worksheet_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check that task addition links are present
        self.assertContains(response, 'Add Task from Template')
        self.assertContains(response, 'Add Task Manually')

        # Check that restriction message is NOT shown
        self.assertNotContains(response, 'Tasks cannot be added to a')

    def test_can_add_task_manually_to_draft_worksheet(self):
        """Test that tasks can be added manually to draft worksheets (control test)."""
        url = reverse('jobs:task_add_manual', args=[self.draft_worksheet.est_worksheet_id])

        # POST to add task
        response = self.client.post(url, {
            'name': 'Manual Task',
            'units': 'hours',
            'rate': '75.00',
            'est_qty': '3.0',
            'est_worksheet': self.draft_worksheet.est_worksheet_id
        })

        # Should redirect to worksheet detail
        self.assertRedirects(
            response,
            reverse('jobs:estworksheet_detail', args=[self.draft_worksheet.est_worksheet_id])
        )

        # Verify task was created
        tasks = Task.objects.filter(est_worksheet=self.draft_worksheet)
        self.assertEqual(tasks.count(), 1)

        task = tasks.first()
        self.assertEqual(task.name, 'Manual Task')
        self.assertEqual(task.rate, Decimal('75.00'))
        self.assertEqual(task.est_qty, Decimal('3.0'))


class WorksheetTaskWorkflowTests(TestCase):
    """Test task addition workflow as worksheet status changes."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass',
            email='test@example.com'
        )
        self.client.login(username='testuser', password='testpass')

        # Create contact
        self.contact = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='contact@test.com'
        )

        # Create job
        self.job = Job.objects.create(
            job_number='JOB-TEST-001',
            contact=self.contact,
            status='approved'
        )

        # Create task mapping
        self.task_mapping = TaskMapping.objects.create(
            step_type='labor',
            mapping_strategy='direct',
            task_type_id='TEST',
            breakdown_of_task='Test task',
            line_item_name='Test Labor',
            line_item_description='Test labor description'
        )

        # Create task template
        self.task_template = TaskTemplate.objects.create(
            template_name='Test Template',
            task_mapping=self.task_mapping,
            units='hours',
            rate=Decimal('50.00')
        )

    def test_task_addition_blocked_after_worksheet_finalization(self):
        """Test that task addition is blocked after worksheet becomes final."""
        # Create draft worksheet
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='draft',
            version=1
        )

        # Verify we can add tasks while draft
        url = reverse('jobs:task_add_from_template', args=[worksheet.est_worksheet_id])
        response = self.client.post(url, {
            'template': self.task_template.template_id,
            'est_qty': '1.0'
        })

        self.assertRedirects(
            response,
            reverse('jobs:estworksheet_detail', args=[worksheet.est_worksheet_id])
        )

        # Verify task was added
        self.assertEqual(Task.objects.filter(est_worksheet=worksheet).count(), 1)

        # Mark worksheet as final
        worksheet.status = 'final'
        worksheet.save()

        # Attempt to add another task
        response2 = self.client.post(url, {
            'template': self.task_template.template_id,
            'est_qty': '2.0'
        })

        # Should be rejected
        self.assertRedirects(
            response2,
            reverse('jobs:estworksheet_detail', args=[worksheet.est_worksheet_id])
        )

        # Check for error message
        messages = list(response2.wsgi_request._messages)
        self.assertTrue(any('Cannot add tasks to a final worksheet' in str(m) for m in messages))

        # Verify only the original task exists
        self.assertEqual(Task.objects.filter(est_worksheet=worksheet).count(), 1)