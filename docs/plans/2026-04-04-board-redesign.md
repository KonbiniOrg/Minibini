# Job Board Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the job board to use 4 collapsible columns (Pipeline, In Progress, Unpaid, Closed) with only one expanded at a time, lazy-loaded data, and richer card content per column.

**Architecture:** The board API splits into 4 lazy endpoints (one per column) instead of a single monolithic endpoint. The frontend replaces the 3-column resizable layout with a collapsible accordion of 4 columns using CSS transitions. Each column has its own card design: Pipeline shows estimate/worksheet info, In Progress keeps the existing chip+worker+task layout, Unpaid shows invoice/payment detail with profitability, Closed shows dates and profitability.

**Tech Stack:** Django REST Framework, Svelte 5 (runes), CSS transitions

**Mockup reference:** `.superpowers/brainstorm/48054-1775322861/content/full-board.html`

---

## File Structure

### Backend (modify)
- `apps/jobs/services/board_service.py` — Split `get_board_data()` into 4 methods: `get_pipeline_data()`, `get_approved_data()`, `get_unpaid_data()`, `get_closed_data()`. Add invoice/payment/profitability serialization for unpaid. Add estimate/worksheet serialization for pipeline. Add profitability and date serialization for closed.
- `apps/api/jobs/board_views.py` — Add 3 new endpoints: `pipeline_view`, `unpaid_view`, `closed_view`. Keep existing `board_view` returning only approved data (rename internally).

### Backend (modify)
- `apps/api/urls.py` — Register new endpoints.

### Frontend (modify)
- `frontend/src/routes/jobs/JobBoardPage.svelte` — Replace 3-column resizable layout with 4 collapsible columns. Remove ResizeHandle imports. Load only the active column's data on expand.

### Frontend (create)
- `frontend/src/components/board/CollapsedTab.svelte` — Reusable collapsed column tab with rotated label.
- `frontend/src/components/board/UnpaidColumn.svelte` — Unpaid column with invoice/payment cards.
- `frontend/src/components/board/UnpaidCard.svelte` — Individual unpaid job card with invoice table.
- `frontend/src/components/board/ClosedCard.svelte` — Individual closed job card with profitability.

### Frontend (modify)
- `frontend/src/components/board/PipelineColumn.svelte` — Add 2-column masonry layout, doc rows for estimate/worksheet, sub-status-colored left borders.
- `frontend/src/components/board/JobCard.svelte` — Add left border colored by sub-status, doc-row slots.
- `frontend/src/components/board/ClosedColumn.svelte` — Replace with 2-column masonry layout using ClosedCard.

### Frontend (delete)
- `frontend/src/components/board/ResizeHandle.svelte` — No longer needed (still used by ApprovedArea internally for worker/unassigned split, so keep for now but remove from JobBoardPage).

### Tests (modify)
- `tests/test_board_service.py` — Add tests for new service methods, unpaid data, profitability calculations, pipeline doc data, closed date/profitability data.
- `tests/test_board_api.py` — Add tests for new endpoints.

---

### Task 1: Backend — Split board service into lazy methods

**Files:**
- Modify: `apps/jobs/services/board_service.py`
- Test: `tests/test_board_service.py`

The existing `get_board_data()` method queries all 3 sections at once. We need to split it into independent methods so columns can be lazy-loaded. The "unpaid" column gets all approved jobs where the work is done (work order complete): `invoice-sent`, `invoice-prepped`, and a new `needs-invoice` sub-status. The "in progress" column keeps only jobs where work is still active (incomplete work order, or no work order yet).

- [ ] **Step 1: Write failing tests for the new service methods**

Add to `tests/test_board_service.py`:

```python
class LazyBoardMethodsTest(FixtureTestCase):
    """Test that individual board section methods return correct data."""

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
        draft = self._make_job(status='draft')
        submitted = self._make_job(status='submitted')
        approved = self._make_job(status='approved')
        result = BoardService.get_pipeline_data()
        job_ids = [j['job_id'] for j in result['jobs']]
        self.assertIn(draft.job_id, job_ids)
        self.assertIn(submitted.job_id, job_ids)
        self.assertNotIn(approved.job_id, job_ids)

    def test_get_approved_data_excludes_completed_work_order(self):
        """Jobs with completed work orders go to unpaid, not in-progress."""
        from apps.jobs.services.board_service import BoardService
        job_active = self._make_job(status='approved')
        wo = WorkOrder.objects.create(job=job_active, status='incomplete')
        Task.objects.create(work_order=wo, name='Task', status='pending')

        job_done = self._make_job(status='approved')
        WorkOrder.objects.create(job=job_done, status='complete')

        result = BoardService.get_approved_data()
        job_ids = [j['job_id'] for j in result['jobs']]
        self.assertIn(job_active.job_id, job_ids)
        self.assertNotIn(job_done.job_id, job_ids)

    def test_get_approved_data_excludes_invoice_sent(self):
        from apps.jobs.services.board_service import BoardService
        from apps.invoicing.models import Invoice
        job_active = self._make_job(status='approved')
        wo = WorkOrder.objects.create(job=job_active, status='incomplete')
        Task.objects.create(work_order=wo, name='Task', status='pending')

        job_invoiced = self._make_job(status='approved')
        Invoice.objects.create(job=job_invoiced, invoice_number='INV-TEST-001', status='open')

        result = BoardService.get_approved_data()
        job_ids = [j['job_id'] for j in result['jobs']]
        self.assertIn(job_active.job_id, job_ids)
        self.assertNotIn(job_invoiced.job_id, job_ids)

    def test_get_unpaid_data_returns_invoice_sent_jobs(self):
        from apps.jobs.services.board_service import BoardService
        from apps.invoicing.models import Invoice
        job = self._make_job(status='approved')
        Invoice.objects.create(job=job, invoice_number='INV-TEST-002', status='open')
        result = BoardService.get_unpaid_data()
        job_ids = [j['job_id'] for j in result['jobs']]
        self.assertIn(job.job_id, job_ids)

    def test_get_unpaid_data_returns_needs_invoice_jobs(self):
        """Approved job with completed work order but no invoice → unpaid."""
        from apps.jobs.services.board_service import BoardService
        job = self._make_job(status='approved')
        WorkOrder.objects.create(job=job, status='complete')
        result = BoardService.get_unpaid_data()
        job_ids = [j['job_id'] for j in result['jobs']]
        self.assertIn(job.job_id, job_ids)
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        self.assertEqual(job_data['sub_status'], 'needs-invoice')

    def test_get_unpaid_data_returns_invoice_prepped_jobs(self):
        """Approved job with completed WO and draft invoice → unpaid."""
        from apps.jobs.services.board_service import BoardService
        from apps.invoicing.models import Invoice
        job = self._make_job(status='approved')
        WorkOrder.objects.create(job=job, status='complete')
        Invoice.objects.create(job=job, invoice_number='INV-TEST-003', status='draft')
        result = BoardService.get_unpaid_data()
        job_ids = [j['job_id'] for j in result['jobs']]
        self.assertIn(job.job_id, job_ids)
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        self.assertEqual(job_data['sub_status'], 'invoice-prepped')

    def test_get_closed_data_returns_terminal_jobs(self):
        from apps.jobs.services.board_service import BoardService
        job = self._make_job(status='completed')
        job.completed_date = timezone.now()
        job.save()
        result = BoardService.get_closed_data()
        job_ids = [j['job_id'] for j in result['jobs']]
        self.assertIn(job.job_id, job_ids)

    def test_get_closed_data_respects_retention(self):
        from apps.jobs.services.board_service import BoardService
        job = self._make_job(status='completed')
        job.completed_date = timezone.now() - timedelta(days=30)
        job.save()
        result = BoardService.get_closed_data()
        job_ids = [j['job_id'] for j in result['jobs']]
        self.assertNotIn(job.job_id, job_ids)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_board_service.LazyBoardMethodsTest -v 2`
Expected: AttributeError — `BoardService` has no attribute `get_pipeline_data`

- [ ] **Step 3: Implement the split service methods**

In `apps/jobs/services/board_service.py`, keep `get_board_data()` for backwards compatibility but add new methods. The key change is that `get_approved_data()` must filter out jobs where work is done (completed work order or open invoice) — those go to `get_unpaid_data()` instead. Also add a new `needs-invoice` sub-status to `_approved_sub_status()` for jobs with completed work orders but no invoice.

First, update `_approved_sub_status()` to add `needs-invoice`. Insert it between the existing `needs-work-order` and `invoice-prepped` checks. The current `invoice-prepped` check fires when `active_wo.status == 'complete'` — change the logic so that if there are no non-cancelled/non-superseded invoices at all, it returns `needs-invoice` instead of `invoice-prepped`:

```python
@staticmethod
def _approved_sub_status(job):
    """Sub-status for Approved jobs."""
    invoices = job.invoice_set.all()
    sent_invoice = invoices.filter(status='open').first()
    if sent_invoice:
        return 'invoice-sent'

    work_orders = job.workorder_set.all()
    if not work_orders.exists():
        return 'needs-work-order'

    active_wo = work_orders.filter(status='incomplete').order_by('-pk').first()
    if not active_wo:
        active_wo = work_orders.order_by('-pk').first()

    if active_wo.status == 'complete':
        # Work is done — check if an invoice exists
        has_invoice = invoices.exclude(
            status__in=['cancelled', 'superseded']
        ).exists()
        if has_invoice:
            return 'invoice-prepped'
        return 'needs-invoice'

    tasks = active_wo.task_set.exclude(
        status__in=[Task.STATUS_COMPLETE, Task.STATUS_CANCELLED]
    )
    if tasks.filter(status=Task.STATUS_BLOCKED).exists():
        return 'blocked'
    if tasks.filter(status=Task.STATUS_IN_PROGRESS).exists():
        return 'in-progress'

    return 'work-ready'
```

The set of sub-statuses that belong to the unpaid column:

```python
UNPAID_SUB_STATUSES = {'invoice-sent', 'invoice-prepped', 'needs-invoice'}
```

Add this as a class constant on `BoardService`.

Then add the new methods:

```python
@staticmethod
def get_pipeline_data():
    """Return pipeline (draft + submitted) jobs."""
    from apps.jobs.models import Job
    pipeline_jobs = Job.objects.filter(
        status__in=['draft', 'submitted']
    ).select_related('contact').order_by('due_date')
    jobs = [BoardService._serialize_job(job) for job in pipeline_jobs]
    return {'jobs': jobs}

@staticmethod
def get_approved_data():
    """Return approved jobs where work is still active (not done/invoiced)."""
    from apps.jobs.models import Job, WorkOrder, Task
    from django.contrib.auth import get_user_model
    User = get_user_model()

    approved_jobs = Job.objects.filter(
        status='approved'
    ).select_related('contact').order_by('due_date')

    # Serialize and compute sub-status, exclude jobs that belong in unpaid
    approved_list = []
    for i, job in enumerate(approved_jobs):
        job_data = BoardService._serialize_job(job)
        if job_data['sub_status'] in BoardService.UNPAID_SUB_STATUSES:
            continue
        job_data['accent_color'] = BoardService.ACCENT_COLORS[
            len(approved_list) % len(BoardService.ACCENT_COLORS)
        ]
        approved_list.append(job_data)

    color_map = {j['job_id']: j['accent_color'] for j in approved_list}
    approved_job_ids = [j['job_id'] for j in approved_list]

    tasks = Task.objects.filter(
        work_order__job_id__in=approved_job_ids,
        work_order__status='incomplete',
    ).exclude(
        status__in=[Task.STATUS_COMPLETE, Task.STATUS_CANCELLED]
    ).select_related(
        'work_order__job', 'assignee'
    ).order_by('worker_queue', 'pk')

    worker_map = {}
    unassigned = []
    for task in tasks:
        task_data = BoardService._serialize_task(task, color_map)
        if task.assignee_id:
            if task.assignee_id not in worker_map:
                worker_map[task.assignee_id] = {
                    'user': BoardService._serialize_user(task.assignee),
                    'tasks': [],
                }
            worker_map[task.assignee_id]['tasks'].append(task_data)
        else:
            unassigned.append(task_data)

    unassigned.sort(key=lambda t: t.get('job_due_date') or '9999-12-31')

    existing_worker_ids = set(worker_map.keys())
    available_users = User.objects.filter(
        is_active=True
    ).exclude(pk__in=existing_worker_ids).order_by('first_name', 'last_name')
    available_workers = [BoardService._serialize_user(u) for u in available_users]

    return {
        'jobs': approved_list,
        'workers': list(worker_map.values()),
        'unassigned': unassigned,
        'available_workers': available_workers,
    }

@staticmethod
def get_unpaid_data():
    """Return approved jobs where work is done (completed WO or invoice exists)."""
    from apps.jobs.models import Job
    approved_jobs = Job.objects.filter(
        status='approved'
    ).select_related('contact').order_by('due_date')

    jobs = []
    for job in approved_jobs:
        sub_status = BoardService._approved_sub_status(job)
        if sub_status in BoardService.UNPAID_SUB_STATUSES:
            jobs.append(BoardService._serialize_unpaid_job(job))

    return {'jobs': jobs}

@staticmethod
def get_closed_data():
    """Return recently closed (completed/rejected/cancelled) jobs."""
    from apps.jobs.models import Job

    retention_days = 14
    try:
        config = Configuration.objects.get(key='board_closed_retention_days')
        retention_days = int(config.value)
    except (Configuration.DoesNotExist, ValueError):
        pass

    cutoff = timezone.now() - timedelta(days=retention_days)

    closed_jobs = Job.objects.filter(
        status__in=['completed', 'rejected', 'cancelled'],
        completed_date__gte=cutoff,
    ).select_related('contact').order_by('-completed_date')

    jobs = [BoardService._serialize_job(job) for job in closed_jobs]
    return {'jobs': jobs}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_board_service.LazyBoardMethodsTest -v 2`
Expected: All 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services/board_service.py tests/test_board_service.py
git commit -m "feat: split BoardService into lazy per-column methods"
```

---

### Task 2: Backend — Add pipeline doc data (worksheets and estimates)

**Files:**
- Modify: `apps/jobs/services/board_service.py`
- Test: `tests/test_board_service.py`

Pipeline cards need to show the latest worksheet and estimate with their status, created_date, and total amount (sum of line item qty * price).

- [ ] **Step 1: Write failing tests**

Add to `tests/test_board_service.py`:

```python
from apps.estimates.models import Estimate, EstWorksheet, EstimateLineItem
from decimal import Decimal


class PipelineDocDataTest(FixtureTestCase):
    """Test that pipeline data includes worksheet and estimate info."""

    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()

    def _make_job(self, status='draft'):
        return Job.objects.create(
            job_number=f'JOB-TEST-{Job.objects.count() + 1:04d}',
            name='Test Job',
            status=status,
            contact=self.contact,
        )

    def test_pipeline_job_with_no_docs_has_empty_arrays(self):
        from apps.jobs.services.board_service import BoardService
        job = self._make_job()
        result = BoardService.get_pipeline_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        self.assertEqual(job_data['worksheets'], [])
        self.assertEqual(job_data['estimates'], [])

    def test_pipeline_job_includes_worksheet_with_total(self):
        from apps.jobs.services.board_service import BoardService
        job = self._make_job()
        estimate = Estimate.objects.create(
            job=job, estimate_number='EST-TEST-001', status='draft'
        )
        ws = EstWorksheet.objects.create(
            job=job, estimate=estimate, status='draft'
        )
        # Worksheets don't have line items directly — estimate does
        EstimateLineItem.objects.create(
            estimate=estimate, qty=Decimal('2'), price=Decimal('100.00'),
        )
        result = BoardService.get_pipeline_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        self.assertEqual(len(job_data['worksheets']), 1)
        self.assertEqual(job_data['worksheets'][0]['status'], 'draft')
        self.assertIsNotNone(job_data['worksheets'][0]['created_date'])

    def test_pipeline_job_includes_estimate_with_total(self):
        from apps.jobs.services.board_service import BoardService
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_board_service.PipelineDocDataTest -v 2`
Expected: KeyError — `worksheets` not in job_data

- [ ] **Step 3: Implement pipeline doc serialization**

Add a `_serialize_pipeline_job` method to `BoardService` and update `get_pipeline_data()`:

```python
@staticmethod
def _serialize_pipeline_job(job):
    """Serialize a pipeline job with worksheet and estimate info."""
    from apps.estimates.models import EstimateLineItem
    data = BoardService._serialize_job(job)

    # Worksheets (most recent first)
    worksheets = []
    for ws in job.estworksheet_set.order_by('-pk'):
        worksheets.append({
            'est_worksheet_id': ws.est_worksheet_id,
            'status': ws.status,
            'created_date': ws.created_date.isoformat() if ws.created_date else None,
        })
    data['worksheets'] = worksheets

    # Estimates with totals
    estimates = []
    for est in job.estimate_set.order_by('-pk'):
        total = EstimateLineItem.objects.filter(estimate=est).aggregate(
            total=models.Sum(models.F('qty') * models.F('price'))
        )['total'] or Decimal('0.00')
        estimates.append({
            'estimate_id': est.estimate_id,
            'estimate_number': est.estimate_number,
            'status': est.status,
            'created_date': est.created_date.isoformat() if est.created_date else None,
            'total': total,
        })
    data['estimates'] = estimates

    return data
```

Add this import at the top of the file:

```python
from decimal import Decimal
from django.db import models
```

Update `get_pipeline_data()` to use the new method:

```python
jobs = [BoardService._serialize_pipeline_job(job) for job in pipeline_jobs]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_board_service.PipelineDocDataTest -v 2`
Expected: All 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services/board_service.py tests/test_board_service.py
git commit -m "feat: add worksheet/estimate data to pipeline board response"
```

---

### Task 3: Backend — Add unpaid invoice/payment/profitability data

**Files:**
- Modify: `apps/jobs/services/board_service.py`
- Test: `tests/test_board_service.py`

Unpaid cards need: invoices with status, terms, due date, amount, payments with paid date and timing. Job-level profitability: total billed (sum of all invoice line items), total spent (sum of PO line items for this job), profit.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_board_service.py`:

```python
from apps.invoicing.models import Invoice, InvoiceLineItem


class UnpaidDataTest(FixtureTestCase):
    """Test that unpaid data includes invoice details and profitability."""

    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()

    def _make_job(self, status='approved'):
        return Job.objects.create(
            job_number=f'JOB-TEST-{Job.objects.count() + 1:04d}',
            name='Test Job',
            status=status,
            contact=self.contact,
        )

    def test_unpaid_job_includes_invoices(self):
        from apps.jobs.services.board_service import BoardService
        job = self._make_job()
        inv = Invoice.objects.create(
            job=job, invoice_number='INV-TEST-001', status='open',
            sent_date=timezone.now(),
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
        from apps.jobs.services.board_service import BoardService
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
        from apps.jobs.services.board_service import BoardService
        from apps.jobs.models import Blep
        from django.contrib.auth import get_user_model
        User = get_user_model()
        worker = User.objects.create_user(username='worker', password='test')

        job = self._make_job()
        inv = Invoice.objects.create(
            job=job, invoice_number='INV-TEST-LABOR', status='open',
        )
        InvoiceLineItem.objects.create(
            invoice=inv, qty=Decimal('1'), price=Decimal('500.00'),
        )
        wo = WorkOrder.objects.create(job=job, status='incomplete')
        task = Task.objects.create(
            work_order=wo, name='Labor task', status='in_progress',
            rate=Decimal('50.00'),  # $50/hr billing, $25/hr cost proxy
        )
        # 2-hour blep
        start = timezone.now() - timedelta(hours=2)
        Blep.objects.create(
            task=task, user=worker,
            start_time=start, end_time=start + timedelta(hours=2),
        )
        result = BoardService.get_unpaid_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        # Spent should include labor: 2hrs * ($50/2) = $50
        self.assertGreaterEqual(job_data['spent'], Decimal('50.00'))

    def test_unpaid_job_includes_qbo_payment_info(self):
        from apps.jobs.services.board_service import BoardService
        job = self._make_job()
        inv = Invoice.objects.create(
            job=job, invoice_number='INV-TEST-003', status='partly-paid',
            qbo_amount_paid=Decimal('200.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=inv, qty=Decimal('1'), price=Decimal('500.00'),
        )
        # Also create an open invoice so the job stays in unpaid
        Invoice.objects.create(
            job=job, invoice_number='INV-TEST-004', status='open',
        )
        result = BoardService.get_unpaid_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        partly_inv = next(i for i in job_data['invoices'] if i['invoice_number'] == 'INV-TEST-003')
        self.assertEqual(partly_inv['amount_paid'], Decimal('200.00'))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_board_service.UnpaidDataTest -v 2`
Expected: KeyError — `invoices` not in job_data

- [ ] **Step 3: Implement unpaid serialization**

Add a `_serialize_unpaid_job` method and a `_compute_profitability` helper to `BoardService`:

```python
@staticmethod
def _compute_profitability(job):
    """Compute billed/spent/profit for a job.

    Spent = PO line item totals + labor cost from bleps.
    Labor cost = sum of (blep elapsed hours * task.rate) for all
    bleps on tasks belonging to this job's work orders.
    """
    from apps.invoicing.models import InvoiceLineItem
    from apps.purchasing.models import PurchaseOrderLineItem
    from apps.jobs.models import Blep

    billed = InvoiceLineItem.objects.filter(
        invoice__job=job
    ).exclude(
        invoice__status__in=['cancelled', 'superseded']
    ).aggregate(
        total=models.Sum(models.F('qty') * models.F('price'))
    )['total'] or Decimal('0.00')

    # Material/purchasing costs
    material_cost = PurchaseOrderLineItem.objects.filter(
        job=job
    ).exclude(
        purchase_order__status='cancelled'
    ).aggregate(
        total=models.Sum(models.F('qty') * models.F('price'))
    )['total'] or Decimal('0.00')

    # Labor costs from time tracking (bleps)
    # TODO: Replace task.rate / 2 with actual User.pay_rate once that
    # field exists. Using half the billing rate as a temporary proxy.
    labor_cost = Decimal('0.00')
    bleps = Blep.objects.filter(
        task__work_order__job=job,
        start_time__isnull=False,
        end_time__isnull=False,
    ).select_related('task')
    for blep in bleps:
        if blep.task.rate:
            elapsed_hours = Decimal(str(
                blep.elapsed.total_seconds() / 3600
            ))
            labor_cost += elapsed_hours * (blep.task.rate / 2)

    spent = material_cost + labor_cost

    return {
        'billed': billed,
        'spent': spent,
        'profit': billed - spent,
    }

@staticmethod
def _serialize_unpaid_job(job):
    """Serialize an unpaid job with invoice details and profitability."""
    data = BoardService._serialize_job(job)

    invoices = []
    for inv in job.invoice_set.exclude(
        status__in=['cancelled', 'superseded']
    ).order_by('created_date'):
        total = inv.invoicelineitem_set.aggregate(
            total=models.Sum(models.F('qty') * models.F('price'))
        )['total'] or Decimal('0.00')
        invoices.append({
            'invoice_id': inv.invoice_id,
            'invoice_number': inv.invoice_number,
            'status': inv.status,
            'total': total,
            'created_date': inv.created_date.isoformat() if inv.created_date else None,
            'sent_date': inv.sent_date.isoformat() if inv.sent_date else None,
            'closed_date': inv.closed_date.isoformat() if inv.closed_date else None,
            'amount_paid': inv.qbo_amount_paid,
        })
    data['invoices'] = invoices

    profitability = BoardService._compute_profitability(job)
    data.update(profitability)

    return data
```

Update `get_unpaid_data()` to use `_serialize_unpaid_job` (the method was already created in Task 1 using `UNPAID_SUB_STATUSES` — this step just adds the richer serialization).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_board_service.UnpaidDataTest -v 2`
Expected: All 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services/board_service.py tests/test_board_service.py
git commit -m "feat: add invoice/payment/profitability data for unpaid board column"
```

---

### Task 4: Backend — Add closed column profitability and date data

**Files:**
- Modify: `apps/jobs/services/board_service.py`
- Test: `tests/test_board_service.py`

Closed cards need: start_date, completed_date, duration, and profitability.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_board_service.py`:

```python
class ClosedDataTest(FixtureTestCase):
    """Test that closed data includes dates and profitability."""

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
            name='Test Job',
            status=status,
            contact=self.contact,
            start_date=timezone.now() - timedelta(days=30),
            completed_date=timezone.now(),
        )

    def test_closed_job_includes_start_date(self):
        from apps.jobs.services.board_service import BoardService
        job = self._make_job()
        result = BoardService.get_closed_data()
        job_data = next(j for j in result['jobs'] if j['job_id'] == job.job_id)
        self.assertIn('start_date', job_data)
        self.assertIsNotNone(job_data['start_date'])

    def test_closed_job_includes_profitability(self):
        from apps.jobs.services.board_service import BoardService
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_board_service.ClosedDataTest -v 2`
Expected: KeyError — `start_date` not in job_data

- [ ] **Step 3: Implement closed serialization**

Add a `_serialize_closed_job` method to `BoardService`:

```python
@staticmethod
def _serialize_closed_job(job):
    """Serialize a closed job with dates and profitability."""
    data = BoardService._serialize_job(job)
    data['start_date'] = job.start_date.isoformat() if job.start_date else None
    profitability = BoardService._compute_profitability(job)
    data.update(profitability)
    return data
```

Update `get_closed_data()` to use it:

```python
jobs = [BoardService._serialize_closed_job(job) for job in closed_jobs]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_board_service.ClosedDataTest -v 2`
Expected: All 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services/board_service.py tests/test_board_service.py
git commit -m "feat: add dates and profitability to closed board column"
```

---

### Task 5: Backend — Add lazy API endpoints

**Files:**
- Modify: `apps/api/jobs/board_views.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_board_api.py`

Add separate endpoints for each column so the frontend can lazy-load.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_board_api.py`:

```python
class LazyBoardEndpointTest(FixtureTestCase):
    """Test individual board column endpoints."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.user = User.objects.create_user(
            username='boarduser', password='testpass'
        )
        self.client.login(username='boarduser', password='testpass')

    def test_pipeline_endpoint_returns_200(self):
        response = self.client.get('/api/jobs/board/pipeline/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('jobs', response.json())

    def test_approved_endpoint_returns_200(self):
        response = self.client.get('/api/jobs/board/approved/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('jobs', response.json())

    def test_unpaid_endpoint_returns_200(self):
        response = self.client.get('/api/jobs/board/unpaid/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('jobs', response.json())

    def test_closed_endpoint_returns_200(self):
        response = self.client.get('/api/jobs/board/closed/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('jobs', response.json())

    def test_endpoints_require_auth(self):
        self.client.logout()
        for path in ['/api/jobs/board/pipeline/', '/api/jobs/board/approved/',
                     '/api/jobs/board/unpaid/', '/api/jobs/board/closed/']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403, f'{path} should require auth')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_board_api.LazyBoardEndpointTest -v 2`
Expected: 404 — endpoints don't exist yet

- [ ] **Step 3: Add new view functions**

In `apps/api/jobs/board_views.py`, add:

```python
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pipeline_view(request):
    """Return pipeline column data."""
    data = BoardService.get_pipeline_data()
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def approved_view(request):
    """Return approved/in-progress column data."""
    data = BoardService.get_approved_data()
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def unpaid_view(request):
    """Return unpaid column data."""
    data = BoardService.get_unpaid_data()
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def closed_view(request):
    """Return closed column data."""
    data = BoardService.get_closed_data()
    return Response(data)
```

- [ ] **Step 4: Register the URL routes**

In `apps/api/urls.py`, find the existing board URL and add the new ones nearby:

```python
path('jobs/board/pipeline/', pipeline_view, name='board-pipeline'),
path('jobs/board/approved/', approved_view, name='board-approved'),
path('jobs/board/unpaid/', unpaid_view, name='board-unpaid'),
path('jobs/board/closed/', closed_view, name='board-closed'),
```

Make sure these are registered BEFORE the existing `jobs/board/` path so they don't get swallowed by it. Update the import at the top to include the new view functions.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_board_api.LazyBoardEndpointTest -v 2`
Expected: All 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/api/jobs/board_views.py apps/api/urls.py tests/test_board_api.py
git commit -m "feat: add lazy-loaded board column API endpoints"
```

---

### Task 6: Frontend — CollapsedTab component

**Files:**
- Create: `frontend/src/components/board/CollapsedTab.svelte`

A reusable component for the collapsed state of a column tab.

- [ ] **Step 1: Create the component**

```svelte
<script>
  let { label, count = null, theme = 'gray', onclick = () => {} } = $props();

  const THEMES = {
    pipeline: { bg: '#e8efff', border: '#60a5fa', text: '#3b82f6' },
    approved: { bg: '#e5f8ec', border: '#4ade80', text: '#16a34a' },
    unpaid:   { bg: '#fef4e5', border: '#f59e0b', text: '#d97706' },
    closed:   { bg: '#f0f0f1', border: '#9ca3af', text: '#6b7280' },
  };

  let colors = $derived(THEMES[theme] || THEMES.gray);
</script>

<div
  class="col-tab"
  style="background:{colors.bg}; border-right: 3px solid {colors.border};"
  {onclick}
  role="button"
  tabindex="0"
  onkeydown={(e) => { if (e.key === 'Enter') onclick(); }}
>
  <span class="tab-label" style="color:{colors.text};">{label}</span>
  {#if count !== null}
    <span class="tab-count">{count}</span>
  {/if}
</div>

<style>
  .col-tab {
    width: 32px; flex-shrink: 0; cursor: pointer; position: relative;
    display: flex; flex-direction: column; align-items: center;
    padding-top: 14px; gap: 8px;
    transition: filter 0.15s;
  }
  .col-tab:hover { filter: brightness(0.95); }
  .tab-label {
    writing-mode: vertical-rl; text-orientation: mixed;
    transform: rotate(180deg);
    font-size: 12px; font-weight: 600; letter-spacing: 0.5px;
    white-space: nowrap; user-select: none;
  }
  .tab-count {
    font-size: 10px; color: #999; writing-mode: horizontal-tb;
  }
</style>
```

- [ ] **Step 2: Verify it builds**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/board/CollapsedTab.svelte
git commit -m "feat: add CollapsedTab component for collapsed board columns"
```

---

### Task 7: Frontend — Redesign JobBoardPage with collapsible columns

**Files:**
- Modify: `frontend/src/routes/jobs/JobBoardPage.svelte`

Replace the 3-column resizable layout with 4 collapsible columns. Only one column expanded at a time. Data is lazy-loaded per column.

- [ ] **Step 1: Rewrite JobBoardPage.svelte**

```svelte
<script>
  import { api } from '../../lib/api.js';
  import { user } from '../../stores/auth.js';
  import CollapsedTab from '../../components/board/CollapsedTab.svelte';
  import PipelineColumn from '../../components/board/PipelineColumn.svelte';
  import ApprovedArea from '../../components/board/ApprovedArea.svelte';
  import UnpaidColumn from '../../components/board/UnpaidColumn.svelte';
  import ClosedColumn from '../../components/board/ClosedColumn.svelte';

  let activeCol = $state('approved');

  // Per-column data and loading state
  let pipelineData = $state(null);
  let approvedData = $state(null);
  let unpaidData = $state(null);
  let closedData = $state(null);

  let pipelineLoading = $state(false);
  let approvedLoading = $state(false);
  let unpaidLoading = $state(false);
  let closedLoading = $state(false);

  let pipelineCount = $state(null);
  let unpaidCount = $state(null);

  async function loadColumn(col) {
    const endpoints = {
      pipeline: '/api/jobs/board/pipeline/',
      approved: '/api/jobs/board/approved/',
      unpaid: '/api/jobs/board/unpaid/',
      closed: '/api/jobs/board/closed/',
    };
    const setLoading = { pipeline: v => pipelineLoading = v, approved: v => approvedLoading = v, unpaid: v => unpaidLoading = v, closed: v => closedLoading = v };
    const setData = {
      pipeline: d => { pipelineData = d; pipelineCount = d.jobs?.length ?? null; },
      approved: d => { approvedData = d; },
      unpaid: d => { unpaidData = d; unpaidCount = d.jobs?.length ?? null; },
      closed: d => { closedData = d; },
    };

    setLoading[col](true);
    try {
      const data = await api.get(endpoints[col]);
      setData[col](data);
    } catch (e) {
      console.error(`Failed to load ${col}:`, e);
    } finally {
      setLoading[col](false);
    }
  }

  function openCol(col) {
    activeCol = col;
    loadColumn(col);
  }

  function canManageJobs() {
    return $user?.permissions?.includes('can_manage_jobs');
  }

  // Load default column on mount
  $effect(() => {
    loadColumn('approved');
  });
</script>

<div class="board-page">
  <div class="board">
    {#if activeCol === 'pipeline'}
      <div class="col-expanded">
        {#if pipelineLoading}
          <p class="loading">Loading pipeline...</p>
        {:else if pipelineData}
          <PipelineColumn jobs={pipelineData.jobs} />
        {/if}
      </div>
    {:else}
      <CollapsedTab label="Pipeline" count={pipelineCount} theme="pipeline" onclick={() => openCol('pipeline')} />
    {/if}

    {#if activeCol === 'approved'}
      <div class="col-expanded">
        {#if approvedLoading}
          <p class="loading">Loading...</p>
        {:else if approvedData}
          <ApprovedArea data={approvedData} canManage={canManageJobs()} onUpdate={() => loadColumn('approved')} />
        {/if}
      </div>
    {:else}
      <CollapsedTab label="In Progress" count={approvedData?.jobs?.length ?? null} theme="approved" onclick={() => openCol('approved')} />
    {/if}

    {#if activeCol === 'unpaid'}
      <div class="col-expanded">
        {#if unpaidLoading}
          <p class="loading">Loading unpaid...</p>
        {:else if unpaidData}
          <UnpaidColumn jobs={unpaidData.jobs} />
        {/if}
      </div>
    {:else}
      <CollapsedTab label="Unpaid" count={unpaidCount} theme="unpaid" onclick={() => openCol('unpaid')} />
    {/if}

    {#if activeCol === 'closed'}
      <div class="col-expanded">
        {#if closedLoading}
          <p class="loading">Loading closed...</p>
        {:else if closedData}
          <ClosedColumn jobs={closedData.jobs} />
        {/if}
      </div>
    {:else}
      <CollapsedTab label="Closed" theme="closed" onclick={() => openCol('closed')} />
    {/if}
  </div>
</div>

<style>
  .board-page {
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .board {
    display: flex;
    flex: 1;
    overflow: hidden;
  }
  .col-expanded {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    animation: expand 0.18s ease-in-out;
  }
  @keyframes expand {
    from { opacity: 0.5; }
    to { opacity: 1; }
  }
  .loading {
    padding: 20px;
    text-align: center;
    color: #999;
  }
</style>
```

- [ ] **Step 2: Verify it builds**

Run: `cd frontend && npm run build`
Expected: Build succeeds (UnpaidColumn and ClosedColumn will be created in subsequent tasks — if build fails due to missing imports, create placeholder files first).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/jobs/JobBoardPage.svelte
git commit -m "feat: replace board layout with collapsible columns and lazy loading"
```

---

### Task 8: Frontend — Redesign PipelineColumn with masonry and doc rows

**Files:**
- Modify: `frontend/src/components/board/PipelineColumn.svelte`
- Modify: `frontend/src/components/board/JobCard.svelte`

Update Pipeline to use 2-column masonry layout. Add worksheet/estimate doc rows to JobCard. Color left border by sub-status.

- [ ] **Step 1: Update JobCard to support left border color and doc rows**

Rewrite `frontend/src/components/board/JobCard.svelte`:

```svelte
<script>
  let { job, docs = [] } = $props();

  const SUB_STATUS_STYLES = {
    'needs-scoping':     { bg: '#f1f5f9', color: '#64748b' },
    'estimating':        { bg: '#dbeafe', color: '#2563eb' },
    'estimate-ready':    { bg: '#e0e7ff', color: '#4338ca' },
    'awaiting-response': { bg: '#fef3c7', color: '#b45309' },
    'completed':         { bg: '#f3e8ff', color: '#7c3aed' },
    'rejected':          { bg: '#fee2e2', color: '#b91c1c' },
    'cancelled':         { bg: '#f1f5f9', color: '#64748b' },
  };

  const BORDER_COLORS = {
    'needs-scoping': '#64748b',
    'estimating': '#2563eb',
    'estimate-ready': '#4338ca',
    'awaiting-response': '#b45309',
    'completed': '#7c3aed',
    'rejected': '#b91c1c',
    'cancelled': '#64748b',
  };

  function pillLabel(subStatus) {
    if (!subStatus) return job.status;
    return subStatus.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  function pillStyle(subStatus) {
    const key = subStatus || job.status;
    const s = SUB_STATUS_STYLES[key];
    if (!s) return '';
    return `background:${s.bg}; color:${s.color};`;
  }

  function borderColor() {
    const key = job.sub_status || job.status;
    return BORDER_COLORS[key] || '#94a3b8';
  }

  function deadlineClass() {
    if (!job.due_date) return '';
    const due = new Date(job.due_date);
    const now = new Date();
    const daysLeft = (due - now) / (1000 * 60 * 60 * 24);
    if (daysLeft < 0) return 'overdue';
    if (daysLeft < 7) return 'soon';
    return '';
  }

  function deadlineText() {
    if (job.completed_date) {
      const label = job.status === 'rejected' ? 'Rejected' : job.status === 'cancelled' ? 'Cancelled' : 'Completed';
      return `${label} ${new Date(job.completed_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
    }
    if (!job.due_date) return '';
    const due = new Date(job.due_date);
    const now = new Date();
    if (due < now) {
      return `Overdue — was ${due.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
    }
    return `Due ${due.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
  }

  function formatDate(isoDate) {
    if (!isoDate) return '';
    return new Date(isoDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function formatAmount(amount) {
    if (amount == null) return '';
    return Number(amount).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  }

  const DOC_PILL_STYLES = {
    'draft': 'doc-pill-draft',
    'final': 'doc-pill-final',
    'open': 'doc-pill-open',
  };
</script>

<div class="job-card" style="border-left-color: {borderColor()};">
  <div class="card-top">
    <span class="card-number">{job.job_number}</span>
    {#if job.sub_status || job.status}
      <span class="card-substatus" style={pillStyle(job.sub_status)}>{pillLabel(job.sub_status)}</span>
    {/if}
  </div>
  <div class="card-body">
    <div class="card-name">{job.name}</div>
    {#if job.contact_name}
      <a class="card-customer" href="#/contacts/{job.contact_id}">{job.contact_name}</a>
    {/if}
    {#if deadlineText()}
      <div class="card-deadline {deadlineClass()}">{deadlineText()}</div>
    {/if}
  </div>
  {#each docs as doc}
    <div class="doc-row">
      <span class="doc-type">{doc.type}</span>
      <span class="doc-pill {DOC_PILL_STYLES[doc.status] || ''}">{doc.statusLabel}</span>
      <span class="doc-date">{formatDate(doc.created_date)}</span>
      <span class="doc-amount">{formatAmount(doc.total)}</span>
    </div>
  {/each}
</div>

<style>
  .job-card {
    background: #fff; border-radius: 10px; overflow: hidden; cursor: pointer;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06); transition: transform 0.1s, box-shadow 0.15s;
    border-left: 4px solid #94a3b8;
  }
  .job-card:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
  .card-top { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px 0; margin-bottom: 6px; }
  .card-number { font-size: 11px; color: #999; font-family: 'SF Mono', 'Fira Code', monospace; }
  .card-substatus { font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: 600; white-space: nowrap; }
  .card-body { padding: 0 12px 8px; }
  .card-name { font-size: 14px; font-weight: 600; line-height: 1.3; margin-bottom: 3px; }
  .card-customer { font-size: 12px; color: #2563eb; text-decoration: none; display: inline-block; }
  .card-customer:hover { text-decoration: underline; }
  .card-deadline { font-size: 11px; color: #888; margin-top: 6px; }
  .card-deadline.overdue { color: #dc2626; font-weight: 600; }
  .card-deadline.soon { color: #d97706; }

  .doc-row {
    display: flex; align-items: center; gap: 6px; padding: 5px 12px;
    font-size: 11px; color: #666; background: #f8f9fb; border-top: 1px solid #f0f0f0;
  }
  .doc-type { font-weight: 600; color: #555; min-width: 68px; }
  .doc-pill { font-size: 9px; padding: 1px 6px; border-radius: 8px; font-weight: 600; }
  .doc-pill-draft { background: #f1f5f9; color: #64748b; }
  .doc-pill-final { background: #dcfce7; color: #15803d; }
  .doc-pill-open { background: #fef3c7; color: #b45309; }
  .doc-date { font-size: 10px; color: #999; }
  .doc-amount { margin-left: auto; font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; color: #333; }
</style>
```

- [ ] **Step 2: Update PipelineColumn to use masonry layout and pass doc rows**

Rewrite `frontend/src/components/board/PipelineColumn.svelte`:

```svelte
<script>
  import JobCard from './JobCard.svelte';
  let { jobs = [] } = $props();

  function buildDocs(job) {
    const docs = [];
    if (job.worksheets) {
      for (const ws of job.worksheets) {
        docs.push({
          type: 'Worksheet',
          status: ws.status,
          statusLabel: ws.status === 'final' ? 'Final' : 'Draft',
          created_date: ws.created_date,
          total: null,
        });
      }
    }
    if (job.estimates) {
      for (const est of job.estimates) {
        docs.push({
          type: 'Estimate',
          status: est.status === 'open' ? 'open' : 'draft',
          statusLabel: est.status === 'open' ? 'Sent' : 'Draft',
          created_date: est.created_date,
          total: est.total,
        });
      }
    }
    return docs;
  }
</script>

<div class="column-header">
  <strong>Pipeline</strong>
  <span class="count">{jobs.length}</span>
</div>
<div class="column-body">
  {#each jobs as job (job.job_id)}
    <a href="#/jobs/{job.job_id}" class="card-link">
      <JobCard {job} docs={buildDocs(job)} />
    </a>
  {/each}
  {#if jobs.length === 0}
    <p class="empty">No jobs in pipeline</p>
  {/if}
</div>

<style>
  .column-header { padding: 14px 16px 10px; display: flex; align-items: center; justify-content: center; gap: 10px; border-bottom: 3px solid #60a5fa; flex-shrink: 0; }
  .count { font-size: 12px; color: #999; }
  .column-body { flex: 1; overflow-y: auto; padding: 12px; background: #f0f5ff; columns: 2; column-gap: 10px; }
  .card-link { text-decoration: none; color: inherit; display: block; break-inside: avoid; margin-bottom: 10px; }
  .empty { font-size: 13px; color: #999; text-align: center; padding: 20px 0; }
</style>
```

- [ ] **Step 3: Verify it builds**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/board/PipelineColumn.svelte frontend/src/components/board/JobCard.svelte
git commit -m "feat: redesign Pipeline column with masonry layout and doc rows"
```

---

### Task 9: Frontend — UnpaidColumn and UnpaidCard components

**Files:**
- Create: `frontend/src/components/board/UnpaidColumn.svelte`
- Create: `frontend/src/components/board/UnpaidCard.svelte`

Two-column masonry layout of cards showing invoice/payment detail with profitability.

- [ ] **Step 1: Create UnpaidCard component**

Create `frontend/src/components/board/UnpaidCard.svelte`:

```svelte
<script>
  let { job } = $props();

  function formatAmount(amount) {
    if (amount == null) return '$0.00';
    return Number(amount).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  }

  function formatDate(isoDate) {
    if (!isoDate) return '';
    return new Date(isoDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function hasOverdue() {
    return job.invoices?.some(inv => {
      if (inv.status === 'paid') return false;
      if (!inv.sent_date) return false;
      // TODO: proper due date calculation would need payment terms
      // For now check if invoice is open and past a reasonable date
      return inv.status === 'open' || inv.status === 'partly-paid';
    }) || false;
  }

  function invoiceStatusPill(inv) {
    if (inv.status === 'paid') return { label: 'Paid', cls: 'paid' };
    if (inv.status === 'partly-paid') return { label: 'Partly Paid', cls: 'partly' };
    if (inv.status === 'open') return { label: 'Unpaid', cls: 'open' };
    return { label: inv.status, cls: '' };
  }

  function amountClass(inv) {
    if (inv.status === 'paid') return 'amt-paid';
    return 'amt-owing';
  }

  function paymentRows(inv) {
    if (!inv.amount_paid || Number(inv.amount_paid) === 0) return [];
    return [{
      date: inv.closed_date || inv.sent_date,
      amount: inv.amount_paid,
    }];
  }

  let totalDue = $derived(() => {
    if (!job.invoices) return 0;
    return job.invoices.reduce((sum, inv) => {
      if (inv.status === 'paid' || inv.status === 'cancelled') return sum;
      const total = Number(inv.total) || 0;
      const paid = Number(inv.amount_paid) || 0;
      return sum + total - paid;
    }, 0);
  });

  let invoiceCount = $derived(job.invoices?.length || 0);
  let paymentCount = $derived(job.invoices?.filter(i => i.amount_paid && Number(i.amount_paid) > 0).length || 0);
</script>

<div class="unpaid-card" class:has-overdue={hasOverdue()} class:needs-inv={job.sub_status === 'needs-invoice'}>
  <div class="card-head">
    <div class="card-head-top">
      <span class="job-name">{job.name}</span>
      <span class="profit">
        Billed <span class="val">{formatAmount(job.billed)}</span>
        Spent <span class="val">{formatAmount(job.spent)}</span>
        Profit <span class="val" class:green={Number(job.profit) >= 0} class:red={Number(job.profit) < 0}>{formatAmount(job.profit)}</span>
      </span>
    </div>
    <div class="card-head-sub">
      <a class="customer" href="#/contacts/{job.contact_id}">{job.contact_name || 'No contact'}</a>
      <span class="job-num">{job.job_number}</span>
    </div>
  </div>
  {#if job.sub_status === 'needs-invoice'}
    <div class="needs-invoice">
      <span class="pill needs-inv">Needs Invoice</span>
      <span class="needs-inv-text">Work order complete — no invoice created yet</span>
    </div>
  {:else}
    <table class="line-table">
      {#each job.invoices || [] as inv}
        {@const pill = invoiceStatusPill(inv)}
        <tr>
          <td class="col-num">{inv.invoice_number}</td>
          <td class="col-status"><span class="pill {pill.cls}">{pill.label}</span></td>
          <td class="col-date">{inv.sent_date ? `Sent ${formatDate(inv.sent_date)}` : ''}</td>
          <td class="col-amt {amountClass(inv)}">{formatAmount(inv.total)}</td>
        </tr>
        {#each paymentRows(inv) as pmt}
          <tr class="payment-row">
            <td class="col-num"></td>
            <td class="col-status"><span class="pill payment">Payment</span></td>
            <td class="col-date">Paid {formatDate(pmt.date)}</td>
            <td class="col-amt amt-payment">-{formatAmount(pmt.amount)}</td>
          </tr>
        {/each}
      {/each}
    </table>
    <div class="card-foot">
      <span>{invoiceCount} invoice{invoiceCount !== 1 ? 's' : ''}{paymentCount > 0 ? ` · ${paymentCount} payment${paymentCount !== 1 ? 's' : ''}` : ''}</span>
      <span class="spacer"></span>
      <span class="total">{formatAmount(totalDue())} due</span>
    </div>
  {/if}
</div>

<style>
  .unpaid-card {
    background: #fff; border-radius: 10px; overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    border-left: 4px solid #f59e0b;
  }
  .unpaid-card.has-overdue { border-left-color: #dc2626; }
  .unpaid-card.needs-inv { border-left-color: #64748b; }

  .needs-invoice {
    padding: 10px 12px; display: flex; align-items: center; gap: 8px;
    background: #f8f9fb; border-top: 1px solid #f0f0f0;
  }
  .needs-inv-text { font-size: 11px; color: #888; }
  .pill.needs-inv { background: #f1f5f9; color: #64748b; }

  .card-head { padding: 8px 10px 6px; border-bottom: 1px solid #f0f0f0; }
  .card-head-top { display: flex; align-items: baseline; gap: 6px; }
  .job-name { font-size: 13px; font-weight: 600; }
  .profit { margin-left: auto; display: flex; gap: 8px; font-size: 10px; color: #888; }
  .val { font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; }
  .val.green { color: #15803d; }
  .val.red { color: #dc2626; }
  .card-head-sub { display: flex; align-items: baseline; gap: 6px; margin-top: 2px; }
  .customer { font-size: 11px; color: #2563eb; text-decoration: none; }
  .customer:hover { text-decoration: underline; }
  .job-num { font-size: 10px; color: #999; font-family: 'SF Mono', 'Fira Code', monospace; }

  .line-table { width: 100%; border-collapse: collapse; font-size: 11px; }
  .line-table td { padding: 4px 6px; white-space: nowrap; }
  .line-table tr { border-bottom: 1px solid #f8f8f8; }
  .line-table tr:last-child { border-bottom: none; }
  .line-table tr.payment-row { background: #f9fdf9; }
  .col-num { font-family: 'SF Mono', 'Fira Code', monospace; color: #888; font-size: 10px; width: 68px; }
  .col-status { width: 72px; }
  .col-date { color: #888; font-size: 10px; }
  .col-amt { text-align: right; font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 11px; }
  .amt-paid { color: #15803d; }
  .amt-owing { color: #b45309; }
  .amt-payment { color: #15803d; }

  .pill { font-size: 9px; padding: 1px 6px; border-radius: 8px; font-weight: 600; display: inline-block; }
  .pill.open { background: #fef3c7; color: #b45309; }
  .pill.paid { background: #dcfce7; color: #15803d; }
  .pill.partly { background: #e0e7ff; color: #4338ca; }
  .pill.payment { background: #dcfce7; color: #15803d; }

  .card-foot {
    display: flex; align-items: center; padding: 5px 10px; background: #f8f9fa;
    font-size: 10px; color: #888; gap: 8px; border-top: 1px solid #f0f0f0;
  }
  .spacer { flex: 1; }
  .total { font-weight: 700; font-size: 11px; font-family: 'SF Mono', 'Fira Code', monospace; color: #b45309; }
</style>
```

- [ ] **Step 2: Create UnpaidColumn component**

Create `frontend/src/components/board/UnpaidColumn.svelte`:

```svelte
<script>
  import UnpaidCard from './UnpaidCard.svelte';
  let { jobs = [] } = $props();
</script>

<div class="column-header">
  <strong>Unpaid</strong>
  <span class="count">{jobs.length}</span>
</div>
<div class="column-body">
  {#each jobs as job (job.job_id)}
    <a href="#/jobs/{job.job_id}" class="card-link">
      <UnpaidCard {job} />
    </a>
  {/each}
  {#if jobs.length === 0}
    <p class="empty">No unpaid jobs</p>
  {/if}
</div>

<style>
  .column-header { padding: 14px 16px 10px; display: flex; align-items: center; justify-content: center; gap: 10px; border-bottom: 3px solid #f59e0b; flex-shrink: 0; }
  .count { font-size: 12px; color: #999; }
  .column-body { flex: 1; overflow-y: auto; padding: 12px; background: #fffbf0; columns: 2; column-gap: 10px; }
  .card-link { text-decoration: none; color: inherit; display: block; break-inside: avoid; margin-bottom: 10px; }
  .empty { font-size: 13px; color: #999; text-align: center; padding: 20px 0; }
</style>
```

- [ ] **Step 3: Verify it builds**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/board/UnpaidCard.svelte frontend/src/components/board/UnpaidColumn.svelte
git commit -m "feat: add UnpaidColumn and UnpaidCard components"
```

---

### Task 10: Frontend — Redesign ClosedColumn with ClosedCard

**Files:**
- Create: `frontend/src/components/board/ClosedCard.svelte`
- Modify: `frontend/src/components/board/ClosedColumn.svelte`

Two-column masonry layout with profitability and date info.

- [ ] **Step 1: Create ClosedCard component**

Create `frontend/src/components/board/ClosedCard.svelte`:

```svelte
<script>
  let { job } = $props();

  function formatAmount(amount) {
    if (amount == null) return '$0.00';
    return Number(amount).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  }

  function formatDate(isoDate) {
    if (!isoDate) return '';
    return new Date(isoDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function borderColor() {
    if (job.status === 'completed') return '#7c3aed';
    if (job.status === 'rejected') return '#b91c1c';
    return '#64748b';
  }

  function statusLabel() {
    if (job.status === 'completed') return 'Completed';
    if (job.status === 'rejected') return 'Rejected';
    if (job.status === 'cancelled') return 'Cancelled';
    return job.status;
  }

  function statusClass() {
    return job.status;
  }

  function duration() {
    if (!job.start_date || !job.completed_date) return '';
    const start = new Date(job.start_date);
    const end = new Date(job.completed_date);
    const days = Math.round((end - start) / (1000 * 60 * 60 * 24));
    if (days < 14) return `${days} day${days !== 1 ? 's' : ''}`;
    const weeks = Math.floor(days / 7);
    const remainder = days % 7;
    if (remainder === 0) return `${weeks} week${weeks !== 1 ? 's' : ''}`;
    return `${weeks} week${weeks !== 1 ? 's' : ''} ${remainder} day${remainder !== 1 ? 's' : ''}`;
  }

  let margin = $derived(() => {
    const billed = Number(job.billed) || 0;
    if (billed === 0) return null;
    return Math.round(((billed - (Number(job.spent) || 0)) / billed) * 100);
  });
</script>

<div class="closed-card" style="border-left-color: {borderColor()};">
  <div class="card-head">
    <div class="card-head-top">
      <span class="job-name">{job.name}</span>
      <span class="substatus {statusClass()}">{statusLabel()}</span>
    </div>
    <div class="card-head-sub">
      <a class="customer" href="#/contacts/{job.contact_id}">{job.contact_name || 'No contact'}</a>
      <span class="job-num">{job.job_number}</span>
    </div>
  </div>
  <div class="card-details">
    <div class="detail-row">
      <span class="label">Start</span>
      <span class="value">{formatDate(job.start_date)}</span>
      <span class="label">End</span>
      <span class="value">{formatDate(job.completed_date)}</span>
      {#if duration()}
        <span class="duration">{duration()}</span>
      {/if}
    </div>
  </div>
  <div class="profit-row">
    <span>Billed <span class="val">{formatAmount(job.billed)}</span></span>
    <span>Spent <span class="val">{formatAmount(job.spent)}</span></span>
    <span>Profit <span class="val" class:green={Number(job.profit) >= 0} class:red={Number(job.profit) < 0}>{formatAmount(job.profit)}</span></span>
    <span class="spacer"></span>
    {#if margin() !== null}
      <span class="margin" class:green={margin() >= 0} class:red={margin() < 0}>{margin()}%</span>
    {/if}
  </div>
</div>

<style>
  .closed-card {
    background: #fff; border-radius: 10px; overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    border-left: 4px solid #9ca3af;
  }

  .card-head { padding: 8px 10px 6px; }
  .card-head-top { display: flex; align-items: baseline; gap: 6px; }
  .job-name { font-size: 13px; font-weight: 600; }
  .substatus { font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: 600; margin-left: auto; }
  .substatus.completed { background: #f3e8ff; color: #7c3aed; }
  .substatus.rejected { background: #fee2e2; color: #b91c1c; }
  .substatus.cancelled { background: #f1f5f9; color: #64748b; }
  .card-head-sub { display: flex; align-items: baseline; gap: 6px; margin-top: 2px; }
  .customer { font-size: 11px; color: #2563eb; text-decoration: none; }
  .customer:hover { text-decoration: underline; }
  .job-num { font-size: 10px; color: #999; font-family: 'SF Mono', 'Fira Code', monospace; }

  .card-details { padding: 0 10px 8px; }
  .detail-row {
    display: flex; align-items: center; gap: 8px;
    font-size: 11px; color: #666; margin-top: 4px;
  }
  .label { color: #999; font-size: 10px; min-width: 36px; }
  .value { font-size: 11px; }
  .duration { margin-left: auto; font-size: 10px; color: #888; }

  .profit-row {
    display: flex; align-items: center; gap: 8px; padding: 5px 10px;
    font-size: 10px; color: #888; background: #f8f9fa; border-top: 1px solid #f0f0f0;
  }
  .val { font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; }
  .val.green, .green { color: #15803d; }
  .val.red, .red { color: #dc2626; }
  .spacer { flex: 1; }
  .margin { font-weight: 600; }
</style>
```

- [ ] **Step 2: Update ClosedColumn to use masonry layout and ClosedCard**

Rewrite `frontend/src/components/board/ClosedColumn.svelte`:

```svelte
<script>
  import ClosedCard from './ClosedCard.svelte';
  let { jobs = [] } = $props();
</script>

<div class="column-header">
  <strong>Closed</strong>
  <span class="count">{jobs.length}</span>
</div>
<div class="column-body">
  {#each jobs as job (job.job_id)}
    <a href="#/jobs/{job.job_id}" class="card-link">
      <ClosedCard {job} />
    </a>
  {/each}
  {#if jobs.length === 0}
    <p class="empty">No recently closed jobs</p>
  {/if}
</div>

<style>
  .column-header { padding: 14px 16px 10px; display: flex; align-items: center; justify-content: center; gap: 10px; border-bottom: 3px solid #9ca3af; flex-shrink: 0; }
  .count { font-size: 12px; color: #999; }
  .column-body { flex: 1; overflow-y: auto; padding: 12px; background: #f5f5f6; columns: 2; column-gap: 10px; }
  .card-link { text-decoration: none; color: inherit; display: block; break-inside: avoid; margin-bottom: 10px; }
  .empty { font-size: 13px; color: #999; text-align: center; padding: 20px 0; }
</style>
```

- [ ] **Step 3: Verify it builds**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/board/ClosedCard.svelte frontend/src/components/board/ClosedColumn.svelte
git commit -m "feat: redesign ClosedColumn with profitability and date cards"
```

---

### Task 11: Run all tests and verify end-to-end

**Files:**
- No changes — verification only

- [ ] **Step 1: Run all backend tests**

Run: `python manage.py test tests.test_board_service tests.test_board_api -v 2`
Expected: All tests pass, including both old and new tests.

- [ ] **Step 2: Build the frontend**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no errors.

- [ ] **Step 3: Manual smoke test**

Start both servers (`python manage.py runserver` and `cd frontend && npm run dev`). Navigate to `http://localhost:9000/#/jobs/board`. Verify:

1. In Progress column loads by default with chip strip and worker columns
2. Clicking Pipeline tab slides it open, shows 2-column masonry with doc rows
3. Clicking Unpaid tab slides it open, shows invoice/payment cards with profitability. Jobs with completed work orders but no invoice show "Needs Invoice" message. Jobs with draft invoices show "Invoice Prepped". Jobs with open invoices show invoice detail.
4. Clicking Closed tab slides it open, shows date/profitability cards
5. Only one column is expanded at a time
6. Collapsed tabs show rotated labels (no count on Closed)
7. Transition animation is smooth (~180ms)

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: board redesign polish from smoke testing"
```
