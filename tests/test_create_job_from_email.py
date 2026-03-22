"""Tests for the create_job_from_email view."""
from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from apps.core.models import EmailRecord
from apps.contacts.models import Contact, Business


class CreateJobFromEmailTest(TestCase):
    """Tests for core:create_job_from_email view."""

    def setUp(self):
        self.client = Client()
        self.client.force_login(get_user_model().objects.create_superuser(username=f'admin_{id(self)}', password='testpass'))
        self.email_record = EmailRecord.objects.create(
            message_id='<test@example.com>',
        )
        self.url = reverse(
            'core:create_job_from_email',
            args=[self.email_record.email_record_id])

    def _mock_email_content(self, from_header='Jane Doe <jane@acme.com>',
                            text='Hello, I need a quote.\n\n--\nJane Doe\nAcme Corp'):
        """Return a standard email content dict for mocking."""
        return {
            'from': from_header,
            'subject': 'New project inquiry',
            'text': text,
            'html': '',
        }

    @patch.object(
        __import__('apps.core.services', fromlist=['EmailService']).EmailService,
        'get_email_content')
    def test_email_content_not_found(self, mock_get):
        """Shows error and redirects when email content can't be fetched."""
        mock_get.return_value = None

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            f'/inbox/{self.email_record.email_record_id}/',
            response.url)

    @patch.object(
        __import__('apps.core.services', fromlist=['EmailService']).EmailService,
        'get_email_content')
    def test_sender_email_not_parseable(self, mock_get):
        """Shows error when sender email can't be extracted."""
        mock_get.return_value = {'from': '', 'text': '', 'html': ''}

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            f'/inbox/{self.email_record.email_record_id}/',
            response.url)

    @patch.object(
        __import__('apps.core.services', fromlist=['EmailService']).EmailService,
        'get_email_content')
    def test_existing_contact_redirects_to_job_create(self, mock_get):
        """Redirects to job creation with contact pre-filled when contact exists."""
        contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@acme.com')
        mock_get.return_value = self._mock_email_content()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/jobs/create/', response.url)
        self.assertIn(f'contact_id={contact.contact_id}', response.url)

    @patch.object(
        __import__('apps.core.services', fromlist=['EmailService']).EmailService,
        'get_email_content')
    def test_existing_contact_stores_session_data(self, mock_get):
        """Stores email_record_id and email body in session."""
        Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@acme.com')
        mock_get.return_value = self._mock_email_content()

        self.client.get(self.url)

        session = self.client.session
        self.assertEqual(
            session['email_record_id_for_job'],
            self.email_record.email_record_id)
        self.assertIn('email_body_for_job', session)

    @patch.object(
        __import__('apps.core.services', fromlist=['EmailService']).EmailService,
        'get_email_content')
    def test_no_contact_redirects_to_add_contact(self, mock_get):
        """Redirects to contact creation when no contact found."""
        mock_get.return_value = self._mock_email_content()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/contacts/', response.url)

    @patch.object(
        __import__('apps.core.services', fromlist=['EmailService']).EmailService,
        'get_email_content')
    def test_no_contact_stores_contact_data_in_session(self, mock_get):
        """Stores parsed sender info in session for contact creation form."""
        mock_get.return_value = self._mock_email_content()

        self.client.get(self.url)

        session = self.client.session
        self.assertEqual(session['contact_name'], 'Jane Doe')
        self.assertEqual(session['contact_email'], 'jane@acme.com')

    @patch.object(
        __import__('apps.core.services', fromlist=['EmailService']).EmailService,
        'get_email_content')
    def test_no_contact_suggests_matching_business(self, mock_get):
        """Finds and suggests matching business when company name extracted."""
        default_contact = Contact.objects.create(
            first_name='Default', last_name='Contact',
            email='default@acme.com')
        business = Business.objects.create(
            business_name='Acme Corp',
            default_contact=default_contact)
        mock_get.return_value = self._mock_email_content()

        self.client.get(self.url)

        session = self.client.session
        self.assertEqual(
            session.get('suggested_business_id'),
            business.business_id)

    @patch.object(
        __import__('apps.core.services', fromlist=['EmailService']).EmailService,
        'get_email_content')
    def test_multiple_contacts_uses_first(self, mock_get):
        """When multiple contacts share an email, uses the first and redirects."""
        Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@acme.com')
        Contact.objects.create(
            first_name='Jane', last_name='Smith',
            email='jane@acme.com')
        mock_get.return_value = self._mock_email_content()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/jobs/create/', response.url)
        self.assertIn('contact_id=', response.url)

    def test_nonexistent_email_record_returns_404(self):
        """Returns 404 for nonexistent email record."""
        url = reverse('core:create_job_from_email', args=[99999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
