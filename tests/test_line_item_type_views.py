"""Tests for LineItemType CRUD views."""
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import LineItemType


class LineItemTypeListViewTest(TestCase):
    """Tests for line item type list view."""

    def setUp(self):
        self.client = Client()

    def test_list_view_returns_200(self):
        """Test that list view returns 200."""
        response = self.client.get(reverse('core:line_item_type_list'))
        self.assertEqual(response.status_code, 200)

    def test_list_view_shows_line_item_types(self):
        """Test that list view displays line item types."""
        LineItemType.objects.create(code='TST', name='Test Type')
        response = self.client.get(reverse('core:line_item_type_list'))
        self.assertContains(response, 'Test Type')
        self.assertContains(response, 'TST')

    def test_list_view_only_shows_active_by_default(self):
        """Test that inactive types are hidden by default."""
        LineItemType.objects.create(code='ACT', name='ActiveTestType', is_active=True)
        LineItemType.objects.create(code='INA', name='InactiveTestType', is_active=False)
        response = self.client.get(reverse('core:line_item_type_list'))
        self.assertContains(response, 'ActiveTestType')
        self.assertNotContains(response, 'InactiveTestType')

    def test_list_view_shows_all_with_param(self):
        """Test that show_all=1 displays inactive types."""
        LineItemType.objects.create(code='INA', name='InactiveTestType', is_active=False)
        response = self.client.get(reverse('core:line_item_type_list') + '?show_all=1')
        self.assertContains(response, 'InactiveTestType')


class LineItemTypeDetailViewTest(TestCase):
    """Tests for line item type detail view."""

    def setUp(self):
        self.client = Client()
        self.line_item_type = LineItemType.objects.create(
            code='TST',
            name='Test Type',
            taxable=True,
            default_description='Test description'
        )

    def test_detail_view_returns_200(self):
        """Test that detail view returns 200."""
        response = self.client.get(
            reverse('core:line_item_type_detail', args=[self.line_item_type.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_detail_view_shows_all_fields(self):
        """Test that detail view displays all fields."""
        response = self.client.get(
            reverse('core:line_item_type_detail', args=[self.line_item_type.pk])
        )
        self.assertContains(response, 'TST')
        self.assertContains(response, 'Test Type')
        self.assertContains(response, 'Test description')

    def test_detail_view_404_for_invalid_id(self):
        """Test that detail view returns 404 for invalid ID."""
        response = self.client.get(
            reverse('core:line_item_type_detail', args=[99999])
        )
        self.assertEqual(response.status_code, 404)


class LineItemTypeCreateViewTest(TestCase):
    """Tests for line item type create view."""

    def setUp(self):
        self.client = Client()

    def test_create_view_returns_200(self):
        """Test that create view returns 200."""
        response = self.client.get(reverse('core:line_item_type_create'))
        self.assertEqual(response.status_code, 200)

    def test_create_view_creates_line_item_type(self):
        """Test that POST creates a new line item type."""
        response = self.client.post(reverse('core:line_item_type_create'), {
            'code': 'NEW',
            'name': 'New Type',
            'taxable': True,
            'default_description': 'New description',
            'is_active': True,
        })
        self.assertEqual(LineItemType.objects.filter(code='NEW').count(), 1)
        self.assertRedirects(response, reverse('core:line_item_type_list'))

    def test_create_view_shows_validation_errors(self):
        """Test that create view shows validation errors."""
        # Create existing type first
        LineItemType.objects.create(code='DUP', name='Duplicate')
        response = self.client.post(reverse('core:line_item_type_create'), {
            'code': 'DUP',  # Duplicate code
            'name': 'Another Type',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')


class LineItemTypeEditViewTest(TestCase):
    """Tests for line item type edit view."""

    def setUp(self):
        self.client = Client()
        self.line_item_type = LineItemType.objects.create(
            code='EDT',
            name='Editable Type',
            taxable=False
        )

    def test_edit_view_returns_200(self):
        """Test that edit view returns 200."""
        response = self.client.get(
            reverse('core:line_item_type_edit', args=[self.line_item_type.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_edit_view_updates_line_item_type(self):
        """Test that POST updates the line item type."""
        response = self.client.post(
            reverse('core:line_item_type_edit', args=[self.line_item_type.pk]),
            {
                'code': 'EDT',
                'name': 'Updated Name',
                'taxable': True,
                'default_description': '',
                'is_active': True,
            }
        )
        self.line_item_type.refresh_from_db()
        self.assertEqual(self.line_item_type.name, 'Updated Name')
        self.assertTrue(self.line_item_type.taxable)
        self.assertRedirects(response, reverse('core:line_item_type_detail', args=[self.line_item_type.pk]))

    def test_edit_view_prepopulates_form(self):
        """Test that edit view prepopulates the form with current values."""
        response = self.client.get(
            reverse('core:line_item_type_edit', args=[self.line_item_type.pk])
        )
        self.assertContains(response, 'Editable Type')
        self.assertContains(response, 'EDT')
