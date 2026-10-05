"""
Tests for the negative-total send-gate precheck in InvoiceEmailService
(I3 review finding).

QuickBooks Online rejects a negative-total invoice outright. Before any
QBO/PDF/email work, send_invoice must raise
django.core.exceptions.ValidationError if the invoice's line items sum to a
negative grand total. The helper _assert_total_non_negative(invoice) is
tested directly so the positive-path test never reaches external calls
(QBO/email) — same pattern as test_invoice_send_category_gate.py.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.core.models import AccountingCategory, AppState, Configuration
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.services import InvoiceEmailService


class InvoiceSendNegativeTotalGateTest(TestCase):
    def setUp(self):
        Configuration.objects.create(
            key='invoice_number_sequence', value='INV-{year}-{counter:04d}',
        )
        AppState.objects.create(key='invoice_counter', value='0')

        self.cat = AccountingCategory.objects.create(
            code='LAB-NT', name='Labor-NT', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='Neg', last_name='Total', email='nt@test.com',
        )
        self.job = Job.objects.create(
            contact=self.contact,
            status=Job.STATUS_APPROVED,
            job_number='JOB-NT-0001',
        )
        self.invoice = Invoice.objects.create(
            job=self.job,
            status=Invoice.STATUS_DRAFT,
        )

    # ------------------------------------------------------------------
    # Tests on the helper directly.
    # ------------------------------------------------------------------

    def test_helper_raises_when_total_negative(self):
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1, qty=Decimal('1'), units='ea',
            description='Big credit', price=Decimal('-500.00'),
            accounting_category=self.cat,
        )
        with self.assertRaises(ValidationError) as ctx:
            InvoiceEmailService._assert_total_non_negative(self.invoice)
        self.assertIn('negative', str(ctx.exception).lower())

    def test_helper_does_not_raise_when_total_positive(self):
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1, qty=Decimal('1'), units='ea',
            description='Charge', price=Decimal('100.00'),
            accounting_category=self.cat,
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=2, qty=Decimal('1'), units='ea',
            description='Small credit', price=Decimal('-30.00'),
            accounting_category=self.cat,
        )
        InvoiceEmailService._assert_total_non_negative(self.invoice)

    def test_helper_does_not_raise_when_total_zero(self):
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1, qty=Decimal('1'), units='ea',
            description='Charge', price=Decimal('100.00'),
            accounting_category=self.cat,
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=2, qty=Decimal('1'), units='ea',
            description='Offsetting credit', price=Decimal('-100.00'),
            accounting_category=self.cat,
        )
        InvoiceEmailService._assert_total_non_negative(self.invoice)

    def test_helper_does_not_raise_when_no_lines(self):
        InvoiceEmailService._assert_total_non_negative(self.invoice)

    # ------------------------------------------------------------------
    # Integration test: send_invoice raises before any external call.
    # ------------------------------------------------------------------

    def test_send_invoice_raises_validation_error_before_external_calls(self):
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1, qty=Decimal('1'), units='ea',
            description='Big credit', price=Decimal('-500.00'),
            accounting_category=self.cat,
        )
        with self.assertRaises(ValidationError) as ctx:
            InvoiceEmailService.send_invoice(
                self.invoice,
                to='customer@example.com',
                subject='Test',
                body='Test body',
            )
        self.assertIn('negative', str(ctx.exception).lower())
