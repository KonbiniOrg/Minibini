from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.contacts.models import Business
from apps.purchasing.models import Bill, BillLineItem
from apps.purchasing.services import BillService


class BillDetailSerializerTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.vendor = Business.objects.first()

    def test_detail_includes_due_paid_and_balance(self):
        bill = Bill.objects.create(
            business=self.vendor, vendor_invoice_number='V-DET',
            status=Bill.STATUS_RECEIVED,
            due_date=timezone.now() + timedelta(days=15),
        )
        BillLineItem.objects.create(
            bill=bill, line_number=1, description='X',
            qty=Decimal('3'), units='ea', price=Decimal('10.00'))
        resp = self.client.get(f'/api/bills/{bill.bill_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('due_date', resp.data)
        self.assertIn('paid_date', resp.data)
        self.assertEqual(resp.data['balance'], '30.00')


class BillUpdateServiceTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.vendor = Business.objects.first()

    def test_update_bill_changes_header_on_draft(self):
        bill = Bill.objects.create(business=self.vendor,
                                   vendor_invoice_number='OLD',
                                   status=Bill.STATUS_DRAFT)
        BillService.update_bill(bill.pk, vendor_invoice_number='NEW')
        bill.refresh_from_db()
        self.assertEqual(bill.vendor_invoice_number, 'NEW')

    def test_update_bill_rejected_on_non_draft(self):
        bill = Bill.objects.create(business=self.vendor,
                                   vendor_invoice_number='LOCK',
                                   status=Bill.STATUS_RECEIVED)
        with self.assertRaises(ValidationError):
            BillService.update_bill(bill.pk, vendor_invoice_number='NOPE')


class BillEditingAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.admin = User.objects.get(username='admin')
        self.worker = User.objects.get(username='johnq')
        self.client.force_authenticate(user=self.admin)
        self.vendor = Business.objects.first()

    def _draft(self, number='V-EDIT'):
        return Bill.objects.create(business=self.vendor,
                                   vendor_invoice_number=number,
                                   status=Bill.STATUS_DRAFT)

    def _draft_with_line(self, number='V-LINE'):
        bill = self._draft(number)
        BillLineItem.objects.create(bill=bill, line_number=1, description='X',
                                    qty=Decimal('1'), units='ea',
                                    price=Decimal('5.00'))
        return bill

    def test_patch_updates_draft_header(self):
        bill = self._draft()
        resp = self.client.patch(f'/api/bills/{bill.bill_id}/',
                                 {'vendor_invoice_number': 'V-NEW'},
                                 format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        bill.refresh_from_db()
        self.assertEqual(bill.vendor_invoice_number, 'V-NEW')

    def test_patch_non_draft_rejected(self):
        bill = self._draft_with_line('V-RX')
        self.client.post(f'/api/bills/{bill.bill_id}/receive/', format='json')
        resp = self.client.patch(f'/api/bills/{bill.bill_id}/',
                                 {'vendor_invoice_number': 'V-NO'},
                                 format='json')
        self.assertEqual(resp.status_code, 400)

    def test_receive_requires_line_item(self):
        bill = self._draft('V-EMPTY')
        resp = self.client.post(f'/api/bills/{bill.bill_id}/receive/',
                                format='json')
        self.assertEqual(resp.status_code, 400)

    def test_receive_then_mark_paid(self):
        bill = self._draft_with_line('V-PAY')
        r1 = self.client.post(f'/api/bills/{bill.bill_id}/receive/',
                              format='json')
        self.assertEqual(r1.status_code, 200, r1.data)
        bill.refresh_from_db()
        self.assertEqual(bill.status, Bill.STATUS_RECEIVED)
        r2 = self.client.post(f'/api/bills/{bill.bill_id}/mark_paid/',
                              format='json')
        self.assertEqual(r2.status_code, 200, r2.data)
        bill.refresh_from_db()
        self.assertEqual(bill.status, Bill.STATUS_PAID_IN_FULL)
        self.assertIsNotNone(bill.paid_date)

    def test_cancel_requires_reason(self):
        bill = self._draft_with_line('V-CXL')
        self.client.post(f'/api/bills/{bill.bill_id}/receive/', format='json')
        resp = self.client.post(f'/api/bills/{bill.bill_id}/cancel/',
                                format='json')
        self.assertEqual(resp.status_code, 400)

    def test_worker_cannot_edit(self):
        bill = self._draft('V-PERM')
        self.client.force_authenticate(user=self.worker)
        resp = self.client.patch(f'/api/bills/{bill.bill_id}/',
                                 {'vendor_invoice_number': 'V-X'},
                                 format='json')
        self.assertEqual(resp.status_code, 403)
