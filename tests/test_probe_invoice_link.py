"""probe_invoice_link management command — payment-link diagnostic."""
from io import StringIO
from unittest.mock import patch, MagicMock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class ProbeInvoiceLinkTest(SimpleTestCase):
    @patch('apps.qbo.services.QBOService.get_client')
    def test_prints_link_fields_and_full_response(self, mock_get_client):
        client = MagicMock()
        client.api_url = 'https://sandbox-quickbooks.api.intuit.com/v3'
        client.company_id = '9341'
        client.get.return_value = {
            'Invoice': {
                'Id': '179', 'DocNumber': '1060',
                'invoiceLink': 'https://pay.example/i/179',
                'AllowOnlineCreditCardPayment': True,
            },
        }
        mock_get_client.return_value = client

        out = StringIO()
        call_command('probe_invoice_link', '179', stdout=out)
        text = out.getvalue()

        self.assertIn('/invoice/179', text)
        self.assertIn('minorversion=75', text)
        self.assertIn('include=invoiceLink', text)
        self.assertIn("invoiceLink: 'https://pay.example/i/179'", text)
        self.assertIn('AllowOnlineCreditCardPayment: True', text)
        self.assertIn('"DocNumber": "1060"', text)

    @patch('apps.qbo.services.QBOService.get_client', return_value=None)
    def test_no_connection_errors_cleanly(self, mock_get_client):
        with self.assertRaises(CommandError):
            call_command('probe_invoice_link', '179')
