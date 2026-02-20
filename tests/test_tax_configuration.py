"""
Tests for tax configuration settings - TDD approach.
Testing default_tax_rate and org_tax_multiplier configuration keys.
"""
from decimal import Decimal
from django.test import TestCase
from apps.core.models import Configuration


class TaxConfigurationTest(TestCase):
    """Tests for tax-related Configuration keys."""

    def test_default_tax_rate_can_be_set(self):
        """Test that default_tax_rate can be stored in Configuration."""
        Configuration.objects.create(
            key='default_tax_rate',
            value='0.08'  # 8%
        )

        config = Configuration.objects.get(key='default_tax_rate')
        self.assertEqual(config.value, '0.08')

    def test_default_tax_rate_retrieval_as_decimal(self):
        """Test that default_tax_rate can be retrieved and converted to Decimal."""
        Configuration.objects.create(
            key='default_tax_rate',
            value='0.0825'  # 8.25%
        )

        config = Configuration.objects.get(key='default_tax_rate')
        rate = Decimal(config.value)
        self.assertEqual(rate, Decimal('0.0825'))

    def test_org_tax_multiplier_can_be_set(self):
        """Test that org_tax_multiplier can be stored in Configuration."""
        Configuration.objects.create(
            key='org_tax_multiplier',
            value='0.00'  # Fully exempt
        )

        config = Configuration.objects.get(key='org_tax_multiplier')
        self.assertEqual(config.value, '0.00')

    def test_org_tax_multiplier_retrieval_as_decimal(self):
        """Test that org_tax_multiplier can be retrieved and converted to Decimal."""
        Configuration.objects.create(
            key='org_tax_multiplier',
            value='0.50'  # Half rate
        )

        config = Configuration.objects.get(key='org_tax_multiplier')
        multiplier = Decimal(config.value)
        self.assertEqual(multiplier, Decimal('0.50'))

    def test_missing_default_tax_rate_handled(self):
        """Test that missing default_tax_rate returns DoesNotExist."""
        with self.assertRaises(Configuration.DoesNotExist):
            Configuration.objects.get(key='default_tax_rate')

    def test_missing_org_tax_multiplier_handled(self):
        """Test that missing org_tax_multiplier returns DoesNotExist."""
        with self.assertRaises(Configuration.DoesNotExist):
            Configuration.objects.get(key='org_tax_multiplier')

    def test_default_tax_rate_can_be_updated(self):
        """Test that default_tax_rate can be updated."""
        Configuration.objects.create(
            key='default_tax_rate',
            value='0.08'
        )

        config = Configuration.objects.get(key='default_tax_rate')
        config.value = '0.10'  # 10%
        config.save()

        config.refresh_from_db()
        self.assertEqual(config.value, '0.10')

    def test_org_tax_multiplier_can_be_updated(self):
        """Test that org_tax_multiplier can be updated."""
        Configuration.objects.create(
            key='org_tax_multiplier',
            value='1.00'  # Full rate
        )

        config = Configuration.objects.get(key='org_tax_multiplier')
        config.value = '0.00'  # Now exempt
        config.save()

        config.refresh_from_db()
        self.assertEqual(config.value, '0.00')
