"""Tests for TaskMapping CRUD views."""

from django.test import TestCase, Client
from django.urls import reverse
from apps.jobs.models import TaskMapping, TaskTemplate
from apps.core.models import LineItemType


class TestTaskMappingCreateView(TestCase):
    """Tests for TaskMapping create view."""

    def setUp(self):
        self.client = Client()
        self.service_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )

    def test_create_view_renders_form(self):
        """GET task_mapping_create shows the form."""
        response = self.client.get(reverse('jobs:task_mapping_create'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Task Mapping')
        self.assertContains(response, 'mapping_strategy')

    def test_create_view_saves_mapping(self):
        """POST with valid data creates a TaskMapping."""
        data = {
            'task_type_id': 'TEST-MAPPING',
            'step_type': 'labor',
            'mapping_strategy': 'direct',
            'default_product_type': '',
            'line_item_name': 'Test Service',
            'line_item_description': 'A test service',
            'output_line_item_type': self.service_type.pk,
            'breakdown_of_task': '',
        }
        response = self.client.post(reverse('jobs:task_mapping_create'), data)
        self.assertEqual(response.status_code, 302)  # Redirect on success
        self.assertTrue(TaskMapping.objects.filter(task_type_id='TEST-MAPPING').exists())

    def test_create_view_saves_mapping_without_line_item_type(self):
        """POST without line_item_type also works (field is optional)."""
        data = {
            'task_type_id': 'TEST-NO-TYPE',
            'step_type': 'overhead',
            'mapping_strategy': 'exclude',
            'default_product_type': '',
            'line_item_name': '',
            'line_item_description': '',
            'output_line_item_type': '',
            'breakdown_of_task': 'Internal task',
        }
        response = self.client.post(reverse('jobs:task_mapping_create'), data)
        self.assertEqual(response.status_code, 302)
        mapping = TaskMapping.objects.filter(task_type_id='TEST-NO-TYPE').first()
        self.assertIsNotNone(mapping)
        self.assertIsNone(mapping.output_line_item_type)


class TestTaskMappingDetailView(TestCase):
    """Tests for TaskMapping detail view."""

    def setUp(self):
        self.client = Client()
        self.service_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )
        self.mapping = TaskMapping.objects.create(
            task_type_id='DETAIL-TEST',
            step_type='labor',
            mapping_strategy='direct',
            line_item_name='Test Service',
            output_line_item_type=self.service_type
        )

    def test_detail_view_shows_mapping(self):
        """GET task_mapping_detail shows the mapping details."""
        response = self.client.get(
            reverse('jobs:task_mapping_detail', args=[self.mapping.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'DETAIL-TEST')
        self.assertContains(response, 'Test Service')
        self.assertContains(response, 'Service')  # LineItemType name

    def test_detail_view_shows_linked_templates(self):
        """Detail view shows TaskTemplates using this mapping."""
        # Create a TaskTemplate linked to this mapping
        template = TaskTemplate.objects.create(
            template_name='Linked Template',
            task_mapping=self.mapping,
            units='hours',
            rate='50.00'
        )

        response = self.client.get(
            reverse('jobs:task_mapping_detail', args=[self.mapping.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Linked Template')


class TestTaskMappingEditView(TestCase):
    """Tests for TaskMapping edit view."""

    def setUp(self):
        self.client = Client()
        self.service_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )
        self.mapping = TaskMapping.objects.create(
            task_type_id='EDIT-TEST',
            step_type='labor',
            mapping_strategy='direct',
            line_item_name='Original Name'
        )

    def test_edit_view_renders_form(self):
        """GET task_mapping_edit shows form with existing data."""
        response = self.client.get(
            reverse('jobs:task_mapping_edit', args=[self.mapping.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'EDIT-TEST')
        self.assertContains(response, 'Original Name')

    def test_edit_view_updates_mapping(self):
        """POST with valid data updates the TaskMapping."""
        data = {
            'task_type_id': 'EDIT-TEST',
            'step_type': 'material',
            'mapping_strategy': 'direct',
            'default_product_type': '',
            'line_item_name': 'Updated Name',
            'line_item_description': '',
            'breakdown_of_task': '',
        }
        response = self.client.post(
            reverse('jobs:task_mapping_edit', args=[self.mapping.pk]),
            data
        )
        self.assertEqual(response.status_code, 302)
        self.mapping.refresh_from_db()
        self.assertEqual(self.mapping.line_item_name, 'Updated Name')
        self.assertEqual(self.mapping.step_type, 'material')


class TestTaskMappingListView(TestCase):
    """Tests for TaskMapping list view."""

    def setUp(self):
        self.client = Client()
        self.mapping = TaskMapping.objects.create(
            task_type_id='LIST-TEST',
            step_type='labor',
            mapping_strategy='direct'
        )

    def test_list_view_shows_add_button(self):
        """List view should have Add New Mapping button."""
        response = self.client.get(reverse('jobs:task_mapping_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add New Mapping')
        self.assertContains(response, reverse('jobs:task_mapping_create'))

    def test_list_view_shows_actions(self):
        """List view should have View/Edit links for each mapping."""
        response = self.client.get(reverse('jobs:task_mapping_list'))
        self.assertContains(response, 'View')
        self.assertContains(response, 'Edit')


class TestTaskMappingDeleteView(TestCase):
    """Tests for TaskMapping delete view."""

    def setUp(self):
        self.client = Client()
        self.mapping = TaskMapping.objects.create(
            task_type_id='DELETE-TEST',
            step_type='labor',
            mapping_strategy='direct'
        )

    def test_delete_view_shows_confirmation(self):
        """GET task_mapping_delete shows confirmation page."""
        response = self.client.get(
            reverse('jobs:task_mapping_delete', args=[self.mapping.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'DELETE-TEST')
        self.assertContains(response, 'Are you sure')

    def test_delete_view_deletes_mapping(self):
        """POST deletes the TaskMapping."""
        response = self.client.post(
            reverse('jobs:task_mapping_delete', args=[self.mapping.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(TaskMapping.objects.filter(pk=self.mapping.pk).exists())

    def test_delete_blocked_when_templates_linked(self):
        """Cannot delete mapping if TaskTemplates are using it."""
        # Create a TaskTemplate linked to this mapping
        TaskTemplate.objects.create(
            template_name='Linked Template',
            task_mapping=self.mapping,
            units='each',
            rate='100.00'
        )
        response = self.client.post(
            reverse('jobs:task_mapping_delete', args=[self.mapping.pk])
        )
        # Should redirect back with error, mapping still exists
        self.assertTrue(TaskMapping.objects.filter(pk=self.mapping.pk).exists())
