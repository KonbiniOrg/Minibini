"""
Tests for TaxCalculationService.

Taxation amounts are handled by QuickBooks, not the app — the service only
surfaces per-line *taxability* (so the invoice→QBO export can group taxable vs
non-taxable lines). The rate/amount methods were removed; only
get_effective_taxability remains.
"""
from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory
from apps.core.services import TaxCalculationService
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.estimates.models import Estimate, EstimateLineItem


class TaxCalculationServiceEffectiveTaxabilityTest(TestCase):
    """Tests for get_effective_taxability method."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data."""
        cls.taxable_type, _ = AccountingCategory.objects.get_or_create(
            code='MAT',
            defaults={'name': 'Material', 'taxable': True}
        )
        cls.nontaxable_type, _ = AccountingCategory.objects.get_or_create(
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
            accounting_category=self.taxable_type,
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            taxable_override=None  # Use type default
        )

        result = TaxCalculationService.get_effective_taxability(line_item)
        self.assertTrue(result)

    def test_uses_type_default_nontaxable(self):
        """Test that non-taxable type default is respected."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            accounting_category=self.nontaxable_type,
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            taxable_override=None
        )

        result = TaxCalculationService.get_effective_taxability(line_item)
        self.assertFalse(result)

    def test_override_true_overrides_nontaxable_type(self):
        """Test that taxable_override=True overrides non-taxable type default."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            accounting_category=self.nontaxable_type,  # Type is non-taxable
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            taxable_override=True  # Override to taxable
        )

        result = TaxCalculationService.get_effective_taxability(line_item)
        self.assertTrue(result)

    def test_override_false_overrides_taxable_type(self):
        """Test that taxable_override=False overrides taxable type default."""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            accounting_category=self.taxable_type,  # Type is taxable
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            taxable_override=False  # Override to non-taxable
        )

        result = TaxCalculationService.get_effective_taxability(line_item)
        self.assertFalse(result)
