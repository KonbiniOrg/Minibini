"""Tests for BundlingService and domain-level bundling operations."""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import models
from apps.estimates.models import (
    WorkOrderTemplate, TaskTemplate, TemplateTaskAssociation, TemplateBundle,
)
from apps.estimates.services import WorkOrderTemplateService, WorksheetService
from apps.jobs.models import Job, Task, TaskBundle
from apps.jobs.services import JobService
from apps.core.services import NotFoundError, BundlingService
from apps.core.models import LineItemType
from apps.contacts.models import Contact, Business


class BundlingTestBase(TestCase):
    """Shared setUp for bundling tests."""
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@test.com', work_number='555-1234',
        )
        self.business = Business.objects.create(
            business_name='Test Biz', business_phone='555-1234',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.lit = LineItemType.objects.create(
            code='SVC', name='Service', taxable=True,
        )
        self.job = JobService.create_job(name='Test Job', contact=self.contact)


# --- BundlingService low-level tests (using Task/TaskBundle) ---

class BundlingServiceBundleItemsTest(BundlingTestBase):
    """Tests for BundlingService.bundle_items."""

    def setUp(self):
        super().setUp()
        from apps.estimates.models import EstWorksheet
        self.ws = EstWorksheet.objects.create(job=self.job, status='draft')
        self.t1 = Task.objects.create(
            est_worksheet=self.ws, name='Task 1', sort_order=1,
        )
        self.t2 = Task.objects.create(
            est_worksheet=self.ws, name='Task 2', sort_order=2,
        )
        self.t3 = Task.objects.create(
            est_worksheet=self.ws, name='Task 3', sort_order=3,
        )
        self.bundle = TaskBundle.objects.create(
            est_worksheet=self.ws, name='Bundle A',
            line_item_type=self.lit, sort_order=10,
        )

    def test_bundle_items(self):
        """Bundle two tasks into a bundle."""
        items = Task.objects.filter(pk__in=[self.t1.pk, self.t2.pk])
        BundlingService.bundle_items(items, self.bundle)
        self.t1.refresh_from_db()
        self.t2.refresh_from_db()
        self.assertEqual(self.t1.mapping_strategy, 'bundle')
        self.assertEqual(self.t1.bundle, self.bundle)
        self.assertEqual(self.t2.mapping_strategy, 'bundle')
        self.assertEqual(self.t2.bundle, self.bundle)

    def test_bundle_items_sequential_sort_order(self):
        """Bundled items get sequential within-bundle sort_order."""
        items = Task.objects.filter(
            pk__in=[self.t1.pk, self.t2.pk]
        ).order_by('sort_order')
        BundlingService.bundle_items(items, self.bundle)
        self.t1.refresh_from_db()
        self.t2.refresh_from_db()
        self.assertEqual(self.t1.sort_order, 1)
        self.assertEqual(self.t2.sort_order, 2)

    def test_bundle_items_additive(self):
        """Adding to existing bundle continues sort_order from max."""
        # Put t1 in the bundle first
        self.t1.mapping_strategy = 'bundle'
        self.t1.bundle = self.bundle
        self.t1.sort_order = 1
        self.t1.save()
        # Now add t2
        items = Task.objects.filter(pk=self.t2.pk)
        BundlingService.bundle_items(items, self.bundle)
        self.t2.refresh_from_db()
        self.assertEqual(self.t2.sort_order, 2)  # continues from existing max


class BundlingServiceUnbundleItemTest(BundlingTestBase):
    """Tests for BundlingService.unbundle_item."""

    def setUp(self):
        super().setUp()
        from apps.estimates.models import EstWorksheet
        self.ws = EstWorksheet.objects.create(job=self.job, status='draft')
        self.bundle = TaskBundle.objects.create(
            est_worksheet=self.ws, name='Bundle A',
            line_item_type=self.lit, sort_order=5,
        )
        self.t1 = Task.objects.create(
            est_worksheet=self.ws, name='Task 1', sort_order=1,
            mapping_strategy='bundle', bundle=self.bundle,
        )
        self.t2 = Task.objects.create(
            est_worksheet=self.ws, name='Task 2', sort_order=2,
            mapping_strategy='bundle', bundle=self.bundle,
        )
        self.t3 = Task.objects.create(
            est_worksheet=self.ws, name='Task 3', sort_order=3,
            mapping_strategy='bundle', bundle=self.bundle,
        )
        # An unbundled task at container level
        self.t4 = Task.objects.create(
            est_worksheet=self.ws, name='Task 4', sort_order=6,
        )

    def test_unbundle_item(self):
        """Unbundled item becomes direct and gets insert_point sort_order."""
        container_items_qs = Task.objects.filter(
            est_worksheet=self.ws, bundle__isnull=True,
        )
        container_bundles_qs = TaskBundle.objects.filter(est_worksheet=self.ws)
        BundlingService.unbundle_item(
            self.t1, container_items_qs, container_bundles_qs,
        )
        self.t1.refresh_from_db()
        self.assertEqual(self.t1.mapping_strategy, 'direct')
        self.assertIsNone(self.t1.bundle)
        self.assertEqual(self.t1.sort_order, 6)  # bundle.sort_order + 1

    def test_unbundle_bumps_existing(self):
        """Items at or after insert_point get bumped."""
        container_items_qs = Task.objects.filter(
            est_worksheet=self.ws, bundle__isnull=True,
        )
        container_bundles_qs = TaskBundle.objects.filter(est_worksheet=self.ws)
        BundlingService.unbundle_item(
            self.t1, container_items_qs, container_bundles_qs,
        )
        self.t4.refresh_from_db()
        self.assertEqual(self.t4.sort_order, 7)  # was 6, bumped to 7


class BundlingServiceAutoDissolveTest(BundlingTestBase):
    """Tests for BundlingService.auto_dissolve_bundles."""

    def setUp(self):
        super().setUp()
        from apps.estimates.models import EstWorksheet
        self.ws = EstWorksheet.objects.create(job=self.job, status='draft')

    def test_dissolve_empty_bundle(self):
        """Bundle with 0 items gets deleted."""
        bundle = TaskBundle.objects.create(
            est_worksheet=self.ws, name='Empty',
            line_item_type=self.lit, sort_order=1,
        )
        bundles_qs = TaskBundle.objects.filter(est_worksheet=self.ws)
        BundlingService.auto_dissolve_bundles(bundles_qs, Task)
        self.assertFalse(TaskBundle.objects.filter(pk=bundle.pk).exists())

    def test_dissolve_single_item_bundle(self):
        """Bundle with 1 item: item is unbundled, bundle deleted."""
        bundle = TaskBundle.objects.create(
            est_worksheet=self.ws, name='Solo',
            line_item_type=self.lit, sort_order=5,
        )
        task = Task.objects.create(
            est_worksheet=self.ws, name='Lonely', sort_order=1,
            mapping_strategy='bundle', bundle=bundle,
        )
        bundles_qs = TaskBundle.objects.filter(est_worksheet=self.ws)
        BundlingService.auto_dissolve_bundles(bundles_qs, Task)
        task.refresh_from_db()
        self.assertEqual(task.mapping_strategy, 'direct')
        self.assertIsNone(task.bundle)
        self.assertEqual(task.sort_order, 5)  # inherits bundle's sort_order
        self.assertFalse(TaskBundle.objects.filter(pk=bundle.pk).exists())

    def test_skip_healthy_bundle(self):
        """Bundle with 2+ items is left alone."""
        bundle = TaskBundle.objects.create(
            est_worksheet=self.ws, name='Healthy',
            line_item_type=self.lit, sort_order=5,
        )
        Task.objects.create(
            est_worksheet=self.ws, name='T1', sort_order=1,
            mapping_strategy='bundle', bundle=bundle,
        )
        Task.objects.create(
            est_worksheet=self.ws, name='T2', sort_order=2,
            mapping_strategy='bundle', bundle=bundle,
        )
        bundles_qs = TaskBundle.objects.filter(est_worksheet=self.ws)
        BundlingService.auto_dissolve_bundles(bundles_qs, Task)
        self.assertTrue(TaskBundle.objects.filter(pk=bundle.pk).exists())

    def test_exclude_pk(self):
        """Excluded bundle is not dissolved even if empty."""
        bundle = TaskBundle.objects.create(
            est_worksheet=self.ws, name='Protected',
            line_item_type=self.lit, sort_order=1,
        )
        bundles_qs = TaskBundle.objects.filter(est_worksheet=self.ws)
        BundlingService.auto_dissolve_bundles(
            bundles_qs, Task, exclude_pk=bundle.pk,
        )
        self.assertTrue(TaskBundle.objects.filter(pk=bundle.pk).exists())


class BundlingServiceReorderContainerTest(BundlingTestBase):
    """Tests for BundlingService.reorder_container_items."""

    def setUp(self):
        super().setUp()
        from apps.estimates.models import EstWorksheet
        self.ws = EstWorksheet.objects.create(job=self.job, status='draft')
        self.t1 = Task.objects.create(
            est_worksheet=self.ws, name='Task 1', sort_order=1,
        )
        self.bundle = TaskBundle.objects.create(
            est_worksheet=self.ws, name='Bundle',
            line_item_type=self.lit, sort_order=2,
        )
        self.bt1 = Task.objects.create(
            est_worksheet=self.ws, name='BT1', sort_order=1,
            mapping_strategy='bundle', bundle=self.bundle,
        )
        self.t2 = Task.objects.create(
            est_worksheet=self.ws, name='Task 2', sort_order=3,
        )

    def test_move_task_down(self):
        """Move unbundled task down past a bundle."""
        items_qs = Task.objects.filter(est_worksheet=self.ws)
        bundles_qs = TaskBundle.objects.filter(est_worksheet=self.ws)
        BundlingService.reorder_container_items(
            items_qs, bundles_qs, 'task', self.t1.pk, 'down',
        )
        self.t1.refresh_from_db()
        self.bundle.refresh_from_db()
        self.assertEqual(self.t1.sort_order, 2)
        self.assertEqual(self.bundle.sort_order, 1)

    def test_move_bundle_down(self):
        """Move a bundle down past an unbundled task."""
        items_qs = Task.objects.filter(est_worksheet=self.ws)
        bundles_qs = TaskBundle.objects.filter(est_worksheet=self.ws)
        BundlingService.reorder_container_items(
            items_qs, bundles_qs, 'bundle', self.bundle.pk, 'down',
        )
        self.bundle.refresh_from_db()
        self.t2.refresh_from_db()
        self.assertEqual(self.bundle.sort_order, 3)
        self.assertEqual(self.t2.sort_order, 2)

    def test_cannot_move_past_boundary(self):
        """Moving beyond boundaries raises ValidationError."""
        items_qs = Task.objects.filter(est_worksheet=self.ws)
        bundles_qs = TaskBundle.objects.filter(est_worksheet=self.ws)
        with self.assertRaises(ValidationError):
            BundlingService.reorder_container_items(
                items_qs, bundles_qs, 'task', self.t1.pk, 'up',
            )


class BundlingServiceReorderInBundleTest(BundlingTestBase):
    """Tests for BundlingService.reorder_in_bundle."""

    def setUp(self):
        super().setUp()
        from apps.estimates.models import EstWorksheet
        self.ws = EstWorksheet.objects.create(job=self.job, status='draft')
        self.bundle = TaskBundle.objects.create(
            est_worksheet=self.ws, name='Bundle',
            line_item_type=self.lit, sort_order=1,
        )
        self.t1 = Task.objects.create(
            est_worksheet=self.ws, name='T1', sort_order=1,
            mapping_strategy='bundle', bundle=self.bundle,
        )
        self.t2 = Task.objects.create(
            est_worksheet=self.ws, name='T2', sort_order=2,
            mapping_strategy='bundle', bundle=self.bundle,
        )

    def test_reorder_down(self):
        """Move first item down within bundle."""
        bundle_items_qs = Task.objects.filter(bundle=self.bundle)
        BundlingService.reorder_in_bundle(bundle_items_qs, self.t1, 'down')
        self.t1.refresh_from_db()
        self.t2.refresh_from_db()
        self.assertEqual(self.t1.sort_order, 2)
        self.assertEqual(self.t2.sort_order, 1)

    def test_reorder_up(self):
        """Move second item up within bundle."""
        bundle_items_qs = Task.objects.filter(bundle=self.bundle)
        BundlingService.reorder_in_bundle(bundle_items_qs, self.t2, 'up')
        self.t1.refresh_from_db()
        self.t2.refresh_from_db()
        self.assertEqual(self.t2.sort_order, 1)
        self.assertEqual(self.t1.sort_order, 2)


# --- WorksheetService domain bundling tests ---

class WorksheetServiceBundleTest(BundlingTestBase):
    """Tests for WorksheetService.bundle_tasks."""

    def setUp(self):
        super().setUp()
        self.ws = WorksheetService.create_worksheet(self.job.pk)
        self.t1 = Task.objects.create(
            est_worksheet=self.ws, name='Task 1', sort_order=1,
        )
        self.t2 = Task.objects.create(
            est_worksheet=self.ws, name='Task 2', sort_order=2,
        )
        self.t3 = Task.objects.create(
            est_worksheet=self.ws, name='Task 3', sort_order=3,
        )

    def test_bundle_tasks(self):
        """Bundle tasks on a worksheet."""
        bundle = WorksheetService.bundle_tasks(
            self.ws.pk, [self.t1.pk, self.t2.pk],
            bundle_name='My Bundle', line_item_type=self.lit,
        )
        self.assertIsNotNone(bundle.pk)
        self.t1.refresh_from_db()
        self.t2.refresh_from_db()
        self.assertEqual(self.t1.mapping_strategy, 'bundle')
        self.assertEqual(self.t2.mapping_strategy, 'bundle')

    def test_bundle_requires_two_tasks(self):
        """Cannot bundle fewer than 2 tasks."""
        with self.assertRaises(ValidationError):
            WorksheetService.bundle_tasks(
                self.ws.pk, [self.t1.pk],
                bundle_name='Solo', line_item_type=self.lit,
            )

    def test_bundle_non_draft_raises(self):
        """Cannot bundle on a non-draft worksheet."""
        self.ws.status = 'final'
        self.ws.save()
        with self.assertRaises(ValidationError):
            WorksheetService.bundle_tasks(
                self.ws.pk, [self.t1.pk, self.t2.pk],
                bundle_name='X', line_item_type=self.lit,
            )


class WorksheetServiceUnbundleTest(BundlingTestBase):
    """Tests for WorksheetService.unbundle_task."""

    def setUp(self):
        super().setUp()
        self.ws = WorksheetService.create_worksheet(self.job.pk)
        self.bundle = TaskBundle.objects.create(
            est_worksheet=self.ws, name='Bundle',
            line_item_type=self.lit, sort_order=5,
        )
        self.t1 = Task.objects.create(
            est_worksheet=self.ws, name='T1', sort_order=1,
            mapping_strategy='bundle', bundle=self.bundle,
        )
        self.t2 = Task.objects.create(
            est_worksheet=self.ws, name='T2', sort_order=2,
            mapping_strategy='bundle', bundle=self.bundle,
        )
        self.t3 = Task.objects.create(
            est_worksheet=self.ws, name='T3', sort_order=3,
            mapping_strategy='bundle', bundle=self.bundle,
        )

    def test_unbundle_task(self):
        """Unbundle a task from a worksheet bundle."""
        WorksheetService.unbundle_task(self.ws.pk, self.t1.pk)
        self.t1.refresh_from_db()
        self.assertEqual(self.t1.mapping_strategy, 'direct')
        self.assertIsNone(self.t1.bundle)

    def test_unbundle_dissolves_single_remaining(self):
        """Unbundling until 1 remains auto-dissolves the bundle."""
        WorksheetService.unbundle_task(self.ws.pk, self.t1.pk)
        WorksheetService.unbundle_task(self.ws.pk, self.t2.pk)
        # Only t3 remains — bundle should be dissolved
        self.t3.refresh_from_db()
        self.assertEqual(self.t3.mapping_strategy, 'direct')
        self.assertIsNone(self.t3.bundle)
        self.assertFalse(TaskBundle.objects.filter(pk=self.bundle.pk).exists())


class WorksheetServiceReorderTest(BundlingTestBase):
    """Tests for WorksheetService reorder methods."""

    def setUp(self):
        super().setUp()
        self.ws = WorksheetService.create_worksheet(self.job.pk)
        self.t1 = Task.objects.create(
            est_worksheet=self.ws, name='Task 1', sort_order=1,
        )
        self.t2 = Task.objects.create(
            est_worksheet=self.ws, name='Task 2', sort_order=2,
        )

    def test_reorder_items(self):
        """Reorder tasks at container level."""
        WorksheetService.reorder_items(
            self.ws.pk, 'task', self.t1.pk, 'down',
        )
        self.t1.refresh_from_db()
        self.t2.refresh_from_db()
        self.assertEqual(self.t1.sort_order, 2)
        self.assertEqual(self.t2.sort_order, 1)

    def test_reorder_non_draft_raises(self):
        """Cannot reorder on non-draft worksheet."""
        self.ws.status = 'final'
        self.ws.save()
        with self.assertRaises(ValidationError):
            WorksheetService.reorder_items(
                self.ws.pk, 'task', self.t1.pk, 'down',
            )


# --- WorkOrderTemplateService domain bundling tests ---

class TemplateServiceBundleTest(BundlingTestBase):
    """Tests for WorkOrderTemplateService.bundle_associations."""

    def setUp(self):
        super().setUp()
        self.tmpl = WorkOrderTemplateService.create_template(
            template_name='Test Template',
        )
        self.tt1 = WorkOrderTemplateService.create_task_template(
            template_name='TT1', line_item_type=self.lit,
        )
        self.tt2 = WorkOrderTemplateService.create_task_template(
            template_name='TT2', line_item_type=self.lit,
        )
        self.a1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.tmpl, task_template=self.tt1, sort_order=1,
        )
        self.a2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.tmpl, task_template=self.tt2, sort_order=2,
        )

    def test_bundle_associations(self):
        """Bundle associations on a template."""
        bundle = WorkOrderTemplateService.bundle_associations(
            self.tmpl.pk, [self.a1.pk, self.a2.pk],
            bundle_name='My Bundle', line_item_type=self.lit,
        )
        self.assertIsNotNone(bundle.pk)
        self.a1.refresh_from_db()
        self.a2.refresh_from_db()
        self.assertEqual(self.a1.mapping_strategy, 'bundle')
        self.assertEqual(self.a2.mapping_strategy, 'bundle')
        self.assertEqual(self.a1.bundle, bundle)

    def test_bundle_requires_two(self):
        """Cannot bundle fewer than 2 associations."""
        with self.assertRaises(ValidationError):
            WorkOrderTemplateService.bundle_associations(
                self.tmpl.pk, [self.a1.pk],
                bundle_name='Solo', line_item_type=self.lit,
            )


class TemplateServiceUnbundleTest(BundlingTestBase):
    """Tests for WorkOrderTemplateService.unbundle_association."""

    def setUp(self):
        super().setUp()
        self.tmpl = WorkOrderTemplateService.create_template(
            template_name='Test Template',
        )
        self.tt1 = WorkOrderTemplateService.create_task_template(
            template_name='TT1', line_item_type=self.lit,
        )
        self.tt2 = WorkOrderTemplateService.create_task_template(
            template_name='TT2', line_item_type=self.lit,
        )
        self.tt3 = WorkOrderTemplateService.create_task_template(
            template_name='TT3', line_item_type=self.lit,
        )
        self.bundle = TemplateBundle.objects.create(
            work_order_template=self.tmpl, name='Bundle',
            line_item_type=self.lit, sort_order=5,
        )
        self.a1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.tmpl, task_template=self.tt1,
            sort_order=1, mapping_strategy='bundle', bundle=self.bundle,
        )
        self.a2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.tmpl, task_template=self.tt2,
            sort_order=2, mapping_strategy='bundle', bundle=self.bundle,
        )
        self.a3 = TemplateTaskAssociation.objects.create(
            work_order_template=self.tmpl, task_template=self.tt3,
            sort_order=3, mapping_strategy='bundle', bundle=self.bundle,
        )

    def test_unbundle_association(self):
        """Unbundle an association from a template bundle."""
        WorkOrderTemplateService.unbundle_association(self.tmpl.pk, self.a1.pk)
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.mapping_strategy, 'direct')
        self.assertIsNone(self.a1.bundle)

    def test_unbundle_dissolves_single_remaining(self):
        """Auto-dissolves bundle when only 1 association remains."""
        WorkOrderTemplateService.unbundle_association(self.tmpl.pk, self.a1.pk)
        WorkOrderTemplateService.unbundle_association(self.tmpl.pk, self.a2.pk)
        self.a3.refresh_from_db()
        self.assertEqual(self.a3.mapping_strategy, 'direct')
        self.assertFalse(TemplateBundle.objects.filter(pk=self.bundle.pk).exists())


class TemplateServiceReorderTest(BundlingTestBase):
    """Tests for WorkOrderTemplateService reorder methods."""

    def setUp(self):
        super().setUp()
        self.tmpl = WorkOrderTemplateService.create_template(
            template_name='Test Template',
        )
        self.tt1 = WorkOrderTemplateService.create_task_template(
            template_name='TT1', line_item_type=self.lit,
        )
        self.tt2 = WorkOrderTemplateService.create_task_template(
            template_name='TT2', line_item_type=self.lit,
        )
        self.a1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.tmpl, task_template=self.tt1, sort_order=1,
        )
        self.a2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.tmpl, task_template=self.tt2, sort_order=2,
        )

    def test_reorder_items(self):
        """Reorder associations at container level."""
        WorkOrderTemplateService.reorder_items(
            self.tmpl.pk, 'task', self.a1.pk, 'down',
        )
        self.a1.refresh_from_db()
        self.a2.refresh_from_db()
        self.assertEqual(self.a1.sort_order, 2)
        self.assertEqual(self.a2.sort_order, 1)

    def test_reorder_in_bundle(self):
        """Reorder associations within a bundle."""
        bundle = TemplateBundle.objects.create(
            work_order_template=self.tmpl, name='B',
            line_item_type=self.lit, sort_order=10,
        )
        self.a1.mapping_strategy = 'bundle'
        self.a1.bundle = bundle
        self.a1.sort_order = 1
        self.a1.save()
        self.a2.mapping_strategy = 'bundle'
        self.a2.bundle = bundle
        self.a2.sort_order = 2
        self.a2.save()

        WorkOrderTemplateService.reorder_in_bundle(
            self.tmpl.pk, self.a1.pk, 'down',
        )
        self.a1.refresh_from_db()
        self.a2.refresh_from_db()
        self.assertEqual(self.a1.sort_order, 2)
        self.assertEqual(self.a2.sort_order, 1)
