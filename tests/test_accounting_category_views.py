"""Tests for AccountingCategory CRUD views."""
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import AccountingCategory


class AccountingCategoryListViewTest(TestCase):
    """Tests for line item type list view."""

    def setUp(self):
        self.client = Client()
        self.client.force_login(get_user_model().objects.create_superuser(username=f'admin_{id(self)}', password='testpass'))

    def test_list_view_returns_200(self):
        """Test that list view returns 200."""
        response = self.client.get(reverse('core:accounting_category_list'))
        self.assertEqual(response.status_code, 200)

    def test_list_view_shows_accounting_categories(self):
        """Test that list view displays line item types."""
        AccountingCategory.objects.create(code='TST', name='Test Type')
        response = self.client.get(reverse('core:accounting_category_list'))
        self.assertContains(response, 'Test Type')
        self.assertContains(response, 'TST')

    def test_list_view_only_shows_active_by_default(self):
        """Test that inactive types are hidden by default."""
        AccountingCategory.objects.create(code='ACT', name='ActiveTestType', is_active=True)
        AccountingCategory.objects.create(code='INA', name='InactiveTestType', is_active=False)
        response = self.client.get(reverse('core:accounting_category_list'))
        self.assertContains(response, 'ActiveTestType')
        self.assertNotContains(response, 'InactiveTestType')

    def test_list_view_shows_all_with_param(self):
        """Test that show_all=1 displays inactive types."""
        AccountingCategory.objects.create(code='INA', name='InactiveTestType', is_active=False)
        response = self.client.get(reverse('core:accounting_category_list') + '?show_all=1')
        self.assertContains(response, 'InactiveTestType')


class AccountingCategoryDetailViewTest(TestCase):
    """Tests for line item type detail view."""

    def setUp(self):
        self.client = Client()
        self.client.force_login(get_user_model().objects.create_superuser(username=f'admin_{id(self)}', password='testpass'))
        self.accounting_category = AccountingCategory.objects.create(
            code='TST',
            name='Test Type',
            taxable=True,
            default_description='Test description'
        )

    def test_detail_view_returns_200(self):
        """Test that detail view returns 200."""
        response = self.client.get(
            reverse('core:accounting_category_detail', args=[self.accounting_category.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_detail_view_shows_all_fields(self):
        """Test that detail view displays all fields."""
        response = self.client.get(
            reverse('core:accounting_category_detail', args=[self.accounting_category.pk])
        )
        self.assertContains(response, 'TST')
        self.assertContains(response, 'Test Type')
        self.assertContains(response, 'Test description')

    def test_detail_view_404_for_invalid_id(self):
        """Test that detail view returns 404 for invalid ID."""
        response = self.client.get(
            reverse('core:accounting_category_detail', args=[99999])
        )
        self.assertEqual(response.status_code, 404)


class AccountingCategoryCreateViewTest(TestCase):
    """Tests for line item type create view."""

    def setUp(self):
        self.client = Client()
        self.client.force_login(get_user_model().objects.create_superuser(username=f'admin_{id(self)}', password='testpass'))

    def test_create_view_returns_200(self):
        """Test that create view returns 200."""
        response = self.client.get(reverse('core:accounting_category_create'))
        self.assertEqual(response.status_code, 200)

    def test_create_view_creates_accounting_category(self):
        """Test that POST creates a new line item type."""
        response = self.client.post(reverse('core:accounting_category_create'), {
            'code': 'NEW',
            'name': 'New Type',
            'taxable': True,
            'default_description': 'New description',
            'is_active': True,
        })
        self.assertEqual(AccountingCategory.objects.filter(code='NEW').count(), 1)
        self.assertRedirects(response, reverse('core:accounting_category_list'))

    def test_create_view_shows_validation_errors(self):
        """Test that create view shows validation errors."""
        # Create existing type first
        AccountingCategory.objects.create(code='DUP', name='Duplicate')
        response = self.client.post(reverse('core:accounting_category_create'), {
            'code': 'DUP',  # Duplicate code
            'name': 'Another Type',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')


class AccountingCategoryEditViewTest(TestCase):
    """Tests for line item type edit view."""

    def setUp(self):
        self.client = Client()
        self.client.force_login(get_user_model().objects.create_superuser(username=f'admin_{id(self)}', password='testpass'))
        self.accounting_category = AccountingCategory.objects.create(
            code='EDT',
            name='Editable Type',
            taxable=False
        )

    def test_edit_view_returns_200(self):
        """Test that edit view returns 200."""
        response = self.client.get(
            reverse('core:accounting_category_edit', args=[self.accounting_category.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_edit_view_updates_accounting_category(self):
        """Test that POST updates the line item type."""
        response = self.client.post(
            reverse('core:accounting_category_edit', args=[self.accounting_category.pk]),
            {
                'code': 'EDT',
                'name': 'Updated Name',
                'taxable': True,
                'default_description': '',
                'is_active': True,
            }
        )
        self.accounting_category.refresh_from_db()
        self.assertEqual(self.accounting_category.name, 'Updated Name')
        self.assertTrue(self.accounting_category.taxable)
        self.assertRedirects(response, reverse('core:accounting_category_detail', args=[self.accounting_category.pk]))

    def test_edit_view_prepopulates_form(self):
        """Test that edit view prepopulates the form with current values."""
        response = self.client.get(
            reverse('core:accounting_category_edit', args=[self.accounting_category.pk])
        )
        self.assertContains(response, 'Editable Type')
        self.assertContains(response, 'EDT')
