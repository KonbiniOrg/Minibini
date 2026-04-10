from django.db import IntegrityError
from django.test import TestCase
from decimal import Decimal
from django.utils import timezone

from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.jobs.models import Job, WorkOrder, Task, Blep
from apps.inventory.models import Material, PriceListItem
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration, AccountingCategory


class InvoiceLineItemSourceTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

        self.job = Job.objects.create(
            job_number='JOB-2026-0001',
            contact=self.contact,
            status=Job.STATUS_APPROVED,
        )
        self.workorder = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.workorder,
            name='Labor',
            rate=Decimal('25.00'),
            accounting_category=self.category,
        )
        self.blep = Blep.objects.create(
            task=self.task,
            start_time=timezone.now(),
            end_time=timezone.now(),
        )

        self.invoice = Invoice.objects.create(job=self.job)
        self.line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Test',
            qty=Decimal('1'),
            price=Decimal('100.00'),
            accounting_category=self.category,
        )

    def test_source_links_line_item_to_blep(self):
        source = InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep.pk,
        )
        self.assertEqual(source.invoice_line_item, self.line_item)
        self.assertEqual(source.source_pk, self.blep.pk)

    def test_resolve_returns_blep_instance(self):
        source = InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep.pk,
        )
        resolved = source.resolve()
        self.assertEqual(resolved, self.blep)

    def test_unique_atom_constraint_prevents_double_claim(self):
        InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep.pk,
        )
        other_line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Other',
            qty=Decimal('1'),
            price=Decimal('50.00'),
            accounting_category=self.category,
        )
        with self.assertRaises(IntegrityError):
            InvoiceLineItemSource.objects.create(
                invoice_line_item=other_line_item,
                source_type=InvoiceLineItemSource.SOURCE_BLEP,
                source_pk=self.blep.pk,
            )

    def test_deleting_line_item_cascades_to_sources(self):
        source = InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep.pk,
        )
        self.line_item.delete()
        self.assertFalse(
            InvoiceLineItemSource.objects.filter(pk=source.pk).exists()
        )
