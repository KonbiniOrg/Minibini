from django.test import TestCase
from django.urls import reverse
from apps.jobs.models import Task, EstWorksheet, WorkOrder, Job
from apps.contacts.models import Contact, Business
from apps.core.models import User


class TaskReorderingTestCase(TestCase):
    """Test reordering of tasks within EstWorksheets and WorkOrders"""

    def setUp(self):
        """Set up test data"""
        # Create a user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )

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
            status='draft'
        )

        # Create an EstWorksheet
        self.worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='draft',
            version=1
        )

        # Create multiple tasks for the worksheet
        self.task1 = Task.objects.create(
            name='Task 1',
            est_worksheet=self.worksheet,
            est_qty=1.0,
            rate=100.00,
            units='hours'
        )
        self.task2 = Task.objects.create(
            name='Task 2',
            est_worksheet=self.worksheet,
            est_qty=2.0,
            rate=200.00,
            units='hours'
        )
        self.task3 = Task.objects.create(
            name='Task 3',
            est_worksheet=self.worksheet,
            est_qty=3.0,
            rate=300.00,
            units='hours'
        )

        # Create a work order
        self.work_order = WorkOrder.objects.create(
            job=self.job,
            status='incomplete'
        )

        # Create tasks for the work order
        self.wo_task1 = Task.objects.create(
            name='WO Task 1',
            work_order=self.work_order,
            est_qty=1.0,
            rate=50.00,
            units='hours'
        )
        self.wo_task2 = Task.objects.create(
            name='WO Task 2',
            work_order=self.work_order,
            est_qty=2.0,
            rate=75.00,
            units='hours'
        )
        self.wo_task3 = Task.objects.create(
            name='WO Task 3',
            work_order=self.work_order,
            est_qty=3.0,
            rate=100.00,
            units='hours'
        )

    def test_worksheet_tasks_have_line_numbers(self):
        """Test that tasks are automatically assigned line numbers"""
        self.assertIsNotNone(self.task1.line_number)
        self.assertIsNotNone(self.task2.line_number)
        self.assertIsNotNone(self.task3.line_number)
        self.assertEqual(self.task1.line_number, 1)
        self.assertEqual(self.task2.line_number, 2)
        self.assertEqual(self.task3.line_number, 3)

    def test_work_order_tasks_have_line_numbers(self):
        """Test that work order tasks are automatically assigned line numbers"""
        self.assertIsNotNone(self.wo_task1.line_number)
        self.assertIsNotNone(self.wo_task2.line_number)
        self.assertIsNotNone(self.wo_task3.line_number)
        self.assertEqual(self.wo_task1.line_number, 1)
        self.assertEqual(self.wo_task2.line_number, 2)
        self.assertEqual(self.wo_task3.line_number, 3)

    def test_reorder_worksheet_task_down(self):
        """Test moving a task down in the worksheet"""
        url = reverse('jobs:task_reorder_worksheet', kwargs={
            'worksheet_id': self.worksheet.est_worksheet_id,
            'task_id': self.task1.task_id,
            'direction': 'down'
        })
        response = self.client.post(url)

        # Should redirect back to worksheet detail
        self.assertEqual(response.status_code, 302)

        # Refresh tasks from database
        self.task1.refresh_from_db()
        self.task2.refresh_from_db()

        # Task 1 should now have line_number 2, Task 2 should have line_number 1
        self.assertEqual(self.task1.line_number, 2)
        self.assertEqual(self.task2.line_number, 1)

    def test_reorder_worksheet_task_up(self):
        """Test moving a task up in the worksheet"""
        url = reverse('jobs:task_reorder_worksheet', kwargs={
            'worksheet_id': self.worksheet.est_worksheet_id,
            'task_id': self.task2.task_id,
            'direction': 'up'
        })
        response = self.client.post(url)

        # Should redirect back to worksheet detail
        self.assertEqual(response.status_code, 302)

        # Refresh tasks from database
        self.task1.refresh_from_db()
        self.task2.refresh_from_db()

        # Task 2 should now have line_number 1, Task 1 should have line_number 2
        self.assertEqual(self.task2.line_number, 1)
        self.assertEqual(self.task1.line_number, 2)

    def test_cannot_move_first_task_up(self):
        """Test that first task cannot be moved up"""
        url = reverse('jobs:task_reorder_worksheet', kwargs={
            'worksheet_id': self.worksheet.est_worksheet_id,
            'task_id': self.task1.task_id,
            'direction': 'up'
        })
        response = self.client.post(url)

        # Should redirect back
        self.assertEqual(response.status_code, 302)

        # Refresh task from database
        self.task1.refresh_from_db()

        # Task 1 should still have line_number 1
        self.assertEqual(self.task1.line_number, 1)

    def test_cannot_move_last_task_down(self):
        """Test that last task cannot be moved down"""
        url = reverse('jobs:task_reorder_worksheet', kwargs={
            'worksheet_id': self.worksheet.est_worksheet_id,
            'task_id': self.task3.task_id,
            'direction': 'down'
        })
        response = self.client.post(url)

        # Should redirect back
        self.assertEqual(response.status_code, 302)

        # Refresh task from database
        self.task3.refresh_from_db()

        # Task 3 should still have line_number 3
        self.assertEqual(self.task3.line_number, 3)

    def test_cannot_reorder_non_draft_worksheet(self):
        """Test that tasks in non-draft worksheets cannot be reordered"""
        # Mark worksheet as final
        self.worksheet.status = 'final'
        self.worksheet.save()

        url = reverse('jobs:task_reorder_worksheet', kwargs={
            'worksheet_id': self.worksheet.est_worksheet_id,
            'task_id': self.task1.task_id,
            'direction': 'down'
        })
        response = self.client.post(url)

        # Should redirect back
        self.assertEqual(response.status_code, 302)

        # Refresh task from database
        self.task1.refresh_from_db()

        # Task 1 should still have original line_number
        self.assertEqual(self.task1.line_number, 1)

    def test_reorder_work_order_task_down(self):
        """Test moving a work order task down"""
        url = reverse('jobs:task_reorder_work_order', kwargs={
            'work_order_id': self.work_order.work_order_id,
            'task_id': self.wo_task1.task_id,
            'direction': 'down'
        })
        response = self.client.post(url)

        # Should redirect back to work order detail
        self.assertEqual(response.status_code, 302)

        # Refresh tasks from database
        self.wo_task1.refresh_from_db()
        self.wo_task2.refresh_from_db()

        # WO Task 1 should now have line_number 2, WO Task 2 should have line_number 1
        self.assertEqual(self.wo_task1.line_number, 2)
        self.assertEqual(self.wo_task2.line_number, 1)

    def test_reorder_work_order_task_up(self):
        """Test moving a work order task up"""
        url = reverse('jobs:task_reorder_work_order', kwargs={
            'work_order_id': self.work_order.work_order_id,
            'task_id': self.wo_task3.task_id,
            'direction': 'up'
        })
        response = self.client.post(url)

        # Should redirect back to work order detail
        self.assertEqual(response.status_code, 302)

        # Refresh tasks from database
        self.wo_task2.refresh_from_db()
        self.wo_task3.refresh_from_db()

        # WO Task 3 should now have line_number 2, WO Task 2 should have line_number 3
        self.assertEqual(self.wo_task3.line_number, 2)
        self.assertEqual(self.wo_task2.line_number, 3)
