from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, MagicMock
from apps.core.models import EmailRecord, TempEmail, Configuration


class EmailInboxViewTest(TestCase):
    """Test email_inbox view with display limit functionality."""

    def setUp(self):
        self.client = Client()
        self.url = reverse('core:email_inbox')

    def test_email_inbox_respects_display_limit(self):
        """Test that inbox displays only up to email_display_limit emails."""
        # Create configuration with display limit of 5
        Configuration.objects.create(key='email_display_limit', value='5')
        Configuration.objects.create(key='email_retention_days', value='90')

        # Create 10 emails
        for i in range(10):
            email_record = EmailRecord.objects.create(
                message_id=f'<email{i}@example.com>'
            )
            TempEmail.objects.create(
                email_record=email_record,
                uid=str(1000 + i),
                from_email=f'sender{i}@example.com',
                to_email='recipient@example.com',
                date_sent=timezone.now() - timedelta(hours=i),
                subject=f'Email {i}'
            )

        # Mock the EmailService to avoid IMAP calls
        with patch('apps.core.views.EmailService') as mock_service_class:
            mock_service = MagicMock()
            mock_service.fetch_emails_by_date_range.return_value = {
                'new': 0,
                'existing': 10,
                'errors': []
            }
            mock_service_class.return_value = mock_service

            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        # Check context variables
        self.assertEqual(response.context['total_count'], 10)
        self.assertEqual(response.context['displayed_count'], 5)
        self.assertEqual(response.context['display_limit'], 5)

        # Verify only 5 emails in template
        emails = response.context['emails']
        self.assertEqual(len(emails), 5)

    def test_email_inbox_orders_by_most_recent(self):
        """Test that emails are ordered by date_sent descending (most recent first)."""
        # Create configuration
        Configuration.objects.create(key='email_display_limit', value='30')
        Configuration.objects.create(key='email_retention_days', value='90')

        # Create emails with different dates
        old_email_record = EmailRecord.objects.create(message_id='<old@example.com>')
        old_temp = TempEmail.objects.create(
            email_record=old_email_record,
            uid='1',
            from_email='old@example.com',
            to_email='recipient@example.com',
            date_sent=timezone.now() - timedelta(days=5),
            subject='Old Email'
        )

        new_email_record = EmailRecord.objects.create(message_id='<new@example.com>')
        new_temp = TempEmail.objects.create(
            email_record=new_email_record,
            uid='2',
            from_email='new@example.com',
            to_email='recipient@example.com',
            date_sent=timezone.now() - timedelta(hours=1),
            subject='New Email'
        )

        # Mock the EmailService
        with patch('apps.core.views.EmailService') as mock_service_class:
            mock_service = MagicMock()
            mock_service.fetch_emails_by_date_range.return_value = {
                'new': 0,
                'existing': 2,
                'errors': []
            }
            mock_service_class.return_value = mock_service

            response = self.client.get(self.url)

        emails = list(response.context['emails'])
        # Most recent should be first
        self.assertEqual(emails[0].temp_email_id, new_temp.temp_email_id)
        self.assertEqual(emails[1].temp_email_id, old_temp.temp_email_id)

    def test_email_inbox_uses_default_limit_when_no_config(self):
        """Test that inbox uses default limit of 30 when configuration doesn't exist."""
        # Ensure no configuration exists
        Configuration.objects.filter(key='email_config').delete()

        # Create 35 emails
        for i in range(35):
            email_record = EmailRecord.objects.create(
                message_id=f'<email{i}@example.com>'
            )
            TempEmail.objects.create(
                email_record=email_record,
                uid=str(2000 + i),
                from_email=f'sender{i}@example.com',
                to_email='recipient@example.com',
                date_sent=timezone.now() - timedelta(hours=i),
                subject=f'Email {i}'
            )

        # Mock the EmailService
        with patch('apps.core.views.EmailService') as mock_service_class:
            mock_service = MagicMock()
            mock_service.fetch_emails_by_date_range.return_value = {
                'new': 0,
                'existing': 35,
                'errors': []
            }
            mock_service_class.return_value = mock_service

            response = self.client.get(self.url)

        # Should use default limit of 30
        self.assertEqual(response.context['total_count'], 35)
        self.assertEqual(response.context['displayed_count'], 30)
        self.assertEqual(response.context['display_limit'], 30)

        emails = response.context['emails']
        self.assertEqual(len(emails), 30)

    def test_email_inbox_fetches_from_imap_on_load(self):
        """Test that inbox fetches emails from IMAP server on page load."""
        # Create configuration
        Configuration.objects.create(key='email_display_limit', value='30')
        Configuration.objects.create(key='email_retention_days', value='90')

        # Mock the EmailService
        with patch('apps.core.views.EmailService') as mock_service_class:
            mock_service = MagicMock()
            mock_service.fetch_emails_by_date_range.return_value = {
                'new': 5,
                'existing': 10,
                'errors': []
            }
            mock_service_class.return_value = mock_service

            response = self.client.get(self.url)

            # Verify fetch was called
            mock_service.fetch_emails_by_date_range.assert_called_once_with(days_back=30)

        # Check stats in context
        self.assertEqual(response.context['stats']['new'], 5)
        self.assertEqual(response.context['stats']['existing'], 10)

    def test_email_inbox_handles_imap_error_gracefully(self):
        """Test that inbox handles IMAP connection errors gracefully."""
        # Mock EmailService to raise exception
        with patch('apps.core.views.EmailService') as mock_service_class:
            mock_service = MagicMock()
            mock_service.fetch_emails_by_date_range.side_effect = Exception("IMAP connection failed")
            mock_service_class.return_value = mock_service

            response = self.client.get(self.url)

        # Should still render page with error stats
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['stats']['new'], 0)
        self.assertEqual(response.context['stats']['existing'], 0)
        self.assertIn('IMAP connection failed', response.context['stats']['errors'][0])

    def test_email_inbox_template_displays_counts(self):
        """Test that template displays correct count information."""
        # Create configuration
        Configuration.objects.create(key='email_display_limit', value='10')
        Configuration.objects.create(key='email_retention_days', value='90')

        # Create 15 emails
        for i in range(15):
            email_record = EmailRecord.objects.create(
                message_id=f'<test{i}@example.com>'
            )
            TempEmail.objects.create(
                email_record=email_record,
                uid=str(3000 + i),
                from_email=f'sender{i}@example.com',
                to_email='recipient@example.com',
                date_sent=timezone.now() - timedelta(hours=i),
                subject=f'Test {i}'
            )

        # Mock the EmailService
        with patch('apps.core.views.EmailService') as mock_service_class:
            mock_service = MagicMock()
            mock_service.fetch_emails_by_date_range.return_value = {
                'new': 5,
                'existing': 10,
                'errors': []
            }
            mock_service_class.return_value = mock_service

            response = self.client.get(self.url)

        # Check template content
        self.assertContains(response, 'Displaying:')
        self.assertContains(response, '10 of 15 total emails')
        self.assertContains(response, 'limit: 10')
        self.assertContains(response, 'Fetched from server:')
        self.assertContains(response, '5 new, 10 existing')
