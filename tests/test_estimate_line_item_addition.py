"""Tests for adding line items to estimates"""

from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.jobs.models import Job, Estimate, EstimateLineItem
from apps.contacts.models import Contact
from apps.core.models import Configuration
from apps.invoicing.models import PriceListItem


class EstimateLineItemAdditionTests(TestCase):
    """Test adding line items to estimates via both manual entry and price list."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        # Create a test contact
        self.contact = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='test@example.com'
        )

        # Create a job
        self.job = Job.objects.create(
            job_number='TEST001',
            description='Test Job',
            contact=self.contact
        )

        # Create an estimate
        self.estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-TEST-001',
            version=1,
            status='draft'
        )

        # Create a price list item
        self.price_list_item = PriceListItem.objects.create(
            code='ITEM001',
            units='each',
            description='Test Price List Item',
            purchase_price=Decimal('10.00'),
            selling_price=Decimal('15.00'),
            qty_on_hand=Decimal('100.00')
        )

    def test_get_add_line_item_page(self):
        """Test GET request to add line item page shows both forms."""
        url = reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Manual Entry')
        self.assertContains(response, 'From Price List')
        self.assertContains(response, 'manual_submit')
        self.assertContains(response, 'pricelist_submit')

    def test_add_manual_line_item(self):
        """Test adding a manual line item via POST."""
        url = reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id])

        form_data = {
            'description': 'Custom line item',
            'qty': '5.00',
            'units': 'hours',
            'price_currency': '75.50',
            'manual_submit': 'Add Manual Line Item'
        }

        response = self.client.post(url, data=form_data)

        # Should redirect to estimate detail page
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('jobs:estimate_detail', args=[self.estimate.estimate_id]))

        # Check line item was created
        line_item = EstimateLineItem.objects.filter(estimate=self.estimate).first()
        self.assertIsNotNone(line_item)
        self.assertEqual(line_item.description, 'Custom line item')
        self.assertEqual(line_item.qty, Decimal('5.00'))
        self.assertEqual(line_item.units, 'hours')
        self.assertEqual(line_item.price_currency, Decimal('75.50'))
        self.assertIsNone(line_item.task)
        self.assertIsNone(line_item.price_list_item)

    def test_add_pricelist_line_item(self):
        """Test adding a line item from price list via POST."""
        url = reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id])

        form_data = {
            'price_list_item': str(self.price_list_item.price_list_item_id),
            'qty': '10.00',
            'pricelist_submit': 'Add from Price List'
        }

        response = self.client.post(url, data=form_data)

        # Should redirect to estimate detail page
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('jobs:estimate_detail', args=[self.estimate.estimate_id]))

        # Check line item was created
        line_item = EstimateLineItem.objects.filter(estimate=self.estimate).first()
        self.assertIsNotNone(line_item)

        # Verify values were copied from price list item
        self.assertEqual(line_item.description, self.price_list_item.description)
        self.assertEqual(line_item.units, self.price_list_item.units)
        self.assertEqual(line_item.price_currency, self.price_list_item.selling_price)

        # Verify qty came from form, not from price list item
        self.assertEqual(line_item.qty, Decimal('10.00'))

        # Verify price_list_item reference is set
        self.assertEqual(line_item.price_list_item, self.price_list_item)

        # Verify task is not set
        self.assertIsNone(line_item.task)

    def test_add_manual_line_item_missing_required_fields(self):
        """Test adding a manual line item with missing required fields shows errors."""
        url = reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id])

        form_data = {
            'description': '',  # Missing description
            'qty': '',  # Missing qty
            'units': 'hours',
            'price_currency': '',  # Missing price
            'manual_submit': 'Add Manual Line Item'
        }

        response = self.client.post(url, data=form_data)

        # Should NOT redirect (form errors)
        self.assertEqual(response.status_code, 200)

        # No line item should be created
        line_items = EstimateLineItem.objects.filter(estimate=self.estimate)
        self.assertEqual(line_items.count(), 0)

    def test_add_pricelist_line_item_missing_qty(self):
        """Test adding a price list line item with missing qty shows errors."""
        url = reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id])

        form_data = {
            'price_list_item': str(self.price_list_item.price_list_item_id),
            'qty': '',  # Missing qty
            'pricelist_submit': 'Add from Price List'
        }

        response = self.client.post(url, data=form_data)

        # Should NOT redirect (form errors)
        self.assertEqual(response.status_code, 200)

        # No line item should be created
        line_items = EstimateLineItem.objects.filter(estimate=self.estimate)
        self.assertEqual(line_items.count(), 0)

    def test_cannot_add_line_item_to_superseded_estimate(self):
        """Test that line items cannot be added to superseded estimates."""
        # First transition estimate to open (valid transition from draft)
        self.estimate.status = 'open'
        self.estimate.save()

        # Create a revision, which marks the parent as superseded
        url_revise = reverse('jobs:estimate_revise', args=[self.estimate.estimate_id])
        response = self.client.post(url_revise)

        # Get the superseded estimate
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, 'superseded')

        url = reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id])

        form_data = {
            'description': 'Should not be added',
            'qty': '1.00',
            'units': 'each',
            'price_currency': '10.00',
            'manual_submit': 'Add Manual Line Item'
        }

        response = self.client.post(url, data=form_data)

        # Should redirect to estimate detail (with error message)
        self.assertEqual(response.status_code, 302)

        # No line item should be created on the superseded estimate
        line_items = EstimateLineItem.objects.filter(estimate=self.estimate)
        self.assertEqual(line_items.count(), 0)

    def test_multiple_line_items_can_be_added(self):
        """Test that multiple line items can be added to an estimate."""
        url = reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id])

        # Add first manual line item
        form_data_1 = {
            'description': 'First item',
            'qty': '1.00',
            'units': 'each',
            'price_currency': '100.00',
            'manual_submit': 'Add Manual Line Item'
        }
        self.client.post(url, data=form_data_1)

        # Add second line item from price list
        form_data_2 = {
            'price_list_item': str(self.price_list_item.price_list_item_id),
            'qty': '2.00',
            'pricelist_submit': 'Add from Price List'
        }
        self.client.post(url, data=form_data_2)

        # Check both line items were created
        line_items = EstimateLineItem.objects.filter(estimate=self.estimate).order_by('line_item_id')
        self.assertEqual(line_items.count(), 2)

        # Verify first is manual
        self.assertEqual(line_items[0].description, 'First item')
        self.assertIsNone(line_items[0].price_list_item)

        # Verify second is from price list
        self.assertEqual(line_items[1].price_list_item, self.price_list_item)

    def test_line_item_total_amount_calculation(self):
        """Test that line item total amount is calculated correctly."""
        url = reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id])

        # Add line item with qty and price
        form_data = {
            'description': 'Test item',
            'qty': '3.00',
            'units': 'hours',
            'price_currency': '50.00',
            'manual_submit': 'Add Manual Line Item'
        }

        self.client.post(url, data=form_data)

        # Check total_amount property
        line_item = EstimateLineItem.objects.filter(estimate=self.estimate).first()
        expected_total = Decimal('3.00') * Decimal('50.00')
        self.assertEqual(line_item.total_amount, expected_total)


class EstimateLineItemDeletionTests(TestCase):
    """Test deleting line items and renumbering behavior."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        # Create a test contact
        self.contact = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='test@example.com'
        )

        # Create a job
        self.job = Job.objects.create(
            job_number='TEST001',
            description='Test Job',
            contact=self.contact
        )

        # Create an estimate
        self.estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-TEST-001',
            version=1,
            status='draft'
        )

    def test_delete_line_item(self):
        """Test deleting a single line item."""
        # Create a line item
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Test item',
            qty=Decimal('1.00'),
            units='each',
            price_currency=Decimal('10.00')
        )

        url = reverse('jobs:estimate_delete_line_item', args=[self.estimate.estimate_id, line_item.line_item_id])
        response = self.client.post(url)

        # Should redirect to estimate detail
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('jobs:estimate_detail', args=[self.estimate.estimate_id]))

        # Line item should be deleted
        self.assertFalse(EstimateLineItem.objects.filter(line_item_id=line_item.line_item_id).exists())

    def test_delete_middle_item_renumbers_correctly(self):
        """Test that deleting a middle item renumbers remaining items."""
        # Create 3 line items
        item1 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Item 1',
            qty=Decimal('1.00'),
            units='each',
            price_currency=Decimal('10.00')
        )
        item2 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Item 2',
            qty=Decimal('2.00'),
            units='each',
            price_currency=Decimal('20.00')
        )
        item3 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Item 3',
            qty=Decimal('3.00'),
            units='each',
            price_currency=Decimal('30.00')
        )

        # Verify initial line numbers
        item1.refresh_from_db()
        item2.refresh_from_db()
        item3.refresh_from_db()
        self.assertEqual(item1.line_number, 1)
        self.assertEqual(item2.line_number, 2)
        self.assertEqual(item3.line_number, 3)

        # Delete item 2
        url = reverse('jobs:estimate_delete_line_item', args=[self.estimate.estimate_id, item2.line_item_id])
        response = self.client.post(url)

        # Item 2 should be deleted
        self.assertFalse(EstimateLineItem.objects.filter(line_item_id=item2.line_item_id).exists())

        # Item 3 should now be line #2
        item3.refresh_from_db()
        self.assertEqual(item3.line_number, 2)

        # Item 1 should still be line #1
        item1.refresh_from_db()
        self.assertEqual(item1.line_number, 1)

        # Total items should be 2
        remaining_items = EstimateLineItem.objects.filter(estimate=self.estimate)
        self.assertEqual(remaining_items.count(), 2)

    def test_delete_first_item_renumbers_correctly(self):
        """Test that deleting the first item renumbers remaining items."""
        # Create 3 line items
        item1 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Item 1',
            qty=Decimal('1.00'),
            units='each',
            price_currency=Decimal('10.00')
        )
        item2 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Item 2',
            qty=Decimal('2.00'),
            units='each',
            price_currency=Decimal('20.00')
        )
        item3 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Item 3',
            qty=Decimal('3.00'),
            units='each',
            price_currency=Decimal('30.00')
        )

        # Delete item 1
        url = reverse('jobs:estimate_delete_line_item', args=[self.estimate.estimate_id, item1.line_item_id])
        response = self.client.post(url)

        # Item 1 should be deleted
        self.assertFalse(EstimateLineItem.objects.filter(line_item_id=item1.line_item_id).exists())

        # Item 2 should now be line #1
        item2.refresh_from_db()
        self.assertEqual(item2.line_number, 1)

        # Item 3 should now be line #2
        item3.refresh_from_db()
        self.assertEqual(item3.line_number, 2)

    def test_delete_last_item_no_renumbering_needed(self):
        """Test that deleting the last item doesn't affect other items."""
        # Create 3 line items
        item1 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Item 1',
            qty=Decimal('1.00'),
            units='each',
            price_currency=Decimal('10.00')
        )
        item2 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Item 2',
            qty=Decimal('2.00'),
            units='each',
            price_currency=Decimal('20.00')
        )
        item3 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Item 3',
            qty=Decimal('3.00'),
            units='each',
            price_currency=Decimal('30.00')
        )

        # Delete item 3
        url = reverse('jobs:estimate_delete_line_item', args=[self.estimate.estimate_id, item3.line_item_id])
        response = self.client.post(url)

        # Item 3 should be deleted
        self.assertFalse(EstimateLineItem.objects.filter(line_item_id=item3.line_item_id).exists())

        # Item 1 and 2 should remain unchanged
        item1.refresh_from_db()
        item2.refresh_from_db()
        self.assertEqual(item1.line_number, 1)
        self.assertEqual(item2.line_number, 2)

    def test_cannot_delete_from_superseded_estimate(self):
        """Test that line items cannot be deleted from superseded estimates."""
        # Create a line item
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Test item',
            qty=Decimal('1.00'),
            units='each',
            price_currency=Decimal('10.00')
        )

        # Mark estimate as open first (valid transition)
        self.estimate.status = 'open'
        self.estimate.save()

        # Create a revision (marks parent as superseded)
        url_revise = reverse('jobs:estimate_revise', args=[self.estimate.estimate_id])
        self.client.post(url_revise)

        # Refresh to get superseded status
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, 'superseded')

        # Try to delete the line item
        url = reverse('jobs:estimate_delete_line_item', args=[self.estimate.estimate_id, line_item.line_item_id])
        response = self.client.post(url)

        # Should redirect
        self.assertEqual(response.status_code, 302)

        # Line item should still exist
        self.assertTrue(EstimateLineItem.objects.filter(line_item_id=line_item.line_item_id).exists())

    def test_sequential_deletions_maintain_numbering(self):
        """Test that multiple sequential deletions maintain correct numbering."""
        # Create 5 line items
        items = []
        for i in range(1, 6):
            item = EstimateLineItem.objects.create(
                estimate=self.estimate,
                description=f'Item {i}',
                qty=Decimal('1.00'),
                units='each',
                price_currency=Decimal('10.00')
            )
            items.append(item)

        # Delete item 2
        url = reverse('jobs:estimate_delete_line_item', args=[self.estimate.estimate_id, items[1].line_item_id])
        self.client.post(url)

        # Delete item 4 (which should now be #3 after first deletion)
        url = reverse('jobs:estimate_delete_line_item', args=[self.estimate.estimate_id, items[3].line_item_id])
        self.client.post(url)

        # Check remaining items are numbered 1, 2, 3
        remaining_items = EstimateLineItem.objects.filter(estimate=self.estimate).order_by('line_number')
        self.assertEqual(remaining_items.count(), 3)

        line_numbers = [item.line_number for item in remaining_items]
        self.assertEqual(line_numbers, [1, 2, 3])

    def test_delete_action_column_only_shown_for_draft(self):
        """Test that delete action column only shows for draft estimates."""
        # Create a line item
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Test item',
            qty=Decimal('1.00'),
            units='each',
            price_currency=Decimal('10.00')
        )

        # Check draft estimate shows delete button
        url = reverse('jobs:estimate_detail', args=[self.estimate.estimate_id])
        response = self.client.get(url)
        self.assertContains(response, 'Actions')
        self.assertContains(response, 'Delete')

        # Change to open status
        self.estimate.status = 'open'
        self.estimate.save()

        # Check open estimate doesn't show delete button
        response = self.client.get(url)
        self.assertNotContains(response, 'Actions')
        self.assertNotContains(response, 'type="submit" onclick="return confirm')
