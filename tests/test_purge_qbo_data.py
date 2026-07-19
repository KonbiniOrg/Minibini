"""Tests for the purge_qbo_data management command.

The command strips every QBO-company-scoped value from the database so a
dataset prepared against one sandbox company can be pointed at another
(e.g. prepping a sample dataset for staging). See
docs/designs/quickbooks-integration.md.
"""
import json
from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.utils import timezone

from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, Configuration, User
from apps.expenses.models import Expense, Reimbursement
from apps.invoicing.models import Invoice
from apps.purchasing.models import Bill, BillPayment
from apps.qbo.models import QBOConnection, QBOSyncLog
from tests.base import BaseTestCase


class PurgeQBODataTest(BaseTestCase):
    """purge_qbo_data clears mappings, config, ids, caches, and QBO rows."""

    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.user = User.objects.first()

        # Stamp QBO-scoped values onto fixture rows. Direct updates are
        # deliberate: these are test preconditions, not domain writes.
        AccountingCategory.objects.update(
            qbo_item_id='11', qbo_expense_account_id='22')
        Invoice.objects.update(
            qbo_id='301', qbo_payment_status='Paid',
            qbo_amount_paid=Decimal('100.00'), status=Invoice.STATUS_PAID)
        Bill.objects.update(qbo_id='401', qbo_payment_status='Paid')
        Business.objects.update(qbo_customer_id='51', qbo_vendor_id='52')
        Contact.objects.update(qbo_customer_id='61')

        self.expense = Expense.objects.create(
            entered_by=self.user, amount=Decimal('25.00'),
            purchased_on=date(2026, 7, 1),
            accounting_category=AccountingCategory.objects.first(),
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='42',
            qbo_id='701', qbo_sync_status=Expense.SYNC_SYNCED)

        self.reimbursement = Reimbursement.objects.create(
            purchased_by=self.user, created_by=self.user,
            paid_on=date(2026, 7, 2), payment_account_id='42',
            qbo_sync_status=Reimbursement.SYNC_FAILED,
            qbo_sync_error='boom', qbo_pending_op=Reimbursement.OP_CREATE)

        self.bill_payment = BillPayment.objects.create(
            bill=Bill.objects.first(), amount=Decimal('10.00'),
            payment_date=now, payment_account_id='42',
            qbo_id='801', qbo_sync_status=BillPayment.SYNC_SYNCED)

        QBOConnection.objects.create(
            realm_id='9130350000000000', access_token='tok',
            refresh_token='ref',
            access_token_expires_at=now + timezone.timedelta(hours=1),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now)

        QBOSyncLog.objects.create(
            entity_type='invoice', entity_id=1, qbo_entity_type='Invoice',
            qbo_entity_id='301', action='create', status='success')

        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': json.dumps([
                {'qbo_account_id': '42', 'display_name': 'Checking',
                 'account_type': 'Bank'}])})
        Configuration.objects.update_or_create(
            key='unrelated_key', defaults={'value': 'keep-me'})

    def purge(self):
        out = StringIO()
        call_command('purge_qbo_data', '--yes', stdout=out)
        return out.getvalue()

    def test_clears_accounting_category_mappings(self):
        self.purge()
        for cat in AccountingCategory.objects.all():
            self.assertEqual(cat.qbo_item_id, '')
            self.assertEqual(cat.qbo_expense_account_id, '')

    def test_deletes_payment_accounts_config_and_keeps_other_keys(self):
        self.purge()
        self.assertFalse(
            Configuration.objects.filter(key='qbo_payment_accounts').exists())
        self.assertEqual(
            Configuration.objects.get(key='unrelated_key').value, 'keep-me')

    def test_clears_invoice_qbo_fields_but_not_status(self):
        self.purge()
        for invoice in Invoice.objects.all():
            self.assertIsNone(invoice.qbo_id)
            self.assertEqual(invoice.qbo_payment_status, '')
            self.assertIsNone(invoice.qbo_amount_paid)
            self.assertEqual(invoice.status, Invoice.STATUS_PAID)

    def test_clears_bill_qbo_fields(self):
        self.purge()
        for bill in Bill.objects.all():
            self.assertIsNone(bill.qbo_id)
            self.assertEqual(bill.qbo_payment_status, '')

    def test_clears_business_and_contact_ids(self):
        self.purge()
        for business in Business.objects.all():
            self.assertIsNone(business.qbo_customer_id)
            self.assertIsNone(business.qbo_vendor_id)
        for contact in Contact.objects.all():
            self.assertIsNone(contact.qbo_customer_id)

    def test_resets_syncable_records(self):
        self.purge()
        for record in (Expense.objects.get(pk=self.expense.pk),
                       Reimbursement.objects.get(pk=self.reimbursement.pk),
                       BillPayment.objects.get(pk=self.bill_payment.pk)):
            self.assertEqual(record.qbo_id, '')
            self.assertEqual(record.qbo_sync_status, record.SYNC_PENDING)
            self.assertEqual(record.qbo_sync_error, '')
            self.assertEqual(record.qbo_pending_op, record.OP_NONE)

    def test_keeps_payment_account_id_values(self):
        # Dangling references to the purged account list are accepted; the
        # which-account information itself is kept readable.
        self.purge()
        self.assertEqual(
            Expense.objects.get(pk=self.expense.pk).payment_account_id, '42')
        self.assertEqual(
            BillPayment.objects.get(
                pk=self.bill_payment.pk).payment_account_id, '42')

    def test_deletes_connection_and_sync_log(self):
        self.purge()
        self.assertEqual(QBOConnection.objects.count(), 0)
        self.assertEqual(QBOSyncLog.objects.count(), 0)

    def test_prompt_declined_aborts_without_changes(self):
        out = StringIO()
        with patch('builtins.input', return_value='n'):
            call_command('purge_qbo_data', stdout=out)
        self.assertEqual(QBOConnection.objects.count(), 1)
        self.assertEqual(Invoice.objects.exclude(qbo_id=None).count(), 2)
        self.assertIn('Aborted', out.getvalue())

    def test_prompt_accepted_purges(self):
        with patch('builtins.input', return_value='y'):
            call_command('purge_qbo_data', stdout=StringIO())
        self.assertEqual(QBOConnection.objects.count(), 0)
