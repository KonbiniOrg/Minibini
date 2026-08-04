"""
Tests for the send-gate precheck in InvoiceEmailService.

Task 3: Before any QBO/PDF/email work, send_invoice must raise
django.core.exceptions.ValidationError if any line item has
accounting_category_id is None.

The helper _assert_all_lines_categorized(invoice) is tested directly so
the positive-path test never reaches external calls (QBO/email).

Task 5 (task-owned-money Phase 3) reconciliation note: invoice compose now
stamps the configured fallback_accounting_category onto any composed line
whose null category traces back to a source atom with no AC of its own
(see tests/test_invoice_compose_fallback_ac.py). That does NOT make this
gate obsolete — bundling two atoms that carry two DIFFERENT real
categories into one line still legitimately resolves to a null category
(no atom is null, so the fallback hook is never consulted — the "pick
manually" case, see
AddAtomsToNewLineItemFallbackTest.test_bundle_two_different_real_categories_stays_none
in test_invoice_compose_fallback_ac.py). Manually-added freeform lines
added directly against the API (bypassing the frontend's client-side
"Accounting Category is required" check) are a second live path. So this
gate remains necessary, reachable through ordinary (non-corrupted) usage
— see InvoiceSendGateAmbiguousBundleTest below — not merely a backstop for
a surgically-corrupted DB row (that backstop is
apps.qbo.services.QBOInvoiceSyncService._build_qbo_invoice's own guard,
see tests/test_qbo_invoice_push.py::NullCategoryDefensiveGuardTest).
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.core.models import User, Configuration, AppState, AccountingCategory
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.jobs.models import RateScheme, Task
from apps.inventory.models import Material
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.services import InvoiceEmailService, InvoiceWizardService


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
        self.assertIn('1', str(ctx.exception))

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
        self.assertIn('accounting category', str(ctx.exception).lower())
        self.assertIn('1', str(ctx.exception))


class InvoiceSendGateAmbiguousBundleTest(TestCase):
    """Task 5 reconciliation: the gate is still reachable through ordinary
    (non-corrupted) usage even with compose-time fallback stamping (Task
    3) in place — bundling two atoms that each carry a different REAL
    accounting category onto one line resolves to a null category with no
    null atom involved, so the fallback hook is never consulted (the
    pre-existing "pick manually" behavior — see
    test_invoice_compose_fallback_ac.py::AddAtomsToNewLineItemFallbackTest.
    test_bundle_two_different_real_categories_stays_none). No fallback
    is configured here at all, proving this path doesn't depend on it."""

    def setUp(self):
        Configuration.objects.create(
            key='invoice_number_sequence', value='INV-{year}-{counter:04d}',
        )
        AppState.objects.create(key='invoice_counter', value='0')
        self.cat_labor = AccountingCategory.objects.create(
            code='LBR-AMB', name='Labor-AMB',
        )
        self.cat_materials = AccountingCategory.objects.create(
            code='MAT-AMB', name='Materials-AMB',
        )
        self.contact = Contact.objects.create(
            first_name='Amb', last_name='Iguous', email='amb@test.com',
        )
        self.job = Job.objects.create(
            contact=self.contact,
            status=Job.STATUS_APPROVED,
            job_number='JOB-AMB-0001',
        )
        self.invoice = Invoice.objects.create(
            job=self.job,
            status=Invoice.STATUS_DRAFT,
        )
        self.task = Task(
            job=self.job, name='Labor',
            qty_source=Task.QTY_ENTERED, rate=Decimal('25.00'),
            unit_label='hour', actual_qty=Decimal('1.00'),
            accounting_category=self.cat_labor,
        )
        self.task.save()
        self.task.status = Task.STATUS_COMPLETE
        self.task.save()
        self.material = Material.objects.create(
            job=self.job, description='Plywood',
            quantity=Decimal('1.00'), sell_price=Decimal('25.00'),
            accounting_category=self.cat_materials,
        )
        self.material.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        self.material.save(update_fields=['consumption_state'])

    def test_ambiguous_bundle_line_trips_the_gate(self):
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice,
            [{'type': 'task', 'id': self.task.pk},
             {'type': 'material', 'id': self.material.pk}],
        )
        self.assertIsNone(line_item.accounting_category_id)
        with self.assertRaises(ValidationError) as ctx:
            InvoiceEmailService._assert_all_lines_categorized(self.invoice)
        self.assertIn(str(line_item.line_number), str(ctx.exception))
