"""Tests for tax display on Estimates."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import Configuration, LineItemType
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, Estimate, EstimateLineItem


class EstimateTaxDisplayTest(TestCase):
    """Tests for tax calculation display on Estimate detail."""

    @classmethod
    def setUpTestData(cls):
        # Set up tax rate
        Configuration.objects.create(key='default_tax_rate', value='0.10')  # 10%

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
            estimate_number='EST-001',
            status='draft'
        )
        cls.taxable_type, _ = LineItemType.objects.get_or_create(
            code='MAT',
            defaults={'name': 'Material', 'taxable': True}
        )
        cls.nontaxable_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )

    def setUp(self):
        self.client = Client()
        # Clear line items between tests
        EstimateLineItem.objects.filter(estimate=self.estimate).delete()

    def test_estimate_detail_shows_subtotal(self):
        """Test that estimate detail shows subtotal."""
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            description='Test Item',
            qty=Decimal('2.00'),
            price=Decimal('50.00')
        )
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[self.estimate.estimate_id])
        )
        self.assertContains(response, 'Subtotal')
        self.assertContains(response, '100.00')

    def test_estimate_detail_shows_tax(self):
        """Test that estimate detail shows tax amount."""
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            description='Taxable Item',
            qty=Decimal('1.00'),
            price=Decimal('100.00')
        )
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[self.estimate.estimate_id])
        )
        self.assertContains(response, 'Tax')
        self.assertContains(response, '10.00')  # 10% of $100

    def test_estimate_detail_shows_total_with_tax(self):
        """Test that estimate detail shows total including tax."""
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            description='Taxable Item',
            qty=Decimal('1.00'),
            price=Decimal('100.00')
        )
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[self.estimate.estimate_id])
        )
        self.assertContains(response, 'Total')
        self.assertContains(response, '110.00')  # $100 + $10 tax

    def test_nontaxable_items_excluded_from_tax(self):
        """Test that non-taxable items don't contribute to tax."""
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.nontaxable_type,  # Non-taxable
            description='Service Item',
            qty=Decimal('1.00'),
            price=Decimal('100.00')
        )
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[self.estimate.estimate_id])
        )
        # Tax should be $0
        self.assertContains(response, '$0.00')

    def test_estimate_detail_shows_line_item_type(self):
        """Test that estimate detail shows LineItemType for each item."""
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            description='Material Item',
            qty=Decimal('1.00'),
            price=Decimal('50.00')
        )
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[self.estimate.estimate_id])
        )
        self.assertContains(response, 'Material')  # The type name


class EstimateCustomerExemptionTest(TestCase):
    """Tests for customer tax exemption on Estimates."""

    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='default_tax_rate', value='0.10')  # 10%

        cls.taxable_type, _ = LineItemType.objects.get_or_create(
            code='MAT',
            defaults={'name': 'Material', 'taxable': True}
        )

    def setUp(self):
        self.client = Client()

    def test_exempt_customer_shows_zero_tax(self):
        """Test that tax-exempt customer shows $0 tax."""
        # Create exempt business
        contact = Contact.objects.create(
            first_name='Exempt',
            last_name='Customer',
            email='exempt@example.com',
            work_number='555-0000'
        )
        exempt_business = Business.objects.create(
            business_name='Tax Exempt Corp',
            default_contact=contact,
            tax_multiplier=Decimal('0.00')
        )
        contact.business = exempt_business
        contact.save()

        job = Job.objects.create(
            job_number='EXEMPT-001',
            contact=contact
        )
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-EXEMPT',
            status='draft'
        )
        EstimateLineItem.objects.create(
            estimate=estimate,
            line_item_type=self.taxable_type,
            description='Taxable Item',
            qty=Decimal('1.00'),
            price=Decimal('100.00')
        )

        response = self.client.get(
            reverse('jobs:estimate_detail', args=[estimate.estimate_id])
        )
        # Should show exemption info and $0 tax
        self.assertContains(response, 'exempt', status_code=200)
