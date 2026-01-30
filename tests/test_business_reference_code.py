"""Tests for Business reference code generation.

These tests verify that:
1. Reference codes are auto-generated when not provided
2. Reference codes are unique
3. IntegrityError from duplicate codes triggers retry logic
"""
from django.test import TestCase
from django.db import IntegrityError, transaction
from apps.contacts.models import Contact, Business


class BusinessReferenceCodeTest(TestCase):
    """Test Business.save() reference code generation."""

    def setUp(self):
        # Create a contact to use as default_contact
        self.contact = Contact.objects.create(
            first_name='Test',
            last_name='Contact',
            email='test@test.com',
            work_number='555-1234'
        )

    def test_auto_generates_reference_code(self):
        """Business should auto-generate reference code if not provided."""
        business = Business.objects.create(
            business_name="Test Business",
            default_contact=self.contact
        )

        self.assertIsNotNone(business.our_reference_code)
        self.assertTrue(business.our_reference_code.startswith('BUS-'))

    def test_preserves_provided_reference_code(self):
        """Business should preserve reference code if explicitly provided."""
        business = Business.objects.create(
            business_name="Test Business",
            default_contact=self.contact,
            our_reference_code="CUSTOM-001"
        )

        self.assertEqual(business.our_reference_code, "CUSTOM-001")

    def test_unique_reference_codes(self):
        """Each business should have a unique reference code."""
        business1 = Business.objects.create(
            business_name="Business 1",
            default_contact=self.contact
        )
        business2 = Business.objects.create(
            business_name="Business 2",
            default_contact=self.contact
        )

        self.assertNotEqual(business1.our_reference_code, business2.our_reference_code)

    def test_handles_integrity_error_gracefully(self):
        """Business.save() should handle IntegrityError from duplicate codes.

        This tests that the retry logic works when a race condition would
        otherwise cause a duplicate key error.
        """
        # Create first business with a specific code
        business1 = Business.objects.create(
            business_name="Business 1",
            default_contact=self.contact,
            our_reference_code="BUS-0001"
        )

        # Create second business - it should NOT fail even if the auto-generated
        # code would conflict, because the save method should retry
        business2 = Business.objects.create(
            business_name="Business 2",
            default_contact=self.contact
        )

        # Both should exist with different codes
        self.assertEqual(Business.objects.count(), 2)
        self.assertNotEqual(business1.our_reference_code, business2.our_reference_code)

    def test_reference_code_not_regenerated_on_update(self):
        """Updating a business should not change its reference code."""
        business = Business.objects.create(
            business_name="Test Business",
            default_contact=self.contact
        )
        original_code = business.our_reference_code

        # Update the business
        business.business_name = "Updated Business"
        business.save()

        business.refresh_from_db()
        self.assertEqual(business.our_reference_code, original_code)

    def test_duplicate_reference_code_raises_integrity_error(self):
        """Manually providing a duplicate code should raise IntegrityError."""
        Business.objects.create(
            business_name="Business 1",
            default_contact=self.contact,
            our_reference_code="DUPLICATE-001"
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Business.objects.create(
                    business_name="Business 2",
                    default_contact=self.contact,
                    our_reference_code="DUPLICATE-001"
                )
