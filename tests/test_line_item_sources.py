"""
Task 1.2: EstimateLineItemSource and InvoiceLineItemSource resolve
Task / Material / Fee atoms.

Asserts:
  - EstimateLineItemSource.resolve() for source_type in {'task', 'material', 'fee'}
  - InvoiceLineItemSource.resolve() for source_type == 'fee'
  - unique_together still blocks a second claim of the same (source_type, source_pk)
"""
from decimal import Decimal
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource
from apps.inventory.models import InventoryItem, Material
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.jobs.models import Fee, Job, RateScheme, Task


class EstimateLineItemSourceAtomTest(TestCase):
    """EstimateLineItemSource resolves Task, Material, and Fee atoms."""

    def setUp(self):
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        AppState.objects.create(key='estimate_counter', value='0')

        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Ann', last_name='Test',
            email='ann@example.com', mobile_number='555-0100',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('90'), unit_label='hour', accounting_category=self.cat,
        )
        self.task = Task(
            job=self.job, name='Weld',
        )
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()
        inv_item = InventoryItem.objects.create(
            code='STL-001', description='Steel bar',
            purchase_price=Decimal('10'), selling_price=Decimal('20'),
            accounting_category=self.cat,
        )
        self.material = Material.objects.create(
            job=self.job, task=self.task,
            quantity=Decimal('5'), sell_price=Decimal('20'),
            inventory_item=inv_item,
        )
        self.fee = Fee.objects.create(
            job=self.job, description='Setup charge',
            quantity=Decimal('1'), unit_rate=Decimal('150'),
            accounting_category=self.cat,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, status=Estimate.STATUS_DRAFT,
            estimate_number='EST-2026-0001',
        )
        self.line_item = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('90'), description='', accounting_category=self.cat,
        )

    # ------------------------------------------------------------------
    # resolve() tests
    # ------------------------------------------------------------------

    def test_resolve_returns_task(self):
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        self.assertEqual(src.resolve(), self.task)

    def test_resolve_returns_material(self):
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=self.material.pk,
        )
        self.assertEqual(src.resolve(), self.material)

    def test_resolve_returns_fee(self):
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_FEE,
            source_pk=self.fee.pk,
        )
        self.assertEqual(src.resolve(), self.fee)

    # ------------------------------------------------------------------
    # unique_together still enforces whole-atom claim
    # ------------------------------------------------------------------

    def test_double_claim_task_raises_integrity_error(self):
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        other_li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('1'), description='', accounting_category=self.cat,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EstimateLineItemSource.objects.create(
                    estimate_line_item=other_li,
                    source_type=EstimateLineItemSource.SOURCE_TASK,
                    source_pk=self.task.pk,
                )

    def test_double_claim_fee_raises_integrity_error(self):
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_FEE,
            source_pk=self.fee.pk,
        )
        other_li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('1'), description='', accounting_category=self.cat,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EstimateLineItemSource.objects.create(
                    estimate_line_item=other_li,
                    source_type=EstimateLineItemSource.SOURCE_FEE,
                    source_pk=self.fee.pk,
                )


class InvoiceLineItemSourceFeeTest(TestCase):
    """InvoiceLineItemSource resolves Fee atoms."""

    def setUp(self):
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')

        self.cat = AccountingCategory.objects.create(name='Services', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Bob', last_name='Test',
            email='bob@example.com', mobile_number='555-0200',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001',
        )
        self.fee = Fee.objects.create(
            job=self.job, description='Rush fee',
            quantity=Decimal('1'), unit_rate=Decimal('200'),
            accounting_category=self.cat,
        )
        self.invoice = Invoice.objects.create(job=self.job)
        self.line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Rush',
            qty=Decimal('1'),
            price=Decimal('200'),
            accounting_category=self.cat,
        )

    def test_resolve_returns_fee(self):
        src = InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_FEE,
            source_pk=self.fee.pk,
        )
        self.assertEqual(src.resolve(), self.fee)

    def test_double_claim_fee_raises_integrity_error(self):
        InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_FEE,
            source_pk=self.fee.pk,
        )
        other_li = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Other',
            qty=Decimal('1'),
            price=Decimal('1'),
            accounting_category=self.cat,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InvoiceLineItemSource.objects.create(
                    invoice_line_item=other_li,
                    source_type=InvoiceLineItemSource.SOURCE_FEE,
                    source_pk=self.fee.pk,
                )
