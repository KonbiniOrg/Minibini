"""
Tests for hard-coded line item descriptions.

Gap 3 resolution: We removed template placeholders and the line_item_template and
description_template fields entirely. Descriptions are now built using predictable,
hard-coded patterns from product_type and bundle_identifier values in code.

Descriptions look like "Custom Cabinet - kitchen_island", with the format
determined by code in EstimateGenerationService.
"""
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import Configuration
from apps.jobs.models import (
    Job, EstWorksheet, Task, TaskMapping, BundlingRule,
    TaskTemplate, TaskInstanceMapping, WorkOrderTemplate
)
from apps.jobs.services import EstimateGenerationService


class TestHardcodedDescriptions(TestCase):
    """Test that line item descriptions use hard-coded patterns."""

    def setUp(self):
        """Set up test data."""
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')

        self.contact = Contact.objects.create(
            first_name='Test',
            last_name='Customer',
            email='test@example.com'
        )

        self.job = Job.objects.create(
            job_number='TEST-HARDCODED-001',
            contact=self.contact,
            description='Test Job'
        )

        self.worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='draft'
        )

    def test_bundled_description_uses_product_type(self):
        """
        Bundled line items should use product_type for description.
        Format: "Custom {ProductType}"
        """
        task_mapping = TaskMapping.objects.create(
            task_type_id='HARDCODE-TEST',
            step_type='component',
            mapping_strategy='bundle',
            default_product_type='cabinet'
        )

        task_template = TaskTemplate.objects.create(
            template_name='Cabinet Frame',
            units='each',
            rate=Decimal('200.00'),
            task_mapping=task_mapping
        )

        BundlingRule.objects.create(
            rule_name='Cabinet Bundler',
            product_type='cabinet',
            combine_instances=True,
            pricing_method='sum_components'
        )

        Task.objects.create(
            est_worksheet=self.worksheet,
            name='Cabinet Frame',
            template=task_template,
            units='each',
            rate=Decimal('200.00'),
            est_qty=Decimal('1.00')
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(self.worksheet)

        line_items = list(estimate.estimatelineitem_set.all())
        self.assertEqual(len(line_items), 1)

        line_item = line_items[0]
        self.assertEqual(
            line_item.description,
            'Custom Cabinet',
            f"Description should be 'Custom Cabinet', got: {line_item.description}"
        )

    def test_bundled_description_with_identifier(self):
        """
        When a bundle_identifier exists, description should include it.
        Format: "Custom {ProductType} - {identifier}"
        """
        task_mapping = TaskMapping.objects.create(
            task_type_id='IDENT-TEST',
            step_type='component',
            mapping_strategy='bundle',
            default_product_type='cabinet'
        )

        task_template = TaskTemplate.objects.create(
            template_name='Cabinet Frame',
            units='each',
            rate=Decimal('200.00'),
            task_mapping=task_mapping
        )

        BundlingRule.objects.create(
            rule_name='Cabinet Bundler',
            product_type='cabinet',
            combine_instances=True,
            pricing_method='sum_components'
        )

        task = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Cabinet Frame',
            template=task_template,
            units='each',
            rate=Decimal('200.00'),
            est_qty=Decimal('1.00')
        )

        TaskInstanceMapping.objects.create(
            task=task,
            bundle_identifier='kitchen_island'
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(self.worksheet)

        line_items = list(estimate.estimatelineitem_set.all())
        self.assertEqual(len(line_items), 1)

        line_item = line_items[0]
        self.assertEqual(
            line_item.description,
            'Custom Cabinet - kitchen_island',
            f"Got: {line_item.description}"
        )

    def test_bundled_description_with_tasks_list(self):
        """
        When multiple tasks are bundled, description should include task list.
        Format: "Custom {ProductType}\n- Task A\n- Task B"
        """
        task_mapping = TaskMapping.objects.create(
            task_type_id='TASKS-LIST-TEST',
            step_type='labor',
            mapping_strategy='bundle',
            default_product_type='service'
        )

        task_template = TaskTemplate.objects.create(
            template_name='Service Task',
            units='hours',
            rate=Decimal('50.00'),
            task_mapping=task_mapping
        )

        BundlingRule.objects.create(
            rule_name='Service Bundler',
            product_type='service',
            default_units='hours',
            pricing_method='sum_components'
        )

        Task.objects.create(
            est_worksheet=self.worksheet,
            name='Task A',
            template=task_template,
            units='hours',
            rate=Decimal('50.00'),
            est_qty=Decimal('1.00')
        )
        Task.objects.create(
            est_worksheet=self.worksheet,
            name='Task B',
            template=task_template,
            units='hours',
            rate=Decimal('50.00'),
            est_qty=Decimal('2.00')
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(self.worksheet)

        line_items = list(estimate.estimatelineitem_set.all())
        self.assertEqual(len(line_items), 1)

        description = line_items[0].description
        self.assertIn('Custom Service', description)
        self.assertIn('- Task A', description)
        self.assertIn('- Task B', description)

    def test_combined_bundle_description_multiple_instances(self):
        """
        When combine_instances=True and multiple instances exist,
        description should be like "2x Widget".
        """
        task_mapping = TaskMapping.objects.create(
            task_type_id='COMBINED-TEST',
            step_type='component',
            mapping_strategy='bundle',
            default_product_type='widget'
        )

        task_template = TaskTemplate.objects.create(
            template_name='Widget Part',
            units='each',
            rate=Decimal('100.00'),
            task_mapping=task_mapping
        )

        worksheet_template = WorkOrderTemplate.objects.create(
            template_name='Widget Build',
            template_type='product',
            product_type='widget'
        )

        BundlingRule.objects.create(
            rule_name='Widget Bundler',
            product_type='widget',
            work_order_template=worksheet_template,
            combine_instances=True,
            pricing_method='sum_components'
        )

        task1 = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Widget Part 1',
            template=task_template,
            units='each',
            rate=Decimal('100.00'),
            est_qty=Decimal('1.00')
        )
        task2 = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Widget Part 2',
            template=task_template,
            units='each',
            rate=Decimal('100.00'),
            est_qty=Decimal('1.00')
        )

        # Two different widgets
        TaskInstanceMapping.objects.create(task=task1, bundle_identifier='widget_001')
        TaskInstanceMapping.objects.create(task=task2, bundle_identifier='widget_002')

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(self.worksheet)

        line_items = list(estimate.estimatelineitem_set.all())
        self.assertEqual(len(line_items), 1, "Should combine into one line item")

        description = line_items[0].description
        # Should be "2x Widget"
        self.assertIn('Widget', description)
        self.assertIn('2', description)

    def test_single_instance_shows_identifier_not_quantity(self):
        """
        When there's only one instance, show the identifier, not "1x".
        E.g., "Custom Cabinet - kitchen_island", not "1x Cabinet".
        """
        task_mapping = TaskMapping.objects.create(
            task_type_id='SINGLE-TEST',
            step_type='component',
            mapping_strategy='bundle',
            default_product_type='cabinet'
        )

        task_template = TaskTemplate.objects.create(
            template_name='Cabinet Part',
            units='each',
            rate=Decimal('100.00'),
            task_mapping=task_mapping
        )

        worksheet_template = WorkOrderTemplate.objects.create(
            template_name='Cabinet Build',
            template_type='product',
            product_type='cabinet'
        )

        BundlingRule.objects.create(
            rule_name='Cabinet Bundler',
            product_type='cabinet',
            work_order_template=worksheet_template,
            combine_instances=True,
            pricing_method='sum_components'
        )

        task = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Cabinet Part',
            template=task_template,
            units='each',
            rate=Decimal('100.00'),
            est_qty=Decimal('1.00')
        )

        TaskInstanceMapping.objects.create(task=task, bundle_identifier='kitchen_island')

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(self.worksheet)

        line_items = list(estimate.estimatelineitem_set.all())
        self.assertEqual(len(line_items), 1)

        description = line_items[0].description
        self.assertEqual(description, 'Custom Cabinet - kitchen_island')
        self.assertNotIn('1x', description)
