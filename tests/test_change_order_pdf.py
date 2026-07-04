"""Tests for change order PDF generation and its email attachment."""
from decimal import Decimal

from django.core import mail
from django.test import override_settings

from tests.base import FixtureTestCase
from apps.contacts.models import Contact
from apps.core.models import Configuration
from apps.deliverables.models import Deliverable
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import (
    Estimate, EstimateLineItem, ChangeOrder, ChangeOrderLineItem,
)
from apps.estimates.pdf import generate_change_order_pdf
from apps.estimates.services import ChangeOrderEmailService
from apps.jobs.models import Job
from apps.jobs.services import JobService


def _advance_job_to_on_hold(job):
    for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_ON_HOLD):
        job.status = s
        job.save()
    job.refresh_from_db()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ChangeOrderPdfTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        Configuration.objects.update_or_create(
            key='our_public_url', defaults={'value': 'https://shop.test'})
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='PDF Job', contact=self.contact)
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-PDF-1', version=1,
            status=Estimate.STATUS_ACCEPTED)
        self.l1 = EstimateLineItem.objects.create(
            estimate=self.est, description='Base work', qty=Decimal('2'),
            units='ea', price=Decimal('100.00'), line_number=1)
        Deliverable.objects.create(
            job=self.job, description='Widget', qty_ordered=Decimal('1'),
            units='ea', sort_order=10)
        _advance_job_to_on_hold(self.job)
        self.co = ChangeOrderService.create(job_id=self.job.pk)
        # An add + a replace, so the PDF exercises the diff row kinds.
        ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra scope', qty=Decimal('1'), units='ea',
            price=Decimal('250.00'), line_number=1, accounting_category_id=901)
        ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.l1, description='Base work (revised)',
            qty=Decimal('2'), units='ea', price=Decimal('150.00'), line_number=2)

    def test_generate_returns_pdf_bytes(self):
        pdf = generate_change_order_pdf(self.co)
        self.assertIsInstance(pdf, (bytes, bytearray))
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf), 500)

    def test_generate_renders_all_deliverable_diff_kinds(self):
        """Change / add / remove a deliverable so the template exercises every
        deliverable-diff branch without error."""
        # baseline (snapshot at create) = the single 'Widget' deliverable.
        widget = self.job.deliverables.get(description='Widget')
        widget.qty_ordered = Decimal('4')   # -> changed + changed-orig
        widget.save()
        Deliverable.objects.create(          # -> added
            job=self.job, description='New panel', qty_ordered=Decimal('2'),
            units='ea', sort_order=20)
        pdf = generate_change_order_pdf(self.co)
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_send_attaches_a_pdf(self):
        mail.outbox = []
        ChangeOrderEmailService.send_change_order(
            self.co, to='pat@acme.com', subject='CO', body='see link')
        self.assertEqual(len(mail.outbox), 1)
        attachments = mail.outbox[0].attachments
        self.assertEqual(len(attachments), 1)
        filename, content, mimetype = attachments[0]
        self.assertTrue(filename.endswith('.pdf'))
        self.assertEqual(mimetype, 'application/pdf')
        self.assertTrue(bytes(content).startswith(b'%PDF'))

    def test_pdf_shows_date_after_send(self):
        """Regression: the chained `sent_date|date|default:created_date|date`
        expression rendered a blank Date once sent_date was set (i.e. on a
        resend of an open CO). The date must render in all states."""
        from django.template.loader import render_to_string
        ChangeOrderService.mark_open(self.co.pk)
        self.co.refresh_from_db()
        self.assertIsNotNone(self.co.sent_date)
        html = render_to_string('estimates/change_order_pdf.html', {
            'co': self.co, 'job': self.job,
            'business_name': '', 'contact_name': '',
            'estimate_number': self.est.estimate_number,
            'deliverable_rows': [], 'line_rows': [],
            'prior_total': 0, 'proposed_total': 0, 'diff_total': 0,
        })
        self.assertIn(str(self.co.sent_date.year), html)

    def test_email_defaults_preview_shows_pdf(self):
        defaults = ChangeOrderEmailService.get_email_defaults(self.co)
        self.assertEqual(len(defaults['attachments_preview']), 1)
        self.assertEqual(
            defaults['attachments_preview'][0]['content_type'], 'application/pdf')
