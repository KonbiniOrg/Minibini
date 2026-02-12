"""
Tests for BaseLineItem tax-related fields - TDD approach.
Testing line_item_type FK, taxable_override, and tax_rate_override.
"""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.core.models import LineItemType
from apps.jobs.models import Job, Estimate, EstimateLineItem
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
        cls.service_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )
        cls.material_type, _ = LineItemType.objects.get_or_create(
            code='MAT',
            defaults={'name': 'Material', 'taxable': True}
        )

    def test_line_item_type_fk_nullable_initially(self):
        """Test that line_item_type FK is nullable (for migration strategy)."""
        # Creating a line item without line_item_type should work initially
        # This will be changed to required after data migration
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            description='Test item without type'
        )
        self.assertIsNone(line_item.line_item_type)

    def test_line_item_type_fk_assignment(self):
        """Test that line_item_type can be assigned to a line item."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.service_type,
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            description='Service item'
        )

        self.assertEqual(line_item.line_item_type, self.service_type)
        self.assertEqual(line_item.line_item_type.code, 'SVC')

    def test_taxable_override_null_by_default(self):
        """Test that taxable_override is null by default (uses type default)."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.material_type,
            qty=Decimal('1.00'),
            price=Decimal('50.00'),
            description='Material item'
        )

        self.assertIsNone(line_item.taxable_override)

    def test_taxable_override_can_be_set_true(self):
        """Test that taxable_override can be explicitly set to True."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.service_type,  # Service is taxable=False by default
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            description='Taxable service',
            taxable_override=True  # Override to taxable
        )

        self.assertTrue(line_item.taxable_override)

    def test_taxable_override_can_be_set_false(self):
        """Test that taxable_override can be explicitly set to False."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.material_type,  # Material is taxable=True by default
            qty=Decimal('1.00'),
            price=Decimal('50.00'),
            description='Non-taxable material',
            taxable_override=False  # Override to non-taxable
        )

        self.assertFalse(line_item.taxable_override)

    def test_tax_rate_override_null_by_default(self):
        """Test that tax_rate_override is null by default (uses app default)."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.material_type,
            qty=Decimal('1.00'),
            price=Decimal('50.00'),
            description='Material item'
        )

        self.assertIsNone(line_item.tax_rate_override)

    def test_tax_rate_override_can_be_set(self):
        """Test that tax_rate_override can be set to a custom rate."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.material_type,
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            description='Special tax rate item',
            tax_rate_override=Decimal('0.0500')  # 5% special rate
        )

        self.assertEqual(line_item.tax_rate_override, Decimal('0.0500'))

    def test_tax_rate_override_precision(self):
        """Test that tax_rate_override supports 4 decimal places (e.g., 8.25% = 0.0825)."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.material_type,
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            description='Precise tax rate item',
            tax_rate_override=Decimal('0.0825')  # 8.25%
        )

        self.assertEqual(line_item.tax_rate_override, Decimal('0.0825'))

    def test_line_item_type_protect_on_delete(self):
        """Test that deleting a LineItemType is protected if line items reference it."""
        from django.db.models import ProtectedError

        # Create a new type specifically for this test
        test_type = LineItemType.objects.create(
            code='TST',
            name='Test Type'
        )

        # Create a line item referencing it
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=test_type,
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            description='Protected item'
        )

        # Deleting the type should raise ProtectedError
        with self.assertRaises(ProtectedError):
            test_type.delete()

    def test_line_item_type_related_name(self):
        """Test that LineItemType has access to related line items."""
        line_item1 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.service_type,
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            description='Service 1'
        )
        line_item2 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.service_type,
            qty=Decimal('2.00'),
            price=Decimal('50.00'),
            description='Service 2'
        )

        # The related_name pattern is %(class)s_items
        service_items = self.service_type.estimatelineitem_items.all()
        self.assertEqual(service_items.count(), 2)
        self.assertIn(line_item1, service_items)
        self.assertIn(line_item2, service_items)
