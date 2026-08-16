"""TDD tests for answeredness + auto-release (docs/plans/2026-08-15-estimating-structure.md
"The timeline" / "Auto-release" sections) — the acceptance checklist's engine.

`EstimateService.unanswered_lines(estimate)`: plain hand lines still owing a
work decision (no sources, not an adjustment, not a deposit line,
work_declined=False).

`JobService.maybe_auto_release(job)`: approved -> in_progress (system
transition) once every accepted estimate's checklist is fully answered.
Wired at three trigger points: end of acceptance (on_accept), after a mint
claim, after a work_declined flip.

Object graphs are built directly (mirrors tests/test_mint_service.py and
tests/test_work_declined.py) — no fixtures. Scenarios that need job.status
assertions drive REAL Estimate transitions (EstimateService.update_status),
matching tests/test_portal_api.py's PortalApiTest.test_accept_transitions_and_advances_job
pattern, so the estimate_status_changed_for_job / estimate_accepted signal
cascade actually fires (a QuerySet.update() bypass, used elsewhere in this
suite for cheaper single-field arrangement, does NOT fire it).
"""
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.estimates.acceptance import EstimateAcceptanceService
from apps.estimates.mint import MintService
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource, ServiceItem
from apps.estimates.services import EstimateService
from apps.jobs.models import Job, RateScheme, Task
from apps.jobs.services import JobService


class AutoReleaseBase(TestCase):
    """Shared object graph: one AccountingCategory, one Contact, an
    ELAPSED_TIME RateScheme, and helpers to build/accept an estimate."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(
            name='Labor', code='AR-LAB', is_active=True,
        )
        self.deposit_cat = AccountingCategory.objects.create(
            name='Deposit', code='AR-DEP', is_active=True,
            taxable=False, is_deposit=True,
        )
        self.contact = Contact.objects.create(
            first_name='A', last_name='R', email='ar@test.com', mobile_number='555-0200',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly-AR', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100.00'), unit_label='hour', accounting_category=self.cat,
        )

    def _job(self, suffix, status=Job.STATUS_DRAFT):
        return Job.objects.create(
            contact=self.contact, job_number=f'JOB-AR-{suffix}', status=status,
        )

    def _estimate(self, job, suffix):
        return Estimate.objects.create(
            job=job, estimate_number=f'EST-AR-{suffix}', status=Estimate.STATUS_DRAFT,
        )

    def _plain_line(self, estimate, line_number, description='Plain hand line', price='50.00'):
        return EstimateLineItem.objects.create(
            estimate=estimate, line_number=line_number, description=description,
            qty=Decimal('1'), price=Decimal(price), accounting_category=self.cat,
        )

    def _service_item_line(self, estimate, line_number, description='Deferred service'):
        service_item = ServiceItem.objects.create(
            template_name=description, rate_scheme=self.scheme,
        )
        return EstimateLineItem.objects.create(
            estimate=estimate, line_number=line_number, description=description,
            qty=Decimal('1'), price=Decimal('100.00'),
            accounting_category=self.cat, service_item=service_item,
        )

    def _make_task(self, job, name='Atom task'):
        task = Task(job=job, name=name, est_qty=Decimal('1'))
        task.stamp_from_scheme(self.scheme)
        task.save()
        return task

    def _accept_for_real(self, estimate):
        """Drive the REAL draft -> open -> accepted transition so the
        estimate_status_changed_for_job / estimate_accepted signal cascade
        fires (job -> approved, then on_accept crystallization + our new
        auto-release trigger) — not the QuerySet.update() bypass used
        elsewhere in this suite for cheap single-field arrangement."""
        EstimateService.update_status(estimate.pk, Estimate.STATUS_OPEN)
        EstimateService.update_status(estimate.pk, Estimate.STATUS_ACCEPTED)
        estimate.refresh_from_db()
        return estimate


class UnansweredLinesTest(AutoReleaseBase):
    """Direct unit coverage of the answeredness predicate."""

    def setUp(self):
        super().setUp()
        self.job = self._job('UL')
        self.estimate = self._estimate(self.job, 'UL')

    def _accept_bypass(self):
        Estimate.objects.filter(pk=self.estimate.pk).update(status=Estimate.STATUS_ACCEPTED)
        self.estimate.refresh_from_db()

    def test_plain_unanswered_hand_line_is_included(self):
        line = self._plain_line(self.estimate, 1)
        self._accept_bypass()
        self.assertIn(line, list(EstimateService.unanswered_lines(self.estimate)))

    def test_sourced_line_is_excluded(self):
        line = self._plain_line(self.estimate, 1)
        task = self._make_task(self.job)
        EstimateLineItemSource.objects.create(
            estimate_line_item=line,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=task.pk,
        )
        self._accept_bypass()
        self.assertNotIn(line, list(EstimateService.unanswered_lines(self.estimate)))

    def test_adjustment_line_is_excluded(self):
        adj_scheme = RateScheme.objects.create(
            name='Rush 10%-UL', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='%', accounting_category=self.cat,
        )
        adj_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Rush surcharge',
            qty=Decimal('1'), price=Decimal('50.00'),
            adjustment_service=adj_scheme, adjustment_percent=adj_scheme.rate,
        )
        self._accept_bypass()
        self.assertNotIn(adj_line, list(EstimateService.unanswered_lines(self.estimate)))

    def test_deposit_line_is_excluded(self):
        deposit_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Deposit',
            qty=Decimal('1'), price=Decimal('500.00'), accounting_category=self.deposit_cat,
        )
        self._accept_bypass()
        self.assertNotIn(deposit_line, list(EstimateService.unanswered_lines(self.estimate)))

    def test_declined_line_is_excluded(self):
        line = self._plain_line(self.estimate, 1)
        self._accept_bypass()
        line.work_declined = True
        line.save()
        self.assertNotIn(line, list(EstimateService.unanswered_lines(self.estimate)))

    def test_fully_answered_estimate_returns_empty(self):
        line = self._plain_line(self.estimate, 1)
        self._accept_bypass()
        line.work_declined = True
        line.save()
        self.assertFalse(EstimateService.unanswered_lines(self.estimate).exists())


class MaybeAutoReleaseAllCatalogTest(AutoReleaseBase):
    """All-catalog estimate -> accept -> job lands in_progress directly."""

    def test_all_catalog_estimate_releases_at_accept(self):
        job = self._job('CAT')
        estimate = self._estimate(job, 'CAT')
        self._service_item_line(estimate, 1)

        self._accept_for_real(estimate)
        job.refresh_from_db()

        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)
        self.assertTrue(Task.objects.filter(job=job).exists())


class MaybeAutoReleaseMixedTest(AutoReleaseBase):
    """Mixed estimate -> accept -> stays approved -> mint one line -> still
    approved -> decline the last -> in_progress."""

    def test_mixed_checklist_walks_to_release(self):
        job = self._job('MIX')
        estimate = self._estimate(job, 'MIX')
        line1 = self._plain_line(estimate, 1, description='Line one')
        line2 = self._plain_line(estimate, 2, description='Line two')

        self._accept_for_real(estimate)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_APPROVED)

        # Mint an atom onto line1 — line2 still unanswered.
        task = self._make_task(job)
        MintService.claim_atom_for_line(line1, EstimateLineItemSource.SOURCE_TASK, task.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_APPROVED)

        # Decline line2 — the last unanswered line — releases the job.
        EstimateService.update_line_item(line2.pk, work_declined=True)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)


class MaybeAutoReleaseAllDeclinedTest(AutoReleaseBase):
    """All-declined (taskless) estimate releases with zero tasks."""

    def test_all_declined_releases_taskless(self):
        job = self._job('DECL')
        estimate = self._estimate(job, 'DECL')
        line1 = self._plain_line(estimate, 1, description='Line one')
        line2 = self._plain_line(estimate, 2, description='Line two')

        self._accept_for_real(estimate)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_APPROVED)

        EstimateService.update_line_item(line1.pk, work_declined=True)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_APPROVED)  # line2 still unanswered

        EstimateService.update_line_item(line2.pk, work_declined=True)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)
        self.assertEqual(Task.objects.filter(job=job).count(), 0)  # taskless


class MaybeAutoReleaseOnHoldTest(AutoReleaseBase):
    """on_hold job: checklist completion does NOT release (hold wins).
    Release happens via the existing hold-release path (JobService.release_job),
    which does not itself re-check the checklist — read from hold_job/release_job
    (apps/jobs/services.py): release_job only clears the flag and does not
    call maybe_auto_release, so the job stays at its pre-hold status
    (approved) until another trigger fires."""

    def test_decline_while_held_does_not_release(self):
        job = self._job('HOLD')
        estimate = self._estimate(job, 'HOLD')
        line = self._plain_line(estimate, 1)

        self._accept_for_real(estimate)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_APPROVED)

        JobService.hold_job(job.pk, 'customer rethink')
        job.refresh_from_db()
        self.assertTrue(job.on_hold)

        # Answering the last checklist line while held must not raise (the
        # while-held update_job guard would raise on an attempted status
        # write) and must not release the job.
        EstimateService.update_line_item(line.pk, work_declined=True)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_APPROVED)
        self.assertTrue(job.on_hold)

    def test_release_job_does_not_auto_advance(self):
        job = self._job('HOLD2')
        estimate = self._estimate(job, 'HOLD2')
        line = self._plain_line(estimate, 1)

        self._accept_for_real(estimate)
        JobService.hold_job(job.pk, 'customer rethink')
        EstimateService.update_line_item(line.pk, work_declined=True)  # no-op while held

        released = JobService.release_job(job.pk)
        self.assertFalse(released.on_hold)
        # release_job is not one of the three auto-release trigger points —
        # the job resumes at its pre-hold status, not in_progress.
        self.assertEqual(released.status, Job.STATUS_APPROVED)


class MarkWorkStartedUnchangedTest(AutoReleaseBase):
    """Regression pin: mark_work_started's own behavior is untouched by
    auto-release — it still promotes approved -> in_progress unconditionally
    (no checklist check) and still no-ops for any other status."""

    def test_mark_work_started_still_promotes_approved(self):
        job = self._job('MWS', status=Job.STATUS_APPROVED)
        JobService.mark_work_started(job)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)

    def test_mark_work_started_noop_on_draft(self):
        job = self._job('MWS2', status=Job.STATUS_DRAFT)
        JobService.mark_work_started(job)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_DRAFT)


class PreClaimedCatalogLineAcceptanceSkipTest(AutoReleaseBase):
    """CARRIED FINDING (Task 2 review): on_accept's dupe-guard for a
    PRE-CLAIMED catalog line (`if li.sources.exists(): continue`) had no
    regression pin anywhere in the suite. A service_item line whose atom was
    already claimed (e.g. via mint-by-modal before some other path re-drives
    acceptance) must not mint a second Task."""

    def test_preclaimed_service_item_line_mints_no_duplicate_task(self):
        job = self._job('PRECLAIM', status=Job.STATUS_APPROVED)
        estimate = self._estimate(job, 'PRECLAIM')
        line = self._service_item_line(estimate, 1)

        # Pre-seed a source pointing at a manually created Task — simulating
        # an atom already claimed on this line before acceptance runs.
        task = self._make_task(job, name='Pre-existing atom')
        EstimateLineItemSource.objects.create(
            estimate_line_item=line,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=task.pk,
        )

        result = EstimateAcceptanceService.on_accept(estimate)

        self.assertEqual(result['tasks_created'], 0)
        self.assertEqual(Task.objects.filter(job=job).count(), 1)  # no duplicate
