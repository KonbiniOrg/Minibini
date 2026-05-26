from django.test import TestCase
from django.utils import timezone
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration
from apps.invoicing.models import Invoice
from apps.jobs.models import Job


class InvoiceClosedDateTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555',
        )
        self.business = Business.objects.create(business_name='Acme', default_contact=self.contact)
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(
            contact=self.contact, job_number='JOB-2026-0001',
            status=Job.STATUS_COMPLETED,
        )

    def test_closed_date_set_on_paid(self):
        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_OPEN)
        self.assertIsNone(inv.closed_date)
        inv.status = Invoice.STATUS_PAID
        inv.save()
        inv.refresh_from_db()
        self.assertIsNotNone(inv.closed_date)

    def test_existing_closed_date_not_overwritten(self):
        stamp = timezone.now()
        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_OPEN, closed_date=stamp)
        inv.status = Invoice.STATUS_PAID
        inv.save()
        inv.refresh_from_db()
        self.assertEqual(inv.closed_date, stamp)
