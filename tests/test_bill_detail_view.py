"""
Tests for Bill detail view with status update functionality.
"""

from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.purchasing.models import Bill, PurchaseOrder, BillLineItem
from apps.contacts.models import Contact, Business


class BillDetailViewTest(TestCase):
    """Test suite for Bill detail view with status update form."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create default contact for business
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')

        # Create a test business
        self.business = Business.objects.create(
            business_name='Test Vendor Business',
            default_contact=self.default_contact
        )

        # Create a test contact
        self.contact = Contact.objects.create(
            first_name='Test Vendor',
            last_name='',
            email='test.vendor@test.com',
            business=self.business
        )

        # Create a test purchase order in issued status
        self.purchase_order = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-TEST-001',
            status='draft'
        )
        self.purchase_order.status = 'issued'
        self.purchase_order.save()

        # Create a test bill
        self.bill = Bill.objects.create(
            bill_number="BILL-001",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )

        # Add a line item to the bill so it can transition out of draft
        BillLineItem.objects.create(
            bill=self.bill,
            description="Test item",
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00')
        )

    def test_bill_detail_view_displays_status_form_for_non_terminal_status(self):
        """Test that bill detail view displays status update form for draft status."""
        url = reverse('purchasing:bill_detail', args=[self.bill.bill_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Draft')
        # Check that status_form is in context
        self.assertIn('status_form', response.context)
        self.assertIsNotNone(response.context['status_form'])
        # Check that the form is rendered
        self.assertContains(response, 'Update Status')
        self.assertContains(response, 'name="update_status"')

    def test_bill_detail_view_no_status_form_for_terminal_status(self):
        """Test that bill detail view does not display status form for terminal states."""
        # Transition bill to terminal state (cancelled)
        self.bill.status = 'received'
        self.bill.save()
        self.bill.status = 'cancelled'
        self.bill.save()

        url = reverse('purchasing:bill_detail', args=[self.bill.bill_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        # Check that status_form is None for terminal states
        self.assertIsNone(response.context.get('status_form'))
        # Check that the form is not rendered
        self.assertNotContains(response, 'name="update_status"')

    def test_bill_status_update_via_post(self):
        """Test that posting to bill detail view updates status."""
        url = reverse('purchasing:bill_detail', args=[self.bill.bill_id])

        # Post status update from draft to received
        response = self.client.post(url, {
            'update_status': '1',
            'status': 'received'
        }, follow=True)

        # Check redirect back to detail view
        self.assertRedirects(response, url)

        # Check that bill status was updated
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, 'received')

        # Check success message
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertIn('status updated', str(messages[0]).lower())

    def test_bill_status_update_invalid_transition(self):
        """Test that invalid status transitions show error message."""
        url = reverse('purchasing:bill_detail', args=[self.bill.bill_id])

        # Try to post invalid status transition (draft -> partly_paid)
        response = self.client.post(url, {
            'update_status': '1',
            'status': 'partly_paid'
        }, follow=True)

        # Check redirect back to detail view
        self.assertRedirects(response, url)

        # Check that bill status was NOT updated
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, 'draft')

        # Check error message
        messages = list(response.context['messages'])
        self.assertTrue(len(messages) >= 1)
        # Should have an error message about the invalid transition
        message_text = ' '.join([str(m) for m in messages])
        self.assertIn('error', message_text.lower())

    def test_bill_status_update_from_terminal_state_shows_error(self):
        """Test that attempting to update from terminal state shows error."""
        # Transition bill to terminal state
        self.bill.status = 'received'
        self.bill.save()
        self.bill.status = 'cancelled'
        self.bill.save()

        url = reverse('purchasing:bill_detail', args=[self.bill.bill_id])

        # Try to post status update from terminal state
        response = self.client.post(url, {
            'update_status': '1',
            'status': 'paid_in_full'
        }, follow=True)

        # Check redirect back to detail view
        self.assertRedirects(response, url)

        # Check that bill status was NOT updated
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, 'cancelled')

        # Check error message
        messages = list(response.context['messages'])
        self.assertTrue(len(messages) >= 1)
        message_text = ' '.join([str(m) for m in messages])
        self.assertIn('terminal', message_text.lower())

    def test_bill_status_choices_are_context_aware(self):
        """Test that status form only shows valid transitions for current status."""
        # Bill is in draft status
        url = reverse('purchasing:bill_detail', args=[self.bill.bill_id])
        response = self.client.get(url)

        # Status form should only show draft (current) and received (valid transition)
        status_form = response.context['status_form']
        choices = [choice[0] for choice in status_form.fields['status'].choices]

        self.assertIn('draft', choices)  # Current status
        self.assertIn('received', choices)  # Valid transition
        self.assertNotIn('partly_paid', choices)  # Invalid direct transition
        self.assertNotIn('paid_in_full', choices)  # Invalid direct transition
