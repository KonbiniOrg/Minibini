"""Tests for Tax Configuration UI."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import Configuration


class TaxConfigurationUITest(TestCase):
    """Tests for tax configuration settings UI."""

    def setUp(self):
        self.client = Client()

    def test_settings_shows_tax_rate(self):
        """Test that settings page shows the default tax rate."""
        Configuration.objects.create(key='default_tax_rate', value='0.10')
        response = self.client.get(reverse('settings'))
        self.assertContains(response, 'default_tax_rate')
        self.assertContains(response, '0.10')

    def test_settings_shows_org_tax_multiplier(self):
        """Test that settings page shows the org tax multiplier."""
        Configuration.objects.create(key='org_tax_multiplier', value='1.00')
        response = self.client.get(reverse('settings'))
        self.assertContains(response, 'org_tax_multiplier')
        self.assertContains(response, '1.00')

    def test_settings_shows_tax_settings_section(self):
        """Test that settings page has a Tax Settings section."""
        response = self.client.get(reverse('settings'))
        self.assertContains(response, 'Tax Settings')

    def test_settings_shows_default_values_when_no_config_exists(self):
        """Test that settings page shows default values when no config exists."""
        response = self.client.get(reverse('settings'))
        # Should show the section even without config
        self.assertContains(response, 'Tax Settings')
        # Should indicate no value or show N/A
        self.assertContains(response, 'default_tax_rate')
        self.assertContains(response, 'org_tax_multiplier')

    def test_settings_returns_200(self):
        """Test that settings page returns 200 status code."""
        response = self.client.get(reverse('settings'))
        self.assertEqual(response.status_code, 200)


class TaxConfigurationEditTest(TestCase):
    """Tests for editing tax configuration values."""

    def setUp(self):
        self.client = Client()

    def test_tax_config_edit_view_exists(self):
        """Test that tax configuration edit view exists."""
        response = self.client.get(reverse('tax_config_edit'))
        self.assertEqual(response.status_code, 200)

    def test_tax_config_edit_shows_form(self):
        """Test that edit view shows a form with current values."""
        Configuration.objects.create(key='default_tax_rate', value='0.0825')
        Configuration.objects.create(key='org_tax_multiplier', value='1.00')
        response = self.client.get(reverse('tax_config_edit'))
        self.assertContains(response, '0.0825')
        self.assertContains(response, '1.00')

    def test_tax_config_edit_updates_values(self):
        """Test that POST updates the configuration values."""
        Configuration.objects.create(key='default_tax_rate', value='0.08')
        Configuration.objects.create(key='org_tax_multiplier', value='1.00')

        response = self.client.post(reverse('tax_config_edit'), {
            'default_tax_rate': '0.10',
            'org_tax_multiplier': '0.50',
        })

        # Should redirect to settings page after successful update
        self.assertRedirects(response, reverse('settings'))

        # Verify values were updated
        tax_rate = Configuration.objects.get(key='default_tax_rate')
        self.assertEqual(tax_rate.value, '0.10')

        multiplier = Configuration.objects.get(key='org_tax_multiplier')
        self.assertEqual(multiplier.value, '0.50')

    def test_tax_config_edit_creates_values_if_not_exist(self):
        """Test that POST creates configuration values if they don't exist."""
        # No initial config
        response = self.client.post(reverse('tax_config_edit'), {
            'default_tax_rate': '0.0925',
            'org_tax_multiplier': '0.75',
        })

        self.assertRedirects(response, reverse('settings'))

        # Verify values were created
        tax_rate = Configuration.objects.get(key='default_tax_rate')
        self.assertEqual(tax_rate.value, '0.0925')

        multiplier = Configuration.objects.get(key='org_tax_multiplier')
        self.assertEqual(multiplier.value, '0.75')

    def test_settings_page_has_edit_link(self):
        """Test that settings page has a link to edit tax configuration."""
        response = self.client.get(reverse('settings'))
        self.assertContains(response, reverse('tax_config_edit'))
