"""Tests for BundlingRule CRUD views."""

from django.test import TestCase, Client
from django.urls import reverse
from apps.jobs.models import BundlingRule, TaskMapping
from apps.jobs.forms import BundlingRuleForm
from apps.core.models import LineItemType


class TestBundlingRuleListView(TestCase):
    """Tests for BundlingRule list view."""

    def setUp(self):
        self.client = Client()

    def test_list_view_renders(self):
        """GET bundling_rule_list shows the list."""
        response = self.client.get(reverse('jobs:bundling_rule_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bundling Rules')

    def test_list_view_shows_rules(self):
        """List view displays existing rules."""
        rule = BundlingRule.objects.create(
            rule_name='Test Rule',
            product_type='cabinet',
            line_item_template='Custom {product_type}',
            pricing_method='sum_components'
        )
        response = self.client.get(reverse('jobs:bundling_rule_list'))
        self.assertContains(response, 'Test Rule')
        self.assertContains(response, 'cabinet')

    def test_list_view_shows_add_text(self):
        """List view has Add New Rule text."""
        response = self.client.get(reverse('jobs:bundling_rule_list'))
        self.assertContains(response, 'Add New Rule')


class TestBundlingRuleCreateView(TestCase):
    """Tests for BundlingRule create view."""

    def setUp(self):
        self.client = Client()

    def test_create_view_renders_form(self):
        """GET bundling_rule_create shows the form."""
        response = self.client.get(reverse('jobs:bundling_rule_create'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Bundling Rule')

    def test_create_view_saves_rule(self):
        """POST with valid data creates a BundlingRule."""
        data = {
            'rule_name': 'New Test Rule',
            'product_type': 'table',
            'line_item_template': 'Custom {product_type}',
            'combine_instances': True,
            'pricing_method': 'sum_components',
            'default_units': 'each',
            'include_materials': True,
            'include_labor': True,
            'include_overhead': False,
            'priority': 100,
            'is_active': True,
        }
        response = self.client.post(reverse('jobs:bundling_rule_create'), data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(BundlingRule.objects.filter(rule_name='New Test Rule').exists())


class TestBundlingRuleDetailView(TestCase):
    """Tests for BundlingRule detail view."""

    def setUp(self):
        self.client = Client()
        self.rule = BundlingRule.objects.create(
            rule_name='Detail Test Rule',
            product_type='cabinet',
            line_item_template='Custom {product_type} - {bundle_identifier}',
            pricing_method='sum_components'
        )

    def test_detail_view_shows_rule(self):
        """GET bundling_rule_detail shows the rule details."""
        response = self.client.get(
            reverse('jobs:bundling_rule_detail', args=[self.rule.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Detail Test Rule')
        self.assertContains(response, 'cabinet')


class TestBundlingRuleEditView(TestCase):
    """Tests for BundlingRule edit view."""

    def setUp(self):
        self.client = Client()
        self.rule = BundlingRule.objects.create(
            rule_name='Edit Test Rule',
            product_type='table',
            line_item_template='Original Template',
            pricing_method='sum_components'
        )

    def test_edit_view_renders_form(self):
        """GET bundling_rule_edit shows form with existing data."""
        response = self.client.get(
            reverse('jobs:bundling_rule_edit', args=[self.rule.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit Test Rule')

    def test_edit_view_updates_rule(self):
        """POST with valid data updates the BundlingRule."""
        data = {
            'rule_name': 'Updated Rule Name',
            'product_type': 'table',
            'line_item_template': 'Updated Template',
            'combine_instances': False,
            'pricing_method': 'sum_components',
            'default_units': 'each',
            'include_materials': True,
            'include_labor': True,
            'include_overhead': True,
            'priority': 50,
            'is_active': True,
        }
        response = self.client.post(
            reverse('jobs:bundling_rule_edit', args=[self.rule.pk]),
            data
        )
        self.assertEqual(response.status_code, 302)
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.rule_name, 'Updated Rule Name')
        self.assertEqual(self.rule.priority, 50)
        self.assertTrue(self.rule.include_overhead)


class TestBundlingRuleDeleteView(TestCase):
    """Tests for BundlingRule delete view."""

    def setUp(self):
        self.client = Client()
        self.rule = BundlingRule.objects.create(
            rule_name='Delete Test Rule',
            product_type='chair',
            line_item_template='Custom {product_type}',
            pricing_method='sum_components'
        )

    def test_delete_view_shows_confirmation(self):
        """GET bundling_rule_delete shows confirmation page."""
        response = self.client.get(
            reverse('jobs:bundling_rule_delete', args=[self.rule.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Delete Test Rule')
        self.assertContains(response, 'Are you sure')

    def test_delete_view_deletes_rule(self):
        """POST deletes the BundlingRule."""
        response = self.client.post(
            reverse('jobs:bundling_rule_delete', args=[self.rule.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(BundlingRule.objects.filter(pk=self.rule.pk).exists())


class TestBundlingRuleConflictingTypesValidation(TestCase):
    """Tests for validating conflicting LineItemTypes in bundles."""

    def setUp(self):
        # Create two different LineItemTypes
        self.service_type = LineItemType.objects.create(
            code='SVC_TEST', name='Service', taxable=False
        )
        self.material_type = LineItemType.objects.create(
            code='MAT_TEST', name='Material', taxable=True
        )

    def test_form_rejects_conflicting_types_without_override(self):
        """
        When TaskMappings for the same product_type have different
        output_line_item_types, the form should reject a bundling rule
        that doesn't specify its own output_line_item_type.
        """
        # Create TaskMappings with same product_type but different line item types
        TaskMapping.objects.create(
            task_type_id='CABINET-FRAME',
            step_type='component',
            mapping_strategy='bundle',
            default_product_type='cabinet',
            output_line_item_type=self.service_type
        )
        TaskMapping.objects.create(
            task_type_id='CABINET-MATERIALS',
            step_type='material',
            mapping_strategy='bundle',
            default_product_type='cabinet',
            output_line_item_type=self.material_type
        )

        # Try to create a bundling rule without specifying output_line_item_type
        form = BundlingRuleForm(data={
            'rule_name': 'Cabinet Bundler',
            'product_type': 'cabinet',
            'line_item_template': 'Custom {product_type}',
            'combine_instances': True,
            'pricing_method': 'sum_components',
            'include_materials': True,
            'include_labor': True,
            'include_overhead': False,
            'priority': 100,
            'is_active': True,
            # NOT setting output_line_item_type
        })

        # Form should be invalid due to conflicting types
        self.assertFalse(form.is_valid())
        self.assertIn('output_line_item_type', form.errors)
        self.assertIn('conflicting', form.errors['output_line_item_type'][0].lower())

    def test_form_accepts_conflicting_types_with_explicit_override(self):
        """
        When TaskMappings have different types, the form should accept
        a bundling rule that explicitly sets output_line_item_type.
        """
        # Create TaskMappings with same product_type but different line item types
        TaskMapping.objects.create(
            task_type_id='TABLE-FRAME',
            step_type='component',
            mapping_strategy='bundle',
            default_product_type='table',
            output_line_item_type=self.service_type
        )
        TaskMapping.objects.create(
            task_type_id='TABLE-MATERIALS',
            step_type='material',
            mapping_strategy='bundle',
            default_product_type='table',
            output_line_item_type=self.material_type
        )

        # Create bundling rule WITH explicit output_line_item_type
        form = BundlingRuleForm(data={
            'rule_name': 'Table Bundler',
            'product_type': 'table',
            'line_item_template': 'Custom {product_type}',
            'combine_instances': True,
            'pricing_method': 'sum_components',
            'default_units': 'each',
            'include_materials': True,
            'include_labor': True,
            'include_overhead': False,
            'priority': 100,
            'is_active': True,
            'output_line_item_type': self.service_type.pk,  # Explicit override
        })

        # Form should be valid
        self.assertTrue(form.is_valid(), f"Form errors: {form.errors}")

    def test_form_accepts_consistent_types_without_override(self):
        """
        When all TaskMappings for a product_type have the same
        output_line_item_type, no explicit override is needed.
        """
        # Create TaskMappings with same product_type and same line item type
        TaskMapping.objects.create(
            task_type_id='CHAIR-FRAME',
            step_type='component',
            mapping_strategy='bundle',
            default_product_type='chair',
            output_line_item_type=self.service_type
        )
        TaskMapping.objects.create(
            task_type_id='CHAIR-FINISH',
            step_type='labor',
            mapping_strategy='bundle',
            default_product_type='chair',
            output_line_item_type=self.service_type  # Same type
        )

        # Create bundling rule without output_line_item_type
        form = BundlingRuleForm(data={
            'rule_name': 'Chair Bundler',
            'product_type': 'chair',
            'line_item_template': 'Custom {product_type}',
            'combine_instances': True,
            'pricing_method': 'sum_components',
            'default_units': 'each',
            'include_materials': True,
            'include_labor': True,
            'include_overhead': False,
            'priority': 100,
            'is_active': True,
            # NOT setting output_line_item_type - should be OK
        })

        # Form should be valid
        self.assertTrue(form.is_valid(), f"Form errors: {form.errors}")
