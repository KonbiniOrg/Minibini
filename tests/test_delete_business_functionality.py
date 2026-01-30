from django.test import TestCase, Client
from django.urls import reverse
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job
from apps.purchasing.models import Bill, PurchaseOrder


class BusinessDeletionValidationTest(TestCase):
    """Test validation preventing business deletion when contacts have associations"""

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
            our_reference_code='TEST001',
            default_contact=self.contact
        )
        # Link contact to business
        self.contact.business = self.business
        self.contact.save()

    def test_cannot_delete_business_when_contact_has_job(self):
        """Cannot delete business if any contact has associated Jobs"""
        job = Job.objects.create(
            job_number='JOB001',
            contact=self.contact
        )

        url = reverse('contacts:delete_business', args=[self.business.business_id])
        response = self.client.post(url, follow=True)

        # Business should still exist
        self.assertTrue(Business.objects.filter(business_id=self.business.business_id).exists())

        # Should show error message
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertIn('Cannot delete business', str(messages[0]))
        self.assertIn('John Doe', str(messages[0]))
        self.assertIn('JOB001', str(messages[0]))

    def test_cannot_delete_business_when_contact_has_bill(self):
        """Cannot delete business if any contact has associated Bills"""
        po = PurchaseOrder.objects.create(
            po_number='PO001',
            business=self.business,
            status='issued'
        )
        bill = Bill.objects.create(
            purchase_order=po,
            contact=self.contact,
            vendor_invoice_number='INV001',
            bill_number='BILL001'
        )

        url = reverse('contacts:delete_business', args=[self.business.business_id])
        response = self.client.post(url, follow=True)

        # Business should still exist
        self.assertTrue(Business.objects.filter(business_id=self.business.business_id).exists())

        # Should show error message
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertIn('Cannot delete business', str(messages[0]))
        self.assertIn('John Doe', str(messages[0]))
        self.assertIn('Bills:', str(messages[0]))

    def test_cannot_delete_business_with_multiple_contact_associations(self):
        """Cannot delete business when multiple contacts have associations"""
        contact2 = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0002',
            business=self.business
        )

        job = Job.objects.create(
            job_number='JOB001',
            contact=self.contact
        )

        po = PurchaseOrder.objects.create(
            po_number='PO001',
            business=self.business,
            status='issued'
        )
        bill = Bill.objects.create(
            purchase_order=po,
            contact=contact2,
            vendor_invoice_number='INV001',
            bill_number='BILL001'
        )

        url = reverse('contacts:delete_business', args=[self.business.business_id])
        response = self.client.post(url, follow=True)

        # Business should still exist
        self.assertTrue(Business.objects.filter(business_id=self.business.business_id).exists())

        # Should show error message with both contacts
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        error_message = str(messages[0])
        self.assertIn('Cannot delete business', error_message)
        self.assertIn('John Doe', error_message)
        self.assertIn('Jane Smith', error_message)


class BusinessDeletionConfirmationFormTest(TestCase):
    """Test that confirmation form is shown when business has contacts"""

    def setUp(self):
        self.client = Client()
        # Create initial contact for default_contact
        initial_contact = Contact.objects.create(
            first_name='Initial',
            last_name='Contact',
            email='initial@test.com',
            work_number='555-0000'
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            our_reference_code='TEST001',
            default_contact=initial_contact
        )
        initial_contact.business = self.business
        initial_contact.save()

    def test_confirmation_form_shown_when_business_has_contacts(self):
        """Confirmation form should be shown on first POST when business has contacts"""
        contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001',
            business=self.business
        )

        url = reverse('contacts:delete_business', args=[self.business.business_id])
        response = self.client.post(url)

        # Should show confirmation form (200 response, not redirect)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'contacts/confirm_delete_business.html')

        # Should contain radio buttons for action choice
        self.assertContains(response, 'name="contact_action"')
        self.assertContains(response, 'value="unlink"')
        self.assertContains(response, 'value="delete"')

        # Should show contact information
        self.assertContains(response, 'John Doe')

        # Business should not be deleted yet
        self.assertTrue(Business.objects.filter(business_id=self.business.business_id).exists())

    def test_confirmation_form_shows_contact_count(self):
        """Confirmation form should display the count of associated contacts"""
        Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            business=self.business
        )
        Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            business=self.business
        )
        Contact.objects.create(
            first_name='Bob',
            last_name='Johnson',
            email='bob@test.com',
            business=self.business
        )

        url = reverse('contacts:delete_business', args=[self.business.business_id])
        response = self.client.post(url)

        self.assertContains(response, '3')
        self.assertContains(response, 'contact(s)')

    def test_delete_business_with_unlink_action_removes_associations(self):
        """Deleting business with 'unlink' action should remove business associations from contacts"""
        # Add additional contacts to the business
        contact2 = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0002',
            business=self.business
        )

        # Get contact IDs before deletion
        initial_contact = self.business.default_contact
        contact1_id = initial_contact.contact_id
        contact2_id = contact2.contact_id

        # Verify business has contacts
        self.assertEqual(self.business.contacts.count(), 2)

        # Delete business with unlink action
        url = reverse('contacts:delete_business', args=[self.business.business_id])
        response = self.client.post(url, {'contact_action': 'unlink'}, follow=True)

        # Business should be deleted
        self.assertFalse(Business.objects.filter(business_id=self.business.business_id).exists())

        # Contacts should still exist but with business=None
        contact1 = Contact.objects.get(contact_id=contact1_id)
        contact2 = Contact.objects.get(contact_id=contact2_id)
        self.assertIsNone(contact1.business)
        self.assertIsNone(contact2.business)

        # Should redirect to business list
        self.assertRedirects(response, reverse('contacts:business_list'))

        # Should show success message
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertIn('has been deleted', str(messages[0]))
        self.assertIn('2 contact(s) have been unlinked', str(messages[0]))


class BusinessDeletionUnlinkActionTest(TestCase):
    """Test unlinking contacts when deleting business"""

    def setUp(self):
        self.client = Client()
        # Create contact first for default_contact
        self.contact1 = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            our_reference_code='TEST001',
            default_contact=self.contact1
        )
        self.contact1.business = self.business
        self.contact1.save()
        self.contact2 = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0002',
            business=self.business
        )

    def test_unlink_action_keeps_contacts_removes_business_association(self):
        """Unlink action should keep contacts but remove their business association"""
        url = reverse('contacts:delete_business', args=[self.business.business_id])
        response = self.client.post(url, {'contact_action': 'unlink'}, follow=True)

        # Business should be deleted
        self.assertFalse(Business.objects.filter(business_id=self.business.business_id).exists())

        # Contacts should still exist
        self.assertTrue(Contact.objects.filter(contact_id=self.contact1.contact_id).exists())
        self.assertTrue(Contact.objects.filter(contact_id=self.contact2.contact_id).exists())

        # Contacts should have no business association
        self.contact1.refresh_from_db()
        self.contact2.refresh_from_db()
        self.assertIsNone(self.contact1.business)
        self.assertIsNone(self.contact2.business)

    def test_unlink_action_success_message(self):
        """Unlink action should show appropriate success message"""
        url = reverse('contacts:delete_business', args=[self.business.business_id])
        response = self.client.post(url, {'contact_action': 'unlink'}, follow=True)

        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertIn('has been deleted', str(messages[0]))
        self.assertIn('2 contact(s) have been unlinked', str(messages[0]))

    def test_unlink_action_redirects_to_business_list(self):
        """Unlink action should redirect to business list after deletion"""
        url = reverse('contacts:delete_business', args=[self.business.business_id])
        response = self.client.post(url, {'contact_action': 'unlink'})

        self.assertRedirects(response, reverse('contacts:business_list'))


class BusinessDeletionDeleteActionTest(TestCase):
    """Test deleting contacts along with business"""

    def setUp(self):
        self.client = Client()
        # Create contact first for default_contact
        self.contact1 = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            our_reference_code='TEST001',
            default_contact=self.contact1
        )
        self.contact1.business = self.business
        self.contact1.save()
        self.contact2 = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0002',
            business=self.business
        )

    def test_delete_action_removes_business_and_all_contacts(self):
        """Delete action should remove both business and all associated contacts"""
        url = reverse('contacts:delete_business', args=[self.business.business_id])
        response = self.client.post(url, {'contact_action': 'delete'}, follow=True)

        # Business should be deleted
        self.assertFalse(Business.objects.filter(business_id=self.business.business_id).exists())

        # All contacts should be deleted
        self.assertFalse(Contact.objects.filter(contact_id=self.contact1.contact_id).exists())
        self.assertFalse(Contact.objects.filter(contact_id=self.contact2.contact_id).exists())

    def test_delete_action_success_message(self):
        """Delete action should show appropriate success message"""
        url = reverse('contacts:delete_business', args=[self.business.business_id])
        response = self.client.post(url, {'contact_action': 'delete'}, follow=True)

        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertIn('have been deleted', str(messages[0]))
        self.assertIn('2 contact(s)', str(messages[0]))

    def test_delete_action_redirects_to_business_list(self):
        """Delete action should redirect to business list after deletion"""
        url = reverse('contacts:delete_business', args=[self.business.business_id])
        response = self.client.post(url, {'contact_action': 'delete'})

        self.assertRedirects(response, reverse('contacts:business_list'))


class BusinessDeletionMissingActionTest(TestCase):
    """Test that action selection is required when contacts exist"""

    def setUp(self):
        self.client = Client()
        # Create contact first for default_contact
        contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            our_reference_code='TEST001',
            default_contact=contact
        )
        contact.business = self.business
        contact.save()

    def test_missing_action_shows_confirmation_form(self):
        """Missing contact_action should show confirmation form, not process deletion"""
        url = reverse('contacts:delete_business', args=[self.business.business_id])
        response = self.client.post(url)

        # Should show confirmation form
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'contacts/confirm_delete_business.html')

        # Business should not be deleted
        self.assertTrue(Business.objects.filter(business_id=self.business.business_id).exists())


class BusinessDetailPageDeleteButtonTest(TestCase):
    """Test that business detail page has delete button"""

    def setUp(self):
        self.client = Client()
        # Create initial contact for default_contact
        initial_contact = Contact.objects.create(
            first_name='Initial',
            last_name='Contact',
            email='initial@test.com',
            work_number='555-0000'
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            our_reference_code='TEST001',
            default_contact=initial_contact
        )
        initial_contact.business = self.business
        initial_contact.save()

    def test_business_detail_page_has_delete_button(self):
        """Business detail page should have a delete button"""
        url = reverse('contacts:business_detail', args=[self.business.business_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Delete Business')
        self.assertContains(response, 'confirmDeleteBusiness()')

    def test_delete_button_has_confirmation_javascript(self):
        """Delete button should have JavaScript confirmation"""
        url = reverse('contacts:business_detail', args=[self.business.business_id])
        response = self.client.get(url)

        # Check for JavaScript confirmation function
        self.assertContains(response, 'function confirmDeleteBusiness()')
        self.assertContains(response, 'Are you sure you want to delete')


class BusinessDeletionGETRequestTest(TestCase):
    """Test that GET requests don't delete businesses"""

    def setUp(self):
        self.client = Client()
        # Create initial contact for default_contact
        initial_contact = Contact.objects.create(
            first_name='Initial',
            last_name='Contact',
            email='initial@test.com',
            work_number='555-0000'
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            our_reference_code='TEST001',
            default_contact=initial_contact
        )
        initial_contact.business = self.business
        initial_contact.save()

    def test_get_request_does_not_delete_business(self):
        """GET request should not delete business"""
        url = reverse('contacts:delete_business', args=[self.business.business_id])
        response = self.client.get(url)

        # Business should still exist
        self.assertTrue(Business.objects.filter(business_id=self.business.business_id).exists())

        # Should show confirmation page or redirect (but not delete)
        self.assertIn(response.status_code, [200, 302])
