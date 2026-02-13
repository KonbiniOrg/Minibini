"""
Tests for WorkOrderTemplate bundling and ordering functionality.

Covers:
A. Remove/Unbundle behavior
B. Bundle creation and sort_order assignment
C. Container-level reordering (bundles + unbundled tasks share sort_order space)
D. Within-bundle reordering
E. Shared sort_order helper (tested indirectly)
F. Edge cases (cross-template isolation)
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from apps.jobs.models import (
    WorkOrderTemplate, TaskTemplate, TemplateTaskAssociation, TemplateBundle,
)
from apps.core.models import LineItemType

User = get_user_model()


class TemplateOrderingTestBase(TestCase):
    """Base class with shared setUp for template ordering tests."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

        self.lit, _ = LineItemType.objects.get_or_create(
            code="LBR", defaults={"name": "Labor"}
        )
        self.lit2, _ = LineItemType.objects.get_or_create(
            code="MAT", defaults={"name": "Material"}
        )

        self.wo_template = WorkOrderTemplate.objects.create(
            template_name="Test WO Template"
        )

        # Create task templates
        self.task1 = TaskTemplate.objects.create(
            template_name="Task 1", rate=50, line_item_type=self.lit
        )
        self.task2 = TaskTemplate.objects.create(
            template_name="Task 2", rate=75, line_item_type=self.lit
        )
        self.task3 = TaskTemplate.objects.create(
            template_name="Task 3", rate=100, line_item_type=self.lit
        )
        self.task4 = TaskTemplate.objects.create(
            template_name="Task 4", rate=60, line_item_type=self.lit
        )
        self.task5 = TaskTemplate.objects.create(
            template_name="Task 5", rate=80, line_item_type=self.lit
        )

    def _detail_url(self, template=None):
        t = template or self.wo_template
        return reverse(
            'jobs:work_order_template_detail',
            kwargs={'template_id': t.template_id},
        )

    def _container_reorder_url(self, item_type, item_id, direction, template=None):
        t = template or self.wo_template
        return reverse(
            'jobs:template_reorder_item',
            kwargs={
                'template_id': t.template_id,
                'item_type': item_type,
                'item_id': item_id,
                'direction': direction,
            },
        )

    def _bundle_reorder_url(self, association_id, direction, template=None):
        t = template or self.wo_template
        return reverse(
            'jobs:template_reorder_in_bundle',
            kwargs={
                'template_id': t.template_id,
                'association_id': association_id,
                'direction': direction,
            },
        )


# ---------------------------------------------------------------------------
# A. Remove / Unbundle
# ---------------------------------------------------------------------------

class RemoveUnbundleTests(TemplateOrderingTestBase):
    """Tests for removing tasks and unbundling behavior."""

    def test_remove_unbundled_task_deletes_association(self):
        """A1: Removing an unbundled (direct) task deletes the TemplateTaskAssociation."""
        assoc = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1,
            sort_order=1,
            mapping_strategy='direct',
        )
        assoc_pk = assoc.pk

        response = self.client.post(self._detail_url(), {
            'remove_task': self.task1.template_id,
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            TemplateTaskAssociation.objects.filter(pk=assoc_pk).exists()
        )

    def test_remove_bundled_task_unbundles_it(self):
        """A2: Removing a bundled task unbundles it (mapping_strategy='direct', bundle=None)."""
        bundle = TemplateBundle.objects.create(
            work_order_template=self.wo_template,
            name="Bundle A",
            line_item_type=self.lit,
            sort_order=1,
        )
        assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
            mapping_strategy='bundle', bundle=bundle,
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2,
            mapping_strategy='bundle', bundle=bundle,
        )
        assoc3 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task3,
            est_qty=1, sort_order=3,
            mapping_strategy='bundle', bundle=bundle,
        )

        # Remove task1 from the 3-task bundle
        self.client.post(self._detail_url(), {
            'remove_task': self.task1.template_id,
        })

        assoc1.refresh_from_db()
        self.assertEqual(assoc1.mapping_strategy, 'direct')
        self.assertIsNone(assoc1.bundle)

    def test_unbundle_then_remove_deletes_association(self):
        """A3: After unbundling, a second remove deletes the association."""
        bundle = TemplateBundle.objects.create(
            work_order_template=self.wo_template,
            name="Bundle A",
            line_item_type=self.lit,
            sort_order=1,
        )
        assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
            mapping_strategy='bundle', bundle=bundle,
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2,
            mapping_strategy='bundle', bundle=bundle,
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task3,
            est_qty=1, sort_order=3,
            mapping_strategy='bundle', bundle=bundle,
        )

        # First remove: unbundles
        self.client.post(self._detail_url(), {
            'remove_task': self.task1.template_id,
        })
        assoc1.refresh_from_db()
        self.assertEqual(assoc1.mapping_strategy, 'direct')

        # Second remove: deletes
        self.client.post(self._detail_url(), {
            'remove_task': self.task1.template_id,
        })
        self.assertFalse(
            TemplateTaskAssociation.objects.filter(pk=assoc1.pk).exists()
        )

    def test_unbundle_from_two_task_bundle_dissolves_bundle(self):
        """A4: Unbundling from a 2-task bundle auto-dissolves the bundle."""
        bundle = TemplateBundle.objects.create(
            work_order_template=self.wo_template,
            name="Bundle A",
            line_item_type=self.lit,
            sort_order=1,
        )
        bundle_pk = bundle.pk

        assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
            mapping_strategy='bundle', bundle=bundle,
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2,
            mapping_strategy='bundle', bundle=bundle,
        )

        self.client.post(self._detail_url(), {
            'remove_task': self.task1.template_id,
        })

        # Both should now be direct
        assoc1.refresh_from_db()
        assoc2.refresh_from_db()
        self.assertEqual(assoc1.mapping_strategy, 'direct')
        self.assertIsNone(assoc1.bundle)
        self.assertEqual(assoc2.mapping_strategy, 'direct')
        self.assertIsNone(assoc2.bundle)

        # Bundle should be deleted
        self.assertFalse(
            TemplateBundle.objects.filter(pk=bundle_pk).exists()
        )

    def test_unbundle_from_three_task_bundle_keeps_bundle(self):
        """A5: Unbundling from a 3-task bundle keeps the bundle (2 remain)."""
        bundle = TemplateBundle.objects.create(
            work_order_template=self.wo_template,
            name="Bundle A",
            line_item_type=self.lit,
            sort_order=1,
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
            mapping_strategy='bundle', bundle=bundle,
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2,
            mapping_strategy='bundle', bundle=bundle,
        )
        assoc3 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task3,
            est_qty=1, sort_order=3,
            mapping_strategy='bundle', bundle=bundle,
        )

        self.client.post(self._detail_url(), {
            'remove_task': self.task1.template_id,
        })

        # Bundle still exists with 2 members
        self.assertTrue(TemplateBundle.objects.filter(pk=bundle.pk).exists())
        assoc2.refresh_from_db()
        assoc3.refresh_from_db()
        self.assertEqual(assoc2.mapping_strategy, 'bundle')
        self.assertEqual(assoc2.bundle_id, bundle.pk)
        self.assertEqual(assoc3.mapping_strategy, 'bundle')
        self.assertEqual(assoc3.bundle_id, bundle.pk)


# ---------------------------------------------------------------------------
# B. Bundle Creation
# ---------------------------------------------------------------------------

class BundleCreationTests(TemplateOrderingTestBase):
    """Tests for bundle creation via the bundle_tasks POST action."""

    def test_bundling_assigns_sequential_sort_order(self):
        """B6: Bundling assigns sequential sort_order within the bundle (1, 2, ...)."""
        assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2,
        )
        assoc3 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task3,
            est_qty=1, sort_order=3,
        )

        self.client.post(self._detail_url(), {
            'bundle_tasks': 'true',
            'selected_tasks': [assoc1.pk, assoc2.pk, assoc3.pk],
            'bundle_name': 'My Bundle',
            'bundle_description': '',
            'line_item_type': self.lit.pk,
        })

        assoc1.refresh_from_db()
        assoc2.refresh_from_db()
        assoc3.refresh_from_db()

        self.assertEqual(assoc1.sort_order, 1)
        self.assertEqual(assoc2.sort_order, 2)
        self.assertEqual(assoc3.sort_order, 3)
        self.assertEqual(assoc1.mapping_strategy, 'bundle')
        self.assertEqual(assoc2.mapping_strategy, 'bundle')
        self.assertEqual(assoc3.mapping_strategy, 'bundle')

    def test_bundle_sort_order_uses_shared_container_space(self):
        """B7: Bundle sort_order uses the shared container-level space (max of unbundled + bundles + 1)."""
        # Create an existing unbundled association with sort_order=5
        TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task3,
            est_qty=1, sort_order=5,
            mapping_strategy='direct',
        )

        assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2,
        )

        self.client.post(self._detail_url(), {
            'bundle_tasks': 'true',
            'selected_tasks': [assoc1.pk, assoc2.pk],
            'bundle_name': 'Late Bundle',
            'bundle_description': '',
            'line_item_type': self.lit.pk,
        })

        bundle = TemplateBundle.objects.get(
            work_order_template=self.wo_template, name='Late Bundle'
        )
        # The next container sort_order should be max(5, 0) + 1 = 6
        self.assertEqual(bundle.sort_order, 6)

    def test_same_bundle_name_adds_to_existing_bundle(self):
        """B8: Using the same bundle name adds tasks to existing bundle via get_or_create."""
        assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2,
        )
        assoc3 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task3,
            est_qty=1, sort_order=3,
        )
        assoc4 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task4,
            est_qty=1, sort_order=4,
        )

        # First bundle: tasks 1 and 2
        self.client.post(self._detail_url(), {
            'bundle_tasks': 'true',
            'selected_tasks': [assoc1.pk, assoc2.pk],
            'bundle_name': 'Shared Bundle',
            'bundle_description': '',
            'line_item_type': self.lit.pk,
        })

        self.assertEqual(
            TemplateBundle.objects.filter(
                work_order_template=self.wo_template, name='Shared Bundle'
            ).count(),
            1,
        )

        # Second bundle action with same name: add tasks 3 and 4
        self.client.post(self._detail_url(), {
            'bundle_tasks': 'true',
            'selected_tasks': [assoc3.pk, assoc4.pk],
            'bundle_name': 'Shared Bundle',
            'bundle_description': '',
            'line_item_type': self.lit.pk,
        })

        # Still only one bundle
        self.assertEqual(
            TemplateBundle.objects.filter(
                work_order_template=self.wo_template, name='Shared Bundle'
            ).count(),
            1,
        )

        bundle = TemplateBundle.objects.get(
            work_order_template=self.wo_template, name='Shared Bundle'
        )
        # All four should be in the bundle
        self.assertEqual(
            TemplateTaskAssociation.objects.filter(bundle=bundle).count(), 4
        )

    def test_moving_all_tasks_to_new_bundle_deletes_old_bundle(self):
        """B9: Moving all tasks from Bundle A to Bundle B deletes Bundle A."""
        bundle_a = TemplateBundle.objects.create(
            work_order_template=self.wo_template,
            name="Bundle A",
            line_item_type=self.lit,
            sort_order=1,
        )
        bundle_a_pk = bundle_a.pk

        assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
            mapping_strategy='bundle', bundle=bundle_a,
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2,
            mapping_strategy='bundle', bundle=bundle_a,
        )

        # Move both tasks to Bundle B
        self.client.post(self._detail_url(), {
            'bundle_tasks': 'true',
            'selected_tasks': [assoc1.pk, assoc2.pk],
            'bundle_name': 'Bundle B',
            'bundle_description': '',
            'line_item_type': self.lit2.pk,
        })

        # Bundle A should be gone (0 tasks remaining)
        self.assertFalse(
            TemplateBundle.objects.filter(pk=bundle_a_pk).exists()
        )

        # Bundle B should exist with both tasks
        bundle_b = TemplateBundle.objects.get(
            work_order_template=self.wo_template, name='Bundle B'
        )
        self.assertEqual(
            TemplateTaskAssociation.objects.filter(bundle=bundle_b).count(), 2
        )

    def test_moving_two_of_three_auto_unbundles_last_and_deletes_old_bundle(self):
        """B10: Moving 2 of 3 tasks from Bundle A to Bundle B auto-unbundles the last and deletes A."""
        bundle_a = TemplateBundle.objects.create(
            work_order_template=self.wo_template,
            name="Bundle A",
            line_item_type=self.lit,
            sort_order=1,
        )
        bundle_a_pk = bundle_a.pk

        assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
            mapping_strategy='bundle', bundle=bundle_a,
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2,
            mapping_strategy='bundle', bundle=bundle_a,
        )
        assoc3 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task3,
            est_qty=1, sort_order=3,
            mapping_strategy='bundle', bundle=bundle_a,
        )

        # Move tasks 1 and 2 to Bundle B
        self.client.post(self._detail_url(), {
            'bundle_tasks': 'true',
            'selected_tasks': [assoc1.pk, assoc2.pk],
            'bundle_name': 'Bundle B',
            'bundle_description': '',
            'line_item_type': self.lit2.pk,
        })

        # Bundle A is deleted (auto-unbundle because only 1 task remained)
        self.assertFalse(
            TemplateBundle.objects.filter(pk=bundle_a_pk).exists()
        )

        # Task 3 is now direct with no bundle
        assoc3.refresh_from_db()
        self.assertEqual(assoc3.mapping_strategy, 'direct')
        self.assertIsNone(assoc3.bundle)

        # Tasks 1 and 2 are in Bundle B
        bundle_b = TemplateBundle.objects.get(
            work_order_template=self.wo_template, name='Bundle B'
        )
        assoc1.refresh_from_db()
        assoc2.refresh_from_db()
        self.assertEqual(assoc1.bundle, bundle_b)
        self.assertEqual(assoc2.bundle, bundle_b)


# ---------------------------------------------------------------------------
# C. Container-Level Reorder
# ---------------------------------------------------------------------------

class ContainerReorderTests(TemplateOrderingTestBase):
    """Tests for reordering at the container level (bundles + unbundled tasks)."""

    def test_reorder_unbundled_task_down(self):
        """C11: Reorder unbundled task down swaps sort_orders."""
        assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1, mapping_strategy='direct',
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2, mapping_strategy='direct',
        )

        url = self._container_reorder_url('task', assoc1.pk, 'down')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        assoc1.refresh_from_db()
        assoc2.refresh_from_db()
        self.assertEqual(assoc1.sort_order, 2)
        self.assertEqual(assoc2.sort_order, 1)

    def test_reorder_bundle_up_swaps_with_unbundled_task(self):
        """C12: Reorder bundle up swaps sort_orders with adjacent unbundled task."""
        assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1, mapping_strategy='direct',
        )
        bundle = TemplateBundle.objects.create(
            work_order_template=self.wo_template,
            name="Bundle A",
            line_item_type=self.lit,
            sort_order=2,
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=1,
            mapping_strategy='bundle', bundle=bundle,
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task3,
            est_qty=1, sort_order=2,
            mapping_strategy='bundle', bundle=bundle,
        )

        url = self._container_reorder_url('bundle', bundle.pk, 'up')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        bundle.refresh_from_db()
        assoc1.refresh_from_db()
        self.assertEqual(bundle.sort_order, 1)
        self.assertEqual(assoc1.sort_order, 2)

    def test_reorder_first_item_up_does_nothing(self):
        """C13: Reorder first item up does nothing (still redirects)."""
        assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1, mapping_strategy='direct',
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2, mapping_strategy='direct',
        )

        url = self._container_reorder_url('task', assoc1.pk, 'up')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        assoc1.refresh_from_db()
        assoc2.refresh_from_db()
        self.assertEqual(assoc1.sort_order, 1)
        self.assertEqual(assoc2.sort_order, 2)

    def test_reorder_last_item_down_does_nothing(self):
        """C14: Reorder last item down does nothing (still redirects)."""
        assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1, mapping_strategy='direct',
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2, mapping_strategy='direct',
        )

        url = self._container_reorder_url('task', assoc2.pk, 'down')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        assoc1.refresh_from_db()
        assoc2.refresh_from_db()
        self.assertEqual(assoc1.sort_order, 1)
        self.assertEqual(assoc2.sort_order, 2)

    def test_reorder_requires_post(self):
        """C15: Reorder requires POST (GET returns 405)."""
        assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1, mapping_strategy='direct',
        )

        url = self._container_reorder_url('task', assoc1.pk, 'down')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)


# ---------------------------------------------------------------------------
# D. Within-Bundle Reorder
# ---------------------------------------------------------------------------

class WithinBundleReorderTests(TemplateOrderingTestBase):
    """Tests for reordering tasks within a bundle."""

    def setUp(self):
        super().setUp()
        self.bundle = TemplateBundle.objects.create(
            work_order_template=self.wo_template,
            name="Bundle A",
            line_item_type=self.lit,
            sort_order=1,
        )
        self.assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
            mapping_strategy='bundle', bundle=self.bundle,
        )
        self.assoc2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2,
            mapping_strategy='bundle', bundle=self.bundle,
        )
        self.assoc3 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task3,
            est_qty=1, sort_order=3,
            mapping_strategy='bundle', bundle=self.bundle,
        )

    def test_reorder_task_down_in_bundle(self):
        """D16: Reorder task down within bundle swaps sort_orders."""
        url = self._bundle_reorder_url(self.assoc1.pk, 'down')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        self.assoc1.refresh_from_db()
        self.assoc2.refresh_from_db()
        self.assertEqual(self.assoc1.sort_order, 2)
        self.assertEqual(self.assoc2.sort_order, 1)

    def test_reorder_task_up_in_bundle(self):
        """D17: Reorder task up within bundle swaps sort_orders."""
        url = self._bundle_reorder_url(self.assoc3.pk, 'up')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        self.assoc2.refresh_from_db()
        self.assoc3.refresh_from_db()
        self.assertEqual(self.assoc3.sort_order, 2)
        self.assertEqual(self.assoc2.sort_order, 3)

    def test_reorder_first_task_up_in_bundle_does_nothing(self):
        """D18: Reorder first task up in bundle does nothing."""
        url = self._bundle_reorder_url(self.assoc1.pk, 'up')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        self.assoc1.refresh_from_db()
        self.assoc2.refresh_from_db()
        self.assoc3.refresh_from_db()
        self.assertEqual(self.assoc1.sort_order, 1)
        self.assertEqual(self.assoc2.sort_order, 2)
        self.assertEqual(self.assoc3.sort_order, 3)

    def test_reorder_last_task_down_in_bundle_does_nothing(self):
        """D19: Reorder last task down in bundle does nothing."""
        url = self._bundle_reorder_url(self.assoc3.pk, 'down')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        self.assoc1.refresh_from_db()
        self.assoc2.refresh_from_db()
        self.assoc3.refresh_from_db()
        self.assertEqual(self.assoc1.sort_order, 1)
        self.assertEqual(self.assoc2.sort_order, 2)
        self.assertEqual(self.assoc3.sort_order, 3)

    def test_reorder_non_bundled_association_returns_404(self):
        """D20: Reorder with a non-bundled association returns 404."""
        direct_assoc = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task4,
            est_qty=1, sort_order=10,
            mapping_strategy='direct',
        )

        url = self._bundle_reorder_url(direct_assoc.pk, 'down')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# E. Shared sort_order helper (tested indirectly)
# ---------------------------------------------------------------------------

class SortOrderHelperTests(TemplateOrderingTestBase):
    """Tests for _next_container_sort_order via the associate_task action."""

    def test_new_association_gets_sort_order_after_existing(self):
        """E21: New task association gets sort_order after existing bundles and unbundled tasks."""
        # Create an unbundled association at sort_order=3
        TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=3,
            mapping_strategy='direct',
        )

        # Create a bundle at sort_order=5
        bundle = TemplateBundle.objects.create(
            work_order_template=self.wo_template,
            name="Bundle A",
            line_item_type=self.lit,
            sort_order=5,
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=1,
            mapping_strategy='bundle', bundle=bundle,
        )

        # Associate a new task via POST (the associate_task action)
        self.client.post(self._detail_url(), {
            'associate_task': 'true',
            'task_template_id': self.task3.template_id,
            'est_qty': '1.00',
        })

        new_assoc = TemplateTaskAssociation.objects.get(
            work_order_template=self.wo_template,
            task_template=self.task3,
        )
        # Max of unbundled (3) and bundle (5) is 5, so next = 6
        self.assertEqual(new_assoc.sort_order, 6)


# ---------------------------------------------------------------------------
# F. Edge Cases
# ---------------------------------------------------------------------------

class EdgeCaseTests(TemplateOrderingTestBase):
    """Edge case tests for template ordering."""

    def test_same_bundle_name_different_templates_no_cross_contamination(self):
        """F22: Same bundle name on different WorkOrderTemplates doesn't cross-contaminate."""
        wo_template_2 = WorkOrderTemplate.objects.create(
            template_name="Second WO Template"
        )
        task_a = TaskTemplate.objects.create(
            template_name="Task A", rate=10, line_item_type=self.lit
        )
        task_b = TaskTemplate.objects.create(
            template_name="Task B", rate=20, line_item_type=self.lit
        )

        # Create associations on template 1
        assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2,
        )

        # Create associations on template 2
        assoc_a = TemplateTaskAssociation.objects.create(
            work_order_template=wo_template_2,
            task_template=task_a,
            est_qty=1, sort_order=1,
        )
        assoc_b = TemplateTaskAssociation.objects.create(
            work_order_template=wo_template_2,
            task_template=task_b,
            est_qty=1, sort_order=2,
        )

        # Bundle on template 1 with name "Prep"
        self.client.post(self._detail_url(self.wo_template), {
            'bundle_tasks': 'true',
            'selected_tasks': [assoc1.pk, assoc2.pk],
            'bundle_name': 'Prep',
            'bundle_description': '',
            'line_item_type': self.lit.pk,
        })

        # Bundle on template 2 with the same name "Prep"
        self.client.post(self._detail_url(wo_template_2), {
            'bundle_tasks': 'true',
            'selected_tasks': [assoc_a.pk, assoc_b.pk],
            'bundle_name': 'Prep',
            'bundle_description': '',
            'line_item_type': self.lit.pk,
        })

        # Two separate bundles should exist
        bundle_1 = TemplateBundle.objects.get(
            work_order_template=self.wo_template, name='Prep'
        )
        bundle_2 = TemplateBundle.objects.get(
            work_order_template=wo_template_2, name='Prep'
        )
        self.assertNotEqual(bundle_1.pk, bundle_2.pk)

        # Template 1 bundle has task1 and task2
        self.assertEqual(
            set(
                TemplateTaskAssociation.objects.filter(bundle=bundle_1)
                .values_list('task_template_id', flat=True)
            ),
            {self.task1.template_id, self.task2.template_id},
        )

        # Template 2 bundle has task_a and task_b
        self.assertEqual(
            set(
                TemplateTaskAssociation.objects.filter(bundle=bundle_2)
                .values_list('task_template_id', flat=True)
            ),
            {task_a.template_id, task_b.template_id},
        )
