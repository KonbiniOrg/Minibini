from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from decimal import Decimal

from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.jobs.models import Job, Task, RateScheme
from apps.inventory.models import Material, InventoryItem
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration, AccountingCategory, AppState


class InvoiceLineItemSourceTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})

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
        self.scheme = RateScheme.objects.create(
            name='S-ilis', algorithm=RateScheme.ENTERED_QTY,
            rate=1, unit_label='ea', accounting_category=self.category,
        )
        self.task = Task.objects.create(
            job=self.job,
            name='Labor',
            rate_scheme=self.scheme,
        )

        self.invoice = Invoice.objects.create(job=self.job)
        self.line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Test',
            qty=Decimal('1'),
            price=Decimal('100.00'),
            accounting_category=self.category,
        )

    def test_source_links_line_item_to_task(self):
        source = InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        self.assertEqual(source.invoice_line_item, self.line_item)
        self.assertEqual(source.source_pk, self.task.pk)

    def test_resolve_returns_task_instance(self):
        source = InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        resolved = source.resolve()
        self.assertEqual(resolved, self.task)

    def test_resolve_returns_material_instance(self):
        pli = InventoryItem.objects.create(
            code='MAT-001',
            description='Test Material',
            purchase_price=Decimal('5.00'),
            selling_price=Decimal('10.00'),
            accounting_category=self.category,
        )
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            quantity=Decimal('3.00'),
            sell_price=Decimal('10.00'),
            inventory_item=pli,
        )
        source = InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_MATERIAL,
            source_pk=material.pk,
        )
        resolved = source.resolve()
        self.assertEqual(resolved, material)

    def test_unique_atom_constraint_prevents_double_claim(self):
        InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
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
                source_type=InvoiceLineItemSource.SOURCE_TASK,
                source_pk=self.task.pk,
            )

    def test_deleting_line_item_cascades_to_sources(self):
        source = InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        self.line_item.delete()
        self.assertFalse(
            InvoiceLineItemSource.objects.filter(pk=source.pk).exists()
        )


class UniqueDraftInvoicePerJobTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001')

    def test_second_draft_for_same_job_raises(self):
        Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        with self.assertRaises(ValidationError):
            Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_multiple_non_draft_invoices_allowed(self):
        # Two open invoices for the same job is fine
        Invoice.objects.create(job=self.job, status=Invoice.STATUS_OPEN)
        Invoice.objects.create(job=self.job, status=Invoice.STATUS_OPEN)
        self.assertEqual(
            Invoice.objects.filter(job=self.job, status=Invoice.STATUS_OPEN).count(),
            2,
        )

    def test_draft_plus_non_draft_allowed(self):
        Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        Invoice.objects.create(job=self.job, status=Invoice.STATUS_OPEN)
        self.assertEqual(Invoice.objects.filter(job=self.job).count(), 2)

    def test_new_draft_allowed_after_old_draft_moves_to_open(self):
        # Create first draft, add a line item so we can transition it
        inv1 = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        category = AccountingCategory.objects.create(name='Labor', is_active=True)
        InvoiceLineItem.objects.create(
            invoice=inv1,
            description='x',
            qty=Decimal('1'),
            price=Decimal('1'),
            accounting_category=category,
        )
        # Move the first draft to open
        inv1.status = Invoice.STATUS_OPEN
        inv1.save()
        # A new draft for the same job should succeed
        inv2 = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        self.assertEqual(
            Invoice.objects.filter(job=self.job, status=Invoice.STATUS_DRAFT).count(),
            1,
        )
        self.assertEqual(
            Invoice.objects.filter(job=self.job, status=Invoice.STATUS_OPEN).count(),
            1,
        )
