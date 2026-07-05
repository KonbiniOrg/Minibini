"""Category-A serializer.save() bypass fixes (2026-07-04 deep sweep).

Every model mutation goes through a Service. These pin the seven holes where
DRF's implicit (or a bare) serializer.save() skipped service-level side
effects, permissions, or invariants:

1. POST /api/shifts/ routes through ShiftService.create (permission +
   enclosure rules) — a worker cannot fabricate another user's shift.
2. DELETE /api/shifts/{id} refuses while it would orphan enclosed bleps.
3. PATCH /api/estimates/{id} status routes through the services
   (mark_open's send-gate; update_status's atomic acceptance).
4. Invoice `status`/`job` are read-only on PATCH (transitions come from the
   cancel action / QBO polling / send flow).
5. Change requests are editable only by their requester, only while pending.
6. Reimbursement batches take no PATCH/PUT at all.
7. Deleting a referenced RateScheme is a friendly 409, not a ProtectedError.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from tests.base import grant_atoms
from apps.contacts.models import Contact
from apps.core.models import (
    AccountingCategory, Shift, ShiftChangeRequest, User,
)
from apps.estimates.models import Estimate, EstimateLineItem
from apps.invoicing.models import Invoice
from apps.jobs.models import Blep, Job, RateScheme, Task


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class ShiftCreateGuardTest(TestCase):
    def setUp(self):
        self.worker = User.objects.create_user(username='sbg_w', password='x')
        self.other = User.objects.create_user(username='sbg_o', password='x')
        self.manager = grant_atoms(
            User.objects.create_user(username='sbg_m', password='x'),
            'can_manage_time')
        self.start = (timezone.now() - timedelta(hours=3)).replace(microsecond=0)
        self.end = (timezone.now() - timedelta(hours=1)).replace(microsecond=0)

    def test_worker_cannot_create_shift_for_another_user(self):
        resp = _client(self.worker).post('/api/shifts/', {
            'user': self.other.pk,
            'start_time': self.start.isoformat(),
            'end_time': self.end.isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertFalse(Shift.objects.filter(user=self.other).exists())

    def test_worker_creates_own_shift(self):
        resp = _client(self.worker).post('/api/shifts/', {
            'user': self.worker.pk,
            'start_time': self.start.isoformat(),
            'end_time': self.end.isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_manager_creates_shift_for_other(self):
        resp = _client(self.manager).post('/api/shifts/', {
            'user': self.other.pk,
            'start_time': self.start.isoformat(),
            'end_time': self.end.isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_user_defaults_to_actor_when_omitted(self):
        resp = _client(self.worker).post('/api/shifts/', {
            'start_time': self.start.isoformat(),
            'end_time': self.end.isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(Shift.objects.filter(user=self.worker).exists())


class ShiftDeleteOrphanGuardTest(TestCase):
    def setUp(self):
        self.manager = grant_atoms(
            User.objects.create_user(username='sbg_dm', password='x'),
            'can_manage_time')
        self.worker = User.objects.create_user(username='sbg_dw', password='x')
        self.cat = AccountingCategory.objects.create(name='sbg', code='SBG')
        self.scheme = RateScheme.objects.create(
            name='S-sbg', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('10'), unit_label='hr', accounting_category=self.cat)
        contact = Contact.objects.create(first_name='S', last_name='G')
        self.job = Job.objects.create(
            job_number='JOB-SBG-1', contact=contact,
            status=Job.STATUS_IN_PROGRESS)
        self.task = Task.objects.create(
            job=self.job, name='t', rate_scheme=self.scheme,
            status=Task.STATUS_IN_PROGRESS)
        now = timezone.now().replace(second=0, microsecond=0)
        self.shift = Shift.objects.create(
            user=self.worker,
            start_time=now - timedelta(hours=8),
            end_time=now - timedelta(hours=1))
        self.blep = Blep.objects.create(
            task=self.task, user=self.worker,
            start_time=now - timedelta(hours=5),
            end_time=now - timedelta(hours=4))

    def test_delete_refused_while_bleps_would_be_orphaned(self):
        resp = _client(self.manager).delete(f'/api/shifts/{self.shift.pk}/')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertTrue(Shift.objects.filter(pk=self.shift.pk).exists())

    def test_delete_allowed_when_another_shift_encloses(self):
        Shift.objects.create(
            user=self.worker,
            start_time=self.shift.start_time - timedelta(hours=1),
            end_time=self.shift.end_time + timedelta(hours=1))
        resp = _client(self.manager).delete(f'/api/shifts/{self.shift.pk}/')
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_delete_allowed_with_no_bleps(self):
        self.blep.delete()
        resp = _client(self.manager).delete(f'/api/shifts/{self.shift.pk}/')
        self.assertEqual(resp.status_code, 200, resp.data)


class EstimateStatusPatchRoutingTest(TestCase):
    def setUp(self):
        self.mgr = grant_atoms(
            User.objects.create_user(username='sbg_em', password='x'),
            'can_manage_jobs')
        self.cat = AccountingCategory.objects.create(name='sbe', code='SBE')
        contact = Contact.objects.create(first_name='E', last_name='S')
        self.job = Job.objects.create(job_number='JOB-SBE-1', contact=contact)
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-SBE-1',
            status=Estimate.STATUS_DRAFT)
        # mark_open's send-gate also requires deliverables on the job.
        from apps.deliverables.models import Deliverable
        Deliverable.objects.create(
            job=self.job, description='W', qty_ordered=Decimal('1'),
            units='ea', sort_order=10)

    def test_patch_to_open_runs_the_send_gate(self):
        # A hand-line without an accounting category must block the send —
        # the gate lives in EstimateService.mark_open, which the PATCH now
        # routes through instead of writing status directly.
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, description='no AC',
            qty=Decimal('1'), price=Decimal('10.00'))
        resp = _client(self.mgr).patch(
            f'/api/estimates/{self.est.pk}/', {'status': 'open'}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        self.est.refresh_from_db()
        self.assertEqual(self.est.status, Estimate.STATUS_DRAFT)

    def test_patch_to_open_succeeds_with_valid_lines(self):
        EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, description='ok',
            qty=Decimal('1'), price=Decimal('10.00'),
            accounting_category=self.cat)
        resp = _client(self.mgr).patch(
            f'/api/estimates/{self.est.pk}/', {'status': 'open'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.est.refresh_from_db()
        self.assertEqual(self.est.status, Estimate.STATUS_OPEN)


class InvoiceStatusReadOnlyTest(TestCase):
    def setUp(self):
        self.fin = grant_atoms(
            User.objects.create_user(username='sbg_f', password='x'),
            'can_manage_financials')
        contact = Contact.objects.create(first_name='I', last_name='V')
        self.job = Job.objects.create(
            job_number='JOB-SBI-1', contact=contact,
            status=Job.STATUS_IN_PROGRESS)
        self.other_job = Job.objects.create(
            job_number='JOB-SBI-2', contact=contact)
        self.inv = Invoice.objects.create(
            job=self.job, invoice_number='INV-SBI-1',
            status=Invoice.STATUS_DRAFT)

    def test_patch_cannot_flip_status_or_job(self):
        resp = _client(self.fin).patch(
            f'/api/invoices/{self.inv.pk}/',
            {'status': 'paid', 'job': self.other_job.pk}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)  # ignored, not error
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, Invoice.STATUS_DRAFT)
        self.assertEqual(self.inv.job_id, self.job.pk)


class ChangeRequestOwnershipTest(TestCase):
    def setUp(self):
        self.requester = User.objects.create_user(username='sbg_r', password='x')
        self.intruder = User.objects.create_user(username='sbg_i', password='x')
        now = timezone.now().replace(second=0, microsecond=0)
        self.req = ShiftChangeRequest.objects.create(
            requester=self.requester,
            requested_start=now - timedelta(hours=40),
            requested_end=now - timedelta(hours=32),
            reason='forgot to clock in')

    def test_non_requester_cannot_edit(self):
        # A non-manager can't even see others' requests (queryset scoping →
        # 404 mask); either way the edit must not land.
        resp = _client(self.intruder).patch(
            f'/api/shift-change-requests/{self.req.pk}/',
            {'reason': 'tampered'}, format='json')
        self.assertIn(resp.status_code, (403, 404), resp.data)
        self.req.refresh_from_db()
        self.assertEqual(self.req.reason, 'forgot to clock in')

    def test_manager_cannot_edit_someone_elses_request(self):
        # Managers SEE every request (review queue) but their verbs are
        # approve/deny — editing the requester's content is tampering.
        manager = grant_atoms(
            User.objects.create_user(username='sbg_cm', password='x'),
            'can_manage_time')
        resp = _client(manager).patch(
            f'/api/shift-change-requests/{self.req.pk}/',
            {'reason': 'manager rewrite'}, format='json')
        self.assertEqual(resp.status_code, 403, resp.data)
        self.req.refresh_from_db()
        self.assertEqual(self.req.reason, 'forgot to clock in')

    def test_requester_edits_own_pending_request(self):
        resp = _client(self.requester).patch(
            f'/api/shift-change-requests/{self.req.pk}/',
            {'reason': 'corrected reason'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.req.refresh_from_db()
        self.assertEqual(self.req.reason, 'corrected reason')

    def test_reviewed_request_is_frozen(self):
        self.req.status = 'denied'
        self.req.save(update_fields=['status'])
        resp = _client(self.requester).patch(
            f'/api/shift-change-requests/{self.req.pk}/',
            {'reason': 'too late'}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)


class ReimbursementNoPatchTest(TestCase):
    def test_patch_method_not_allowed(self):
        fin = grant_atoms(
            User.objects.create_user(username='sbg_rb', password='x'),
            'can_manage_financials')
        resp = _client(fin).patch('/api/reimbursements/1/', {}, format='json')
        self.assertEqual(resp.status_code, 405)


class RateSchemeReferencedDeleteTest(TestCase):
    def test_referenced_delete_is_409_not_500(self):
        admin = grant_atoms(
            User.objects.create_user(username='sbg_rs', password='x'),
            'can_manage_config')
        cat = AccountingCategory.objects.create(name='sbr', code='SBR')
        scheme = RateScheme.objects.create(
            name='S-sbr', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea', accounting_category=cat)
        contact = Contact.objects.create(first_name='R', last_name='S')
        job = Job.objects.create(job_number='JOB-SBR-1', contact=contact)
        Task.objects.create(job=job, name='t', rate_scheme=scheme)
        resp = _client(admin).delete(f'/api/rate-schemes/{scheme.pk}/')
        self.assertEqual(resp.status_code, 409, getattr(resp, 'data', None))
        self.assertTrue(RateScheme.objects.filter(pk=scheme.pk).exists())
