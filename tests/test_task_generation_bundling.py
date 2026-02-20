from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import (
    Task, TaskBundle, EstWorksheet, WorkOrder, Job,
    WorkOrderTemplate, TaskTemplate, TemplateTaskAssociation, TemplateBundle,
)
from apps.contacts.models import Contact
from apps.core.models import LineItemType


class TaskGenerationBundlingTest(TestCase):
    """Tests that generate_tasks_for_worksheet copies bundling config to instances."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.lit_labor, _ = LineItemType.objects.get_or_create(
            code="LBR", defaults={"name": "Labor"}
        )
        self.lit_material, _ = LineItemType.objects.get_or_create(
            code="MAT", defaults={"name": "Material"}
        )

    def test_direct_tasks_get_direct_mapping(self):
        """Tasks generated from direct associations get mapping_strategy='direct'."""
        wot = WorkOrderTemplate.objects.create(template_name="Simple Job")
        tt = TaskTemplate.objects.create(
            template_name="Sand", rate=50, line_item_type=self.lit_labor
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt,
            est_qty=2, mapping_strategy='direct'
        )

        worksheet = EstWorksheet.objects.create(job=self.job)
        tasks = wot.generate_tasks_for_worksheet(worksheet)

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].mapping_strategy, 'direct')
        self.assertIsNone(tasks[0].bundle)

    def test_excluded_tasks_get_exclude_mapping(self):
        """Tasks generated from excluded associations get mapping_strategy='exclude'."""
        wot = WorkOrderTemplate.objects.create(template_name="With Excluded")
        tt = TaskTemplate.objects.create(
            template_name="Internal Check", rate=0, line_item_type=self.lit_labor
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt,
            est_qty=1, mapping_strategy='exclude'
        )

        worksheet = EstWorksheet.objects.create(job=self.job)
        tasks = wot.generate_tasks_for_worksheet(worksheet)

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].mapping_strategy, 'exclude')
        self.assertIsNone(tasks[0].bundle)

    def test_bundled_tasks_create_task_bundle(self):
        """Generating from a template with a TemplateBundle creates a TaskBundle on the worksheet."""
        wot = WorkOrderTemplate.objects.create(template_name="Bundle Job")
        template_bundle = TemplateBundle.objects.create(
            work_order_template=wot, name="Prep Work",
            line_item_type=self.lit_labor, sort_order=1
        )

        tt1 = TaskTemplate.objects.create(
            template_name="Sand", rate=50, line_item_type=self.lit_labor
        )
        tt2 = TaskTemplate.objects.create(
            template_name="Clean", rate=25, line_item_type=self.lit_labor
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt1,
            est_qty=1, mapping_strategy='bundle', bundle=template_bundle
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt2,
            est_qty=1, mapping_strategy='bundle', bundle=template_bundle
        )

        worksheet = EstWorksheet.objects.create(job=self.job)
        tasks = wot.generate_tasks_for_worksheet(worksheet)

        # Should have created a TaskBundle on the worksheet
        task_bundles = list(worksheet.bundles.all())
        self.assertEqual(len(task_bundles), 1)
        tb = task_bundles[0]
        self.assertEqual(tb.name, "Prep Work")
        self.assertEqual(tb.line_item_type, self.lit_labor)
        self.assertEqual(tb.source_template_bundle, template_bundle)
        self.assertEqual(tb.sort_order, 1)

        # Both tasks should be bundled and point to the TaskBundle
        self.assertEqual(len(tasks), 2)
        for task in tasks:
            self.assertEqual(task.mapping_strategy, 'bundle')
            self.assertEqual(task.bundle, tb)

    def test_multiple_bundles_created_separately(self):
        """Each TemplateBundle becomes its own TaskBundle."""
        wot = WorkOrderTemplate.objects.create(template_name="Multi Bundle")
        bundle_a = TemplateBundle.objects.create(
            work_order_template=wot, name="Prep",
            line_item_type=self.lit_labor, sort_order=1
        )
        bundle_b = TemplateBundle.objects.create(
            work_order_template=wot, name="Materials",
            line_item_type=self.lit_material, sort_order=2
        )

        tt1 = TaskTemplate.objects.create(
            template_name="Sand", rate=50, line_item_type=self.lit_labor
        )
        tt2 = TaskTemplate.objects.create(
            template_name="Buy Stain", rate=30, line_item_type=self.lit_material
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt1,
            est_qty=1, mapping_strategy='bundle', bundle=bundle_a
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt2,
            est_qty=1, mapping_strategy='bundle', bundle=bundle_b
        )

        worksheet = EstWorksheet.objects.create(job=self.job)
        tasks = wot.generate_tasks_for_worksheet(worksheet)

        task_bundles = list(worksheet.bundles.order_by('sort_order'))
        self.assertEqual(len(task_bundles), 2)
        self.assertEqual(task_bundles[0].name, "Prep")
        self.assertEqual(task_bundles[0].source_template_bundle, bundle_a)
        self.assertEqual(task_bundles[1].name, "Materials")
        self.assertEqual(task_bundles[1].source_template_bundle, bundle_b)

        # Each task should point to the correct bundle
        sand_task = next(t for t in tasks if t.name == "Sand")
        buy_task = next(t for t in tasks if t.name == "Buy Stain")
        self.assertEqual(sand_task.bundle, task_bundles[0])
        self.assertEqual(buy_task.bundle, task_bundles[1])

    def test_mixed_direct_and_bundled(self):
        """Generation handles a mix of direct, bundled, and excluded tasks."""
        wot = WorkOrderTemplate.objects.create(template_name="Mixed Job")
        bundle = TemplateBundle.objects.create(
            work_order_template=wot, name="Prep",
            line_item_type=self.lit_labor, sort_order=1
        )

        tt_sand = TaskTemplate.objects.create(
            template_name="Sand", rate=50, line_item_type=self.lit_labor
        )
        tt_clean = TaskTemplate.objects.create(
            template_name="Clean", rate=25, line_item_type=self.lit_labor
        )
        tt_finish = TaskTemplate.objects.create(
            template_name="Apply Finish", rate=100, line_item_type=self.lit_labor
        )
        tt_qc = TaskTemplate.objects.create(
            template_name="QC Check", rate=0, line_item_type=self.lit_labor
        )

        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt_sand,
            est_qty=1, mapping_strategy='bundle', bundle=bundle
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt_clean,
            est_qty=1, mapping_strategy='bundle', bundle=bundle
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt_finish,
            est_qty=2, mapping_strategy='direct'
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt_qc,
            est_qty=1, mapping_strategy='exclude'
        )

        worksheet = EstWorksheet.objects.create(job=self.job)
        tasks = wot.generate_tasks_for_worksheet(worksheet)

        self.assertEqual(len(tasks), 4)

        # One TaskBundle created
        self.assertEqual(worksheet.bundles.count(), 1)

        task_map = {t.name: t for t in tasks}
        self.assertEqual(task_map["Sand"].mapping_strategy, 'bundle')
        self.assertEqual(task_map["Clean"].mapping_strategy, 'bundle')
        self.assertEqual(task_map["Apply Finish"].mapping_strategy, 'direct')
        self.assertIsNone(task_map["Apply Finish"].bundle)
        self.assertEqual(task_map["QC Check"].mapping_strategy, 'exclude')
        self.assertIsNone(task_map["QC Check"].bundle)
