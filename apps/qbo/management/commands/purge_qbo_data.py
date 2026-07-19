"""Purge every QBO-company-scoped value from the database.

Prepares a dataset built against one QBO (sandbox) company for use against
another — e.g. prepping a sample dataset for a staging instance. Clears the
category mappings, the payment-account list, every stored QBO id and payment
cache, and the connection + sync-log rows.

Deliberately writes directly to the DB (bulk update/delete): none of these
fields are normalized by save(), and skipping side effects is the point —
this is a data-surgery tool, not a domain operation. Known follow-on effect:
records whose payment state came from the old company keep that state
(e.g. paid invoices stay paid) with no QBO record behind it.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, Configuration
from apps.expenses.models import Expense, Reimbursement
from apps.invoicing.models import Invoice
from apps.purchasing.models import Bill, BillPayment
from apps.qbo.models import QBOConnection, QBOSyncLog


class Command(BaseCommand):
    help = ('Remove all QBO-scoped data (mappings, payment accounts, qbo ids, '
            'connection, sync log) so the dataset can be pointed at a '
            'different QBO company.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--yes', action='store_true',
            help='Skip the confirmation prompt.')

    def handle(self, *args, **options):
        if not options['yes']:
            answer = input(
                'This permanently removes all QBO mappings, ids, connection '
                'and sync-log data from the database. Continue? [y/N] ')
            if answer.strip().lower() not in ('y', 'yes'):
                self.stdout.write('Aborted.')
                return

        syncable_reset = {
            'qbo_id': '', 'qbo_sync_status': Expense.SYNC_PENDING,
            'qbo_sync_error': '', 'qbo_pending_op': Expense.OP_NONE,
        }

        with transaction.atomic():
            counts = {
                'accounting categories': AccountingCategory.objects.update(
                    qbo_item_id='', qbo_expense_account_id=''),
                'invoices': Invoice.objects.update(
                    qbo_id=None, qbo_payment_status='', qbo_amount_paid=None),
                'bills': Bill.objects.update(
                    qbo_id=None, qbo_payment_status=''),
                'businesses': Business.objects.update(
                    qbo_customer_id=None, qbo_vendor_id=None),
                'contacts': Contact.objects.update(qbo_customer_id=None),
                'expenses': Expense.objects.update(**syncable_reset),
                'reimbursements': Reimbursement.objects.update(
                    **syncable_reset),
                'bill payments': BillPayment.objects.update(**syncable_reset),
                'payment-account config rows': Configuration.objects.filter(
                    key='qbo_payment_accounts').delete()[0],
                'connections': QBOConnection.objects.all().delete()[0],
                'sync log rows': QBOSyncLog.objects.all().delete()[0],
            }

        for label, count in counts.items():
            self.stdout.write(f'{label}: {count}')
        self.stdout.write(self.style.SUCCESS('QBO data purged.'))
