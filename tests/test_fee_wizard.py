"""Tests: Fee atoms appear in the invoice wizard source pool as always-billable."""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.core.models import AccountingCategory, AppState, Configuration
from apps.contacts.models import Contact
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.invoicing.services import InvoiceWizardService
from apps.jobs.models import Fee, Job


class FeeWizardSourcePoolTest(TestCase):
    def setUp(self):
        Configuration.objects.create(
            key='invoice_number_sequence', value='INV-{year}-{counter:04d}'
        )
        AppState.objects.create(key='invoice_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='Neal', last_name='Test', email='n@example.com'
        )
        self.cat = AccountingCategory.objects.create(name='Services', code='SVC')
        self.job = Job.objects.create(
            contact=self.contact,
            status=Job.STATUS_APPROVED,
            job_number='JOB-FW-01',
        )
        # quantity=15, unit_rate=10 → compute_amount() = 150.00
        self.fee = Fee.objects.create(
            job=self.job,
            description='Delivery charge',
            quantity=Decimal('15'),
            unit_rate=Decimal('10.00'),
            accounting_category=self.cat,
        )
        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT
        )

    def _fee_group(self, pool):
        return next((g for g in pool['tasks'] if g['name'] == 'Fees'), None)

    def test_fee_group_appears_in_source_pool(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        grp = self._fee_group(pool)
        self.assertIsNotNone(grp, 'Expected a "Fees" group in source pool')

    def test_fee_atom_is_available(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        grp = self._fee_group(pool)
        self.assertEqual(len(grp['atoms']), 1)
        atom = grp['atoms'][0]
        self.assertEqual(atom['type'], 'fee')
        self.assertEqual(atom['id'], self.fee.pk)
        self.assertEqual(atom['state'], 'available')

    def test_fee_atom_amount_is_150(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        grp = self._fee_group(pool)
        atom = grp['atoms'][0]
        self.assertEqual(atom['amount'], Decimal('150.00'))

    def test_fee_atom_detail_qty_rate_units(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        grp = self._fee_group(pool)
        atom = grp['atoms'][0]
        self.assertEqual(atom['qty'], Decimal('15'))
        self.assertEqual(atom['rate'], Decimal('10.00'))
        self.assertEqual(atom['units'], 'none')

    def test_assert_atom_billable_does_not_raise(self):
        # Fees have no completion gate — _assert_atom_billable must never raise.
        try:
            InvoiceWizardService._assert_atom_billable(self.fee)
        except ValidationError:
            self.fail('_assert_atom_billable raised ValidationError for a Fee')

    def test_fee_atom_not_billable_reason_is_none(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        grp = self._fee_group(pool)
        atom = grp['atoms'][0]
        self.assertIsNone(atom['not_billable_reason'])


class FeeWizardClaimTest(TestCase):
    """Fee atoms follow the same claim rules as other atoms (exclusive, whole-atom)."""

    def setUp(self):
        Configuration.objects.create(
            key='invoice_number_sequence', value='INV-{year}-{counter:04d}'
        )
        AppState.objects.create(key='invoice_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='B', last_name='T', email='b@example.com'
        )
        self.cat = AccountingCategory.objects.create(name='Svc', code='SVC2')
        self.job = Job.objects.create(
            contact=self.contact,
            status=Job.STATUS_APPROVED,
            job_number='JOB-FW-02',
        )
        self.fee = Fee.objects.create(
            job=self.job,
            description='Setup fee',
            quantity=Decimal('1'),
            unit_rate=Decimal('150.00'),
            accounting_category=self.cat,
        )
        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT
        )

    def _fee_group(self, pool):
        return next((g for g in pool['tasks'] if g['name'] == 'Fees'), None)

    def test_add_fee_atom_creates_line_item(self):
        atoms = [{'type': 'fee', 'id': self.fee.pk}]
        li = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(li.qty, Decimal('1'))
        self.assertEqual(li.price, Decimal('150.00'))
        self.assertEqual(li.units, 'none')
        self.assertTrue(
            InvoiceLineItemSource.objects.filter(
                source_type=InvoiceLineItemSource.SOURCE_FEE,
                source_pk=self.fee.pk,
            ).exists()
        )

    def test_claimed_fee_shows_claimed_by_current(self):
        InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'fee', 'id': self.fee.pk}]
        )
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        atom = self._fee_group(pool)['atoms'][0]
        self.assertEqual(atom['state'], 'claimed_by_current')

    def test_fee_billed_on_other_invoice_shows_claimed_by_other(self):
        other_invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_OPEN
        )
        other_li = InvoiceLineItem.objects.create(
            invoice=other_invoice,
            description='Fee',
            qty=Decimal('1'),
            price=Decimal('150.00'),
            accounting_category=self.cat,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=other_li,
            source_type=InvoiceLineItemSource.SOURCE_FEE,
            source_pk=self.fee.pk,
        )
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        atom = self._fee_group(pool)['atoms'][0]
        self.assertEqual(atom['state'], 'claimed_by_other')
        self.assertEqual(atom['claiming_invoice_id'], other_invoice.pk)
