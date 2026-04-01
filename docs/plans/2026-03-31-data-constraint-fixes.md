# Data Constraint Code Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 6 code fixes identified in `docs/designs/data-constraints.md` Section 4 so that the code matches the documented intended behavior.

**Architecture:** Each fix is a small, independent change to model validation, signal handlers, or service methods. All follow existing patterns in the codebase. TDD throughout.

**Tech Stack:** Django 5.2, Django TestCase, model clean()/save() methods, Django signals

---

### Task 1: Task blocked → complete transition

**Files:**
- Modify: `apps/jobs/models.py:205` (Task.VALID_TRANSITIONS)
- Test: `tests/test_task_lifecycle.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_task_lifecycle.py`, add to the existing test class (or create a new one if no `CompleteTaskTest` exists):

```python
class CompleteBlockedTaskTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='Test Task', work_order=self.wo)

    def test_complete_from_blocked(self):
        """blocked → complete should be a valid transition."""
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_BLOCKED)
        self.task.refresh_from_db()
        TaskLifecycleService.complete_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_COMPLETE)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_task_lifecycle.CompleteBlockedTaskTest.test_complete_from_blocked`
Expected: FAIL — ValidationError because `complete` is not in `VALID_TRANSITIONS[blocked]`

- [ ] **Step 3: Add STATUS_COMPLETE to blocked transitions**

In `apps/jobs/models.py`, change the `STATUS_BLOCKED` entry in `VALID_TRANSITIONS`:

```python
STATUS_BLOCKED: [STATUS_IN_PROGRESS, STATUS_COMPLETE, STATUS_CANCELLED],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_task_lifecycle.CompleteBlockedTaskTest.test_complete_from_blocked`
Expected: PASS

- [ ] **Step 5: Run full task lifecycle tests**

Run: `python manage.py test tests.test_task_lifecycle`
Expected: All pass (no regressions)

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/models.py tests/test_task_lifecycle.py
git commit -m "feat: allow task transition from blocked to complete"
```

---

### Task 2: Estimate sent → Job submitted

**Files:**
- Modify: `apps/estimates/models.py` (Estimate._maybe_update_job_status)
- Modify: `apps/estimates/signals.py` (add receiver)
- Test: `tests/test_estimate_job_signals.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_estimate_job_signals.py`:

```python
from decimal import Decimal
from django.test import TestCase
from apps.core.models import Configuration, User
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job
from apps.estimates.models import Estimate


class EstimateSentJobSubmittedTest(TestCase):
    """When an Estimate is sent (draft → open), its Job should move to submitted."""

    def setUp(self):
        # Configuration for number generation and expiry
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='est_expire_days', value='30')

        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='JOB-TEST-0001', contact=self.contact,
            status=Job.STATUS_DRAFT,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-TEST-0001',
            status=Estimate.STATUS_DRAFT,
        )

    def test_job_moves_to_submitted_when_estimate_sent(self):
        self.assertEqual(self.job.status, Job.STATUS_DRAFT)
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

    def test_job_stays_submitted_if_already_submitted(self):
        Job.objects.filter(pk=self.job.pk).update(status=Job.STATUS_SUBMITTED)
        self.job.refresh_from_db()
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

    def test_job_not_affected_if_already_approved(self):
        Job.objects.filter(pk=self.job.pk).update(status=Job.STATUS_APPROVED)
        self.job.refresh_from_db()
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    def test_accepted_estimate_skips_double_transition(self):
        """Once sent→submitted works, acceptance should be a single submitted→approved."""
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_estimate_job_signals`
Expected: `test_job_moves_to_submitted_when_estimate_sent` FAILS (job stays draft)

- [ ] **Step 3: Add the signal for estimate sent → job submitted**

In `apps/estimates/models.py`, update `_maybe_update_job_status` to also handle the `open` transition. Add this block BEFORE the existing acceptance check:

```python
def _maybe_update_job_status(self, old_status):
    """Send signal to update job status if the change is relevant."""
    from apps.estimates.signals import estimate_status_changed_for_job, estimate_accepted

    # Signal when estimate is sent (draft → open): job should become submitted
    if self.status == Estimate.STATUS_OPEN and old_status == Estimate.STATUS_DRAFT:
        from apps.jobs.models import Job
        estimate_status_changed_for_job.send(
            sender=self.__class__,
            estimate=self,
            new_job_status=Job.STATUS_SUBMITTED
        )

    # Signal when estimate is accepted
    if self.status == Estimate.STATUS_ACCEPTED and old_status != Estimate.STATUS_ACCEPTED:
        from apps.jobs.models import Job
        estimate_status_changed_for_job.send(
            sender=self.__class__,
            estimate=self,
            new_job_status=Job.STATUS_APPROVED
        )
        estimate_accepted.send(
            sender=self.__class__,
            estimate=self,
        )

    # Signal when approved estimate is superseded
    elif self.status == Estimate.STATUS_SUPERSEDED and old_status == Estimate.STATUS_ACCEPTED:
        estimate_status_changed_for_job.send(
            sender=self.__class__,
            estimate=self,
            new_job_status='blocked'
        )
```

- [ ] **Step 4: Update the signal receiver to handle submitted transition**

In `apps/estimates/signals.py`, the existing `update_job_status` receiver already handles arbitrary `new_job_status` values. Check that it handles `draft → submitted` correctly. The existing code already does:

```python
if job.status != new_job_status:
    # If trying to go to 'approved' from 'draft', first go through 'submitted'
    if new_job_status == Job.STATUS_APPROVED and job.status == Job.STATUS_DRAFT:
        ...
    else:
        old_status = job.status
        job.status = new_job_status
        job.save()
        ...
```

The `else` branch handles `draft → submitted` naturally. No changes needed to the receiver.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_estimate_job_signals`
Expected: All 4 tests PASS

- [ ] **Step 6: Run existing estimate/signal tests for regressions**

Run: `python manage.py test tests.test_auto_earmark tests.test_estimate_status_signals`
Expected: All pass. The existing acceptance tests should still work since the `draft → submitted` transition now happens on `open`, and the `submitted → approved` transition happens on acceptance.

- [ ] **Step 7: Commit**

```bash
git add apps/estimates/models.py tests/test_estimate_job_signals.py
git commit -m "feat: auto-transition job to submitted when estimate is sent"
```

---

### Task 3: Last Invoice paid → Job completed

**Files:**
- Modify: `apps/invoicing/models.py` (Invoice.save)
- Test: `tests/test_estimate_job_signals.py` (add to existing new file)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_estimate_job_signals.py`:

```python
from apps.invoicing.models import Invoice, InvoiceLineItem


class LastInvoicePaidJobCompletedTest(TestCase):
    """When all Invoices for a Job are paid, the Job should move to completed."""

    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')

        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='JOB-TEST-0001', contact=self.contact,
            status=Job.STATUS_APPROVED,
        )

    def test_job_completed_when_single_invoice_paid(self):
        inv = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0001', status=Invoice.STATUS_OPEN)
        InvoiceLineItem.objects.create(invoice=inv, description='Work', price=Decimal('100.00'))
        inv.status = Invoice.STATUS_PAID
        inv.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_COMPLETED)
        self.assertIsNotNone(self.job.completed_date)

    def test_job_not_completed_when_one_invoice_still_open(self):
        inv1 = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0001', status=Invoice.STATUS_OPEN)
        InvoiceLineItem.objects.create(invoice=inv1, description='Work', price=Decimal('100.00'))
        inv2 = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0002', status=Invoice.STATUS_OPEN)
        InvoiceLineItem.objects.create(invoice=inv2, description='More work', price=Decimal('200.00'))
        inv1.status = Invoice.STATUS_PAID
        inv1.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    def test_job_completed_when_last_invoice_paid(self):
        inv1 = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0001', status=Invoice.STATUS_PAID)
        inv2 = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0002', status=Invoice.STATUS_OPEN)
        InvoiceLineItem.objects.create(invoice=inv2, description='More work', price=Decimal('200.00'))
        inv2.status = Invoice.STATUS_PAID
        inv2.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_COMPLETED)

    def test_cancelled_invoices_ignored(self):
        inv1 = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0001', status=Invoice.STATUS_OPEN)
        InvoiceLineItem.objects.create(invoice=inv1, description='Work', price=Decimal('100.00'))
        inv2 = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0002', status=Invoice.STATUS_CANCELLED)
        inv1.status = Invoice.STATUS_PAID
        inv1.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_COMPLETED)

    def test_already_completed_job_not_affected(self):
        Job.objects.filter(pk=self.job.pk).update(status=Job.STATUS_COMPLETED)
        self.job.refresh_from_db()
        inv = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0001', status=Invoice.STATUS_OPEN)
        InvoiceLineItem.objects.create(invoice=inv, description='Work', price=Decimal('100.00'))
        inv.status = Invoice.STATUS_PAID
        inv.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_COMPLETED)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_estimate_job_signals.LastInvoicePaidJobCompletedTest`
Expected: `test_job_completed_when_single_invoice_paid` FAILS (job stays approved)

- [ ] **Step 3: Add auto-complete logic to Invoice.save()**

In `apps/invoicing/models.py`, update the `save()` method:

```python
def save(self, *args, **kwargs):
    """Override save to auto-generate invoice_number and check job completion."""
    from apps.core.services import NumberGenerationService

    old_status = None
    if self.pk:
        try:
            old_invoice = Invoice.objects.get(pk=self.pk)
            old_status = old_invoice.status
        except Invoice.DoesNotExist:
            pass

    # Auto-generate invoice_number if not provided
    if not self.invoice_number:
        self.invoice_number = NumberGenerationService.generate_next_number('invoice')

    # Call parent save
    super().save(*args, **kwargs)

    # Check if status changed to paid and all invoices for the job are now paid
    if old_status and old_status != self.status and self.status == Invoice.STATUS_PAID:
        self._maybe_complete_job()

def _maybe_complete_job(self):
    """Complete the job if all its invoices are paid (or cancelled)."""
    from apps.core.models import HistoryEntry, User

    job = self.job
    # Don't touch completed or cancelled jobs
    if job.status in (Job.STATUS_COMPLETED, Job.STATUS_CANCELLED):
        return

    # Check if any invoices are still unresolved
    unresolved = Invoice.objects.filter(job=job).exclude(
        status__in=(Invoice.STATUS_PAID, Invoice.STATUS_CANCELLED)
    ).exists()

    if not unresolved:
        old_status = job.status
        job.status = Job.STATUS_COMPLETED
        job.save()

        system_user, _ = User.objects.get_or_create(
            username='system',
            defaults={'first_name': 'System', 'is_active': False},
        )
        HistoryEntry.objects.create(
            entry_type='action',
            object_type='job',
            object_id=job.pk,
            user=system_user,
            changes={
                'status': {'old': old_status, 'new': Job.STATUS_COMPLETED},
                '_action': f'All invoices paid — job completed',
            },
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_estimate_job_signals.LastInvoicePaidJobCompletedTest`
Expected: All 5 tests PASS

- [ ] **Step 5: Run full test suite for regressions**

Run: `python manage.py test`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add apps/invoicing/models.py tests/test_estimate_job_signals.py
git commit -m "feat: auto-complete job when all invoices are paid"
```

---

### Task 4: Task blocked → WorkOrder blocked

**Files:**
- Modify: `apps/jobs/services/__init__.py` (TaskLifecycleService.block_task)
- Test: `tests/test_task_lifecycle.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_task_lifecycle.py`:

```python
class TaskBlockedWorkOrderBlockedTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='Test Task', work_order=self.wo)

    def test_workorder_blocked_when_task_blocked(self):
        TaskLifecycleService.block_task(self.task.pk)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.STATUS_BLOCKED)

    def test_workorder_stays_blocked_if_already_blocked(self):
        WorkOrder.objects.filter(pk=self.wo.pk).update(status=WorkOrder.STATUS_BLOCKED)
        self.wo.refresh_from_db()
        task2 = Task.objects.create(name='Task 2', work_order=self.wo)
        TaskLifecycleService.block_task(task2.pk)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.STATUS_BLOCKED)

    def test_worksheet_task_block_does_not_affect_workorder(self):
        """Blocking a task on an EstWorksheet should not try to block a WorkOrder."""
        from apps.estimates.models import EstWorksheet
        ws = EstWorksheet.objects.create(job=self.job)
        ws_task = Task.objects.create(name='WS Task', est_worksheet=ws)
        # Should not raise — no WorkOrder to block
        TaskLifecycleService.block_task(ws_task.pk)
        ws_task.refresh_from_db()
        self.assertEqual(ws_task.status, Task.STATUS_BLOCKED)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_task_lifecycle.TaskBlockedWorkOrderBlockedTest`
Expected: `test_workorder_blocked_when_task_blocked` FAILS (WO stays incomplete)

- [ ] **Step 3: Add WorkOrder blocking to TaskLifecycleService.block_task**

In `apps/jobs/services/__init__.py`, add a helper and call it from `block_task`. After the line `task.status = Task.STATUS_BLOCKED`, add:

```python
TaskLifecycleService._check_wo_blocked(task)
```

Then add the helper method to `TaskLifecycleService`:

```python
@staticmethod
def _check_wo_blocked(task):
    """Block WorkOrder if a task on it is blocked."""
    if not task.work_order:
        return
    wo = task.work_order
    if wo.status == WorkOrder.STATUS_BLOCKED:
        return
    if wo.status == WorkOrder.STATUS_COMPLETE:
        return
    WorkOrderService.update_status(wo.pk, WorkOrder.STATUS_BLOCKED)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_task_lifecycle.TaskBlockedWorkOrderBlockedTest`
Expected: All 3 tests PASS

- [ ] **Step 5: Run full task lifecycle tests**

Run: `python manage.py test tests.test_task_lifecycle`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/services/__init__.py tests/test_task_lifecycle.py
git commit -m "feat: auto-block work order when a task is blocked"
```

---

### Task 5: Line item requirement on Estimate, Invoice, PurchaseOrder

**Files:**
- Modify: `apps/estimates/models.py` (Estimate.clean)
- Modify: `apps/invoicing/models.py` (Invoice.save — add clean/full_clean)
- Modify: `apps/purchasing/models.py` (PurchaseOrder.clean)
- Test: `tests/test_line_item_requirement.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_line_item_requirement.py`:

```python
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.core.models import Configuration, AccountingCategory
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job
from apps.estimates.models import Estimate, EstimateLineItem
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem


class EstimateLineItemRequirementTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='est_expire_days', value='30')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='JOB-TEST-0001', contact=self.contact,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-TEST-0001',
            status=Estimate.STATUS_DRAFT,
        )

    def test_cannot_send_estimate_without_line_items(self):
        self.estimate.status = Estimate.STATUS_OPEN
        with self.assertRaises(ValidationError) as ctx:
            self.estimate.save()
        self.assertIn('line item', str(ctx.exception).lower())

    def test_can_send_estimate_with_line_items(self):
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Test item',
            price=Decimal('100.00'),
        )
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, Estimate.STATUS_OPEN)


class InvoiceLineItemRequirementTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='JOB-TEST-0001', contact=self.contact,
        )
        self.invoice = Invoice.objects.create(
            job=self.job, invoice_number='INV-TEST-0001',
            status=Invoice.STATUS_DRAFT,
        )

    def test_cannot_send_invoice_without_line_items(self):
        self.invoice.status = Invoice.STATUS_OPEN
        with self.assertRaises(ValidationError) as ctx:
            self.invoice.save()
        self.assertIn('line item', str(ctx.exception).lower())

    def test_can_send_invoice_with_line_items(self):
        InvoiceLineItem.objects.create(
            invoice=self.invoice, description='Test item',
            price=Decimal('100.00'),
        )
        self.invoice.status = Invoice.STATUS_OPEN
        self.invoice.save()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.STATUS_OPEN)


class PurchaseOrderLineItemRequirementTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='po_number_sequence', value='PO-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.business = Business.objects.create(
            business_name='Test Biz', default_contact=self.contact,
            our_reference_code='TST-0001',
        )
        self.contact.business = self.business
        self.contact.save()
        self.po = PurchaseOrder.objects.create(
            business=self.business, contact=self.contact,
            po_number='PO-TEST-0001', status=PurchaseOrder.STATUS_DRAFT,
        )

    def test_cannot_issue_po_without_line_items(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        with self.assertRaises(ValidationError) as ctx:
            self.po.save()
        self.assertIn('line item', str(ctx.exception).lower())

    def test_can_issue_po_with_line_items(self):
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='Test item',
            price=Decimal('100.00'),
        )
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.STATUS_ISSUED)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_line_item_requirement`
Expected: The 3 `cannot_*` tests FAIL (no validation error raised)

- [ ] **Step 3: Add line item check to Estimate.clean()**

In `apps/estimates/models.py`, in `Estimate.clean()`, add after the status transition check block (after the `except Estimate.DoesNotExist: pass`), before the "only one accepted" check:

```python
# If transitioning out of draft, ensure at least one line item exists
if self.pk:
    try:
        old_estimate = Estimate.objects.get(pk=self.pk)
        if old_estimate.status == Estimate.STATUS_DRAFT and self.status != Estimate.STATUS_DRAFT:
            from apps.estimates.models import EstimateLineItem
            if not EstimateLineItem.objects.filter(estimate=self).exists():
                raise ValidationError(
                    'Cannot change Estimate status from Draft without at least one line item.'
                )
    except Estimate.DoesNotExist:
        pass
```

Note: this needs to be integrated into the existing `if self.pk:` block that already fetches `old_estimate`. Add the line item check inside that block, after the transition validation, to avoid a redundant DB query.

- [ ] **Step 4: Add line item check to Invoice.save()**

In `apps/invoicing/models.py`, update Invoice.save() to add validation. Add a `clean()` method:

```python
def clean(self):
    super().clean()
    if self.pk:
        try:
            old_invoice = Invoice.objects.get(pk=self.pk)
            if old_invoice.status == Invoice.STATUS_DRAFT and self.status != Invoice.STATUS_DRAFT:
                if not InvoiceLineItem.objects.filter(invoice=self).exists():
                    raise ValidationError(
                        'Cannot change Invoice status from Draft without at least one line item.'
                    )
        except Invoice.DoesNotExist:
            pass
```

And call `self.full_clean()` in `save()` before `super().save()`.

- [ ] **Step 5: Add line item check to PurchaseOrder.clean()**

In `apps/purchasing/models.py`, in `PurchaseOrder.clean()`, add inside the existing `if self.pk:` block, after the transition validation:

```python
# If transitioning out of draft, ensure at least one line item exists
if old_status == PurchaseOrder.STATUS_DRAFT and self.status != PurchaseOrder.STATUS_DRAFT:
    if not PurchaseOrderLineItem.objects.filter(purchase_order=self).exists():
        raise ValidationError(
            'Cannot change Purchase Order status from Draft without at least one line item.'
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python manage.py test tests.test_line_item_requirement`
Expected: All 6 tests PASS

- [ ] **Step 7: Run full test suite for regressions**

Run: `python manage.py test`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add apps/estimates/models.py apps/invoicing/models.py apps/purchasing/models.py tests/test_line_item_requirement.py
git commit -m "feat: require at least one line item before leaving draft on all document types"
```

---

### Task 6: Estimate accepted → WorkOrder created from worksheet

**Files:**
- Modify: `apps/estimates/signals.py` (add receiver for estimate_accepted)
- Test: `tests/test_estimate_job_signals.py` (add test class)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_estimate_job_signals.py`:

```python
from apps.estimates.models import Estimate, EstWorksheet, EstimateLineItem
from apps.jobs.models import Job, WorkOrder, Task, TaskBundle
from apps.inventory.models import Material, PriceListItem
from apps.core.models import AccountingCategory


class EstimateAcceptedWorkOrderCreatedTest(TestCase):
    """When an Estimate with a worksheet is accepted, a WorkOrder should be
    auto-created by copying the worksheet's tasks, bundles, and materials."""

    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='est_expire_days', value='30')

        self.category = AccountingCategory.objects.create(code='SVC', name='Service')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='JOB-TEST-0001', contact=self.contact,
            status=Job.STATUS_DRAFT,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-TEST-0001',
            status=Estimate.STATUS_DRAFT,
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, estimate=self.estimate,
        )
        self.task1 = Task.objects.create(
            name='Task A', est_worksheet=self.worksheet,
            units='hours', rate=Decimal('50.00'), est_qty=Decimal('10.00'),
            accounting_category=self.category,
        )
        self.task2 = Task.objects.create(
            name='Task B', est_worksheet=self.worksheet,
            units='hours', rate=Decimal('75.00'), est_qty=Decimal('5.00'),
            accounting_category=self.category,
        )
        # Add a line item so estimate can leave draft
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Work',
            price=Decimal('100.00'),
        )

    def test_workorder_created_on_acceptance(self):
        self.assertEqual(WorkOrder.objects.filter(job=self.job).count(), 0)
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()
        self.assertEqual(WorkOrder.objects.filter(job=self.job).count(), 1)

    def test_tasks_copied_to_workorder(self):
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()
        wo = WorkOrder.objects.get(job=self.job)
        wo_tasks = Task.objects.filter(work_order=wo)
        self.assertEqual(wo_tasks.count(), 2)
        self.assertTrue(wo_tasks.filter(name='Task A').exists())
        self.assertTrue(wo_tasks.filter(name='Task B').exists())

    def test_tasks_start_in_pending(self):
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()
        wo = WorkOrder.objects.get(job=self.job)
        for task in Task.objects.filter(work_order=wo):
            self.assertEqual(task.status, Task.STATUS_PENDING)

    def test_bundles_copied_to_workorder(self):
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='Bundle 1',
            accounting_category=self.category,
        )
        Task.objects.filter(pk=self.task1.pk).update(
            bundle=bundle, mapping_strategy='bundle',
        )
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()
        wo = WorkOrder.objects.get(job=self.job)
        wo_bundles = TaskBundle.objects.filter(work_order=wo)
        self.assertEqual(wo_bundles.count(), 1)
        self.assertEqual(wo_bundles.first().name, 'Bundle 1')
        # Task A should be in the new bundle
        wo_task_a = Task.objects.get(work_order=wo, name='Task A')
        self.assertEqual(wo_task_a.bundle, wo_bundles.first())
        self.assertEqual(wo_task_a.mapping_strategy, 'bundle')

    def test_materials_copied_to_workorder(self):
        pli = PriceListItem.objects.create(
            code='MAT-001', description='Plywood',
            purchase_price=Decimal('25.00'), selling_price=Decimal('50.00'),
            accounting_category=self.category,
        )
        Material.objects.create(
            task=self.task1, price_list_item=pli,
            quantity=Decimal('5.00'),
        )
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()
        wo = WorkOrder.objects.get(job=self.job)
        wo_task_a = Task.objects.get(work_order=wo, name='Task A')
        wo_materials = Material.objects.filter(task=wo_task_a)
        self.assertEqual(wo_materials.count(), 1)
        self.assertEqual(wo_materials.first().price_list_item, pli)
        self.assertEqual(wo_materials.first().quantity, Decimal('5.00'))

    def test_no_workorder_without_worksheet(self):
        """Estimate without a worksheet should not create a WorkOrder."""
        est2 = Estimate.objects.create(
            job=self.job, estimate_number='EST-TEST-0002',
            status=Estimate.STATUS_DRAFT,
        )
        EstimateLineItem.objects.create(
            estimate=est2, description='Work', price=Decimal('50.00'),
        )
        est2.status = Estimate.STATUS_OPEN
        est2.save()
        est2.status = Estimate.STATUS_ACCEPTED
        est2.save()
        # Only the WO from the first estimate (if any) — est2 has no worksheet
        # so no WO should be created for it
        wo_count = WorkOrder.objects.filter(job=self.job).count()
        # The first estimate is still draft, so 0 WOs total
        self.assertEqual(wo_count, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_estimate_job_signals.EstimateAcceptedWorkOrderCreatedTest`
Expected: Tests expecting WorkOrder creation FAIL

- [ ] **Step 3: Add signal receiver for WorkOrder creation**

In `apps/estimates/signals.py`, add a new receiver for `estimate_accepted`:

```python
@receiver(estimate_accepted)
def auto_create_workorder_from_worksheet(sender, estimate, **kwargs):
    """Auto-create a WorkOrder by copying the accepted estimate's worksheet."""
    from apps.estimates.models import EstWorksheet
    from apps.jobs.models import WorkOrder
    from apps.jobs.services import WorkOrderService

    # Find the worksheet linked to this estimate
    worksheets = EstWorksheet.objects.filter(estimate=estimate)
    if not worksheets.exists():
        return 0

    worksheet = worksheets.first()

    # Create WorkOrder for the job
    wo = WorkOrderService.create_direct(estimate.job)

    # Copy worksheet contents to the WorkOrder
    WorkOrderService.copy_from_worksheet(wo.pk, worksheet.pk)

    return 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_estimate_job_signals.EstimateAcceptedWorkOrderCreatedTest`
Expected: All 6 tests PASS

- [ ] **Step 5: Run all related tests for regressions**

Run: `python manage.py test tests.test_auto_earmark tests.test_estimate_status_signals tests.test_estimate_job_signals tests.test_task_lifecycle`
Expected: All pass. The existing `auto_earmark_inventory` receiver still runs (it will be replaced later by the Material-triggered approach, but for now both can coexist).

- [ ] **Step 6: Commit**

```bash
git add apps/estimates/signals.py tests/test_estimate_job_signals.py
git commit -m "feat: auto-create work order from worksheet when estimate is accepted"
```
