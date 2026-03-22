from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from decimal import Decimal

from apps.jobs.models import Job, WorkOrder, Task
from apps.estimates.models import Estimate, EstimateLineItem, EstWorksheet, WorkOrderTemplate, TaskTemplate
from apps.jobs.services import TaskService
from apps.contacts.models import Contact
from apps.inventory.models import PriceListItem

User = get_user_model()


class LineItemTaskGenerationTestCase(TestCase):
    """Test task generation from different types of EstimateLineItems"""

    fixtures = ['mixed_lineitems.json']

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            is_superuser=True
        )
        self.client.login(username='testuser', password='testpass123')

    def test_worksheet_task_generation(self):
        """Test that worksheet-based LineItems properly copy tasks"""
        estimate = Estimate.objects.get(pk=200)
        line_item = EstimateLineItem.objects.get(pk=200)  # Worksheet-based item

        # Verify this is a worksheet-based line item
        self.assertIsNotNone(line_item.task)
        self.assertIsNone(line_item.price_list_item)

        # Create WorkOrder and generate tasks
        work_order = WorkOrder.objects.create(job=estimate.job)
        generated_tasks = TaskService.create_from_line_item(line_item, work_order)

        # Verify task was created
        self.assertEqual(len(generated_tasks), 1)
        task = generated_tasks[0]

        # Verify task properties match original
        original_task = line_item.task
        self.assertEqual(task.name, original_task.name)
        self.assertEqual(task.units, original_task.units)
        self.assertEqual(task.rate, original_task.rate)
        self.assertEqual(task.est_qty, original_task.est_qty)
        self.assertEqual(task.work_order, work_order)

    def test_catalog_item_task_generation(self):
        """Test that catalog-based LineItems create appropriate tasks"""
        estimate = Estimate.objects.get(pk=200)
        line_item = EstimateLineItem.objects.get(pk=201)  # Catalog-based item

        # Verify this is a catalog-based line item
        self.assertIsNone(line_item.task)
        self.assertIsNotNone(line_item.price_list_item)

        # Create WorkOrder and generate tasks
        work_order = WorkOrder.objects.create(job=estimate.job)
        generated_tasks = TaskService.create_from_line_item(line_item, work_order)

        # Verify task was created
        self.assertEqual(len(generated_tasks), 1)
        task = generated_tasks[0]

        # Verify task properties
        self.assertIn(line_item.price_list_item.code, task.name)
        self.assertEqual(task.units, line_item.units)
        self.assertEqual(task.rate, line_item.price)
        self.assertEqual(task.est_qty, line_item.qty)
        self.assertEqual(task.work_order, work_order)

    def test_manual_item_task_generation(self):
        """Test that manual LineItems create generic tasks"""
        estimate = Estimate.objects.get(pk=200)
        line_item = EstimateLineItem.objects.get(pk=203)  # Manual item

        # Verify this is a manual line item
        self.assertIsNone(line_item.task)
        self.assertIsNone(line_item.price_list_item)

        # Create WorkOrder and generate tasks
        work_order = WorkOrder.objects.create(job=estimate.job)
        generated_tasks = TaskService.create_from_line_item(line_item, work_order)

        # Verify task was created
        self.assertEqual(len(generated_tasks), 1)
        task = generated_tasks[0]

        # Verify task properties
        self.assertEqual(task.name, line_item.description)
        self.assertEqual(task.units, line_item.units)
        self.assertEqual(task.rate, line_item.price)
        self.assertEqual(task.est_qty, line_item.qty)
        self.assertEqual(task.work_order, work_order)

    def test_manual_item_without_description(self):
        """Test manual item task generation when no description provided"""
        estimate = Estimate.objects.get(pk=200)

        # Create a manual line item without description
        line_item = EstimateLineItem.objects.create(
            estimate=estimate,
            line_number=10,
            qty=Decimal('1.00'),
            units='each',
            description='',  # Empty description
            price=Decimal('100.00')
        )

        work_order = WorkOrder.objects.create(job=estimate.job)
        generated_tasks = TaskService.create_from_line_item(line_item, work_order)

        self.assertEqual(len(generated_tasks), 1)
        task = generated_tasks[0]
        self.assertIn(f'Line Item {line_item.line_number}', task.name)

    def test_mixed_estimate_task_generation(self):
        """Test WorkOrder creation from estimate with worksheet copies worksheet tasks."""
        estimate = Estimate.objects.get(pk=200)
        worksheet = EstWorksheet.objects.filter(estimate=estimate).first()

        # Create WorkOrder via the view
        url = reverse('estimates:work_order_create_from_estimate', kwargs={'estimate_id': estimate.estimate_id})
        response = self.client.post(url, follow=True)

        # Verify WorkOrder was created
        work_order = WorkOrder.objects.filter(job=estimate.job).first()
        self.assertIsNotNone(work_order)

        # When worksheet exists, tasks are copied from worksheet (not line items)
        ws_task_count = Task.objects.filter(est_worksheet=worksheet).count()
        wo_task_count = Task.objects.filter(work_order=work_order).count()
        self.assertEqual(wo_task_count, ws_task_count)

        # Verify the worksheet task was copied
        self.assertTrue(Task.objects.filter(work_order=work_order, name="Mixed Assembly Task").exists())

    def test_confirmation_page_shows_worksheet_source(self):
        """Test that confirmation page shows worksheet as source when one exists."""
        estimate = Estimate.objects.get(pk=200)

        url = reverse('estimates:work_order_create_from_estimate', kwargs={'estimate_id': estimate.estimate_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # When worksheet exists, shows worksheet info (not line item breakdown)
        self.assertIsNotNone(response.context['worksheet'])
        self.assertContains(response, 'Tasks, bundles, and materials will be copied directly from the worksheet.')

    def test_empty_estimate_handling(self):
        """Test WorkOrder creation from estimate with no line items"""
        # Create estimate with no line items
        job = Job.objects.get(pk=100)
        empty_estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-EMPTY-001',
            version=1,
            status='accepted'
        )

        url = reverse('estimates:work_order_create_from_estimate', kwargs={'estimate_id': empty_estimate.estimate_id})
        response = self.client.post(url, follow=True)

        # Should still create WorkOrder, just with no tasks
        work_order = WorkOrder.objects.filter(job=job).exclude(pk__in=[]).last()
        self.assertIsNotNone(work_order)

        task_count = Task.objects.filter(work_order=work_order).count()
        self.assertEqual(task_count, 0)

        # Check success message
        messages = list(response.context['messages'])
        self.assertTrue(any('Work Order' in str(m) and 'created successfully' in str(m) for m in messages))

    def test_price_fallback_handling(self):
        """Test that catalog items handle price fallbacks correctly"""
        estimate = Estimate.objects.get(pk=200)
        price_list_item = PriceListItem.objects.get(pk=200)

        # Create line item with no price (should use selling_price)
        line_item = EstimateLineItem.objects.create(
            estimate=estimate,
            price_list_item=price_list_item,
            line_number=20,
            qty=Decimal('5.00'),
            units='',  # Empty units (should use price_list_item.units)
            description='Test fallback',
            price=Decimal('0.00')  # Zero price
        )

        work_order = WorkOrder.objects.create(job=estimate.job)
        generated_tasks = TaskService.create_from_line_item(line_item, work_order)

        self.assertEqual(len(generated_tasks), 1)
        task = generated_tasks[0]

        # Should use selling_price as fallback
        self.assertEqual(task.rate, price_list_item.selling_price)
        # Should use price_list_item units as fallback
        self.assertEqual(task.units, price_list_item.units)


class LineItemTaskGenerationEdgeCasesTest(TestCase):
    """Test edge cases and error conditions for task generation"""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Edge Case Contact',
            last_name='',
            email='edge@test.com'
        )

        self.job = Job.objects.create(
            job_number='JOB-EDGE-001',
            contact=self.contact,
            status='approved'
        )

        self.estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-EDGE-001',
            version=1,
            status='accepted'
        )

    def test_line_item_with_null_values(self):
        """Test task generation when line item has null/empty values"""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_number=1,
            qty=Decimal('0.00'),  # Zero quantity
            units='',  # Empty units
            description='',  # Empty description
            price=Decimal('0.00')  # Zero price
        )

        work_order = WorkOrder.objects.create(job=self.job)
        generated_tasks = TaskService.create_from_line_item(line_item, work_order)

        self.assertEqual(len(generated_tasks), 1)
        task = generated_tasks[0]

        # Should handle null/empty values gracefully (using line_number since description is empty)
        self.assertIn(f'Line Item {line_item.line_number}', task.name)
        self.assertEqual(task.units, '')
        self.assertEqual(task.rate, Decimal('0.00'))
        self.assertEqual(task.est_qty, Decimal('0.00'))

    def test_catalog_item_with_long_description(self):
        """Test catalog task naming with very long descriptions"""
        price_list_item = PriceListItem.objects.create(
            code='LONG001',
            description='This is a very long description that should be truncated when creating a task name because it exceeds the reasonable length for display',
            units='each',
            selling_price=Decimal('10.00')
        )

        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            price_list_item=price_list_item,
            line_number=1,
            qty=Decimal('1.00'),
            units='each',
            description='',
            price=Decimal('10.00')
        )

        work_order = WorkOrder.objects.create(job=self.job)
        generated_tasks = TaskService.create_from_line_item(line_item, work_order)

        self.assertEqual(len(generated_tasks), 1)
        task = generated_tasks[0]

        # Should truncate long description
        self.assertIn('LONG001', task.name)
        self.assertIn('...', task.name)  # Should have truncation indicator
        self.assertLess(len(task.name), 100)  # Should be reasonable length