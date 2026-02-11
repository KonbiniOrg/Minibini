"""
Tests that EstimateGenerationService reads mapping config from instance-level
Task fields (mapping_strategy, bundle) rather than reaching back to templates.
"""
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import (
    Task, TaskBundle, EstWorksheet, Job, EstimateLineItem,
)
from apps.jobs.services import EstimateGenerationService
from apps.contacts.models import Contact
from apps.core.models import LineItemType, Configuration


class InstanceLevelEstimateGenerationTest(TestCase):
    """EstimateGenerationService should use Task.mapping_strategy and Task.bundle,
    not reach back to TemplateTaskAssociation."""

    def setUp(self):
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
        self.lit_labor, _ = LineItemType.objects.get_or_create(
            code="LBR", defaults={"name": "Labor"}
        )
        self.lit_material, _ = LineItemType.objects.get_or_create(
            code="MAT", defaults={"name": "Material"}
        )

    def test_direct_task_without_template(self):
        """A manually created task (no template) with mapping_strategy='direct' becomes a line item."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        Task.objects.create(
            est_worksheet=worksheet, name="Custom Task",
            rate=Decimal('100'), est_qty=Decimal('2'), units='hours',
            mapping_strategy='direct'
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        self.assertEqual(estimate.estimatelineitem_set.count(), 1)
        li = estimate.estimatelineitem_set.first()
        self.assertEqual(li.description, "Custom Task")
        self.assertEqual(li.price_currency, Decimal('200.00'))

    def test_excluded_task_without_template(self):
        """A manually created task with mapping_strategy='exclude' does not become a line item."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        Task.objects.create(
            est_worksheet=worksheet, name="Visible Task",
            rate=Decimal('50'), est_qty=Decimal('1'),
            mapping_strategy='direct'
        )
        Task.objects.create(
            est_worksheet=worksheet, name="Internal Task",
            rate=Decimal('25'), est_qty=Decimal('1'),
            mapping_strategy='exclude'
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        self.assertEqual(estimate.estimatelineitem_set.count(), 1)
        self.assertEqual(estimate.estimatelineitem_set.first().description, "Visible Task")

    def test_bundled_tasks_without_template(self):
        """Manually created tasks with TaskBundle become one line item, no template needed."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        bundle = TaskBundle.objects.create(
            est_worksheet=worksheet, name="Prep Work",
            line_item_type=self.lit_labor, sort_order=1
        )
        Task.objects.create(
            est_worksheet=worksheet, name="Sand",
            rate=Decimal('50'), est_qty=Decimal('1'),
            mapping_strategy='bundle', bundle=bundle
        )
        Task.objects.create(
            est_worksheet=worksheet, name="Clean",
            rate=Decimal('25'), est_qty=Decimal('1'),
            mapping_strategy='bundle', bundle=bundle
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        self.assertEqual(estimate.estimatelineitem_set.count(), 1)
        li = estimate.estimatelineitem_set.first()
        self.assertEqual(li.description, "Prep Work")
        self.assertEqual(li.line_item_type, self.lit_labor)
        self.assertEqual(li.price_currency, Decimal('75.00'))

    def test_mixed_strategies_without_template(self):
        """Mixed direct, bundled, excluded - all from instance-level config, no templates."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        bundle = TaskBundle.objects.create(
            est_worksheet=worksheet, name="Prep",
            line_item_type=self.lit_labor, sort_order=1
        )

        Task.objects.create(
            est_worksheet=worksheet, name="Sand",
            rate=Decimal('50'), est_qty=Decimal('1'),
            mapping_strategy='bundle', bundle=bundle
        )
        Task.objects.create(
            est_worksheet=worksheet, name="Clean",
            rate=Decimal('25'), est_qty=Decimal('1'),
            mapping_strategy='bundle', bundle=bundle
        )
        Task.objects.create(
            est_worksheet=worksheet, name="Apply Finish",
            rate=Decimal('100'), est_qty=Decimal('2'),
            mapping_strategy='direct'
        )
        Task.objects.create(
            est_worksheet=worksheet, name="QC Check",
            rate=Decimal('0'), est_qty=Decimal('1'),
            mapping_strategy='exclude'
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        # 1 bundle line item + 1 direct line item = 2 (excluded is skipped)
        self.assertEqual(estimate.estimatelineitem_set.count(), 2)
        line_items = list(estimate.estimatelineitem_set.order_by('line_number'))

        descriptions = {li.description for li in line_items}
        self.assertIn("Prep", descriptions)
        self.assertIn("Apply Finish", descriptions)
        self.assertNotIn("QC Check", descriptions)

    def test_instance_mapping_overrides_template(self):
        """If a task has a template but instance-level mapping_strategy='exclude',
        the instance-level config wins."""
        from apps.jobs.models import TaskTemplate, WorkOrderTemplate, TemplateTaskAssociation

        wot = WorkOrderTemplate.objects.create(template_name="Job Template")
        tt = TaskTemplate.objects.create(
            template_name="Sand", rate=50, line_item_type=self.lit_labor
        )
        # Template says 'direct'
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt,
            est_qty=1, mapping_strategy='direct'
        )

        worksheet = EstWorksheet.objects.create(job=self.job)
        # But instance says 'exclude'
        Task.objects.create(
            est_worksheet=worksheet, name="Sand",
            rate=Decimal('50'), est_qty=Decimal('1'),
            template=tt,
            mapping_strategy='exclude'
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        # Instance-level 'exclude' should win
        self.assertEqual(estimate.estimatelineitem_set.count(), 0)
