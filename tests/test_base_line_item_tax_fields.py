"""
Tests for BaseLineItem tax-related fields - TDD approach.
Testing the accounting_category FK. (The per-line taxable_override /
tax_rate_override phantom fields were removed with the per-line QBO push.)
"""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.core.models import AccountingCategory
from apps.jobs.models import Job
from apps.estimates.models import Estimate, EstimateLineItem
from apps.contacts.models import Contact, Business


class BaseLineItemTaxFieldsTest(TestCase):
    """Tests for tax fields on BaseLineItem (via EstimateLineItem)."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data that persists across test methods."""
        # Create a business and contact for the job
        cls.contact = Contact.objects.create(
            first_name='Test',
            last_name='Customer',
            email='test@example.com',
            work_number='555-1234'
        )

        # Create a job
        cls.job = Job.objects.create(
            job_number='TEST-001',
            contact=cls.contact
        )

        # Create an estimate
        cls.estimate = Estimate.objects.create(
            job=cls.job,
            estimate_number='EST-001'
        )

        # Get or create line item types (migration creates defaults)
        cls.service_type, _ = AccountingCategory.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )
        cls.material_type, _ = AccountingCategory.objects.get_or_create(
            code='MAT',
            defaults={'name': 'Material', 'taxable': True}
        )

    def test_accounting_category_fk_nullable_initially(self):
        """Test that accounting_category FK is nullable (for migration strategy)."""
        # Creating a line item without accounting_category should work initially
        # This will be changed to required after data migration
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            description='Test item without type'
        )
        self.assertIsNone(line_item.accounting_category)

    def test_accounting_category_fk_assignment(self):
        """Test that accounting_category can be assigned to a line item."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            accounting_category=self.service_type,
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            description='Service item'
        )

        self.assertEqual(line_item.accounting_category, self.service_type)
        self.assertEqual(line_item.accounting_category.code, 'SVC')


    def test_accounting_category_protect_on_delete(self):
        """Test that deleting a AccountingCategory is protected if line items reference it."""
        from django.db.models import ProtectedError

        # Create a new type specifically for this test
        test_type = AccountingCategory.objects.create(
            code='TST',
            name='Test Type'
        )

        # Create a line item referencing it
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            accounting_category=test_type,
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            description='Protected item'
        )

        # Deleting the type should raise ProtectedError
        with self.assertRaises(ProtectedError):
            test_type.delete()

    def test_accounting_category_related_name(self):
        """Test that AccountingCategory has access to related line items."""
        line_item1 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            accounting_category=self.service_type,
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            description='Service 1'
        )
        line_item2 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            accounting_category=self.service_type,
            qty=Decimal('2.00'),
            price=Decimal('50.00'),
            description='Service 2'
        )

        # The related_name pattern is %(class)s_items
        rate_schemes = self.service_type.estimatelineitem_items.all()
        self.assertEqual(rate_schemes.count(), 2)
        self.assertIn(line_item1, rate_schemes)
        self.assertIn(line_item2, rate_schemes)
