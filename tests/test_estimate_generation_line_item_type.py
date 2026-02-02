"""
Test that EstimateGenerationService sets line_item_type on generated line items.
"""
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import (
    Job, EstWorksheet, Task, TaskTemplate, TaskMapping,
    WorkOrderTemplate, Estimate
)
from apps.jobs.services import EstimateGenerationService
from apps.contacts.models import Contact
from apps.core.models import Configuration, LineItemType


class TestEstimateGenerationLineItemType(TestCase):
    """Test that line_item_type is properly set during estimate generation."""

    def setUp(self):
        """Set up test data."""
        Configuration.objects.create(pk="estimate_number_sequence", value="EST-TEST-{counter:04d}")
        Configuration.objects.create(pk="estimate_counter", value="0")

        # Get existing line item types (created by migrations)
        self.service_type, _ = LineItemType.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False}
        )
        self.material_type, _ = LineItemType.objects.get_or_create(
            code='MAT', defaults={'name': 'Material', 'taxable': True}
        )

        # Create contact
        self.contact = Contact.objects.create(
            first_name="Test", last_name="Customer",
            email="test@example.com", mobile_number="555-0000"
        )

    def test_direct_mapping_sets_line_item_type(self):
        """
        Tasks with direct mapping should have their line_item_type set
        from TaskMapping.output_line_item_type.
        """
        # Create task mapping with output_line_item_type
        task_mapping = TaskMapping.objects.create(
            task_type_id="LABOR-DIRECT",
            step_type="labor",
            mapping_strategy="direct",
            output_line_item_type=self.service_type
        )

        # Create task template using the mapping
        task_template = TaskTemplate.objects.create(
            template_name="Consultation",
            units="hours",
            rate=Decimal("75.00"),
            task_mapping=task_mapping
        )

        # Create worksheet template
        worksheet_template = WorkOrderTemplate.objects.create(
            template_name="Service Job",
            template_type="service"
        )

        # Create job and worksheet
        job = Job.objects.create(
            job_number="JOB-LIT-TEST-001",
            contact=self.contact,
            status="draft"
        )

        worksheet = EstWorksheet.objects.create(
            job=job,
            template=worksheet_template,
            status="draft"
        )

        # Create task
        Task.objects.create(
            est_worksheet=worksheet,
            name="Consultation",
            template=task_template,
            units="hours",
            rate=Decimal("75.00"),
            est_qty=Decimal("2.00")
        )

        # Generate estimate
        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        # Verify line items have line_item_type set
        line_items = list(estimate.estimatelineitem_set.all())
        self.assertEqual(len(line_items), 1)

        line_item = line_items[0]
        self.assertIsNotNone(
            line_item.line_item_type,
            "line_item_type should be set from TaskMapping.output_line_item_type"
        )
        self.assertEqual(line_item.line_item_type, self.service_type)
        self.assertFalse(line_item.line_item_type.taxable)

    def test_direct_mapping_material_is_taxable(self):
        """
        Material tasks with direct mapping should inherit taxable=True from LineItemType.
        """
        # Create task mapping with taxable material type
        task_mapping = TaskMapping.objects.create(
            task_type_id="MATERIAL-DIRECT",
            step_type="material",
            mapping_strategy="direct",
            output_line_item_type=self.material_type
        )

        task_template = TaskTemplate.objects.create(
            template_name="Lumber",
            units="each",
            rate=Decimal("25.00"),
            task_mapping=task_mapping
        )

        worksheet_template = WorkOrderTemplate.objects.create(
            template_name="Material Job",
            template_type="service"
        )

        job = Job.objects.create(
            job_number="JOB-LIT-TEST-002",
            contact=self.contact,
            status="draft"
        )

        worksheet = EstWorksheet.objects.create(
            job=job,
            template=worksheet_template,
            status="draft"
        )

        Task.objects.create(
            est_worksheet=worksheet,
            name="Lumber 2x4",
            template=task_template,
            units="each",
            rate=Decimal("25.00"),
            est_qty=Decimal("10.00")
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        line_items = list(estimate.estimatelineitem_set.all())
        self.assertEqual(len(line_items), 1)

        line_item = line_items[0]
        self.assertIsNotNone(line_item.line_item_type)
        self.assertEqual(line_item.line_item_type, self.material_type)
        self.assertTrue(line_item.line_item_type.taxable)

    def test_bundled_product_sets_line_item_type(self):
        """
        Bundled product line items should get line_item_type from the
        TaskMapping.output_line_item_type of the component tasks.
        """
        from apps.jobs.models import ProductBundlingRule, TaskInstanceMapping

        # Create product line item type
        product_type = LineItemType.objects.get_or_create(
            code='PRD', defaults={'name': 'Product', 'taxable': True}
        )[0]

        # Create task mapping for cabinet components
        task_mapping = TaskMapping.objects.create(
            task_type_id="COMPONENT-CABINET",
            step_type="component",
            mapping_strategy="bundle_to_product",
            default_product_type="cabinet",
            output_line_item_type=product_type
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
            product_type="cabinet"
        )

        # Create bundling rule
        ProductBundlingRule.objects.create(
            rule_name="Cabinet Bundler",
            product_type="cabinet",
            work_order_template=worksheet_template,
            line_item_template="Custom Cabinet - {product_identifier}",
            pricing_method="sum_components"
        )

        # Create job and worksheet
        job = Job.objects.create(
            job_number="JOB-LIT-TEST-003",
            contact=self.contact,
            status="draft"
        )

        worksheet = EstWorksheet.objects.create(
            job=job,
            template=worksheet_template,
            status="draft"
        )

        # Create tasks
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

        # Generate estimate
        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        # Verify bundled line item has line_item_type set
        line_items = list(estimate.estimatelineitem_set.all())
        self.assertEqual(len(line_items), 1, "Should have 1 bundled line item")

        line_item = line_items[0]
        self.assertIsNotNone(
            line_item.line_item_type,
            "Bundled line item should have line_item_type set"
        )
        self.assertEqual(line_item.line_item_type, product_type)
