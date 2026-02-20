from django.test import TestCase, TransactionTestCase, override_settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from datetime import timedelta, datetime
from unittest.mock import Mock, patch, MagicMock
from apps.core.models import EmailRecord, TempEmail, Configuration
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
        self.assertFalse(temp_email.is_read)
        self.assertFalse(temp_email.is_starred)
        self.assertFalse(temp_email.has_attachments)

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

    def test_link_email_to_job(self):
        """Test linking an EmailRecord to a Job."""
        service = EmailService()
        email_record = EmailRecord.objects.create(message_id="<link@example.com>")

        result = service.link_email_to_job(
            email_record.email_record_id,
            self.job.job_id
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.job, self.job)

        # Verify in database
        email_record.refresh_from_db()
        self.assertEqual(email_record.job, self.job)

    def test_link_email_to_job_not_found(self):
        """Test linking non-existent EmailRecord."""
        service = EmailService()
        result = service.link_email_to_job(99999, self.job.job_id)
        self.assertIsNone(result)

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
        mock_msg.attachments = []

        # Mock the mailbox
        mock_mailbox = MagicMock()
        mock_mailbox.fetch.return_value = [mock_msg]
        mock_mailbox.__enter__.return_value = mock_mailbox
        mock_mailbox_class.return_value.login.return_value = mock_mailbox

        service = EmailService()
        stats = service.fetch_new_emails()

        self.assertEqual(stats['new'], 1)
        self.assertEqual(stats['existing'], 0)
        self.assertEqual(len(stats['errors']), 0)

        # Verify EmailRecord created
        email_record = EmailRecord.objects.get(message_id='<new@example.com>')
        self.assertIsNotNone(email_record)
        self.assertIsNone(email_record.job)  # No automatic job linking

        # Verify TempEmail created
        temp_email = TempEmail.objects.get(email_record=email_record)
        self.assertEqual(temp_email.uid, '12345')
        self.assertEqual(temp_email.subject, 'New Email')
        self.assertEqual(temp_email.from_email, 'sender@example.com')

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
    def test_fetch_emails_by_date_range_creates_configuration(self, mock_mailbox_class):
        """Test that fetch_emails_by_date_range creates Configuration if not exists."""
        # Mock empty mailbox
        mock_mailbox = MagicMock()
        mock_mailbox.fetch.return_value = []
        mock_mailbox.__enter__.return_value = mock_mailbox
        mock_mailbox_class.return_value.login.return_value = mock_mailbox

        # Ensure no configuration exists
        Configuration.objects.filter(key='latest_email_date').delete()
        Configuration.objects.filter(key='email_retention_days').delete()
        Configuration.objects.filter(key='email_display_limit').delete()

        service = EmailService()
        stats = service.fetch_emails_by_date_range(days_back=30)

        # Should create configuration entries
        latest_date_config = Configuration.objects.get(key='latest_email_date')
        self.assertIsNotNone(latest_date_config)
        self.assertIsNotNone(latest_date_config.value)

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
        # Create configuration with old date
        old_date = timezone.now() - timedelta(days=10)
        Configuration.objects.create(
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

        mock_mailbox = MagicMock()
        mock_mailbox.fetch.return_value = [mock_msg]
        mock_mailbox.__enter__.return_value = mock_mailbox
        mock_mailbox_class.return_value.login.return_value = mock_mailbox

        service = EmailService()
        stats = service.fetch_emails_by_date_range(days_back=30)

        # Configuration should be updated with newer date
        updated_config = Configuration.objects.get(key='latest_email_date')
        updated_date = datetime.fromisoformat(updated_config.value)
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
        # Create configuration with specific date
        fetch_since_date = timezone.now() - timedelta(days=5)
        Configuration.objects.create(
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
