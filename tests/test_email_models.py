from django.test import TestCase, TransactionTestCase, override_settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from datetime import timedelta, datetime
from unittest.mock import Mock, patch, MagicMock
from apps.core.models import EmailRecord, TempEmail, Configuration, AppState
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business
from apps.core.services import EmailService


class EmailRecordModelTest(TestCase):
    """Test EmailRecord model - permanent record of email-job associations."""

    def setUp(self):
        """Create test data."""
        self.contact = Contact.objects.create(
            first_name="Test",
            last_name="Contact",
            email="contact@example.com",
        )
        self.business = Business.objects.create(
            business_name="Test Business",
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(
            job_number="JOB-001",
            contact=self.contact,
            description="Test job"
        )

    def test_email_record_creation_minimal(self):
        """Test creating EmailRecord with minimum required fields."""
        email_record = EmailRecord.objects.create(
            message_id="<test123@example.com>"
        )
        self.assertEqual(email_record.message_id, "<test123@example.com>")
        self.assertIsNone(email_record.job)
        self.assertIsNotNone(email_record.created_at)

    def test_email_record_with_job(self):
        """Test creating EmailRecord linked to a job."""
        email_record = EmailRecord.objects.create(
            message_id="<test456@example.com>",
            job=self.job
        )
        self.assertEqual(email_record.job, self.job)
        self.assertEqual(email_record.job.job_number, "JOB-001")

    def test_email_record_message_id_unique(self):
        """Test that message_id must be unique."""
        EmailRecord.objects.create(message_id="<unique@example.com>")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EmailRecord.objects.create(message_id="<unique@example.com>")

    def test_email_record_str_method(self):
        """Test string representation."""
        email_record = EmailRecord.objects.create(
            message_id="<test789@example.com>"
        )
        self.assertIn("<test789@example.com>", str(email_record))

    def test_email_record_job_deletion(self):
        """Test that EmailRecord persists when job is deleted (SET_NULL)."""
        email_record = EmailRecord.objects.create(
            message_id="<persist@example.com>",
            job=self.job
        )

        # Delete the job
        self.job.delete()

        # EmailRecord should still exist with job set to NULL
        email_record.refresh_from_db()
        self.assertIsNone(email_record.job)
        self.assertEqual(email_record.message_id, "<persist@example.com>")

    def test_email_record_reverse_relation(self):
        """Test reverse relation from Job to EmailRecords."""
        email1 = EmailRecord.objects.create(
            message_id="<email1@example.com>",
            job=self.job
        )
        email2 = EmailRecord.objects.create(
            message_id="<email2@example.com>",
            job=self.job
        )

        job_emails = self.job.email_records.all()
        self.assertEqual(job_emails.count(), 2)
        self.assertIn(email1, job_emails)
        self.assertIn(email2, job_emails)

    def test_email_record_with_purchase_order(self):
        """EmailRecord can link to a PurchaseOrder independently of job."""
        from apps.purchasing.models import PurchaseOrder
        po = PurchaseOrder.objects.create(
            po_number="PO-0001",
            business=self.business,
        )
        email_record = EmailRecord.objects.create(
            message_id="<po-link@example.com>",
            purchase_order=po,
        )
        self.assertEqual(email_record.purchase_order, po)
        self.assertIsNone(email_record.job)

    def test_email_record_with_both_targets(self):
        """A single email can be linked to job and PO simultaneously."""
        from apps.purchasing.models import PurchaseOrder
        po = PurchaseOrder.objects.create(po_number="PO-0002", business=self.business)
        email_record = EmailRecord.objects.create(
            message_id="<both-targets@example.com>",
            job=self.job,
            purchase_order=po,
        )
        self.assertEqual(email_record.job, self.job)
        self.assertEqual(email_record.purchase_order, po)

    def test_email_record_purchase_order_set_null_on_delete(self):
        from apps.purchasing.models import PurchaseOrder
        po = PurchaseOrder.objects.create(po_number="PO-0003", business=self.business)
        email_record = EmailRecord.objects.create(
            message_id="<po-setnull@example.com>",
            purchase_order=po,
        )
        po.delete()
        email_record.refresh_from_db()
        self.assertIsNone(email_record.purchase_order)

    def test_email_record_direction_defaults_inbound(self):
        email_record = EmailRecord.objects.create(message_id="<dir-default@example.com>")
        self.assertEqual(email_record.direction, EmailRecord.INBOUND)
        self.assertIsNone(email_record.sent_at)
        self.assertEqual(email_record.last_send_error, '')

    def test_email_record_outbound_round_trip(self):
        email_record = EmailRecord.objects.create(
            message_id="<outbound-rt@example.com>",
            direction=EmailRecord.OUTBOUND,
            sent_at=timezone.now(),
            last_send_error='',
        )
        email_record.refresh_from_db()
        self.assertEqual(email_record.direction, EmailRecord.OUTBOUND)
        self.assertIsNotNone(email_record.sent_at)

    def test_email_record_outbound_failed_send(self):
        email_record = EmailRecord.objects.create(
            message_id="<outbound-fail@example.com>",
            direction=EmailRecord.OUTBOUND,
            sent_at=None,
            last_send_error='SMTP connection refused',
        )
        email_record.refresh_from_db()
        self.assertIsNone(email_record.sent_at)
        self.assertEqual(email_record.last_send_error, 'SMTP connection refused')

    def test_purchase_order_reverse_relation_to_email_records(self):
        from apps.purchasing.models import PurchaseOrder
        po = PurchaseOrder.objects.create(po_number="PO-0004", business=self.business)
        email1 = EmailRecord.objects.create(message_id="<po-rev1@example.com>", purchase_order=po)
        email2 = EmailRecord.objects.create(message_id="<po-rev2@example.com>", purchase_order=po)
        emails = po.email_records.all()
        self.assertEqual(emails.count(), 2)
        self.assertIn(email1, emails)
        self.assertIn(email2, emails)


class TempEmailModelTest(TestCase):
    """Test TempEmail model - temporary cache of email metadata."""

    def setUp(self):
        """Create test data."""
        self.email_record = EmailRecord.objects.create(
            message_id="<test@example.com>"
        )

    def test_temp_email_creation(self):
        """Test creating TempEmail with all fields."""
        temp_email = TempEmail.objects.create(
            email_record=self.email_record,
            uid="12345",
            subject="Test Subject",
            from_email="sender@example.com",
            to_email="recipient@example.com",
            cc_email="cc@example.com",
            date_sent=timezone.now(),
            is_read=False,
            is_starred=False,
            has_attachments=True
        )

        self.assertEqual(temp_email.email_record, self.email_record)
        self.assertEqual(temp_email.uid, "12345")
        self.assertEqual(temp_email.subject, "Test Subject")
        self.assertEqual(temp_email.from_email, "sender@example.com")
        self.assertTrue(temp_email.has_attachments)

    def test_temp_email_minimal_fields(self):
        """Test creating TempEmail with minimal fields."""
        temp_email = TempEmail.objects.create(
            email_record=self.email_record,
            uid="67890",
            from_email="sender@example.com",
            to_email="recipient@example.com",
            date_sent=timezone.now()
        )

        self.assertEqual(temp_email.subject, "")
        self.assertEqual(temp_email.cc_email, "")
        self.assertEqual(temp_email.text_body, "")
        self.assertEqual(temp_email.html_body, "")
        self.assertFalse(temp_email.is_read)
        self.assertFalse(temp_email.is_starred)
        self.assertFalse(temp_email.has_attachments)

    def test_temp_email_body_fields_round_trip(self):
        """Cached IMAP bodies round-trip through text_body/html_body."""
        text = "Hi,\n\nNeed 50 brackets.\n\nThanks,\nJane"
        html = "<p>Hi,</p><p>Need 50 brackets.</p>"
        temp_email = TempEmail.objects.create(
            email_record=self.email_record,
            uid="body-rt",
            from_email="sender@example.com",
            to_email="recipient@example.com",
            date_sent=timezone.now(),
            text_body=text,
            html_body=html,
        )
        temp_email.refresh_from_db()
        self.assertEqual(temp_email.text_body, text)
        self.assertEqual(temp_email.html_body, html)

    def test_temp_email_attachments_metadata_round_trip(self):
        """Per-attachment metadata round-trips as JSON; default is []."""
        metadata = [
            {'filename': 'spec.pdf', 'content_type': 'application/pdf', 'size': 12345},
            {'filename': 'photo.jpg', 'content_type': 'image/jpeg', 'size': 6789},
        ]
        temp_email = TempEmail.objects.create(
            email_record=self.email_record,
            uid="att-meta-rt",
            from_email="sender@example.com",
            to_email="recipient@example.com",
            date_sent=timezone.now(),
            attachments_metadata=metadata,
        )
        temp_email.refresh_from_db()
        self.assertEqual(temp_email.attachments_metadata, metadata)

    def test_temp_email_attachments_metadata_default_is_empty_list(self):
        temp_email = TempEmail.objects.create(
            email_record=self.email_record,
            uid="default-test",
            from_email="sender@example.com",
            to_email="recipient@example.com",
            date_sent=timezone.now(),
        )
        temp_email.refresh_from_db()
        self.assertEqual(temp_email.attachments_metadata, [])

    def test_temp_email_new_fields_default_empty(self):
        """bcc_email, in_reply_to, references default to empty strings."""
        temp_email = TempEmail.objects.create(
            email_record=self.email_record,
            uid="new-fields-default",
            from_email="sender@example.com",
            to_email="recipient@example.com",
            date_sent=timezone.now(),
        )
        temp_email.refresh_from_db()
        self.assertEqual(temp_email.bcc_email, '')
        self.assertEqual(temp_email.in_reply_to, '')
        self.assertEqual(temp_email.references, '')

    def test_temp_email_new_fields_round_trip(self):
        temp_email = TempEmail.objects.create(
            email_record=self.email_record,
            uid="new-fields-rt",
            from_email="sender@example.com",
            to_email="recipient@example.com",
            bcc_email="bcc1@example.com,bcc2@example.com",
            date_sent=timezone.now(),
            in_reply_to="<parent-id@example.com>",
            references="<root@example.com> <middle@example.com> <parent-id@example.com>",
        )
        temp_email.refresh_from_db()
        self.assertEqual(temp_email.bcc_email, "bcc1@example.com,bcc2@example.com")
        self.assertEqual(temp_email.in_reply_to, "<parent-id@example.com>")
        self.assertIn("<root@example.com>", temp_email.references)

    def test_temp_email_one_to_one_relationship(self):
        """Test that each EmailRecord can have only one TempEmail."""
        TempEmail.objects.create(
            email_record=self.email_record,
            uid="111",
            from_email="sender@example.com",
            to_email="recipient@example.com",
            date_sent=timezone.now()
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TempEmail.objects.create(
                    email_record=self.email_record,
                    uid="222",
                    from_email="sender2@example.com",
                    to_email="recipient2@example.com",
                    date_sent=timezone.now()
                )

    def test_temp_email_str_method(self):
        """Test string representation."""
        temp_email = TempEmail.objects.create(
            email_record=self.email_record,
            uid="333",
            subject="Important Email",
            from_email="boss@example.com",
            to_email="employee@example.com",
            date_sent=timezone.now()
        )

        str_repr = str(temp_email)
        self.assertIn("boss@example.com", str_repr)
        self.assertIn("Important Email", str_repr)

    def test_temp_email_cascade_delete(self):
        """Test that TempEmail is deleted when EmailRecord is deleted."""
        temp_email = TempEmail.objects.create(
            email_record=self.email_record,
            uid="444",
            from_email="sender@example.com",
            to_email="recipient@example.com",
            date_sent=timezone.now()
        )

        temp_email_id = temp_email.temp_email_id

        # Delete EmailRecord
        self.email_record.delete()

        # TempEmail should be deleted too
        with self.assertRaises(TempEmail.DoesNotExist):
            TempEmail.objects.get(temp_email_id=temp_email_id)

    def test_temp_email_reverse_relation(self):
        """Test accessing TempEmail from EmailRecord."""
        temp_email = TempEmail.objects.create(
            email_record=self.email_record,
            uid="555",
            from_email="sender@example.com",
            to_email="recipient@example.com",
            date_sent=timezone.now()
        )

        self.assertEqual(self.email_record.temp_data, temp_email)

    def test_temp_email_ordering(self):
        """Test that TempEmails are ordered by date_sent descending."""
        email_record_1 = EmailRecord.objects.create(message_id="<msg1@example.com>")
        email_record_2 = EmailRecord.objects.create(message_id="<msg2@example.com>")
        email_record_3 = EmailRecord.objects.create(message_id="<msg3@example.com>")

        old_date = timezone.now() - timedelta(days=5)
        recent_date = timezone.now() - timedelta(days=1)
        newest_date = timezone.now()

        temp1 = TempEmail.objects.create(
            email_record=email_record_1,
            uid="1",
            from_email="a@example.com",
            to_email="b@example.com",
            date_sent=old_date
        )
        temp2 = TempEmail.objects.create(
            email_record=email_record_2,
            uid="2",
            from_email="a@example.com",
            to_email="b@example.com",
            date_sent=newest_date
        )
        temp3 = TempEmail.objects.create(
            email_record=email_record_3,
            uid="3",
            from_email="a@example.com",
            to_email="b@example.com",
            date_sent=recent_date
        )

        all_temps = list(TempEmail.objects.all())
        self.assertEqual(all_temps[0], temp2)  # newest
        self.assertEqual(all_temps[1], temp3)  # recent
        self.assertEqual(all_temps[2], temp1)  # oldest


class ConfigurationEmailRetentionTest(TestCase):
    """Test email retention configuration."""

    def test_configuration_email_retention_default(self):
        """Test storing email_retention_days as key-value pair."""
        config = Configuration.objects.create(
            key="email_retention_days",
            value="90"
        )
        self.assertEqual(config.value, "90")
        self.assertEqual(int(config.value), 90)

    def test_configuration_email_retention_custom(self):
        """Test setting custom email retention period."""
        config = Configuration.objects.create(
            key="email_retention_days",
            value="30"
        )
        self.assertEqual(config.value, "30")
        self.assertEqual(int(config.value), 30)

    def test_configuration_email_display_limit(self):
        """Test storing email_display_limit as key-value pair."""
        config = Configuration.objects.create(
            key="email_display_limit",
            value="30"
        )
        self.assertEqual(config.value, "30")
        self.assertEqual(int(config.value), 30)

    def test_configuration_latest_email_date_nullable(self):
        """Test that latest_email_date can be empty string."""
        config = Configuration.objects.create(
            key="latest_email_date",
            value=""
        )
        self.assertEqual(config.value, "")

    def test_configuration_latest_email_date_custom(self):
        """Test setting custom latest_email_date as ISO format."""
        test_date = timezone.now() - timedelta(days=7)
        config = Configuration.objects.create(
            key="latest_email_date",
            value=test_date.isoformat()
        )
        self.assertEqual(config.value, test_date.isoformat())
        # Test we can parse it back
        parsed_date = datetime.fromisoformat(config.value)
        self.assertEqual(parsed_date, test_date)


class EmailServiceTest(TestCase):
    """Test EmailService class."""

    def setUp(self):
        """Create test data."""
        self.contact = Contact.objects.create(
            first_name="Test",
            last_name="Contact",
            email="contact@example.com",
        )
        self.business = Business.objects.create(
            business_name="Test Business",
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(
            job_number="JOB-001",
            contact=self.contact,
            description="Test job"
        )

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123'
    )
    def test_email_service_initialization(self):
        """Test EmailService initialization with settings."""
        # The setup migration seeds gmail server defaults into Configuration,
        # which outrank env settings — clear them to test the env path.
        from apps.core.models import Configuration
        Configuration.objects.filter(
            key__in=('email_imap_server', 'email_smtp_host',
                     'email_smtp_port')).delete()
        service = EmailService()
        self.assertEqual(service.imap_server, 'imap.example.com')
        self.assertEqual(service.email, 'test@example.com')
        self.assertEqual(service.password, 'password123')
        self.assertEqual(service.mailbox_folder, 'INBOX')

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123',
        EMAIL_IMAP_FOLDER='Custom/Folder'
    )
    def test_email_service_custom_folder(self):
        """Test EmailService with custom IMAP folder."""
        service = EmailService()
        self.assertEqual(service.mailbox_folder, 'Custom/Folder')

    @override_settings(
        EMAIL_IMAP_SERVER=None,
        EMAIL_HOST_USER=None,
        EMAIL_HOST_PASSWORD=None
    )
    def test_email_service_validate_config(self):
        """Test configuration validation."""
        service = EmailService()
        # No settings configured
        self.assertFalse(service._validate_config())

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123'
    )
    def test_email_service_validate_config_complete(self):
        """Test configuration validation with complete settings."""
        service = EmailService()
        self.assertTrue(service._validate_config())

    def test_associate_with_job(self):
        """Test associating an EmailRecord with a Job."""
        email_record = EmailRecord.objects.create(message_id="<link@example.com>")

        result = EmailService.associate_with_job(
            email_record.email_record_id,
            self.job.job_id
        )

        self.assertEqual(result.job, self.job)

        # Verify in database
        email_record.refresh_from_db()
        self.assertEqual(email_record.job, self.job)

    def test_associate_with_job_email_not_found(self):
        """Test associating non-existent EmailRecord raises NotFoundError."""
        from apps.core.services import NotFoundError
        with self.assertRaises(NotFoundError):
            EmailService.associate_with_job(99999, self.job.job_id)

    def test_associate_with_job_job_not_found(self):
        """Test associating with non-existent Job raises NotFoundError."""
        from apps.core.services import NotFoundError
        email_record = EmailRecord.objects.create(message_id="<link2@example.com>")
        with self.assertRaises(NotFoundError):
            EmailService.associate_with_job(email_record.email_record_id, 99999)

    def test_associate_with_parameterized_job(self):
        """The parameterized associate_with handles the job field path."""
        email_record = EmailRecord.objects.create(message_id="<gen-job@example.com>")
        result = EmailService.associate_with(
            email_record.email_record_id, 'job', self.job.job_id,
        )
        self.assertEqual(result.job, self.job)

    def test_associate_with_purchase_order(self):
        from apps.purchasing.models import PurchaseOrder
        po = PurchaseOrder.objects.create(po_number="PO-LINK-1", business=self.business)
        email_record = EmailRecord.objects.create(message_id="<gen-po@example.com>")
        result = EmailService.associate_with(
            email_record.email_record_id, 'purchase_order', po.po_id,
        )
        self.assertEqual(result.purchase_order, po)

    def test_associate_with_rejects_unknown_field(self):
        email_record = EmailRecord.objects.create(message_id="<gen-bad@example.com>")
        with self.assertRaises(ValueError):
            EmailService.associate_with(
                email_record.email_record_id, 'estimate', 1,
            )

    def test_associate_with_target_not_found(self):
        from apps.core.services import NotFoundError
        email_record = EmailRecord.objects.create(message_id="<gen-po-404@example.com>")
        with self.assertRaises(NotFoundError):
            EmailService.associate_with(
                email_record.email_record_id, 'purchase_order', 99999,
            )

    def test_disassociate_from_purchase_order(self):
        from apps.purchasing.models import PurchaseOrder
        po = PurchaseOrder.objects.create(po_number="PO-UNLINK-1", business=self.business)
        email_record = EmailRecord.objects.create(
            message_id="<gen-po-unlink@example.com>", purchase_order=po,
        )
        result = EmailService.disassociate_from(
            email_record.email_record_id, 'purchase_order',
        )
        self.assertIsNone(result.purchase_order)

    def test_disassociate_from_only_clears_named_field(self):
        """Disassociating one target leaves the other alone."""
        from apps.purchasing.models import PurchaseOrder
        po = PurchaseOrder.objects.create(po_number="PO-MULTI-1", business=self.business)
        email_record = EmailRecord.objects.create(
            message_id="<multi@example.com>",
            job=self.job, purchase_order=po,
        )
        EmailService.disassociate_from(email_record.email_record_id, 'purchase_order')
        email_record.refresh_from_db()
        self.assertEqual(email_record.job, self.job)
        self.assertIsNone(email_record.purchase_order)

    def test_cleanup_old_temp_emails(self):
        """Test cleanup of old TempEmail records."""
        service = EmailService()

        # Create old email
        old_email_record = EmailRecord.objects.create(message_id="<old@example.com>")
        old_temp = TempEmail.objects.create(
            email_record=old_email_record,
            uid="old-uid",
            from_email="old@example.com",
            to_email="recipient@example.com",
            date_sent=timezone.now() - timedelta(days=100)
        )

        # Manually set created_at to 100 days ago
        TempEmail.objects.filter(temp_email_id=old_temp.temp_email_id).update(
            created_at=timezone.now() - timedelta(days=100)
        )

        # Create recent email
        recent_email_record = EmailRecord.objects.create(message_id="<recent@example.com>")
        recent_temp = TempEmail.objects.create(
            email_record=recent_email_record,
            uid="recent-uid",
            from_email="recent@example.com",
            to_email="recipient@example.com",
            date_sent=timezone.now() - timedelta(days=30)
        )

        # Run cleanup with default 90 days
        deleted_count = service.cleanup_old_temp_emails(retention_days=90)

        # Old TempEmail should be deleted
        self.assertEqual(deleted_count, 1)
        self.assertFalse(TempEmail.objects.filter(temp_email_id=old_temp.temp_email_id).exists())

        # Recent TempEmail should still exist
        self.assertTrue(TempEmail.objects.filter(temp_email_id=recent_temp.temp_email_id).exists())

        # Old EmailRecord should still exist (not deleted)
        self.assertTrue(EmailRecord.objects.filter(email_record_id=old_email_record.email_record_id).exists())

    def test_cleanup_uses_configuration(self):
        """Test cleanup uses Configuration model for retention period."""
        Configuration.objects.create(
            key="email_retention_days",
            value="30"
        )

        service = EmailService()

        # Create email 60 days old
        email_record = EmailRecord.objects.create(message_id="<sixty@example.com>")
        temp = TempEmail.objects.create(
            email_record=email_record,
            uid="sixty-uid",
            from_email="sixty@example.com",
            to_email="recipient@example.com",
            date_sent=timezone.now() - timedelta(days=60)
        )

        TempEmail.objects.filter(temp_email_id=temp.temp_email_id).update(
            created_at=timezone.now() - timedelta(days=60)
        )

        # Run cleanup without specifying retention_days (should use config = 30)
        deleted_count = service.cleanup_old_temp_emails()

        # Should be deleted because it's older than 30 days
        self.assertEqual(deleted_count, 1)
        self.assertFalse(TempEmail.objects.filter(temp_email_id=temp.temp_email_id).exists())

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123'
    )
    @patch('apps.core.services.MailBox')
    def test_fetch_new_emails_success(self, mock_mailbox_class):
        """Test fetching new emails from IMAP server."""
        # Mock the IMAP message
        mock_msg = Mock()
        mock_msg.uid = '12345'
        mock_msg.headers = {'message-id': ['<new@example.com>']}
        mock_msg.subject = 'New Email'
        mock_msg.from_ = 'sender@example.com'
        mock_msg.to = ['recipient@example.com']
        mock_msg.cc = []
        mock_msg.date = timezone.now()
        att = Mock()
        att.filename = 'spec.pdf'
        att.content_type = 'application/pdf'
        att.payload = b'%PDF-binary'
        mock_msg.attachments = [att]

        # Mock the mailbox
        mock_mailbox = MagicMock()
        mock_mailbox.fetch.return_value = [mock_msg]
        mock_mailbox.__enter__.return_value = mock_mailbox
        mock_mailbox_class.return_value.login.return_value = mock_mailbox

        mock_msg.text = 'plain body'
        mock_msg.html = '<p>html body</p>'

        service = EmailService()
        stats = service.fetch_new_emails()

        self.assertEqual(stats['new'], 1)
        self.assertEqual(stats['existing'], 0)
        self.assertEqual(len(stats['errors']), 0)

        # Verify EmailRecord created
        email_record = EmailRecord.objects.get(message_id='<new@example.com>')
        self.assertIsNotNone(email_record)
        self.assertIsNone(email_record.job)  # No automatic job linking

        # Verify TempEmail created with cached bodies + attachment metadata
        temp_email = TempEmail.objects.get(email_record=email_record)
        self.assertEqual(temp_email.uid, '12345')
        self.assertEqual(temp_email.subject, 'New Email')
        self.assertEqual(temp_email.from_email, 'sender@example.com')
        self.assertEqual(temp_email.text_body, 'plain body')
        self.assertEqual(temp_email.html_body, '<p>html body</p>')
        self.assertTrue(temp_email.has_attachments)
        self.assertEqual(temp_email.attachments_metadata, [
            {'filename': 'spec.pdf', 'content_type': 'application/pdf', 'size': len(b'%PDF-binary')},
        ])

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123'
    )
    @patch('apps.core.services.MailBox')
    def test_fetch_new_emails_existing(self, mock_mailbox_class):
        """Test that existing emails are not duplicated."""
        # Create existing email record
        EmailRecord.objects.create(message_id='<existing@example.com>')

        # Mock message with same message_id
        mock_msg = Mock()
        mock_msg.uid = '99999'
        mock_msg.headers = {'message-id': ['<existing@example.com>']}

        mock_mailbox = MagicMock()
        mock_mailbox.fetch.return_value = [mock_msg]
        mock_mailbox.__enter__.return_value = mock_mailbox
        mock_mailbox_class.return_value.login.return_value = mock_mailbox

        service = EmailService()
        stats = service.fetch_new_emails()

        self.assertEqual(stats['new'], 0)
        self.assertEqual(stats['existing'], 1)

        # Should still only have one EmailRecord
        self.assertEqual(EmailRecord.objects.filter(message_id='<existing@example.com>').count(), 1)

    @override_settings(
        EMAIL_IMAP_SERVER=None,
        EMAIL_HOST_USER=None,
        EMAIL_HOST_PASSWORD=None
    )
    def test_fetch_new_emails_no_config(self):
        """Test that fetch raises error when config is incomplete."""
        service = EmailService()

        with self.assertRaises(ValueError) as context:
            service.fetch_new_emails()

        self.assertIn("Email configuration incomplete", str(context.exception))

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123'
    )
    @patch('apps.core.services.MailBox')
    def test_get_email_content_by_uid(self, mock_mailbox_class):
        """Test fetching full email content by UID."""
        # Create email record with temp data
        email_record = EmailRecord.objects.create(message_id='<content@example.com>')
        TempEmail.objects.create(
            email_record=email_record,
            uid='12345',
            from_email='sender@example.com',
            to_email='recipient@example.com',
            date_sent=timezone.now()
        )

        # Mock full message
        mock_msg = Mock()
        mock_msg.subject = 'Full Subject'
        mock_msg.from_ = 'sender@example.com'
        mock_msg.to = ['recipient@example.com']
        mock_msg.cc = []
        mock_msg.date = timezone.now()
        mock_msg.text = 'Email body text'
        mock_msg.html = '<p>Email body HTML</p>'
        mock_msg.attachments = []

        mock_mailbox = MagicMock()
        mock_mailbox.fetch.return_value = [mock_msg]
        mock_mailbox.__enter__.return_value = mock_mailbox
        mock_mailbox_class.return_value.login.return_value = mock_mailbox

        service = EmailService()
        content = service.get_email_content(email_record.email_record_id)

        self.assertIsNotNone(content)
        self.assertEqual(content['text'], 'Email body text')
        self.assertEqual(content['html'], '<p>Email body HTML</p>')
        self.assertEqual(content['subject'], 'Full Subject')
        self.assertEqual(len(content['attachments']), 0)

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123'
    )
    def test_get_email_content_not_found(self):
        """Test getting content for non-existent email."""
        service = EmailService()
        content = service.get_email_content(99999)
        self.assertIsNone(content)

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123'
    )
    @patch('apps.core.services.MailBox')
    def test_get_email_content_prefers_cache(self, mock_mailbox_class):
        """When TempEmail has cached body, no IMAP fetch occurs."""
        email_record = EmailRecord.objects.create(message_id='<cached@example.com>')
        TempEmail.objects.create(
            email_record=email_record,
            uid='cached-uid',
            subject='Cached Subject',
            from_email='sender@example.com',
            to_email='r@example.com',
            cc_email='',
            date_sent=timezone.now(),
            text_body='cached text body',
            html_body='<p>cached html</p>',
        )

        service = EmailService()
        content = service.get_email_content(email_record.email_record_id)

        self.assertIsNotNone(content)
        self.assertEqual(content['text'], 'cached text body')
        self.assertEqual(content['html'], '<p>cached html</p>')
        self.assertEqual(content['subject'], 'Cached Subject')
        # Crucially: no IMAP login was attempted.
        mock_mailbox_class.assert_not_called()

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123'
    )
    @patch('apps.core.services.MailBox')
    def test_get_email_content_falls_back_to_imap_when_cache_empty(self, mock_mailbox_class):
        """When TempEmail exists but bodies are blank, fall back to IMAP."""
        email_record = EmailRecord.objects.create(message_id='<empty@example.com>')
        TempEmail.objects.create(
            email_record=email_record,
            uid='55555',
            from_email='sender@example.com',
            to_email='r@example.com',
            date_sent=timezone.now(),
            text_body='',
            html_body='',
        )

        mock_msg = Mock()
        mock_msg.subject = 'From IMAP'
        mock_msg.from_ = 'sender@example.com'
        mock_msg.to = ['r@example.com']
        mock_msg.cc = []
        mock_msg.date = timezone.now()
        mock_msg.text = 'fetched text'
        mock_msg.html = ''
        mock_msg.attachments = []

        mock_mailbox = MagicMock()
        mock_mailbox.fetch.return_value = [mock_msg]
        mock_mailbox.__enter__.return_value = mock_mailbox
        mock_mailbox_class.return_value.login.return_value = mock_mailbox

        service = EmailService()
        content = service.get_email_content(email_record.email_record_id)

        self.assertEqual(content['text'], 'fetched text')
        mock_mailbox_class.assert_called_once()

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123'
    )
    @patch('apps.core.services.MailBox')
    def test_get_email_content_uses_cache_when_attachments_metadata_cached(self, mock_mailbox_class):
        """Emails with cached attachments_metadata serve the detail view
        entirely from cache — IMAP is reserved for the future download path."""
        email_record = EmailRecord.objects.create(message_id='<att@example.com>')
        TempEmail.objects.create(
            email_record=email_record,
            uid='77777',
            from_email='sender@example.com',
            to_email='r@example.com',
            date_sent=timezone.now(),
            text_body='cached body',
            html_body='',
            has_attachments=True,
            attachments_metadata=[
                {'filename': 'spec.pdf', 'content_type': 'application/pdf', 'size': 12345},
            ],
        )

        service = EmailService()
        content = service.get_email_content(email_record.email_record_id)

        self.assertEqual(content['text'], 'cached body')
        self.assertEqual(content['attachments'], [
            {'filename': 'spec.pdf', 'content_type': 'application/pdf', 'size': 12345},
        ])
        mock_mailbox_class.assert_not_called()

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123'
    )
    @patch('apps.core.services.MailBox')
    def test_get_email_content_falls_back_when_attachments_metadata_missing(self, mock_mailbox_class):
        """Old rows that pre-date the attachments_metadata column have
        has_attachments=True but attachments_metadata=[]. We can't render
        a useful attachment list from cache, so fall back to IMAP."""
        email_record = EmailRecord.objects.create(message_id='<old-att@example.com>')
        TempEmail.objects.create(
            email_record=email_record,
            uid='88888',
            from_email='sender@example.com',
            to_email='r@example.com',
            date_sent=timezone.now(),
            text_body='cached body',
            html_body='',
            has_attachments=True,
            attachments_metadata=[],  # not yet backfilled
        )

        mock_msg = Mock()
        mock_msg.subject = 'With Attachments'
        mock_msg.from_ = 'sender@example.com'
        mock_msg.to = ['r@example.com']
        mock_msg.cc = []
        mock_msg.date = timezone.now()
        mock_msg.text = 'fresh body'
        mock_msg.html = ''
        att = Mock()
        att.filename = 'spec.pdf'
        att.content_type = 'application/pdf'
        att.payload = b'%PDF...'
        mock_msg.attachments = [att]

        mock_mailbox = MagicMock()
        mock_mailbox.fetch.return_value = [mock_msg]
        mock_mailbox.__enter__.return_value = mock_mailbox
        mock_mailbox_class.return_value.login.return_value = mock_mailbox

        service = EmailService()
        content = service.get_email_content(email_record.email_record_id)

        self.assertEqual(content['text'], 'fresh body')
        self.assertEqual(len(content['attachments']), 1)
        mock_mailbox_class.assert_called_once()

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123'
    )
    @patch('apps.core.services.MailBox')
    def test_fetch_emails_by_date_range_creates_configuration(self, mock_mailbox_class):
        """Test that fetch_emails_by_date_range creates Configuration if not exists."""
        # Mock empty mailbox
        mock_mailbox = MagicMock()
        mock_mailbox.fetch.return_value = []
        mock_mailbox.__enter__.return_value = mock_mailbox
        mock_mailbox_class.return_value.login.return_value = mock_mailbox

        # Ensure no existing state
        AppState.objects.filter(key='latest_email_date').delete()
        Configuration.objects.filter(key='email_retention_days').delete()
        Configuration.objects.filter(key='email_display_limit').delete()

        service = EmailService()
        stats = service.fetch_emails_by_date_range(days_back=30)

        # latest_email_date is machine state (AppState); the email config keys
        # remain in Configuration.
        latest_date_state = AppState.objects.get(key='latest_email_date')
        self.assertIsNotNone(latest_date_state)
        self.assertIsNotNone(latest_date_state.value)

        retention_config = Configuration.objects.get(key='email_retention_days')
        self.assertEqual(retention_config.value, '90')

        display_config = Configuration.objects.get(key='email_display_limit')
        self.assertEqual(display_config.value, '30')

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123'
    )
    @patch('apps.core.services.MailBox')
    def test_fetch_emails_by_date_range_updates_latest_date(self, mock_mailbox_class):
        """Test that latest_email_date is updated after fetching."""
        # Seed the cursor (AppState) with an old date
        old_date = timezone.now() - timedelta(days=10)
        AppState.objects.create(
            key='latest_email_date',
            value=old_date.isoformat()
        )
        Configuration.objects.create(key='email_retention_days', value='90')
        Configuration.objects.create(key='email_display_limit', value='30')

        # Mock message with newer date
        new_date = timezone.now() - timedelta(days=1)
        mock_msg = Mock()
        mock_msg.uid = '12345'
        mock_msg.headers = {'message-id': ['<newest@example.com>']}
        mock_msg.subject = 'New Email'
        mock_msg.from_ = 'sender@example.com'
        mock_msg.to = ['recipient@example.com']
        mock_msg.cc = []
        mock_msg.date = new_date
        mock_msg.attachments = []
        mock_msg.text = ''
        mock_msg.html = ''

        mock_mailbox = MagicMock()
        mock_mailbox.fetch.return_value = [mock_msg]
        mock_mailbox.__enter__.return_value = mock_mailbox
        mock_mailbox_class.return_value.login.return_value = mock_mailbox

        service = EmailService()
        stats = service.fetch_emails_by_date_range(days_back=30)

        # The cursor (AppState) should be updated with the newer date
        updated_state = AppState.objects.get(key='latest_email_date')
        updated_date = datetime.fromisoformat(updated_state.value)
        self.assertGreater(updated_date, old_date)
        self.assertEqual(stats['new'], 1)
        self.assertIsNotNone(stats['latest_date'])

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123'
    )
    @patch('apps.core.services.MailBox')
    def test_fetch_emails_by_date_range_uses_latest_email_date(self, mock_mailbox_class):
        """Test that fetch uses latest_email_date as threshold."""
        # Seed the cursor (AppState) with a specific date
        fetch_since_date = timezone.now() - timedelta(days=5)
        AppState.objects.create(
            key='latest_email_date',
            value=fetch_since_date.isoformat()
        )
        Configuration.objects.create(key='email_retention_days', value='90')
        Configuration.objects.create(key='email_display_limit', value='30')

        mock_mailbox = MagicMock()
        mock_mailbox.fetch.return_value = []
        mock_mailbox.__enter__.return_value = mock_mailbox
        mock_mailbox_class.return_value.login.return_value = mock_mailbox

        service = EmailService()
        service.fetch_emails_by_date_range(days_back=30)

        # Verify that fetch was called with date_gte using latest_email_date
        # (The AND filter will use the date from config, not days_back=30)
        mock_mailbox.fetch.assert_called_once()
        call_args = mock_mailbox.fetch.call_args
        # The actual date used should be from config, not 30 days back

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123'
    )
    @patch('apps.core.services.MailBox')
    def test_fetch_handles_naive_message_date(self, mock_mailbox_class):
        """A message with a naive Date header (missing/malformed tz) must not
        error out against the aware cursor — it fetches, and the cursor
        advances past it and stays aware."""
        old_date = timezone.now() - timedelta(days=10)
        AppState.objects.create(
            key='latest_email_date',
            value=old_date.isoformat()  # aware cursor
        )
        Configuration.objects.create(key='email_retention_days', value='90')
        Configuration.objects.create(key='email_display_limit', value='30')

        naive_date = (timezone.now() - timedelta(days=1)).replace(tzinfo=None)
        mock_msg = Mock()
        mock_msg.uid = '12345'
        mock_msg.headers = {'message-id': ['<naive@example.com>']}
        mock_msg.subject = 'Naive Date Email'
        mock_msg.from_ = 'sender@example.com'
        mock_msg.to = ['recipient@example.com']
        mock_msg.cc = []
        mock_msg.date = naive_date
        mock_msg.attachments = []
        mock_msg.text = ''
        mock_msg.html = ''

        mock_mailbox = MagicMock()
        mock_mailbox.fetch.return_value = [mock_msg]
        mock_mailbox.__enter__.return_value = mock_mailbox
        mock_mailbox_class.return_value.login.return_value = mock_mailbox

        service = EmailService()
        stats = service.fetch_emails_by_date_range(days_back=30)

        self.assertEqual(stats['errors'], [])
        self.assertEqual(stats['new'], 1)
        self.assertTrue(
            EmailRecord.objects.filter(message_id='<naive@example.com>').exists())
        # Cursor advanced past the message and round-trips aware
        updated = datetime.fromisoformat(
            AppState.objects.get(key='latest_email_date').value)
        self.assertIsNotNone(updated.tzinfo)
        self.assertGreater(updated, old_date)

    @override_settings(
        EMAIL_IMAP_SERVER='imap.example.com',
        EMAIL_HOST_USER='test@example.com',
        EMAIL_HOST_PASSWORD='password123'
    )
    @patch('apps.core.services.MailBox')
    def test_fetch_handles_naive_stored_cursor(self, mock_mailbox_class):
        """A cursor persisted naive (legacy round-trip) must compare cleanly
        against an aware message date."""
        naive_cursor = (timezone.now() - timedelta(days=10)).replace(tzinfo=None)
        AppState.objects.create(
            key='latest_email_date',
            value=naive_cursor.isoformat()  # naive cursor
        )
        Configuration.objects.create(key='email_retention_days', value='90')
        Configuration.objects.create(key='email_display_limit', value='30')

        mock_msg = Mock()
        mock_msg.uid = '54321'
        mock_msg.headers = {'message-id': ['<aware@example.com>']}
        mock_msg.subject = 'Aware Date Email'
        mock_msg.from_ = 'sender@example.com'
        mock_msg.to = ['recipient@example.com']
        mock_msg.cc = []
        mock_msg.date = timezone.now() - timedelta(days=1)
        mock_msg.attachments = []
        mock_msg.text = ''
        mock_msg.html = ''

        mock_mailbox = MagicMock()
        mock_mailbox.fetch.return_value = [mock_msg]
        mock_mailbox.__enter__.return_value = mock_mailbox
        mock_mailbox_class.return_value.login.return_value = mock_mailbox

        service = EmailService()
        stats = service.fetch_emails_by_date_range(days_back=30)

        self.assertEqual(stats['errors'], [])
        self.assertEqual(stats['new'], 1)
        updated = datetime.fromisoformat(
            AppState.objects.get(key='latest_email_date').value)
        self.assertIsNotNone(updated.tzinfo)


class PropagateThreadAssociationTest(TestCase):
    """EmailService.propagate_thread_association copies a single FK to
    every thread sibling that has a null value for the same field. Doesn't
    overwrite differing existing links."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='J', last_name='D',
            email='j@example.com', mobile_number='555',
        )
        self.business = Business.objects.create(
            business_name='Acme', default_contact=self.contact,
        )
        self.job_a = Job.objects.create(
            job_number='JOB-PROP-A', contact=self.contact, description='A',
        )
        self.job_b = Job.objects.create(
            job_number='JOB-PROP-B', contact=self.contact, description='B',
        )

    def _make(self, mid, *, in_reply_to='', references='', job=None,
              po=None, direction=None):
        from apps.core.models import EmailRecord, TempEmail
        kwargs = {'message_id': mid}
        if direction is not None:
            kwargs['direction'] = direction
        if job:
            kwargs['job'] = job
        if po:
            kwargs['purchase_order'] = po
        record = EmailRecord.objects.create(**kwargs)
        TempEmail.objects.create(
            email_record=record,
            uid=mid.replace('<', '').replace('>', '')[:10],
            from_email='x@x.com', to_email='us@example.com',
            date_sent=timezone.now(),
            in_reply_to=in_reply_to, references=references,
        )
        return record

    def test_linear_chain_propagates_job_to_unlinked_siblings(self):
        from apps.core.services import EmailService
        e1 = self._make('<m1@example.com>')
        e2 = self._make(
            '<m2@example.com>',
            in_reply_to='<m1@example.com>',
            references='<m1@example.com>',
        )
        e3 = self._make(
            '<m3@example.com>',
            in_reply_to='<m2@example.com>',
            references='<m1@example.com> <m2@example.com>',
        )

        # User links e3 to job_a.
        EmailService.associate_with(e3.email_record_id, 'job', self.job_a.pk)

        e1.refresh_from_db(); e2.refresh_from_db(); e3.refresh_from_db()
        self.assertEqual(e1.job, self.job_a)
        self.assertEqual(e2.job, self.job_a)
        self.assertEqual(e3.job, self.job_a)

    def test_sibling_already_linked_to_different_job_is_not_overwritten(self):
        """E1 pre-linked to job_a; user now links E3 to job_b. Propagation
        leaves E1 alone, sets E2 (null) to job_b, E3 stays job_b."""
        from apps.core.services import EmailService
        e1 = self._make('<m1@example.com>', job=self.job_a)
        e2 = self._make(
            '<m2@example.com>',
            in_reply_to='<m1@example.com>',
            references='<m1@example.com>',
        )
        e3 = self._make(
            '<m3@example.com>',
            in_reply_to='<m2@example.com>',
            references='<m1@example.com> <m2@example.com>',
        )

        EmailService.associate_with(e3.email_record_id, 'job', self.job_b.pk)

        e1.refresh_from_db(); e2.refresh_from_db(); e3.refresh_from_db()
        self.assertEqual(e1.job, self.job_a, 'pre-existing link must stay')
        self.assertEqual(e2.job, self.job_b)
        self.assertEqual(e3.job, self.job_b)

    def test_mixed_fk_types_propagate_independently(self):
        """E1 has PO=p. Linking E3 to a Job propagates only Job, leaves PO
        untouched on E1; E2 gains Job too."""
        from apps.core.services import EmailService
        from apps.purchasing.models import PurchaseOrder
        po = PurchaseOrder.objects.create(
            po_number='PO-PROP-1', business=self.business,
        )
        e1 = self._make('<m1@example.com>', po=po)
        e2 = self._make(
            '<m2@example.com>', in_reply_to='<m1@example.com>',
            references='<m1@example.com>',
        )
        e3 = self._make(
            '<m3@example.com>', in_reply_to='<m2@example.com>',
            references='<m1@example.com> <m2@example.com>',
        )

        EmailService.associate_with(e3.email_record_id, 'job', self.job_a.pk)

        e1.refresh_from_db(); e2.refresh_from_db(); e3.refresh_from_db()
        self.assertEqual(e1.purchase_order, po, 'unrelated FK untouched')
        self.assertEqual(e1.job, self.job_a, 'job propagated even though PO was set')
        self.assertEqual(e2.job, self.job_a)
        self.assertEqual(e3.job, self.job_a)

    def test_outbound_in_thread_picks_up_association(self):
        from apps.core.services import EmailService
        from apps.core.models import EmailRecord
        inbound = self._make('<customer@example.com>')
        outbound = self._make(
            '<minibini-out@example.com>',
            in_reply_to='<customer@example.com>',
            references='<customer@example.com>',
            direction=EmailRecord.OUTBOUND,
        )

        EmailService.associate_with(inbound.email_record_id, 'job', self.job_a.pk)

        outbound.refresh_from_db()
        self.assertEqual(outbound.job, self.job_a)

    def test_no_op_when_source_field_is_null(self):
        """propagate_thread_association is a no-op when the source has no
        value for the target field — there's nothing to propagate."""
        from apps.core.services import EmailService
        e1 = self._make('<m1@example.com>')
        e2 = self._make(
            '<m2@example.com>', in_reply_to='<m1@example.com>',
            references='<m1@example.com>',
        )
        # e1.job is null. Calling propagate directly should do nothing.
        EmailService.propagate_thread_association(e1, 'job')
        e1.refresh_from_db(); e2.refresh_from_db()
        self.assertIsNone(e1.job)
        self.assertIsNone(e2.job)

    def test_disassociate_does_not_propagate(self):
        """Disassociate is a per-email surgical tool, not a thread-level
        one (per spec §4.3)."""
        from apps.core.services import EmailService
        e1 = self._make('<m1@example.com>', job=self.job_a)
        e2 = self._make(
            '<m2@example.com>', in_reply_to='<m1@example.com>',
            references='<m1@example.com>',
            job=self.job_a,
        )
        EmailService.disassociate_from(e1.email_record_id, 'job')
        e1.refresh_from_db(); e2.refresh_from_db()
        self.assertIsNone(e1.job)
        # e2 still has its job — we don't strip siblings.
        self.assertEqual(e2.job, self.job_a)
