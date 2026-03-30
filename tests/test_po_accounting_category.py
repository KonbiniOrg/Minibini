"""Tests for AccountingCategory in PurchaseOrder line items."""
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import AccountingCategory
from apps.contacts.models import Contact, Business
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.inventory.models import PriceListItem


class POAccountingCategoryManualFormTest(TestCase):
    """Tests for AccountingCategory in PO line item manual entry forms."""

    @classmethod
    def setUpTestData(cls):
        cls.default_contact = Contact.objects.create(
            first_name='Default',
            last_name='Contact',
            email='default@test.com'
        )
        cls.business = Business.objects.create(
            business_name='Test Vendor',
            default_contact=cls.default_contact
        )
        cls.po = PurchaseOrder.objects.create(
            business=cls.business,
            po_number='PO-001',
            status=PurchaseOrder.STATUS_DRAFT
        )
        cls.service_type, _ = AccountingCategory.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(get_user_model().objects.create_superuser(username=f'admin_{id(self)}', password='testpass'))

    def test_manual_form_includes_accounting_category_field(self):
        """Test that manual line item form shows AccountingCategory field."""
        response = self.client.get(
            reverse('purchasing:purchase_order_add_line_item', args=[self.po.po_id])
        )
        self.assertContains(response, 'accounting_category')

    def test_manual_form_creates_line_item_with_type(self):
        """Test that manual form creates line item with AccountingCategory."""
        response = self.client.post(
            reverse('purchasing:purchase_order_add_line_item', args=[self.po.po_id]),
            {
                'manual_submit': '1',
                'description': 'Test Service',
                'qty': '2.00',
                'units': 'hours',
                'price': '50.00',
                'accounting_category': self.service_type.pk,
            }
        )
        line_item = PurchaseOrderLineItem.objects.filter(purchase_order=self.po).first()
        self.assertIsNotNone(line_item)
        self.assertEqual(line_item.accounting_category, self.service_type)

    def test_manual_form_requires_accounting_category(self):
        """Test that manual form requires AccountingCategory."""
        response = self.client.post(
            reverse('purchasing:purchase_order_add_line_item', args=[self.po.po_id]),
            {
                'manual_submit': '1',
                'description': 'Test Service',
                'qty': '2.00',
                'units': 'hours',
                'price': '50.00',
                # No accounting_category
            }
        )
        # Should stay on page with error
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PurchaseOrderLineItem.objects.filter(purchase_order=self.po).count(), 0)


class POLineItemFromPriceListTest(TestCase):
    """Tests for AccountingCategory when adding from PriceList."""

    @classmethod
    def setUpTestData(cls):
        cls.default_contact = Contact.objects.create(
            first_name='Default',
            last_name='Contact',
            email='default2@test.com'
        )
        cls.business = Business.objects.create(
            business_name='Test Vendor',
            default_contact=cls.default_contact
        )
        cls.po = PurchaseOrder.objects.create(
            business=cls.business,
            po_number='PO-002',
            status=PurchaseOrder.STATUS_DRAFT
        )
        cls.product_type, _ = AccountingCategory.objects.get_or_create(
            code='PRD',
            defaults={'name': 'Product', 'taxable': True}
        )
        cls.price_list_item = PriceListItem.objects.create(
            code='ITEM-001',
            description='Test Product',
            selling_price=Decimal('100.00'),
            purchase_price=Decimal('75.00'),
            accounting_category=cls.product_type
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(get_user_model().objects.create_superuser(username=f'admin_{id(self)}', password='testpass'))

    def test_pricelist_form_copies_accounting_category(self):
        """Test that adding from price list copies the AccountingCategory."""
        response = self.client.post(
            reverse('purchasing:purchase_order_add_line_item', args=[self.po.po_id]),
            {
                'pricelist_submit': '1',
                'price_list_item': self.price_list_item.pk,
                'qty': '1.00',
            }
        )
        line_item = PurchaseOrderLineItem.objects.filter(purchase_order=self.po).first()
        self.assertIsNotNone(line_item)
        self.assertEqual(line_item.accounting_category, self.product_type)
