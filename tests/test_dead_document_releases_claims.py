"""A rejected or expired estimate / change order releases its atom claims.

Parallel to InvoiceService.cancel (see test_invoice_cancel_releases_claims).
EstimateLineItemSource and ChangeOrderLineItemSource are each globally unique
on (source_type, source_pk), so a dead document that keeps its rows locks its
atoms out of every future document on the same job — permanently, since
rejected/expired are terminal.

Which statuses release, and why:

  rejected / expired  — the document died; nothing was ever promised, so the
                        atoms return to the pool.
  accepted            — NO. The claims ARE the agreement record (what was sold
                        on which line); compose_agreement and the struck-atom
                        derivation read them.
  superseded          — already holds none: revise_estimate re-points the rows
                        onto the new revision rather than copying them.
"""
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItemSource, Estimate, EstimateLineItemSource,
)
from apps.estimates.services import EstimateWizardService
from apps.jobs.models import Job, RateScheme, Task


class DeadDocumentBase(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence',
                                     value='EST-{year}-{counter:04d}')
        AppState.objects.create(key='estimate_counter', value='0')
        self.cat = AccountingCategory.objects.create(code='LAB', name='Labor')
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555')
        self.job = Job.objects.create(
            contact=contact, job_number='JOB-2026-0001',
            status=Job.STATUS_APPROVED)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ENTERED_QTY, rate=Decimal('100'),
            unit_label='hour', accounting_category=self.cat)
        self.task = Task.objects.create(
            job=self.job, name='Cut', rate_scheme=self.scheme,
            est_qty=Decimal('2'))

    def _estimate_claiming_task(self, number='EST-1', status=Estimate.STATUS_OPEN):
        est = Estimate.objects.create(
            job=self.job, estimate_number=number, status=Estimate.STATUS_DRAFT)
        EstimateWizardService.add_atoms_to_new_line_item(
            est, [{'type': 'task', 'id': self.task.pk}])
        # Walk the legal path: draft -> open -> (accepted|rejected|expired).
        # draft -> accepted is not a valid transition.
        if status != Estimate.STATUS_DRAFT:
            if status != Estimate.STATUS_REJECTED:
                est.status = Estimate.STATUS_OPEN
                est.save()
            if status != Estimate.STATUS_OPEN:
                est.status = status
                est.save()
        return est

    def _task_claims(self):
        return EstimateLineItemSource.objects.filter(
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk).count()


class EstimateReleasesClaimsTest(DeadDocumentBase):

    def test_rejecting_an_open_estimate_releases_its_claims(self):
        est = self._estimate_claiming_task()
        self.assertEqual(self._task_claims(), 1)

        est.status = Estimate.STATUS_REJECTED
        est.save()

        self.assertEqual(self._task_claims(), 0)

    def test_expiring_an_open_estimate_releases_its_claims(self):
        est = self._estimate_claiming_task()
        est.status = Estimate.STATUS_EXPIRED
        est.save()
        self.assertEqual(self._task_claims(), 0)

    def test_rejecting_a_draft_estimate_releases_its_claims(self):
        # draft -> rejected is a legal transition; it kills the document just
        # as thoroughly as open -> rejected.
        est = self._estimate_claiming_task(status=Estimate.STATUS_DRAFT)
        est.status = Estimate.STATUS_REJECTED
        est.save()
        self.assertEqual(self._task_claims(), 0)

    def test_a_new_estimate_can_claim_the_atom_after_rejection(self):
        # The bug: rejected is terminal, so without release the atom was
        # locked out of every future estimate on a still-live job.
        est = self._estimate_claiming_task()
        est.status = Estimate.STATUS_REJECTED
        est.save()

        replacement = Estimate.objects.create(
            job=self.job, estimate_number='EST-2', status=Estimate.STATUS_DRAFT)
        li = EstimateWizardService.add_atoms_to_new_line_item(
            replacement, [{'type': 'task', 'id': self.task.pk}])
        self.assertEqual(li.sources.count(), 1)

    def test_rejected_estimate_keeps_its_line_items_as_a_snapshot(self):
        est = self._estimate_claiming_task()
        est.status = Estimate.STATUS_REJECTED
        est.save()
        lines = est.estimatelineitem_set.all()
        self.assertEqual(lines.count(), 1)
        self.assertEqual(lines.first().sources.count(), 0)

    def test_accepting_an_estimate_keeps_its_claims(self):
        # The claims ARE the agreement record — releasing them would erase
        # what was sold on which line.
        est = self._estimate_claiming_task()
        est.status = Estimate.STATUS_ACCEPTED
        est.save()
        self.assertEqual(self._task_claims(), 1)

    def test_rejecting_one_estimate_leaves_another_documents_claims(self):
        other_task = Task.objects.create(
            job=self.job, name='Sand', rate_scheme=self.scheme,
            est_qty=Decimal('1'))
        keeper = Estimate.objects.create(
            job=self.job, estimate_number='EST-K', status=Estimate.STATUS_DRAFT)
        EstimateWizardService.add_atoms_to_new_line_item(
            keeper, [{'type': 'task', 'id': other_task.pk}])

        doomed = self._estimate_claiming_task(number='EST-D')
        doomed.status = Estimate.STATUS_REJECTED
        doomed.save()

        self.assertTrue(EstimateLineItemSource.objects.filter(
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=other_task.pk).exists())


class ChangeOrderReleasesClaimsTest(DeadDocumentBase):
    """Same rule on the CO lens — ChangeOrderLineItemSource carries the
    identical global unique_together."""

    def _co_with_claim(self, status=ChangeOrder.STATUS_OPEN):
        from apps.estimates.models import ChangeOrderLineItem
        accepted = self._estimate_claiming_task(
            number='EST-A', status=Estimate.STATUS_ACCEPTED)
        co = ChangeOrder.objects.create(
            job=self.job, estimate=accepted, status=ChangeOrder.STATUS_DRAFT)
        li = ChangeOrderLineItem.objects.create(
            change_order=co, description='extra', qty=Decimal('1'),
            price=Decimal('50.00'), accounting_category=self.cat,
            action=ChangeOrderLineItem.ACTION_ADD)
        co_task = Task.objects.create(
            job=self.job, name='Extra', rate_scheme=self.scheme,
            est_qty=Decimal('1'))
        ChangeOrderLineItemSource.objects.create(
            change_order_line_item=li,
            source_type=ChangeOrderLineItemSource.SOURCE_TASK,
            source_pk=co_task.pk)
        if status != ChangeOrder.STATUS_DRAFT:
            co.status = status
            co.save()
        return co, co_task

    def _co_claims(self, task):
        return ChangeOrderLineItemSource.objects.filter(
            source_type=ChangeOrderLineItemSource.SOURCE_TASK,
            source_pk=task.pk).count()

    def test_rejecting_a_change_order_releases_its_claims(self):
        co, co_task = self._co_with_claim()
        self.assertEqual(self._co_claims(co_task), 1)

        co.status = ChangeOrder.STATUS_REJECTED
        co.save()

        self.assertEqual(self._co_claims(co_task), 0)

    def test_expiring_a_change_order_releases_its_claims(self):
        co, co_task = self._co_with_claim()
        co.status = ChangeOrder.STATUS_EXPIRED
        co.save()
        self.assertEqual(self._co_claims(co_task), 0)

    def test_accepting_a_change_order_keeps_its_claims(self):
        co, co_task = self._co_with_claim()
        co.status = ChangeOrder.STATUS_ACCEPTED
        co.save()
        self.assertEqual(self._co_claims(co_task), 1)
