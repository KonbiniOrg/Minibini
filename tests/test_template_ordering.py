"""
Tests for WorkTemplate task association ordering functionality.

Covers:
A. Remove association behavior
C. Container-level reordering
E. Sort order helper (tested indirectly)
F. Edge cases (cross-template isolation)
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from decimal import Decimal

from apps.estimates.models import WorkTemplate, TaskTemplate, TemplateTaskAssociation
from apps.core.models import AccountingCategory
from apps.jobs.models import RateScheme

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

        self.lit, _ = AccountingCategory.objects.get_or_create(
            code="LBR", defaults={"name": "Labor"}
        )
        self.lit2, _ = AccountingCategory.objects.get_or_create(
            code="MAT", defaults={"name": "Material"}
        )
        self.scheme = RateScheme.objects.create(
            name='S-to', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1'), unit_label='ea', accounting_category=self.lit,
        )

        self.wo_template = WorkTemplate.objects.create(
            template_name="Test WO Template"
        )

        # Create task templates
        self.task1 = TaskTemplate.objects.create(
            template_name="Task 1",
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'),
        )
        self.task2 = TaskTemplate.objects.create(
            template_name="Task 2",
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'),
        )
        self.task3 = TaskTemplate.objects.create(
            template_name="Task 3",
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'),
        )
        self.task4 = TaskTemplate.objects.create(
            template_name="Task 4",
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'),
        )
        self.task5 = TaskTemplate.objects.create(
            template_name="Task 5",
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'),
        )

    def _detail_url(self, template=None):
        t = template or self.wo_template
        return reverse(
            'estimates:work_template_detail',
            kwargs={'template_id': t.template_id},
        )

    def _container_reorder_url(self, item_type, item_id, direction, template=None):
        t = template or self.wo_template
        return reverse(
            'estimates:template_reorder_item',
            kwargs={
                'template_id': t.template_id,
                'item_type': item_type,
                'item_id': item_id,
                'direction': direction,
            },
        )


# ---------------------------------------------------------------------------
# A. Remove association
# ---------------------------------------------------------------------------

class RemoveAssociationTests(TemplateOrderingTestBase):
    """Tests for removing task associations."""

    def test_remove_task_deletes_association(self):
        """A1: Removing a task deletes the TemplateTaskAssociation."""
        assoc = TemplateTaskAssociation.objects.create(
            work_template=self.wo_template,
            task_template=self.task1,
            est_qty=1,
            sort_order=1,
        )
        assoc_pk = assoc.pk

        response = self.client.post(self._detail_url(), {
            'remove_task': self.task1.template_id,
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            TemplateTaskAssociation.objects.filter(pk=assoc_pk).exists()
        )

    def test_remove_nonexistent_task_does_nothing(self):
        """A2: Removing a task not in the template does nothing."""
        assoc = TemplateTaskAssociation.objects.create(
            work_template=self.wo_template,
            task_template=self.task1,
            est_qty=1,
            sort_order=1,
        )

        response = self.client.post(self._detail_url(), {
            'remove_task': self.task2.template_id,
        })
        self.assertEqual(response.status_code, 302)
        # assoc for task1 still exists
        self.assertTrue(TemplateTaskAssociation.objects.filter(pk=assoc.pk).exists())


# ---------------------------------------------------------------------------
# C. Container-Level Reorder
# ---------------------------------------------------------------------------

class ContainerReorderTests(TemplateOrderingTestBase):
    """Tests for reordering at the container level."""

    def test_reorder_task_down(self):
        """C11: Reorder task down swaps sort_orders."""
        assoc1 = TemplateTaskAssociation.objects.create(
            work_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2,
        )

        url = self._container_reorder_url('task', assoc1.pk, 'down')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        assoc1.refresh_from_db()
        assoc2.refresh_from_db()
        self.assertEqual(assoc1.sort_order, 2)
        self.assertEqual(assoc2.sort_order, 1)

    def test_reorder_first_item_up_does_nothing(self):
        """C13: Reorder first item up does nothing (still redirects)."""
        assoc1 = TemplateTaskAssociation.objects.create(
            work_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2,
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
            work_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2,
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
            work_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
        )

        url = self._container_reorder_url('task', assoc1.pk, 'down')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)


# ---------------------------------------------------------------------------
# E. Sort order helper (tested indirectly)
# ---------------------------------------------------------------------------

class SortOrderHelperTests(TemplateOrderingTestBase):
    """Tests for _next_container_sort_order via the associate_task action."""

    def test_new_association_gets_sort_order_after_existing(self):
        """E21: New task association gets sort_order after existing associations."""
        TemplateTaskAssociation.objects.create(
            work_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=3,
        )
        TemplateTaskAssociation.objects.create(
            work_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=5,
        )

        # Associate a new task via POST (the associate_task action)
        self.client.post(self._detail_url(), {
            'associate_task': 'true',
            'task_template_id': self.task3.template_id,
            'est_qty': '1.00',
        })

        new_assoc = TemplateTaskAssociation.objects.get(
            work_template=self.wo_template,
            task_template=self.task3,
        )
        # Max sort_order is 5, so next = 6
        self.assertEqual(new_assoc.sort_order, 6)


# ---------------------------------------------------------------------------
# F. Edge Cases
# ---------------------------------------------------------------------------

class EdgeCaseTests(TemplateOrderingTestBase):
    """Edge case tests for template ordering."""

    def test_different_templates_no_cross_contamination(self):
        """F22: Reordering on one template doesn't affect another."""
        wo_template_2 = WorkTemplate.objects.create(
            template_name="Second WO Template"
        )
        task_a = TaskTemplate.objects.create(
            template_name="Task A",
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'),
        )
        task_b = TaskTemplate.objects.create(
            template_name="Task B",
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'),
        )

        # Create associations on template 1
        assoc1 = TemplateTaskAssociation.objects.create(
            work_template=self.wo_template,
            task_template=self.task1,
            est_qty=1, sort_order=1,
        )
        assoc2 = TemplateTaskAssociation.objects.create(
            work_template=self.wo_template,
            task_template=self.task2,
            est_qty=1, sort_order=2,
        )

        # Create associations on template 2
        assoc_a = TemplateTaskAssociation.objects.create(
            work_template=wo_template_2,
            task_template=task_a,
            est_qty=1, sort_order=1,
        )
        assoc_b = TemplateTaskAssociation.objects.create(
            work_template=wo_template_2,
            task_template=task_b,
            est_qty=1, sort_order=2,
        )

        # Reorder on template 1
        url = self._container_reorder_url('task', assoc1.pk, 'down')
        self.client.post(url)

        assoc1.refresh_from_db()
        assoc2.refresh_from_db()
        assoc_a.refresh_from_db()
        assoc_b.refresh_from_db()

        # Template 1 changed
        self.assertEqual(assoc1.sort_order, 2)
        self.assertEqual(assoc2.sort_order, 1)

        # Template 2 unchanged
        self.assertEqual(assoc_a.sort_order, 1)
        self.assertEqual(assoc_b.sort_order, 2)
