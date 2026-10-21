"""An archived job is a read-only historical record: every user-driven mutation
that the inactive-contact freeze refuses is refused for an archived job too,
with the archived sentence. The contact stays ACTIVE throughout, so the
archived branch (not the inactive one) is what fires."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, EmailRecord, TempEmail, User
from apps.jobs.models import Job, RateScheme, Task
from apps.jobs.services import JobService
from tests.base import BaseTestCase
from tests.test_contacts_status import make_business

ARCHIVED = 'is archived'


class ArchivedGuardBase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.biz, self.dc, (self.other,) = make_business('ArcCo')
        self.job = Job.objects.create(
            job_number='ARC-G1', contact=self.other, status=Job.STATUS_ARCHIVED)
        self.scheme = RateScheme.objects.first()
        self.task = Task.objects.create(
            job=self.job, name='T', status=Task.STATUS_COMPLETE,
            qty_source=Task.QTY_ENTERED)
        self.pending = Task(job=self.job, name='P', status=Task.STATUS_PENDING)
        self.pending.stamp_from_scheme(self.scheme)
        self.pending.save()

    def _assert_archived(self, response):
        self.assertEqual(response.status_code, 400, getattr(response, 'data', None))
        self.assertIn(ARCHIVED, response.data.get('detail', ''))


class ArchivedJobGuardTest(ArchivedGuardBase):
    def test_header_patch_refused(self):
        self._assert_archived(self.client.patch(f'/api/jobs/{self.job.pk}/', {'name': 'x'}, format='json'))

    def test_reopen_status_patch_refused(self):
        self._assert_archived(self.client.patch(
            f'/api/jobs/{self.job.pk}/', {'status': Job.STATUS_IN_PROGRESS}, format='json'))

    def test_hold_refused(self):
        self._assert_archived(self.client.post(
            f'/api/jobs/{self.job.pk}/hold/', {'reason': 'x'}, format='json'))

    def test_note_refused(self):
        self._assert_archived(self.client.post(f'/api/jobs/{self.job.pk}/notes/', {'text': 'n'}, format='json'))

    def test_task_add_edit_delete_refused(self):
        self._assert_archived(self.client.post(
            f'/api/jobs/{self.job.pk}/tasks/', {'name': 'New', 'rate_scheme': self.scheme.pk}, format='json'))
        self._assert_archived(self.client.patch(
            f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/', {'name': 'x'}, format='json'))
        self._assert_archived(self.client.delete(f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/'))

    def test_task_complete_refused(self):
        self._assert_archived(self.client.post(f'/api/tasks/{self.pending.pk}/complete/', {}, format='json'))

    def test_blep_start_refused(self):
        self._assert_archived(self.client.post(f'/api/tasks/{self.pending.pk}/start-work/', {}, format='json'))

    def test_blep_create_refused(self):
        now = timezone.now()
        self._assert_archived(self.client.post('/api/bleps/', {
            'task': self.pending.pk,
            'start_time': (now - timedelta(hours=2)).isoformat(),
            'end_time': (now - timedelta(hours=1)).isoformat(),
        }, format='json'))

    def test_delete_job_refused(self):
        self._assert_archived(self.client.delete(f'/api/jobs/{self.job.pk}/'))

    def test_material_add_refused(self):
        self._assert_archived(self.client.post(
            f'/api/jobs/{self.job.pk}/materials/',
            {'description': 'm', 'quantity': '1.00', 'units': 'none', 'unit_cost': '5.00',
             'sell_price': '10.00', 'accounting_category': AccountingCategory.objects.first().pk},
            format='json'))

    def test_contact_swap_carve_out_does_not_apply(self):
        self._assert_archived(self.client.patch(
            f'/api/jobs/{self.job.pk}/', {'contact': self.dc.pk}, format='json'))

    def test_assert_mutable_raises(self):
        with self.assertRaises(ValidationError) as cm:
            JobService.assert_mutable(self.job)
        self.assertIn(ARCHIVED, str(cm.exception))

    def test_duplicate_still_works(self):
        new = JobService.duplicate_job(self.job, contact=self.job.contact, path='estimate')
        self.assertEqual(new.status, Job.STATUS_DRAFT)
        self.assertNotEqual(new.pk, self.job.pk)

    def test_email_link_and_unlink_work(self):
        email = EmailRecord.objects.create(message_id='<arc-1@example.com>', job=None)
        TempEmail.objects.create(
            email_record=email, uid='777', subject='S', from_email='a@example.com',
            to_email='b@example.com', cc_email='', date_sent=timezone.now(),
            is_read=False, is_starred=False, has_attachments=False)
        r = self.client.post(f'/api/emails/{email.pk}/link-to-job/', {'job_id': self.job.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['job'], self.job.pk)
        listing = self.client.get(f'/api/emails/?job={self.job.pk}')
        self.assertEqual([e['email_record_id'] for e in listing.data['results']], [email.pk])
        r = self.client.post(f'/api/emails/{email.pk}/unlink-from-job/')
        self.assertEqual(r.status_code, 200, r.data)


class ArchivedDocumentGuardTest(ArchivedGuardBase):
    def test_estimate_create_refused(self):
        self._assert_archived(self.client.post('/api/estimates/', {'job': self.job.pk}, format='json'))

    def test_change_order_create_refused(self):
        self._assert_archived(self.client.post('/api/change-orders/', {'job': self.job.pk}, format='json'))

    def test_deliverable_create_refused(self):
        self._assert_archived(self.client.post(
            f'/api/jobs/{self.job.pk}/deliverables/',
            {'description': 'd', 'qty_ordered': '1', 'units': 'ea'}, format='json'))

    def test_shipment_create_refused(self):
        self._assert_archived(self.client.post(f'/api/jobs/{self.job.pk}/shipments/', {}, format='json'))

    def test_invoice_open_refused(self):
        self._assert_archived(self.client.post(
            f'/api/jobs/{self.job.pk}/start-invoice-wizard/', {}, format='json'))

    def test_wizard_funnel_refuses(self):
        from apps.estimates.models import Estimate
        from apps.estimates.services import EstimateWizardService
        est = Estimate.objects.create(job=self.job, estimate_number='EST-ARC-1', status=Estimate.STATUS_DRAFT)
        with self.assertRaises(ValidationError) as cm:
            EstimateWizardService.add_atoms_to_new_line_item(est, [{'type': 'task', 'id': self.pending.pk}])
        self.assertIn(ARCHIVED, str(cm.exception))
