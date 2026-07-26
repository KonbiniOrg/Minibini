from decimal import Decimal
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.invoicing.models import (
    Invoice, InvoiceLineItem, InvoiceLineItemSource,
)
from apps.jobs.models import Job


class DepositSerializerTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence',
                                     value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.user = User.objects.create_user(username='fin', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials'))
        self.client = APIClient()
        self.client.login(username='fin', password='pw')
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
        self.deposit_inv = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT)
        self.dep_line = InvoiceLineItem.objects.create(
            invoice=self.deposit_inv, description='Deposit',
            qty=Decimal('1'), price=Decimal('5000.00'),
            accounting_category=self.dep_cat)

    def test_detail_exposes_line_and_invoice_flags(self):
        data = self.client.get(
            f'/api/invoices/{self.deposit_inv.pk}/').json()
        self.assertTrue(data['is_deposit'])
        line = next(l for l in data['line_items']
                    if l['line_item_id'] == self.dep_line.pk)
        self.assertTrue(line['is_deposit'])

    def test_summary_list_exposes_invoice_flag(self):
        # deposit_inv is STATUS_DRAFT; the summary endpoint's default status
        # filter is 'open' (STATUS_OPEN/STATUS_PARTLY_PAID only), so status=all
        # is required for a draft invoice to appear in the list at all.
        data = self.client.get('/api/invoices/?summary=true&status=all').json()
        rows = data['results'] if isinstance(data, dict) else data
        row = next(r for r in rows
                   if r['invoice_id'] == self.deposit_inv.pk)
        self.assertTrue(row['is_deposit'])

    def test_deduction_does_not_mark_invoice_as_deposit(self):
        # Single-draft-per-job guard (Invoice.clean): only one draft invoice
        # per job at a time is allowed, so promote deposit_inv out of draft
        # (via queryset.update to bypass clean/save) before a second draft
        # invoice for the same job can be created.
        Invoice.objects.filter(pk=self.deposit_inv.pk).update(
            status=Invoice.STATUS_PAID)
        other = Invoice.objects.create(job=self.job,
                                       status=Invoice.STATUS_DRAFT)
        ded = InvoiceLineItem.objects.create(
            invoice=other, description='Less deposit', qty=Decimal('1'),
            price=Decimal('-5000.00'), accounting_category=self.dep_cat)
        InvoiceLineItemSource.objects.create(
            invoice_line_item=ded,
            source_type=InvoiceLineItemSource.SOURCE_DEPOSIT,
            source_pk=self.dep_line.pk)
        data = self.client.get(f'/api/invoices/{other.pk}/').json()
        self.assertFalse(data['is_deposit'])
