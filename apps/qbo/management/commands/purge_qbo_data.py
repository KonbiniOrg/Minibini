"""Strip every QBO-company-scoped value from a dumpdata JSON file.

Reads a `manage.py dumpdata` JSON dump and writes a copy with the QBO
category mappings, payment-account list, stored QBO ids, payment caches,
and connection/sync-log records removed — so a dataset prepared against one
QBO (sandbox) company can be loaded into an instance that will connect to a
different one (e.g. prepping a staging seed). Never touches a database.

Models absent from the dump (e.g. QBO features with no data yet) are simply
not there to scrub; when new QBO-coupled models or fields land, extend the
tables below and recheck against a fresh dump.

Known follow-on effect: domain state derived from the old company stays
as-is (paid invoices stay paid with no QBO record behind them), and
payment_account_id values are kept even though the account list they
reference is purged.
"""
import json

from django.core.management.base import BaseCommand

from apps.core.models import QBOSyncable

SYNCABLE_RESET = {
    'qbo_id': '',
    'qbo_sync_status': QBOSyncable.SYNC_PENDING,
    'qbo_sync_error': '',
    'qbo_pending_op': QBOSyncable.OP_NONE,
}

# model label -> field overrides applied to that model's records. Only keys
# actually present in a record are overwritten, so an older dump that
# predates a field never gains one it can't loaddata.
FIELD_RESETS = {
    'core.accountingcategory': {'qbo_item_id': '', 'qbo_expense_account_id': ''},
    'invoicing.invoice': {'qbo_id': None, 'qbo_payment_status': '',
                          'qbo_amount_paid': None},
    'purchasing.bill': {'qbo_id': None, 'qbo_payment_status': ''},
    'inventory.inventoryitem': {'qbo_id': ''},
    'estimates.serviceitem': {'qbo_id': ''},
    'contacts.business': {'qbo_customer_id': None, 'qbo_vendor_id': None},
    'contacts.contact': {'qbo_customer_id': None},
    'expenses.expense': SYNCABLE_RESET,
    'expenses.reimbursement': SYNCABLE_RESET,
    'purchasing.billpayment': SYNCABLE_RESET,
}

DROP_MODELS = {'qbo.qboconnection', 'qbo.qbosynclog'}


class Command(BaseCommand):
    help = ('Read a dumpdata JSON file and write a copy with all QBO-scoped '
            'data (mappings, payment accounts, qbo ids, connection, sync '
            'log) removed, so the dataset can be pointed at a different '
            'QBO company.')

    def add_arguments(self, parser):
        parser.add_argument('input', help='Path to a dumpdata JSON file.')
        parser.add_argument('output', help='Path to write the purged copy '
                            '(may equal input for in-place).')

    def handle(self, *args, **options):
        with open(options['input']) as f:
            records = json.load(f)

        kept = []
        scrubbed = {}
        dropped = {}
        for rec in records:
            model = rec['model']
            fields = rec['fields']
            if model in DROP_MODELS or (
                    model == 'core.configuration'
                    and fields.get('key') == 'qbo_payment_accounts'):
                dropped[model] = dropped.get(model, 0) + 1
                continue
            resets = FIELD_RESETS.get(model)
            if resets:
                changed = False
                for key, value in resets.items():
                    if key in fields and fields[key] != value:
                        fields[key] = value
                        changed = True
                if changed:
                    scrubbed[model] = scrubbed.get(model, 0) + 1
            kept.append(rec)

        with open(options['output'], 'w') as f:
            json.dump(kept, f, indent=2)

        for model, count in sorted(scrubbed.items()):
            self.stdout.write(f'{model}: {count} scrubbed')
        for model, count in sorted(dropped.items()):
            self.stdout.write(f'{model}: {count} dropped')
        self.stdout.write(self.style.SUCCESS(
            f'{len(kept)} records written ({len(records) - len(kept)} '
            'dropped).'))
