"""
Tests for TaxCalculationService - TDD approach.
Testing tax calculation logic for line items and documents.
"""
from decimal import Decimal
from django.test import TestCase
from apps.core.models import Configuration, LineItemType
from apps.core.services import TaxCalculationService
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, Estimate, EstimateLineItem


class TaxCalculationServiceEffectiveTaxabilityTest(TestCase):
    """Tests for get_effective_taxability method."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data."""
        cls.taxable_type, _ = LineItemType.objects.get_or_create(
            code='MAT',
            defaults={'name': 'Material', 'taxable': True}
        )
        cls.nontaxable_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )

        # Set up estimate for line items
        cls.contact = Contact.objects.create(
            first_name='Test',
            last_name='Customer',
            email='test@example.com',
            work_number='555-1234'
        )
        cls.job = Job.objects.create(
            job_number='TEST-001',
            contact=cls.contact
        )
        cls.estimate = Estimate.objects.create(
            job=cls.job,
            estimate_number='EST-001'
        )

    def test_uses_type_default_when_override_is_null(self):
        """Test that taxability uses type default when override is null."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00'),
            taxable_override=None  # Use type default
        )

        result = TaxCalculationService.get_effective_taxability(line_item)
        self.assertTrue(result)

    def test_uses_type_default_nontaxable(self):
        """Test that non-taxable type default is respected."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.nontaxable_type,
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00'),
            taxable_override=None
        )

        result = TaxCalculationService.get_effective_taxability(line_item)
        self.assertFalse(result)

    def test_override_true_overrides_nontaxable_type(self):
        """Test that taxable_override=True overrides non-taxable type default."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.nontaxable_type,  # Type is non-taxable
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00'),
            taxable_override=True  # Override to taxable
        )

        result = TaxCalculationService.get_effective_taxability(line_item)
        self.assertTrue(result)

    def test_override_false_overrides_taxable_type(self):
        """Test that taxable_override=False overrides taxable type default."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,  # Type is taxable
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00'),
            taxable_override=False  # Override to non-taxable
        )

        result = TaxCalculationService.get_effective_taxability(line_item)
        self.assertFalse(result)


class TaxCalculationServiceEffectiveTaxRateTest(TestCase):
    """Tests for get_effective_tax_rate method."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data."""
        cls.line_item_type, _ = LineItemType.objects.get_or_create(
            code='MAT',
            defaults={'name': 'Material', 'taxable': True}
        )

        cls.contact = Contact.objects.create(
            first_name='Test',
            last_name='Customer',
            email='test@example.com',
            work_number='555-1234'
        )
        cls.job = Job.objects.create(
            job_number='TEST-001',
            contact=cls.contact
        )
        cls.estimate = Estimate.objects.create(
            job=cls.job,
            estimate_number='EST-001'
        )

    def test_uses_app_default_when_override_is_null(self):
        """Test that tax rate uses app default when override is null."""
        # Set up app default
        Configuration.objects.create(key='default_tax_rate', value='0.08')

        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.line_item_type,
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00'),
            tax_rate_override=None
        )

        result = TaxCalculationService.get_effective_tax_rate(line_item)
        self.assertEqual(result, Decimal('0.08'))

    def test_uses_override_when_set(self):
        """Test that tax_rate_override is used when set."""
        Configuration.objects.create(key='default_tax_rate', value='0.08')

        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.line_item_type,
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00'),
            tax_rate_override=Decimal('0.05')  # 5% special rate
        )

        result = TaxCalculationService.get_effective_tax_rate(line_item)
        self.assertEqual(result, Decimal('0.05'))

    def test_defaults_to_zero_when_no_config(self):
        """Test that rate defaults to 0 when no Configuration exists."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.line_item_type,
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00'),
            tax_rate_override=None
        )

        result = TaxCalculationService.get_effective_tax_rate(line_item)
        self.assertEqual(result, Decimal('0'))


class TaxCalculationServiceLineItemTaxTest(TestCase):
    """Tests for calculate_line_item_tax method."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data."""
        Configuration.objects.create(key='default_tax_rate', value='0.10')  # 10%

        cls.taxable_type, _ = LineItemType.objects.get_or_create(
            code='MAT',
            defaults={'name': 'Material', 'taxable': True}
        )
        cls.nontaxable_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )

        cls.contact = Contact.objects.create(
            first_name='Test',
            last_name='Customer',
            email='test@example.com',
            work_number='555-1234'
        )
        cls.job = Job.objects.create(
            job_number='TEST-001',
            contact=cls.contact
        )
        cls.estimate = Estimate.objects.create(
            job=cls.job,
            estimate_number='EST-001'
        )

    def test_calculates_tax_for_taxable_item(self):
        """Test basic tax calculation for a taxable item."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            qty=Decimal('2.00'),
            price_currency=Decimal('50.00'),  # total = 100.00
            taxable_override=None
        )

        # 10% of $100 = $10
        result = TaxCalculationService.calculate_line_item_tax(line_item)
        self.assertEqual(result, Decimal('10.00'))

    def test_returns_zero_for_nontaxable_item(self):
        """Test that non-taxable items return zero tax."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.nontaxable_type,
            qty=Decimal('2.00'),
            price_currency=Decimal('50.00'),
            taxable_override=None
        )

        result = TaxCalculationService.calculate_line_item_tax(line_item)
        self.assertEqual(result, Decimal('0'))

    def test_applies_customer_full_exemption(self):
        """Test that customer with tax_multiplier=0 is fully exempt."""
        exempt_business = Business.objects.create(
            business_name='Tax Exempt Corp',
            default_contact=self.contact,
            tax_multiplier=Decimal('0.00')
        )

        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            qty=Decimal('2.00'),
            price_currency=Decimal('50.00'),
            taxable_override=None
        )

        result = TaxCalculationService.calculate_line_item_tax(line_item, customer=exempt_business)
        self.assertEqual(result, Decimal('0.00'))

    def test_applies_customer_partial_exemption(self):
        """Test that customer with tax_multiplier=0.5 pays half rate."""
        partial_business = Business.objects.create(
            business_name='Partial Exempt Corp',
            default_contact=self.contact,
            tax_multiplier=Decimal('0.50')
        )

        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            qty=Decimal('2.00'),
            price_currency=Decimal('50.00'),  # total = 100.00
            taxable_override=None
        )

        # 10% * 0.5 = 5% rate, 5% of $100 = $5
        result = TaxCalculationService.calculate_line_item_tax(line_item, customer=partial_business)
        self.assertEqual(result, Decimal('5.00'))

    def test_null_customer_multiplier_uses_full_rate(self):
        """Test that customer with null tax_multiplier uses full rate."""
        regular_business = Business.objects.create(
            business_name='Regular Corp',
            default_contact=self.contact,
            tax_multiplier=None  # Full rate
        )

        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            qty=Decimal('2.00'),
            price_currency=Decimal('50.00'),
            taxable_override=None
        )

        result = TaxCalculationService.calculate_line_item_tax(line_item, customer=regular_business)
        self.assertEqual(result, Decimal('10.00'))

    def test_applies_org_multiplier_for_purchases(self):
        """Test that org_tax_multiplier is applied when customer is None (purchasing)."""
        Configuration.objects.create(key='org_tax_multiplier', value='0.00')  # We're tax exempt

        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            qty=Decimal('2.00'),
            price_currency=Decimal('50.00'),
            taxable_override=None
        )

        # No customer = purchasing, org is exempt
        result = TaxCalculationService.calculate_line_item_tax(line_item, customer=None)
        self.assertEqual(result, Decimal('0.00'))

    def test_rounds_to_two_decimal_places(self):
        """Test that tax is rounded to 2 decimal places."""
        # Set rate that would produce long decimal
        Configuration.objects.update_or_create(
            key='default_tax_rate',
            defaults={'value': '0.0825'}  # 8.25%
        )

        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            qty=Decimal('1.00'),
            price_currency=Decimal('33.33'),  # 8.25% of 33.33 = 2.749725
            taxable_override=None
        )

        result = TaxCalculationService.calculate_line_item_tax(line_item)
        self.assertEqual(result, Decimal('2.75'))  # Rounded


class TaxCalculationServiceDocumentTaxTest(TestCase):
    """Tests for calculate_document_tax method."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data."""
        Configuration.objects.create(key='default_tax_rate', value='0.10')  # 10%

        cls.taxable_type, _ = LineItemType.objects.get_or_create(
            code='MAT',
            defaults={'name': 'Material', 'taxable': True}
        )
        cls.nontaxable_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )

        cls.contact = Contact.objects.create(
            first_name='Test',
            last_name='Customer',
            email='test@example.com',
            work_number='555-1234'
        )
        cls.job = Job.objects.create(
            job_number='TEST-001',
            contact=cls.contact
        )
        cls.estimate = Estimate.objects.create(
            job=cls.job,
            estimate_number='EST-001'
        )

    def test_sums_tax_across_multiple_line_items(self):
        """Test that document tax is sum of all line item taxes."""
        # Create multiple line items
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00'),  # 10% = $10
        )
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            qty=Decimal('2.00'),
            price_currency=Decimal('25.00'),  # total 50, 10% = $5
        )
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.nontaxable_type,
            qty=Decimal('1.00'),
            price_currency=Decimal('200.00'),  # Non-taxable = $0
        )

        result = TaxCalculationService.calculate_document_tax(self.estimate)
        self.assertEqual(result, Decimal('15.00'))  # $10 + $5 + $0

    def test_empty_document_returns_zero(self):
        """Test that document with no line items returns zero tax."""
        empty_estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-002'
        )

        result = TaxCalculationService.calculate_document_tax(empty_estimate)
        self.assertEqual(result, Decimal('0'))

    def test_applies_customer_multiplier_to_all_items(self):
        """Test that customer multiplier applies to all taxable line items."""
        exempt_business = Business.objects.create(
            business_name='Tax Exempt Corp',
            default_contact=self.contact,
            tax_multiplier=Decimal('0.00')
        )

        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00'),
        )
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            qty=Decimal('1.00'),
            price_currency=Decimal('50.00'),
        )

        result = TaxCalculationService.calculate_document_tax(self.estimate, customer=exempt_business)
        self.assertEqual(result, Decimal('0.00'))
