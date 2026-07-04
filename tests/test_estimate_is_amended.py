"""Tests for the derived `is_amended` flag on estimates: true when an estimate
is accepted AND at least one ACCEPTED change order amends it. Surfaced by the
EstimateSerializer and the board pipeline payload so the UI can show "amended"
without re-deriving it client-side. The stored `status` stays `accepted`.
"""
from decimal import Decimal

from rest_framework.test import APIClient

from tests.base import FixtureTestCase
from apps.contacts.models import Contact
from apps.core.models import User
from apps.deliverables.models import Deliverable
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import (
    Estimate, EstimateLineItem, ChangeOrder, ChangeOrderLineItem,
)
from apps.jobs.models import Job
from apps.jobs.services import JobService


def _advance_job_to_on_hold(job):
    for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_ON_HOLD):
        job.status = s
        job.save()
    job.refresh_from_db()


class EstimateIsAmendedSerializerTest(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='C', email='pat@acme.com')
        self.job = JobService.create_job(name='Amend Job', contact=self.contact)
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-AMEND-1', version=1,
            status=Estimate.STATUS_ACCEPTED)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Base', qty=Decimal('1'),
            units='ea', price=Decimal('100'), line_number=1)
        Deliverable.objects.create(
            job=self.job, description='W', qty_ordered=Decimal('1'),
            units='ea', sort_order=10)

    def _is_amended(self):
        r = self.client.get(f'/api/estimates/{self.est.estimate_id}/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('is_amended', r.data)
        return r.data['is_amended']

    def _make_accepted_co(self):
        _advance_job_to_on_hold(self.job)
        co = ChangeOrderService.create(job_id=self.job.pk)
        ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra', qty=Decimal('1'), price=Decimal('50'),
            line_number=1, accounting_category_id=901)
        ChangeOrderService.mark_open(co.pk)
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_ACCEPTED)
        return co

    def test_accepted_estimate_no_co_is_not_amended(self):
        self.assertFalse(self._is_amended())

    def test_accepted_estimate_with_draft_co_is_not_amended(self):
        _advance_job_to_on_hold(self.job)
        ChangeOrderService.create(job_id=self.job.pk)  # draft CO, never accepted
        self.assertFalse(self._is_amended())

    def test_accepted_estimate_with_accepted_co_is_amended(self):
        self._make_accepted_co()
        self.assertTrue(self._is_amended())

    def test_status_field_stays_accepted_when_amended(self):
        self._make_accepted_co()
        r = self.client.get(f'/api/estimates/{self.est.estimate_id}/')
        self.assertEqual(r.data['status'], Estimate.STATUS_ACCEPTED)

    def test_non_accepted_estimate_is_never_amended(self):
        draft = Estimate.objects.create(
            job=Job.objects.create(
                contact=self.contact, job_number='JOB-AMEND-2'),
            estimate_number='EST-AMEND-2', version=1,
            status=Estimate.STATUS_DRAFT)
        r = self.client.get(f'/api/estimates/{draft.estimate_id}/')
        self.assertFalse(r.data['is_amended'])


class BoardPipelineIsAmendedTest(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='C', email='pat@acme.com')
        self.job = JobService.create_job(name='Board Amend Job', contact=self.contact)
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-BAMEND-1', version=1,
            status=Estimate.STATUS_ACCEPTED)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Base', qty=Decimal('1'),
            units='ea', price=Decimal('100'), line_number=1)
        Deliverable.objects.create(
            job=self.job, description='W', qty_ordered=Decimal('1'),
            units='ea', sort_order=10)
        _advance_job_to_on_hold(self.job)
        co = ChangeOrderService.create(job_id=self.job.pk)
        ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra', qty=Decimal('1'), price=Decimal('50'),
            line_number=1, accounting_category_id=901)
        ChangeOrderService.mark_open(co.pk)
        # Accept -> job advances on_hold -> approved (lands in the pipeline panel).
        ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_ACCEPTED)

    def test_pipeline_estimate_carries_is_amended(self):
        r = self.client.get('/api/jobs/board/pipeline/')
        self.assertEqual(r.status_code, 200)
        jobs = r.data['jobs'] if isinstance(r.data, dict) else r.data
        mine = next(j for j in jobs if j['job_id'] == self.job.job_id)
        est_row = next(e for e in mine['estimates']
                       if e['estimate_id'] == self.est.estimate_id)
        self.assertTrue(est_row['is_amended'])
