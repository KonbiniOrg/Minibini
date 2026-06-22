from decimal import Decimal
from unittest.mock import patch, MagicMock
import json
from django.test import TestCase
from django.utils import timezone
from apps.contacts.models import Business, Contact
from apps.core.models import Configuration
from apps.purchasing.models import Bill, BillPayment
from apps.purchasing.services import BillPaymentService


class BillPaymentLifecycleTests(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': json.dumps([
                {'qbo_account_id': '35', 'display_name': 'Checking', 'account_type': 'Bank'},
            ])},
        )
        contact = Contact.objects.create(first_name='Acme', last_name='Vendor')
        self.business = Business.objects.create(
            business_name='Acme Corp', default_contact=contact,
            qbo_vendor_id='qbo-vendor-1',
        )
        self.bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='INV-LC-1',
            status=Bill.STATUS_RECEIVED,
        )
        self.bill.qbo_id = 'qbo-bill-1'
        self.bill.save(update_fields=['qbo_id'])

    @patch('apps.qbo.services.QBOBillSyncService.update_bill_payment')
    @patch('apps.qbo.services.QBOBillSyncService.push_bill_payment')
    def test_edit_synced_payment_resyncs(self, mock_push, mock_update):
        pay = BillPayment.objects.create(
            bill=self.bill, amount=Decimal('50.00'), payment_date=timezone.now(),
            payment_account_id='35',
            qbo_id='qbo-bp-1', qbo_sync_status=BillPayment.SYNC_SYNCED,
        )
        BillPaymentService.update_payment(pay.pk, amount='75.00')
        mock_update.assert_called_once()
        mock_push.assert_not_called()

    @patch('apps.qbo.services.QBOBillSyncService.void_bill_payment')
    def test_delete_synced_payment_voids(self, mock_void):
        pay = BillPayment.objects.create(
            bill=self.bill, amount=Decimal('50.00'), payment_date=timezone.now(),
            payment_account_id='35',
            qbo_id='qbo-bp-2', qbo_sync_status=BillPayment.SYNC_SYNCED,
        )
        BillPaymentService.delete_payment(pay.pk)
        mock_void.assert_called_once()
