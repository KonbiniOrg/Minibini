from unittest.mock import patch, MagicMock, ANY
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration, AccountingCategory, AppState
from apps.qbo.services import QBOInvoiceSyncService
from apps.qbo.models import QBOSyncLog

User = get_user_model()


class InvoiceQBOFieldsTest(TestCase):
    """Test QBO tracking fields on Invoice model."""

    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme Corp', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(job_number='JOB-2026-0001', contact=self.contact)

    def test_invoice_has_qbo_id(self):
        inv = Invoice.objects.create(job=self.job)
        self.assertIsNone(inv.qbo_id)

    def test_invoice_has_qbo_payment_status(self):
        inv = Invoice.objects.create(job=self.job)
        self.assertEqual(inv.qbo_payment_status, '')

    def test_invoice_has_qbo_amount_paid(self):
        inv = Invoice.objects.create(job=self.job)
        self.assertIsNone(inv.qbo_amount_paid)

    def test_invoice_can_store_qbo_data(self):
        inv = Invoice.objects.create(job=self.job)
        inv.qbo_id = '12345'
        inv.qbo_payment_status = 'Paid'
        inv.qbo_amount_paid = 4250.00
        inv.save()
        inv.refresh_from_db()
        self.assertEqual(inv.qbo_id, '12345')
        self.assertEqual(inv.qbo_payment_status, 'Paid')
        self.assertEqual(inv.qbo_amount_paid, 4250.00)

    def test_customer_business_chain(self):
        """Can traverse Invoice → Job → Contact → Business."""
        inv = Invoice.objects.create(job=self.job)
        business = inv.job.contact.business
        self.assertEqual(business.business_name, 'Acme Corp')


class PerLineInvoiceBuilderTest(TestCase):
    """_build_qbo_invoice pushes each konbini line individually: verbatim
    Description, per-line TaxCodeRef from the category flag, resolved
    ItemRef, CustomerMemo job reference, BillEmail, payment flags."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(
            job_number='JOB-2026-0007', contact=self.contact,
            name='Cabinet run',
        )
        self.taxable_cat = AccountingCategory.objects.create(
            code='MAT', name='Material', taxable=True, qbo_item_id='55',
        )
        self.nontax_cat = AccountingCategory.objects.create(
            code='FRT', name='Freight', taxable=False, qbo_item_id='66',
        )
        self.bare_cat = AccountingCategory.objects.create(
            code='MISC', name='Misc', taxable=True, qbo_item_id='',
        )
        self.invoice = Invoice.objects.create(
            job=self.job, invoice_number='INV-BLD-1',
        )

    def _line(self, line_number, description, qty, price, category):
        return InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=line_number,
            description=description, qty=Decimal(qty),
            price=Decimal(price), accounting_category=category,
        )

    def _build(self):
        return QBOInvoiceSyncService._build_qbo_invoice(
            self.invoice, '77', MagicMock(),
        )

    def test_one_sales_line_per_konbini_line_in_order(self):
        self._line(2, 'Second line', '1', '10.00', self.taxable_cat)
        self._line(1, 'First line', '2', '5.50', self.taxable_cat)
        self._line(3, 'Third line', '1', '3.00', self.nontax_cat)
        qbo_inv = self._build()
        self.assertEqual(len(qbo_inv.Line), 3)
        self.assertEqual(
            [l.Description for l in qbo_inv.Line],
            ['First line', 'Second line', 'Third line'],
        )
        self.assertEqual(qbo_inv.Line[0].Amount, 11.0)
        self.assertEqual(qbo_inv.Line[1].Amount, 10.0)

    def test_tax_code_from_category_flag(self):
        self._line(1, 'Taxed', '1', '10.00', self.taxable_cat)
        self._line(2, 'Untaxed', '1', '10.00', self.nontax_cat)
        qbo_inv = self._build()
        self.assertEqual(
            qbo_inv.Line[0].SalesItemLineDetail.TaxCodeRef.value, 'TAX')
        self.assertEqual(
            qbo_inv.Line[1].SalesItemLineDetail.TaxCodeRef.value, 'NON')

    def test_item_ref_from_category_fallback(self):
        self._line(1, 'Plain', '1', '10.00', self.taxable_cat)
        qbo_inv = self._build()
        self.assertEqual(
            qbo_inv.Line[0].SalesItemLineDetail.ItemRef.value, '55')

    def test_item_ref_omitted_for_unmapped_category(self):
        self._line(1, 'Bare', '1', '10.00', self.bare_cat)
        qbo_inv = self._build()
        self.assertIsNone(qbo_inv.Line[0].SalesItemLineDetail.ItemRef)

    def test_item_ref_resolution_consulted_per_line(self):
        self._line(1, 'Resolved', '1', '10.00', self.taxable_cat)
        with patch(
            'apps.qbo.services.QBOInvoiceSyncService._resolve_item_ref',
            return_value='901',
        ) as mock_resolve:
            qbo_inv = self._build()
        mock_resolve.assert_called_once()
        self.assertEqual(
            qbo_inv.Line[0].SalesItemLineDetail.ItemRef.value, '901')

    def test_customer_memo_carries_job_reference(self):
        self._line(1, 'L', '1', '1.00', self.taxable_cat)
        qbo_inv = self._build()
        self.assertEqual(
            qbo_inv.CustomerMemo.value, 'Job JOB-2026-0007 — Cabinet run')

    def test_bill_email_from_contact(self):
        self._line(1, 'L', '1', '1.00', self.taxable_cat)
        qbo_inv = self._build()
        self.assertEqual(qbo_inv.BillEmail.Address, 'john@example.com')

    def test_bill_email_omitted_without_contact_email(self):
        self.contact.email = ''
        self.contact.save()
        self._line(1, 'L', '1', '1.00', self.taxable_cat)
        qbo_inv = self._build()
        self.assertIsNone(qbo_inv.BillEmail)

    def test_online_payment_flags_enabled(self):
        self._line(1, 'L', '1', '1.00', self.taxable_cat)
        qbo_inv = self._build()
        self.assertTrue(qbo_inv.AllowOnlineCreditCardPayment)
        self.assertTrue(qbo_inv.AllowOnlineACHPayment)

    def test_customer_ref_set(self):
        self._line(1, 'L', '1', '1.00', self.taxable_cat)
        qbo_inv = self._build()
        self.assertEqual(qbo_inv.CustomerRef.value, '77')


