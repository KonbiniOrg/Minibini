"""
Tests for the consolidated bundling strategy.

This tests the merger of 'bundle_to_product' and 'bundle_to_service' into a single 'bundle' strategy.
"""
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import (
    Job, EstWorksheet, Task, TaskTemplate, TaskMapping,
    BundlingRule, TaskInstanceMapping, Estimate
)
from apps.jobs.services import EstimateGenerationService
from apps.contacts.models import Contact
from apps.core.models import Configuration


class TestConsolidatedBundlingStrategy(TestCase):
    """Test the unified 'bundle' mapping strategy."""

    def setUp(self):
        """Set up configuration for number generation."""
        Configuration.objects.create(key="estimate_number_sequence", value="EST-TEST-{counter:04d}")
        Configuration.objects.create(key="estimate_counter", value="0")

        # Create contact and job
        self.contact = Contact.objects.create(
            first_name="Test",
            last_name="Customer",
            email="test@example.com"
        )
        self.job = Job.objects.create(
            job_number="JOB-BUNDLE-001",
            contact=self.contact,
            status="draft"
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job,
            status="draft"
        )
        self.service = EstimateGenerationService()

    def test_bundle_strategy_exists_in_choices(self):
        """TaskMapping should have 'bundle' as a valid strategy choice."""
        strategy_values = [choice[0] for choice in TaskMapping.MAPPING_STRATEGY_CHOICES]
        self.assertIn('bundle', strategy_values)
        # Old strategies should NOT exist
        self.assertNotIn('bundle_to_product', strategy_values)
        self.assertNotIn('bundle_to_service', strategy_values)

    def test_bundle_with_default_units_each(self):
        """
        BundlingRule with default_units='each' should produce qty=1, units='each'.
        This replaces the old 'bundle_to_product' behavior.
        """
        # Create task mapping with 'bundle' strategy
        mapping = TaskMapping.objects.create(
            task_type_id='CABINET-COMPONENT',
            step_type='component',
            mapping_strategy='bundle',
            default_product_type='cabinet'
        )
        template = TaskTemplate.objects.create(
            template_name='Cabinet Frame',
            units='hours',
            rate=Decimal('100.00'),
            task_mapping=mapping
        )

        # Create bundling rule with default_units='each'
        rule = BundlingRule.objects.create(
            rule_name='Cabinet Bundler',
            product_type='cabinet',
            default_units='each',
            pricing_method='sum_components'
        )

        # Create tasks
        task1 = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Cabinet Frame',
            template=template,
            units='hours',
            rate=Decimal('100.00'),
            est_qty=Decimal('4.00')
        )
        task2 = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Cabinet Doors',
            template=template,
            units='hours',
            rate=Decimal('50.00'),
            est_qty=Decimal('2.00')
        )

        # Group tasks with bundle_identifier (renamed from product_identifier)
        TaskInstanceMapping.objects.create(
            task=task1,
            bundle_identifier='cabinet_001'  # RENAMED FIELD
        )
        TaskInstanceMapping.objects.create(
            task=task2,
            bundle_identifier='cabinet_001'
        )

        # Generate estimate
        estimate = self.service.generate_estimate_from_worksheet(self.worksheet)

        # Verify bundled line item
        line_items = list(estimate.estimatelineitem_set.all())
        self.assertEqual(len(line_items), 1)

        line_item = line_items[0]
        self.assertEqual(line_item.qty, Decimal('1.00'))  # qty=1 for 'each'
        self.assertEqual(line_item.units, 'each')
        # Total: (4 * 100) + (2 * 50) = 500
        self.assertEqual(line_item.price_currency, Decimal('500.00'))

    def test_bundle_with_default_units_hours(self):
        """
        BundlingRule with default_units='hours' should produce qty=sum_of_hours.
        This replaces the old 'bundle_to_service' behavior.
        """
        # Create task mapping with 'bundle' strategy
        mapping = TaskMapping.objects.create(
            task_type_id='SERVICE-LABOR',
            step_type='labor',
            mapping_strategy='bundle',
            default_product_type='installation'
        )
        template = TaskTemplate.objects.create(
            template_name='Installation Labor',
            units='hours',
            rate=Decimal('75.00'),
            task_mapping=mapping
        )

        # Create bundling rule with default_units='hours'
        rule = BundlingRule.objects.create(
            rule_name='Installation Service Bundler',
            product_type='installation',
            default_units='hours',  # sum hours
            pricing_method='sum_components'
        )

        # Create tasks (no instance mapping needed - grouped by product_type)
        task1 = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Site Prep',
            template=template,
            units='hours',
            rate=Decimal('75.00'),
            est_qty=Decimal('2.00')
        )
        task2 = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Installation',
            template=template,
            units='hours',
            rate=Decimal('75.00'),
            est_qty=Decimal('3.00')
        )

        # Generate estimate
        estimate = self.service.generate_estimate_from_worksheet(self.worksheet)

        # Verify bundled line item
        line_items = list(estimate.estimatelineitem_set.all())
        self.assertEqual(len(line_items), 1)

        line_item = line_items[0]
        self.assertEqual(line_item.qty, Decimal('5.00'))  # 2 + 3 = 5 hours
        self.assertEqual(line_item.units, 'hours')
        # Total: (2 * 75) + (3 * 75) = 375
        self.assertEqual(line_item.price_currency, Decimal('375.00'))

    def test_description_includes_tasks_list(self):
        """
        Bundled line items with multiple tasks should include a task list.
        Descriptions are built using hard-coded patterns.
        """
        mapping = TaskMapping.objects.create(
            task_type_id='SERVICE-ITEM',
            step_type='labor',
            mapping_strategy='bundle',
            default_product_type='maintenance'
        )
        template = TaskTemplate.objects.create(
            template_name='Service Item',
            units='hours',
            rate=Decimal('50.00'),
            task_mapping=mapping
        )

        # Create bundling rule
        rule = BundlingRule.objects.create(
            rule_name='Maintenance Bundler',
            product_type='maintenance',
            default_units='hours',
            pricing_method='sum_components'
        )

        # Create tasks
        Task.objects.create(
            est_worksheet=self.worksheet,
            name='Oil Change',
            template=template,
            units='hours',
            rate=Decimal('50.00'),
            est_qty=Decimal('1.00')
        )
        Task.objects.create(
            est_worksheet=self.worksheet,
            name='Filter Replacement',
            template=template,
            units='hours',
            rate=Decimal('50.00'),
            est_qty=Decimal('0.50')
        )

        # Generate estimate
        estimate = self.service.generate_estimate_from_worksheet(self.worksheet)

        # Verify description uses hard-coded pattern with task list
        line_items = list(estimate.estimatelineitem_set.all())
        self.assertEqual(len(line_items), 1)

        description = line_items[0].description
        # Hard-coded format: "Custom Maintenance\n- Oil Change\n- Filter Replacement"
        self.assertIn('Custom Maintenance', description)
        self.assertIn('- Oil Change', description)
        self.assertIn('- Filter Replacement', description)

    def test_bundling_rule_model_has_default_units_field(self):
        """BundlingRule should have default_units field."""
        rule = BundlingRule.objects.create(
            rule_name='Test Rule',
            product_type='test',
            default_units='each'
        )
        rule.refresh_from_db()
        self.assertEqual(rule.default_units, 'each')

    def test_bundle_identifier_field_renamed(self):
        """TaskInstanceMapping should use bundle_identifier, not product_identifier."""
        # Create a task
        task = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Test Task',
            units='hours',
            rate=Decimal('100.00'),
            est_qty=Decimal('1.00')
        )

        # Create instance mapping with bundle_identifier
        instance_mapping = TaskInstanceMapping.objects.create(
            task=task,
            bundle_identifier='test_bundle_001'
        )

        instance_mapping.refresh_from_db()
        self.assertEqual(instance_mapping.bundle_identifier, 'test_bundle_001')

        # Verify product_identifier field no longer exists
        self.assertFalse(hasattr(instance_mapping, 'product_identifier'))


class TestBundlingRuleDefaultUnitsChoices(TestCase):
    """Test the DEFAULT_UNITS_CHOICES on BundlingRule."""

    def test_default_units_choices_exist(self):
        """BundlingRule should have DEFAULT_UNITS_CHOICES defined."""
        from apps.jobs.models import BundlingRule
        self.assertTrue(hasattr(BundlingRule, 'DEFAULT_UNITS_CHOICES'))
        choices = BundlingRule.DEFAULT_UNITS_CHOICES
        choice_values = [c[0] for c in choices]
        self.assertIn('each', choice_values)
        self.assertIn('hours', choice_values)

    def test_default_units_field_defaults_to_each(self):
        """default_units should default to 'each'."""
        from apps.jobs.models import BundlingRule
        rule = BundlingRule.objects.create(
            rule_name='Default Test',
            product_type='test'
        )
        self.assertEqual(rule.default_units, 'each')


class TestBundleIdentifierGrouping(TestCase):
    """Test that tasks are grouped by bundle_identifier."""

    def setUp(self):
        Configuration.objects.create(key="estimate_number_sequence", value="EST-TEST-{counter:04d}")
        Configuration.objects.create(key="estimate_counter", value="0")

        self.contact = Contact.objects.create(
            first_name="Test", last_name="Customer", email="test@example.com"
        )
        self.job = Job.objects.create(
            job_number="JOB-BUNDLE-002", contact=self.contact, status="draft"
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job, status="draft")
        self.service = EstimateGenerationService()

    def test_tasks_with_different_bundle_identifiers_create_separate_line_items(self):
        """Tasks with different bundle_identifiers should create separate line items."""
        mapping = TaskMapping.objects.create(
            task_type_id='PRODUCT-COMPONENT',
            step_type='component',
            mapping_strategy='bundle',
            default_product_type='widget'
        )
        template = TaskTemplate.objects.create(
            template_name='Widget Part',
            units='each',
            rate=Decimal('100.00'),
            task_mapping=mapping
        )

        BundlingRule.objects.create(
            rule_name='Widget Bundler',
            product_type='widget',
            default_units='each',
            combine_instances=False  # Don't combine into qty > 1
        )

        # Create tasks for two different widgets
        task1 = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Widget Part A',
            template=template,
            rate=Decimal('100.00'),
            est_qty=Decimal('1.00')
        )
        task2 = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Widget Part B',
            template=template,
            rate=Decimal('200.00'),
            est_qty=Decimal('1.00')
        )

        # Different bundle identifiers
        TaskInstanceMapping.objects.create(task=task1, bundle_identifier='widget_001')
        TaskInstanceMapping.objects.create(task=task2, bundle_identifier='widget_002')

        estimate = self.service.generate_estimate_from_worksheet(self.worksheet)
        line_items = list(estimate.estimatelineitem_set.all())

        self.assertEqual(len(line_items), 2)
        descriptions = [li.description for li in line_items]
        self.assertTrue(any('widget_001' in d for d in descriptions))
        self.assertTrue(any('widget_002' in d for d in descriptions))

    def test_tasks_without_instance_mapping_grouped_by_product_type(self):
        """Tasks without TaskInstanceMapping should be auto-grouped by product_type."""
        mapping = TaskMapping.objects.create(
            task_type_id='SERVICE-TASK',
            step_type='labor',
            mapping_strategy='bundle',
            default_product_type='consulting'
        )
        template = TaskTemplate.objects.create(
            template_name='Consulting',
            units='hours',
            rate=Decimal('150.00'),
            task_mapping=mapping
        )

        BundlingRule.objects.create(
            rule_name='Consulting Bundler',
            product_type='consulting',
            default_units='hours'
        )

        # Create tasks WITHOUT TaskInstanceMapping
        Task.objects.create(
            est_worksheet=self.worksheet,
            name='Initial Consultation',
            template=template,
            rate=Decimal('150.00'),
            est_qty=Decimal('2.00')
        )
        Task.objects.create(
            est_worksheet=self.worksheet,
            name='Follow-up Meeting',
            template=template,
            rate=Decimal('150.00'),
            est_qty=Decimal('1.00')
        )

        estimate = self.service.generate_estimate_from_worksheet(self.worksheet)
        line_items = list(estimate.estimatelineitem_set.all())

        # Should be bundled into single line item
        self.assertEqual(len(line_items), 1)
        self.assertEqual(line_items[0].qty, Decimal('3.00'))  # 2 + 1 hours
