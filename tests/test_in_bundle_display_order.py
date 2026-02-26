"""Tests that within-bundle items are displayed in sort_order, not by ID."""
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import (
    Task, TaskBundle, EstWorksheet, Job,
    WorkOrderTemplate, TaskTemplate, TemplateTaskAssociation, TemplateBundle,
)
from apps.contacts.models import Contact
from apps.core.models import LineItemType


class WithinBundleDisplayOrderTest(TestCase):
    """Items within a bundle should be displayed sorted by sort_order, not ID."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test', last_name='User')
        self.job = Job.objects.create(job_number='J001', contact=self.contact)
        self.lit, _ = LineItemType.objects.get_or_create(
            code='LBR', defaults={'name': 'Labor'}
        )

    def test_worksheet_bundle_items_sorted_by_sort_order(self):
        """_build_container_items_from_tasks should sort within-bundle items by sort_order."""
        from apps.jobs.views import _build_container_items_from_tasks

        worksheet = EstWorksheet.objects.create(job=self.job)
        bundle = TaskBundle.objects.create(
            est_worksheet=worksheet, name='Bundle',
            line_item_type=self.lit, sort_order=1
        )
        # Create tasks with sort_order opposite to ID order
        t1 = Task.objects.create(
            est_worksheet=worksheet, name='First by ID, Last by sort',
            rate=10, mapping_strategy='bundle', bundle=bundle, sort_order=3
        )
        t2 = Task.objects.create(
            est_worksheet=worksheet, name='Second by ID, First by sort',
            rate=20, mapping_strategy='bundle', bundle=bundle, sort_order=1
        )
        t3 = Task.objects.create(
            est_worksheet=worksheet, name='Third by ID, Middle by sort',
            rate=30, mapping_strategy='bundle', bundle=bundle, sort_order=2
        )

        container_items = _build_container_items_from_tasks(worksheet)
        self.assertEqual(len(container_items), 1)
        item_type, bundle_data, _ = container_items[0]
        self.assertEqual(item_type, 'bundle')

        names = [item['name'] for item in bundle_data['items']]
        self.assertEqual(names, [
            'Second by ID, First by sort',
            'Third by ID, Middle by sort',
            'First by ID, Last by sort',
        ])

    def test_template_bundle_items_sorted_by_sort_order(self):
        """_build_container_items_from_associations should sort within-bundle items by sort_order."""
        from apps.jobs.views import _build_container_items_from_associations

        wot = WorkOrderTemplate.objects.create(template_name='Test')
        template_bundle = TemplateBundle.objects.create(
            work_order_template=wot, name='Bundle',
            line_item_type=self.lit, sort_order=1
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
        # Create associations with sort_order opposite to PK order
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt1,
            est_qty=1, mapping_strategy='bundle', bundle=template_bundle,
            sort_order=3
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt2,
            est_qty=1, mapping_strategy='bundle', bundle=template_bundle,
            sort_order=1
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt3,
            est_qty=1, mapping_strategy='bundle', bundle=template_bundle,
            sort_order=2
        )

        associations = TemplateTaskAssociation.objects.filter(
            work_order_template=wot
        ).select_related('task_template', 'bundle')
        container_items = _build_container_items_from_associations(associations)

        self.assertEqual(len(container_items), 1)
        item_type, bundle_data, _ = container_items[0]
        self.assertEqual(item_type, 'bundle')

        names = [item['name'] for item in bundle_data['items']]
        self.assertEqual(names, ['Beta', 'Gamma', 'Alpha'])
