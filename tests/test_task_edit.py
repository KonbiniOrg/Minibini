"""
Tests for task detail view enhancements and task editing.
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.jobs.models import Job, EstWorksheet, Task, TaskTemplate
from apps.contacts.models import Contact
from decimal import Decimal

User = get_user_model()


class TaskDetailViewTests(TestCase):
    """Test the task detail view shows appropriate edit controls."""

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
            job_number='JOB-EDIT-001', contact=self.contact, status='approved'
        )

        self.draft_worksheet = EstWorksheet.objects.create(
            job=self.job, status='draft', version=1
        )
        self.final_worksheet = EstWorksheet.objects.create(
            job=self.job, status='final', version=2
        )

        self.draft_task = Task.objects.create(
            name='Draft Task', est_worksheet=self.draft_worksheet,
            units='hours', rate=Decimal('50.00'), est_qty=Decimal('2.00')
        )
        self.final_task = Task.objects.create(
            name='Final Task', est_worksheet=self.final_worksheet,
            units='sqft', rate=Decimal('10.00'), est_qty=Decimal('100.00')
        )

    def test_detail_shows_edit_link_for_draft_worksheet_task(self):
        """Task detail should show an Edit link when the task is on a draft worksheet."""
        url = reverse('jobs:task_detail', args=[self.draft_task.task_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        edit_url = reverse('jobs:task_edit', args=[self.draft_task.task_id])
        self.assertContains(response, edit_url)

    def test_detail_hides_edit_link_for_final_worksheet_task(self):
        """Task detail should NOT show an Edit link when the task is on a non-draft worksheet."""
        url = reverse('jobs:task_detail', args=[self.final_task.task_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Edit')

    def test_detail_links_back_to_worksheet(self):
        """Task detail should link back to its worksheet, not the task list."""
        url = reverse('jobs:task_detail', args=[self.draft_task.task_id])
        response = self.client.get(url)
        worksheet_url = reverse('jobs:estworksheet_detail', args=[self.draft_worksheet.est_worksheet_id])
        self.assertContains(response, worksheet_url)

    def test_worksheet_detail_shows_task_links(self):
        """Worksheet detail should link task names to their detail pages."""
        url = reverse('jobs:estworksheet_detail', args=[self.draft_worksheet.est_worksheet_id])
        response = self.client.get(url)
        task_detail_url = reverse('jobs:task_detail', args=[self.draft_task.task_id])
        self.assertContains(response, task_detail_url)


class TaskEditViewTests(TestCase):
    """Test task editing functionality."""

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
            job_number='JOB-EDIT-002', contact=self.contact, status='approved'
        )

        self.draft_worksheet = EstWorksheet.objects.create(
            job=self.job, status='draft', version=1
        )

        self.task = Task.objects.create(
            name='Editable Task', est_worksheet=self.draft_worksheet,
            units='hours', rate=Decimal('50.00'), est_qty=Decimal('2.00')
        )

    def test_edit_get_shows_form_with_current_values(self):
        """GET on task edit should show a form pre-filled with current task values."""
        url = reverse('jobs:task_edit', args=[self.task.task_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Editable Task')
        self.assertContains(response, '50.00')
        self.assertContains(response, '2.00')

    def test_edit_post_updates_task_fields(self):
        """POST on task edit should update the task's name, units, rate, and est_qty."""
        url = reverse('jobs:task_edit', args=[self.task.task_id])
        response = self.client.post(url, {
            'name': 'Updated Task',
            'units': 'sqft',
            'rate': '75.00',
            'est_qty': '10.00',
        })

        # Should redirect to task detail
        self.assertRedirects(
            response,
            reverse('jobs:task_detail', args=[self.task.task_id])
        )

        # Verify task was updated
        self.task.refresh_from_db()
        self.assertEqual(self.task.name, 'Updated Task')
        self.assertEqual(self.task.units, 'sqft')
        self.assertEqual(self.task.rate, Decimal('75.00'))
        self.assertEqual(self.task.est_qty, Decimal('10.00'))

    def test_edit_post_shows_success_message(self):
        """POST on task edit should show a success message."""
        url = reverse('jobs:task_edit', args=[self.task.task_id])
        response = self.client.post(url, {
            'name': 'Updated Task',
            'units': 'hours',
            'rate': '50.00',
            'est_qty': '3.00',
        }, follow=True)

        msgs = list(response.context['messages'])
        self.assertTrue(any('updated' in str(m).lower() for m in msgs))

    def test_edit_post_with_invalid_data_redisplays_form(self):
        """POST with missing required name should redisplay the form with errors."""
        url = reverse('jobs:task_edit', args=[self.task.task_id])
        response = self.client.post(url, {
            'name': '',  # required field
            'units': 'hours',
            'rate': '50.00',
            'est_qty': '2.00',
        })
        self.assertEqual(response.status_code, 200)
        # Task should NOT be changed
        self.task.refresh_from_db()
        self.assertEqual(self.task.name, 'Editable Task')


class TaskEditRestrictionTests(TestCase):
    """Test that task editing is restricted for non-draft worksheets."""

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
            job_number='JOB-EDIT-003', contact=self.contact, status='approved'
        )

        self.final_worksheet = EstWorksheet.objects.create(
            job=self.job, status='final', version=1
        )
        self.superseded_worksheet = EstWorksheet.objects.create(
            job=self.job, status='superseded', version=2
        )

        self.final_task = Task.objects.create(
            name='Final Task', est_worksheet=self.final_worksheet,
            units='hours', rate=Decimal('50.00'), est_qty=Decimal('2.00')
        )
        self.superseded_task = Task.objects.create(
            name='Superseded Task', est_worksheet=self.superseded_worksheet,
            units='hours', rate=Decimal('50.00'), est_qty=Decimal('2.00')
        )

    def test_edit_get_blocked_for_final_worksheet(self):
        """GET on task edit should redirect with error for final worksheet tasks."""
        url = reverse('jobs:task_edit', args=[self.final_task.task_id])
        response = self.client.get(url)
        self.assertRedirects(
            response,
            reverse('jobs:task_detail', args=[self.final_task.task_id])
        )
        msgs = list(response.wsgi_request._messages)
        self.assertTrue(any('cannot' in str(m).lower() for m in msgs))

    def test_edit_post_blocked_for_final_worksheet(self):
        """POST on task edit should redirect with error for final worksheet tasks."""
        url = reverse('jobs:task_edit', args=[self.final_task.task_id])
        response = self.client.post(url, {
            'name': 'Hacked Task',
            'units': 'hours',
            'rate': '999.00',
            'est_qty': '999.00',
        })
        self.assertRedirects(
            response,
            reverse('jobs:task_detail', args=[self.final_task.task_id])
        )
        # Task should NOT be changed
        self.final_task.refresh_from_db()
        self.assertEqual(self.final_task.name, 'Final Task')

    def test_edit_get_blocked_for_superseded_worksheet(self):
        """GET on task edit should redirect with error for superseded worksheet tasks."""
        url = reverse('jobs:task_edit', args=[self.superseded_task.task_id])
        response = self.client.get(url)
        self.assertRedirects(
            response,
            reverse('jobs:task_detail', args=[self.superseded_task.task_id])
        )
        msgs = list(response.wsgi_request._messages)
        self.assertTrue(any('cannot' in str(m).lower() for m in msgs))

    def test_edit_post_blocked_for_superseded_worksheet(self):
        """POST on task edit should redirect with error for superseded worksheet tasks."""
        url = reverse('jobs:task_edit', args=[self.superseded_task.task_id])
        response = self.client.post(url, {
            'name': 'Hacked Task',
            'units': 'hours',
            'rate': '999.00',
            'est_qty': '999.00',
        })
        self.assertRedirects(
            response,
            reverse('jobs:task_detail', args=[self.superseded_task.task_id])
        )
        self.superseded_task.refresh_from_db()
        self.assertEqual(self.superseded_task.name, 'Superseded Task')
