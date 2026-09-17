"""
Tests for the comment line item ("is_comment"): a purely informational row —
no charge, no atom linkage — available on any BaseLineItem subclass
(EstimateLineItem, ChangeOrderLineItem, InvoiceLineItem, PurchaseOrderLineItem).

Covers:
- BaseLineItem.clean() invariants (qty/price forced to zero, mutually
  exclusive with inventory_item/task/adjustment_service/is_material/service_item)
- Estimate/ChangeOrder add_line_item + update_line_item exempt comment lines
  from the accounting-category-required rule
- EstimateAcceptanceService.on_accept / ChangeOrderAcceptanceService.on_accept
  never crystallize a comment line into a Task/Material/Fee
- InvoiceEmailService._assert_all_lines_categorized exempts comment lines
- QBOInvoiceSyncService._build_qbo_invoice never pushes a comment line
- PurchaseOrderService.add_line_item accepts a comment line with no category
"""
from decimal import Decimal
from unittest.mock import MagicMock

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase

from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.estimates.acceptance import EstimateAcceptanceService
from apps.estimates.co_acceptance import ChangeOrderAcceptanceService
from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItem, Estimate, EstimateLineItem,
    EstimateLineItemSource,
)
from apps.estimates.services import EstimateService
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.services import InvoiceEmailService
from apps.jobs.models import Fee, Job, RateScheme, Task
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService
from apps.qbo.services import QBOInvoiceSyncService


class CommentLineValidationTest(TestCase):
    """BaseLineItem.clean() enforces that a comment line carries no charge and
    no other line-item semantics, on every subclass that has the relevant field."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(code='GEN', name='General', taxable=True)
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com', mobile_number='555-0100',
        )
        self.job = Job.objects.create(job_number='JOB-CMT-0001', contact=self.contact)
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-CMT-0001', status=Estimate.STATUS_DRAFT,
        )

    def test_comment_line_with_zero_qty_and_price_is_valid(self):
        li = EstimateLineItem(
            estimate=self.estimate, description='See attached spec sheet',
            is_comment=True, qty=Decimal('0'), price=Decimal('0'),
        )
        li.full_clean()  # should not raise

    def test_comment_line_rejects_nonzero_qty(self):
        li = EstimateLineItem(
            estimate=self.estimate, description='Note', is_comment=True,
            qty=Decimal('1'), price=Decimal('0'),
        )
        with self.assertRaises(DjangoValidationError) as ctx:
            li.full_clean()
        self.assertIn('qty', ctx.exception.message_dict)

    def test_comment_line_rejects_nonzero_price(self):
        li = EstimateLineItem(
            estimate=self.estimate, description='Note', is_comment=True,
            qty=Decimal('0'), price=Decimal('5.00'),
        )
        with self.assertRaises(DjangoValidationError) as ctx:
            li.full_clean()
        self.assertIn('price', ctx.exception.message_dict)

    def test_comment_line_rejects_inventory_item(self):
        from apps.inventory.models import InventoryItem
        pli = InventoryItem.objects.create(code='X1', accounting_category=self.cat)
        li = EstimateLineItem(
            estimate=self.estimate, description='Note', is_comment=True,
            qty=Decimal('0'), price=Decimal('0'), inventory_item=pli,
        )
        with self.assertRaises(DjangoValidationError) as ctx:
            li.full_clean()
        self.assertIn('inventory_item', ctx.exception.message_dict)

    def test_comment_line_rejects_is_material(self):
        li = EstimateLineItem(
            estimate=self.estimate, description='Note', is_comment=True,
            qty=Decimal('0'), price=Decimal('0'), is_material=True,
        )
        with self.assertRaises(DjangoValidationError) as ctx:
            li.full_clean()
        self.assertIn('is_material', ctx.exception.message_dict)

    def test_comment_line_rejects_adjustment_service(self):
        scheme = RateScheme.objects.create(
            name='Rush', algorithm=RateScheme.PERCENTAGE, rate=Decimal('10'),
            unit_label='none', accounting_category=self.cat,
        )
        li = EstimateLineItem(
            estimate=self.estimate, description='Note', is_comment=True,
            qty=Decimal('0'), price=Decimal('0'), adjustment_service=scheme,
        )
        with self.assertRaises(DjangoValidationError) as ctx:
            li.full_clean()
        self.assertIn('adjustment_service', ctx.exception.message_dict)

    def test_comment_line_does_not_require_accounting_category(self):
        li = EstimateLineItem(
            estimate=self.estimate, description='Note', is_comment=True,
            qty=Decimal('0'), price=Decimal('0'),
        )
        li.full_clean()  # no accounting_category set — should not raise

    def test_po_comment_line_rejects_task(self):
        business = Business.objects.create(
            business_name='Acme', default_contact=self.contact, our_reference_code='ACM-01',
        )
        self.contact.business = business
        self.contact.save()
        po = PurchaseOrder.objects.create(
            business=business, contact=self.contact, po_number='PO-CMT-0001',
            status=PurchaseOrder.STATUS_DRAFT,
        )
        scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME, rate=Decimal('50'),
            unit_label='hour', accounting_category=self.cat,
        )
        task = Task.objects.create(job=self.job, name='Setup', rate_scheme=scheme, est_qty=Decimal('1'))
        li = PurchaseOrderLineItem(
            purchase_order=po, description='Note', is_comment=True,
            qty=Decimal('0'), price=Decimal('0'), task=task,
        )
        with self.assertRaises(DjangoValidationError) as ctx:
            li.full_clean()
        self.assertIn('task', ctx.exception.message_dict)


class EstimateCommentLineAddUpdateTest(TestCase):
    """EstimateService.add_line_item / update_line_item exempt is_comment
    lines from the hand-line accounting-category-required rule."""

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})

        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com', mobile_number='555-0100',
        )
        self.job = Job.objects.create(job_number='JOB-CMT-0002', contact=self.contact)
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-CMT-0002', status=Estimate.STATUS_DRAFT,
        )

    def test_add_comment_line_without_accounting_category_succeeds(self):
        li = EstimateService.add_line_item(
            self.estimate.pk, description='See attached spec sheet', is_comment=True,
        )
        self.assertTrue(li.is_comment)
        self.assertIsNone(li.accounting_category_id)
        self.assertEqual(li.qty, Decimal('0.00'))
        self.assertEqual(li.price, Decimal('0.00'))

    def test_add_non_comment_line_without_accounting_category_still_fails(self):
        with self.assertRaises(DjangoValidationError):
            EstimateService.add_line_item(self.estimate.pk, description='Bare hand-line')

    def test_update_line_item_to_comment_without_category_succeeds(self):
        cat = AccountingCategory.objects.create(code='LAB', name='Labor', taxable=True)
        li = EstimateService.add_line_item(
            self.estimate.pk, description='Priced item', price=Decimal('10.00'),
            accounting_category=cat.pk,
        )
        updated = EstimateService.update_line_item(
            li.pk, is_comment=True, price=Decimal('0.00'), qty=Decimal('0.00'),
            accounting_category=None,
        )
        self.assertTrue(updated.is_comment)


class EstimateAcceptanceSkipsCommentLinesTest(TestCase):
    """Acceptance must never crystallize a comment line into a Fee/Task/Material."""

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})

        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB2')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='jd2@d.com', mobile_number='555-1',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0002',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0002', status=Estimate.STATUS_OPEN,
        )
        self.hand_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Rush handling',
            qty=Decimal('3'), price=Decimal('25.00'), accounting_category=self.cat,
        )
        self.comment_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='Please see attached drawing',
            is_comment=True, qty=Decimal('0'), price=Decimal('0'),
        )

    def test_comment_line_produces_no_fee_task_or_material(self):
        EstimateAcceptanceService.on_accept(self.estimate)
        self.assertFalse(
            Fee.objects.filter(job=self.job, description='Please see attached drawing').exists()
        )
        self.assertFalse(
            Task.objects.filter(job=self.job, name='Please see attached drawing').exists()
        )

    def test_comment_line_gets_no_source_row(self):
        EstimateAcceptanceService.on_accept(self.estimate)
        self.assertFalse(EstimateLineItemSource.objects.filter(estimate_line_item=self.comment_line).exists())

    def test_only_hand_line_counted_in_fees_created(self):
        result = EstimateAcceptanceService.on_accept(self.estimate)
        self.assertEqual(result['fees_created'], 1)
        self.assertEqual(Fee.objects.filter(job=self.job).count(), 1)


class ChangeOrderCommentLineAcceptanceTest(TestCase):
    """CO acceptance never crystallizes a comment add/replace line; a comment
    replace still retires the old atom (mirrors co_acceptance.py semantics)."""

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})

        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB3')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='jd3@d.com', mobile_number='555-2',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0003',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0003', status=Estimate.STATUS_ACCEPTED,
        )
        self.hand_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Rush handling',
            qty=Decimal('3'), price=Decimal('25.00'), accounting_category=self.cat,
        )
        self.fee = Fee.objects.create(
            job=self.job, description='Rush handling', quantity=Decimal('3'),
            unit_rate=Decimal('25.00'), accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.hand_line,
            source_type=EstimateLineItemSource.SOURCE_FEE, source_pk=self.fee.pk,
        )
        self.co = ChangeOrder.objects.create(job=self.job, estimate=self.estimate)

    def test_comment_add_line_crystallizes_nothing(self):
        ChangeOrderLineItem.objects.create(
            change_order=self.co, line_number=1, action=ChangeOrderLineItem.ACTION_ADD,
            description='FYI: customer prefers morning delivery', is_comment=True,
            qty=Decimal('0'), price=Decimal('0'),
        )
        result = ChangeOrderAcceptanceService.on_accept(self.co)
        self.assertEqual(result['fees_created'], 0)
        self.assertEqual(result['tasks_created'], 0)
        self.assertEqual(result['materials_created'], 0)

    def test_comment_replace_retires_old_fee_without_crystallizing(self):
        ChangeOrderLineItem.objects.create(
            change_order=self.co, line_number=1, action=ChangeOrderLineItem.ACTION_REPLACE,
            description='Cancelled — see note', is_comment=True,
            qty=Decimal('0'), price=Decimal('0'), target_line_item=self.hand_line,
        )
        result = ChangeOrderAcceptanceService.on_accept(self.co)
        self.assertEqual(result['fees_created'], 0)
        self.assertEqual(result['fees_removed'], 1)
        self.assertFalse(Fee.objects.filter(pk=self.fee.pk).exists())


class InvoiceCommentLineCategorizationTest(TestCase):
    """Comment lines are exempt from the pre-send categorization gate."""

    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})

        self.cat = AccountingCategory.objects.create(code='LAB4', name='Labor', taxable=False)
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Cust', email='pat4@acme.com',
        )
        self.job = Job.objects.create(job_number='JOB-CMT-0004', contact=self.contact)
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_categorized_and_comment_lines_pass_the_gate(self):
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1, description='Labor',
            qty=Decimal('1'), price=Decimal('100.00'), accounting_category=self.cat,
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=2, description='See attached warranty terms',
            is_comment=True, qty=Decimal('0'), price=Decimal('0'), accounting_category=None,
        )
        InvoiceEmailService._assert_all_lines_categorized(self.invoice)  # should not raise

    def test_uncategorized_non_comment_line_still_blocks(self):
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1, description='Uncategorized',
            qty=Decimal('1'), price=Decimal('50.00'), accounting_category=None,
        )
        with self.assertRaises(DjangoValidationError):
            InvoiceEmailService._assert_all_lines_categorized(self.invoice)


class QBOInvoicePushSkipsCommentLinesTest(TestCase):
    """_build_qbo_invoice must never push a comment line to QBO."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(code='LAB5', name='Labor', taxable=True, qbo_item_id='55')
        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe', email='john5@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(job_number='JOB-CMT-0005', contact=self.contact, name='Cabinet run')
        self.invoice = Invoice.objects.create(job=self.job, invoice_number='INV-CMT-0005')

    def test_comment_line_excluded_from_qbo_lines(self):
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1, description='Priced line',
            qty=Decimal('1'), price=Decimal('10.00'), accounting_category=self.cat,
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=2, description='Internal note — do not bill',
            is_comment=True, qty=Decimal('0'), price=Decimal('0'), accounting_category=None,
        )
        qbo_inv = QBOInvoiceSyncService._build_qbo_invoice(self.invoice, '77', MagicMock())
        self.assertEqual(len(qbo_inv.Line), 1)
        self.assertEqual(qbo_inv.Line[0].Description, 'Priced line')


class PurchaseOrderCommentLineTest(TestCase):
    """A PO comment line is a bare informational row — no category required."""

    def setUp(self):
        Configuration.objects.update_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})

        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Vendor', email='pat6@acme.com', work_number='555-0100',
        )
        self.business = Business.objects.create(
            business_name='Vendor Co', default_contact=self.contact, our_reference_code='VND-0001',
        )
        self.contact.business = self.business
        self.contact.save()
        self.po = PurchaseOrder.objects.create(
            business=self.business, contact=self.contact,
            po_number='PO-CMT-0006', status=PurchaseOrder.STATUS_DRAFT,
        )

    def test_add_comment_line_with_no_category(self):
        li = PurchaseOrderService.add_line_item(
            self.po.pk, description='Vendor lead time is 6 weeks', is_comment=True,
            qty=Decimal('0'), price=Decimal('0'),
        )
        self.assertTrue(li.is_comment)
        self.assertIsNone(li.accounting_category_id)
