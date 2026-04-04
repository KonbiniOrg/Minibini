from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from tests.base import FixtureTestCase
from apps.jobs.models import Job, WorkOrder, Task
from apps.contacts.models import Contact
from apps.estimates.models import Estimate, EstWorksheet
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
        from apps.jobs.services.board_service import BoardService
        job = self._make_job()
        result = BoardService.compute_sub_status(job)
        self.assertEqual(result, 'needs-scoping')

    def test_estimating_when_worksheet_in_draft(self):
        from apps.jobs.services.board_service import BoardService
        job = self._make_job()
        estimate = Estimate.objects.create(
            job=job, estimate_number='EST-TEST-001', status='draft'
        )
        EstWorksheet.objects.create(job=job, estimate=estimate, status='draft')
        result = BoardService.compute_sub_status(job)
        self.assertEqual(result, 'estimating')

    def test_estimate_ready_when_worksheet_final_estimate_draft(self):
        from apps.jobs.services.board_service import BoardService
        job = self._make_job()
        estimate = Estimate.objects.create(
            job=job, estimate_number='EST-TEST-001', status='draft'
        )
        ws = EstWorksheet.objects.create(job=job, estimate=estimate)
        # Force status to final (save() override sets it from estimate)
        EstWorksheet.objects.filter(pk=ws.pk).update(status='final')
        result = BoardService.compute_sub_status(job)
        self.assertEqual(result, 'estimate-ready')

    def test_awaiting_response_when_estimate_open(self):
        from apps.jobs.services.board_service import BoardService
        job = self._make_job(status='submitted')
        Estimate.objects.create(
            job=job, estimate_number='EST-TEST-001', status='open'
        )
        result = BoardService.compute_sub_status(job)
        self.assertEqual(result, 'awaiting-response')


class ApprovedSubStatusTest(FixtureTestCase):
    """Test sub-status derivation for Approved jobs."""

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
            status='approved',
            contact=self.contact,
        )

    def test_needs_work_order_when_none_exists(self):
        from apps.jobs.services.board_service import BoardService
        result = BoardService.compute_sub_status(self.job)
        self.assertEqual(result, 'needs-work-order')

    def test_work_ready_when_wo_exists_no_tasks_started(self):
        from apps.jobs.services.board_service import BoardService
        wo = WorkOrder.objects.create(job=self.job)
        Task.objects.create(name='Task 1', work_order=wo, status='pending')
        result = BoardService.compute_sub_status(self.job)
        self.assertEqual(result, 'work-ready')

    def test_in_progress_when_tasks_in_progress(self):
        from apps.jobs.services.board_service import BoardService
        wo = WorkOrder.objects.create(job=self.job)
        Task.objects.create(name='Task 1', work_order=wo, status='in_progress')
        result = BoardService.compute_sub_status(self.job)
        self.assertEqual(result, 'in-progress')

    def test_blocked_takes_priority_over_in_progress(self):
        from apps.jobs.services.board_service import BoardService
        wo = WorkOrder.objects.create(job=self.job)
        Task.objects.create(name='Task 1', work_order=wo, status='in_progress')
        Task.objects.create(name='Task 2', work_order=wo, status='blocked')
        result = BoardService.compute_sub_status(self.job)
        self.assertEqual(result, 'blocked')

    def test_invoice_prepped_when_wo_complete(self):
        from apps.jobs.services.board_service import BoardService
        from apps.invoicing.models import Invoice
        wo = WorkOrder.objects.create(job=self.job, status='complete')
        Invoice.objects.create(job=self.job, invoice_number='INV-TEST-001', status='draft')
        result = BoardService.compute_sub_status(self.job)
        self.assertEqual(result, 'invoice-prepped')

    def test_invoice_sent_when_invoice_open(self):
        from apps.jobs.services.board_service import BoardService
        from apps.invoicing.models import Invoice
        wo = WorkOrder.objects.create(job=self.job, status='complete')
        Invoice.objects.create(job=self.job, invoice_number='INV-TEST-001', status='open')
        result = BoardService.compute_sub_status(self.job)
        self.assertEqual(result, 'invoice-sent')


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
            username='worker1', password='testpass', first_name='Mike', last_name='Roberts'
        )

    def test_get_board_data_returns_all_sections(self):
        from apps.jobs.services.board_service import BoardService
        data = BoardService.get_board_data()
        self.assertIn('pipeline', data)
        self.assertIn('approved', data)
        self.assertIn('closed', data)
        self.assertIn('jobs', data['approved'])
        self.assertIn('workers', data['approved'])
        self.assertIn('unassigned', data['approved'])

    def test_pipeline_contains_draft_and_submitted_jobs(self):
        from apps.jobs.services.board_service import BoardService
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
        from apps.jobs.services.board_service import BoardService
        Job.objects.create(
            job_number='JOB-APP-001', name='Approved Job',
            status='approved', contact=self.contact,
        )
        data = BoardService.get_board_data()
        self.assertEqual(len(data['approved']['jobs']), 1)
        self.assertEqual(data['approved']['jobs'][0]['name'], 'Approved Job')

    def test_closed_excludes_old_jobs(self):
        from apps.jobs.services.board_service import BoardService
        old_job = Job.objects.create(
            job_number='JOB-OLD-001', name='Old Completed',
            status='completed', contact=self.contact,
        )
        # Manually set completed_date to 30 days ago
        Job.objects.filter(pk=old_job.pk).update(
            completed_date=timezone.now() - timedelta(days=30)
        )

        recent_job = Job.objects.create(
            job_number='JOB-NEW-001', name='Recent Completed',
            status='completed', contact=self.contact,
            completed_date=timezone.now(),
        )
        data = BoardService.get_board_data()
        names = [j['name'] for j in data['closed']]
        self.assertIn('Recent Completed', names)
        self.assertNotIn('Old Completed', names)

    def test_worker_tasks_grouped_by_assignee(self):
        from apps.jobs.services.board_service import BoardService
        job = Job.objects.create(
            job_number='JOB-APP-001', name='Job',
            status='approved', contact=self.contact,
        )
        wo = WorkOrder.objects.create(job=job)
        Task.objects.create(
            name='Assigned task', work_order=wo,
            assignee=self.worker, worker_queue=1,
        )
        Task.objects.create(
            name='Unassigned task', work_order=wo,
        )
        data = BoardService.get_board_data()
        self.assertEqual(len(data['approved']['workers']), 1)
        self.assertEqual(data['approved']['workers'][0]['user']['id'], self.worker.pk)
        self.assertEqual(len(data['approved']['workers'][0]['tasks']), 1)
        self.assertEqual(len(data['approved']['unassigned']), 1)

    def test_available_workers_excludes_assigned(self):
        from apps.jobs.services.board_service import BoardService
        other_worker = User.objects.create_user(
            username='worker2', password='testpass', first_name='Sarah', last_name='Kim'
        )
        job = Job.objects.create(
            job_number='JOB-APP-001', name='Job',
            status='approved', contact=self.contact,
        )
        wo = WorkOrder.objects.create(job=job)
        Task.objects.create(
            name='Assigned task', work_order=wo,
            assignee=self.worker, worker_queue=1,
        )
        data = BoardService.get_board_data()
        available_ids = [w['id'] for w in data['approved']['available_workers']]
        # worker1 has tasks, should NOT be in available
        self.assertNotIn(self.worker.pk, available_ids)
        # worker2 has no tasks, SHOULD be in available
        self.assertIn(other_worker.pk, available_ids)

    def test_jobs_include_sub_status(self):
        from apps.jobs.services.board_service import BoardService
        Job.objects.create(
            job_number='JOB-DRAFT-001', name='Draft Job',
            status='draft', contact=self.contact,
        )
        data = BoardService.get_board_data()
        self.assertIn('sub_status', data['pipeline'][0])
        self.assertEqual(data['pipeline'][0]['sub_status'], 'needs-scoping')


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
        from apps.jobs.services.board_service import BoardService
        self._make_job(status='draft')
        self._make_job(status='submitted')
        self._make_job(status='approved')
        data = BoardService.get_pipeline_data()
        statuses = [j['status'] for j in data]
        self.assertIn('draft', statuses)
        self.assertIn('submitted', statuses)
        self.assertNotIn('approved', statuses)

    def test_get_approved_data_excludes_completed_work_order(self):
        from apps.jobs.services.board_service import BoardService
        job = self._make_job(status='approved')
        WorkOrder.objects.create(job=job, status='complete')
        data = BoardService.get_approved_data()
        job_ids = [j['job_id'] for j in data['jobs']]
        self.assertNotIn(job.job_id, job_ids)

    def test_get_approved_data_excludes_invoice_sent(self):
        from apps.jobs.services.board_service import BoardService
        from apps.invoicing.models import Invoice
        job = self._make_job(status='approved')
        WorkOrder.objects.create(job=job, status='complete')
        Invoice.objects.create(
            job=job, invoice_number='INV-TEST-001', status='open'
        )
        data = BoardService.get_approved_data()
        job_ids = [j['job_id'] for j in data['jobs']]
        self.assertNotIn(job.job_id, job_ids)

    def test_get_unpaid_data_returns_invoice_sent_jobs(self):
        from apps.jobs.services.board_service import BoardService
        from apps.invoicing.models import Invoice
        job = self._make_job(status='approved')
        WorkOrder.objects.create(job=job, status='complete')
        Invoice.objects.create(
            job=job, invoice_number='INV-TEST-001', status='open'
        )
        data = BoardService.get_unpaid_data()
        job_ids = [j['job_id'] for j in data]
        self.assertIn(job.job_id, job_ids)
        match = [j for j in data if j['job_id'] == job.job_id][0]
        self.assertEqual(match['sub_status'], 'invoice-sent')

    def test_get_unpaid_data_returns_needs_invoice_jobs(self):
        from apps.jobs.services.board_service import BoardService
        job = self._make_job(status='approved')
        WorkOrder.objects.create(job=job, status='complete')
        # No invoice at all
        data = BoardService.get_unpaid_data()
        job_ids = [j['job_id'] for j in data]
        self.assertIn(job.job_id, job_ids)
        match = [j for j in data if j['job_id'] == job.job_id][0]
        self.assertEqual(match['sub_status'], 'needs-invoice')

    def test_get_unpaid_data_returns_invoice_prepped_jobs(self):
        from apps.jobs.services.board_service import BoardService
        from apps.invoicing.models import Invoice
        job = self._make_job(status='approved')
        WorkOrder.objects.create(job=job, status='complete')
        Invoice.objects.create(
            job=job, invoice_number='INV-TEST-001', status='draft'
        )
        data = BoardService.get_unpaid_data()
        job_ids = [j['job_id'] for j in data]
        self.assertIn(job.job_id, job_ids)
        match = [j for j in data if j['job_id'] == job.job_id][0]
        self.assertEqual(match['sub_status'], 'invoice-prepped')

    def test_get_closed_data_returns_terminal_jobs(self):
        from apps.jobs.services.board_service import BoardService
        job = self._make_job(status='completed', completed_date=timezone.now())
        data = BoardService.get_closed_data()
        job_ids = [j['job_id'] for j in data]
        self.assertIn(job.job_id, job_ids)

    def test_get_closed_data_respects_retention(self):
        from apps.jobs.services.board_service import BoardService
        old_job = self._make_job(status='completed')
        Job.objects.filter(pk=old_job.pk).update(
            completed_date=timezone.now() - timedelta(days=30)
        )
        recent_job = self._make_job(status='completed', completed_date=timezone.now())
        data = BoardService.get_closed_data()
        job_ids = [j['job_id'] for j in data]
        self.assertIn(recent_job.job_id, job_ids)
        self.assertNotIn(old_job.job_id, job_ids)
