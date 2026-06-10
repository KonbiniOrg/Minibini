from decimal import Decimal
from apps.core.models import JobHistory
from django.test import TestCase

from apps.contacts.models import Contact
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateService
from apps.jobs.services import JobService


class UpdateStatusActorTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='Actor Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Work', qty=Decimal('1'),
            price=Decimal('100.00'))
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)

    def test_actor_writes_customer_history_entry(self):
        EstimateService.update_status(
            self.est.pk, Estimate.STATUS_ACCEPTED,
            actor={'contact_id': self.contact.pk, 'email': 'pat@acme.com'})
        entry = JobHistory.objects.filter(
            object_type='estimate', object_id=self.est.pk, entry_type='action',
        ).order_by('-timestamp').first()
        self.assertIsNotNone(entry)
        self.assertIsNone(entry.user)
        self.assertEqual(entry.changes['_action'], 'Accepted via customer link')
        self.assertEqual(entry.changes['customer_email'], 'pat@acme.com')
        self.assertEqual(entry.changes['contact_id'], self.contact.pk)

    def test_reject_actor_records_reason(self):
        EstimateService.update_status(
            self.est.pk, Estimate.STATUS_REJECTED,
            actor={'contact_id': self.contact.pk, 'email': 'pat@acme.com',
                   'reason': 'Too expensive'})
        entry = JobHistory.objects.filter(
            object_type='estimate', object_id=self.est.pk, entry_type='action',
        ).order_by('-timestamp').first()
        self.assertEqual(entry.changes['_action'], 'Declined via customer link')
        self.assertEqual(entry.text, 'Too expensive')

    def test_no_actor_writes_no_action_entry(self):
        before = JobHistory.objects.filter(
            object_type='estimate', object_id=self.est.pk,
            entry_type='action').count()
        EstimateService.update_status(self.est.pk, Estimate.STATUS_ACCEPTED)
        after = JobHistory.objects.filter(
            object_type='estimate', object_id=self.est.pk,
            entry_type='action').count()
        self.assertEqual(before, after)
