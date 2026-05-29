from unittest.mock import patch, MagicMock
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, EmailRecord, TempEmail
from apps.jobs.models import Job
from django.utils import timezone


class EmailAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        # Create an email record with temp data for testing
        self.email = EmailRecord.objects.create(
            message_id='<test-123@example.com>',
            job=None,
        )
        self.temp_email = TempEmail.objects.create(
            email_record=self.email,
            uid='12345',
            subject='Test Email Subject',
            from_email='sender@example.com',
            to_email='recipient@example.com',
            cc_email='',
            date_sent=timezone.now(),
            is_read=False,
            is_starred=False,
            has_attachments=False,
        )

    def test_list_emails(self):
        response = self.client.get('/api/emails/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)

    def test_retrieve_email(self):
        response = self.client.get(f'/api/emails/{self.email.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['message_id'], '<test-123@example.com>')
        self.assertEqual(response.data['temp_email']['subject'], 'Test Email Subject')

    def test_retrieve_email_not_found(self):
        response = self.client.get('/api/emails/99999/')
        self.assertEqual(response.status_code, 404)

    def test_link_to_job(self):
        job = Job.objects.first()
        response = self.client.post(
            f'/api/emails/{self.email.pk}/link-to-job/',
            {'job_id': job.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.email.refresh_from_db()
        self.assertEqual(self.email.job_id, job.pk)

    def test_link_to_job_missing_job_id(self):
        response = self.client.post(
            f'/api/emails/{self.email.pk}/link-to-job/',
            {},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_unlink_from_job(self):
        job = Job.objects.first()
        self.email.job = job
        self.email.save()
        response = self.client.post(f'/api/emails/{self.email.pk}/unlink-from-job/')
        self.assertEqual(response.status_code, 200)
        self.email.refresh_from_db()
        self.assertIsNone(self.email.job)

    def test_send_stub_returns_501(self):
        response = self.client.post('/api/emails/send/', {}, format='json')
        self.assertEqual(response.status_code, 501)

    def test_refresh_returns_stats(self):
        with patch('apps.api.email.views.EmailService') as mock_service_class:
            mock_service = MagicMock()
            mock_service.fetch_emails_by_date_range.return_value = {
                'new': 3,
                'existing': 27,
                'errors': [],
            }
            mock_service_class.return_value = mock_service

            response = self.client.post('/api/emails/refresh/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['new'], 3)
        self.assertEqual(response.data['existing'], 27)
        self.assertEqual(response.data['errors'], [])
        self.assertIn('email_address', response.data)
        mock_service.fetch_emails_by_date_range.assert_called_once_with(days_back=30)

    def test_refresh_returns_configured_email_address(self):
        from django.test import override_settings
        with override_settings(EMAIL_HOST_USER='ops@example.com'):
            with patch('apps.api.email.views.EmailService') as mock_service_class:
                mock_service = MagicMock()
                mock_service.fetch_emails_by_date_range.return_value = {'new': 0, 'existing': 0, 'errors': []}
                mock_service_class.return_value = mock_service

                response = self.client.post('/api/emails/refresh/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['email_address'], 'ops@example.com')

    def test_refresh_reports_imap_errors(self):
        with patch('apps.api.email.views.EmailService') as mock_service_class:
            mock_service = MagicMock()
            mock_service.fetch_emails_by_date_range.side_effect = Exception("IMAP connection failed")
            mock_service_class.return_value = mock_service

            response = self.client.post('/api/emails/refresh/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['new'], 0)
        self.assertEqual(response.data['existing'], 0)
        self.assertIn('IMAP connection failed', response.data['errors'][0])

    def test_refresh_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.post('/api/emails/refresh/')
        self.assertEqual(response.status_code, 403)

    def _mock_email_content(self, from_header='Jane Doe <jane@acme.com>', text='Hi,\n\nLet us talk.\n\nRegards,\nJane Doe\nAcme Corp LLC\n'):
        return {
            'subject': 'Hello',
            'from': from_header,
            'to': ['ops@ours.com'],
            'cc': [],
            'date': timezone.now(),
            'text': text,
            'html': '',
            'attachments': [],
        }

    def test_sender_info_parses_sender_and_matches_contact(self):
        from apps.contacts.models import Contact, Business
        contact = Contact.objects.create(
            first_name='Jane',
            last_name='Doe',
            email='jane@acme.com',
        )
        business = Business.objects.create(business_name='Acme Corp LLC', default_contact=contact)
        contact.business = business
        contact.save()
        with patch('apps.api.email.views.EmailService') as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_email_content.return_value = self._mock_email_content()
            mock_service_class.return_value = mock_service

            response = self.client.get(f'/api/emails/{self.email.pk}/sender-info/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['sender_name'], 'Jane Doe')
        self.assertEqual(response.data['sender_email'], 'jane@acme.com')
        self.assertIn('Let us talk', response.data['suggested_body'])
        match_ids = [c['id'] for c in response.data['matching_contacts']]
        self.assertIn(contact.contact_id, match_ids)

    def test_sender_info_no_contact_match_returns_business_suggestion(self):
        from apps.contacts.models import Contact, Business
        anchor = Contact.objects.create(first_name='Anchor', last_name='Person', email='anchor@acme.com')
        biz = Business.objects.create(business_name='Acme Corp LLC', default_contact=anchor)
        with patch('apps.api.email.views.EmailService') as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_email_content.return_value = self._mock_email_content()
            mock_service_class.return_value = mock_service

            response = self.client.get(f'/api/emails/{self.email.pk}/sender-info/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['matching_contacts'], [])
        self.assertEqual(response.data['extracted_company'], 'Acme Corp LLC')
        biz_ids = [b['id'] for b in response.data['matching_businesses']]
        self.assertIn(biz.business_id, biz_ids)

    def test_sender_info_returns_503_when_content_unavailable(self):
        with patch('apps.api.email.views.EmailService') as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_email_content.return_value = None
            mock_service_class.return_value = mock_service

            response = self.client.get(f'/api/emails/{self.email.pk}/sender-info/')

        self.assertEqual(response.status_code, 503)

    def test_sender_info_not_found(self):
        response = self.client.get('/api/emails/99999/sender-info/')
        self.assertEqual(response.status_code, 404)

    def test_sender_info_requires_can_manage_jobs(self):
        plain_user = User.objects.create_user(username='worker_xx', password='pw')
        self.client.force_authenticate(user=plain_user)
        response = self.client.get(f'/api/emails/{self.email.pk}/sender-info/')
        self.assertEqual(response.status_code, 403)

    def test_link_to_job_rejects_non_integer_job_id(self):
        response = self.client.post(
            f'/api/emails/{self.email.pk}/link-to-job/',
            {'job_id': 'not-a-number'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_list_ignores_invalid_job_filter(self):
        response = self.client.get('/api/emails/?job=not-a-number')
        self.assertEqual(response.status_code, 400)

    def test_create_job_returns_400_on_validation_error(self):
        from apps.contacts.models import Contact
        contact = Contact.objects.create(first_name='X', last_name='Y', email='x@y.com', mobile_number='555')
        overlong = 'a' * 100  # Job.name max_length is 50
        response = self.client.post(
            f'/api/emails/{self.email.pk}/create-job/',
            {'contact': contact.contact_id, 'name': overlong},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('name', str(response.data).lower())

    def test_sender_info_returns_cleaned_subject(self):
        with patch('apps.api.email.views.EmailService') as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_email_content.return_value = self._mock_email_content()
            mock_service_class.return_value = mock_service
            # Force the subject we care about via the EmailRecord row, which is
            # what the view actually reads.
            self.temp_email.subject = 'Re: Fwd: Quote for bracket'
            self.temp_email.save()

            response = self.client.get(f'/api/emails/{self.email.pk}/sender-info/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['subject'], 'Quote for bracket')

    def test_sender_info_suggested_body_trimmed_at_signoff_not_at_200(self):
        long_body = ('Line ' + 'x' * 50 + '\n') * 10  # well over 200 chars
        text = long_body + '\nThanks,\nJane Doe\n'
        with patch('apps.api.email.views.EmailService') as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_email_content.return_value = self._mock_email_content(text=text)
            mock_service_class.return_value = mock_service

            response = self.client.get(f'/api/emails/{self.email.pk}/sender-info/')

        self.assertEqual(response.status_code, 200)
        body = response.data['suggested_body']
        self.assertGreater(len(body), 200)  # no longer hard-truncated to 200
        self.assertNotIn('Thanks,', body)   # signoff was stripped
        self.assertNotIn('Jane Doe', body)  # signer was stripped

    def test_create_job_stores_description(self):
        from apps.contacts.models import Contact
        contact = Contact.objects.create(
            first_name='X', last_name='Y', email='x@y.com', mobile_number='555',
        )
        response = self.client.post(
            f'/api/emails/{self.email.pk}/create-job/',
            {
                'contact': contact.contact_id,
                'name': 'Quote bracket',
                'description': 'Need 50 of these by Friday.',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        job = Job.objects.get(pk=response.data['job_id'])
        self.assertEqual(job.name, 'Quote bracket')
        self.assertEqual(job.description, 'Need 50 of these by Friday.')

    def test_filter_emails_by_job(self):
        """Emails can be filtered by job."""
        from apps.core.models import EmailRecord
        from apps.jobs.models import Job
        job = Job.objects.first()
        email1 = EmailRecord.objects.create(message_id='test-filter-1@example.com', job=job)
        email2 = EmailRecord.objects.create(message_id='test-filter-2@example.com')

        response = self.client.get(f'/api/emails/?job={job.job_id}')
        self.assertEqual(response.status_code, 200)
        email_ids = [r['email_record_id'] for r in response.data['results']]
        self.assertIn(email1.email_record_id, email_ids)
        self.assertNotIn(email2.email_record_id, email_ids)

    def test_email_list_includes_direction_display_address_snippet(self):
        """Serializer exposes the panel-ready fields."""
        # Replace the default temp_email with one that has a real cached body.
        self.temp_email.text_body = (
            "Sounds good — let's go with 50 units.\n\n"
            "Thanks,\nJane"
        )
        self.temp_email.save()

        response = self.client.get(f'/api/emails/{self.email.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['direction'], 'inbound')
        self.assertEqual(response.data['display_address'], 'sender@example.com')
        # Snippet comes from text_body, with sign-off + signature line stripped
        # by extract_email_body via strip_quoted_reply downstream callers; for
        # the snippet path we just strip the quoted-reply markers, so the
        # "Thanks,\nJane" tail survives until the regex truncation kicks in.
        # Verify we got the body content (not the raw cached_body with newlines).
        self.assertIn("Sounds good", response.data['snippet'])
        self.assertNotIn('\n', response.data['snippet'])

    def test_snippet_strips_quoted_reply(self):
        self.temp_email.text_body = (
            "Confirmed for next Friday.\n\n"
            "On Jan 1, John wrote:\n"
            "> Are we still on for Friday?\n"
        )
        self.temp_email.save()

        response = self.client.get(f'/api/emails/{self.email.pk}/')
        self.assertEqual(response.status_code, 200)
        snippet = response.data['snippet']
        self.assertIn('Confirmed', snippet)
        self.assertNotIn('John wrote', snippet)
        self.assertNotIn('still on for Friday', snippet)

    def test_snippet_truncates_with_ellipsis(self):
        self.temp_email.text_body = 'A' * 200
        self.temp_email.save()

        response = self.client.get(f'/api/emails/{self.email.pk}/')
        self.assertEqual(response.status_code, 200)
        snippet = response.data['snippet']
        self.assertEqual(len(snippet), 80)
        self.assertTrue(snippet.endswith('…'))

    def test_snippet_empty_when_temp_data_missing(self):
        record = EmailRecord.objects.create(message_id='<no-temp@example.com>')
        response = self.client.get(f'/api/emails/{record.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['snippet'], '')
        self.assertEqual(response.data['display_address'], '')

    def test_email_detail_with_binary_attachment_serializes(self):
        """Email detail for a message with a binary attachment must not
        500. The IMAP service strips raw payload bytes from the dict it
        returns so the JSON encoder doesn't choke on them."""
        from django.test.utils import override_settings
        # Force the cache-miss path so the IMAP code in get_email_content
        # actually runs against the mocked MailBox.
        self.temp_email.has_attachments = True
        self.temp_email.uid = '12345'
        self.temp_email.text_body = ''
        self.temp_email.html_body = ''
        self.temp_email.save()

        binary_payload = b'\xff\xd8\xff\xe0\x00\x10JFIF binary garbage'
        att = MagicMock()
        att.filename = 'photo.jpg'
        att.content_type = 'image/jpeg'
        att.payload = binary_payload

        mock_msg = MagicMock()
        mock_msg.subject = 'with attachment'
        mock_msg.from_ = 'sender@example.com'
        mock_msg.to = ['us@example.com']
        mock_msg.cc = []
        from django.utils import timezone as tz
        mock_msg.date = tz.now()
        mock_msg.text = 'see attached'
        mock_msg.html = ''
        mock_msg.attachments = [att]

        with override_settings(
            EMAIL_IMAP_SERVER='imap.example.com',
            EMAIL_HOST_USER='t@e.com',
            EMAIL_HOST_PASSWORD='pw',
        ), patch('apps.core.services.MailBox') as mock_mailbox_class:
            mock_mailbox = MagicMock()
            mock_mailbox.fetch.return_value = [mock_msg]
            mock_mailbox.__enter__.return_value = mock_mailbox
            mock_mailbox_class.return_value.login.return_value = mock_mailbox

            response = self.client.get(f'/api/emails/{self.email.pk}/')

        self.assertEqual(response.status_code, 200)
        attachments = response.data['content']['attachments']
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]['filename'], 'photo.jpg')
        self.assertEqual(attachments[0]['content_type'], 'image/jpeg')
        self.assertEqual(attachments[0]['size'], len(binary_payload))
        # Raw bytes must NOT be in the API response.
        self.assertNotIn('payload', attachments[0])

    def test_snippet_from_html_when_text_missing(self):
        self.temp_email.text_body = ''
        self.temp_email.html_body = '<p>Quick note: <strong>50 units</strong>.</p>'
        self.temp_email.save()

        response = self.client.get(f'/api/emails/{self.email.pk}/')
        self.assertEqual(response.status_code, 200)
        snippet = response.data['snippet']
        self.assertIn('Quick note', snippet)
        self.assertIn('50 units', snippet)
        self.assertNotIn('<', snippet)
        self.assertNotIn('>', snippet)
