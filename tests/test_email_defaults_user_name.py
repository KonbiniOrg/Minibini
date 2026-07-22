"""{my_user_name} in send-defaults renders the requesting user's name.

Longstanding gap (noticed 2026-07-22): all three document email services
hardcoded my_user_name to '' so every outbound template signed off blank.
"""
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, User
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateEmailService
from apps.invoicing.models import Invoice
from apps.invoicing.services import InvoiceEmailService
from apps.jobs.models import Job
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import PurchaseOrderEmailService


class EmailDefaultsUserNameTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='rmc', password='x',
            first_name='Rachel', last_name='McConnell',
        )
        self.bare_user = User.objects.create_user(
            username='bare', password='x',
        )
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(
            contact=self.contact, job_number='JOB-2026-0001', name='Cabinets',
        )

    def test_invoice_defaults_render_full_name(self):
        invoice = Invoice.objects.create(job=self.job)
        defaults = InvoiceEmailService.get_email_defaults(
            invoice, user=self.user)
        self.assertIn('Rachel McConnell', defaults['body'])

    def test_invoice_defaults_fall_back_to_username(self):
        invoice = Invoice.objects.create(job=self.job)
        defaults = InvoiceEmailService.get_email_defaults(
            invoice, user=self.bare_user)
        self.assertIn('bare', defaults['body'])

    def test_invoice_defaults_without_user_stay_blank(self):
        invoice = Invoice.objects.create(job=self.job)
        defaults = InvoiceEmailService.get_email_defaults(invoice)
        self.assertNotIn('{my_user_name}', defaults['body'])

    def test_estimate_defaults_render_full_name(self):
        estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-UN-1',
        )
        defaults = EstimateEmailService.get_email_defaults(
            estimate, user=self.user)
        self.assertIn('Rachel McConnell', defaults['body'])

    def test_po_defaults_render_full_name(self):
        # The PO *default* body has no {my_user_name}; a configured template
        # may use it — this asserts the plumbing resolves it.
        from apps.core.models import Configuration
        Configuration.objects.create(
            key='po_email_body_template',
            value='PO {document_number} attached.\n\nThanks,\n{my_user_name}',
        )
        business = Business.objects.create(
            business_name='Vendor Co', default_contact=self.contact,
        )
        po = PurchaseOrder.objects.create(
            business=business, po_number='PO-UN-1',
        )
        defaults = PurchaseOrderEmailService.get_email_defaults(
            po, user=self.user)
        self.assertIn('Rachel McConnell', defaults['body'])
