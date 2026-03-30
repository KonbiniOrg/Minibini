from decimal import Decimal
from django.test import TestCase
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.services import InvoiceGroupingService
from apps.core.models import AccountingCategory, Configuration
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business


class InvoiceGroupingTest(TestCase):
    """Test grouping invoice line items by category + taxability."""

    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.cat_cnc = AccountingCategory.objects.create(
            code='CNC', name='CNC Machining', taxable=True,
            qbo_item_id='100',
        )
        self.cat_design = AccountingCategory.objects.create(
            code='DSN', name='Design Services', taxable=False,
            qbo_item_id='200',
        )
        self.cat_storage = AccountingCategory.objects.create(
            code='STR', name='Storage', taxable=True,
            qbo_item_id='300',
        )

        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme Corp', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(contact=self.contact, job_number='JOB-2026-0001')
        self.invoice = Invoice.objects.create(job=self.job)

    def test_single_category_single_line(self):
        """One category produces one grouped line."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=2, price=100,
            description='CNC part A', accounting_category=self.cat_cnc,
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=3, price=50,
            description='CNC part B', accounting_category=self.cat_cnc,
        )
        groups = InvoiceGroupingService.group_for_qbo(self.invoice)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['amount'], Decimal('350.00'))
        self.assertTrue(groups[0]['taxable'])
        self.assertEqual(groups[0]['qbo_item_id'], '100')

    def test_mixed_categories(self):
        """Different categories produce separate grouped lines."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=1, price=200,
            description='CNC work', accounting_category=self.cat_cnc,
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=1, price=500,
            description='Design', accounting_category=self.cat_design,
        )
        groups = InvoiceGroupingService.group_for_qbo(self.invoice)
        self.assertEqual(len(groups), 2)
        names = {g['category_name'] for g in groups}
        self.assertIn('CNC Machining', names)
        self.assertIn('Design Services', names)

    def test_taxable_override_creates_separate_group(self):
        """Line with taxable_override=False groups separately from taxable default."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=1, price=100,
            accounting_category=self.cat_cnc,
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=1, price=200,
            accounting_category=self.cat_cnc,
            taxable_override=False,
        )
        groups = InvoiceGroupingService.group_for_qbo(self.invoice)
        self.assertEqual(len(groups), 2)
        taxable_group = [g for g in groups if g['taxable']][0]
        nontaxable_group = [g for g in groups if not g['taxable']][0]
        self.assertEqual(taxable_group['amount'], Decimal('100.00'))
        self.assertEqual(nontaxable_group['amount'], Decimal('200.00'))

    def test_group_includes_job_number(self):
        """Each grouped line description includes the job number."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=1, price=100,
            accounting_category=self.cat_cnc,
        )
        groups = InvoiceGroupingService.group_for_qbo(self.invoice)
        self.assertIn(self.job.job_number, groups[0]['description'])

    def test_no_category_groups_as_uncategorized(self):
        """Line items without accounting_category group as 'Uncategorized'."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=1, price=100,
            description='Misc charge',
        )
        groups = InvoiceGroupingService.group_for_qbo(self.invoice)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['category_name'], 'Uncategorized')
        self.assertFalse(groups[0]['taxable'])
