"""
Tests for Business.tax_multiplier field - TDD approach.
Testing customer tax exemption multiplier (0.0-1.0).
"""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.contacts.models import Contact, Business


class BusinessTaxMultiplierTest(TestCase):
    """Tests for tax_multiplier field on Business model."""

    def setUp(self):
        """Set up test data."""
        # Create a contact first (required for business default_contact)
        self.contact = Contact.objects.create(
            first_name='Test',
            last_name='Contact',
            email='test@example.com',
            work_number='555-1234'
        )

    def test_tax_multiplier_null_by_default(self):
        """Test that tax_multiplier is null by default (full rate)."""
        business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.contact
        )

        self.assertIsNone(business.tax_multiplier)

    def test_tax_multiplier_can_be_set_to_full_exemption(self):
        """Test that tax_multiplier can be set to 0 (fully exempt)."""
        business = Business.objects.create(
            business_name='Tax Exempt Business',
            default_contact=self.contact,
            tax_multiplier=Decimal('0.00')
        )

        self.assertEqual(business.tax_multiplier, Decimal('0.00'))

    def test_tax_multiplier_can_be_set_to_partial_exemption(self):
        """Test that tax_multiplier can be set to 0.5 (half rate)."""
        business = Business.objects.create(
            business_name='Partial Exempt Business',
            default_contact=self.contact,
            tax_multiplier=Decimal('0.50')
        )

        self.assertEqual(business.tax_multiplier, Decimal('0.50'))

    def test_tax_multiplier_can_be_set_to_full_rate(self):
        """Test that tax_multiplier can be set to 1.0 (full rate)."""
        business = Business.objects.create(
            business_name='Full Rate Business',
            default_contact=self.contact,
            tax_multiplier=Decimal('1.00')
        )

        self.assertEqual(business.tax_multiplier, Decimal('1.00'))

    def test_tax_multiplier_precision(self):
        """Test that tax_multiplier supports 2 decimal places."""
        business = Business.objects.create(
            business_name='Precise Rate Business',
            default_contact=self.contact,
            tax_multiplier=Decimal('0.75')  # 75% rate
        )

        self.assertEqual(business.tax_multiplier, Decimal('0.75'))

    def test_tax_multiplier_can_be_updated(self):
        """Test that tax_multiplier can be updated after creation."""
        business = Business.objects.create(
            business_name='Updateable Business',
            default_contact=self.contact,
            tax_multiplier=Decimal('1.00')
        )

        # Update to exempt status
        business.tax_multiplier = Decimal('0.00')
        business.save()

        business.refresh_from_db()
        self.assertEqual(business.tax_multiplier, Decimal('0.00'))

    def test_tax_multiplier_with_tax_exemption_number(self):
        """Test that tax_multiplier works alongside tax_exemption_number."""
        business = Business.objects.create(
            business_name='Exempt Business',
            default_contact=self.contact,
            tax_exemption_number='EX-12345',
            tax_multiplier=Decimal('0.00')
        )

        self.assertEqual(business.tax_exemption_number, 'EX-12345')
        self.assertEqual(business.tax_multiplier, Decimal('0.00'))
