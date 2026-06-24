from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from tests.base import FixtureTestCase
from apps.jobs.models import Job, Task
from apps.contacts.models import Contact
from apps.estimates.models import Estimate, EstWorksheet, EstimateLineItem
from decimal import Decimal
from apps.core.models import Configuration

User = get_user_model()


class PipelineSubStatusTest(FixtureTestCase):
    """Test sub-status derivation for Draft and Submitted jobs."""

    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'}
        )
        self.contact = Contact.objects.first()

    def _make_job(self, status='draft'):
        return Job.objects.create(
            job_number=f'JOB-TEST-{Job.objects.count() + 1:04d}',
            name='Test Job',
            status=status,
            contact=self.contact,
        )

    def test_needs_scoping_when_no_worksheet(self):
        from apps.jobs.services import BoardService
        job = self._make_job()
        result = BoardService.compute_sub_status(job)
        self.assertEqual(result, 'needs-scoping')

    def test_estimating_when_worksheet_in_draft(self):
        from apps.jobs.services import BoardService
        job = self._make_job()
        estimate = Estimate.objects.create(
            job=job, estimate_number='EST-TEST-001', status='draft'
        )
        EstWorksheet.objects.create(job=job)
        result = BoardService.compute_sub_status(job)
        self.assertEqual(result, 'estimating')

    def test_estimating_when_worksheet_present_estimate_draft(self):
        from apps.jobs.services import BoardService
        job = self._make_job()
        Estimate.objects.create(
            job=job, estimate_number='EST-TEST-001', status='draft'
        )
        EstWorksheet.objects.create(job=job)
        result = BoardService.compute_sub_status(job)
        self.assertEqual(result, 'estimating')

    def test_awaiting_response_when_estimate_open(self):
        from apps.jobs.services import BoardService
        job = self._make_job(status='submitted')
        Estimate.objects.create(
            job=job, estimate_number='EST-TEST-001', status='open'
        )
        result = BoardService.compute_sub_status(job)
        self.assertEqual(result, 'awaiting-response')

    def test_estimating_when_draft_estimate_no_worksheet(self):
        from apps.jobs.services import BoardService
        job = self._make_job()
        Estimate.objects.create(
            job=job, estimate_number='EST-TEST-001', status='draft'
        )
        result = BoardService.compute_sub_status(job)
        self.assertEqual(result, 'estimating')

    def test_estimating_when_draft_estimate_with_superseded_sibling(self):
        from apps.jobs.services import BoardService
        job = self._make_job()
        old = Estimate.objects.create(
            job=job, estimate_number='EST-TEST-001', status='draft'
        )
        Estimate.objects.filter(pk=old.pk).update(status='superseded')
        Estimate.objects.create(
            job=job, estimate_number='EST-TEST-001', version=2, status='draft'
        )
        result = BoardService.compute_sub_status(job)
        self.assertEqual(result, 'estimating')

    def test_is_revision_true_for_draft_revision(self):
        """A draft estimate at version > 1 (superseded predecessor) is a re-quote
        in progress — drives the 'Revision' board badge."""
        from apps.jobs.services import BoardService
        job = self._make_job()
        old = Estimate.objects.create(
            job=job, estimate_number='JOB-TEST-0001-1', status='draft')
        Estimate.objects.filter(pk=old.pk).update(status='superseded')
        Estimate.objects.create(
            job=job, estimate_number='JOB-TEST-0001-2', version=2, status='draft')
        self.assertTrue(BoardService.is_revision(job))

    def test_is_revision_false_for_fresh_draft(self):
        from apps.jobs.services import BoardService
        job = self._make_job()
        Estimate.objects.create(
            job=job, estimate_number='JOB-TEST-0001-1', status='draft')
        self.assertFalse(BoardService.is_revision(job))

    def test_is_revision_false_when_live_estimate_open(self):
        from apps.jobs.services import BoardService
        job = self._make_job()
        old = Estimate.objects.create(
            job=job, estimate_number='JOB-TEST-0001-1', status='draft')
        Estimate.objects.filter(pk=old.pk).update(status='superseded')
        v2 = Estimate.objects.create(
            job=job, estimate_number='JOB-TEST-0001-2', version=2, status='draft')
        Estimate.objects.filter(pk=v2.pk).update(status='open')
        self.assertFalse(BoardService.is_revision(job))

    def test_needs_scoping_when_only_terminal_estimate_no_worksheet(self):
        from apps.jobs.services import BoardService
        job = self._make_job()
        est = Estimate.objects.create(
            job=job, estimate_number='EST-TEST-001', status='draft'
        )
        Estimate.objects.filter(pk=est.pk).update(status='rejected')
        result = BoardService.compute_sub_status(job)
        self.assertEqual(result, 'needs-scoping')

    def test_needs_scoping_when_only_terminal_estimate_with_worksheet(self):
        from apps.jobs.services import BoardService
        job = self._make_job()
        est = Estimate.objects.create(
            job=job, estimate_number='EST-TEST-001', status='draft'
        )
        EstWorksheet.objects.create(job=job)
        Estimate.objects.filter(pk=est.pk).update(status='rejected')
        result = BoardService.compute_sub_status(job)
        self.assertEqual(result, 'needs-scoping')


class ApprovedSubStatusTest(FixtureTestCase):
    """Test sub-status derivation for Approved and In Progress jobs.

    'approved' jobs now have the fixed sub-status 'awaiting-prep' (estimate
    accepted, not yet released to floor). 'in_progress' jobs carry the
    task-derived sub-statuses that used to belong to 'approved'.
    """

    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'}
        )
        self.contact = Contact.objects.first()
        self.approved_job = Job.objects.create(
            job_number='JOB-TEST-0001',
            name='Approved Job',
            status=Job.STATUS_APPROVED,
            contact=self.contact,
        )
        self.in_progress_job = Job.objects.create(
            job_number='JOB-TEST-0002',
            name='In Progress Job',
            status=Job.STATUS_IN_PROGRESS,
            contact=self.contact,
        )

    def test_approved_job_has_awaiting_prep_sub_status(self):
        """Approved job (estimate accepted, not yet released) → 'awaiting-prep'."""
        from apps.jobs.services import BoardService
        result = BoardService.compute_sub_status(self.approved_job)
        self.assertEqual(result, 'awaiting-prep')

    def test_needs_tasks_when_no_tasks_exist(self):
        """In Progress Job with no tasks has sub-status 'needs-tasks'."""
        from apps.jobs.services import BoardService
        result = BoardService.compute_sub_status(self.in_progress_job)
        self.assertEqual(result, 'needs-tasks')

    def test_work_ready_when_tasks_pending(self):
        from apps.jobs.services import BoardService
        Task.objects.create(name='Task 1', job=self.in_progress_job, status='pending', service_price_id=1)
        result = BoardService.compute_sub_status(self.in_progress_job)
        self.assertEqual(result, 'work-ready')

    def test_in_progress_when_tasks_in_progress(self):
        from apps.jobs.services import BoardService
        Task.objects.create(name='Task 1', job=self.in_progress_job, status='in_progress', service_price_id=1)
        result = BoardService.compute_sub_status(self.in_progress_job)
        self.assertEqual(result, 'in-progress')

    def test_blocked_takes_priority_over_in_progress(self):
        from apps.jobs.services import BoardService
        Task.objects.create(name='Task 1', job=self.in_progress_job, status='in_progress', service_price_id=1)
        Task.objects.create(name='Task 2', job=self.in_progress_job, status='blocked', service_price_id=1)
        result = BoardService.compute_sub_status(self.in_progress_job)
        self.assertEqual(result, 'blocked')


class WorkCompleteSubStatusTest(FixtureTestCase):
    """Test sub-status derivation for work_complete jobs: invoice lifecycle."""

    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days', defaults={'value': '14'}
        )
        self.contact = Contact.objects.first()
        self.job = Job.objects.create(
            job_number='JOB-WC-0001', name='WC Job',
            status=Job.STATUS_WORK_COMPLETE, contact=self.contact,
        )

    def test_needs_invoice_when_no_invoice(self):
        from apps.jobs.services import BoardService
        self.assertEqual(BoardService.compute_sub_status(self.job), 'needs-invoice')

    def test_invoice_prepped_when_draft_invoice(self):
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice
        Invoice.objects.create(
            job=self.job, invoice_number='INV-WC-DRAFT', status='draft',
        )
        self.assertEqual(
            BoardService.compute_sub_status(self.job), 'invoice-prepped',
        )

    def test_invoice_sent_when_open_invoice(self):
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice
        Invoice.objects.create(
            job=self.job, invoice_number='INV-WC-OPEN', status='open',
        )
        self.assertEqual(
            BoardService.compute_sub_status(self.job), 'invoice-sent',
        )

    def test_invoice_sent_takes_priority_over_invoice_prepped(self):
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice
        Invoice.objects.create(
            job=self.job, invoice_number='INV-WC-DRAFT', status='draft',
        )
        Invoice.objects.create(
            job=self.job, invoice_number='INV-WC-OPEN', status='open',
        )
        self.assertEqual(
            BoardService.compute_sub_status(self.job), 'invoice-sent',
        )

    def test_cancelled_invoices_ignored(self):
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice
        Invoice.objects.create(
            job=self.job, invoice_number='INV-WC-CANCEL', status='cancelled',
        )
        self.assertEqual(
            BoardService.compute_sub_status(self.job), 'needs-invoice',
        )


class InProgressColumnJobsHelperTest(FixtureTestCase):
    """The shared helper defining the board's In Progress column job set,
    reused by both get_approved_data and the schedule chip strip so the two
    never drift."""

    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()

    def test_returns_in_progress_jobs_ordered_by_due_date(self):
        from apps.jobs.services import BoardService
        later = Job.objects.create(
            job_number='JOB-HELP-LATE', name='Late', status='in_progress',
            contact=self.contact, due_date=timezone.now() + timedelta(days=10),
        )
        earlier = Job.objects.create(
            job_number='JOB-HELP-EARLY', name='Early', status='in_progress',
            contact=self.contact, due_date=timezone.now() + timedelta(days=1),
        )
        pks = [j.pk for j in BoardService.in_progress_column_jobs()]
        self.assertIn(earlier.pk, pks)
        self.assertIn(later.pk, pks)
        self.assertLess(pks.index(earlier.pk), pks.index(later.pk))

    def test_excludes_non_in_progress_jobs(self):
        from apps.jobs.services import BoardService
        wc = Job.objects.create(
            job_number='JOB-HELP-WC', name='Done', status='work_complete',
            contact=self.contact,
        )
        pks = [j.pk for j in BoardService.in_progress_column_jobs()]
        self.assertNotIn(wc.pk, pks)


class BoardDataAssemblyTest(FixtureTestCase):
    """Test the full board data assembly."""

    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'}
        )
        self.contact = Contact.objects.first()
        self.worker = User.objects.create_user(
            username='worker1', password='testpass',
            first_name='Mike', last_name='Roberts',
        )

    def test_get_board_data_returns_all_sections(self):
        from apps.jobs.services import BoardService
        data = BoardService.get_board_data()
        self.assertIn('pipeline', data)
        self.assertIn('approved', data)
        self.assertIn('closed', data)
        self.assertIn('jobs', data['approved'])
        self.assertIn('workers', data['approved'])
        self.assertIn('unassigned', data['approved'])

    def test_pipeline_contains_draft_and_submitted_jobs(self):
        from apps.jobs.services import BoardService
        Job.objects.create(
            job_number='JOB-DRAFT-001', name='Draft Job',
            status='draft', contact=self.contact,
        )
        Job.objects.create(
            job_number='JOB-SUB-001', name='Submitted Job',
            status='submitted', contact=self.contact,
        )
        data = BoardService.get_board_data()
        statuses = [j['status'] for j in data['pipeline']]
        self.assertIn('draft', statuses)
        self.assertIn('submitted', statuses)

    def test_in_progress_jobs_in_approved_section(self):
        """in_progress jobs appear in the 'approved' board section (In Progress column)."""
        from apps.jobs.services import BoardService
        Job.objects.create(
            job_number='JOB-INP-001', name='In Progress Job',
            status='in_progress', contact=self.contact,
        )
        data = BoardService.get_board_data()
        approved_names = [j['name'] for j in data['approved']['jobs']]
        self.assertIn('In Progress Job', approved_names)

    def test_approved_jobs_in_pipeline_section(self):
        """approved jobs now appear in the pipeline column."""
        from apps.jobs.services import BoardService
        Job.objects.create(
            job_number='JOB-APP-001', name='Approved Job',
            status='approved', contact=self.contact,
        )
        data = BoardService.get_board_data()
        pipeline_statuses = [j['status'] for j in data['pipeline']]
        self.assertIn('approved', pipeline_statuses)

    def test_closed_includes_recently_rejected_jobs(self):
        """Bug 3: a job rejected within the retention window shows in Closed."""
        from apps.jobs.services import BoardService
        job = Job.objects.create(
            job_number='JOB-REJ-001', name='Rejected Job',
            status='draft', contact=self.contact,
        )
        job.status = 'rejected'
        job.save()
        data = BoardService.get_board_data()
        names = [j['name'] for j in data['closed']]
        self.assertIn('Rejected Job', names)

    def test_closed_excludes_old_jobs(self):
        from apps.jobs.services import BoardService
        old_job = Job.objects.create(
            job_number='JOB-OLD-001', name='Old Completed',
            status='completed', contact=self.contact,
        )
        Job.objects.filter(pk=old_job.pk).update(
            completed_date=timezone.now() - timedelta(days=30)
        )

        Job.objects.create(
            job_number='JOB-NEW-001', name='Recent Completed',
            status='completed', contact=self.contact,
            completed_date=timezone.now(),
        )
        data = BoardService.get_board_data()
        names = [j['name'] for j in data['closed']]
        self.assertIn('Recent Completed', names)
        self.assertNotIn('Old Completed', names)

    def test_worker_tasks_grouped_by_assignee(self):
        from apps.jobs.services import BoardService
        job = Job.objects.create(
            job_number='JOB-APP-WRK', name='Job',
            status='in_progress', contact=self.contact,
        )
        Task.objects.create(
            name='Assigned task', job=job,
            assignee=self.worker, worker_queue=1, service_price_id=1,
            est_worker_time=timedelta(hours=1),
        )
        Task.objects.create(name='Unassigned task', job=job, service_price_id=1)
        data = BoardService.get_board_data()
        self.assertEqual(len(data['approved']['workers']), 1)
        self.assertEqual(data['approved']['workers'][0]['user']['id'], self.worker.pk)
        self.assertEqual(len(data['approved']['workers'][0]['tasks']), 1)
        self.assertEqual(len(data['approved']['unassigned']), 1)

    def test_available_workers_excludes_assigned(self):
        from apps.jobs.services import BoardService
        other_worker = User.objects.create_user(
            username='worker2', password='testpass',
            first_name='Sarah', last_name='Kim',
        )
        job = Job.objects.create(
            job_number='JOB-APP-AV', name='Job',
            status='in_progress', contact=self.contact,
        )
        Task.objects.create(
            name='Assigned task', job=job,
            assignee=self.worker, worker_queue=1, service_price_id=1,
            est_worker_time=timedelta(hours=1),
        )
        data = BoardService.get_board_data()
        available_ids = [w['id'] for w in data['approved']['available_workers']]
        self.assertNotIn(self.worker.pk, available_ids)
        self.assertIn(other_worker.pk, available_ids)

    def test_jobs_include_sub_status(self):
        from apps.jobs.services import BoardService
        Job.objects.create(
            job_number='JOB-DRAFT-SUB', name='Draft Job',
            status='draft', contact=self.contact,
        )
        data = BoardService.get_board_data()
        # pick the one we just created
        item = next(j for j in data['pipeline'] if j['name'] == 'Draft Job')
        self.assertEqual(item['sub_status'], 'needs-scoping')


class LazyBoardMethodsTest(FixtureTestCase):
    """Test lazy board methods that return individual sections."""

    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'}
        )
        self.contact = Contact.objects.first()

    def _make_job(self, status='draft', **kwargs):
        return Job.objects.create(
            job_number=f'JOB-TEST-{Job.objects.count() + 1:04d}',
            name='Test Job',
            status=status,
            contact=self.contact,
            **kwargs,
        )

    def test_get_pipeline_data_returns_draft_submitted_and_approved(self):
        """Pipeline now includes draft, submitted, AND approved jobs."""
        from apps.jobs.services import BoardService
        self._make_job(status='draft')
        self._make_job(status='submitted')
        self._make_job(status='approved')
        data = BoardService.get_pipeline_data()
        statuses = [j['status'] for j in data['jobs']]
        self.assertIn('draft', statuses)
        self.assertIn('submitted', statuses)
        self.assertIn('approved', statuses)

    def test_get_pipeline_data_excludes_in_progress(self):
        """in_progress jobs belong in the In Progress (approved) column, not pipeline."""
        from apps.jobs.services import BoardService
        self._make_job(status='in_progress')
        data = BoardService.get_pipeline_data()
        statuses = [j['status'] for j in data['jobs']]
        self.assertNotIn('in_progress', statuses)

    def test_get_approved_data_only_includes_in_progress(self):
        """In Progress column (get_approved_data) returns only in_progress jobs."""
        from apps.jobs.services import BoardService
        approved_job = self._make_job(status=Job.STATUS_APPROVED)
        in_progress_job = self._make_job(status=Job.STATUS_IN_PROGRESS)
        wc_job = self._make_job(status=Job.STATUS_WORK_COMPLETE)
        data = BoardService.get_approved_data()
        job_ids = [j['job_id'] for j in data['jobs']]
        self.assertIn(in_progress_job.job_id, job_ids)
        self.assertNotIn(approved_job.job_id, job_ids)
        self.assertNotIn(wc_job.job_id, job_ids)

    def test_get_unpaid_data_union_of_work_complete_and_outstanding_invoice(self):
        """Unpaid lane is the UNION of:
          (a) all work_complete jobs (includes those awaiting first invoice), AND
          (b) any-status jobs with an outstanding (non-settled) invoice.

        A work_complete job WITH an outstanding invoice appears (satisfies both).
        A work_complete job WITHOUT any invoice ALSO appears (needs-invoice).
        A completed job WITHOUT an invoice does NOT appear.
        """
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice
        wc_job_with_invoice = self._make_job(status=Job.STATUS_WORK_COMPLETE)
        wc_job_no_invoice = self._make_job(status=Job.STATUS_WORK_COMPLETE)
        completed_no_invoice = self._make_job(
            status=Job.STATUS_COMPLETED, completed_date=timezone.now(),
        )
        Invoice.objects.create(
            job=wc_job_with_invoice, invoice_number='INV-WC-OUT-001', status='open',
        )
        data = BoardService.get_unpaid_data()
        job_ids = [j['job_id'] for j in data['jobs']]
        self.assertIn(wc_job_with_invoice.job_id, job_ids)
        # Regression guard: work_complete job with no invoice must appear (needs-invoice)
        self.assertIn(wc_job_no_invoice.job_id, job_ids)
        self.assertNotIn(completed_no_invoice.job_id, job_ids)

    def test_get_unpaid_data_returns_invoice_sent_jobs(self):
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice
        job = self._make_job(status=Job.STATUS_WORK_COMPLETE)
        Invoice.objects.create(
            job=job, invoice_number='INV-TEST-001', status='open',
        )
        data = BoardService.get_unpaid_data()
        match = next(j for j in data['jobs'] if j['job_id'] == job.job_id)
        self.assertEqual(match['sub_status'], 'invoice-sent')

    def test_get_unpaid_data_includes_work_complete_jobs_without_invoice(self):
        """Regression guard: a work_complete job with no invoice must appear in the
        unpaid lane with sub_status 'needs-invoice' — it's work done awaiting billing."""
        from apps.jobs.services import BoardService
        job = self._make_job(status=Job.STATUS_WORK_COMPLETE)
        data = BoardService.get_unpaid_data()
        job_ids = [j['job_id'] for j in data['jobs']]
        self.assertIn(job.job_id, job_ids)
        card = next(j for j in data['jobs'] if j['job_id'] == job.job_id)
        self.assertEqual(card['sub_status'], 'needs-invoice')

    def test_get_unpaid_data_returns_invoice_prepped_jobs(self):
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice
        job = self._make_job(status=Job.STATUS_WORK_COMPLETE)
        Invoice.objects.create(
            job=job, invoice_number='INV-TEST-001', status='draft',
        )
        data = BoardService.get_unpaid_data()
        match = next(j for j in data['jobs'] if j['job_id'] == job.job_id)
        self.assertEqual(match['sub_status'], 'invoice-prepped')

    def test_cancelled_job_with_outstanding_invoice_appears_in_unpaid(self):
        """A cancelled job with an outstanding (unpaid, non-cancelled) invoice
        appears in the unpaid lane — a billable cancellation must not be lost."""
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice
        cancelled_job = self._make_job(status=Job.STATUS_CANCELLED)
        Invoice.objects.create(
            job=cancelled_job, invoice_number='INV-CANC-001', status='open',
        )
        data = BoardService.get_unpaid_data()
        job_ids = [j['job_id'] for j in data['jobs']]
        self.assertIn(cancelled_job.job_id, job_ids)
        # Serialized card must carry the job's status so the UI can badge it
        card = next(j for j in data['jobs'] if j['job_id'] == cancelled_job.job_id)
        self.assertEqual(card['status'], Job.STATUS_CANCELLED)

    def test_cancelled_job_with_no_invoice_excluded_from_unpaid(self):
        """A cancelled job with no invoice at all does NOT appear in the unpaid lane."""
        from apps.jobs.services import BoardService
        cancelled_job = self._make_job(status=Job.STATUS_CANCELLED)
        data = BoardService.get_unpaid_data()
        job_ids = [j['job_id'] for j in data['jobs']]
        self.assertNotIn(cancelled_job.job_id, job_ids)

    def test_cancelled_job_with_only_paid_invoice_excluded_from_unpaid(self):
        """A cancelled job whose only invoice is paid does NOT appear in the unpaid lane."""
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice
        cancelled_job = self._make_job(status=Job.STATUS_CANCELLED)
        Invoice.objects.create(
            job=cancelled_job, invoice_number='INV-CANC-PAID-001', status='paid',
        )
        data = BoardService.get_unpaid_data()
        job_ids = [j['job_id'] for j in data['jobs']]
        self.assertNotIn(cancelled_job.job_id, job_ids)

    def test_work_complete_job_with_outstanding_invoice_still_appears(self):
        """Regression: a normal work_complete job with an outstanding invoice
        still appears in the unpaid lane after the invoice-driven change."""
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice
        wc_job = self._make_job(status=Job.STATUS_WORK_COMPLETE)
        Invoice.objects.create(
            job=wc_job, invoice_number='INV-WC-REG-001', status='open',
        )
        data = BoardService.get_unpaid_data()
        job_ids = [j['job_id'] for j in data['jobs']]
        self.assertIn(wc_job.job_id, job_ids)

    def test_work_complete_job_with_outstanding_invoice_appears_exactly_once(self):
        """Union with distinct: a work_complete job that also has an outstanding
        invoice satisfies BOTH predicates but must appear only once in the lane."""
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice
        wc_job = self._make_job(status=Job.STATUS_WORK_COMPLETE)
        Invoice.objects.create(
            job=wc_job, invoice_number='INV-WC-ONCE-001', status='open',
        )
        Invoice.objects.create(
            job=wc_job, invoice_number='INV-WC-ONCE-002', status='draft',
        )
        data = BoardService.get_unpaid_data()
        matching = [j for j in data['jobs'] if j['job_id'] == wc_job.job_id]
        self.assertEqual(len(matching), 1, 'Job appeared more than once (missing distinct)')

    def test_get_closed_data_returns_terminal_jobs(self):
        from apps.jobs.services import BoardService
        job = self._make_job(status='completed', completed_date=timezone.now())
        data = BoardService.get_closed_data()
        job_ids = [j['job_id'] for j in data['jobs']]
        self.assertIn(job.job_id, job_ids)

    def test_get_unpaid_data_returns_dict_with_jobs(self):
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice
        job = self._make_job(status=Job.STATUS_WORK_COMPLETE)
        Invoice.objects.create(job=job, invoice_number='INV-DICT-001', status='open')
        data = BoardService.get_unpaid_data()
        self.assertIsInstance(data, dict)
        self.assertIn('jobs', data)

    def test_get_closed_data_respects_retention(self):
        from apps.jobs.services import BoardService
        old_job = self._make_job(status='completed')
        Job.objects.filter(pk=old_job.pk).update(
            completed_date=timezone.now() - timedelta(days=30)
        )
        recent_job = self._make_job(
            status='completed', completed_date=timezone.now(),
        )
        data = BoardService.get_closed_data()
        job_ids = [j['job_id'] for j in data['jobs']]
        self.assertIn(recent_job.job_id, job_ids)
        self.assertNotIn(old_job.job_id, job_ids)


class PipelineDocDataTest(FixtureTestCase):
    """Test that pipeline data includes worksheet and estimate info."""

    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'}
        )
        self.contact = Contact.objects.first()

    def _make_job(self, status='draft'):
        return Job.objects.create(
            job_number=f'JOB-TEST-{Job.objects.count() + 1:04d}',
            name='Test Job',
            status=status,
            contact=self.contact,
        )

    def test_pipeline_job_with_no_docs_has_empty_arrays(self):
        from apps.jobs.services import BoardService
        job = self._make_job()
        result = BoardService.get_pipeline_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        self.assertEqual(job_data['worksheets'], [])
        self.assertEqual(job_data['estimates'], [])

    def test_pipeline_job_includes_worksheet_with_total(self):
        from apps.jobs.services import BoardService
        job = self._make_job()
        estimate = Estimate.objects.create(
            job=job, estimate_number='EST-TEST-001', status='draft'
        )
        EstWorksheet.objects.create(job=job)
        EstimateLineItem.objects.create(
            estimate=estimate, qty=Decimal('2'), price=Decimal('100.00'),
        )
        result = BoardService.get_pipeline_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        self.assertEqual(len(job_data['worksheets']), 1)
        self.assertIsNotNone(job_data['worksheets'][0]['created_date'])
        self.assertIsNotNone(job_data['worksheets'][0]['created_date'])

    def test_pipeline_job_includes_estimate_with_total(self):
        from apps.jobs.services import BoardService
        job = self._make_job()
        estimate = Estimate.objects.create(
            job=job, estimate_number='EST-TEST-002', status='open'
        )
        EstimateLineItem.objects.create(
            estimate=estimate, qty=Decimal('3'), price=Decimal('50.00'),
        )
        result = BoardService.get_pipeline_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        self.assertEqual(len(job_data['estimates']), 1)
        self.assertEqual(job_data['estimates'][0]['status'], 'open')
        self.assertEqual(job_data['estimates'][0]['total'], Decimal('150.00'))


class ClosedDataTest(FixtureTestCase):
    """Test that closed data includes start_date, completed_date, and profitability."""

    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'}
        )
        self.contact = Contact.objects.first()

    def _make_job(self, status='completed'):
        return Job.objects.create(
            job_number=f'JOB-TEST-{Job.objects.count() + 1:04d}',
            name='Test Job', status=status, contact=self.contact,
            start_date=timezone.now() - timedelta(days=30),
            completed_date=timezone.now(),
        )

    def test_closed_job_includes_start_date(self):
        from apps.jobs.services import BoardService
        job = self._make_job()
        result = BoardService.get_closed_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        self.assertIn('start_date', job_data)
        self.assertIsNotNone(job_data['start_date'])

    def test_closed_job_includes_profitability(self):
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice, InvoiceLineItem
        job = self._make_job()
        inv = Invoice.objects.create(
            job=job, invoice_number='INV-TEST-010', status='paid',
        )
        InvoiceLineItem.objects.create(
            invoice=inv, qty=Decimal('1'), price=Decimal('2000.00'),
        )
        result = BoardService.get_closed_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        self.assertEqual(job_data['billed'], Decimal('2000.00'))
        self.assertIn('profit', job_data)


class UnpaidDataTest(FixtureTestCase):
    """Test unpaid data includes invoice details and profitability."""

    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'}
        )
        self.contact = Contact.objects.first()

    def _make_job(self, status=Job.STATUS_WORK_COMPLETE):
        return Job.objects.create(
            job_number=f'JOB-TEST-{Job.objects.count() + 1:04d}',
            name='Test Job', status=status, contact=self.contact,
        )

    def test_unpaid_job_includes_invoices(self):
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice, InvoiceLineItem
        job = self._make_job()
        inv = Invoice.objects.create(
            job=job, invoice_number='INV-TEST-001',
            status='open', sent_date=timezone.now(),
        )
        InvoiceLineItem.objects.create(
            invoice=inv, qty=Decimal('1'), price=Decimal('500.00'),
        )
        result = BoardService.get_unpaid_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        self.assertEqual(len(job_data['invoices']), 1)
        self.assertEqual(job_data['invoices'][0]['status'], 'open')
        self.assertEqual(job_data['invoices'][0]['total'], Decimal('500.00'))

    def test_unpaid_job_includes_profitability(self):
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice, InvoiceLineItem
        job = self._make_job()
        inv = Invoice.objects.create(
            job=job, invoice_number='INV-TEST-002', status='open',
        )
        InvoiceLineItem.objects.create(
            invoice=inv, qty=Decimal('1'), price=Decimal('1000.00'),
        )
        result = BoardService.get_unpaid_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        self.assertIn('billed', job_data)
        self.assertIn('spent', job_data)
        self.assertIn('profit', job_data)
        self.assertEqual(job_data['billed'], Decimal('1000.00'))

    def test_profitability_includes_labor_from_bleps(self):
        from apps.jobs.services import BoardService
        from apps.jobs.models import Blep
        from apps.invoicing.models import Invoice, InvoiceLineItem
        # Labor cost is now blep hours × the average_labor_cost config.
        Configuration.objects.update_or_create(
            key='average_labor_cost', defaults={'value': '25'})
        worker = User.objects.create_user(username='worker', password='test')
        job = self._make_job()
        inv = Invoice.objects.create(
            job=job, invoice_number='INV-TEST-LABOR', status='open',
        )
        InvoiceLineItem.objects.create(
            invoice=inv, qty=Decimal('1'), price=Decimal('500.00'),
        )
        from apps.jobs.models import ServicePrice
        from apps.core.models import AccountingCategory
        cat = AccountingCategory.objects.create(code='LBR-bs', name='lbr-bs')
        scheme = ServicePrice.objects.create(
            name='Hourly-bs', algorithm=ServicePrice.ELAPSED_TIME,
            rate=Decimal('50.00'), unit_label='hours', accounting_category=cat,
        )
        task = Task.objects.create(
            job=job, name='Labor task', status='in_progress',
            service_price=scheme,
        )
        start = timezone.now() - timedelta(hours=2)
        Blep.objects.create(
            task=task, user=worker,
            start_time=start, end_time=start + timedelta(hours=2),
        )
        result = BoardService.get_unpaid_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        # 2hrs * $25/h = $50, with no materials/expenses on the job.
        self.assertEqual(job_data['spent'], Decimal('50.00'))

    def test_unpaid_job_includes_qbo_payment_info(self):
        from apps.jobs.services import BoardService
        from apps.invoicing.models import Invoice, InvoiceLineItem
        job = self._make_job()
        inv = Invoice.objects.create(
            job=job, invoice_number='INV-TEST-003',
            status='partly-paid', qbo_amount_paid=Decimal('200.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=inv, qty=Decimal('1'), price=Decimal('500.00'),
        )
        Invoice.objects.create(
            job=job, invoice_number='INV-TEST-004', status='open',
        )
        result = BoardService.get_unpaid_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        partly_inv = next(
            i for i in job_data['invoices']
            if i['invoice_number'] == 'INV-TEST-003'
        )
        self.assertEqual(partly_inv['amount_paid'], Decimal('200.00'))


class OnHoldBoardTest(FixtureTestCase):
    """Test that on_hold jobs appear in the Pipeline lane with sub_status 'on-hold'."""

    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'}
        )
        self.contact = Contact.objects.first()

    def _make_job(self, status='draft', **kwargs):
        return Job.objects.create(
            job_number=f'JOB-TEST-{Job.objects.count() + 1:04d}',
            name='Test Job',
            status=status,
            contact=self.contact,
            **kwargs,
        )

    def test_on_hold_job_appears_in_pipeline_with_sub_status(self):
        """on_hold job appears in Pipeline lane with sub_status 'on-hold',
        and is absent from the In Progress lane."""
        from apps.jobs.services import BoardService

        # Reach on_hold via a valid transition: approved -> on_hold
        job = self._make_job(status=Job.STATUS_APPROVED)
        Job.objects.filter(pk=job.pk).update(status=Job.STATUS_ON_HOLD)
        job.refresh_from_db()

        # --- sub_status ---
        self.assertEqual(BoardService.compute_sub_status(job), 'on-hold')

        # --- full board: pipeline contains the job ---
        board = BoardService.get_board_data()
        pipeline_ids = [j['job_id'] for j in board['pipeline']]
        self.assertIn(job.job_id, pipeline_ids)

        # --- full board: pipeline entry has correct sub_status ---
        pipeline_entry = next(j for j in board['pipeline'] if j['job_id'] == job.job_id)
        self.assertEqual(pipeline_entry['sub_status'], 'on-hold')

        # --- full board: job is NOT in the In Progress lane ---
        in_progress_ids = [j['job_id'] for j in board['approved']['jobs']]
        self.assertNotIn(job.job_id, in_progress_ids)

        # --- per-lane endpoint: get_pipeline_data includes on_hold ---
        pipeline_data = BoardService.get_pipeline_data()
        pipeline_lane_ids = [j['job_id'] for j in pipeline_data['jobs']]
        self.assertIn(job.job_id, pipeline_lane_ids)

        # --- per-lane endpoint: get_approved_data excludes on_hold ---
        approved_data = BoardService.get_approved_data()
        approved_lane_ids = [j['job_id'] for j in approved_data['jobs']]
        self.assertNotIn(job.job_id, approved_lane_ids)
