from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.jobs.models import (
    WorkOrderTemplate, TaskTemplate, TemplateTaskAssociation, TemplateBundle
)
from apps.core.models import LineItemType

User = get_user_model()


class TemplateBundleUITest(TestCase):
    """Test the Template Bundle UI functionality"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

        # Create a line item type
        self.line_item_type = LineItemType.objects.create(
            name="Labor", code="LBR"
        )

        # Create work order template
        self.wo_template = WorkOrderTemplate.objects.create(
            template_name="Test WO Template"
        )

        # Create task templates
        self.task1 = TaskTemplate.objects.create(
            template_name="Task 1", rate=50
        )
        self.task2 = TaskTemplate.objects.create(
            template_name="Task 2", rate=75
        )
        self.task3 = TaskTemplate.objects.create(
            template_name="Task 3", rate=100
        )

        # Create associations
        self.assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1,
            sort_order=1
        )
        self.assoc2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=2,
            sort_order=2
        )
        self.assoc3 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task3,
            est_qty=3,
            sort_order=3
        )

    def test_bundle_creation_success(self):
        """Test successfully creating a bundle from selected tasks"""
        url = reverse('jobs:work_order_template_detail',
                      kwargs={'template_id': self.wo_template.template_id})

        response = self.client.post(url, {
            'bundle_tasks': 'true',
            'selected_tasks': [self.assoc1.pk, self.assoc2.pk],
            'bundle_name': 'Test Bundle',
            'bundle_description': 'A test bundle',
            'line_item_type': self.line_item_type.pk
        }, follow=True)

        self.assertEqual(response.status_code, 200)

        # Verify bundle was created
        bundle = TemplateBundle.objects.get(
            work_order_template=self.wo_template,
            name='Test Bundle'
        )
        self.assertEqual(bundle.line_item_type, self.line_item_type)
        self.assertEqual(bundle.description, 'A test bundle')

        # Verify associations were updated
        self.assoc1.refresh_from_db()
        self.assoc2.refresh_from_db()
        self.assoc3.refresh_from_db()

        self.assertEqual(self.assoc1.mapping_strategy, 'bundle')
        self.assertEqual(self.assoc1.bundle, bundle)
        self.assertEqual(self.assoc2.mapping_strategy, 'bundle')
        self.assertEqual(self.assoc2.bundle, bundle)
        # assoc3 should remain unchanged
        self.assertEqual(self.assoc3.mapping_strategy, 'direct')
        self.assertIsNone(self.assoc3.bundle)

    def test_bundle_creation_requires_two_tasks(self):
        """Test that bundling requires at least 2 tasks"""
        url = reverse('jobs:work_order_template_detail',
                      kwargs={'template_id': self.wo_template.template_id})

        response = self.client.post(url, {
            'bundle_tasks': 'true',
            'selected_tasks': [self.assoc1.pk],  # Only 1 task
            'bundle_name': 'Test Bundle',
            'line_item_type': self.line_item_type.pk
        }, follow=True)

        # Should show error message
        messages = list(response.context['messages'])
        self.assertTrue(any('at least 2 tasks' in str(m) for m in messages))

        # No bundle should be created
        self.assertEqual(TemplateBundle.objects.count(), 0)

    def test_bundle_creation_requires_name(self):
        """Test that bundle name is required"""
        url = reverse('jobs:work_order_template_detail',
                      kwargs={'template_id': self.wo_template.template_id})

        response = self.client.post(url, {
            'bundle_tasks': 'true',
            'selected_tasks': [self.assoc1.pk, self.assoc2.pk],
            'bundle_name': '',  # Empty name
            'line_item_type': self.line_item_type.pk
        }, follow=True)

        messages = list(response.context['messages'])
        self.assertTrue(any('name is required' in str(m) for m in messages))
        self.assertEqual(TemplateBundle.objects.count(), 0)

    def test_bundle_creation_requires_line_item_type(self):
        """Test that line item type is required"""
        url = reverse('jobs:work_order_template_detail',
                      kwargs={'template_id': self.wo_template.template_id})

        response = self.client.post(url, {
            'bundle_tasks': 'true',
            'selected_tasks': [self.assoc1.pk, self.assoc2.pk],
            'bundle_name': 'Test Bundle',
            'line_item_type': ''  # No type
        }, follow=True)

        messages = list(response.context['messages'])
        self.assertTrue(any('Line item type is required' in str(m) for m in messages))
        self.assertEqual(TemplateBundle.objects.count(), 0)

    def test_bundled_tasks_display_grouped(self):
        """Test that bundled tasks appear grouped in the UI"""
        # Create a bundle first
        bundle = TemplateBundle.objects.create(
            work_order_template=self.wo_template,
            name="Existing Bundle",
            line_item_type=self.line_item_type
        )
        self.assoc1.mapping_strategy = 'bundle'
        self.assoc1.bundle = bundle
        self.assoc1.save()
        self.assoc2.mapping_strategy = 'bundle'
        self.assoc2.bundle = bundle
        self.assoc2.save()

        url = reverse('jobs:work_order_template_detail',
                      kwargs={'template_id': self.wo_template.template_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Existing Bundle')
        self.assertContains(response, 'bundle-group')
