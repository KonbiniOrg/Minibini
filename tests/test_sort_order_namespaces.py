"""Tests for sort_order namespace separation: container-level vs within-bundle."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.jobs.models import (
    Task, TaskBundle, EstWorksheet, Job,
    WorkOrderTemplate, TaskTemplate, TemplateTaskAssociation, TemplateBundle,
)
from apps.contacts.models import Contact
from apps.core.models import User, LineItemType


class SortOrderAutoGenerationTest(TestCase):
    """Task.save() auto-generation should be namespace-aware."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test', last_name='User')
        self.job = Job.objects.create(job_number='J001', contact=self.contact)
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.lit, _ = LineItemType.objects.get_or_create(
            code='LBR', defaults={'name': 'Labor'}
        )

    def test_new_unbundled_task_ignores_bundled_task_sort_orders(self):
        """Adding an unbundled task should not consider bundled tasks' sort_order values."""
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='Bundle',
            line_item_type=self.lit, sort_order=1
        )
        # Bundled tasks with HIGH within-bundle sort_orders (50, 99)
        # If save() wrongly considers these, the new unbundled task would get 100
        Task.objects.create(
            est_worksheet=self.worksheet, name='Bundled 1',
            rate=10, mapping_strategy='bundle', bundle=bundle, sort_order=50
        )
        Task.objects.create(
            est_worksheet=self.worksheet, name='Bundled 2',
            rate=10, mapping_strategy='bundle', bundle=bundle, sort_order=99
        )
        # Unbundled task at container sort_order 2
        Task.objects.create(
            est_worksheet=self.worksheet, name='Unbundled 1',
            rate=10, sort_order=2
        )

        # New unbundled task should get sort_order 3 (max of unbundled=2, bundle=1, so max=2, +1=3)
        # NOT sort_order 100 (max across all tasks including bundled = 99, +1)
        new_task = Task.objects.create(
            est_worksheet=self.worksheet, name='Unbundled 2', rate=10
        )
        self.assertEqual(new_task.sort_order, 3)

    def test_new_unbundled_task_considers_bundle_sort_order(self):
        """Adding an unbundled task should consider TaskBundle sort_orders (they share container namespace)."""
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='Bundle',
            line_item_type=self.lit, sort_order=5
        )
        Task.objects.create(
            est_worksheet=self.worksheet, name='Bundled 1',
            rate=10, mapping_strategy='bundle', bundle=bundle, sort_order=1
        )
        # Unbundled task at sort_order 2
        Task.objects.create(
            est_worksheet=self.worksheet, name='Unbundled 1',
            rate=10, sort_order=2
        )

        # New unbundled task should be after the bundle (sort_order=5), so 6
        new_task = Task.objects.create(
            est_worksheet=self.worksheet, name='Unbundled 2', rate=10
        )
        self.assertEqual(new_task.sort_order, 6)

    def test_new_bundled_task_uses_within_bundle_namespace(self):
        """Adding a bundled task should get sort_order based on max within that bundle only."""
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='Bundle',
            line_item_type=self.lit, sort_order=1
        )
        Task.objects.create(
            est_worksheet=self.worksheet, name='Bundled 1',
            rate=10, mapping_strategy='bundle', bundle=bundle, sort_order=1
        )
        Task.objects.create(
            est_worksheet=self.worksheet, name='Bundled 2',
            rate=10, mapping_strategy='bundle', bundle=bundle, sort_order=2
        )
        # Unbundled task with high sort_order
        Task.objects.create(
            est_worksheet=self.worksheet, name='Unbundled',
            rate=10, sort_order=10
        )

        # New bundled task should get sort_order 3 (max within bundle = 2, +1)
        # NOT 11 (max across all tasks = 10, +1)
        new_task = Task.objects.create(
            est_worksheet=self.worksheet, name='Bundled 3',
            rate=10, mapping_strategy='bundle', bundle=bundle
        )
        self.assertEqual(new_task.sort_order, 3)


class BundleCreationSortOrderTest(TestCase):
    """Bundling tasks should reassign their sort_order to within-bundle values."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', email='test@test.com', password='testpass123'
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.contact = Contact.objects.create(first_name='Test', last_name='User')
        self.job = Job.objects.create(job_number='J001', contact=self.contact)
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.lit, _ = LineItemType.objects.get_or_create(
            code='LBR', defaults={'name': 'Labor'}
        )

    def test_bundled_tasks_get_sequential_within_bundle_sort_order(self):
        """Tasks bundled together should get sort_order 1, 2, 3... regardless of original values."""
        t1 = Task.objects.create(
            est_worksheet=self.worksheet, name='Task A', rate=10, sort_order=3
        )
        t2 = Task.objects.create(
            est_worksheet=self.worksheet, name='Task B', rate=20, sort_order=7
        )
        t3 = Task.objects.create(
            est_worksheet=self.worksheet, name='Task C', rate=30, sort_order=12
        )

        url = reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        self.client.post(url, {
            'bundle_tasks': '1',
            'selected_tasks': [t1.task_id, t2.task_id, t3.task_id],
            'bundle_name': 'Test Bundle',
            'bundle_description': '',
            'line_item_type': self.lit.pk,
        })

        t1.refresh_from_db()
        t2.refresh_from_db()
        t3.refresh_from_db()

        # Should be reassigned to sequential within-bundle values
        sort_orders = sorted([t1.sort_order, t2.sort_order, t3.sort_order])
        self.assertEqual(sort_orders, [1, 2, 3])


class UnbundleSortOrderTest(TestCase):
    """Unbundling a task should place it right after the bundle, not at end of list."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', email='test@test.com', password='testpass123'
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.contact = Contact.objects.create(first_name='Test', last_name='User')
        self.job = Job.objects.create(job_number='J001', contact=self.contact)
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.lit, _ = LineItemType.objects.get_or_create(
            code='LBR', defaults={'name': 'Labor'}
        )

    def test_unbundled_task_goes_right_after_bundle(self):
        """Unbundled task should get sort_order = bundle.sort_order + 1."""
        # Unbundled task at container sort_order 10 (higher than bundle)
        solo = Task.objects.create(
            est_worksheet=self.worksheet, name='Solo', rate=10, sort_order=10
        )
        # Bundle at container sort_order 5
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='Bundle',
            line_item_type=self.lit, sort_order=5
        )
        t1 = Task.objects.create(
            est_worksheet=self.worksheet, name='Bundled A', rate=10,
            mapping_strategy='bundle', bundle=bundle, sort_order=1
        )
        Task.objects.create(
            est_worksheet=self.worksheet, name='Bundled B', rate=10,
            mapping_strategy='bundle', bundle=bundle, sort_order=2
        )
        Task.objects.create(
            est_worksheet=self.worksheet, name='Bundled C', rate=10,
            mapping_strategy='bundle', bundle=bundle, sort_order=3
        )

        # Unbundle t1
        url = reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        self.client.post(url, {'remove_task': t1.task_id})

        t1.refresh_from_db()
        solo.refresh_from_db()
        # Should go right after the bundle (sort_order=5), so 6
        self.assertEqual(t1.sort_order, 6)
        self.assertEqual(t1.mapping_strategy, 'direct')
        self.assertIsNone(t1.bundle)
        # Solo was at 10, bumped to 11 (>= 6, so +1)
        self.assertEqual(solo.sort_order, 11)

    def test_unbundle_bumps_items_at_insertion_point(self):
        """Existing container items at bundle.sort_order + 1 get bumped to make room."""
        # Task right after the bundle
        neighbor = Task.objects.create(
            est_worksheet=self.worksheet, name='Neighbor', rate=10, sort_order=6
        )
        # Bundle at container sort_order 5
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='Bundle',
            line_item_type=self.lit, sort_order=5
        )
        t1 = Task.objects.create(
            est_worksheet=self.worksheet, name='Bundled A', rate=10,
            mapping_strategy='bundle', bundle=bundle, sort_order=1
        )
        Task.objects.create(
            est_worksheet=self.worksheet, name='Bundled B', rate=10,
            mapping_strategy='bundle', bundle=bundle, sort_order=2
        )

        url = reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        self.client.post(url, {'remove_task': t1.task_id})

        t1.refresh_from_db()
        neighbor.refresh_from_db()
        # Unbundled task takes the slot right after bundle
        self.assertEqual(t1.sort_order, 6)
        # Neighbor was at 6, bumped to 7
        self.assertEqual(neighbor.sort_order, 7)

    def test_auto_dissolve_positions_tasks_at_bundle_location(self):
        """When bundle dissolves, both tasks appear where the bundle was."""
        # Solo task further down
        solo = Task.objects.create(
            est_worksheet=self.worksheet, name='Solo', rate=10, sort_order=10
        )
        # Bundle at container sort_order 5
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='Bundle',
            line_item_type=self.lit, sort_order=5
        )
        t1 = Task.objects.create(
            est_worksheet=self.worksheet, name='Bundled A', rate=10,
            mapping_strategy='bundle', bundle=bundle, sort_order=1
        )
        t2 = Task.objects.create(
            est_worksheet=self.worksheet, name='Bundled B', rate=10,
            mapping_strategy='bundle', bundle=bundle, sort_order=2
        )

        # Unbundle t1 — only t2 remains, triggers auto-dissolve
        url = reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        self.client.post(url, {'remove_task': t1.task_id})

        t1.refresh_from_db()
        t2.refresh_from_db()
        solo.refresh_from_db()
        # Last task (t2) takes bundle's position
        self.assertEqual(t2.sort_order, 5)
        self.assertEqual(t2.mapping_strategy, 'direct')
        self.assertIsNone(t2.bundle)
        # Removed task (t1) goes right after
        self.assertEqual(t1.sort_order, 6)
        self.assertEqual(t1.mapping_strategy, 'direct')
        # Solo bumped from 10 to 11
        self.assertEqual(solo.sort_order, 11)
        # Bundle should be deleted
        self.assertFalse(TaskBundle.objects.filter(pk=bundle.pk).exists())


class GenerateTaskSortOrderTest(TestCase):
    """generate_tasks_for_worksheet should pass association sort_order through."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test', last_name='User')
        self.job = Job.objects.create(job_number='J001', contact=self.contact)
        self.lit_labor, _ = LineItemType.objects.get_or_create(
            code='LBR', defaults={'name': 'Labor'}
        )
        self.lit_material, _ = LineItemType.objects.get_or_create(
            code='MAT', defaults={'name': 'Material'}
        )

    def test_generated_bundled_tasks_get_association_sort_order(self):
        """Bundled tasks should get the association's sort_order (within-bundle position)."""
        wot = WorkOrderTemplate.objects.create(template_name='Test Template')
        template_bundle = TemplateBundle.objects.create(
            work_order_template=wot, name='Prep',
            line_item_type=self.lit_labor, sort_order=1
        )
        tt1 = TaskTemplate.objects.create(
            template_name='Sand', rate=50, line_item_type=self.lit_labor
        )
        tt2 = TaskTemplate.objects.create(
            template_name='Clean', rate=25, line_item_type=self.lit_labor
        )
        # Use non-sequential sort_orders (5, 10) to distinguish from auto-generated (1, 2)
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt1,
            est_qty=1, mapping_strategy='bundle', bundle=template_bundle,
            sort_order=5
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt2,
            est_qty=1, mapping_strategy='bundle', bundle=template_bundle,
            sort_order=10
        )

        worksheet = EstWorksheet.objects.create(job=self.job)
        tasks = wot.generate_tasks_for_worksheet(worksheet)

        sand = next(t for t in tasks if t.name == 'Sand')
        clean = next(t for t in tasks if t.name == 'Clean')
        self.assertEqual(sand.sort_order, 5)
        self.assertEqual(clean.sort_order, 10)

    def test_generated_unbundled_tasks_get_association_sort_order(self):
        """Unbundled tasks should get the association's sort_order (container-level position)."""
        wot = WorkOrderTemplate.objects.create(template_name='Test Template')
        template_bundle = TemplateBundle.objects.create(
            work_order_template=wot, name='Prep',
            line_item_type=self.lit_labor, sort_order=5
        )
        tt_direct = TaskTemplate.objects.create(
            template_name='Finish', rate=100, line_item_type=self.lit_labor
        )
        tt_bundled = TaskTemplate.objects.create(
            template_name='Sand', rate=50, line_item_type=self.lit_labor
        )
        # Direct task at sort_order 3 (not 1, to avoid coincidental match with auto-gen)
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt_direct,
            est_qty=2, mapping_strategy='direct', sort_order=3
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt_bundled,
            est_qty=1, mapping_strategy='bundle', bundle=template_bundle,
            sort_order=1
        )
        # Excluded task at container sort_order 7
        tt_excl = TaskTemplate.objects.create(
            template_name='Overhead', rate=0, line_item_type=self.lit_labor
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt_excl,
            est_qty=1, mapping_strategy='exclude', sort_order=7
        )

        worksheet = EstWorksheet.objects.create(job=self.job)
        tasks = wot.generate_tasks_for_worksheet(worksheet)

        finish = next(t for t in tasks if t.name == 'Finish')
        overhead = next(t for t in tasks if t.name == 'Overhead')
        self.assertEqual(finish.sort_order, 3)
        self.assertEqual(overhead.sort_order, 7)


class TemplateUnbundleSortOrderTest(TestCase):
    """Template unbundle should bump existing items to make room."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', email='test@test.com', password='testpass123'
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.lit, _ = LineItemType.objects.get_or_create(
            code='LBR', defaults={'name': 'Labor'}
        )

    def test_template_unbundle_bumps_items_at_insertion_point(self):
        """Unbundling a template assoc should bump existing items at bundle.sort_order + 1."""
        wot = WorkOrderTemplate.objects.create(template_name='Test')
        template_bundle = TemplateBundle.objects.create(
            work_order_template=wot, name='Bundle',
            line_item_type=self.lit, sort_order=5
        )
        tt1 = TaskTemplate.objects.create(
            template_name='Alpha', rate=10, line_item_type=self.lit
        )
        tt2 = TaskTemplate.objects.create(
            template_name='Beta', rate=20, line_item_type=self.lit
        )
        tt3 = TaskTemplate.objects.create(
            template_name='Gamma', rate=30, line_item_type=self.lit
        )
        # Two bundled associations
        a1 = TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt1,
            est_qty=1, mapping_strategy='bundle', bundle=template_bundle,
            sort_order=1
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt2,
            est_qty=1, mapping_strategy='bundle', bundle=template_bundle,
            sort_order=2
        )
        # Unbundled association right after the bundle (collision point)
        a3 = TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt3,
            est_qty=1, mapping_strategy='direct', sort_order=6
        )

        url = reverse('jobs:work_order_template_detail', args=[wot.template_id])
        self.client.post(url, {'remove_task': tt1.template_id})

        a1.refresh_from_db()
        a3.refresh_from_db()
        # Unbundled assoc should be at bundle.sort_order + 1 = 6
        self.assertEqual(a1.sort_order, 6)
        self.assertEqual(a1.mapping_strategy, 'direct')
        self.assertIsNone(a1.bundle)
        # Gamma was at 6, should be bumped to 7
        self.assertEqual(a3.sort_order, 7)
