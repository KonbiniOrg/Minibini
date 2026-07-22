"""Diagnostic: fetch a QBO invoice with include=invoiceLink and dump the
raw response — for verifying why a payment link is (or isn't) returned.

Usage:
    python manage.py probe_invoice_link <qbo_invoice_id>

Read-only against QBO (a plain GET). May refresh the stored OAuth access
token as a side effect of obtaining the client, exactly as the app does.
"""
import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ('Fetch a QBO invoice with include=invoiceLink and print the raw '
            'response (payment-link diagnostic).')

    def add_arguments(self, parser):
        parser.add_argument('qbo_invoice_id', help='QBO-side invoice Id (e.g. 179)')

    def handle(self, *args, **options):
        from apps.qbo.services import QBOService

        client = QBOService.get_client()
        if not client:
            raise CommandError('No active QBO connection.')

        qbo_id = options['qbo_invoice_id']
        url = "{0}/company/{1}/invoice/{2}/".format(
            client.api_url, client.company_id, qbo_id)
        params = {'include': 'invoiceLink', 'minorversion': '75'}

        self.stdout.write(f'GET {url}')
        self.stdout.write(f'params: {params}')

        result = client.get(url, {}, params=params)

        invoice = result.get('Invoice') or {}
        self.stdout.write('\n--- payment-relevant fields ---')
        for key in ('Id', 'DocNumber', 'invoiceLink',
                    'AllowOnlineCreditCardPayment', 'AllowOnlineACHPayment',
                    'AllowOnlinePayment', 'EmailStatus', 'BillEmail'):
            self.stdout.write(f'{key}: {invoice.get(key)!r}')

        self.stdout.write('\n--- full response ---')
        self.stdout.write(json.dumps(result, indent=2, default=str))
