from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.jobs.models import Job, WorkOrder, Task
from apps.estimates.models import Estimate, EstWorksheet, WorkOrderTemplate, TaskTemplate
from apps.contacts.models import Contact

User = get_user_model()


class WorkOrderFromEstimateTestCase(TestCase):
    """Test creating WorkOrders from Estimates"""

    fixtures = ['workorder_from_estimate.json']

    def setUp(self):
        self.client = Client()
        # Create a test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

    def test_create_workorder_from_accepted_estimate_with_worksheet(self):
        """Test creating a WorkOrder from an accepted estimate with an associated worksheet.
        When a worksheet exists, tasks are copied directly from the worksheet (not from line items)."""
        estimate = Estimate.objects.get(pk=100)
        worksheet = EstWorksheet.objects.get(pk=100)

        # Verify initial state
        self.assertEqual(estimate.status, 'accepted')
        self.assertEqual(worksheet.estimate_id, estimate.estimate_id)
        initial_task_count = Task.objects.filter(est_worksheet=worksheet).count()
        self.assertEqual(initial_task_count, 5)  # 1 parent + 2 children + 2 standalone

        # GET request - should show confirmation page
        url = reverse('jobs:work_order_create_from_estimate', kwargs={'estimate_id': estimate.estimate_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Work Order from Estimate')
        self.assertContains(response, estimate.estimate_number)
        self.assertContains(response, 'Tasks, bundles, and materials will be copied directly from the worksheet.')

        # POST request - create the WorkOrder
        response = self.client.post(url, follow=True)

        # Check WorkOrder was created
        work_orders = WorkOrder.objects.filter(job=estimate.job)
        self.assertEqual(work_orders.count(), 1)
        work_order = work_orders.first()

        # Verify WorkOrder properties
        self.assertEqual(work_order.status, 'draft')
        self.assertEqual(work_order.job_id, estimate.job_id)
        self.assertEqual(work_order.template_id, worksheet.template_id)

        # Verify tasks were copied from worksheet (5 tasks, not 3 line items)
        wo_tasks = Task.objects.filter(work_order=work_order).order_by('task_id')
        self.assertEqual(wo_tasks.count(), 5)

        # Check success message
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertIn(f'Work Order {work_order.work_order_id} created successfully', str(messages[0]))

        # Check redirect to work order detail
        self.assertRedirects(
            response,
            reverse('jobs:work_order_detail', kwargs={'work_order_id': work_order.work_order_id})
        )

    def test_create_workorder_from_accepted_estimate_without_worksheet(self):
        """Test creating a WorkOrder from an accepted estimate without a worksheet"""
        estimate = Estimate.objects.get(pk=103)  # This estimate has no worksheet

        # Verify no worksheet exists
        worksheet_count = EstWorksheet.objects.filter(estimate=estimate).count()
        self.assertEqual(worksheet_count, 0)

        # POST request - create the WorkOrder
        url = reverse('jobs:work_order_create_from_estimate', kwargs={'estimate_id': estimate.estimate_id})
        response = self.client.post(url, follow=True)

        # Check WorkOrder was created
        work_orders = WorkOrder.objects.filter(job=estimate.job)
        # Note: Job 100 might have other work orders from previous test
        work_order = work_orders.last()  # Get the most recently created

        # Verify WorkOrder properties
        self.assertEqual(work_order.status, 'draft')
        self.assertEqual(work_order.job_id, estimate.job_id)
        self.assertIsNone(work_order.template)

        # Verify no tasks were created
        wo_tasks = Task.objects.filter(work_order=work_order)
        self.assertEqual(wo_tasks.count(), 0)

        # Check success message
        messages = list(response.context['messages'])
        self.assertTrue(any(f'Work Order {work_order.work_order_id} created successfully' in str(m) for m in messages))

    def test_cannot_create_workorder_from_non_accepted_estimate(self):
        """Test that WorkOrders cannot be created from estimates with status != accepted"""
        test_cases = [
            (101, 'open'),
            (102, 'draft'),
        ]

        for estimate_id, expected_status in test_cases:
            with self.subTest(estimate_id=estimate_id, status=expected_status):
                estimate = Estimate.objects.get(pk=estimate_id)
                self.assertEqual(estimate.status, expected_status)

                url = reverse('jobs:work_order_create_from_estimate', kwargs={'estimate_id': estimate_id})
                response = self.client.post(url, follow=True)

                # Should redirect back to estimate detail with error message
                self.assertRedirects(
                    response,
                    reverse('jobs:estimate_detail', kwargs={'estimate_id': estimate_id})
                )

                # Check error message
                messages = list(response.context['messages'])
                self.assertTrue(any('Work Orders can only be created from accepted estimates' in str(m) for m in messages))

                # Verify no WorkOrder was created
                work_orders = WorkOrder.objects.filter(job=estimate.job)
                self.assertEqual(work_orders.count(), 0)

    def test_tasks_copied_from_worksheet(self):
        """Test that tasks are copied from worksheet when one exists (not from line items)."""
        estimate = Estimate.objects.get(pk=100)
        worksheet = EstWorksheet.objects.get(pk=100)

        # Verify worksheet has 5 tasks
        ws_task_count = Task.objects.filter(est_worksheet=worksheet).count()
        self.assertEqual(ws_task_count, 5)

        # Create WorkOrder
        url = reverse('jobs:work_order_create_from_estimate', kwargs={'estimate_id': estimate.estimate_id})
        response = self.client.post(url, follow=True)

        # Get the created WorkOrder
        work_order = WorkOrder.objects.filter(job=estimate.job).first()

        # Verify 5 tasks created (copied from worksheet, not 3 from line items)
        wo_tasks = Task.objects.filter(work_order=work_order)
        self.assertEqual(wo_tasks.count(), 5)

        # Verify task names match worksheet tasks
        ws_task_names = set(Task.objects.filter(est_worksheet=worksheet).values_list('name', flat=True))
        wo_task_names = set(wo_tasks.values_list('name', flat=True))
        self.assertEqual(wo_task_names, ws_task_names)

    def test_worksheet_tasks_copied_to_work_order(self):
        """Test that worksheet tasks are copied with correct names to work order."""
        estimate = Estimate.objects.get(pk=100)

        # Create WorkOrder
        url = reverse('jobs:work_order_create_from_estimate', kwargs={'estimate_id': estimate.estimate_id})
        response = self.client.post(url)

        work_order = WorkOrder.objects.filter(job=estimate.job).first()

        # Verify tasks from worksheet exist on work order
        parent_task = Task.objects.get(
            work_order=work_order,
            name="Parent Task - Assembly"
        )
        self.assertIsNotNone(parent_task)

        task_delivery = Task.objects.get(
            work_order=work_order,
            name="Standalone Task - Material Delivery"
        )
        self.assertIsNotNone(task_delivery)

    def test_confirmation_page_displays_correct_info(self):
        """Test that the confirmation page shows correct information before creating WorkOrder"""
        estimate = Estimate.objects.get(pk=100)

        url = reverse('jobs:work_order_create_from_estimate', kwargs={'estimate_id': estimate.estimate_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check context data
        self.assertEqual(response.context['estimate'], estimate)
        self.assertIsNotNone(response.context['worksheet'])

        # Check displayed information
        self.assertContains(response, estimate.estimate_number)
        self.assertContains(response, estimate.job.job_number)
        self.assertContains(response, "Status: Draft")
        self.assertContains(response, "Tasks, bundles, and materials will be copied directly from the worksheet.")
        self.assertContains(response, "Test Product Template")

    def test_confirmation_page_no_worksheet(self):
        """Test confirmation page when estimate has no worksheet"""
        estimate = Estimate.objects.get(pk=103)

        url = reverse('jobs:work_order_create_from_estimate', kwargs={'estimate_id': estimate.estimate_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['worksheet'])
        self.assertEqual(response.context['total_line_items'], 0)

        self.assertContains(response, "No worksheet is associated with this estimate")
        self.assertContains(response, "may need manual refinement")

    def test_create_workorder_link_visibility(self):
        """Test that Create Work Order link only shows for accepted estimates"""
        # Test accepted estimate - should show link
        estimate_accepted = Estimate.objects.get(pk=100)
        url = reverse('jobs:estimate_detail', kwargs={'estimate_id': estimate_accepted.estimate_id})
        response = self.client.get(url)
        self.assertContains(response, 'Create Work Order')

        # Test open estimate - should not show link
        estimate_open = Estimate.objects.get(pk=101)
        url = reverse('jobs:estimate_detail', kwargs={'estimate_id': estimate_open.estimate_id})
        response = self.client.get(url)
        self.assertNotContains(response, 'Create Work Order')

        # Test draft estimate - should not show link
        estimate_draft = Estimate.objects.get(pk=102)
        url = reverse('jobs:estimate_detail', kwargs={'estimate_id': estimate_draft.estimate_id})
        response = self.client.get(url)
        self.assertNotContains(response, 'Create Work Order')


class WorkOrderFromEstimateIntegrationTest(TestCase):
    """Integration tests for the complete workflow"""

    fixtures = ['workorder_from_estimate.json']

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

    def test_complete_workflow_from_estimate_to_workorder(self):
        """Test the complete workflow from viewing an estimate to creating a WorkOrder"""
        estimate = Estimate.objects.get(pk=100)

        # Step 1: View estimate detail page
        estimate_url = reverse('jobs:estimate_detail', kwargs={'estimate_id': estimate.estimate_id})
        response = self.client.get(estimate_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Work Order')

        # Step 2: Click on Create Work Order (GET request to confirmation page)
        create_url = reverse('jobs:work_order_create_from_estimate', kwargs={'estimate_id': estimate.estimate_id})
        response = self.client.get(create_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Work Order from Estimate')

        # Step 3: Confirm creation (POST request)
        response = self.client.post(create_url)
        self.assertEqual(response.status_code, 302)  # Redirect after creation

        # Step 4: Follow redirect to WorkOrder detail
        work_order = WorkOrder.objects.filter(job=estimate.job).first()
        expected_url = reverse('jobs:work_order_detail', kwargs={'work_order_id': work_order.work_order_id})
        self.assertRedirects(response, expected_url)

        # Step 5: View the created WorkOrder
        response = self.client.get(expected_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'Work Order {work_order.work_order_id}')
        self.assertContains(response, 'Parent Task - Assembly')
        self.assertContains(response, 'Standalone Task - Material Delivery')

    def test_multiple_workorders_from_same_job(self):
        """Test that multiple WorkOrders can be created for the same job from different estimates"""
        # Create first WorkOrder from estimate 100
        estimate1 = Estimate.objects.get(pk=100)
        url1 = reverse('jobs:work_order_create_from_estimate', kwargs={'estimate_id': estimate1.estimate_id})
        response1 = self.client.post(url1)

        # Create second WorkOrder from estimate 103 (same job, different estimate)
        estimate2 = Estimate.objects.get(pk=103)
        url2 = reverse('jobs:work_order_create_from_estimate', kwargs={'estimate_id': estimate2.estimate_id})
        response2 = self.client.post(url2)

        # Verify both WorkOrders exist for the same job
        work_orders = WorkOrder.objects.filter(job=estimate1.job).order_by('work_order_id')
        self.assertEqual(work_orders.count(), 2)

        # Verify they have different characteristics
        wo1 = work_orders[0]
        wo2 = work_orders[1]

        # First has tasks, second doesn't
        self.assertGreater(Task.objects.filter(work_order=wo1).count(), 0)
        self.assertEqual(Task.objects.filter(work_order=wo2).count(), 0)