"""Tests for TaskTemplate edit and delete functionality."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse

from apps.jobs.models import TaskTemplate, WorkOrderTemplate, TemplateTaskAssociation


class TaskTemplateEditViewTest(TestCase):
    """Tests for editing TaskTemplate."""

    def setUp(self):
        self.client = Client()
        self.template = TaskTemplate.objects.create(
            template_name='Original Task',
            description='Original description',
            units='hours',
            rate=Decimal('50.00')
        )

    def test_edit_view_get_returns_form(self):
        """Test that GET request returns form with current values."""
        response = self.client.get(
            reverse('jobs:task_template_edit', args=[self.template.template_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Original Task')
        self.assertContains(response, 'Original description')

    def test_edit_view_post_updates_template(self):
        """Test that POST request updates the template."""
        response = self.client.post(
            reverse('jobs:task_template_edit', args=[self.template.template_id]),
            {
                'template_name': 'Updated Task',
                'description': 'Updated description',
                'units': 'pieces',
                'rate': '75.00',
            }
        )
        self.assertRedirects(response, reverse('jobs:task_template_list'))

        self.template.refresh_from_db()
        self.assertEqual(self.template.template_name, 'Updated Task')
        self.assertEqual(self.template.description, 'Updated description')
        self.assertEqual(self.template.units, 'pieces')
        self.assertEqual(self.template.rate, Decimal('75.00'))

    def test_edit_view_shows_success_message(self):
        """Test that success message is shown after edit."""
        response = self.client.post(
            reverse('jobs:task_template_edit', args=[self.template.template_id]),
            {
                'template_name': 'Updated Task',
                'description': 'Updated description',
                'units': 'hours',
                'rate': '50.00',
            },
            follow=True
        )
        self.assertContains(response, 'updated successfully')

    def test_edit_view_404_for_nonexistent_template(self):
        """Test that 404 is returned for nonexistent template."""
        response = self.client.get(
            reverse('jobs:task_template_edit', args=[99999])
        )
        self.assertEqual(response.status_code, 404)

    def test_edit_view_shows_delete_button_when_unused(self):
        """Test that edit page shows Delete button when template is not used."""
        response = self.client.get(
            reverse('jobs:task_template_edit', args=[self.template.template_id])
        )
        self.assertEqual(response.status_code, 200)
        delete_url = reverse('jobs:task_template_delete', args=[self.template.template_id])
        self.assertContains(response, delete_url)

    def test_edit_view_hides_delete_button_when_used(self):
        """Test that edit page hides Delete button when template is used."""
        # Associate with a WorkOrderTemplate
        work_order_template = WorkOrderTemplate.objects.create(
            template_name='Test WOT',
            description='Test'
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=work_order_template,
            task_template=self.template,
            est_qty=1
        )

        response = self.client.get(
            reverse('jobs:task_template_edit', args=[self.template.template_id])
        )
        self.assertEqual(response.status_code, 200)
        delete_url = reverse('jobs:task_template_delete', args=[self.template.template_id])
        self.assertNotContains(response, delete_url)

    def test_edit_view_shows_work_order_templates_using_this(self):
        """Test that edit page shows list of WorkOrderTemplates using this TaskTemplate."""
        # Associate with WorkOrderTemplates
        wot1 = WorkOrderTemplate.objects.create(
            template_name='Kitchen Remodel',
            description='Test'
        )
        wot2 = WorkOrderTemplate.objects.create(
            template_name='Bathroom Renovation',
            description='Test'
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot1,
            task_template=self.template,
            est_qty=1
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot2,
            task_template=self.template,
            est_qty=2
        )

        response = self.client.get(
            reverse('jobs:task_template_edit', args=[self.template.template_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Kitchen Remodel')
        self.assertContains(response, 'Bathroom Renovation')

    def test_edit_view_shows_not_used_message_when_unused(self):
        """Test that edit page shows message when template is not used."""
        response = self.client.get(
            reverse('jobs:task_template_edit', args=[self.template.template_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not used')


class TaskTemplateDeleteViewTest(TestCase):
    """Tests for deleting TaskTemplate."""

    def setUp(self):
        self.client = Client()
        self.template = TaskTemplate.objects.create(
            template_name='Task to Delete',
            description='This will be deleted',
            units='hours',
            rate=Decimal('25.00')
        )

    def test_delete_view_removes_unused_template(self):
        """Test that POST request deletes an unused template."""
        template_id = self.template.template_id
        response = self.client.post(
            reverse('jobs:task_template_delete', args=[template_id])
        )
        self.assertRedirects(response, reverse('jobs:task_template_list'))

        # Verify template is deleted
        self.assertFalse(TaskTemplate.objects.filter(template_id=template_id).exists())

    def test_delete_view_shows_success_message(self):
        """Test that success message is shown after delete."""
        response = self.client.post(
            reverse('jobs:task_template_delete', args=[self.template.template_id]),
            follow=True
        )
        self.assertContains(response, 'deleted successfully')

    def test_delete_view_404_for_nonexistent_template(self):
        """Test that 404 is returned for nonexistent template."""
        response = self.client.post(
            reverse('jobs:task_template_delete', args=[99999])
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_view_blocks_deletion_when_used(self):
        """Test that deletion is blocked when template is used in WorkOrderTemplates."""
        # Associate with a WorkOrderTemplate
        work_order_template = WorkOrderTemplate.objects.create(
            template_name='Test WOT',
            description='Test'
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=work_order_template,
            task_template=self.template,
            est_qty=1
        )

        template_id = self.template.template_id
        response = self.client.post(
            reverse('jobs:task_template_delete', args=[template_id]),
            follow=True
        )

        # Verify template still exists
        self.assertTrue(TaskTemplate.objects.filter(template_id=template_id).exists())
        # Verify error message shown
        self.assertContains(response, 'cannot be deleted')

    def test_delete_view_get_not_allowed(self):
        """Test that GET request is not allowed for delete."""
        response = self.client.get(
            reverse('jobs:task_template_delete', args=[self.template.template_id])
        )
        self.assertEqual(response.status_code, 405)


class TaskTemplateListTest(TestCase):
    """Tests for TaskTemplate list page."""

    def setUp(self):
        self.client = Client()
        self.template = TaskTemplate.objects.create(
            template_name='Test Task Template',
            description='Test description'
        )

    def test_list_page_has_edit_link(self):
        """Test that list page shows Edit link."""
        response = self.client.get(reverse('jobs:task_template_list'))
        self.assertEqual(response.status_code, 200)
        edit_url = reverse('jobs:task_template_edit', args=[self.template.template_id])
        self.assertContains(response, f'href="{edit_url}"')

    def test_list_page_does_not_have_delete_button(self):
        """Test that list page does NOT show Delete button (moved to edit view)."""
        response = self.client.get(reverse('jobs:task_template_list'))
        self.assertEqual(response.status_code, 200)
        delete_url = reverse('jobs:task_template_delete', args=[self.template.template_id])
        self.assertNotContains(response, delete_url)
