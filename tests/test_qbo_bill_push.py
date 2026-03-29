from unittest.mock import patch, MagicMock
from decimal import Decimal
from django.test import TestCase
from apps.purchasing.models import Bill, BillLineItem
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration, AccountingCategory
from apps.qbo.services import QBOBillSyncService
from apps.qbo.models import QBOSyncLog


class BillQBOFieldsTest(TestCase):
    """Test QBO tracking fields on Bill model."""

    def setUp(self):
        Configuration.objects.create(key='bill_number_sequence', value='BILL-{year}-{counter:04d}')
        Configuration.objects.create(key='bill_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Smith',
            email='jane@vendor.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Supply Co', default_contact=self.contact,
        )

    def test_bill_has_qbo_id_null_by_default(self):
        bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='V-001',
        )
        self.assertIsNone(bill.qbo_id)

    def test_bill_has_qbo_payment_status_empty_by_default(self):
        bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='V-001',
        )
        self.assertEqual(bill.qbo_payment_status, '')

    def test_bill_can_store_qbo_data(self):
        bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='V-001',
        )
        bill.qbo_id = '5555'
        bill.qbo_payment_status = 'Paid'
        bill.save()
        bill.refresh_from_db()
        self.assertEqual(bill.qbo_id, '5555')
        self.assertEqual(bill.qbo_payment_status, 'Paid')


class QBOBillPushTest(TestCase):
    """Test pushing a bill to QBO."""

    def setUp(self):
        Configuration.objects.create(key='bill_number_sequence', value='BILL-{year}-{counter:04d}')
        Configuration.objects.create(key='bill_counter', value='0')

        self.cat_materials = AccountingCategory.objects.create(
            code='MAT', name='Materials',
            qbo_expense_account_id='500',
        )
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Smith',
            email='jane@vendor.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Supply Co', default_contact=self.contact,
            qbo_vendor_id='77',
        )
        self.bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='V-001',
        )
        BillLineItem.objects.create(
            bill=self.bill, qty=10, price=Decimal('25.00'),
            description='Steel bolts', accounting_category=self.cat_materials,
        )

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_bill_stores_qbo_id(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_qbo_bill = MagicMock()
        mock_qbo_bill.Id = '888'
        mock_qbo_bill.save = MagicMock(return_value=mock_qbo_bill)
        with patch('apps.qbo.services.QBOBillSyncService._build_qbo_bill',
                   return_value=mock_qbo_bill):
            result = QBOBillSyncService.push_bill(self.bill)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.qbo_id, '888')
        self.assertEqual(result, '888')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_bill_skips_if_already_synced(self, mock_get_client):
        self.bill.qbo_id = '888'
        self.bill.save()
        result = QBOBillSyncService.push_bill(self.bill)
        self.assertEqual(result, '888')
        mock_get_client.assert_not_called()

    @patch('apps.qbo.services.QBOService.get_client')
    @patch('apps.qbo.services.QBOVendorSyncService.push_vendor')
    def test_push_bill_auto_syncs_vendor(self, mock_push_vendor, mock_get_client):
        self.business.qbo_vendor_id = None
        self.business.save()
        mock_push_vendor.return_value = '77'
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_qbo_bill = MagicMock()
        mock_qbo_bill.Id = '888'
        mock_qbo_bill.save = MagicMock(return_value=mock_qbo_bill)
        with patch('apps.qbo.services.QBOBillSyncService._build_qbo_bill',
                   return_value=mock_qbo_bill):
            QBOBillSyncService.push_bill(self.bill)
        mock_push_vendor.assert_called_once_with(self.business)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_bill_logs_success(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_qbo_bill = MagicMock()
        mock_qbo_bill.Id = '888'
        mock_qbo_bill.save = MagicMock(return_value=mock_qbo_bill)
        with patch('apps.qbo.services.QBOBillSyncService._build_qbo_bill',
                   return_value=mock_qbo_bill):
            QBOBillSyncService.push_bill(self.bill)
        log = QBOSyncLog.objects.get(entity_type='bill')
        self.assertEqual(log.status, 'success')
        self.assertEqual(log.qbo_entity_id, '888')

    def test_push_bill_requires_connection(self):
        with self.assertRaises(ValueError):
            QBOBillSyncService.push_bill(self.bill)

    def test_build_bill_maps_line_items(self):
        qbo_bill = QBOBillSyncService._build_qbo_bill(self.bill)
        self.assertEqual(len(qbo_bill.Line), 1)
        self.assertEqual(qbo_bill.VendorRef.value, '77')
        self.assertEqual(qbo_bill.Line[0].Amount, 250.0)  # 10 * 25.00
        self.assertEqual(qbo_bill.Line[0].Description, 'Steel bolts')
