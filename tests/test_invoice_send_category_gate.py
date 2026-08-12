"""
Tests for the send-gate precheck in InvoiceEmailService.

Task 3: Before any QBO/PDF/email work, send_invoice must raise
django.core.exceptions.ValidationError if any line item has
accounting_category_id is None.

The helper _assert_all_lines_categorized(invoice) is tested directly so
the positive-path test never reaches external calls (QBO/email).
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.core.models import User, Configuration, AppState, AccountingCategory
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.services import InvoiceEmailService


class InvoiceSendCategoryGateTest(TestCase):
    def setUp(self):
        # Invoice numbering configuration (required by Invoice.save()).
        Configuration.objects.create(
            key='invoice_number_sequence', value='INV-{year}-{counter:04d}',
        )
        AppState.objects.create(key='invoice_counter', value='0')

        self.cat = AccountingCategory.objects.create(
            code='LAB-CG', name='Labor-CG', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='Cat', last_name='Gate', email='cg@test.com',
        )
        self.job = Job.objects.create(
            contact=self.contact,
            status=Job.STATUS_APPROVED,
            job_number='JOB-CG-0001',
        )
        self.invoice = Invoice.objects.create(
            job=self.job,
            status=Invoice.STATUS_DRAFT,
        )

    # ------------------------------------------------------------------
    # Tests on the helper directly (avoids needing QBO/email for the
    # positive case).
    # ------------------------------------------------------------------

    def test_helper_raises_when_line_missing_category(self):
        """_assert_all_lines_categorized raises ValidationError if any line has no category."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            line_number=1,
            qty=Decimal('1'),
            units='ea',
            description='Uncategorized line',
            price=Decimal('50.00'),
            accounting_category=None,
        )
        with self.assertRaises(ValidationError) as ctx:
            InvoiceEmailService._assert_all_lines_categorized(self.invoice)
        msg = str(ctx.exception)
        self.assertIn('1', msg)
        self.assertIn('fallback_accounting_category', msg)

    def test_helper_names_multiple_offending_lines(self):
        """Error message includes all line numbers missing a category."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            line_number=1,
            qty=Decimal('1'),
            units='ea',
            description='Line one',
            price=Decimal('10.00'),
            accounting_category=self.cat,
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            line_number=2,
            qty=Decimal('1'),
            units='ea',
            description='Line two — no cat',
            price=Decimal('20.00'),
            accounting_category=None,
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            line_number=3,
            qty=Decimal('1'),
            units='ea',
            description='Line three — no cat',
            price=Decimal('30.00'),
            accounting_category=None,
        )
        with self.assertRaises(ValidationError) as ctx:
            InvoiceEmailService._assert_all_lines_categorized(self.invoice)
        msg = str(ctx.exception)
        self.assertIn('2', msg)
        self.assertIn('3', msg)

    def test_helper_does_not_raise_when_all_lines_categorized(self):
        """_assert_all_lines_categorized does not raise when every line has a category."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            line_number=1,
            qty=Decimal('1'),
            units='ea',
            description='Categorized line',
            price=Decimal('100.00'),
            accounting_category=self.cat,
        )
        # Should not raise.
        InvoiceEmailService._assert_all_lines_categorized(self.invoice)

    def test_helper_does_not_raise_when_no_lines(self):
        """_assert_all_lines_categorized does not raise for an invoice with no line items."""
        # An invoice with no lines trivially has no uncategorized lines.
        InvoiceEmailService._assert_all_lines_categorized(self.invoice)

    # ------------------------------------------------------------------
    # Integration test: send_invoice raises before any external call.
    # ------------------------------------------------------------------

    def test_send_invoice_raises_validation_error_before_external_calls(self):
        """send_invoice raises ValidationError (not reaching QBO/email) when a line lacks a category."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            line_number=1,
            qty=Decimal('1'),
            units='ea',
            description='No category here',
            price=Decimal('75.00'),
            accounting_category=None,
        )
        with self.assertRaises(ValidationError) as ctx:
            InvoiceEmailService.send_invoice(
                self.invoice,
                to='customer@example.com',
                subject='Test',
                body='Test body',
            )
        msg = str(ctx.exception)
        self.assertIn('accounting category', msg.lower())
        self.assertIn('1', msg)
        self.assertIn('fallback_accounting_category', msg)
