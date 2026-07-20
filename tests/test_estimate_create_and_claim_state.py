"""
Task 3.4 — Create an Estimate on a Job (no worksheet); expose per-atom claim state.

Tests:
  - POST /api/estimates/ {job} creates a draft Estimate directly on the job.
  - Task / Material / Fee in the job detail each expose ``claimed: bool``.
  - ``claimed`` is True iff an EstimateLineItemSource on a *non-superseded*
    estimate references the atom; False otherwise (including when the only
    referencing estimate is SUPERSEDED).
"""
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import AccountingCategory, User
from apps.contacts.models import Contact
from apps.estimates.models import (
    Estimate, EstimateLineItem, EstimateLineItemSource,
)
from apps.jobs.models import Fee, Job, RateScheme, Task
from apps.inventory.models import Material


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_manager(tag):
    user = User.objects.create_user(username=f'mgr_{tag}', password='pw')
    perm = Permission.objects.get(codename='can_manage_jobs')
    user.user_permissions.add(perm)
    return User.objects.get(pk=user.pk)


def _make_estimate_line(estimate, cat, **kwargs):
    defaults = dict(
        description='Line',
        qty=Decimal('1.00'),
        units='ea',
        price=Decimal('10.00'),
        accounting_category=cat,
    )
    defaults.update(kwargs)
    return EstimateLineItem.objects.create(estimate=estimate, **defaults)


# ---------------------------------------------------------------------------
# 1. Create an estimate directly on a job (no worksheet)
# ---------------------------------------------------------------------------

class EstimateCreateOnJobTest(TestCase):
    """POST /api/estimates/ {job} creates a draft estimate without a worksheet."""

    def setUp(self):
        self.user = _make_manager('ect')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        contact = Contact.objects.create(
            first_name='E', last_name='CT', email='ect@test.com',
        )
        self.job = Job.objects.create(
            contact=contact,
            job_number='JOB-ECT-001',
            status=Job.STATUS_DRAFT,
        )

    def test_post_creates_draft_estimate(self):
        """POST /api/estimates/ {job} → 201, status='draft', job FK matches."""
        resp = self.client.post(
            '/api/estimates/',
            {'job': self.job.pk},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['status'], Estimate.STATUS_DRAFT)
        self.assertEqual(resp.data['job'], self.job.pk)

    def test_second_create_rejected_when_live_estimate_exists(self):
        """Creating a second estimate on a job that already has a live estimate returns 400."""
        first = self.client.post('/api/estimates/', {'job': self.job.pk}, format='json')
        self.assertIn(first.status_code, [200, 201])
        second = self.client.post('/api/estimates/', {'job': self.job.pk}, format='json')
        self.assertEqual(second.status_code, 400)

    def test_create_allowed_on_submitted_job(self):
        # Still quoting: a submitted job may start its (first) estimate.
        Job.objects.filter(pk=self.job.pk).update(status=Job.STATUS_SUBMITTED)
        resp = self.client.post('/api/estimates/', {'job': self.job.pk}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_create_rejected_on_job_past_quoting(self):
        # An approved (hand-approved, estimate-less) job is past the
        # estimating phase — a fresh estimate makes no sense there. Same for
        # every later/terminal status.
        for status in (Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS,
                       Job.STATUS_WORK_COMPLETE, Job.STATUS_COMPLETED,
                       Job.STATUS_CANCELLED, Job.STATUS_REJECTED):
            Job.objects.filter(pk=self.job.pk).update(status=status)
            resp = self.client.post('/api/estimates/', {'job': self.job.pk},
                                    format='json')
            self.assertEqual(resp.status_code, 400,
                             f'{status}: {getattr(resp, "data", None)}')
            self.assertEqual(self.job.estimate_set.count(), 0)


# ---------------------------------------------------------------------------
# 2. Per-atom claim state in the job detail
# ---------------------------------------------------------------------------

class AtomClaimStateTest(TestCase):
    """Job detail endpoint exposes claimed: bool on Task, Material, and Fee atoms."""

    def setUp(self):
        self.user = _make_manager('acs')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.cat = AccountingCategory.objects.create(name='ACS-Cat', is_active=True)
        contact = Contact.objects.create(
            first_name='A', last_name='CS', email='acs@test.com',
        )
        self.job = Job.objects.create(
            contact=contact,
            job_number='JOB-ACS-001',
            status=Job.STATUS_DRAFT,
        )
        self.scheme = RateScheme.objects.create(
            name='ACS-Hourly',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100.00'),
            unit_label='hour',
            accounting_category=self.cat,
        )
        self.task = Task.objects.create(
            job=self.job,
            name='ACS Task',
            rate_scheme=self.scheme,
        )
        self.material = Material.objects.create(
            job=self.job,
            description='ACS Material',
            quantity=Decimal('2.00'),
            sell_price=Decimal('20.00'),
            accounting_category=self.cat,
        )
        self.fee = Fee.objects.create(
            job=self.job,
            description='ACS Fee',
            quantity=Decimal('1.00'),
            unit_rate=Decimal('50.00'),
            accounting_category=self.cat,
        )
        # A non-superseded (draft) estimate on the same job
        self.estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-ACS-001',
            version=1,
            status=Estimate.STATUS_DRAFT,
        )

    def _job_detail(self):
        return self.client.get(f'/api/jobs/{self.job.pk}/')

    # ---- unclaimed (baseline) ----

    def test_task_unclaimed_initially(self):
        resp = self._job_detail()
        self.assertEqual(resp.status_code, 200)
        task_data = next(t for t in resp.data['tasks'] if t['task_id'] == self.task.pk)
        self.assertFalse(task_data['claimed'])

    def test_material_unclaimed_initially(self):
        resp = self._job_detail()
        self.assertEqual(resp.status_code, 200)
        mat_data = next(
            m for m in resp.data['materials'] if m['material_id'] == self.material.pk
        )
        self.assertFalse(mat_data['claimed'])

    def test_fee_unclaimed_initially(self):
        resp = self._job_detail()
        self.assertEqual(resp.status_code, 200)
        fee_data = next(f for f in resp.data['fees'] if f['fee_id'] == self.fee.pk)
        self.assertFalse(fee_data['claimed'])

    # ---- claimed after source row created ----

    def test_task_claimed_after_source_row(self):
        """Task becomes claimed once EstimateLineItemSource references it on a live estimate."""
        li = _make_estimate_line(self.estimate, self.cat, description='Task Line',
                                 units='hour', price=Decimal('100.00'))
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        task_data = next(
            t for t in self._job_detail().data['tasks'] if t['task_id'] == self.task.pk
        )
        self.assertTrue(task_data['claimed'])

    def test_material_claimed_after_source_row(self):
        """Material becomes claimed once EstimateLineItemSource references it."""
        li = _make_estimate_line(self.estimate, self.cat, description='Mat Line',
                                 qty=Decimal('2.00'), price=Decimal('20.00'))
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=self.material.pk,
        )
        mat_data = next(
            m for m in self._job_detail().data['materials']
            if m['material_id'] == self.material.pk
        )
        self.assertTrue(mat_data['claimed'])

    def test_fee_claimed_after_source_row(self):
        """Fee becomes claimed once EstimateLineItemSource references it."""
        li = _make_estimate_line(self.estimate, self.cat, description='Fee Line',
                                 price=Decimal('50.00'))
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_FEE,
            source_pk=self.fee.pk,
        )
        fee_data = next(
            f for f in self._job_detail().data['fees'] if f['fee_id'] == self.fee.pk
        )
        self.assertTrue(fee_data['claimed'])

    def test_superseded_estimate_source_does_not_count_as_claimed(self):
        """An atom on a SUPERSEDED estimate shows claimed=False — superseded estimates
        release their atoms to the new revision (which will have its own source rows)."""
        # Manually create a SUPERSEDED estimate with a source row for the task.
        # (In real usage source rows move via revise_estimate; here we test the
        # theoretical edge case that a superseded-estimate source row doesn't claim.)
        superseded = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-ACS-SUPER-001',
            version=0,
            status=Estimate.STATUS_SUPERSEDED,
        )
        # Must bypass Model.clean() to create a superseded estimate directly;
        # use .save() with skip_full_clean workaround via update-after-create.
        # Easier: create as draft then force status to superseded via .save()/update.
        Estimate.objects.filter(pk=superseded.pk).update(
            status=Estimate.STATUS_SUPERSEDED,
        )
        li = EstimateLineItem.objects.create(
            estimate=superseded,
            description='Old line',
            qty=Decimal('1.00'),
            units='hour',
            price=Decimal('100.00'),
            accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        task_data = next(
            t for t in self._job_detail().data['tasks'] if t['task_id'] == self.task.pk
        )
        # Superseded → atom is NOT claimed
        self.assertFalse(task_data['claimed'])
