from tests.base import FixtureTestCase
from apps.jobs.models import Job, WorkOrder, Task
from apps.contacts.models import Contact
from apps.estimates.models import Estimate, EstWorksheet
from apps.core.models import Configuration


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
