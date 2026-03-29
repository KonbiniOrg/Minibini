from unittest.mock import patch, MagicMock
from django.test import TestCase
from apps.core.services import OutboundEmailService


class OutboundEmailServiceTest(TestCase):
    """Test OutboundEmailService.send_email()."""

    @patch('django.core.mail.EmailMessage')
    def test_send_basic_email(self, MockEmailMessage):
        """Sends a basic email with to, subject, body."""
        mock_msg = MagicMock()
        MockEmailMessage.return_value = mock_msg

        OutboundEmailService.send_email(
            to=['customer@example.com'],
            subject='Your Invoice',
            body='Please find your invoice attached.',
        )

        MockEmailMessage.assert_called_once_with(
            subject='Your Invoice',
            body='Please find your invoice attached.',
            from_email='minibini.test@gmail.com',
            to=['customer@example.com'],
            cc=[],
            bcc=[],
        )
        mock_msg.send.assert_called_once()

    @patch('django.core.mail.EmailMessage')
    def test_send_with_cc_and_bcc(self, MockEmailMessage):
        """CC and BCC addresses are passed through."""
        mock_msg = MagicMock()
        MockEmailMessage.return_value = mock_msg

        OutboundEmailService.send_email(
            to=['customer@example.com'],
            subject='Invoice',
            body='See attached.',
            cc=['ap@example.com'],
            bcc=['internal@shop.com'],
        )

        MockEmailMessage.assert_called_once_with(
            subject='Invoice',
            body='See attached.',
            from_email='minibini.test@gmail.com',
            to=['customer@example.com'],
            cc=['ap@example.com'],
            bcc=['internal@shop.com'],
        )

    @patch('django.core.mail.EmailMessage')
    def test_send_with_attachment(self, MockEmailMessage):
        """Attachments are added to the email."""
        mock_msg = MagicMock()
        MockEmailMessage.return_value = mock_msg

        OutboundEmailService.send_email(
            to=['customer@example.com'],
            subject='Invoice',
            body='See attached.',
            attachments=[
                ('invoice.pdf', b'%PDF-fake', 'application/pdf'),
            ],
        )

        mock_msg.attach.assert_called_once_with(
            'invoice.pdf', b'%PDF-fake', 'application/pdf',
        )
        mock_msg.send.assert_called_once()

    @patch('django.core.mail.EmailMessage')
    def test_send_with_multiple_attachments(self, MockEmailMessage):
        """Multiple attachments are all added."""
        mock_msg = MagicMock()
        MockEmailMessage.return_value = mock_msg

        OutboundEmailService.send_email(
            to=['customer@example.com'],
            subject='Invoice',
            body='See attached.',
            attachments=[
                ('invoice.pdf', b'%PDF-1', 'application/pdf'),
                ('statement.pdf', b'%PDF-2', 'application/pdf'),
            ],
        )

        self.assertEqual(mock_msg.attach.call_count, 2)

    @patch('django.core.mail.EmailMessage')
    def test_send_with_custom_from(self, MockEmailMessage):
        """Custom from_email overrides the default."""
        mock_msg = MagicMock()
        MockEmailMessage.return_value = mock_msg

        OutboundEmailService.send_email(
            to=['customer@example.com'],
            subject='Invoice',
            body='See attached.',
            from_email='billing@myshop.com',
        )

        call_kwargs = MockEmailMessage.call_args[1]
        self.assertEqual(call_kwargs['from_email'], 'billing@myshop.com')
