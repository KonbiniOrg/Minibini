"""Integration tests for LineItemType feature."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import Configuration, LineItemType
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, Estimate, EstimateLineItem
from apps.invoicing.models import PriceListItem


class LineItemTypeIntegrationTest(TestCase):
    """End-to-end tests for LineItemType workflow."""

    def setUp(self):
        self.client = Client()
        # Set up default tax rate
        Configuration.objects.create(key='default_tax_rate', value='0.10')  # 10%

    def test_full_workflow_taxable_item(self):
        """Test complete workflow: Create type -> PriceListItem -> Estimate with tax."""
        # 1. Create LineItemType
        response = self.client.post(reverse('core:line_item_type_create'), {
            'code': 'HWRE',
            'name': 'Hardware',
            'taxable': True,
            'default_description': 'Hardware items',
            'is_active': True,
        })
        self.assertRedirects(response, reverse('core:line_item_type_list'))
        hardware_type = LineItemType.objects.get(code='HWRE')
        self.assertTrue(hardware_type.taxable)

        # 2. Create PriceListItem with that type
        response = self.client.post(reverse('invoicing:price_list_item_add'), {
            'code': 'BOLT-001',
            'description': 'Steel Bolt',
            'selling_price': '10.00',
            'purchase_price': '5.00',
            'qty_on_hand': '100.00',
            'qty_sold': '0.00',
            'qty_wasted': '0.00',
            'line_item_type': hardware_type.pk,
        })
        self.assertRedirects(response, reverse('invoicing:price_list_item_list'))
        price_list_item = PriceListItem.objects.get(code='BOLT-001')
        self.assertEqual(price_list_item.line_item_type, hardware_type)

        # 3. Create Contact, Job, Estimate
        contact = Contact.objects.create(
            first_name='Integration',
            last_name='Test',
            email='integration@test.com',
            work_number='555-0000'
        )
        job = Job.objects.create(job_number='INT-001', contact=contact)
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-INT-001',
            status='draft'
        )

        # 4. Add line item from PriceListItem
        response = self.client.post(
            reverse('jobs:estimate_add_line_item', args=[estimate.estimate_id]),
            {
                'pricelist_submit': '1',
                'price_list_item': price_list_item.pk,
                'qty': '10',
            }
        )

        # 5. Verify line item has correct type
        line_item = EstimateLineItem.objects.get(estimate=estimate)
        self.assertEqual(line_item.line_item_type, hardware_type)
        self.assertEqual(line_item.total_amount, Decimal('100.00'))  # 10 x $10

        # 6. Verify tax calculation on estimate detail
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[estimate.estimate_id])
        )
        self.assertContains(response, 'Subtotal')
        self.assertContains(response, '100.00')
        self.assertContains(response, 'Tax')
        self.assertContains(response, '10.00')  # 10% of $100
        self.assertContains(response, '110.00')  # Total with tax

    def test_full_workflow_nontaxable_item(self):
        """Test workflow with non-taxable service item."""
        # Create non-taxable type
        service_type = LineItemType.objects.create(
            code='SRVC',
            name='Service',
            taxable=False,
            is_active=True
        )

        # Create Contact, Job, Estimate
        contact = Contact.objects.create(
            first_name='Service',
            last_name='Customer',
            email='service@test.com',
            work_number='555-0001'
        )
        job = Job.objects.create(job_number='SVC-001', contact=contact)
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-SVC-001',
            status='draft'
        )

        # Add manual service line item
        response = self.client.post(
            reverse('jobs:estimate_add_line_item', args=[estimate.estimate_id]),
            {
                'manual_submit': '1',
                'description': 'Consulting',
                'qty': '5.00',
                'units': 'hours',
                'price_currency': '100.00',
                'line_item_type': service_type.pk,
            }
        )

        # Verify tax is zero
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[estimate.estimate_id])
        )
        self.assertContains(response, '500.00')  # Subtotal
        self.assertContains(response, '$0.00')   # Tax is zero

    def test_customer_tax_exemption_workflow(self):
        """Test workflow with tax-exempt customer."""
        # Create taxable type
        material_type = LineItemType.objects.create(
            code='MTAL',
            name='Metal',
            taxable=True,
            is_active=True
        )

        # Create exempt business and contact
        contact = Contact.objects.create(
            first_name='Exempt',
            last_name='Corp',
            email='exempt@corp.com',
            work_number='555-0002'
        )
        exempt_business = Business.objects.create(
            business_name='Tax Exempt Organization',
            default_contact=contact,
            tax_multiplier=Decimal('0.00')  # Fully exempt
        )
        contact.business = exempt_business
        contact.save()

        # Create job and estimate for exempt customer
        job = Job.objects.create(job_number='EXM-001', contact=contact)
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-EXM-001',
            status='draft'
        )

        # Add taxable item
        response = self.client.post(
            reverse('jobs:estimate_add_line_item', args=[estimate.estimate_id]),
            {
                'manual_submit': '1',
                'description': 'Metal Sheet',
                'qty': '1.00',
                'units': 'each',
                'price_currency': '200.00',
                'line_item_type': material_type.pk,
            }
        )

        # Verify tax is zero due to exemption
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[estimate.estimate_id])
        )
        self.assertContains(response, '200.00')  # Subtotal
        self.assertContains(response, 'exempt')   # Exemption indicator

    def test_line_item_type_crud_workflow(self):
        """Test full CRUD workflow for LineItemType."""
        # CREATE
        response = self.client.post(reverse('core:line_item_type_create'), {
            'code': 'TEST',
            'name': 'Test Type',
            'taxable': True,
            'default_description': 'Test description',
            'is_active': True,
        })
        self.assertRedirects(response, reverse('core:line_item_type_list'))
        line_item_type = LineItemType.objects.get(code='TEST')
        self.assertEqual(line_item_type.name, 'Test Type')
        self.assertTrue(line_item_type.taxable)

        # READ - List view
        response = self.client.get(reverse('core:line_item_type_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Type')

        # READ - Detail view
        response = self.client.get(
            reverse('core:line_item_type_detail', args=[line_item_type.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Type')
        self.assertContains(response, 'TEST')

        # UPDATE
        response = self.client.post(
            reverse('core:line_item_type_edit', args=[line_item_type.pk]),
            {
                'code': 'TEST',
                'name': 'Updated Test Type',
                'taxable': False,
                'default_description': 'Updated description',
                'is_active': True,
            }
        )
        self.assertRedirects(
            response,
            reverse('core:line_item_type_detail', args=[line_item_type.pk])
        )
        line_item_type.refresh_from_db()
        self.assertEqual(line_item_type.name, 'Updated Test Type')
        self.assertFalse(line_item_type.taxable)

        # SOFT DELETE (deactivate)
        response = self.client.post(
            reverse('core:line_item_type_edit', args=[line_item_type.pk]),
            {
                'code': 'TEST',
                'name': 'Updated Test Type',
                'taxable': False,
                'default_description': 'Updated description',
                'is_active': False,  # Deactivate
            }
        )
        line_item_type.refresh_from_db()
        self.assertFalse(line_item_type.is_active)

        # Verify inactive type is hidden from list by default
        # Use a fresh client to avoid flash messages interfering
        fresh_client = Client()
        response = fresh_client.get(reverse('core:line_item_type_list'))
        self.assertNotContains(response, 'Updated Test Type')

        # Verify inactive type is shown with show_all parameter
        response = fresh_client.get(
            reverse('core:line_item_type_list') + '?show_all=1'
        )
        self.assertContains(response, 'Updated Test Type')

    def test_price_list_item_inherits_type_to_estimate(self):
        """Test that PriceListItem type is correctly inherited by EstimateLineItem."""
        # Create line item type
        material_type = LineItemType.objects.create(
            code='MATL',
            name='Material',
            taxable=True,
            is_active=True
        )

        # Create price list item with the type
        pli = PriceListItem.objects.create(
            code='WIDGET-001',
            description='Widget',
            units='each',
            purchase_price=Decimal('5.00'),
            selling_price=Decimal('10.00'),
            qty_on_hand=Decimal('50.00'),
            line_item_type=material_type
        )

        # Create contact, job, estimate
        contact = Contact.objects.create(
            first_name='Inherit',
            last_name='Test',
            email='inherit@test.com',
            work_number='555-0003'
        )
        job = Job.objects.create(job_number='INH-001', contact=contact)
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-INH-001',
            status='draft'
        )

        # Add line item from price list
        response = self.client.post(
            reverse('jobs:estimate_add_line_item', args=[estimate.estimate_id]),
            {
                'pricelist_submit': '1',
                'price_list_item': pli.pk,
                'qty': '5',
            }
        )

        # Verify the estimate line item has the correct type
        line_item = EstimateLineItem.objects.get(estimate=estimate)
        self.assertEqual(line_item.line_item_type, material_type)
        self.assertEqual(line_item.description, 'Widget')
        self.assertEqual(line_item.price_currency, Decimal('10.00'))
        self.assertEqual(line_item.total_amount, Decimal('50.00'))

    def test_mixed_taxable_and_nontaxable_items(self):
        """Test estimate with both taxable and non-taxable items."""
        # Create taxable type
        product_type = LineItemType.objects.create(
            code='PROD',
            name='Product',
            taxable=True,
            is_active=True
        )

        # Create non-taxable type
        service_type = LineItemType.objects.create(
            code='SERV',
            name='Service',
            taxable=False,
            is_active=True
        )

        # Create contact, job, estimate
        contact = Contact.objects.create(
            first_name='Mixed',
            last_name='Test',
            email='mixed@test.com',
            work_number='555-0004'
        )
        job = Job.objects.create(job_number='MIX-001', contact=contact)
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-MIX-001',
            status='draft'
        )

        # Add taxable product
        self.client.post(
            reverse('jobs:estimate_add_line_item', args=[estimate.estimate_id]),
            {
                'manual_submit': '1',
                'description': 'Physical Product',
                'qty': '2.00',
                'units': 'each',
                'price_currency': '100.00',
                'line_item_type': product_type.pk,
            }
        )

        # Add non-taxable service
        self.client.post(
            reverse('jobs:estimate_add_line_item', args=[estimate.estimate_id]),
            {
                'manual_submit': '1',
                'description': 'Installation Service',
                'qty': '1.00',
                'units': 'hours',
                'price_currency': '50.00',
                'line_item_type': service_type.pk,
            }
        )

        # Verify totals on estimate detail
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[estimate.estimate_id])
        )

        # Subtotal should be $250 (2 x $100 + $50)
        self.assertContains(response, '250.00')

        # Tax should be $20 (10% of $200 taxable amount)
        self.assertContains(response, '20.00')

        # Total should be $270 ($250 + $20)
        self.assertContains(response, '270.00')

    def test_partial_tax_exemption(self):
        """Test workflow with partial tax exemption (e.g., 50% off)."""
        # Create taxable type
        material_type = LineItemType.objects.create(
            code='PART',
            name='Parts',
            taxable=True,
            is_active=True
        )

        # Create partially exempt business and contact
        contact = Contact.objects.create(
            first_name='Partial',
            last_name='Exempt',
            email='partial@exempt.com',
            work_number='555-0005'
        )
        partial_business = Business.objects.create(
            business_name='Partial Exempt Organization',
            default_contact=contact,
            tax_multiplier=Decimal('0.50')  # 50% of normal tax
        )
        contact.business = partial_business
        contact.save()

        # Create job and estimate
        job = Job.objects.create(job_number='PART-001', contact=contact)
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-PART-001',
            status='draft'
        )

        # Add taxable item worth $100
        self.client.post(
            reverse('jobs:estimate_add_line_item', args=[estimate.estimate_id]),
            {
                'manual_submit': '1',
                'description': 'Parts',
                'qty': '1.00',
                'units': 'each',
                'price_currency': '100.00',
                'line_item_type': material_type.pk,
            }
        )

        # Verify tax is 50% of normal (5% instead of 10%)
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[estimate.estimate_id])
        )
        self.assertContains(response, '100.00')  # Subtotal
        # Tax should be $5 (10% x 50% = 5% of $100)
        self.assertContains(response, '5.00')
        # Total should be $105
        self.assertContains(response, '105.00')


class LineItemTypeFormIntegrationTest(TestCase):
    """Test LineItemType appears correctly in forms."""

    def setUp(self):
        self.client = Client()
        Configuration.objects.create(key='default_tax_rate', value='0.10')

    def test_line_item_type_appears_in_estimate_manual_form(self):
        """Test that LineItemType dropdown appears in manual line item form."""
        # Create a line item type
        LineItemType.objects.create(
            code='TEST',
            name='Test Type',
            taxable=True,
            is_active=True
        )

        # Create contact, job, estimate
        contact = Contact.objects.create(
            first_name='Form',
            last_name='Test',
            email='form@test.com',
            work_number='555-0006'
        )
        job = Job.objects.create(job_number='FRM-001', contact=contact)
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-FRM-001',
            status='draft'
        )

        # Get add line item form
        response = self.client.get(
            reverse('jobs:estimate_add_line_item', args=[estimate.estimate_id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'line_item_type')
        self.assertContains(response, 'Test Type')

    def test_inactive_types_hidden_from_forms(self):
        """Test that inactive LineItemTypes are hidden from form dropdowns."""
        # Create active type
        active_type = LineItemType.objects.create(
            code='ACTIVE',
            name='Active Type',
            taxable=True,
            is_active=True
        )

        # Create inactive type
        inactive_type = LineItemType.objects.create(
            code='INACTIVE',
            name='Inactive Type',
            taxable=True,
            is_active=False
        )

        # Create contact, job, estimate
        contact = Contact.objects.create(
            first_name='Hide',
            last_name='Test',
            email='hide@test.com',
            work_number='555-0007'
        )
        job = Job.objects.create(job_number='HID-001', contact=contact)
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-HID-001',
            status='draft'
        )

        # Get add line item form
        response = self.client.get(
            reverse('jobs:estimate_add_line_item', args=[estimate.estimate_id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Active Type')
        self.assertNotContains(response, 'Inactive Type')

    def test_line_item_type_appears_in_price_list_form(self):
        """Test that LineItemType dropdown appears in price list item form."""
        # Create a line item type
        LineItemType.objects.create(
            code='PRLIST',
            name='Price List Type',
            taxable=True,
            is_active=True
        )

        # Get price list item add form
        response = self.client.get(reverse('invoicing:price_list_item_add'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'line_item_type')
        self.assertContains(response, 'Price List Type')


class TaxCalculationIntegrationTest(TestCase):
    """Integration tests for tax calculation display."""

    def setUp(self):
        self.client = Client()
        Configuration.objects.create(key='default_tax_rate', value='0.0825')  # 8.25%

    def test_tax_rate_applied_correctly(self):
        """Test that configured tax rate is applied correctly."""
        # Create taxable type
        taxable_type = LineItemType.objects.create(
            code='TAX',
            name='Taxable Item',
            taxable=True,
            is_active=True
        )

        # Create contact, job, estimate
        contact = Contact.objects.create(
            first_name='Tax',
            last_name='Rate',
            email='taxrate@test.com',
            work_number='555-0008'
        )
        job = Job.objects.create(job_number='TAX-001', contact=contact)
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-TAX-001',
            status='draft'
        )

        # Add item worth exactly $100
        self.client.post(
            reverse('jobs:estimate_add_line_item', args=[estimate.estimate_id]),
            {
                'manual_submit': '1',
                'description': 'Test Item',
                'qty': '1.00',
                'units': 'each',
                'price_currency': '100.00',
                'line_item_type': taxable_type.pk,
            }
        )

        # Verify tax is 8.25% of $100 = $8.25
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[estimate.estimate_id])
        )
        self.assertContains(response, '8.25')  # Tax amount
        self.assertContains(response, '108.25')  # Total

    def test_no_tax_when_no_taxable_items(self):
        """Test that no tax is shown when all items are non-taxable."""
        # Create non-taxable type
        nontaxable_type = LineItemType.objects.create(
            code='NOTAX',
            name='Non-Taxable',
            taxable=False,
            is_active=True
        )

        # Create contact, job, estimate
        contact = Contact.objects.create(
            first_name='No',
            last_name='Tax',
            email='notax@test.com',
            work_number='555-0009'
        )
        job = Job.objects.create(job_number='NOTAX-001', contact=contact)
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-NOTAX-001',
            status='draft'
        )

        # Add non-taxable item
        self.client.post(
            reverse('jobs:estimate_add_line_item', args=[estimate.estimate_id]),
            {
                'manual_submit': '1',
                'description': 'Labor Service',
                'qty': '10.00',
                'units': 'hours',
                'price_currency': '75.00',
                'line_item_type': nontaxable_type.pk,
            }
        )

        # Verify tax is $0
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[estimate.estimate_id])
        )
        self.assertContains(response, '750.00')  # Subtotal
        self.assertContains(response, '$0.00')   # Tax
