from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.core.models import Configuration, AppState
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job
from apps.estimates.models import Estimate, EstimateLineItem
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem


class EstimateLineItemRequirementTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='est_expire_days', value='30')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')

        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='JOB-TEST-0001', contact=self.contact,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-TEST-0001',
            status=Estimate.STATUS_DRAFT,
        )

    def test_cannot_send_estimate_without_line_items(self):
        self.estimate.status = Estimate.STATUS_OPEN
        with self.assertRaises(ValidationError) as ctx:
            self.estimate.save()
        self.assertIn('line item', str(ctx.exception).lower())

    def test_can_send_estimate_with_line_items(self):
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Test item',
            price=Decimal('100.00'),
        )
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, Estimate.STATUS_OPEN)


class InvoiceLineItemRequirementTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')

        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='JOB-TEST-0001', contact=self.contact,
        )
        self.invoice = Invoice.objects.create(
            job=self.job, invoice_number='INV-TEST-0001',
            status=Invoice.STATUS_DRAFT,
        )

    def test_cannot_send_invoice_without_line_items(self):
        self.invoice.status = Invoice.STATUS_OPEN
        with self.assertRaises(ValidationError) as ctx:
            self.invoice.save()
        self.assertIn('line item', str(ctx.exception).lower())

    def test_can_send_invoice_with_line_items(self):
        InvoiceLineItem.objects.create(
            invoice=self.invoice, description='Test item',
            price=Decimal('100.00'),
        )
        self.invoice.status = Invoice.STATUS_OPEN
        self.invoice.save()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.STATUS_OPEN)


class PurchaseOrderLineItemRequirementTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='po_number_sequence', value='PO-{counter:04d}')
        AppState.objects.create(key='po_counter', value='0')

        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.business = Business.objects.create(
            business_name='Test Biz', default_contact=self.contact,
            our_reference_code='TST-0001',
        )
        self.contact.business = self.business
        self.contact.save()
        self.po = PurchaseOrder.objects.create(
            business=self.business, contact=self.contact,
            po_number='PO-TEST-0001', status=PurchaseOrder.STATUS_DRAFT,
        )

    def test_cannot_issue_po_without_line_items(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        with self.assertRaises(ValidationError) as ctx:
            self.po.save()
        self.assertIn('line item', str(ctx.exception).lower())

    def test_can_issue_po_with_line_items(self):
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='Test item',
            price=Decimal('100.00'),
        )
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.STATUS_ISSUED)
