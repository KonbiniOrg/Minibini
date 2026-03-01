from django.test import TestCase, Client
from django.urls import reverse
from unittest.mock import patch, MagicMock
from apps.core.models import EmailRecord, TempEmail, Configuration
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job


class CreateJobFromEmailWorkflowTest(TestCase):
    """Test the complete workflow of creating a job from an email"""

    fixtures = ['email_workflow_test_data.json']

    def setUp(self):
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

    def _mock_email_content(self, from_header, subject, body_text, body_html=''):
        """Helper to create mock email content"""
        return {
            'from': from_header,
            'to': ['info@minibini.com'],
            'cc': [],
            'date': '2024-01-15 10:00:00',
            'subject': subject,
            'text': body_text,
            'html': body_html,
            'attachments': []
        }

    @patch('apps.core.views.EmailService')
    def test_create_job_from_email_existing_contact(self, mock_service_class):
        """Test workflow when contact already exists - should go directly to job creation"""
        # Setup mock
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        email_content = self._mock_email_content(
            from_header='Alice Johnson <alice@acme.com>',
            subject='Request for Quote',
            body_text='Hi, I need a quote for a website.\n\nThanks,\nAlice'
        )
        mock_service.get_email_content.return_value = email_content

        # Email record 1 is from alice@acme.com, and Contact 1 exists with that email
        email_record = EmailRecord.objects.get(pk=1)
        url = reverse('core:create_job_from_email', args=[email_record.email_record_id])

        response = self.client.get(url)

        # Should redirect to job creation with contact pre-selected
        self.assertEqual(response.status_code, 302)
        self.assertIn('jobs/create', response.url)
        self.assertIn(f'contact_id=1', response.url)

        # Check session has email data stored
        session = self.client.session
        self.assertEqual(session['email_record_id_for_job'], email_record.email_record_id)
        self.assertIn('I need a quote for a website', session['email_body_for_job'])

    @patch('apps.core.views.EmailService')
    def test_create_job_from_email_no_contact_no_company(self, mock_service_class):
        """Test workflow when contact doesn't exist and no company detected"""
        # Setup mock
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # Email with no company signature - no name after closing to avoid false detection
        email_content = self._mock_email_content(
            from_header='dave@personal-email.com',
            subject='Need Help',
            body_text='Hi, I need some help with a project.\n\nThanks!'
        )
        mock_service.get_email_content.return_value = email_content

        # Email record 4 is from dave@personal-email.com (no existing contact)
        email_record = EmailRecord.objects.get(pk=4)
        url = reverse('core:create_job_from_email', args=[email_record.email_record_id])

        response = self.client.get(url)

        # Should redirect to add contact
        self.assertEqual(response.status_code, 302)
        self.assertIn('contacts/add', response.url)

        # Check session has contact data
        # Note: parse_email_address capitalizes the name extracted from email (from address part)
        session = self.client.session
        self.assertEqual(session['contact_name'], 'Dave')  # Extracted and capitalized from 'dave@...'
        self.assertEqual(session['contact_email'], 'dave@personal-email.com')
        self.assertEqual(session['contact_company'], '')  # No company detected
        self.assertEqual(session['email_record_id_for_job'], email_record.email_record_id)

    @patch('apps.core.views.EmailService')
    def test_create_job_from_email_no_contact_with_company_match_found(self, mock_service_class):
        """Test workflow when contact doesn't exist but company detected and matching business found"""
        # Setup mock
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # Email with Acme Corp signature - Business 1 exists with name "Acme Corp"
        # Use "Corp" suffix and put company name first in signature
        email_content = self._mock_email_content(
            from_header='Bob Smith <bob.smith@newcustomer.com>',
            subject='New Project',
            body_text='Hi,\n\nI need help with a project.\n\nBest regards,\nAcme Corp\nBob Smith, Senior Manager\n555-100-1000'
        )
        mock_service.get_email_content.return_value = email_content

        # Email record 2 is from bob.smith@newcustomer.com (no existing contact)
        email_record = EmailRecord.objects.get(pk=2)
        url = reverse('core:create_job_from_email', args=[email_record.email_record_id])

        response = self.client.get(url)

        # Should redirect to add contact
        self.assertEqual(response.status_code, 302)
        self.assertIn('contacts/add', response.url)

        # Check session has contact data with company
        session = self.client.session
        self.assertEqual(session['contact_name'], 'Bob Smith')
        self.assertEqual(session['contact_email'], 'bob.smith@newcustomer.com')
        self.assertEqual(session['contact_company'], 'Acme Corp')
        self.assertEqual(session['email_record_id_for_job'], email_record.email_record_id)
        # Should suggest the matching business
        self.assertEqual(session['suggested_business_id'], 1)

    @patch('apps.core.views.EmailService')
    def test_create_job_from_email_no_contact_with_company_no_match(self, mock_service_class):
        """Test workflow when contact doesn't exist, company detected but no matching business"""
        # Setup mock
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # Email with company that doesn't exist in database
        # LLC is recognized suffix, put company name first
        email_content = self._mock_email_content(
            from_header='Carol Williams <carol.williams@techstart.com>',
            subject='Software Services',
            body_text='Hi,\n\nLooking for software services.\n\nRegards,\nBrand New Company LLC\nCarol Williams, CEO\n555-999-9999'
        )
        mock_service.get_email_content.return_value = email_content

        # Email record 3 is from carol.williams@techstart.com (no existing contact)
        email_record = EmailRecord.objects.get(pk=3)
        url = reverse('core:create_job_from_email', args=[email_record.email_record_id])

        response = self.client.get(url)

        # Should redirect to add contact
        self.assertEqual(response.status_code, 302)
        self.assertIn('contacts/add', response.url)

        # Check session has contact data with company
        session = self.client.session
        self.assertEqual(session['contact_name'], 'Carol Williams')
        self.assertEqual(session['contact_email'], 'carol.williams@techstart.com')
        self.assertEqual(session['contact_company'], 'Brand New Company LLC')
        self.assertEqual(session['email_record_id_for_job'], email_record.email_record_id)
        # No matching business, so no suggestion
        self.assertNotIn('suggested_business_id', session)

    @patch('apps.core.views.EmailService')
    def test_create_job_from_email_unsigned_see_attached(self, mock_service_class):
        """Test email with just 'see attached' and no signature - should not extract company"""
        # Setup mock
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # Email with minimal body and no signature
        email_content = self._mock_email_content(
            from_header='Emma Wilson <emma@somecompany.com>',
            subject='Quote Request',
            body_text='See attached.'
        )
        mock_service.get_email_content.return_value = email_content

        # Email record 4 for testing
        email_record = EmailRecord.objects.get(pk=4)
        url = reverse('core:create_job_from_email', args=[email_record.email_record_id])

        response = self.client.get(url)

        # Should redirect to add contact
        self.assertEqual(response.status_code, 302)
        self.assertIn('contacts/add', response.url)

        # Check session - no company should be detected
        session = self.client.session
        self.assertEqual(session['contact_name'], 'Emma Wilson')
        self.assertEqual(session['contact_email'], 'emma@somecompany.com')
        self.assertEqual(session['contact_company'], '')  # No company detected from unsigned email
        self.assertEqual(session['email_record_id_for_job'], email_record.email_record_id)

    @patch('apps.core.views.EmailService')
    def test_create_job_from_email_forwarded_chain_no_signature(self, mock_service_class):
        """Test forwarded email chain without signature - should not extract company from body"""
        # Setup mock
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # Long forwarded chain without sender's signature
        email_content = self._mock_email_content(
            from_header='Frank Chen <frank@email.com>',
            subject='FW: RE: RE: Project discussion',
            body_text='''Please see the conversation below.

---------- Forwarded message ----------
From: Jane Doe <jane@acme.com>
Date: Mon, Jan 1, 2024 at 10:00 AM
Subject: RE: RE: Project discussion

We at Acme Corp would be happy to help with your project.

Best regards,
Jane Doe
Acme Corp

---------- Original message ----------
From: Bob Smith <bob@techcorp.com>
Date: Sun, Dec 31, 2023 at 3:00 PM

Looking for vendors for our upcoming project at TechCorp Inc.

Bob Smith
TechCorp Inc'''
        )
        mock_service.get_email_content.return_value = email_content

        # Email record 4 for testing
        email_record = EmailRecord.objects.get(pk=4)
        url = reverse('core:create_job_from_email', args=[email_record.email_record_id])

        response = self.client.get(url)

        # Should redirect to add contact
        self.assertEqual(response.status_code, 302)
        self.assertIn('contacts/add', response.url)

        # Check session - should NOT extract Acme Corp or TechCorp from forwarded content
        session = self.client.session
        self.assertEqual(session['contact_name'], 'Frank Chen')
        self.assertEqual(session['contact_email'], 'frank@email.com')
        self.assertEqual(session['contact_company'], '')  # No company detected - Frank didn't sign
        self.assertEqual(session['email_record_id_for_job'], email_record.email_record_id)

    @patch('apps.core.views.EmailService')
    def test_create_job_from_email_with_body_company_mention_no_sig(self, mock_service_class):
        """Test email mentioning companies in body but without signature - should not extract"""
        # Setup mock
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        # Email mentioning companies in body but sender didn't sign
        email_content = self._mock_email_content(
            from_header='George Martinez <george@email.net>',
            subject='Partnership opportunity',
            body_text='''Hi,

I wanted to discuss a potential partnership between Microsoft Corporation and Apple Inc.
Both companies have expressed interest in this collaboration.

GlobalTech LLC has also shown some interest in participating.

Let me know your thoughts.'''
        )
        mock_service.get_email_content.return_value = email_content

        # Email record 4 for testing
        email_record = EmailRecord.objects.get(pk=4)
        url = reverse('core:create_job_from_email', args=[email_record.email_record_id])

        response = self.client.get(url)

        # Should redirect to add contact
        self.assertEqual(response.status_code, 302)
        self.assertIn('contacts/add', response.url)

        # Should NOT extract Microsoft, Apple, or GlobalTech from body
        session = self.client.session
        self.assertEqual(session['contact_name'], 'George Martinez')
        self.assertEqual(session['contact_email'], 'george@email.net')
        self.assertEqual(session['contact_company'], '')  # No company from unsigned email
        self.assertEqual(session['email_record_id_for_job'], email_record.email_record_id)

    @patch('apps.core.views.EmailService')
    def test_create_job_from_email_imap_connection_error(self, mock_service_class):
        """Test handling when email content cannot be retrieved from server"""
        # Setup mock to return None (simulating connection error)
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.get_email_content.return_value = None

        email_record = EmailRecord.objects.get(pk=1)
        url = reverse('core:create_job_from_email', args=[email_record.email_record_id])

        response = self.client.get(url)

        # Should redirect back to email detail with error message
        self.assertEqual(response.status_code, 302)
        self.assertIn('inbox', response.url)
        self.assertIn(str(email_record.email_record_id), response.url)

    @patch('apps.core.views.EmailService')
    def test_create_job_from_email_already_has_job(self, mock_service_class):
        """Test that create job button doesn't appear if email already linked to job"""
        # Create a job and link it to email record 1
        contact = Contact.objects.get(pk=1)
        job = Job.objects.create(
            job_number='JOB-2024-001',
            contact=contact,
            description='Test job',
            status='draft'
        )
        email_record = EmailRecord.objects.get(pk=1)
        email_record.job = job
        email_record.save()

        # Setup mock for email detail view
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        email_content = self._mock_email_content(
            from_header='Alice Johnson <alice@acme.com>',
            subject='Request for Quote',
            body_text='Hi, I need a quote.'
        )
        mock_service.get_email_content.return_value = email_content

        # View email detail
        url = reverse('core:email_detail', args=[email_record.email_record_id])
        response = self.client.get(url)

        # Should NOT show "Create Job" button
        self.assertNotContains(response, 'Create Job from this Email')
        # Should show link to existing job
        self.assertContains(response, job.job_number)


class AddContactFromEmailWorkflowTest(TestCase):
    """Test add_contact view when called from email workflow"""

    fixtures = ['email_workflow_test_data.json']

    def setUp(self):
        self.client = Client()
        self.url = reverse('contacts:add_contact')

        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

    def test_add_contact_with_email_session_data_no_business(self):
        """Test adding contact with session data but no business"""
        session = self.client.session
        session['contact_name'] = 'New Person'
        session['contact_email'] = 'new@example.com'
        session['email_record_id_for_job'] = 1
        session.save()

        response = self.client.get(self.url)

        # Check form is pre-filled (name split into first/last)
        self.assertContains(response, 'value="New"')
        self.assertContains(response, 'value="Person"')
        self.assertContains(response, 'value="new@example.com"')

    def test_add_contact_with_suggested_business(self):
        """Test adding contact when business is suggested"""
        session = self.client.session
        session['contact_name'] = 'Bob Smith'
        session['contact_email'] = 'bob@acme.com'
        session['contact_company'] = 'Acme Corporation'
        session['suggested_business_id'] = 1
        session['email_record_id_for_job'] = 2
        session.save()

        response = self.client.get(self.url)

        # Should show suggested business
        self.assertContains(response, 'Acme Corporation')
        self.assertContains(response, 'A matching business was found and pre-selected')

    def test_add_contact_with_company_no_match(self):
        """Test adding contact when company detected but no match"""
        session = self.client.session
        session['contact_name'] = 'Carol New'
        session['contact_email'] = 'carol@newco.com'
        session['contact_company'] = 'NewCo Industries'
        session['email_record_id_for_job'] = 3
        session.save()

        response = self.client.get(self.url)

        # Should show company was detected
        self.assertContains(response, 'Company detected from email: "NewCo Industries"')
        self.assertContains(response, 'No matching business found')

    def test_add_contact_post_with_existing_business(self):
        """Test creating contact and associating with existing business"""
        session = self.client.session
        session['email_record_id_for_job'] = 2
        session['email_body_for_job'] = 'Test email body'
        session.save()

        post_data = {
            'first_name': 'Bob',
            'last_name': 'Smith',
            'email': 'bob@newcustomer.com',
            'work_number': '555-0001',
            'business_id': '1',  # Acme Corp
        }

        response = self.client.post(self.url, data=post_data)

        # Should create contact
        contact = Contact.objects.get(email='bob@newcustomer.com')
        self.assertEqual(contact.name, 'Bob Smith')
        self.assertEqual(contact.business.business_id, 1)

        # Should redirect to job creation
        self.assertEqual(response.status_code, 302)
        self.assertIn('jobs/create', response.url)
        self.assertIn(f'contact_id={contact.contact_id}', response.url)

    def test_add_contact_post_with_none_no_company_detected(self):
        """Test creating contact with NONE selected and no company detected"""
        session = self.client.session
        session['contact_name'] = 'Dave Solo'
        session['contact_email'] = 'dave@solo.com'
        session['email_record_id_for_job'] = 4
        session['email_body_for_job'] = 'Test email'
        session.save()

        post_data = {
            'first_name': 'Dave',
            'last_name': 'Solo',
            'email': 'dave@solo.com',
            'work_number': '555-0002',
            'business_id': 'NONE',
        }

        response = self.client.post(self.url, data=post_data)

        # Should create contact without business
        contact = Contact.objects.get(email='dave@solo.com')
        self.assertIsNone(contact.business)

        # Should redirect directly to job creation (no intermediate page)
        self.assertEqual(response.status_code, 302)
        self.assertIn('jobs/create', response.url)

    def test_add_contact_post_with_none_company_detected(self):
        """Test creating contact with NONE selected but company was detected - should show intermediate page"""
        session = self.client.session
        session['contact_name'] = 'Carol Williams'
        session['contact_email'] = 'carol@techstart.com'
        session['contact_company'] = 'NewCo Industries'
        session['email_record_id_for_job'] = 3
        session['email_body_for_job'] = 'Test email'
        session.save()

        post_data = {
            'first_name': 'Carol',
            'last_name': 'Williams',
            'email': 'carol@techstart.com',
            'work_number': '555-0003',
            'business_id': 'NONE',
        }

        response = self.client.post(self.url, data=post_data)

        # Should create contact
        contact = Contact.objects.get(email='carol@techstart.com')
        self.assertIsNone(contact.business)

        # Should redirect to intermediate confirmation page
        self.assertEqual(response.status_code, 302)
        self.assertIn('confirm-create-business', response.url)

        # Should store contact_id in session
        session = self.client.session
        self.assertEqual(session['contact_id_for_business'], contact.contact_id)


class ConfirmCreateBusinessFromEmailTest(TestCase):
    """Test confirm_create_business intermediate page"""

    fixtures = ['email_workflow_test_data.json']

    def setUp(self):
        self.client = Client()
        self.url = reverse('contacts:confirm_create_business')

        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

    def test_confirm_create_business_get(self):
        """Test viewing the confirmation page"""
        # Create a contact first
        contact = Contact.objects.create(
            first_name='Test',
            last_name='Person',
            email='test@newco.com'
        )

        session = self.client.session
        session['contact_id_for_business'] = contact.contact_id
        session['contact_company'] = 'NewCo Industries'
        session['email_record_id_for_job'] = 2
        session['email_body_for_job'] = 'Test email'
        session.save()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Person')
        self.assertContains(response, 'NewCo Industries')
        self.assertContains(response, 'Yes, Create Business')
        self.assertContains(response, 'No, Continue Without Business')

    def test_confirm_create_business_post_yes(self):
        """Test choosing YES to create business"""
        contact = Contact.objects.create(
            first_name='Test',
            last_name='Person',
            email='test@newco.com'
        )

        session = self.client.session
        session['contact_id_for_business'] = contact.contact_id
        session['contact_company'] = 'NewCo Industries'
        session['email_record_id_for_job'] = 2
        session['email_body_for_job'] = 'Test email'
        session.save()

        post_data = {
            'create_business': 'yes'
        }

        response = self.client.post(self.url, data=post_data)

        # Should create business
        business = Business.objects.get(business_name='NewCo Industries')
        self.assertIsNotNone(business)

        # Should associate contact with business
        contact.refresh_from_db()
        self.assertEqual(contact.business, business)

        # Should redirect to job creation
        self.assertEqual(response.status_code, 302)
        self.assertIn('jobs/create', response.url)

        # Session should be cleaned up
        session = self.client.session
        self.assertNotIn('contact_id_for_business', session)
        self.assertNotIn('contact_company', session)

    def test_confirm_create_business_post_no(self):
        """Test choosing NO to skip business creation"""
        contact = Contact.objects.create(
            first_name='Test',
            last_name='Person',
            email='test@newco.com'
        )

        session = self.client.session
        session['contact_id_for_business'] = contact.contact_id
        session['contact_company'] = 'NewCo Industries'
        session['email_record_id_for_job'] = 2
        session['email_body_for_job'] = 'Test email'
        session.save()

        post_data = {
            'create_business': 'no'
        }

        response = self.client.post(self.url, data=post_data)

        # Should NOT create business
        self.assertFalse(Business.objects.filter(business_name='NewCo Industries').exists())

        # Contact should remain without business
        contact.refresh_from_db()
        self.assertIsNone(contact.business)

        # Should redirect to job creation
        self.assertEqual(response.status_code, 302)
        self.assertIn('jobs/create', response.url)

        # Session should be cleaned up
        session = self.client.session
        self.assertNotIn('contact_id_for_business', session)


class JobCreateWithEmailLinkingTest(TestCase):
    """Test job creation view when coming from email workflow"""

    fixtures = ['email_workflow_test_data.json']

    def setUp(self):
        self.client = Client()
        self.url = reverse('jobs:create')
        self.contact = Contact.objects.get(pk=1)

        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

    def test_job_create_with_email_session_data(self):
        """Test creating job with email data in session"""
        email_record = EmailRecord.objects.get(pk=1)

        session = self.client.session
        session['email_record_id_for_job'] = email_record.email_record_id
        session['email_body_for_job'] = 'Need a website built. Budget is $5000.'
        session.save()

        post_data = {
            'contact': self.contact.contact_id,
            'description': 'Website development from email',
        }

        response = self.client.post(self.url, data=post_data)

        # Should create job with auto-generated number
        job = Job.objects.get(contact=self.contact, description='Website development from email')
        self.assertIsNotNone(job.job_number)
        self.assertTrue(job.job_number.startswith('JOB-'))
        self.assertEqual(job.contact, self.contact)

        # Should link email to job
        email_record.refresh_from_db()
        self.assertEqual(email_record.job, job)

        # Session should be cleaned up
        session = self.client.session
        self.assertNotIn('email_record_id_for_job', session)
        self.assertNotIn('email_body_for_job', session)

    def test_job_create_without_email_session_data(self):
        """Test creating job normally without email workflow"""
        post_data = {
            'contact': self.contact.contact_id,
            'description': 'Normal job creation',
        }

        response = self.client.post(self.url, data=post_data)

        # Should create job normally with auto-generated number
        job = Job.objects.get(contact=self.contact, description='Normal job creation')
        self.assertIsNotNone(job.job_number)
        self.assertTrue(job.job_number.startswith('JOB-'))
        self.assertEqual(job.contact, self.contact)

        # No email should be linked
        self.assertFalse(EmailRecord.objects.filter(job=job).exists())

    def test_job_create_get_with_preselected_contact_and_description(self):
        """Test GET request with contact and description from email"""
        session = self.client.session
        session['email_record_id_for_job'] = 1
        session['email_body_for_job'] = 'Need help with website'
        session.save()

        response = self.client.get(f"{self.url}?contact_id=1&description=Need help with website")

        self.assertEqual(response.status_code, 200)
        # Check form has pre-selected contact
        form = response.context['form']
        self.assertEqual(form.fields['contact'].initial, self.contact)


class EmailJobAssociationTest(TestCase):
    """Test associating and disassociating emails with jobs"""

    fixtures = ['email_workflow_test_data.json']

    def setUp(self):
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

    def _mock_email_content(self, from_header, subject, body_text):
        """Helper to create mock email content"""
        return {
            'from': from_header,
            'to': ['info@minibini.com'],
            'cc': [],
            'date': '2024-01-15 10:00:00',
            'subject': subject,
            'text': body_text,
            'html': '',
            'attachments': []
        }

    @patch('apps.core.views.EmailService')
    def test_associate_email_get_shows_job_list(self, mock_service_class):
        """Test GET request shows form with job dropdown"""
        # Setup mock
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        email_content = self._mock_email_content(
            from_header='Alice Johnson <alice@acme.com>',
            subject='Request for Quote',
            body_text='Hi, I need a quote.'
        )
        mock_service.get_email_content.return_value = email_content

        # Create a couple of jobs
        contact = Contact.objects.get(pk=1)
        job1 = Job.objects.create(
            job_number='JOB-2024-001',
            contact=contact,
            description='First job',
            status='draft'
        )
        job2 = Job.objects.create(
            job_number='JOB-2024-002',
            contact=contact,
            description='Second job',
            status='submitted'
        )

        email_record = EmailRecord.objects.get(pk=1)
        url = reverse('core:associate_email_with_job', args=[email_record.email_record_id])

        response = self.client.get(url)

        # Should show the form
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select Job')
        self.assertContains(response, job1.job_number)
        self.assertContains(response, job2.job_number)
        self.assertContains(response, 'Associate Email with Job')

    @patch('apps.core.views.EmailService')
    def test_associate_email_post_success(self, mock_service_class):
        """Test POST request successfully associates email with job"""
        # Create a job
        contact = Contact.objects.get(pk=1)
        job = Job.objects.create(
            job_number='JOB-2024-001',
            contact=contact,
            description='Test job',
            status='draft'
        )

        email_record = EmailRecord.objects.get(pk=1)
        self.assertIsNone(email_record.job)

        url = reverse('core:associate_email_with_job', args=[email_record.email_record_id])

        response = self.client.post(url, data={'job_id': job.job_id})

        # Should redirect to email detail
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'inbox/{email_record.email_record_id}', response.url)

        # Email should now be associated with job
        email_record.refresh_from_db()
        self.assertEqual(email_record.job, job)

    @patch('apps.core.views.EmailService')
    def test_associate_email_post_no_job_selected(self, mock_service_class):
        """Test POST request without selecting a job shows error"""
        email_record = EmailRecord.objects.get(pk=1)
        url = reverse('core:associate_email_with_job', args=[email_record.email_record_id])

        response = self.client.post(url, data={'job_id': ''})

        # Should redirect back to form
        self.assertEqual(response.status_code, 302)
        self.assertIn('associate-job', response.url)

        # Email should still not be associated
        email_record.refresh_from_db()
        self.assertIsNone(email_record.job)

    @patch('apps.core.views.EmailService')
    def test_associate_email_post_invalid_job_id(self, mock_service_class):
        """Test POST request with invalid job ID shows error"""
        email_record = EmailRecord.objects.get(pk=1)
        url = reverse('core:associate_email_with_job', args=[email_record.email_record_id])

        response = self.client.post(url, data={'job_id': 99999})

        # Should redirect back to form
        self.assertEqual(response.status_code, 302)
        self.assertIn('associate-job', response.url)

        # Email should still not be associated
        email_record.refresh_from_db()
        self.assertIsNone(email_record.job)

    def test_disassociate_email_success(self):
        """Test disassociating email from job"""
        # Create a job and associate it with email
        contact = Contact.objects.get(pk=1)
        job = Job.objects.create(
            job_number='JOB-2024-001',
            contact=contact,
            description='Test job',
            status='draft'
        )

        email_record = EmailRecord.objects.get(pk=1)
        email_record.job = job
        email_record.save()

        url = reverse('core:disassociate_email_from_job', args=[email_record.email_record_id])

        response = self.client.post(url)

        # Should redirect to email detail
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'inbox/{email_record.email_record_id}', response.url)

        # Email should no longer be associated with job
        email_record.refresh_from_db()
        self.assertIsNone(email_record.job)

    def test_disassociate_email_not_associated(self):
        """Test disassociating email that is not associated with any job"""
        email_record = EmailRecord.objects.get(pk=1)
        self.assertIsNone(email_record.job)

        url = reverse('core:disassociate_email_from_job', args=[email_record.email_record_id])

        response = self.client.post(url)

        # Should still redirect to email detail
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'inbox/{email_record.email_record_id}', response.url)

    def test_disassociate_email_get_request_fails(self):
        """Test that GET request to disassociate endpoint fails"""
        email_record = EmailRecord.objects.get(pk=1)
        url = reverse('core:disassociate_email_from_job', args=[email_record.email_record_id])

        response = self.client.get(url)

        # Should redirect back to email detail
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'inbox/{email_record.email_record_id}', response.url)

    @patch('apps.core.views.EmailService')
    def test_email_detail_shows_associate_link_when_not_associated(self, mock_service_class):
        """Test email detail page shows associate link when email is not linked to job"""
        # Setup mock
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        email_content = self._mock_email_content(
            from_header='Alice Johnson <alice@acme.com>',
            subject='Request for Quote',
            body_text='Hi, I need a quote.'
        )
        mock_service.get_email_content.return_value = email_content

        email_record = EmailRecord.objects.get(pk=1)
        self.assertIsNone(email_record.job)

        url = reverse('core:email_detail', args=[email_record.email_record_id])
        response = self.client.get(url)

        # Should show associate link
        self.assertContains(response, 'Associate with Existing Job')
        self.assertContains(response, 'associate-job')

    @patch('apps.core.views.EmailService')
    def test_email_detail_shows_disassociate_button_when_associated(self, mock_service_class):
        """Test email detail page shows disassociate button when email is linked to job"""
        # Setup mock
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        email_content = self._mock_email_content(
            from_header='Alice Johnson <alice@acme.com>',
            subject='Request for Quote',
            body_text='Hi, I need a quote.'
        )
        mock_service.get_email_content.return_value = email_content

        # Create a job and associate it with email
        contact = Contact.objects.get(pk=1)
        job = Job.objects.create(
            job_number='JOB-2024-001',
            contact=contact,
            description='Test job',
            status='draft'
        )

        email_record = EmailRecord.objects.get(pk=1)
        email_record.job = job
        email_record.save()

        url = reverse('core:email_detail', args=[email_record.email_record_id])
        response = self.client.get(url)

        # Should show job link and disassociate button
        self.assertContains(response, job.job_number)
        self.assertContains(response, 'Disassociate')
        self.assertContains(response, 'disassociate-job')
        # Should NOT show create job or associate links
        self.assertNotContains(response, 'Create Job from this Email')
        self.assertNotContains(response, 'Associate with Existing Job')
