"""Tests for LineItemType in Estimate line items."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import LineItemType
from apps.contacts.models import Contact
from apps.jobs.models import Job, Estimate, EstimateLineItem


class EstimateLineItemTypeTest(TestCase):
    """Tests for LineItemType in Estimate line item forms."""

    @classmethod
    def setUpTestData(cls):
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
        cls.service_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )

    def setUp(self):
        self.client = Client()

    def test_manual_form_includes_line_item_type_field(self):
        """Test that manual line item form shows LineItemType field."""
        response = self.client.get(
            reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id])
        )
        self.assertContains(response, 'line_item_type')

    def test_manual_form_creates_line_item_with_type(self):
        """Test that manual form creates line item with LineItemType."""
        response = self.client.post(
            reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id]),
            {
                'manual_submit': '1',
                'description': 'Test Service',
                'qty': '2.00',
                'units': 'hours',
                'price_currency': '50.00',
                'line_item_type': self.service_type.pk,
            }
        )
        line_item = EstimateLineItem.objects.filter(estimate=self.estimate).first()
        self.assertIsNotNone(line_item)
        self.assertEqual(line_item.line_item_type, self.service_type)

    def test_manual_form_requires_line_item_type(self):
        """Test that manual form requires LineItemType."""
        response = self.client.post(
            reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id]),
            {
                'manual_submit': '1',
                'description': 'Test Service',
                'qty': '2.00',
                'units': 'hours',
                'price_currency': '50.00',
                # No line_item_type
            }
        )
        # Should stay on page with error
        self.assertEqual(response.status_code, 200)
        self.assertEqual(EstimateLineItem.objects.filter(estimate=self.estimate).count(), 0)


class EstimateLineItemFromPriceListTest(TestCase):
    """Tests for LineItemType when adding from PriceList."""

    @classmethod
    def setUpTestData(cls):
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
        cls.product_type, _ = LineItemType.objects.get_or_create(
            code='PRD',
            defaults={'name': 'Product', 'taxable': True}
        )
        # Import here to avoid circular import
        from apps.invoicing.models import PriceListItem
        cls.price_list_item = PriceListItem.objects.create(
            code='ITEM-001',
            description='Test Product',
            selling_price=Decimal('100.00'),
            line_item_type=cls.product_type
        )

    def setUp(self):
        self.client = Client()

    def test_pricelist_form_copies_line_item_type(self):
        """Test that adding from price list copies the LineItemType."""
        response = self.client.post(
            reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id]),
            {
                'pricelist_submit': '1',
                'price_list_item': self.price_list_item.pk,
                'qty': '1.00',
            }
        )
        line_item = EstimateLineItem.objects.filter(estimate=self.estimate).first()
        self.assertIsNotNone(line_item)
        self.assertEqual(line_item.line_item_type, self.product_type)
