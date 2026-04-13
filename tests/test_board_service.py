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
        EstWorksheet.objects.create(job=job, estimate=estimate, status='draft')
        result = BoardService.compute_sub_status(job)
        self.assertEqual(result, 'estimating')

    def test_estimate_ready_when_worksheet_final_estimate_draft(self):
        from apps.jobs.services import BoardService
        job = self._make_job()
        estimate = Estimate.objects.create(
            job=job, estimate_number='EST-TEST-001', status='draft'
        )
        ws = EstWorksheet.objects.create(job=job, estimate=estimate)
        EstWorksheet.objects.filter(pk=ws.pk).update(status='final')
        result = BoardService.compute_sub_status(job)
        self.assertEqual(result, 'estimate-ready')

    def test_awaiting_response_when_estimate_open(self):
        from apps.jobs.services import BoardService
        job = self._make_job(status='submitted')
        Estimate.objects.create(
            job=job, estimate_number='EST-TEST-001', status='open'
        )
        result = BoardService.compute_sub_status(job)
        self.assertEqual(result, 'awaiting-response')


class ApprovedSubStatusTest(FixtureTestCase):
    """Test sub-status derivation for Approved jobs (tasks live on job)."""

    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'}
        )
        self.contact = Contact.objects.first()
        self.job = Job.objects.create(
            job_number='JOB-TEST-0001',
            name='Approved Job',
            status=Job.STATUS_APPROVED,
            contact=self.contact,
        )

    def test_needs_tasks_when_no_tasks_exist(self):
        """Approved Job with no tasks has sub-status 'needs-tasks'."""
        from apps.jobs.services import BoardService
        result = BoardService.compute_sub_status(self.job)
        self.assertEqual(result, 'needs-tasks')

    def test_work_ready_when_tasks_pending(self):
        from apps.jobs.services import BoardService
        Task.objects.create(name='Task 1', job=self.job, status='pending')
        result = BoardService.compute_sub_status(self.job)
        self.assertEqual(result, 'work-ready')

    def test_in_progress_when_tasks_in_progress(self):
        from apps.jobs.services import BoardService
        Task.objects.create(name='Task 1', job=self.job, status='in_progress')
        result = BoardService.compute_sub_status(self.job)
        self.assertEqual(result, 'in-progress')

    def test_blocked_takes_priority_over_in_progress(self):
        from apps.jobs.services import BoardService
        Task.objects.create(name='Task 1', job=self.job, status='in_progress')
        Task.objects.create(name='Task 2', job=self.job, status='blocked')
        result = BoardService.compute_sub_status(self.job)
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

    def test_approved_jobs_in_approved_section(self):
        from apps.jobs.services import BoardService
        Job.objects.create(
            job_number='JOB-APP-001', name='Approved Job',
            status='approved', contact=self.contact,
        )
        data = BoardService.get_board_data()
        approved_names = [j['name'] for j in data['approved']['jobs']]
        self.assertIn('Approved Job', approved_names)

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
            status='approved', contact=self.contact,
        )
        Task.objects.create(
            name='Assigned task', job=job,
            assignee=self.worker, worker_queue=1,
        )
        Task.objects.create(name='Unassigned task', job=job)
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
            status='approved', contact=self.contact,
        )
        Task.objects.create(
            name='Assigned task', job=job,
            assignee=self.worker, worker_queue=1,
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

    def test_get_pipeline_data_returns_draft_and_submitted(self):
        from apps.jobs.services import BoardService
        self._make_job(status='draft')
        self._make_job(status='submitted')
        self._make_job(status='approved')
        data = BoardService.get_pipeline_data()
        statuses = [j['status'] for j in data['jobs']]
        self.assertIn('draft', statuses)
        self.assertIn('submitted', statuses)
        self.assertNotIn('approved', statuses)

    def test_get_approved_data_only_includes_approved(self):
        """Approved section returns only approved jobs (work_complete goes to unpaid)."""
        from apps.jobs.services import BoardService
        approved_job = self._make_job(status=Job.STATUS_APPROVED)
        wc_job = self._make_job(status=Job.STATUS_WORK_COMPLETE)
        data = BoardService.get_approved_data()
        job_ids = [j['job_id'] for j in data['jobs']]
        self.assertIn(approved_job.job_id, job_ids)
        self.assertNotIn(wc_job.job_id, job_ids)

    def test_get_unpaid_data_only_returns_work_complete_jobs(self):
        """Unpaid view filters strictly on STATUS_WORK_COMPLETE."""
        from apps.jobs.services import BoardService
        approved_job = self._make_job(status=Job.STATUS_APPROVED)
        wc_job = self._make_job(status=Job.STATUS_WORK_COMPLETE)
        completed_job = self._make_job(
            status=Job.STATUS_COMPLETED, completed_date=timezone.now(),
        )
        data = BoardService.get_unpaid_data()
        job_ids = [j['job_id'] for j in data['jobs']]
        self.assertIn(wc_job.job_id, job_ids)
        self.assertNotIn(approved_job.job_id, job_ids)
        self.assertNotIn(completed_job.job_id, job_ids)

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

    def test_get_unpaid_data_returns_needs_invoice_jobs(self):
        from apps.jobs.services import BoardService
        job = self._make_job(status=Job.STATUS_WORK_COMPLETE)
        data = BoardService.get_unpaid_data()
        match = next(j for j in data['jobs'] if j['job_id'] == job.job_id)
        self.assertEqual(match['sub_status'], 'needs-invoice')

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

    def test_get_closed_data_returns_terminal_jobs(self):
        from apps.jobs.services import BoardService
        job = self._make_job(status='completed', completed_date=timezone.now())
        data = BoardService.get_closed_data()
        job_ids = [j['job_id'] for j in data['jobs']]
        self.assertIn(job.job_id, job_ids)

    def test_get_unpaid_data_returns_dict_with_jobs(self):
        from apps.jobs.services import BoardService
        self._make_job(status=Job.STATUS_WORK_COMPLETE)
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
        ws = EstWorksheet.objects.create(
            job=job, estimate=estimate, status='draft'
        )
        EstimateLineItem.objects.create(
            estimate=estimate, qty=Decimal('2'), price=Decimal('100.00'),
        )
        result = BoardService.get_pipeline_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        self.assertEqual(len(job_data['worksheets']), 1)
        self.assertEqual(job_data['worksheets'][0]['status'], 'draft')
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
        worker = User.objects.create_user(username='worker', password='test')
        job = self._make_job()
        inv = Invoice.objects.create(
            job=job, invoice_number='INV-TEST-LABOR', status='open',
        )
        InvoiceLineItem.objects.create(
            invoice=inv, qty=Decimal('1'), price=Decimal('500.00'),
        )
        task = Task.objects.create(
            job=job, name='Labor task',
            status='in_progress', rate=Decimal('50.00'),
        )
        start = timezone.now() - timedelta(hours=2)
        Blep.objects.create(
            task=task, user=worker,
            start_time=start, end_time=start + timedelta(hours=2),
        )
        result = BoardService.get_unpaid_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        # 2hrs * ($50/2) = $50
        self.assertGreaterEqual(job_data['spent'], Decimal('50.00'))

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
