import json
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, Configuration
from apps.purchasing.models import Bill, BillLineItem

User = get_user_model()


class BillPaymentApiTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='fin', password='x')
        from django.contrib.auth.models import Permission
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials'))
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.contact = Contact.objects.create(first_name='Acme', last_name='Steel', email='c@acme.com')
        self.business = Business.objects.create(business_name='Acme', default_contact=self.contact)
        self.ac = AccountingCategory.objects.create(code='MAT', name='Materials')
        self.bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='INV-1',
            status=Bill.STATUS_RECEIVED)
        BillLineItem.objects.create(
            bill=self.bill, line_number=1, description='Steel',
            qty=Decimal('1'), price=Decimal('100.00'),
            units='none', accounting_category=self.ac)

    def test_record_payment_endpoint(self):
        resp = self.client.post(
            f'/api/bills/{self.bill.pk}/payments/',
            {'amount': '100.00', 'payment_date': '2026-06-19T12:00:00Z',
             'reference': '4471'}, format='json')
        self.assertEqual(resp.status_code, 201)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PAID_IN_FULL)

    def test_record_payment_accepts_json_float_amount(self):
        # A `type=number` input sends the amount as a JSON float; a non-binary-
        # representable value like 33.33 becomes 33.3299... when Django converts
        # the float to Decimal, which used to trip the decimal_places=2 validator.
        # The endpoint must normalize it and accept the exact 2-decimal value.
        resp = self.client.post(
            f'/api/bills/{self.bill.pk}/payments/',
            {'amount': 33.33, 'payment_date': '2026-06-19T12:00:00Z'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['amount'], '33.33')
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PARTLY_PAID)

    def test_record_payment_rejects_over_precise_amount(self):
        # Genuine >2-decimal input must still be rejected (validation preserved).
        resp = self.client.post(
            f'/api/bills/{self.bill.pk}/payments/',
            {'amount': '33.333', 'payment_date': '2026-06-19T12:00:00Z'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_delete_payment_returns_200_json(self):
        resp = self.client.post(
            f'/api/bills/{self.bill.pk}/payments/',
            {'amount': '40.00', 'payment_date': '2026-06-19T12:00:00Z'}, format='json')
        pid = resp.data['payment_id']
        d = self.client.delete(f'/api/bills/{self.bill.pk}/payments/{pid}/')
        self.assertEqual(d.status_code, 200)
        self.assertIn('message', d.data)

    @patch('apps.qbo.services.QBOService.get_client', return_value=object())
    def test_record_payment_requires_account_when_qbo_connected(self, _c):
        """When QBO is connected, omitting payment_account_id must return 400."""
        resp = self.client.post(
            f'/api/bills/{self.bill.pk}/payments/',
            {'amount': '10.00', 'payment_date': timezone.now().isoformat()},
            format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('payment_account_id', resp.json())

    @patch('apps.qbo.services.QBOBillSyncService.push_bill_payment', return_value=None)
    @patch('apps.qbo.services.QBOService.get_client', return_value=object())
    def test_record_payment_with_account_returns_qbo_sync_status(self, _c, _p):
        """When account is supplied, the response must include qbo_sync_status."""
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': json.dumps([
                {'qbo_account_id': '35', 'display_name': 'Checking', 'account_type': 'Bank'},
            ])},
        )
        resp = self.client.post(
            f'/api/bills/{self.bill.pk}/payments/',
            {'amount': '10.00', 'payment_date': timezone.now().isoformat(),
             'payment_account_id': '35'},
            format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertIn('qbo_sync_status', resp.json())

    def test_patch_payment_updates_reference_and_recomputes_status(self):
        # Record a partial payment (40 of 100) — bill should be partly_paid
        resp = self.client.post(
            f'/api/bills/{self.bill.pk}/payments/',
            {'amount': '100.00', 'payment_date': '2026-06-19T12:00:00Z',
             'reference': 'CHK-001'}, format='json')
        self.assertEqual(resp.status_code, 201)
        pid = resp.data['payment_id']
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PAID_IN_FULL)

        # PATCH: change reference and reduce amount so bill is no longer fully paid
        patch_resp = self.client.patch(
            f'/api/bills/{self.bill.pk}/payments/{pid}/',
            {'reference': 'CHK-002', 'amount': '40.00'}, format='json')
        self.assertEqual(patch_resp.status_code, 200)
        self.assertEqual(patch_resp.data['reference'], 'CHK-002')
        self.assertEqual(patch_resp.data['amount'], '40.00')

        # Bill status should have recomputed to partly_paid
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PARTLY_PAID)
