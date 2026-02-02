"""
Test for estimate generation with bundled tasks.

This test verifies that the ProductBundlingRule.line_item_template
can use {product_identifier} placeholder (not just {product_type}).
"""
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import (
    Job, EstWorksheet, Task, TaskTemplate, TaskMapping,
    WorkOrderTemplate, ProductBundlingRule, TaskInstanceMapping, Estimate
)
from apps.jobs.services import EstimateGenerationService
from apps.contacts.models import Contact
from apps.core.models import Configuration


class TestEstimateGenerationWithProductIdentifier(TestCase):
    """Test that bundling works with {product_identifier} in line_item_template."""

    def setUp(self):
        """Set up configuration for number generation."""
        Configuration.objects.create(pk="estimate_number_sequence", value="EST-TEST-{counter:04d}")
        Configuration.objects.create(pk="estimate_counter", value="0")

    def test_bundling_with_product_identifier_template(self):
        """
        ProductBundlingRule.line_item_template should support {product_identifier}
        placeholder, not just {product_type}.

        This allows line items like "Custom Cabinet - cabinet_001" instead of
        just "Custom Cabinet".
        """
        # Create a contact for the job
        contact = Contact.objects.create(
            first_name="Test",
            last_name="Customer",
            email="test@example.com",
            mobile_number="555-0000"
        )

        # Create task mapping for bundled components
        task_mapping = TaskMapping.objects.create(
            task_type_id="COMPONENT-TEST",
            step_type="component",
            mapping_strategy="bundle_to_product",
            default_product_type="cabinet",
            output_line_item_type=None
        )

        # Create task templates
        frame_template = TaskTemplate.objects.create(
            template_name="Cabinet Frame",
            units="each",
            rate=Decimal("200.00"),
            task_mapping=task_mapping
        )
        doors_template = TaskTemplate.objects.create(
            template_name="Cabinet Doors",
            units="each",
            rate=Decimal("150.00"),
            task_mapping=task_mapping
        )

        # Create worksheet template
        worksheet_template = WorkOrderTemplate.objects.create(
            template_name="Cabinet Build",
            template_type="product",
            product_type="cabinet",
            base_price=Decimal("450.00")
        )

        # Create bundling rule WITH {product_identifier} in template
        bundling_rule = ProductBundlingRule.objects.create(
            rule_name="Cabinet Bundler",
            product_type="cabinet",
            work_order_template=worksheet_template,
            line_item_template="Custom Cabinet - {product_identifier}",  # Uses product_identifier!
            combine_instances=True,
            pricing_method="sum_components",
            include_materials=True,
            include_labor=True,
            include_overhead=False
        )

        # Create job and worksheet
        job = Job.objects.create(
            job_number="JOB-BUNDLE-TEST-001",
            contact=contact,
            status="draft",
            description="Test bundling job"
        )

        worksheet = EstWorksheet.objects.create(
            job=job,
            template=worksheet_template,
            status="draft"
        )

        # Create tasks on the worksheet
        task1 = Task.objects.create(
            est_worksheet=worksheet,
            name="Cabinet Frame",
            template=frame_template,
            units="each",
            rate=Decimal("200.00"),
            est_qty=Decimal("1.00")
        )
        task2 = Task.objects.create(
            est_worksheet=worksheet,
            name="Cabinet Doors",
            template=doors_template,
            units="each",
            rate=Decimal("150.00"),
            est_qty=Decimal("2.00")
        )

        # Create TaskInstanceMappings to group them
        TaskInstanceMapping.objects.create(
            task=task1,
            product_identifier="cabinet_001",
            product_instance=1
        )
        TaskInstanceMapping.objects.create(
            task=task2,
            product_identifier="cabinet_001",
            product_instance=1
        )

        # Generate estimate - this should NOT raise KeyError
        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        # Verify estimate was created
        self.assertIsNotNone(estimate)
        self.assertEqual(estimate.status, "draft")

        # Verify line items
        line_items = list(estimate.estimatelineitem_set.all())
        self.assertEqual(len(line_items), 1, "Should have exactly 1 bundled line item")

        # Verify the description includes the product_identifier
        line_item = line_items[0]
        self.assertIn("cabinet_001", line_item.description,
            f"Description should contain 'cabinet_001', got: {line_item.description}")

        # Verify bundled price: (1 * 200) + (2 * 150) = 500
        expected_price = Decimal("500.00")
        self.assertEqual(line_item.price_currency, expected_price,
            f"Expected price {expected_price}, got {line_item.price_currency}")
