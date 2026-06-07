from decimal import Decimal
from django.test import TestCase

from apps.api.portal.views import build_estimate_payload
from apps.contacts.models import Contact
from apps.deliverables.models import Deliverable
from apps.deliverables.services import DeliverableService
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateService
from apps.jobs.services import JobService


class PortalPayloadTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='Payload Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Build widget',
            qty=Decimal('2'), units='each', price=Decimal('50.00'))
        Deliverable.objects.create(
            job=self.job, description='One finished widget',
            qty_ordered=Decimal('2'), units='each')

    def test_open_payload_shape(self):
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        self.est.refresh_from_db()
        data = build_estimate_payload(self.est)
        self.assertEqual(data['status'], 'open')
        self.assertEqual(data['actions'], ['accept', 'request_changes', 'reject'])
        self.assertEqual(len(data['line_items']), 1)
        self.assertEqual(data['line_items'][0]['amount'], '100.00')
        self.assertEqual(data['grand_total'], '100.00')
        self.assertEqual(len(data['deliverables']), 1)
        self.assertEqual(data['deliverables'][0]['description'], 'One finished widget')
        self.assertNotIn('cost', str(data))

    def test_draft_has_no_actions(self):
        data = build_estimate_payload(self.est)
        self.assertEqual(data['actions'], [])

    def test_superseded_exposes_current_token_for_sent_revision(self):
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        new_est = EstimateService.revise_estimate(self.est.pk)
        # current_token points to the latest *non-draft* version, so the
        # revision must be sent before it's offered to the customer.
        EstimateService.update_status(new_est.pk, Estimate.STATUS_OPEN)
        new_est.refresh_from_db()
        self.est.refresh_from_db()
        data = build_estimate_payload(self.est)
        self.assertEqual(data['status'], 'superseded')
        self.assertEqual(data['current_token'], new_est.public_token)

    def test_superseded_with_unsent_draft_revision_has_no_current_token(self):
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        EstimateService.revise_estimate(self.est.pk)  # draft, unsent
        self.est.refresh_from_db()
        data = build_estimate_payload(self.est)
        self.assertEqual(data['status'], 'superseded')
        self.assertIsNone(data['current_token'])

    def test_superseded_payload_uses_frozen_snapshot_not_live(self):
        # Send, then supersede — which snapshots the parent's deliverables.
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        EstimateService.revise_estimate(self.est.pk)
        # The revision edits the now-editable live list.
        d = Deliverable.objects.get(job=self.job)
        d.qty_ordered = Decimal('99')
        d.description = 'Completely different widget'
        d.save()

        self.est.refresh_from_db()
        data = build_estimate_payload(self.est)
        # The superseded estimate must show what the customer saw, not the
        # drifted live list.
        self.assertEqual(len(data['deliverables']), 1)
        self.assertEqual(
            data['deliverables'][0]['description'], 'One finished widget')
        self.assertEqual(data['deliverables'][0]['qty_ordered'], '2.00')

    def test_accepted_with_snapshot_uses_snapshot_not_live(self):
        # An accepted estimate that has been frozen (e.g. by a later change
        # order) shows the agreed scope, not the CO-amended live list.
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        EstimateService.update_status(self.est.pk, Estimate.STATUS_ACCEPTED)
        DeliverableService.snapshot_document(estimate=self.est)
        d = Deliverable.objects.get(job=self.job)
        d.qty_ordered = Decimal('99')
        d.save()

        self.est.refresh_from_db()
        data = build_estimate_payload(self.est)
        self.assertEqual(data['deliverables'][0]['qty_ordered'], '2.00')

    def test_current_open_estimate_uses_live_list(self):
        # No snapshot yet -> live list is the source of truth.
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        self.est.refresh_from_db()
        data = build_estimate_payload(self.est)
        self.assertEqual(len(data['deliverables']), 1)
        self.assertEqual(data['deliverables'][0]['qty_ordered'], '2.00')
