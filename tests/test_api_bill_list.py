from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.contacts.models import Business
from apps.purchasing.models import Bill, BillLineItem


class BillListAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.vendor = Business.objects.first()

    def _bill(self, status=Bill.STATUS_RECEIVED, due_days=10,
              qty='2', price='25.00', number='V-100'):
        bill = Bill.objects.create(
            business=self.vendor, vendor_invoice_number=number, status=status,
            due_date=timezone.now() + timedelta(days=due_days),
        )
        BillLineItem.objects.create(
            bill=bill, line_number=1, description='Parts',
            qty=Decimal(qty), units='ea', price=Decimal(price),
        )
        return bill

    def test_list_exposes_vendor_total_balance_and_dates(self):
        bill = self._bill(qty='2', price='25.00')  # total 50
        resp = self.client.get('/api/bills/?summary=true&status=all')
        self.assertEqual(resp.status_code, 200)
        row = next(r for r in resp.data['results'] if r['bill_id'] == bill.bill_id)
        self.assertEqual(row['vendor_name'], self.vendor.business_name)
        self.assertEqual(row['total'], '50.00')
        self.assertEqual(row['balance'], '50.00')  # received => full balance
        self.assertIn('due_date', row)
        self.assertIn('received_date', row)

    def test_paid_in_full_balance_is_zero(self):
        bill = self._bill(status=Bill.STATUS_PAID_IN_FULL)
        resp = self.client.get('/api/bills/?summary=true&status=all')
        row = next(r for r in resp.data['results'] if r['bill_id'] == bill.bill_id)
        self.assertEqual(row['balance'], '0.00')

    def test_detail_and_summary_balance_agree(self):
        """The detail (BillSerializer, Python) and summary (annotation) paths
        share one coarse-balance rule and must never report different numbers
        for the same bill — including resolved statuses like refunded."""
        for status, expected in (
            (Bill.STATUS_RECEIVED, '50.00'),
            (Bill.STATUS_REFUNDED, '0.00'),
        ):
            bill = self._bill(status=status, number=f'V-AGREE-{status}')
            detail = self.client.get(f'/api/bills/{bill.bill_id}/')
            summary = self.client.get('/api/bills/?summary=true&status=all')
            srow = next(r for r in summary.data['results']
                        if r['bill_id'] == bill.bill_id)
            self.assertEqual(detail.data['balance'], expected)
            self.assertEqual(srow['balance'], expected)
            self.assertEqual(detail.data['balance'], srow['balance'])

    def test_default_filter_is_open(self):
        received = self._bill(status=Bill.STATUS_RECEIVED, number='V-OPEN')
        draft = self._bill(status=Bill.STATUS_DRAFT, number='V-DRAFT')
        paid = self._bill(status=Bill.STATUS_PAID_IN_FULL, number='V-PAID')
        resp = self.client.get('/api/bills/?summary=true')  # no status param
        ids = {r['bill_id'] for r in resp.data['results']}
        self.assertIn(received.bill_id, ids)
        self.assertNotIn(draft.bill_id, ids)
        self.assertNotIn(paid.bill_id, ids)

    def test_default_ordering_due_date_ascending(self):
        soonest = self._bill(due_days=2, number='V-SOON')
        latest = self._bill(due_days=40, number='V-LATE')
        resp = self.client.get('/api/bills/?summary=true&status=open')
        ordered = [r['bill_id'] for r in resp.data['results']]
        self.assertLess(ordered.index(soonest.bill_id),
                        ordered.index(latest.bill_id))

    def test_filter_by_business_exact(self):
        bill = self._bill(number='V-BIZ')
        resp = self.client.get(f'/api/bills/?summary=true&status=all&business={self.vendor.pk}')
        self.assertEqual(resp.status_code, 200)
        ids = {r['bill_id'] for r in resp.data['results']}
        self.assertIn(bill.bill_id, ids)

    def test_status_draft_preset(self):
        draft = self._bill(status=Bill.STATUS_DRAFT, number='V-DRAFT2')
        received = self._bill(status=Bill.STATUS_RECEIVED, number='V-RECV2')
        resp = self.client.get('/api/bills/?summary=true&status=draft')
        self.assertEqual(resp.status_code, 200)
        ids = {r['bill_id'] for r in resp.data['results']}
        self.assertIn(draft.bill_id, ids)
        self.assertNotIn(received.bill_id, ids)
