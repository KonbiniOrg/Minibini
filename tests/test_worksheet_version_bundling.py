"""Tests that create_new_version copies TaskBundles and task mapping config."""
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import Task, TaskBundle, EstWorksheet, Job
from apps.contacts.models import Contact
from apps.core.models import LineItemType


class WorksheetVersionBundlingTest(TestCase):

    def setUp(self):
        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J001", contact=self.contact)
        self.lit_labor, _ = LineItemType.objects.get_or_create(
            code="LBR", defaults={"name": "Labor"}
        )

    def test_direct_task_mapping_copied(self):
        """Task mapping_strategy is preserved across versions."""
        ws1 = EstWorksheet.objects.create(job=self.job, status='draft')
        Task.objects.create(
            est_worksheet=ws1, name="Sand", rate=Decimal('50'),
            est_qty=Decimal('1'), mapping_strategy='direct'
        )
        Task.objects.create(
            est_worksheet=ws1, name="Internal", rate=Decimal('0'),
            est_qty=Decimal('1'), mapping_strategy='exclude'
        )

        ws2 = ws1.create_new_version()

        v2_tasks = {t.name: t for t in Task.objects.filter(est_worksheet=ws2)}
        self.assertEqual(v2_tasks["Sand"].mapping_strategy, 'direct')
        self.assertEqual(v2_tasks["Internal"].mapping_strategy, 'exclude')

    def test_task_bundles_copied(self):
        """TaskBundles are duplicated on the new worksheet version."""
        ws1 = EstWorksheet.objects.create(job=self.job, status='draft')
        bundle = TaskBundle.objects.create(
            est_worksheet=ws1, name="Prep Work",
            line_item_type=self.lit_labor, sort_order=1,
            description="Preparation tasks"
        )
        Task.objects.create(
            est_worksheet=ws1, name="Sand",
            rate=Decimal('50'), est_qty=Decimal('1'),
            mapping_strategy='bundle', bundle=bundle
        )
        Task.objects.create(
            est_worksheet=ws1, name="Clean",
            rate=Decimal('25'), est_qty=Decimal('1'),
            mapping_strategy='bundle', bundle=bundle
        )

        ws2 = ws1.create_new_version()

        # New worksheet should have its own TaskBundle
        new_bundles = list(ws2.bundles.all())
        self.assertEqual(len(new_bundles), 1)
        new_bundle = new_bundles[0]
        self.assertEqual(new_bundle.name, "Prep Work")
        self.assertEqual(new_bundle.description, "Preparation tasks")
        self.assertEqual(new_bundle.line_item_type, self.lit_labor)
        self.assertEqual(new_bundle.sort_order, 1)

        # New bundle is a different object than the original
        self.assertNotEqual(new_bundle.pk, bundle.pk)

        # Tasks on new worksheet should point to the new bundle
        v2_tasks = list(Task.objects.filter(est_worksheet=ws2))
        for task in v2_tasks:
            self.assertEqual(task.mapping_strategy, 'bundle')
            self.assertEqual(task.bundle, new_bundle)

    def test_multiple_bundles_copied_with_correct_task_mapping(self):
        """Multiple bundles are each copied, and tasks point to the right new bundle."""
        ws1 = EstWorksheet.objects.create(job=self.job, status='draft')
        lit_mat, _ = LineItemType.objects.get_or_create(
            code="MAT", defaults={"name": "Material"}
        )
        bundle_a = TaskBundle.objects.create(
            est_worksheet=ws1, name="Prep",
            line_item_type=self.lit_labor, sort_order=1
        )
        bundle_b = TaskBundle.objects.create(
            est_worksheet=ws1, name="Materials",
            line_item_type=lit_mat, sort_order=2
        )

        Task.objects.create(
            est_worksheet=ws1, name="Sand",
            rate=Decimal('50'), est_qty=Decimal('1'),
            mapping_strategy='bundle', bundle=bundle_a
        )
        Task.objects.create(
            est_worksheet=ws1, name="Buy Stain",
            rate=Decimal('30'), est_qty=Decimal('1'),
            mapping_strategy='bundle', bundle=bundle_b
        )
        Task.objects.create(
            est_worksheet=ws1, name="Apply Finish",
            rate=Decimal('100'), est_qty=Decimal('2'),
            mapping_strategy='direct'
        )

        ws2 = ws1.create_new_version()

        new_bundles = {b.name: b for b in ws2.bundles.all()}
        self.assertEqual(len(new_bundles), 2)
        self.assertIn("Prep", new_bundles)
        self.assertIn("Materials", new_bundles)

        v2_tasks = {t.name: t for t in Task.objects.filter(est_worksheet=ws2)}
        self.assertEqual(v2_tasks["Sand"].bundle, new_bundles["Prep"])
        self.assertEqual(v2_tasks["Buy Stain"].bundle, new_bundles["Materials"])
        self.assertEqual(v2_tasks["Apply Finish"].mapping_strategy, 'direct')
        self.assertIsNone(v2_tasks["Apply Finish"].bundle)

    def test_original_bundles_unchanged(self):
        """Versioning doesn't modify the original worksheet's bundles or tasks."""
        ws1 = EstWorksheet.objects.create(job=self.job, status='draft')
        bundle = TaskBundle.objects.create(
            est_worksheet=ws1, name="Prep",
            line_item_type=self.lit_labor, sort_order=1
        )
        task = Task.objects.create(
            est_worksheet=ws1, name="Sand",
            rate=Decimal('50'), est_qty=Decimal('1'),
            mapping_strategy='bundle', bundle=bundle
        )

        ws2 = ws1.create_new_version()

        # Original bundle still exists and still points to ws1
        bundle.refresh_from_db()
        self.assertEqual(bundle.est_worksheet, ws1)

        # Original task still points to original bundle
        task.refresh_from_db()
        self.assertEqual(task.bundle, bundle)
        self.assertEqual(task.est_worksheet, ws1)
