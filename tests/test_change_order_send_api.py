"""Tests for the ChangeOrder send-to-customer API actions (send-defaults / send),
parallel to the estimate send endpoints."""
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core import mail
from django.test import override_settings
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import Configuration, User
from apps.deliverables.models import Deliverable
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import (
    Estimate, ChangeOrder, ChangeOrderLineItem,
)
from apps.jobs.models import Job
from apps.jobs.services import JobService
from tests.base import FixtureTestCase


def _add_can_manage_jobs(user):
    perm = Permission.objects.get(
        codename='can_manage_jobs', content_type__app_label='core')
    user.user_permissions.add(perm)
    return User.objects.get(pk=user.pk)


def _advance_job_to_on_hold(job):
    """Draft → submitted → approved, then hold (on_hold flag)."""
    from apps.jobs.services import JobService
    for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
        job.status = s
        job.save()
    JobService.hold_job(job.pk, 'CO editing')
    job.refresh_from_db()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ChangeOrderSendAPITest(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.manager = _add_can_manage_jobs(
            User.objects.create_user(username='co_send_mgr', password='x'))
        self.plain = User.objects.create_user(username='co_send_plain', password='x')
        Configuration.objects.update_or_create(
            key='our_public_url', defaults={'value': 'https://shop.test'})
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='Send Job', contact=self.contact)
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-SEND-API-1', version=1,
            status=Estimate.STATUS_ACCEPTED)
        Deliverable.objects.create(
            job=self.job, description='Thing', qty_ordered=Decimal('1'),
            units='ea', sort_order=10)
        _advance_job_to_on_hold(self.job)
        self.co = ChangeOrderService.create(job_id=self.job.pk)
        ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra', qty=Decimal('1'), price=Decimal('200'),
            line_number=1, accounting_category_id=901)

    def test_send_defaults_requires_auth(self):
        r = self.client.get(
            f'/api/change-orders/{self.co.change_order_id}/send-defaults/')
        self.assertEqual(r.status_code, 403)

    def test_send_defaults_returns_to_and_link(self):
        self.client.force_authenticate(user=self.manager)
        r = self.client.get(
            f'/api/change-orders/{self.co.change_order_id}/send-defaults/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['to'], 'pat@acme.com')
        self.assertIn(self.co.public_token, r.data['body'])

    def test_send_transitions_to_open(self):
        self.client.force_authenticate(user=self.manager)
        mail.outbox = []
        r = self.client.post(
            f'/api/change-orders/{self.co.change_order_id}/send/',
            {'to': 'pat@acme.com', 'subject': 'CO', 'body': 'link here'})
        self.assertEqual(r.status_code, 200)
        self.co.refresh_from_db()
        self.assertEqual(self.co.status, ChangeOrder.STATUS_OPEN)
        self.assertEqual(len(mail.outbox), 1)

    def test_send_requires_permission(self):
        self.client.force_authenticate(user=self.plain)
        r = self.client.post(
            f'/api/change-orders/{self.co.change_order_id}/send/',
            {'to': 'pat@acme.com', 'subject': 'CO', 'body': 'b'})
        self.assertEqual(r.status_code, 403)

    def test_send_missing_recipient_400(self):
        self.client.force_authenticate(user=self.manager)
        r = self.client.post(
            f'/api/change-orders/{self.co.change_order_id}/send/',
            {'to': '', 'subject': 'CO', 'body': 'b'})
        self.assertEqual(r.status_code, 400)
