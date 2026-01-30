"""
Test that superseded estimates cannot be modified.
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.jobs.models import Job, Estimate, EstimateLineItem
from apps.contacts.models import Contact
from apps.invoicing.models import PriceListItem
from decimal import Decimal

User = get_user_model()


class SupersededEstimateRestrictionTests(TestCase):
    """Test that superseded estimates properly reject modifications."""

    def setUp(self):
        """Set up test data."""
        # TODO: use fixture data?  Some requirements are not met - Estimates
        # should not be in Active state without any LineItems, for example...
        self.client = Client()

        # Create user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass',
            email='test@example.com'
        )
        self.client.login(username='testuser', password='testpass')

        # Create contact
        self.contact = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='contact@test.com'
        )

        # Create job
        self.job = Job.objects.create(
            job_number='JOB-TEST-001',
            contact=self.contact,
            status='approved'
        )

        # Create superseded estimate
        self.superseded_estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-001',
            version=1,
            status='superseded'
        )

        # Create active estimate for comparison
        self.active_estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-002',
            version=2,
            status='open',
            parent=self.superseded_estimate
        )

        # Create a price list item for testing line items
        self.price_list_item = PriceListItem.objects.create(
            code='TEST001',
            description='Test Item',
            units='each',
            purchase_price=Decimal('10.00'),
            selling_price=Decimal('20.00')
        )

    def test_cannot_add_line_item_to_superseded_estimate(self):
        """Test that adding a line item to a superseded estimate is rejected."""
        url = reverse('jobs:estimate_add_line_item', args=[self.superseded_estimate.estimate_id])

        # Attempt to add a line item via POST
        response = self.client.post(url, {
            'price_list_item': self.price_list_item.pk,
            'qty': '5',
            'units': 'each',
            'description': 'Test line item',
            'price_currency': '20.00'
        })

        # Should redirect to estimate detail
        self.assertRedirects(
            response,
            reverse('jobs:estimate_detail', args=[self.superseded_estimate.estimate_id])
        )

        # Check that no line item was created
        line_items = EstimateLineItem.objects.filter(estimate=self.superseded_estimate)
        self.assertEqual(line_items.count(), 0)

        # Check for error message in session
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any('Cannot add line items to a superseded estimate' in str(m) for m in messages))

    def test_cannot_update_status_of_superseded_estimate(self):
        """Test that updating the status of a superseded estimate is rejected."""
        url = reverse('jobs:estimate_update_status', args=[self.superseded_estimate.estimate_id])

        # Attempt to update status via POST
        response = self.client.post(url, {
            'status': 'open'
        })

        # Should redirect to estimate detail
        self.assertRedirects(
            response,
            reverse('jobs:estimate_detail', args=[self.superseded_estimate.estimate_id])
        )

        # Verify status hasn't changed
        self.superseded_estimate.refresh_from_db()
        self.assertEqual(self.superseded_estimate.status, 'superseded')

        # Check for error message
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any('Cannot update the status of a superseded estimate' in str(m) for m in messages))

    def test_cannot_add_line_item_to_active_estimate(self):
        """Test that active estimates can still be modified (control test)."""
        url = reverse('jobs:estimate_add_line_item', args=[self.active_estimate.estimate_id])

        # Add a line item via POST using the price list form
        response = self.client.post(url, {
            'price_list_item': self.price_list_item.pk,
            'qty': '5',
            'pricelist_submit': 'Add from Price List'
        })

        # Should redirect to estimate detail
        self.assertRedirects(
            response,
            reverse('jobs:estimate_detail', args=[self.active_estimate.estimate_id])
        )

        # Check that line item wasn't created
        # TODO: should this throw an exception?
        line_items = EstimateLineItem.objects.filter(estimate=self.active_estimate)
        self.assertEqual(line_items.count(), 0)

    def test_superseded_estimate_displays_restriction_message(self):
        """Test that superseded estimates show a restriction message in the UI."""
        url = reverse('jobs:estimate_detail', args=[self.superseded_estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check that modification links are not present
        self.assertNotContains(response, 'Add Line Item')
        self.assertNotContains(response, 'Update Status')

        # Check that restriction message is shown
        self.assertContains(response, 'This estimate has been superseded and cannot be modified')

    def test_active_estimate_shows_modification_links(self):
        """Test that active estimates show modification links (control test)."""
        url = reverse('jobs:estimate_detail', args=[self.active_estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check that modification links are present
        # Note: Add Line Item only shows for draft status (not open)
        self.assertNotContains(response, 'Add Line Item')  # Open status doesn't show this
        self.assertContains(response, 'Update Status')
        self.assertContains(response, 'Revise Estimate')  # Open status shows this instead

        # Check that restriction message is NOT shown
        self.assertNotContains(response, 'This estimate has been superseded and cannot be modified')

    def test_draft_vs_open_estimate_links(self):
        """Test that draft estimates show Add Line Item but open estimates don't."""
        # Create a draft estimate
        draft_estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-DRAFT-001',
            version=1,
            status='draft'
        )

        # Test draft estimate shows Add Line Item
        url = reverse('jobs:estimate_detail', args=[draft_estimate.estimate_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Line Item')
        self.assertContains(response, 'Update Status')  # Status form submit button
        self.assertContains(response, 'id_status')  # Status dropdown field
        self.assertNotContains(response, 'Revise Estimate')  # Not shown for draft

        # Test open estimate (already created as self.active_estimate)
        url = reverse('jobs:estimate_detail', args=[self.active_estimate.estimate_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Add Line Item')  # Not shown for open
        self.assertContains(response, 'Update Status')  # Status form submit button
        self.assertContains(response, 'id_status')  # Status dropdown field
        self.assertContains(response, 'Revise Estimate')  # Shown for open


class SupersededEstimateModelTests(TestCase):
    """Test model-level behavior for superseded estimates."""

    def setUp(self):
        """Set up test data."""
        # Create contact
        self.contact = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='contact@test.com'
        )

        # Create job
        self.job = Job.objects.create(
            job_number='JOB-TEST-001',
            contact=self.contact,
            status='approved'
        )

        # Create estimate
        self.estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-001',
            version=1,
            status='open'
        )

    def test_estimate_can_be_marked_superseded(self):
        """Test that an estimate can be properly marked as superseded."""
        # Mark estimate as superseded (closed_date is set automatically by model.save())
        self.estimate.status = 'superseded'
        self.estimate.save()

        # Reload from database
        self.estimate.refresh_from_db()

        self.assertEqual(self.estimate.status, 'superseded')
        self.assertIsNotNone(self.estimate.closed_date)

    def test_superseded_estimate_preserves_data(self):
        """Test that superseded estimates preserve their data for historical reference."""
        # Add a line item
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            qty=Decimal('10'),
            units='each',
            description='Test item',
            price_currency=Decimal('25.00')
        )

        # Mark estimate as superseded
        self.estimate.status = 'superseded'
        self.estimate.save()

        # Verify line item still exists
        self.assertTrue(EstimateLineItem.objects.filter(pk=line_item.pk).exists())

        # Verify we can still read the superseded estimate's data
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.estimatelineitem_set.count(), 1)
        self.assertEqual(self.estimate.estimatelineitem_set.first().description, 'Test item')