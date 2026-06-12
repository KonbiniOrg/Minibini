"""Invoice.sent_date is stamped on the draft -> open transition (the
send-to-customer step), mirroring Estimate.save(). Drives the serializer's
derived due_date / is_late. See apps/invoicing/models.py.
"""
from decimal import Decimal

from django.utils import timezone

from tests.base import FixtureTestCase
from apps.contacts.models import Contact
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.jobs.models import Job


class InvoiceSentDateTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.create(
            job_number='JOB-SENT-1', name='Sent test',
            status=Job.STATUS_WORK_COMPLETE, contact=Contact.objects.first(),
        )

    def _draft_with_line(self, number='INV-SENT-1'):
        inv = Invoice.objects.create(
            job=self.job, invoice_number=number, status=Invoice.STATUS_DRAFT)
        InvoiceLineItem.objects.create(
            invoice=inv, qty=Decimal('1'), price=Decimal('100'))
        return inv

    def test_stamped_on_draft_to_open(self):
        inv = self._draft_with_line()
        self.assertIsNone(inv.sent_date)
        before = timezone.now()
        inv.status = Invoice.STATUS_OPEN
        inv.save()
        inv.refresh_from_db()
        self.assertIsNotNone(inv.sent_date)
        self.assertGreaterEqual(inv.sent_date, before)

    def test_sent_date_preserved_on_later_save(self):
        inv = self._draft_with_line()
        inv.status = Invoice.STATUS_OPEN
        inv.save()
        inv.refresh_from_db()
        original = inv.sent_date
        inv.status = Invoice.STATUS_PARTLY_PAID
        inv.save()
        inv.refresh_from_db()
        self.assertEqual(inv.sent_date, original)

    def test_direct_create_as_open_not_stamped(self):
        # Only a real draft -> open transition stamps it; a row created directly
        # as open (test/seed path) is left alone.
        inv = Invoice.objects.create(
            job=self.job, invoice_number='INV-SENT-2', status=Invoice.STATUS_OPEN)
        self.assertIsNone(inv.sent_date)
