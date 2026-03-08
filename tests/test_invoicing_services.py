"""Tests for invoicing app service methods (service-mediated saves)."""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.services import InvoiceService
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job
from apps.core.models import LineItemType


class InvoiceServiceReorderTest(TestCase):
    """Tests for InvoiceService.reorder_line_item — delegates to LineItemService."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@test.com', work_number='555-1234',
        )
        self.business = Business.objects.create(
            business_name='Test Biz', business_phone='555-1234',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(
            name='Test Job', job_number='J2026-0001',
            contact=self.contact, status='draft',
        )
        self.lit = LineItemType.objects.create(
            code='SVC', name='Service', taxable=True,
        )
        self.invoice = Invoice.objects.create(
            job=self.job, invoice_number='INV-0001', status='draft',
        )
        self.li1 = InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=1,
            description='Item 1', qty=1, price=Decimal('10.00'),
            line_item_type=self.lit,
        )
        self.li2 = InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=2,
            description='Item 2', qty=1, price=Decimal('20.00'),
            line_item_type=self.lit,
        )
        self.li3 = InvoiceLineItem.objects.create(
            invoice=self.invoice, line_number=3,
            description='Item 3', qty=1, price=Decimal('30.00'),
            line_item_type=self.lit,
        )

    def test_reorder_down(self):
        """Move line item 1 down — should swap with line item 2."""
        InvoiceService.reorder_line_item(self.li1.pk, 'down')
        self.li1.refresh_from_db()
        self.li2.refresh_from_db()
        self.assertEqual(self.li1.line_number, 2)
        self.assertEqual(self.li2.line_number, 1)

    def test_reorder_up(self):
        """Move line item 3 up — should swap with line item 2."""
        InvoiceService.reorder_line_item(self.li3.pk, 'up')
        self.li3.refresh_from_db()
        self.li2.refresh_from_db()
        self.assertEqual(self.li3.line_number, 2)
        self.assertEqual(self.li2.line_number, 3)

    def test_reorder_non_draft_raises(self):
        """Cannot reorder on a non-draft invoice."""
        self.invoice.status = 'open'
        self.invoice.save()
        with self.assertRaises(ValidationError):
            InvoiceService.reorder_line_item(self.li1.pk, 'down')
