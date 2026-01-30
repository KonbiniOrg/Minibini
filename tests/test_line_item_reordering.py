from django.test import TestCase
from django.urls import reverse
from decimal import Decimal
from apps.jobs.models import Estimate, EstimateLineItem, Job
from apps.contacts.models import Contact, Business
from apps.core.models import User


class EstimateLineItemReorderingTestCase(TestCase):
    """Test reordering of line items within Estimates"""

    def setUp(self):
        """Set up test data"""
        # Create a user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )

        # Create a default contact (must be created before business)
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')

        # Create a business and contact
        self.business = Business.objects.create(
            business_name='Test Company',
            business_phone='12-3456789',
            default_contact=self.default_contact
        )
        self.contact = Contact.objects.create(
            first_name='John Doe',
            last_name='',
            email='john@example.com',
            business=self.business
        )

        # Create a job
        self.job = Job.objects.create(
            job_number='JOB-001',
            name='Test Job',
            contact=self.contact,
            status='draft'
        )

        # Create an estimate
        self.estimate = Estimate.objects.create(
            estimate_number='EST-001',
            job=self.job,
            status='draft',
            version=1
        )

        # Create multiple line items for the estimate
        self.line_item1 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Line Item 1',
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00'),
            units='hours'
        )
        self.line_item2 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Line Item 2',
            qty=Decimal('2.00'),
            price_currency=Decimal('200.00'),
            units='hours'
        )
        self.line_item3 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Line Item 3',
            qty=Decimal('3.00'),
            price_currency=Decimal('300.00'),
            units='hours'
        )

    def test_line_items_have_line_numbers(self):
        """Test that line items are automatically assigned line numbers"""
        self.assertIsNotNone(self.line_item1.line_number)
        self.assertIsNotNone(self.line_item2.line_number)
        self.assertIsNotNone(self.line_item3.line_number)
        self.assertEqual(self.line_item1.line_number, 1)
        self.assertEqual(self.line_item2.line_number, 2)
        self.assertEqual(self.line_item3.line_number, 3)

    def test_reorder_line_item_down(self):
        """Test moving a line item down in the estimate"""
        url = reverse('jobs:estimate_reorder_line_item', kwargs={
            'estimate_id': self.estimate.estimate_id,
            'line_item_id': self.line_item1.line_item_id,
            'direction': 'down'
        })
        response = self.client.post(url)

        # Should redirect back to estimate detail
        self.assertEqual(response.status_code, 302)

        # Refresh line items from database
        self.line_item1.refresh_from_db()
        self.line_item2.refresh_from_db()

        # Line item 1 should now have line_number 2, Line item 2 should have line_number 1
        self.assertEqual(self.line_item1.line_number, 2)
        self.assertEqual(self.line_item2.line_number, 1)

    def test_reorder_line_item_up(self):
        """Test moving a line item up in the estimate"""
        url = reverse('jobs:estimate_reorder_line_item', kwargs={
            'estimate_id': self.estimate.estimate_id,
            'line_item_id': self.line_item2.line_item_id,
            'direction': 'up'
        })
        response = self.client.post(url)

        # Should redirect back to estimate detail
        self.assertEqual(response.status_code, 302)

        # Refresh line items from database
        self.line_item1.refresh_from_db()
        self.line_item2.refresh_from_db()

        # Line item 2 should now have line_number 1, Line item 1 should have line_number 2
        self.assertEqual(self.line_item2.line_number, 1)
        self.assertEqual(self.line_item1.line_number, 2)

    def test_cannot_move_first_line_item_up(self):
        """Test that first line item cannot be moved up"""
        url = reverse('jobs:estimate_reorder_line_item', kwargs={
            'estimate_id': self.estimate.estimate_id,
            'line_item_id': self.line_item1.line_item_id,
            'direction': 'up'
        })
        response = self.client.post(url)

        # Should redirect back
        self.assertEqual(response.status_code, 302)

        # Refresh line item from database
        self.line_item1.refresh_from_db()

        # Line item 1 should still have line_number 1
        self.assertEqual(self.line_item1.line_number, 1)

    def test_cannot_move_last_line_item_down(self):
        """Test that last line item cannot be moved down"""
        url = reverse('jobs:estimate_reorder_line_item', kwargs={
            'estimate_id': self.estimate.estimate_id,
            'line_item_id': self.line_item3.line_item_id,
            'direction': 'down'
        })
        response = self.client.post(url)

        # Should redirect back
        self.assertEqual(response.status_code, 302)

        # Refresh line item from database
        self.line_item3.refresh_from_db()

        # Line item 3 should still have line_number 3
        self.assertEqual(self.line_item3.line_number, 3)

    def test_cannot_reorder_non_draft_estimate(self):
        """Test that line items in non-draft estimates cannot be reordered"""
        # Mark estimate as open
        self.estimate.status = 'open'
        self.estimate.save()

        url = reverse('jobs:estimate_reorder_line_item', kwargs={
            'estimate_id': self.estimate.estimate_id,
            'line_item_id': self.line_item1.line_item_id,
            'direction': 'down'
        })
        response = self.client.post(url)

        # Should redirect back
        self.assertEqual(response.status_code, 302)

        # Refresh line item from database
        self.line_item1.refresh_from_db()

        # Line item 1 should still have original line_number
        self.assertEqual(self.line_item1.line_number, 1)

    def test_multiple_reorders(self):
        """Test multiple sequential reorders"""
        # Move item 1 down
        url = reverse('jobs:estimate_reorder_line_item', kwargs={
            'estimate_id': self.estimate.estimate_id,
            'line_item_id': self.line_item1.line_item_id,
            'direction': 'down'
        })
        self.client.post(url)

        # Move item 1 down again
        self.client.post(url)

        # Refresh all line items
        self.line_item1.refresh_from_db()
        self.line_item2.refresh_from_db()
        self.line_item3.refresh_from_db()

        # After two moves down, item 1 should be at position 3
        self.assertEqual(self.line_item1.line_number, 3)
        # Item 3 should now be at position 2
        self.assertEqual(self.line_item3.line_number, 2)
        # Item 2 should now be at position 1
        self.assertEqual(self.line_item2.line_number, 1)

    def test_line_item_total_amount(self):
        """Test that line item total_amount property works correctly"""
        # This is just to ensure the line items are working properly
        self.assertEqual(self.line_item1.total_amount, Decimal('100.00'))
        self.assertEqual(self.line_item2.total_amount, Decimal('400.00'))
        self.assertEqual(self.line_item3.total_amount, Decimal('900.00'))
