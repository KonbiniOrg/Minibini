"""Tests for the token-authorized customer portal for ChangeOrders.

Mirrors tests/test_portal_api.py + test_portal_job_status_gate.py +
test_portal_request_changes.py, for the CO surface.
"""
from decimal import Decimal
from apps.core.models import JobHistory

from django.core import mail
from django.test import Client, TestCase, override_settings

from apps.contacts.models import Contact
from apps.core.models import Configuration, HistoryEntry
from apps.deliverables.models import Deliverable
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import (
    Estimate, EstimateLineItem, ChangeOrder, ChangeOrderLineItem,
)
from apps.jobs.models import Job
from apps.jobs.services import JobService


def _advance_job_to_on_hold(job):
    job.status = Job.STATUS_SUBMITTED; job.save()
    job.status = Job.STATUS_APPROVED; job.save()
    job.status = Job.STATUS_ON_HOLD; job.save()
    job.refresh_from_db()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PortalChangeOrderTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.http = Client()  # deliberately unauthenticated
        Configuration.objects.update_or_create(
            key='business_email', defaults={'value': 'office@shop.com'})
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='CO Job', contact=self.contact)
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-PORTAL-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.eli = EstimateLineItem.objects.create(
            estimate=self.est, description='Base work', qty=Decimal('1'),
            units='ea', price=Decimal('100.00'), line_number=1)
        Deliverable.objects.create(
            job=self.job, description='Widget', qty_ordered=Decimal('2'),
            units='ea', sort_order=10)
        _advance_job_to_on_hold(self.job)
        self.co = ChangeOrderService.create(job_id=self.job.pk)
        ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra scope', qty=Decimal('1'), units='ea',
            price=Decimal('250.00'), line_number=1)
        ChangeOrderService.mark_open(self.co.pk)
        self.co.refresh_from_db()
        self.token = self.co.public_token

    # --- GET ---

    def test_get_open_co_no_auth(self):
        r = self.http.get(f'/api/portal/change-orders/{self.token}/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['status'], 'open')
        self.assertEqual(body['change_order_number'], self.co.change_order_number)
        self.assertEqual(body['actions'], ['accept', 'request_changes', 'reject'])
        self.assertTrue(body['actionable'])

    def test_get_includes_line_and_deliverable_diff(self):
        r = self.http.get(f'/api/portal/change-orders/{self.token}/')
        body = r.json()
        kinds = [row['kind'] for row in body['line_rows']]
        self.assertEqual(kinds, ['unchanged', 'added'])
        self.assertEqual(body['prior_total'], '100.00')
        self.assertEqual(body['proposed_total'], '350.00')
        self.assertEqual(body['diff_total'], '250.00')
        self.assertTrue(len(body['deliverables']) >= 1)

    def test_get_unknown_token_404(self):
        r = self.http.get('/api/portal/change-orders/nope/')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()['detail'], 'Not available.')

    def test_get_draft_token_404(self):
        draft = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        r = self.http.get(f'/api/portal/change-orders/{draft.public_token}/')
        self.assertEqual(r.status_code, 404)

    # --- accept ---

    def test_accept_advances_job_and_records_customer_history(self):
        mail.outbox = []
        r = self.http.post(f'/api/portal/change-orders/{self.token}/accept/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'accepted')
        self.co.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.co.status, ChangeOrder.STATUS_ACCEPTED)
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)
        entry = JobHistory.objects.filter(
            object_type='changeorder', object_id=self.co.pk,
            entry_type='action', user__isnull=True,
        ).order_by('-pk').first()
        self.assertIsNotNone(entry)
        self.assertIn('customer link', entry.changes.get('_action', ''))
        self.assertEqual(len(mail.outbox), 1)

    def test_accept_on_already_terminal_is_noop(self):
        # An open CO can't have its job moved off on_hold (the exit guard blocks
        # it), so the realistic race is: the shop accepts the CO via the service
        # (closing it), and a second portal accept must be a safe no-op rather
        # than re-running the transition.
        ChangeOrderService.update_status(self.co.pk, ChangeOrder.STATUS_ACCEPTED)
        r = self.http.post(f'/api/portal/change-orders/{self.token}/accept/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'accepted')

    # --- reject ---

    def test_reject_leaves_job_on_hold_and_records_reason(self):
        r = self.http.post(
            f'/api/portal/change-orders/{self.token}/reject/',
            data={'reason': 'too pricey'}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.co.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.co.status, ChangeOrder.STATUS_REJECTED)
        self.assertEqual(self.job.status, Job.STATUS_ON_HOLD)
        entry = JobHistory.objects.filter(
            object_type='changeorder', object_id=self.co.pk,
            entry_type='action', user__isnull=True,
        ).order_by('-pk').first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.text, 'too pricey')

    # --- request changes ---

    def test_request_changes_supersedes_and_seeds_draft(self):
        r = self.http.post(
            f'/api/portal/change-orders/{self.token}/request-changes/',
            data={'reason': 'cheaper please'}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.co.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.co.status, ChangeOrder.STATUS_SUPERSEDED)
        self.assertEqual(self.job.status, Job.STATUS_ON_HOLD)
        self.assertTrue(
            ChangeOrder.objects.filter(
                job=self.job, status=ChangeOrder.STATUS_DRAFT,
                parent=self.co).exists())

    def test_request_changes_stores_comment_and_notifies(self):
        mail.outbox = []
        self.http.post(
            f'/api/portal/change-orders/{self.token}/request-changes/',
            data={'reason': 'cheaper please'}, content_type='application/json')
        entry = JobHistory.objects.filter(
            object_type='changeorder', object_id=self.co.pk,
            entry_type='action').order_by('-pk').first()
        self.assertEqual(entry.text, 'cheaper please')
        self.assertEqual(len(mail.outbox), 1)

    def test_request_changes_on_non_open_is_noop(self):
        ChangeOrderService.update_status(self.co.pk, ChangeOrder.STATUS_ACCEPTED)
        r = self.http.post(
            f'/api/portal/change-orders/{self.token}/request-changes/',
            data={'reason': 'x'}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(
            ChangeOrder.objects.filter(
                job=self.job, status=ChangeOrder.STATUS_DRAFT).exists())

    def test_request_changes_unknown_token_404(self):
        r = self.http.post(
            '/api/portal/change-orders/nope/request-changes/',
            data={'reason': 'x'}, content_type='application/json')
        self.assertEqual(r.status_code, 404)


class PortalChangeOrderSupersededTokenTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.http = Client()
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='CO Job 2', contact=self.contact)
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-SUP-1', version=1,
            status=Estimate.STATUS_ACCEPTED)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Base', qty=Decimal('1'),
            units='ea', price=Decimal('100'), line_number=1)
        Deliverable.objects.create(
            job=self.job, description='W', qty_ordered=Decimal('1'),
            units='ea', sort_order=10)
        _advance_job_to_on_hold(self.job)
        self.co = ChangeOrderService.create(job_id=self.job.pk)
        ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra', qty=Decimal('1'), units='ea',
            price=Decimal('50'), line_number=1)
        ChangeOrderService.mark_open(self.co.pk)
        self.co.refresh_from_db()

    def test_superseded_current_token_none_until_revision_sent(self):
        # request_changes supersedes co and seeds a draft (portal-invisible).
        new_co = ChangeOrderService.request_changes(
            self.co.pk, {'contact_id': None, 'email': '', 'reason': 'x'})
        r = self.http.get(f'/api/portal/change-orders/{self.co.public_token}/')
        self.assertEqual(r.json()['status'], 'superseded')
        self.assertIsNone(r.json()['current_token'])
        # Once the draft revision is sent, current_token points at it.
        ChangeOrderService.mark_open(new_co.pk)
        new_co.refresh_from_db()
        r = self.http.get(f'/api/portal/change-orders/{self.co.public_token}/')
        self.assertEqual(r.json()['current_token'], new_co.public_token)
