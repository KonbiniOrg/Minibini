from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from apps.core.services import OutboundEmailService
from apps.core.models import EmailRecord, TempEmail, Configuration
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job

class SendTrackedTest(TestCase):
    """OutboundEmailService.send_tracked persists outbound EmailRecord +
    TempEmail, generates a Message-ID, attempts SMTP, records outcome."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555',
        )
        self.business = Business.objects.create(
            business_name='Acme Co', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(
            job_number='JOB-OUT-1', contact=self.contact, description='Test',
        )

    @patch('django.core.mail.EmailMessage')
    def test_send_tracked_persists_outbound_email_record(self, MockEmailMessage):
        MockEmailMessage.return_value = MagicMock()

        record = OutboundEmailService.send_tracked(
            to=['jane@example.com'],
            subject='Estimate EST-001',
            body='Hi Jane.\nPlease review.',
            associate_with={'job': self.job},
        )

        self.assertEqual(record.direction, EmailRecord.OUTBOUND)
        self.assertEqual(record.job, self.job)
        self.assertIsNotNone(record.sent_at)
        self.assertEqual(record.last_send_error, '')
        self.assertTrue(record.message_id.startswith('<minibini-'))

        temp = TempEmail.objects.get(email_record=record)
        self.assertEqual(temp.subject, 'Estimate EST-001')
        self.assertEqual(temp.to_email, 'jane@example.com')
        self.assertEqual(temp.text_body, 'Hi Jane.\nPlease review.')

    @patch('django.core.mail.EmailMessage')
    def test_send_tracked_uses_our_domain_from_config(self, MockEmailMessage):
        MockEmailMessage.return_value = MagicMock()
        Configuration.objects.create(key='our_domain', value='nealscnc.com')
        record = OutboundEmailService.send_tracked(
            to=['jane@example.com'],
            subject='Test', body='Body',
            associate_with={'job': self.job},
        )
        self.assertTrue(record.message_id.endswith('@nealscnc.com>'),
                        f'message_id={record.message_id}')

    @patch('django.core.mail.EmailMessage')
    def test_send_tracked_falls_back_to_example_com(self, MockEmailMessage):
        MockEmailMessage.return_value = MagicMock()
        # No 'our_domain' Configuration row exists.
        record = OutboundEmailService.send_tracked(
            to=['jane@example.com'],
            subject='Test', body='Body',
            associate_with={'job': self.job},
        )
        self.assertTrue(record.message_id.endswith('@example.com>'),
                        f'message_id={record.message_id}')

    @patch('django.core.mail.EmailMessage')
    def test_send_tracked_smtp_failure_persists_error(self, MockEmailMessage):
        fail_msg = MagicMock()
        fail_msg.send.side_effect = RuntimeError('connection refused')
        MockEmailMessage.return_value = fail_msg

        with self.assertRaises(RuntimeError):
            OutboundEmailService.send_tracked(
                to=['jane@example.com'],
                subject='Test', body='Body',
                associate_with={'job': self.job},
            )

        record = EmailRecord.objects.get(direction=EmailRecord.OUTBOUND)
        self.assertIsNone(record.sent_at)
        self.assertIn('connection refused', record.last_send_error)
        self.assertEqual(record.job, self.job)

    @patch('django.core.mail.EmailMessage')
    def test_send_tracked_retry_reuses_failed_row(self, MockEmailMessage):
        # First attempt fails.
        fail_msg = MagicMock()
        fail_msg.send.side_effect = RuntimeError('blip')
        MockEmailMessage.return_value = fail_msg
        with self.assertRaises(RuntimeError):
            OutboundEmailService.send_tracked(
                to=['jane@example.com'],
                subject='Sub1', body='Body1',
                associate_with={'job': self.job},
            )
        first_record = EmailRecord.objects.get(direction=EmailRecord.OUTBOUND)
        original_message_id = first_record.message_id

        # Second attempt succeeds — but the user edited the body.
        MockEmailMessage.return_value = MagicMock()
        second = OutboundEmailService.send_tracked(
            to=['jane@example.com'],
            subject='Sub2', body='Body2',
            associate_with={'job': self.job},
        )

        self.assertEqual(second.email_record_id, first_record.email_record_id,
                         'retry should reuse the same EmailRecord row')
        self.assertEqual(second.message_id, original_message_id,
                         'message_id should be preserved across retries')
        self.assertIsNotNone(second.sent_at)
        self.assertEqual(second.last_send_error, '')
        temp = TempEmail.objects.get(email_record=second)
        self.assertEqual(temp.subject, 'Sub2')
        self.assertEqual(temp.text_body, 'Body2')

    @patch('django.core.mail.EmailMessage')
    def test_send_tracked_stores_attachments_metadata(self, MockEmailMessage):
        MockEmailMessage.return_value = MagicMock()
        record = OutboundEmailService.send_tracked(
            to=['jane@example.com'],
            subject='Sub', body='Body',
            attachments=[
                ('Estimate-001.pdf', b'%PDF-1', 'application/pdf'),
                ('drawing.png', b'\x89PNG-1', 'image/png'),
            ],
            associate_with={'job': self.job},
        )
        temp = TempEmail.objects.get(email_record=record)
        self.assertTrue(temp.has_attachments)
        self.assertEqual(temp.attachments_metadata, [
            {'filename': 'Estimate-001.pdf', 'content_type': 'application/pdf', 'size': len(b'%PDF-1')},
            {'filename': 'drawing.png', 'content_type': 'image/png', 'size': len(b'\x89PNG-1')},
        ])

    @patch('django.core.mail.EmailMessage')
    def test_send_tracked_threading_headers_flow_through(self, MockEmailMessage):
        mock_msg = MagicMock()
        mock_msg.extra_headers = {}
        MockEmailMessage.return_value = mock_msg

        record = OutboundEmailService.send_tracked(
            to=['jane@example.com'],
            subject='Re: Quote', body='Yes please.',
            associate_with={'job': self.job},
            in_reply_to='<parent-msg@example.com>',
            references='<root@example.com> <parent-msg@example.com>',
        )

        # Headers set on the outgoing message.
        self.assertEqual(mock_msg.extra_headers.get('In-Reply-To'),
                         '<parent-msg@example.com>')
        self.assertEqual(mock_msg.extra_headers.get('References'),
                         '<root@example.com> <parent-msg@example.com>')

        # Persisted on the outbound TempEmail.
        temp = TempEmail.objects.get(email_record=record)
        self.assertEqual(temp.in_reply_to, '<parent-msg@example.com>')
        self.assertEqual(temp.references,
                         '<root@example.com> <parent-msg@example.com>')

    @patch('django.core.mail.EmailMessage')
    def test_send_tracked_threading_kwargs_default_to_empty(self, MockEmailMessage):
        """Existing document-send callers pass neither kwarg; nothing changes."""
        mock_msg = MagicMock()
        mock_msg.extra_headers = {}
        MockEmailMessage.return_value = mock_msg

        record = OutboundEmailService.send_tracked(
            to=['jane@example.com'],
            subject='Sub', body='Body',
            associate_with={'job': self.job},
        )

        self.assertNotIn('In-Reply-To', mock_msg.extra_headers)
        self.assertNotIn('References', mock_msg.extra_headers)
        temp = TempEmail.objects.get(email_record=record)
        self.assertEqual(temp.in_reply_to, '')
        self.assertEqual(temp.references, '')


class CorrelateReplyTest(TestCase):
    """EmailService.correlate_reply walks In-Reply-To / References against
    existing EmailRecord.message_id and copies the parent's FK associations."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Bob', last_name='Smith',
            email='bob@example.com', mobile_number='555',
        )
        self.business = Business.objects.create(
            business_name='Acme', default_contact=self.contact,
        )
        self.job = Job.objects.create(
            job_number='JOB-CORR-1', contact=self.contact, description='X',
        )

    def _create_inbound(self, message_id, *, in_reply_to='', references=''):
        record = EmailRecord.objects.create(message_id=message_id)
        TempEmail.objects.create(
            email_record=record,
            uid=message_id.replace('<', '').replace('>', '')[:10],
            from_email='bob@example.com',
            to_email='us@example.com',
            date_sent=timezone.now(),
            in_reply_to=in_reply_to,
            references=references,
        )
        return record

    def test_in_reply_to_match_copies_parent_job(self):
        from apps.core.services import EmailService
        parent = EmailRecord.objects.create(
            message_id='<parent@example.com>', job=self.job,
        )
        reply = self._create_inbound(
            '<reply@example.com>', in_reply_to='<parent@example.com>',
        )
        EmailService.correlate_reply(reply)
        reply.refresh_from_db()
        self.assertEqual(reply.job, self.job)

    def test_references_chain_match_copies_parent_job(self):
        from apps.core.services import EmailService
        EmailRecord.objects.create(
            message_id='<root@example.com>', job=self.job,
        )
        reply = self._create_inbound(
            '<reply@example.com>',
            references='<root@example.com> <middle@example.com>',
        )
        EmailService.correlate_reply(reply)
        reply.refresh_from_db()
        self.assertEqual(reply.job, self.job)

    def test_no_match_leaves_reply_unassociated(self):
        from apps.core.services import EmailService
        reply = self._create_inbound(
            '<orphan@example.com>', in_reply_to='<unknown@example.com>',
        )
        EmailService.correlate_reply(reply)
        reply.refresh_from_db()
        self.assertIsNone(reply.job)
        self.assertIsNone(reply.purchase_order)

    def test_in_reply_to_wins_over_conflicting_references(self):
        """When In-Reply-To and References point to differently-associated
        parents, In-Reply-To (the immediate parent) wins."""
        from apps.core.services import EmailService
        other_job = Job.objects.create(
            job_number='JOB-CORR-2', contact=self.contact, description='Y',
        )
        # Root is linked to other_job; immediate parent is linked to self.job.
        EmailRecord.objects.create(message_id='<root@example.com>', job=other_job)
        EmailRecord.objects.create(message_id='<parent@example.com>', job=self.job)
        reply = self._create_inbound(
            '<reply@example.com>',
            in_reply_to='<parent@example.com>',
            references='<root@example.com> <parent@example.com>',
        )
        EmailService.correlate_reply(reply)
        reply.refresh_from_db()
        self.assertEqual(reply.job, self.job)

    def test_copies_both_associations(self):
        from apps.core.services import EmailService
        from apps.purchasing.models import PurchaseOrder
        po = PurchaseOrder.objects.create(po_number='PO-CORR', business=self.business)
        EmailRecord.objects.create(
            message_id='<multi@example.com>',
            job=self.job, purchase_order=po,
        )
        reply = self._create_inbound(
            '<reply@example.com>', in_reply_to='<multi@example.com>',
        )
        EmailService.correlate_reply(reply)
        reply.refresh_from_db()
        self.assertEqual(reply.job, self.job)
        self.assertEqual(reply.purchase_order, po)


class IMAPFetchPopulatesHeadersAndCorrelatesTest(TestCase):
    """Integration test: fetch_new_emails captures In-Reply-To/References
    onto TempEmail and runs the correlation pass on each new inbound."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Bob', last_name='Smith',
            email='bob@example.com', mobile_number='555',
        )
        self.business = Business.objects.create(
            business_name='Acme', default_contact=self.contact,
        )
        self.job = Job.objects.create(
            job_number='JOB-FETCH-1', contact=self.contact, description='Z',
        )
        # Existing outbound we previously sent.
        self.outbound = EmailRecord.objects.create(
            message_id='<outbound-by-us@example.com>',
            direction=EmailRecord.OUTBOUND,
            job=self.job,
        )

    @patch('apps.core.services.MailBox')
    def test_fetch_captures_headers_and_correlates_reply(self, mock_mailbox_class):
        from django.test.utils import override_settings
        # Mock IMAP message that's a reply to our outbound.
        mock_msg = MagicMock()
        mock_msg.uid = '99999'
        mock_msg.headers = {
            'message-id': ['<customer-reply@example.com>'],
            'in-reply-to': ['<outbound-by-us@example.com>'],
            'references': ['<outbound-by-us@example.com>'],
        }
        mock_msg.subject = 'Re: Quote'
        mock_msg.from_ = 'bob@example.com'
        mock_msg.to = ['us@example.com']
        mock_msg.cc = []
        mock_msg.date = timezone.now()
        mock_msg.text = 'Thanks — yes please proceed.'
        mock_msg.html = ''
        mock_msg.attachments = []

        mock_mailbox = MagicMock()
        mock_mailbox.fetch.return_value = [mock_msg]
        mock_mailbox.__enter__.return_value = mock_mailbox
        mock_mailbox_class.return_value.login.return_value = mock_mailbox

        with override_settings(
            EMAIL_IMAP_SERVER='imap.example.com',
            EMAIL_HOST_USER='us@example.com',
            EMAIL_HOST_PASSWORD='pw',
        ):
            service = OutboundEmailService  # for clarity; we use EmailService
            from apps.core.services import EmailService
            stats = EmailService().fetch_new_emails()

        self.assertEqual(stats['new'], 1)
        reply = EmailRecord.objects.get(message_id='<customer-reply@example.com>')
        # Headers captured
        self.assertEqual(reply.temp_data.in_reply_to, '<outbound-by-us@example.com>')
        # Correlated to the same Job as the outbound parent
        self.assertEqual(reply.job, self.job)

    @patch('apps.core.services.MailBox')
    def test_correlation_propagates_to_orphaned_sibling(self, mock_mailbox_class):
        """When correlate_reply links a new inbound, the propagation step
        sweeps up any thread sibling that's still orphaned — closes the
        gap that existed when only the new arrival was linked."""
        from django.test.utils import override_settings

        # An earlier inbound, somehow unlinked (the bug we're closing).
        orphan = EmailRecord.objects.create(message_id='<orphan@example.com>')
        TempEmail.objects.create(
            email_record=orphan,
            uid='orph',
            from_email='bob@example.com', to_email='us@example.com',
            date_sent=timezone.now(),
            in_reply_to='<outbound-by-us@example.com>',
            references='<outbound-by-us@example.com>',
        )

        # New inbound arrives, replying to the same outbound.
        mock_msg = MagicMock()
        mock_msg.uid = '99998'
        mock_msg.headers = {
            'message-id': ['<new-reply@example.com>'],
            'in-reply-to': ['<orphan@example.com>'],
            'references': ['<outbound-by-us@example.com> <orphan@example.com>'],
        }
        mock_msg.subject = 'Re: Quote'
        mock_msg.from_ = 'bob@example.com'
        mock_msg.to = ['us@example.com']
        mock_msg.cc = []
        mock_msg.date = timezone.now()
        mock_msg.text = ''
        mock_msg.html = ''
        mock_msg.attachments = []

        mock_mailbox = MagicMock()
        mock_mailbox.fetch.return_value = [mock_msg]
        mock_mailbox.__enter__.return_value = mock_mailbox
        mock_mailbox_class.return_value.login.return_value = mock_mailbox

        with override_settings(
            EMAIL_IMAP_SERVER='imap.example.com',
            EMAIL_HOST_USER='us@example.com',
            EMAIL_HOST_PASSWORD='pw',
        ):
            from apps.core.services import EmailService
            EmailService().fetch_new_emails()

        new_reply = EmailRecord.objects.get(message_id='<new-reply@example.com>')
        self.assertEqual(new_reply.job, self.job, 'new arrival gets Job')

        orphan.refresh_from_db()
        self.assertEqual(orphan.job, self.job, 'orphaned sibling swept up too')
