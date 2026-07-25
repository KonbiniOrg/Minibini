from decimal import Decimal
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.invoicing.models import (
    Invoice, InvoiceLineItem, InvoiceLineItemSource,
)
from apps.jobs.models import Job


class DepositLineHelperTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence',
                                     value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.dep_cat = AccountingCategory.objects.create(
            code='DEP', name='Deposits', taxable=False, is_deposit=True)
        self.std_cat = AccountingCategory.objects.create(
            code='SVC', name='Service', taxable=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com',
            mobile_number='555')
        self.job = Job.objects.create(
            contact=self.contact, job_number='JOB-2026-0001',
            status=Job.STATUS_APPROVED)
        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT)

    def _line(self, cat, **kw):
        return InvoiceLineItem.objects.create(
            invoice=self.invoice, description='x', qty=Decimal('1'),
            price=Decimal('500.00'), accounting_category=cat, **kw)

    def test_deposit_line_property(self):
        li = self._line(self.dep_cat)
        self.assertTrue(li.is_deposit_line)
        self.assertFalse(li.is_deposit_deduction)

    def test_standard_line_is_not_deposit(self):
        li = self._line(self.std_cat)
        self.assertFalse(li.is_deposit_line)

    def test_deduction_is_not_a_deposit_line(self):
        dep = self._line(self.dep_cat)
        # Invoice.clean() enforces single-draft-per-job, so the deduction's
        # invoice lives on a second job.
        other_job = Job.objects.create(
            contact=self.contact, job_number='JOB-2026-0002',
            status=Job.STATUS_APPROVED)
        other = Invoice.objects.create(job=other_job,
                                       status=Invoice.STATUS_DRAFT)
        ded = InvoiceLineItem.objects.create(
            invoice=other, description='Less deposit', qty=Decimal('1'),
            price=Decimal('-500.00'), accounting_category=self.dep_cat)
        InvoiceLineItemSource.objects.create(
            invoice_line_item=ded,
            source_type=InvoiceLineItemSource.SOURCE_DEPOSIT,
            source_pk=dep.pk)
        self.assertTrue(ded.is_deposit_deduction)
        self.assertFalse(ded.is_deposit_line)
        self.assertEqual(
            ded.sources.get(
                source_type=InvoiceLineItemSource.SOURCE_DEPOSIT
            ).resolve(), dep)

    def test_unique_claim_on_deposit(self):
        dep = self._line(self.dep_cat)
        ded = self._line(self.std_cat)
        InvoiceLineItemSource.objects.create(
            invoice_line_item=ded,
            source_type=InvoiceLineItemSource.SOURCE_DEPOSIT,
            source_pk=dep.pk)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InvoiceLineItemSource.objects.create(
                    invoice_line_item=ded,
                    source_type=InvoiceLineItemSource.SOURCE_DEPOSIT,
                    source_pk=dep.pk)
