from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.invoicing.models import (
    Invoice, InvoiceLineItem, InvoiceLineItemSource,
)
from apps.invoicing.services import InvoiceService, InvoiceWizardService
from apps.jobs.models import Job


def _deposit_group(pool):
    return next((g for g in pool['tasks'] if g['name'] == 'Deposit credits'), None)


class DepositCreditPoolTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence',
                                     value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.dep_cat = AccountingCategory.objects.create(
            code='DEP', name='Deposits', taxable=False, is_deposit=True)
        self.std_cat = AccountingCategory.objects.create(
            code='SVC', name='Service', taxable=True)
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com',
            mobile_number='555')
        self.job = Job.objects.create(
            contact=contact, job_number='JOB-2026-0001',
            status=Job.STATUS_APPROVED)
        # Paid deposit invoice with one deposit line.
        self.dep_invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_OPEN,
            invoice_number='INV-1042')
        self.dep_line = InvoiceLineItem.objects.create(
            invoice=self.dep_invoice, description='Deposit',
            qty=Decimal('1'), price=Decimal('5000.00'),
            accounting_category=self.dep_cat)
        Invoice.objects.filter(pk=self.dep_invoice.pk).update(
            status=Invoice.STATUS_PAID)
        self.dep_invoice.refresh_from_db()
        # The draft being composed.
        self.draft = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT)

    def test_paid_deposit_appears_as_available_credit(self):
        pool = InvoiceWizardService.get_source_pool(self.draft)
        group = _deposit_group(pool)
        self.assertIsNotNone(group)
        atom = group['atoms'][0]
        self.assertEqual(atom['type'], 'deposit')
        self.assertEqual(atom['id'], self.dep_line.pk)
        self.assertEqual(atom['state'], 'available')
        self.assertEqual(Decimal(str(atom['amount'])),
                         Decimal('-5000.00'))

    def test_unpaid_deposit_not_offered(self):
        Invoice.objects.filter(pk=self.dep_invoice.pk).update(
            status=Invoice.STATUS_OPEN)
        pool = InvoiceWizardService.get_source_pool(self.draft)
        self.assertIsNone(_deposit_group(pool))

    def test_other_jobs_deposits_not_offered(self):
        contact2 = Contact.objects.create(
            first_name='K', last_name='E', email='k@e.com',
            mobile_number='556')
        job2 = Job.objects.create(
            contact=contact2, job_number='JOB-2026-0002',
            status=Job.STATUS_APPROVED)
        draft2 = Invoice.objects.create(job=job2,
                                        status=Invoice.STATUS_DRAFT)
        pool = InvoiceWizardService.get_source_pool(draft2)
        self.assertIsNone(_deposit_group(pool))

    def test_pull_creates_locked_negative_deduction(self):
        li = InvoiceWizardService.add_atoms_to_new_line_item(
            self.draft, [{'type': 'deposit', 'id': self.dep_line.pk}])
        self.assertEqual(li.qty, Decimal('1'))
        self.assertEqual(li.price, Decimal('-5000.00'))
        self.assertEqual(li.accounting_category_id, self.dep_cat.pk)
        self.assertIn('INV-1042', li.description)
        self.assertTrue(li.is_deposit_deduction)
        # And it is claimed in the pool now.
        pool = InvoiceWizardService.get_source_pool(self.draft)
        atom = _deposit_group(pool)['atoms'][0]
        self.assertEqual(atom['state'], 'claimed_by_current')

    def test_claimed_deposit_shows_claimed_by_other(self):
        InvoiceWizardService.add_atoms_to_new_line_item(
            self.draft, [{'type': 'deposit', 'id': self.dep_line.pk}])
        Invoice.objects.filter(pk=self.draft.pk).update(
            status=Invoice.STATUS_OPEN)
        draft2 = Invoice.objects.create(job=self.job,
                                        status=Invoice.STATUS_DRAFT)
        pool = InvoiceWizardService.get_source_pool(draft2)
        atom = _deposit_group(pool)['atoms'][0]
        self.assertEqual(atom['state'], 'claimed_by_other')

    def test_deleting_deduction_releases_claim(self):
        li = InvoiceWizardService.add_atoms_to_new_line_item(
            self.draft, [{'type': 'deposit', 'id': self.dep_line.pk}])
        InvoiceService.delete_line_item(li.pk)
        pool = InvoiceWizardService.get_source_pool(self.draft)
        self.assertEqual(_deposit_group(pool)['atoms'][0]['state'],
                         'available')

    def test_deposit_atom_cannot_be_bundled(self):
        with self.assertRaises(ValidationError):
            InvoiceWizardService.add_atoms_to_new_line_item(
                self.draft, [
                    {'type': 'deposit', 'id': self.dep_line.pk},
                    {'type': 'deposit', 'id': self.dep_line.pk},
                ])

    def test_deduction_amount_is_locked(self):
        li = InvoiceWizardService.add_atoms_to_new_line_item(
            self.draft, [{'type': 'deposit', 'id': self.dep_line.pk}])
        with self.assertRaises(ValidationError):
            InvoiceService.update_line_item(li.pk, price='-1.00')
        with self.assertRaises(ValidationError):
            InvoiceService.update_line_item(li.pk, qty='2')
        updated = InvoiceService.update_line_item(
            li.pk, description='Less deposit (thanks!)')
        self.assertEqual(updated.description, 'Less deposit (thanks!)')

    def test_deposit_lines_of_current_draft_not_offered(self):
        # A deposit line on the draft being composed is not a credit.
        InvoiceLineItem.objects.create(
            invoice=self.draft, description='Deposit', qty=Decimal('1'),
            price=Decimal('100.00'), accounting_category=self.dep_cat)
        pool = InvoiceWizardService.get_source_pool(self.draft)
        group = _deposit_group(pool)
        ids = [a['id'] for a in (group['atoms'] if group else [])]
        self.assertNotIn(
            self.draft.invoicelineitem_set.get(price=Decimal('100.00')).pk,
            ids)
