from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.invoicing.models import Invoice
from apps.invoicing.services import InvoiceService
from apps.jobs.models import Job


class DepositLineCreationTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence',
                                     value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.dep_cat = AccountingCategory.objects.create(
            code='DEP', name='Deposits', taxable=False, is_deposit=True)
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com',
            mobile_number='555')
        self.job = Job.objects.create(
            contact=contact, job_number='JOB-2026-0001',
            status=Job.STATUS_APPROVED)
        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT)
        Configuration.objects.create(
            key='default_deposit_accounting_category',
            value=str(self.dep_cat.pk))

    def test_deposit_flag_stamps_default_category(self):
        li = InvoiceService.add_line_item(
            self.invoice.pk, deposit=True,
            description='Deposit on JOB-2026-0001',
            qty='1', price='5000.00', units='none')
        self.assertEqual(li.accounting_category_id, self.dep_cat.pk)
        self.assertTrue(li.is_deposit_line)

    def test_unset_key_raises_coaching_error(self):
        Configuration.objects.filter(
            key='default_deposit_accounting_category').delete()
        with self.assertRaises(ValidationError) as ctx:
            InvoiceService.add_line_item(
                self.invoice.pk, deposit=True, description='Deposit',
                qty='1', price='100.00', units='none')
        self.assertIn('accounting_category', ctx.exception.message_dict)
        self.assertIn('default_deposit_accounting_category',
                      str(ctx.exception))

    def test_dangling_key_raises(self):
        Configuration.objects.filter(
            key='default_deposit_accounting_category').update(value='999999')
        with self.assertRaises(ValidationError):
            InvoiceService.add_line_item(
                self.invoice.pk, deposit=True, description='Deposit',
                qty='1', price='100.00', units='none')

    def test_manual_line_with_deposit_category_still_works(self):
        # Hand-assigning the deposit AC (no flag) is equally a deposit line.
        li = InvoiceService.add_line_item(
            self.invoice.pk, description='Deposit',
            qty='1', price='100.00', units='none',
            accounting_category=self.dep_cat.pk)
        self.assertTrue(li.is_deposit_line)
