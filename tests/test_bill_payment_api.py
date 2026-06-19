from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory
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
             'method': 'check', 'reference': '4471'}, format='json')
        self.assertEqual(resp.status_code, 201)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PAID_IN_FULL)

    def test_delete_payment_returns_200_json(self):
        resp = self.client.post(
            f'/api/bills/{self.bill.pk}/payments/',
            {'amount': '40.00', 'payment_date': '2026-06-19T12:00:00Z',
             'method': 'cash'}, format='json')
        pid = resp.data['payment_id']
        d = self.client.delete(f'/api/bills/{self.bill.pk}/payments/{pid}/')
        self.assertEqual(d.status_code, 200)
        self.assertIn('message', d.data)

    def test_patch_payment_updates_reference_and_recomputes_status(self):
        # Record a partial payment (40 of 100) — bill should be partly_paid
        resp = self.client.post(
            f'/api/bills/{self.bill.pk}/payments/',
            {'amount': '100.00', 'payment_date': '2026-06-19T12:00:00Z',
             'method': 'check', 'reference': 'CHK-001'}, format='json')
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
