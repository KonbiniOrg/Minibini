"""
Tests for the new simplified templating system.
Tests TemplateBundle, TaskTemplate.line_item_type, and TemplateTaskAssociation mapping.
"""
from decimal import Decimal
from django.test import TestCase
from django.db.models import ProtectedError
from django.core.exceptions import ValidationError

from apps.jobs.models import (
    TaskTemplate, WorkOrderTemplate, TemplateTaskAssociation, TemplateBundle,
    TaskBundle, Job, EstWorksheet, Task, Estimate, EstimateLineItem
)
from apps.jobs.services import EstimateGenerationService
from apps.core.models import LineItemType
from apps.contacts.models import Contact
from django.db import IntegrityError


class TestTaskTemplateLineItemType(TestCase):
    """Tests for TaskTemplate.line_item_type field"""

    def test_task_template_can_have_line_item_type(self):
        """TaskTemplate can have a line_item_type"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        tt = TaskTemplate.objects.create(
            template_name="Sand Surface",
            line_item_type=lit
        )
        self.assertEqual(tt.line_item_type, lit)

    def test_task_template_line_item_type_protected(self):
        """Cannot delete LineItemType if TaskTemplate references it"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        TaskTemplate.objects.create(template_name="Sand", line_item_type=lit)

        with self.assertRaises(ProtectedError):
            lit.delete()

    def test_task_template_line_item_type_nullable(self):
        """TaskTemplate.line_item_type can be null (for migration)"""
        tt = TaskTemplate.objects.create(
            template_name="Sand Surface",
            line_item_type=None
        )
        self.assertIsNone(tt.line_item_type)


class TestTemplateBundle(TestCase):
    """Tests for TemplateBundle model"""

    def test_create_template_bundle(self):
        """Can create a TemplateBundle attached to WorkOrderTemplate"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        wot = WorkOrderTemplate.objects.create(template_name="Cabinet Refinish")

        bundle = TemplateBundle.objects.create(
            work_order_template=wot,
            name="Prep Work",
            line_item_type=lit
        )

        self.assertEqual(bundle.work_order_template, wot)
        self.assertEqual(bundle.name, "Prep Work")
        self.assertEqual(bundle.line_item_type, lit)

    def test_bundle_name_unique_per_template(self):
        """Bundle names must be unique within a WorkOrderTemplate"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        wot = WorkOrderTemplate.objects.create(template_name="Cabinet Refinish")

        TemplateBundle.objects.create(work_order_template=wot, name="Prep", line_item_type=lit)

        with self.assertRaises(IntegrityError):
            TemplateBundle.objects.create(work_order_template=wot, name="Prep", line_item_type=lit)

    def test_bundle_cascades_on_template_delete(self):
        """Deleting WorkOrderTemplate deletes its bundles"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        wot = WorkOrderTemplate.objects.create(template_name="Cabinet Refinish")
        TemplateBundle.objects.create(work_order_template=wot, name="Prep", line_item_type=lit)

        wot.delete()
        self.assertEqual(TemplateBundle.objects.count(), 0)

    def test_bundle_line_item_type_protected(self):
        """Cannot delete LineItemType if TemplateBundle references it"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        wot = WorkOrderTemplate.objects.create(template_name="Cabinet Refinish")
        TemplateBundle.objects.create(work_order_template=wot, name="Prep", line_item_type=lit)

        with self.assertRaises(ProtectedError):
            lit.delete()


class TestTemplateTaskAssociationMapping(TestCase):
    """Tests for TemplateTaskAssociation mapping fields"""

    def test_association_direct_mapping(self):
        """Association can have direct mapping strategy"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        wot = WorkOrderTemplate.objects.create(template_name="Cabinet Refinish")
        tt = TaskTemplate.objects.create(template_name="Sand", line_item_type=lit)

        assoc = TemplateTaskAssociation.objects.create(
            work_order_template=wot,
            task_template=tt,
            est_qty=1,
            mapping_strategy='direct'
        )

        self.assertEqual(assoc.mapping_strategy, 'direct')
        self.assertIsNone(assoc.bundle)

    def test_association_bundle_mapping(self):
        """Association can point to a bundle"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        wot = WorkOrderTemplate.objects.create(template_name="Cabinet Refinish")
        tt = TaskTemplate.objects.create(template_name="Sand", line_item_type=lit)
        bundle = TemplateBundle.objects.create(work_order_template=wot, name="Prep", line_item_type=lit)

        assoc = TemplateTaskAssociation.objects.create(
            work_order_template=wot,
            task_template=tt,
            est_qty=1,
            mapping_strategy='bundle',
            bundle=bundle
        )

        self.assertEqual(assoc.mapping_strategy, 'bundle')
        self.assertEqual(assoc.bundle, bundle)

    def test_bundle_must_belong_to_same_template(self):
        """Cannot assign a bundle from a different WorkOrderTemplate"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        wot1 = WorkOrderTemplate.objects.create(template_name="Cabinet Refinish")
        wot2 = WorkOrderTemplate.objects.create(template_name="Table Refinish")
        tt = TaskTemplate.objects.create(template_name="Sand", line_item_type=lit)
        bundle = TemplateBundle.objects.create(work_order_template=wot2, name="Prep", line_item_type=lit)

        assoc = TemplateTaskAssociation(
            work_order_template=wot1,
            task_template=tt,
            est_qty=1,
            mapping_strategy='bundle',
            bundle=bundle  # Wrong template!
        )

        with self.assertRaises(ValidationError):
            assoc.full_clean()


class TestEstimateGeneration(TestCase):
    """Tests for EstimateGenerationService with TemplateBundle system"""

    def setUp(self):
        """Create base test data"""
        from apps.core.models import Configuration

        # Create required Configuration entries for number generation
        Configuration.objects.get_or_create(
            key='estimate_number_sequence',
            defaults={'value': 'EST-{year}-{counter:05d}'}
        )
        Configuration.objects.get_or_create(
            key='estimate_counter',
            defaults={'value': '0'}
        )

        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.lit_labor, _ = LineItemType.objects.get_or_create(code="LBR", defaults={"name": "Labor"})
        self.lit_material, _ = LineItemType.objects.get_or_create(code="MAT", defaults={"name": "Material"})

    def test_direct_tasks_become_line_items(self):
        """Tasks with direct mapping become individual line items"""
        # Create templates
        wot = WorkOrderTemplate.objects.create(template_name="Simple Job")
        tt1 = TaskTemplate.objects.create(template_name="Sand", rate=50, line_item_type=self.lit_labor)
        tt2 = TaskTemplate.objects.create(template_name="Stain", rate=75, line_item_type=self.lit_labor)

        # Create associations (both direct)
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt1, est_qty=2, mapping_strategy='direct'
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt2, est_qty=1, mapping_strategy='direct'
        )

        # Create worksheet and tasks
        worksheet = EstWorksheet.objects.create(job=self.job)
        Task.objects.create(est_worksheet=worksheet, name="Sand", rate=50, est_qty=2, template=tt1)
        Task.objects.create(est_worksheet=worksheet, name="Stain", rate=75, est_qty=1, template=tt2)

        # Generate estimate
        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        # Should have 2 line items
        self.assertEqual(estimate.estimatelineitem_set.count(), 2)
        line_items = list(estimate.estimatelineitem_set.order_by('line_number'))
        self.assertEqual(line_items[0].description, "Sand")
        self.assertEqual(line_items[0].line_item_type, self.lit_labor)
        self.assertEqual(line_items[1].description, "Stain")

    def test_bundled_tasks_become_one_line_item(self):
        """Tasks in same bundle become one line item"""
        wot = WorkOrderTemplate.objects.create(template_name="Bundle Job")
        bundle = TemplateBundle.objects.create(
            work_order_template=wot, name="Prep Work", line_item_type=self.lit_labor
        )

        tt1 = TaskTemplate.objects.create(template_name="Sand", rate=50, line_item_type=self.lit_labor)
        tt2 = TaskTemplate.objects.create(template_name="Clean", rate=25, line_item_type=self.lit_labor)

        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt1, est_qty=1, mapping_strategy='bundle', bundle=bundle
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt2, est_qty=1, mapping_strategy='bundle', bundle=bundle
        )

        worksheet = EstWorksheet.objects.create(job=self.job)
        task_bundle = TaskBundle.objects.create(
            est_worksheet=worksheet, name="Prep Work",
            line_item_type=self.lit_labor, source_template_bundle=bundle
        )
        Task.objects.create(
            est_worksheet=worksheet, name="Sand", rate=50, est_qty=1,
            template=tt1, mapping_strategy='bundle', bundle=task_bundle
        )
        Task.objects.create(
            est_worksheet=worksheet, name="Clean", rate=25, est_qty=1,
            template=tt2, mapping_strategy='bundle', bundle=task_bundle
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        # Should have 1 line item (bundled)
        self.assertEqual(estimate.estimatelineitem_set.count(), 1)
        line_item = estimate.estimatelineitem_set.first()
        self.assertEqual(line_item.description, "Prep Work")
        self.assertEqual(line_item.line_item_type, self.lit_labor)
        self.assertEqual(line_item.price_currency, Decimal('75'))  # 50 + 25

    def test_excluded_tasks_not_on_estimate(self):
        """Tasks with exclude mapping don't appear on estimate"""
        wot = WorkOrderTemplate.objects.create(template_name="With Excluded")
        tt1 = TaskTemplate.objects.create(template_name="Sand", rate=50, line_item_type=self.lit_labor)
        tt2 = TaskTemplate.objects.create(template_name="Internal Check", rate=0, line_item_type=self.lit_labor)

        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt1, est_qty=1, mapping_strategy='direct'
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt2, est_qty=1, mapping_strategy='exclude'
        )

        worksheet = EstWorksheet.objects.create(job=self.job)
        Task.objects.create(
            est_worksheet=worksheet, name="Sand", rate=50, est_qty=1,
            template=tt1, mapping_strategy='direct'
        )
        Task.objects.create(
            est_worksheet=worksheet, name="Internal Check", rate=0, est_qty=1,
            template=tt2, mapping_strategy='exclude'
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        self.assertEqual(estimate.estimatelineitem_set.count(), 1)
        self.assertEqual(estimate.estimatelineitem_set.first().description, "Sand")
