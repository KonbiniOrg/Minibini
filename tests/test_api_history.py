from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import HistoryEntry, User
from apps.api.history.serializers import HistoryEntrySerializer


class JobHistoryAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_job_history_returns_entries(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        HistoryEntry.objects.create(
            entry_type='audit', object_type='job', object_id=job.pk,
            user=self.user, changes={'name': {'old': 'A', 'new': 'B'}},
        )
        HistoryEntry.objects.create(
            entry_type='note', object_type='job', object_id=job.pk,
            user=self.user, text='A note',
        )
        response = self.client.get(f'/api/jobs/{job.pk}/history/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)

    def test_job_history_aggregates_related_objects(self):
        from apps.jobs.models import Job
        from apps.estimates.models import Estimate
        job = Job.objects.first()
        estimate = Estimate.objects.filter(job=job).first()
        if not estimate:
            self.skipTest('No estimate for this job')
        HistoryEntry.objects.create(
            entry_type='audit', object_type='job', object_id=job.pk,
            changes={'status': {'old': 'draft', 'new': 'submitted'}},
        )
        HistoryEntry.objects.create(
            entry_type='audit', object_type='estimate', object_id=estimate.pk,
            changes={'status': {'old': 'draft', 'new': 'open'}},
        )
        response = self.client.get(f'/api/jobs/{job.pk}/history/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)

    def test_job_history_excludes_unrelated(self):
        from apps.jobs.models import Job
        job1 = Job.objects.first()
        job2 = Job.objects.exclude(pk=job1.pk).first()
        if not job2:
            self.skipTest('Need 2 jobs')
        HistoryEntry.objects.create(
            entry_type='note', object_type='job', object_id=job1.pk, text='Job 1',
        )
        HistoryEntry.objects.create(
            entry_type='note', object_type='job', object_id=job2.pk, text='Job 2',
        )
        response = self.client.get(f'/api/jobs/{job1.pk}/history/')
        self.assertEqual(response.data['count'], 1)

    def test_job_history_ordered_newest_first(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        e1 = HistoryEntry.objects.create(
            entry_type='audit', object_type='job', object_id=job.pk,
            changes={'name': {'old': 'A', 'new': 'B'}},
        )
        e2 = HistoryEntry.objects.create(
            entry_type='note', object_type='job', object_id=job.pk,
            text='Later note',
        )
        response = self.client.get(f'/api/jobs/{job.pk}/history/')
        results = response.data['results']
        self.assertEqual(results[0]['id'], e2.pk)


class ContactHistoryAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_contact_history(self):
        from apps.contacts.models import Contact
        contact = Contact.objects.first()
        HistoryEntry.objects.create(
            entry_type='audit', object_type='contact', object_id=contact.pk,
            changes={'first_name': {'old': 'A', 'new': 'B'}},
        )
        response = self.client.get(f'/api/contacts/{contact.pk}/history/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)


class BusinessHistoryAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_business_history_aggregates_contacts(self):
        from apps.contacts.models import Contact, Business
        business = Business.objects.first()
        contact = Contact.objects.filter(business=business).first()
        if not contact:
            self.skipTest('No contact for this business')
        HistoryEntry.objects.create(
            entry_type='audit', object_type='business', object_id=business.pk,
            changes={'business_name': {'old': 'A', 'new': 'B'}},
        )
        HistoryEntry.objects.create(
            entry_type='audit', object_type='contact', object_id=contact.pk,
            changes={'first_name': {'old': 'X', 'new': 'Y'}},
        )
        response = self.client.get(f'/api/businesses/{business.pk}/history/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)


class HistoryEntrySourceLabelTest(BaseTestCase):
    def test_source_label_from_context(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        entry = HistoryEntry.objects.create(
            entry_type='note', object_type='job', object_id=job.pk, text='hi',
        )
        ctx = {
            'source_labels': {('job', job.pk): 'Job XYZ'},
            'source_links': {('job', job.pk): '#/jobs/1'},
        }
        data = HistoryEntrySerializer(entry, context=ctx).data
        self.assertEqual(data['source_label'], 'Job XYZ')
        self.assertEqual(data['source_link'], '#/jobs/1')

    def test_source_label_defaults_null_without_context(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        entry = HistoryEntry.objects.create(
            entry_type='note', object_type='job', object_id=job.pk, text='hi',
        )
        data = HistoryEntrySerializer(entry).data
        self.assertIsNone(data['source_label'])
        self.assertIsNone(data['source_link'])


class JobHistoryCollationTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_collates_new_object_types_and_labels(self):
        from apps.jobs.models import Job, Task
        job = Job.objects.first()
        task = Task.objects.create(job=job, name='History test task', rate_scheme_id=1)
        HistoryEntry.objects.create(
            entry_type='audit', object_type='task', object_id=task.pk,
            changes={'status': {'old': 'pending', 'new': 'complete'}},
        )
        resp = self.client.get(f'/api/jobs/{job.pk}/history/')
        self.assertEqual(resp.status_code, 200)
        labels = {(e['object_type'], e['source_label']) for e in resp.data['results']}
        self.assertIn(('task', f'Task: {task.name}'), labels)

    def test_collates_change_orders(self):
        from decimal import Decimal
        from apps.jobs.models import Job
        from apps.estimates.models import ChangeOrder, Estimate
        from apps.deliverables.models import Deliverable
        from apps.estimates.change_order_service import ChangeOrderService

        job = Job.objects.first()
        # Clear any pre-existing estimates on the job to avoid "already accepted"
        # conflicts, then build the minimum setup ChangeOrderService.create needs:
        # an accepted estimate + job on on_hold.
        Estimate.objects.filter(job=job).delete()
        est = Estimate.objects.create(
            job=job, estimate_number='EST-HIST-CO-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        Deliverable.objects.create(
            job=job, description='Widget', qty_ordered=Decimal('1'),
            units='ea', sort_order=1,
        )
        job.status = Job.STATUS_SUBMITTED; job.save()
        job.status = Job.STATUS_APPROVED; job.save()
        job.status = Job.STATUS_ON_HOLD; job.save()
        job.refresh_from_db()

        co = ChangeOrderService.create(job_id=job.pk)

        HistoryEntry.objects.create(
            entry_type='action', object_type='changeorder', object_id=co.pk,
            changes={'_action': 'Auto-expired'},
        )
        resp = self.client.get(f'/api/jobs/{job.pk}/history/')
        labels = {(e['object_type'], e['source_label']) for e in resp.data['results']}
        self.assertIn(('changeorder', f'Change Order {co.change_order_number}'), labels)

    def test_excludes_estworksheet(self):
        from apps.jobs.models import Job
        from apps.estimates.models import EstWorksheet

        job = Job.objects.first()
        # Construct a minimal EstWorksheet — only job= is required.
        ws = EstWorksheet.objects.create(job=job)
        HistoryEntry.objects.create(
            entry_type='audit', object_type='estworksheet', object_id=ws.pk,
            changes={'status': {'old': 'a', 'new': 'b'}},
        )
        resp = self.client.get(f'/api/jobs/{job.pk}/history/')
        types = [e['object_type'] for e in resp.data['results']]
        self.assertNotIn('estworksheet', types)

    def test_source_links_for_estimate_invoice_shipment(self):
        from apps.jobs.models import Job
        from apps.estimates.models import Estimate
        from apps.invoicing.models import Invoice
        from apps.deliverables.models import Shipment
        from apps.api.jobs.history import build_job_history

        job = Job.objects.first()
        est = Estimate.objects.create(
            job=job, estimate_number='LINK-EST', version=1, status='draft',
        )
        inv = Invoice.objects.create(job=job, status=Invoice.STATUS_OPEN)
        ship = Shipment.objects.create(job=job, sequence=999)

        _qs, _labels, links = build_job_history(job)
        self.assertEqual(links[('estimate', est.pk)], f'#/estimates/{est.pk}')
        self.assertEqual(links[('invoice', inv.pk)], f'#/invoices/{inv.pk}')
        self.assertEqual(links[('shipment', ship.pk)], f'#/jobs/{job.pk}/shipments')
