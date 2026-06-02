from decimal import Decimal
from django.test import TestCase

from apps.api.portal.views import build_estimate_payload
from apps.contacts.models import Contact
from apps.deliverables.models import Deliverable
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
        self.assertEqual(data['actions'], ['accept', 'reject'])
        self.assertEqual(len(data['line_items']), 1)
        self.assertEqual(data['line_items'][0]['amount'], '100.00')
        self.assertEqual(data['grand_total'], '100.00')
        self.assertEqual(len(data['deliverables']), 1)
        self.assertEqual(data['deliverables'][0]['description'], 'One finished widget')
        self.assertNotIn('cost', str(data))

    def test_draft_has_no_actions(self):
        data = build_estimate_payload(self.est)
        self.assertEqual(data['actions'], [])

    def test_superseded_exposes_current_token(self):
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        new_est = EstimateService.revise_estimate(self.est.pk)
        self.est.refresh_from_db()
        data = build_estimate_payload(self.est)
        self.assertEqual(data['status'], 'superseded')
        self.assertEqual(data['current_token'], new_est.public_token)
