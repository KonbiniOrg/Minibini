"""
Tests for contact deletion functionality.

This test suite covers:
- Validation preventing deletion of contacts associated with Jobs or Bills
- Successful deletion of contacts with no associations
- Automatic default contact reassignment when deleting the default
- Default contact clearing when deleting the last contact
"""

from django.test import TestCase, Client
from django.urls import reverse
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job
from apps.purchasing.models import Bill, PurchaseOrder


class ContactDeletionValidationTest(TestCase):
    """Test validation that prevents deletion of contacts with associations"""

    def setUp(self):
        self.client = Client()
        # Create contact first for default_contact
        self.contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )
        # Create business with default_contact
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.contact
        )
        # Link contact to business
        self.contact.business = self.business
        self.contact.save()

    def test_cannot_delete_contact_with_job(self):
        """Contact associated with a Job cannot be deleted"""
        # Create a job associated with the contact
        job = Job.objects.create(
            job_number='TEST-001',
            name='Test Job',
            contact=self.contact
        )

        url = reverse('contacts:delete_contact', args=[self.contact.contact_id])
        response = self.client.post(url)

        # Should redirect back to contact detail with error
        self.assertEqual(response.status_code, 302)

        # Contact should still exist
        self.assertTrue(Contact.objects.filter(contact_id=self.contact.contact_id).exists())

        # Follow redirect and check for error message
        response = self.client.post(url, follow=True)
        self.assertContains(response, 'Cannot delete contact')
        self.assertContains(response, 'Jobs:')
        self.assertContains(response, 'TEST-001')

    def test_cannot_delete_contact_with_bill(self):
        """Contact associated with a Bill cannot be deleted"""
        # Create a purchase order with issued status
        po = PurchaseOrder.objects.create(
            po_number='PO-001',
            business=self.business,
            status='issued'
        )

        # Create a bill associated with the contact
        bill = Bill.objects.create(
            purchase_order=po,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            bill_number='BILL-001'
        )

        url = reverse('contacts:delete_contact', args=[self.contact.contact_id])
        response = self.client.post(url, follow=True)

        # Should show error
        self.assertContains(response, 'Cannot delete contact')
        self.assertContains(response, 'Bills:')

        # Contact should still exist
        self.assertTrue(Contact.objects.filter(contact_id=self.contact.contact_id).exists())

    def test_cannot_delete_contact_with_completed_job(self):
        """Contact cannot be deleted even if job is completed.

        Due to PROTECT foreign key constraint, contacts with ANY jobs cannot be deleted
        regardless of job status.
        """
        # Create a completed job - still blocks deletion due to PROTECT
        job = Job.objects.create(
            job_number='TEST-COMPLETED',
            name='Completed Test Job',
            contact=self.contact,
            status='completed'
        )

        url = reverse('contacts:delete_contact', args=[self.contact.contact_id])
        response = self.client.post(url, follow=True)

        # Should show error
        self.assertContains(response, 'Cannot delete contact')
        self.assertContains(response, 'Jobs:')
        self.assertContains(response, 'TEST-COMPLETED')

        # Contact should still exist
        self.assertTrue(Contact.objects.filter(contact_id=self.contact.contact_id).exists())

    def test_cannot_delete_contact_with_multiple_associations(self):
        """Contact with multiple associations should show all in error message"""
        # Create both a job and a bill
        job = Job.objects.create(
            job_number='TEST-001',
            name='Test Job',
            contact=self.contact
        )

        po = PurchaseOrder.objects.create(
            po_number='PO-001',
            business=self.business,
            status='issued'
        )
        bill = Bill.objects.create(
            purchase_order=po,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            bill_number='BILL-001'
        )

        url = reverse('contacts:delete_contact', args=[self.contact.contact_id])
        response = self.client.post(url, follow=True)

        # Should show error with both associations
        self.assertContains(response, 'Cannot delete contact')
        self.assertContains(response, 'Jobs:')
        self.assertContains(response, 'TEST-001')
        self.assertContains(response, 'Bills:')

        # Contact should still exist
        self.assertTrue(Contact.objects.filter(contact_id=self.contact.contact_id).exists())


class ContactDeletionSuccessTest(TestCase):
    """Test successful contact deletion scenarios"""

    def setUp(self):
        self.client = Client()

    def test_delete_contact_with_no_associations(self):
        """Contact with no associations can be deleted successfully"""
        contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )

        contact_id = contact.contact_id
        url = reverse('contacts:delete_contact', args=[contact_id])
        response = self.client.post(url)

        # Should redirect to contact list
        self.assertEqual(response.status_code, 302)

        # Contact should be deleted
        self.assertFalse(Contact.objects.filter(contact_id=contact_id).exists())

    def test_delete_contact_with_business_no_other_associations(self):
        """Contact with business but no Jobs/Bills can be deleted"""
        # Create contact first for default_contact
        contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )
        # Create business with default_contact
        business = Business.objects.create(
            business_name='Test Business',
            default_contact=contact
        )
        # Link contact to business
        contact.business = business
        contact.save()

        # Add a second contact so we can delete the first one
        contact2 = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0002',
            business=business
        )

        contact_id = contact.contact_id
        url = reverse('contacts:delete_contact', args=[contact_id])
        response = self.client.post(url)

        # Should redirect to business detail
        self.assertEqual(response.status_code, 302)

        # Contact should be deleted
        self.assertFalse(Contact.objects.filter(contact_id=contact_id).exists())

    def test_delete_redirects_to_business_detail_when_has_business(self):
        """Deleting contact with business should redirect to business detail"""
        # Create contact first for default_contact
        contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )
        # Create business with default_contact
        business = Business.objects.create(
            business_name='Test Business',
            default_contact=contact
        )
        # Link contact to business
        contact.business = business
        contact.save()

        # Add a second contact so we can delete the first one
        contact2 = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0002',
            business=business
        )

        url = reverse('contacts:delete_contact', args=[contact.contact_id])
        response = self.client.post(url)

        expected_redirect = reverse('contacts:business_detail', args=[business.business_id])
        self.assertRedirects(response, expected_redirect)

    def test_delete_redirects_to_contact_list_when_no_business(self):
        """Deleting contact without business should redirect to contact list"""
        contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )

        url = reverse('contacts:delete_contact', args=[contact.contact_id])
        response = self.client.post(url)

        expected_redirect = reverse('contacts:contact_list')
        self.assertRedirects(response, expected_redirect)

    def test_get_request_does_not_delete(self):
        """GET request to delete_contact should not delete the contact"""
        contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )

        url = reverse('contacts:delete_contact', args=[contact.contact_id])
        response = self.client.get(url)

        # Should redirect without deleting
        self.assertEqual(response.status_code, 302)

        # Contact should still exist
        self.assertTrue(Contact.objects.filter(contact_id=contact.contact_id).exists())


class DefaultContactReassignmentOnDeletionTest(TestCase):
    """Test automatic default contact reassignment when deleting default"""

    def setUp(self):
        self.client = Client()
        # Create initial contact for default_contact (not linked to business)
        # This allows tests to add their own contacts to the business without interference
        initial_contact = Contact.objects.create(
            first_name='Initial',
            last_name='Contact',
            email='initial@test.com',
            work_number='555-0000'
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=initial_contact
        )
        # Note: initial_contact.business is NOT set, so business.contacts.all() is empty
        # Tests can add contacts to the business as needed

    def test_delete_default_contact_shows_selection_form(self):
        """Deleting default contact with multiple others should show selection form"""
        # Create contacts
        contact_alice = Contact.objects.create(
            first_name='Alice',
            last_name='Alpha',
            email='alice@test.com',
            work_number='555-0001',
            business=self.business
        )

        contact_bob = Contact.objects.create(
            first_name='Bob',
            last_name='Beta',
            email='bob@test.com',
            work_number='555-0002',
            business=self.business
        )

        contact_charlie = Contact.objects.create(
            first_name='Charlie',
            last_name='Gamma',
            email='charlie@test.com',
            work_number='555-0003',
            business=self.business
        )

        # Set Alice as default manually
        self.business.default_contact = contact_alice
        self.business.save()

        # Try to delete Alice without selecting new default
        url = reverse('contacts:delete_contact', args=[contact_alice.contact_id])
        response = self.client.post(url)

        # Should show selection form (200 response, not redirect)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select New Default Contact')
        self.assertContains(response, 'Bob Beta')
        self.assertContains(response, 'Charlie Gamma')

        # Contact should not be deleted yet
        self.assertTrue(Contact.objects.filter(contact_id=contact_alice.contact_id).exists())

    def test_delete_default_contact_with_selection(self):
        """Deleting default contact with new default selected should work"""
        # Create contacts
        contact_alice = Contact.objects.create(
            first_name='Alice',
            last_name='Alpha',
            email='alice@test.com',
            work_number='555-0001',
            business=self.business
        )

        contact_bob = Contact.objects.create(
            first_name='Bob',
            last_name='Beta',
            email='bob@test.com',
            work_number='555-0002',
            business=self.business
        )

        contact_charlie = Contact.objects.create(
            first_name='Charlie',
            last_name='Gamma',
            email='charlie@test.com',
            work_number='555-0003',
            business=self.business
        )

        # Set Alice as default
        self.business.default_contact = contact_alice
        self.business.save()

        # Delete Alice with Bob selected as new default
        url = reverse('contacts:delete_contact', args=[contact_alice.contact_id])
        response = self.client.post(url, {'new_default_contact': contact_bob.contact_id})

        # Should redirect
        self.assertEqual(response.status_code, 302)

        # Alice should be deleted
        self.assertFalse(Contact.objects.filter(contact_id=contact_alice.contact_id).exists())

        # Bob should be new default
        self.business.refresh_from_db()
        self.assertEqual(self.business.default_contact, contact_bob)

    def test_delete_default_with_one_remaining_auto_assigns(self):
        """Deleting default with only one other contact should auto-assign remaining contact"""
        contact_alice = Contact.objects.create(
            first_name='Alice',
            last_name='Alpha',
            email='alice@test.com',
            work_number='555-0001',
            business=self.business
        )

        contact_bob = Contact.objects.create(
            first_name='Bob',
            last_name='Beta',
            email='bob@test.com',
            work_number='555-0002',
            business=self.business
        )

        # Set Alice as default
        self.business.default_contact = contact_alice
        self.business.save()

        # Delete Alice (only Bob remains)
        url = reverse('contacts:delete_contact', args=[contact_alice.contact_id])
        response = self.client.post(url)

        # Should redirect (no selection needed)
        self.assertEqual(response.status_code, 302)

        # Alice should be deleted
        self.assertFalse(Contact.objects.filter(contact_id=contact_alice.contact_id).exists())

        # Bob should be auto-assigned as default
        self.business.refresh_from_db()
        self.assertEqual(self.business.default_contact, contact_bob)

    def test_delete_only_contact_shows_error(self):
        """Deleting the only contact of a business should show an error"""
        contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001',
            business=self.business
        )

        self.business.refresh_from_db()
        self.assertEqual(self.business.default_contact, contact)

        # Try to delete the only contact
        url = reverse('contacts:delete_contact', args=[contact.contact_id])
        response = self.client.post(url, follow=True)

        # Should show error message
        self.assertContains(response, 'Cannot delete')
        self.assertContains(response, 'only contact')
        self.assertContains(response, 'A business must have at least one contact')

        # Contact should still exist
        self.assertTrue(Contact.objects.filter(contact_id=contact.contact_id).exists())

        # Business should still have the contact
        self.assertEqual(self.business.contacts.count(), 1)

    def test_delete_non_default_contact_preserves_default(self):
        """Deleting a non-default contact should not change the default"""
        contact1 = Contact.objects.create(
            first_name='Alice',
            last_name='Alpha',
            email='alice@test.com',
            work_number='555-0001',
            business=self.business
        )

        contact2 = Contact.objects.create(
            first_name='Bob',
            last_name='Beta',
            email='bob@test.com',
            work_number='555-0002',
            business=self.business
        )

        self.business.refresh_from_db()
        original_default = self.business.default_contact

        # Delete the non-default contact
        url = reverse('contacts:delete_contact', args=[contact2.contact_id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)

        # Default should remain unchanged
        self.business.refresh_from_db()
        self.assertEqual(self.business.default_contact, original_default)

    def test_delete_default_success_message_shows_new_default(self):
        """Success message should indicate which contact is now the default"""
        contact1 = Contact.objects.create(
            first_name='Alice',
            last_name='Alpha',
            email='alice@test.com',
            work_number='555-0001',
            business=self.business
        )

        contact2 = Contact.objects.create(
            first_name='Bob',
            last_name='Beta',
            email='bob@test.com',
            work_number='555-0002',
            business=self.business
        )

        contact3 = Contact.objects.create(
            first_name='Charlie',
            last_name='Gamma',
            email='charlie@test.com',
            work_number='555-0003',
            business=self.business
        )

        self.business.refresh_from_db()

        # Delete the default contact with Bob selected as new default
        url = reverse('contacts:delete_contact', args=[contact1.contact_id])
        response = self.client.post(url, {'new_default_contact': contact2.contact_id}, follow=True)

        # Check success message indicates new default
        self.assertContains(response, 'has been deleted')
        self.assertContains(response, 'Bob Beta')
        self.assertContains(response, 'is now the default contact')

    def test_delete_default_with_invalid_selection_shows_error(self):
        """Selecting invalid contact should show error and not delete"""
        contact1 = Contact.objects.create(
            first_name='Alice',
            last_name='Alpha',
            email='alice@test.com',
            work_number='555-0001',
            business=self.business
        )

        contact2 = Contact.objects.create(
            first_name='Bob',
            last_name='Beta',
            email='bob@test.com',
            work_number='555-0002',
            business=self.business
        )

        contact3 = Contact.objects.create(
            first_name='Charlie',
            last_name='Gamma',
            email='charlie@test.com',
            work_number='555-0003',
            business=self.business
        )

        # Create contact from different business
        other_contact = Contact.objects.create(
            first_name='Other',
            last_name='Contact',
            email='other@test.com',
            work_number='555-9999'
        )
        other_business = Business.objects.create(
            business_name='Other Business',
            default_contact=other_contact
        )
        other_contact.business = other_business
        other_contact.save()

        self.business.refresh_from_db()

        # Try to delete Alice with invalid contact selection (contact from different business)
        url = reverse('contacts:delete_contact', args=[contact1.contact_id])
        response = self.client.post(url, {'new_default_contact': other_contact.contact_id})

        # Should show error (200 response with error message)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid contact selection')

        # Alice should not be deleted
        self.assertTrue(Contact.objects.filter(contact_id=contact1.contact_id).exists())

    def test_delete_only_contact_error_message(self):
        """Deleting the only contact should show appropriate error message"""
        contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001',
            business=self.business
        )

        url = reverse('contacts:delete_contact', args=[contact.contact_id])
        response = self.client.post(url, follow=True)

        # Check error message about not being able to delete only contact
        self.assertContains(response, 'Cannot delete')
        self.assertContains(response, 'only contact')

        # Contact should still exist
        self.assertTrue(Contact.objects.filter(contact_id=contact.contact_id).exists())


class ContactDetailPageDeleteButtonTest(TestCase):
    """Test that contact detail page has delete button"""

    def setUp(self):
        self.client = Client()

    def test_contact_detail_page_has_delete_button(self):
        """Contact detail page should have a Delete Contact button"""
        contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )

        url = reverse('contacts:contact_detail', args=[contact.contact_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Delete Contact')

    def test_delete_button_has_confirmation(self):
        """Delete button should trigger JavaScript confirmation"""
        contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )

        url = reverse('contacts:contact_detail', args=[contact.contact_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        # Check for confirmation dialog
        self.assertContains(response, 'confirmDelete')
        self.assertContains(response, 'Are you sure')


class EditContactWithJobStatusTest(TestCase):
    """Test that edit_contact correctly handles job status checks.

    The view should use 'completed' (not 'complete') when checking if a contact's
    business can be changed.
    """

    def setUp(self):
        self.client = Client()
        # Create contact first for default_contact
        self.contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )
        # Create business with default_contact
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.contact
        )
        # Link contact to business
        self.contact.business = self.business
        self.contact.save()

        # Create another business for transfer tests
        self.other_contact = Contact.objects.create(
            first_name='Other',
            last_name='Contact',
            email='other@test.com',
            work_number='555-0002'
        )
        self.other_business = Business.objects.create(
            business_name='Other Business',
            default_contact=self.other_contact
        )
        self.other_contact.business = self.other_business
        self.other_contact.save()

    def test_can_change_business_with_completed_job(self):
        """Contact with completed job can have business changed.

        Uses 'completed' status (not 'complete') to allow business changes.
        """
        # Create a completed job
        job = Job.objects.create(
            job_number='COMPLETED-001',
            name='Completed Job',
            contact=self.contact,
            status='completed'
        )

        # Add second contact to business so first can be moved
        other_contact = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0003',
            business=self.business
        )

        # Try to change business association
        url = reverse('contacts:edit_contact', args=[self.contact.contact_id])
        response = self.client.post(url, {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john@test.com',
            'work_number': '555-0001',
            'business_selection_mode': 'existing',
            'existing_business_id': self.other_business.business_id
        })

        # Should succeed (redirect)
        self.assertEqual(response.status_code, 302)

        # Contact should now belong to other business
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.business, self.other_business)

    def test_cannot_change_business_with_open_job(self):
        """Contact with open (non-terminal) job cannot have business changed."""
        # Create an approved (open) job
        job = Job.objects.create(
            job_number='OPEN-001',
            name='Open Job',
            contact=self.contact,
            status='approved'
        )

        # Add second contact to business so first could potentially be moved
        other_contact = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0003',
            business=self.business
        )

        # Try to change business association
        url = reverse('contacts:edit_contact', args=[self.contact.contact_id])
        response = self.client.post(url, {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john@test.com',
            'work_number': '555-0001',
            'business_selection_mode': 'existing',
            'existing_business_id': self.other_business.business_id
        }, follow=True)

        # Should show error
        self.assertContains(response, 'Cannot change business association')
        self.assertContains(response, 'OPEN-001')

        # Contact should still belong to original business
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.business, self.business)
