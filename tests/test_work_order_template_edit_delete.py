"""Tests for WorkOrderTemplate edit and delete functionality."""
from django.test import TestCase, Client
from django.urls import reverse

from apps.jobs.models import WorkOrderTemplate, TaskTemplate, TemplateTaskAssociation, TemplateBundle
from apps.core.models import LineItemType


class WorkOrderTemplateEditViewTest(TestCase):
    """Tests for editing WorkOrderTemplate."""

    def setUp(self):
        self.client = Client()
        self.template = WorkOrderTemplate.objects.create(
            template_name='Original Name',
            description='Original description'
        )

    def test_edit_view_get_returns_form(self):
        """Test that GET request returns form with current values."""
        response = self.client.get(
            reverse('jobs:work_order_template_edit', args=[self.template.template_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Original Name')
        self.assertContains(response, 'Original description')

    def test_edit_view_post_updates_template(self):
        """Test that POST request updates the template."""
        response = self.client.post(
            reverse('jobs:work_order_template_edit', args=[self.template.template_id]),
            {
                'template_name': 'Updated Name',
                'description': 'Updated description',
            }
        )
        self.assertRedirects(
            response,
            reverse('jobs:work_order_template_detail', args=[self.template.template_id])
        )

        self.template.refresh_from_db()
        self.assertEqual(self.template.template_name, 'Updated Name')
        self.assertEqual(self.template.description, 'Updated description')

    def test_edit_view_shows_success_message(self):
        """Test that success message is shown after edit."""
        response = self.client.post(
            reverse('jobs:work_order_template_edit', args=[self.template.template_id]),
            {
                'template_name': 'Updated Name',
                'description': 'Updated description',
            },
            follow=True
        )
        self.assertContains(response, 'updated successfully')

    def test_edit_view_404_for_nonexistent_template(self):
        """Test that 404 is returned for nonexistent template."""
        response = self.client.get(
            reverse('jobs:work_order_template_edit', args=[99999])
        )
        self.assertEqual(response.status_code, 404)


class WorkOrderTemplateDeleteViewTest(TestCase):
    """Tests for deleting WorkOrderTemplate."""

    def setUp(self):
        self.client = Client()
        self.template = WorkOrderTemplate.objects.create(
            template_name='Template to Delete',
            description='This will be deleted'
        )

    def test_delete_view_removes_template(self):
        """Test that POST request deletes the template."""
        template_id = self.template.template_id
        response = self.client.post(
            reverse('jobs:work_order_template_delete', args=[template_id])
        )
        self.assertRedirects(response, reverse('jobs:work_order_template_list'))

        # Verify template is deleted
        self.assertFalse(WorkOrderTemplate.objects.filter(template_id=template_id).exists())

    def test_delete_view_shows_success_message(self):
        """Test that success message is shown after delete."""
        response = self.client.post(
            reverse('jobs:work_order_template_delete', args=[self.template.template_id]),
            follow=True
        )
        self.assertContains(response, 'deleted successfully')

    def test_delete_view_404_for_nonexistent_template(self):
        """Test that 404 is returned for nonexistent template."""
        response = self.client.post(
            reverse('jobs:work_order_template_delete', args=[99999])
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_view_cascades_to_associations(self):
        """Test that deleting template also deletes task associations."""
        # Create a task template and associate it
        task_template = TaskTemplate.objects.create(
            template_name='Test Task',
            description='Test task description'
        )
        association = TemplateTaskAssociation.objects.create(
            work_order_template=self.template,
            task_template=task_template,
            est_qty=1
        )
        association_id = association.pk

        # Delete the work order template
        self.client.post(
            reverse('jobs:work_order_template_delete', args=[self.template.template_id])
        )

        # Verify association is deleted but task template remains
        self.assertFalse(TemplateTaskAssociation.objects.filter(pk=association_id).exists())
        self.assertTrue(TaskTemplate.objects.filter(template_id=task_template.template_id).exists())

    def test_delete_view_cascades_to_bundles(self):
        """Test that deleting template also deletes bundles."""
        # Create a line item type for the bundle
        line_item_type = LineItemType.objects.create(
            code='TEST',
            name='Test Type'
        )
        bundle = TemplateBundle.objects.create(
            work_order_template=self.template,
            name='Test Bundle',
            line_item_type=line_item_type
        )
        bundle_id = bundle.pk

        # Delete the work order template
        self.client.post(
            reverse('jobs:work_order_template_delete', args=[self.template.template_id])
        )

        # Verify bundle is deleted
        self.assertFalse(TemplateBundle.objects.filter(pk=bundle_id).exists())

    def test_delete_view_get_not_allowed(self):
        """Test that GET request is not allowed for delete."""
        response = self.client.get(
            reverse('jobs:work_order_template_delete', args=[self.template.template_id])
        )
        # Should return 405 Method Not Allowed
        self.assertEqual(response.status_code, 405)


class WorkOrderTemplateDetailEditDeleteLinksTest(TestCase):
    """Tests for Edit and Delete links on detail page."""

    def setUp(self):
        self.client = Client()
        self.template = WorkOrderTemplate.objects.create(
            template_name='Test Template',
            description='Test description'
        )

    def test_detail_page_has_edit_link(self):
        """Test that detail page shows Edit link."""
        response = self.client.get(
            reverse('jobs:work_order_template_detail', args=[self.template.template_id])
        )
        self.assertEqual(response.status_code, 200)
        edit_url = reverse('jobs:work_order_template_edit', args=[self.template.template_id])
        self.assertContains(response, f'href="{edit_url}"')

    def test_detail_page_has_delete_button(self):
        """Test that detail page shows Delete button."""
        response = self.client.get(
            reverse('jobs:work_order_template_detail', args=[self.template.template_id])
        )
        self.assertEqual(response.status_code, 200)
        delete_url = reverse('jobs:work_order_template_delete', args=[self.template.template_id])
        self.assertContains(response, delete_url)
