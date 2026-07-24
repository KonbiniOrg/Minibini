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
        self.assertEqual(response.data['direction'], EmailRecord.INBOUND)
        self.assertEqual(response.data['display_address'], 'sender@example.com')
        # Snippet comes from text_body, with sign-off + signature line stripped
        # by extract_email_body via strip_quoted_reply downstream callers; for
        # the snippet path we just strip the quoted-reply markers, so the
        # "Thanks,\nJane" tail survives until the regex truncation kicks in.
        # Verify we got the body content (not the raw cached_body with newlines).
        self.assertIn("Sounds good", response.data['snippet'])
        self.assertNotIn('\n', response.data['snippet'])

    def test_outbound_email_reports_outbound_direction(self):
        """An outbound EmailRecord reflects 'outbound' in the serializer."""
        outbound = EmailRecord.objects.create(
            message_id='<outbound-direction@example.com>',
            direction=EmailRecord.OUTBOUND,
        )
        response = self.client.get(f'/api/emails/{outbound.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['direction'], EmailRecord.OUTBOUND)

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

    def test_email_detail_includes_contact_links_for_known_addresses(self):
        """From/To/CC addresses that match a known Contact come through as
        contact_links so the SPA can render them as links."""
        from apps.contacts.models import Contact
        jane = Contact.objects.create(
            first_name='Jane', last_name='Doe', email='jane@example.com',
            mobile_number='555-1',
        )
        bob = Contact.objects.create(
            first_name='Bob', last_name='Smith', email='bob@example.com',
            mobile_number='555-2',
        )
        content = self._mock_email_content(
            from_header='Jane Doe <jane@example.com>',
        )
        content['to'] = ['us@example.com']
        content['cc'] = ['Bob Smith <bob@example.com>', 'stranger@nowhere.com']
        with patch('apps.api.email.views.EmailService') as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_email_content.return_value = content
            mock_service_class.return_value = mock_service

            response = self.client.get(f'/api/emails/{self.email.pk}/')

        self.assertEqual(response.status_code, 200)
        links = response.data['contact_links']
        self.assertIn('jane@example.com', links)
        self.assertEqual(links['jane@example.com']['contact_id'], jane.contact_id)
        self.assertEqual(links['jane@example.com']['name'], 'Jane Doe')
        self.assertIn('bob@example.com', links)
        self.assertEqual(links['bob@example.com']['contact_id'], bob.contact_id)
        # Stranger has no Contact row → not in the map.
        self.assertNotIn('stranger@nowhere.com', links)
        # Our own address — no Contact → not in the map either.
        self.assertNotIn('us@example.com', links)

    def test_email_detail_contact_links_when_imap_unavailable(self):
        """Even when IMAP content can't be fetched, the response should still
        resolve contact_links from the TempEmail metadata."""
        from apps.contacts.models import Contact
        jane = Contact.objects.create(
            first_name='Jane', last_name='Doe', email='sender@example.com',
            mobile_number='555-3',
        )
        with patch('apps.api.email.views.EmailService') as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_email_content.return_value = None
            mock_service_class.return_value = mock_service

            response = self.client.get(f'/api/emails/{self.email.pk}/')

        self.assertEqual(response.status_code, 200)
        # temp_email.from_email is 'sender@example.com' from setUp.
        links = response.data['contact_links']
        self.assertIn('sender@example.com', links)
        self.assertEqual(links['sender@example.com']['contact_id'], jane.contact_id)

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


class EmailPoAPITest(BaseTestCase):
    """Coverage for the PO link-unlink + create-po endpoints."""

    def setUp(self):
        super().setUp()
        from apps.contacts.models import Contact, Business
        from apps.purchasing.models import PurchaseOrder
        self.client = APIClient()
        self.admin = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.admin)
        self.email = EmailRecord.objects.create(message_id='<po-link@example.com>')
        self.contact = Contact.objects.create(
            first_name='Vendor', last_name='Sales',
            email='sales@vendor.com', mobile_number='555-9',
        )
        self.business = Business.objects.create(
            business_name='Vendor Inc.', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.po = PurchaseOrder.objects.create(
            po_number='PO-API-1', business=self.business,
        )

    # --- link/unlink PO ----------------------------------------------------

    def test_link_to_po(self):
        response = self.client.post(
            f'/api/emails/{self.email.pk}/link-to-po/',
            {'po_id': self.po.pk}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.email.refresh_from_db()
        self.assertEqual(self.email.purchase_order_id, self.po.pk)

    def test_link_to_po_missing_po_id(self):
        response = self.client.post(
            f'/api/emails/{self.email.pk}/link-to-po/', {}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_link_to_po_rejects_non_integer(self):
        response = self.client.post(
            f'/api/emails/{self.email.pk}/link-to-po/',
            {'po_id': 'not-a-number'}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_link_to_po_target_not_found(self):
        response = self.client.post(
            f'/api/emails/{self.email.pk}/link-to-po/',
            {'po_id': 99999}, format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_unlink_from_po(self):
        self.email.purchase_order = self.po
        self.email.save()
        response = self.client.post(f'/api/emails/{self.email.pk}/unlink-from-po/')
        self.assertEqual(response.status_code, 200)
        self.email.refresh_from_db()
        self.assertIsNone(self.email.purchase_order)

    def test_link_to_po_requires_can_manage_financials(self):
        worker = User.objects.create_user(username='worker_po', password='pw')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/emails/{self.email.pk}/link-to-po/',
            {'po_id': self.po.pk}, format='json',
        )
        self.assertEqual(response.status_code, 403)

    # --- create PO from email ---------------------------------------------

    def test_create_po_from_email(self):
        response = self.client.post(
            f'/api/emails/{self.email.pk}/create-po/',
            {'vendor_business_id': self.business.pk}, format='json',
        )
        self.assertEqual(response.status_code, 201)
        from apps.purchasing.models import PurchaseOrder
        po = PurchaseOrder.objects.get(pk=response.data['po_id'])
        self.assertEqual(po.business, self.business)
        self.email.refresh_from_db()
        self.assertEqual(self.email.purchase_order, po)
        self.assertEqual(response.data['po_number'], po.po_number)

    def test_create_po_missing_vendor(self):
        response = self.client.post(
            f'/api/emails/{self.email.pk}/create-po/', {}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_create_po_vendor_not_found(self):
        response = self.client.post(
            f'/api/emails/{self.email.pk}/create-po/',
            {'vendor_business_id': 99999}, format='json',
        )
        # 400 from validation OR 404 — depending on service shape. Accept either.
        self.assertIn(response.status_code, (400, 404))

    def test_create_po_requires_can_manage_financials(self):
        worker = User.objects.create_user(username='worker_create_po', password='pw')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/emails/{self.email.pk}/create-po/',
            {'vendor_business_id': self.business.pk}, format='json',
        )
        self.assertEqual(response.status_code, 403)

    # --- serializer surface -----------------------------------------------

    def test_email_list_exposes_po(self):
        self.email.purchase_order = self.po
        self.email.save()
        response = self.client.get(f'/api/emails/{self.email.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['purchase_order'], self.po.pk)
        self.assertEqual(response.data['po_number'], self.po.po_number)


class EmailReplyAPITest(BaseTestCase):
    """Coverage for /api/emails/{id}/reply-defaults/ and /reply/ endpoints."""

    def setUp(self):
        super().setUp()
        from django.utils import timezone as tz
        from datetime import datetime
        from django.utils.timezone import make_aware
        from apps.contacts.models import Contact, Business
        from apps.jobs.models import Job
        self.client = APIClient()
        self.admin = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.admin)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@customer.com', mobile_number='555',
        )
        self.business = Business.objects.create(
            business_name='Customer Co', default_contact=self.contact,
        )
        self.job = Job.objects.create(
            job_number='JOB-REPLY-1', contact=self.contact, description='X',
        )
        # Parent inbound email, linked to a Job, with a populated body.
        self.parent = EmailRecord.objects.create(
            message_id='<parent-msg@example.com>',
            job=self.job,
        )
        self.parent_temp = TempEmail.objects.create(
            email_record=self.parent,
            uid='1',
            subject='Re: Quote for bracket',
            from_email='Jane Doe <jane@customer.com>',
            to_email='us@example.com',
            cc_email='proc@customer.com, ops@customer.com',
            date_sent=make_aware(datetime(2026, 5, 28, 9, 32)),
            text_body='Hi,\n\nCould you quote 50 brackets?\n',
            in_reply_to='',
            references='<thread-root@example.com>',
        )

    # --- reply-defaults ---------------------------------------------------

    def test_reply_defaults_shape(self):
        response = self.client.get(f'/api/emails/{self.parent.pk}/reply-defaults/')
        self.assertEqual(response.status_code, 200, response.data)
        for key in ('to', 'cc', 'bcc', 'reply_all_cc', 'subject', 'body',
                    'in_reply_to', 'references', 'inherit_associations'):
            self.assertIn(key, response.data)

    def test_reply_defaults_to_and_subject(self):
        response = self.client.get(f'/api/emails/{self.parent.pk}/reply-defaults/')
        self.assertEqual(response.data['to'], 'jane@customer.com')
        # Subject is Re-prefixed exactly once (the parent was already 'Re: ...').
        self.assertEqual(response.data['subject'], 'Re: Quote for bracket')

    def test_reply_defaults_body_contains_quoted_original(self):
        response = self.client.get(f'/api/emails/{self.parent.pk}/reply-defaults/')
        body = response.data['body']
        self.assertTrue(body.startswith('\n\n'))
        self.assertIn('wrote:', body)
        self.assertIn('> Could you quote 50 brackets?', body)

    def test_reply_defaults_threading_headers(self):
        response = self.client.get(f'/api/emails/{self.parent.pk}/reply-defaults/')
        self.assertEqual(response.data['in_reply_to'], '<parent-msg@example.com>')
        # References extends parent's references with parent's message_id.
        self.assertIn('<thread-root@example.com>', response.data['references'])
        self.assertIn('<parent-msg@example.com>', response.data['references'])

    def test_reply_defaults_inherit_associations(self):
        response = self.client.get(f'/api/emails/{self.parent.pk}/reply-defaults/')
        ia = response.data['inherit_associations']
        self.assertEqual(ia['job'], self.job.job_id)
        self.assertIsNone(ia['purchase_order'])

    def test_reply_defaults_reply_all_cc_strips_our_address(self):
        from django.test.utils import override_settings
        with override_settings(EMAIL_HOST_USER='us@example.com'):
            response = self.client.get(f'/api/emails/{self.parent.pk}/reply-defaults/')
        # parent's to was 'us@example.com' (ours, stripped); cc was two
        # addresses (preserved). Result: just the two CC addresses.
        rac = response.data['reply_all_cc']
        self.assertIn('proc@customer.com', rac)
        self.assertIn('ops@customer.com', rac)
        self.assertNotIn('us@example.com', rac)

    def test_reply_defaults_reply_all_cc_dedupes(self):
        from django.test.utils import override_settings
        self.parent_temp.to_email = 'jane@customer.com, us@example.com'
        self.parent_temp.cc_email = 'jane@customer.com, ops@customer.com'
        self.parent_temp.save()
        with override_settings(EMAIL_HOST_USER='us@example.com'):
            response = self.client.get(f'/api/emails/{self.parent.pk}/reply-defaults/')
        rac = response.data['reply_all_cc']
        # jane appears twice in source; only once in result.
        self.assertEqual(rac.count('jane@customer.com'), 1)
        self.assertNotIn('us@example.com', rac)
        self.assertIn('ops@customer.com', rac)

    def test_reply_defaults_no_text_body_falls_back_to_placeholder(self):
        self.parent_temp.text_body = ''
        self.parent_temp.save()
        response = self.client.get(f'/api/emails/{self.parent.pk}/reply-defaults/')
        self.assertIn('> (original message unavailable)', response.data['body'])

    def test_reply_defaults_404_for_unknown_email(self):
        response = self.client.get('/api/emails/99999/reply-defaults/')
        self.assertEqual(response.status_code, 404)

    # --- reply (send) -----------------------------------------------------

    @patch('django.core.mail.EmailMessage')
    def test_reply_happy_path(self, MockEmailMessage):
        MockEmailMessage.return_value = MagicMock()

        response = self.client.post(
            f'/api/emails/{self.parent.pk}/reply/',
            {
                'to': 'jane@customer.com',
                'cc': '',
                'bcc': '',
                'subject': 'Re: Quote for bracket',
                'body': 'Yes please, send invoice.',
                'in_reply_to': '<parent-msg@example.com>',
                'references': '<thread-root@example.com> <parent-msg@example.com>',
                'inherit_job': str(self.job.job_id),
            },
            format='multipart',
        )
        self.assertEqual(response.status_code, 200, response.data)

        outbound = EmailRecord.objects.get(
            direction=EmailRecord.OUTBOUND, job=self.job,
        )
        self.assertIsNotNone(outbound.sent_at)
        temp = outbound.temp_data
        self.assertEqual(temp.in_reply_to, '<parent-msg@example.com>')
        self.assertIn('<parent-msg@example.com>', temp.references)

    @patch('django.core.mail.EmailMessage')
    def test_reply_with_cc_persists_addresses(self, MockEmailMessage):
        """Covers the Reply-All path — same endpoint, just CC populated."""
        MockEmailMessage.return_value = MagicMock()
        response = self.client.post(
            f'/api/emails/{self.parent.pk}/reply/',
            {
                'to': 'jane@customer.com',
                'cc': 'proc@customer.com, ops@customer.com',
                'bcc': '',
                'subject': 'Re: Quote',
                'body': 'Body',
                'inherit_job': str(self.job.job_id),
            },
            format='multipart',
        )
        self.assertEqual(response.status_code, 200, response.data)
        outbound = EmailRecord.objects.get(
            direction=EmailRecord.OUTBOUND, job=self.job,
        )
        self.assertIn('proc@customer.com', outbound.temp_data.cc_email)
        self.assertIn('ops@customer.com', outbound.temp_data.cc_email)

    @patch('django.core.mail.EmailMessage')
    def test_reply_with_attachment(self, MockEmailMessage):
        from django.core.files.uploadedfile import SimpleUploadedFile
        MockEmailMessage.return_value = MagicMock()
        upload = SimpleUploadedFile(
            'drawing.png', b'\x89PNG-fake', content_type='image/png',
        )
        response = self.client.post(
            f'/api/emails/{self.parent.pk}/reply/',
            {
                'to': 'jane@customer.com',
                'subject': 'Re: Quote',
                'body': 'See attached.',
                'attachments': upload,
                'inherit_job': str(self.job.job_id),
            },
            format='multipart',
        )
        self.assertEqual(response.status_code, 200, response.data)
        outbound = EmailRecord.objects.get(
            direction=EmailRecord.OUTBOUND, job=self.job,
        )
        self.assertTrue(outbound.temp_data.has_attachments)
        names = [a['filename'] for a in outbound.temp_data.attachments_metadata]
        self.assertIn('drawing.png', names)

    @patch('django.core.mail.EmailMessage')
    def test_reply_inherits_no_association_when_parent_unlinked(self, MockEmailMessage):
        # Replace the parent with one that's not linked to anything.
        unlinked = EmailRecord.objects.create(message_id='<unlinked@example.com>')
        TempEmail.objects.create(
            email_record=unlinked, uid='2',
            from_email='someone@example.com', to_email='us@example.com',
            date_sent=self.parent_temp.date_sent,
        )
        MockEmailMessage.return_value = MagicMock()
        response = self.client.post(
            f'/api/emails/{unlinked.pk}/reply/',
            {'to': 'someone@example.com', 'subject': 'Re:', 'body': '.'},
            format='multipart',
        )
        self.assertEqual(response.status_code, 200, response.data)
        outbound = EmailRecord.objects.filter(
            direction=EmailRecord.OUTBOUND, message_id__startswith='<minibini-',
        ).order_by('-created_at').first()
        self.assertIsNone(outbound.job)
        self.assertIsNone(outbound.purchase_order)

    def test_reply_missing_to_returns_400(self):
        response = self.client.post(
            f'/api/emails/{self.parent.pk}/reply/',
            {'subject': 'Re:', 'body': 'X'},
            format='multipart',
        )
        self.assertEqual(response.status_code, 400)

    @patch('django.core.mail.EmailMessage')
    def test_reply_smtp_failure_returns_502_and_persists_error(self, MockEmailMessage):
        fail_msg = MagicMock()
        fail_msg.send.side_effect = RuntimeError('connection refused')
        MockEmailMessage.return_value = fail_msg

        response = self.client.post(
            f'/api/emails/{self.parent.pk}/reply/',
            {
                'to': 'jane@customer.com',
                'subject': 'Re:', 'body': 'X',
                'inherit_job': str(self.job.job_id),
            },
            format='multipart',
        )
        self.assertEqual(response.status_code, 502)
        outbound = EmailRecord.objects.get(
            direction=EmailRecord.OUTBOUND, job=self.job,
        )
        self.assertIsNone(outbound.sent_at)
        self.assertIn('connection refused', outbound.last_send_error)


class ThreadPropagationAPITest(BaseTestCase):
    """End-to-end: linking or creating-from-email any one email in a
    thread cascades the new association to the rest of the thread."""

    def setUp(self):
        super().setUp()
        from apps.contacts.models import Contact, Business
        self.client = APIClient()
        self.admin = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.admin)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@customer.com', mobile_number='555',
        )
        self.business = Business.objects.create(
            business_name='Customer Co', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

    def _thread(self, n=3):
        """Create a linear thread of n emails."""
        from django.utils import timezone as tz
        emails = []
        for i in range(n):
            mid = f'<prop-{i}@example.com>'
            irt = f'<prop-{i-1}@example.com>' if i > 0 else ''
            refs = ' '.join(f'<prop-{j}@example.com>' for j in range(i)) if i > 0 else ''
            er = EmailRecord.objects.create(message_id=mid)
            TempEmail.objects.create(
                email_record=er,
                uid=f'p{i}',
                from_email='jane@customer.com', to_email='us@example.com',
                date_sent=tz.now(),
                in_reply_to=irt, references=refs,
            )
            emails.append(er)
        return emails

    def test_link_to_job_propagates_to_thread_siblings(self):
        e1, e2, e3 = self._thread(3)
        job = Job.objects.first()

        response = self.client.post(
            f'/api/emails/{e3.pk}/link-to-job/',
            {'job_id': job.pk}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

        e1.refresh_from_db(); e2.refresh_from_db(); e3.refresh_from_db()
        self.assertEqual(e1.job, job)
        self.assertEqual(e2.job, job)
        self.assertEqual(e3.job, job)

    def test_link_to_po_propagates(self):
        from apps.purchasing.models import PurchaseOrder
        e1, e2, e3 = self._thread(3)
        po = PurchaseOrder.objects.create(
            po_number='PO-PROP-API-1', business=self.business,
        )

        response = self.client.post(
            f'/api/emails/{e2.pk}/link-to-po/',
            {'po_id': po.pk}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

        e1.refresh_from_db(); e2.refresh_from_db(); e3.refresh_from_db()
        self.assertEqual(e1.purchase_order, po)
        self.assertEqual(e2.purchase_order, po)
        self.assertEqual(e3.purchase_order, po)

    def test_create_po_from_email_propagates(self):
        e1, e2, e3 = self._thread(3)

        response = self.client.post(
            f'/api/emails/{e3.pk}/create-po/',
            {'vendor_business_id': self.business.pk}, format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        new_po_id = response.data['po_id']

        e1.refresh_from_db(); e2.refresh_from_db(); e3.refresh_from_db()
        self.assertEqual(e1.purchase_order_id, new_po_id)
        self.assertEqual(e2.purchase_order_id, new_po_id)
        self.assertEqual(e3.purchase_order_id, new_po_id)

    def test_pre_existing_link_to_different_job_is_preserved(self):
        """If a sibling is already linked to Job A, linking another email
        in the same thread to Job B leaves the sibling alone."""
        e1, e2, e3 = self._thread(3)
        job_a = Job.objects.first()
        job_b = Job.objects.exclude(pk=job_a.pk).first()
        self.assertIsNotNone(job_b, 'fixture must provide at least 2 jobs')

        # E1 already linked to job_a.
        e1.job = job_a
        e1.save()

        # User now links e3 to job_b.
        response = self.client.post(
            f'/api/emails/{e3.pk}/link-to-job/',
            {'job_id': job_b.pk}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

        e1.refresh_from_db(); e2.refresh_from_db(); e3.refresh_from_db()
        self.assertEqual(e1.job, job_a, 'pre-existing link must stay')
        self.assertEqual(e2.job, job_b)
        self.assertEqual(e3.job, job_b)
