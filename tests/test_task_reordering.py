from django.test import TestCase
from django.urls import reverse
from apps.jobs.models import Task, PlanTask, Job
from apps.estimates.models import EstWorksheet
from apps.contacts.models import Contact, Business
from apps.core.models import User


class TaskReorderingTestCase(TestCase):
    """Test reordering of tasks within EstWorksheets."""

    def setUp(self):
        """Set up test data"""
        # Create a user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            is_superuser=True
        )
        self.client.force_login(self.user)

        # Create a default contact (must be created before business)
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')

        # Create a business and contact
        self.business = Business.objects.create(
            business_name='Test Company',
            business_phone='12-3456789',
            default_contact=self.default_contact
        )
        self.contact = Contact.objects.create(
            first_name='John Doe',
            last_name='',
            email='john@example.com',
            business=self.business
        )

        # Create a job
        self.job = Job.objects.create(
            job_number='JOB-001',
            name='Test Job',
            contact=self.contact,
            status=Job.STATUS_DRAFT
        )

        # Create an EstWorksheet
        self.worksheet = EstWorksheet.objects.create(
            job=self.job,
            status=Job.STATUS_DRAFT,
            version=1
        )

        # Create multiple plan tasks for the worksheet
        self.task1 = PlanTask.objects.create(
            name='Task 1',
            est_worksheet=self.worksheet,



        )
        self.task2 = PlanTask.objects.create(
            name='Task 2',
            est_worksheet=self.worksheet,



        )
        self.task3 = PlanTask.objects.create(
            name='Task 3',
            est_worksheet=self.worksheet,



        )

        # Create tasks directly on the job (post-WorkOrder-removal)
        self.wo_task1 = Task.objects.create(
            name='WO Task 1',
            job=self.job,
            est_qty=1.0,
            rate=50.00,
            units='hours'
        )
        self.wo_task2 = Task.objects.create(
            name='WO Task 2',
            job=self.job,
            est_qty=2.0,
            rate=75.00,
            units='hours'
        )
        self.wo_task3 = Task.objects.create(
            name='WO Task 3',
            job=self.job,
            est_qty=3.0,
            rate=100.00,
            units='hours'
        )

    def test_worksheet_tasks_have_sort_orders(self):
        """Test that tasks are automatically assigned line numbers"""
        self.assertIsNotNone(self.task1.sort_order)
        self.assertIsNotNone(self.task2.sort_order)
        self.assertIsNotNone(self.task3.sort_order)
        self.assertEqual(self.task1.sort_order, 1)
        self.assertEqual(self.task2.sort_order, 2)
        self.assertEqual(self.task3.sort_order, 3)

    def test_job_tasks_have_sort_orders(self):
        """Test that job tasks are automatically assigned line numbers"""
        self.assertIsNotNone(self.wo_task1.sort_order)
        self.assertIsNotNone(self.wo_task2.sort_order)
        self.assertIsNotNone(self.wo_task3.sort_order)
        self.assertEqual(self.wo_task1.sort_order, 1)
        self.assertEqual(self.wo_task2.sort_order, 2)
        self.assertEqual(self.wo_task3.sort_order, 3)

    def test_reorder_worksheet_task_down(self):
        """Test moving a task down in the worksheet"""
        url = reverse('estimates:task_reorder_worksheet', kwargs={
            'worksheet_id': self.worksheet.est_worksheet_id,
            'task_id': self.task1.pk,
            'direction': 'down'
        })
        response = self.client.post(url)

        # Should redirect back to worksheet detail
        self.assertEqual(response.status_code, 302)

        # Refresh tasks from database
        self.task1.refresh_from_db()
        self.task2.refresh_from_db()

        # Task 1 should now have sort_order 2, Task 2 should have sort_order 1
        self.assertEqual(self.task1.sort_order, 2)
        self.assertEqual(self.task2.sort_order, 1)

    def test_reorder_worksheet_task_up(self):
        """Test moving a task up in the worksheet"""
        url = reverse('estimates:task_reorder_worksheet', kwargs={
            'worksheet_id': self.worksheet.est_worksheet_id,
            'task_id': self.task2.pk,
            'direction': 'up'
        })
        response = self.client.post(url)

        # Should redirect back to worksheet detail
        self.assertEqual(response.status_code, 302)

        # Refresh tasks from database
        self.task1.refresh_from_db()
        self.task2.refresh_from_db()

        # Task 2 should now have sort_order 1, Task 1 should have sort_order 2
        self.assertEqual(self.task2.sort_order, 1)
        self.assertEqual(self.task1.sort_order, 2)

    def test_cannot_move_first_task_up(self):
        """Test that first task cannot be moved up"""
        url = reverse('estimates:task_reorder_worksheet', kwargs={
            'worksheet_id': self.worksheet.est_worksheet_id,
            'task_id': self.task1.pk,
            'direction': 'up'
        })
        response = self.client.post(url)

        # Should redirect back
        self.assertEqual(response.status_code, 302)

        # Refresh task from database
        self.task1.refresh_from_db()

        # Task 1 should still have sort_order 1
        self.assertEqual(self.task1.sort_order, 1)

    def test_cannot_move_last_task_down(self):
        """Test that last task cannot be moved down"""
        url = reverse('estimates:task_reorder_worksheet', kwargs={
            'worksheet_id': self.worksheet.est_worksheet_id,
            'task_id': self.task3.pk,
            'direction': 'down'
        })
        response = self.client.post(url)

        # Should redirect back
        self.assertEqual(response.status_code, 302)

        # Refresh task from database
        self.task3.refresh_from_db()

        # Task 3 should still have sort_order 3
        self.assertEqual(self.task3.sort_order, 3)

    def test_cannot_reorder_non_draft_worksheet(self):
        """Test that tasks in non-draft worksheets cannot be reordered"""
        # Mark worksheet as final
        self.worksheet.status = EstWorksheet.STATUS_FINAL
        self.worksheet.save()

        url = reverse('estimates:task_reorder_worksheet', kwargs={
            'worksheet_id': self.worksheet.est_worksheet_id,
            'task_id': self.task1.pk,
            'direction': 'down'
        })
        response = self.client.post(url)

        # Should redirect back
        self.assertEqual(response.status_code, 302)

        # Refresh task from database
        self.task1.refresh_from_db()

        # Task 1 should still have original sort_order
        self.assertEqual(self.task1.sort_order, 1)

    # Note: HTML-level reorder for work-order tasks was removed with
    # WorkOrder removal. Task reordering on the job is exercised via the
    # REST API (/api/tasks/reorder/) in tests/test_board_api.py.
