"""Tests for ChangeOrderEmailService (shop notification + send-to-customer)
and build_object_url('change_order')."""
from decimal import Decimal

from django.core import mail
from django.test import override_settings

from tests.base import FixtureTestCase
from apps.contacts.models import Contact
from apps.core.models import Configuration
from apps.core.email_templates import build_object_url
from apps.deliverables.models import Deliverable
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import (
    Estimate, ChangeOrder, ChangeOrderLineItem,
)
from apps.estimates.services import ChangeOrderEmailService
from apps.jobs.models import Job
from apps.jobs.services import JobService


def _advance_job_to_on_hold(job):
    """Draft → submitted → approved, then hold (on_hold flag)."""
    from apps.jobs.services import JobService
    for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
        job.status = s
        job.save()
    JobService.hold_job(job.pk, 'CO editing')
    job.refresh_from_db()


class BuildObjectUrlChangeOrderTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        Configuration.objects.update_or_create(
            key='our_public_url', defaults={'value': 'https://shop.test'})
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-URL-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.co = ChangeOrder.objects.create(job=self.job, estimate=self.est)

    def test_change_order_url_uses_token_and_doc_param(self):
        url = build_object_url('change_order', self.co.change_order_id)
        self.assertEqual(
            url,
            f'https://shop.test/portal/?token={self.co.public_token}&doc=change_order',
        )


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ChangeOrderNotifyShopTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        Configuration.objects.update_or_create(
            key='business_email', defaults={'value': 'office@shop.com'})
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-NOTIFY-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.co = ChangeOrder.objects.create(job=self.job, estimate=self.est)

    def test_notify_sends_to_business_email(self):
        mail.outbox = []
        ChangeOrderEmailService.notify_shop_of_decision(self.co, 'accepted')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('office@shop.com', mail.outbox[0].to)
        self.assertIn(self.co.change_order_number, mail.outbox[0].subject)
        self.assertIn('accepted', mail.outbox[0].subject)

    def test_notify_includes_reason(self):
        mail.outbox = []
        ChangeOrderEmailService.notify_shop_of_decision(
            self.co, 'declined', reason='too pricey')
        self.assertIn('too pricey', mail.outbox[0].body)

    def test_notify_noop_without_business_email(self):
        Configuration.objects.filter(key='business_email').delete()
        mail.outbox = []
        ChangeOrderEmailService.notify_shop_of_decision(self.co, 'accepted')
        self.assertEqual(len(mail.outbox), 0)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ChangeOrderSendTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        Configuration.objects.update_or_create(
            key='our_public_url', defaults={'value': 'https://shop.test'})
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='CO Send Job', contact=self.contact)
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-SEND-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        Deliverable.objects.create(
            job=self.job, description='Thing', qty_ordered=Decimal('1'),
            units='ea', sort_order=10)
        _advance_job_to_on_hold(self.job)
        self.co = ChangeOrderService.create(job_id=self.job.pk)
        ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra', qty=Decimal('1'), price=Decimal('200'),
            line_number=1, accounting_category_id=901)

    def test_get_email_defaults_has_to_link_and_pdf_preview(self):
        defaults = ChangeOrderEmailService.get_email_defaults(self.co)
        self.assertEqual(defaults['to'], 'pat@acme.com')
        self.assertIn(self.co.public_token, defaults['body'])
        self.assertEqual(len(defaults['attachments_preview']), 1)
        self.assertEqual(
            defaults['attachments_preview'][0]['content_type'], 'application/pdf')

    def test_send_transitions_draft_to_open(self):
        mail.outbox = []
        ChangeOrderEmailService.send_change_order(
            self.co, to='pat@acme.com', subject='Your change order',
            body='Please review: link')
        self.co.refresh_from_db()
        self.assertEqual(self.co.status, ChangeOrder.STATUS_OPEN)
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_on_open_co_sends_without_status_change(self):
        """The 'Resend to customer' link re-sends an already-open CO: another
        email goes out, status stays open (the draft->open transition only fires
        on the first send)."""
        ChangeOrderEmailService.send_change_order(
            self.co, to='pat@acme.com', subject='s', body='b')
        self.co.refresh_from_db()
        self.assertEqual(self.co.status, ChangeOrder.STATUS_OPEN)
        mail.outbox = []
        ChangeOrderEmailService.send_change_order(
            self.co, to='pat@acme.com', subject='resend', body='link again')
        self.co.refresh_from_db()
        self.assertEqual(self.co.status, ChangeOrder.STATUS_OPEN)
        self.assertEqual(len(mail.outbox), 1)

    def test_send_leaves_job_on_hold(self):
        ChangeOrderEmailService.send_change_order(
            self.co, to='pat@acme.com', subject='s', body='b')
        self.job.refresh_from_db()
        self.assertTrue(self.job.on_hold)

    def test_send_requires_recipient(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            ChangeOrderEmailService.send_change_order(
                self.co, to='', subject='s', body='b')

    def test_send_requires_line_items(self):
        """Defensive parity with send_estimate: no email goes out for an empty
        CO (and no draft->open transition)."""
        from django.core.exceptions import ValidationError
        ChangeOrderLineItem.objects.filter(change_order=self.co).delete()
        mail.outbox = []
        with self.assertRaises(ValidationError):
            ChangeOrderEmailService.send_change_order(
                self.co, to='pat@acme.com', subject='s', body='b')
        self.assertEqual(len(mail.outbox), 0)
        self.co.refresh_from_db()
        self.assertEqual(self.co.status, ChangeOrder.STATUS_DRAFT)
