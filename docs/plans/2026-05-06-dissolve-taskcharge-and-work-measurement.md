# Dissolve TaskCharge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dissolve `TaskCharge` into `Task`. Restore `est_qty` (with new `actual_qty`) on Task as work-measurement fields. Expose `est_worker_time` in the Task-add UI. Converge TaskModal/SubtaskModal/PlanTaskModal onto a shared `WorkItemForm.svelte` fronted by two top-level buttons (Add From Template / Add Manual Task).

**Architecture:** Three phases in order. Phase A is purely additive on the backend — new columns nullable, no readers switched, no constraints tightened. Pause: developer manually verifies the dev-DB backfill. Phase B switches readers/writers, drops TaskCharge, tightens `Task.rate_scheme` to NOT NULL, and adds the asymmetric `PlanTask.clean()` est_qty enforcement. Phase C ships the frontend convergence on top of the new backend.

**Tech Stack:** Django 5.2, DRF, MySQL, Python 3.12, Svelte 5 (Vite). Tests via Django `TestCase` with fixtures from `tests/base.py`.

**Spec:** `docs/designs/2026-05-06-dissolve-taskcharge-and-work-measurement-design.md`

**Important constraints:**

- `python manage.py migrate` is **never** run by an agent. Only the human applies migrations to the dev DB. Tests create their own test DB automatically.
- `python manage.py makemigrations` is fine to run.
- Tests run via `python manage.py test tests.test_xxx` (single agent — never parallel; MySQL deadlock risk per CLAUDE.md).
- Custom `db_table` names — do NOT assume Django defaults. `tasks`, `plan_tasks`, `task_charges`, `rate_schemes` are all explicit.
- Project pattern: services in `apps/*/services.py` hold business logic, viewsets are thin wrappers.
- All DELETE responses return 200 with a JSON body, never 204.
- TDD: failing test first, see it fail, then minimal implementation.
- Status values: always use model constants (`Task.STATUS_PENDING`, etc.).
- Line item deletes go through `LineItemService.delete_line_item_with_renumber` — not relevant here but reminder.
- Latest existing migration: `apps/jobs/migrations/0032_remove_ratescheme_minimum_charge.py`. New migrations start at `0033`.

---

## File Structure

### Files to create (backend)

- `apps/jobs/migrations/0033_phase_a_add_task_billing_fields.py` — Phase A schema additions: new Task billing fields (nullable) AND moves `est_qty` declaration from PlanTask to TaskBase, which has the side effect of relaxing `PlanTask.est_qty` from NOT NULL to nullable in the same migration.
- `apps/jobs/migrations/0034_phase_a_backfill_task_from_taskcharge.py` — Phase A data migration; copies fields from TaskCharge to Task.
- `apps/jobs/migrations/0035_phase_b_tighten_task_rate_scheme.py` — Phase B; makes `Task.rate_scheme` `NOT NULL`.
- `apps/jobs/migrations/0036_phase_b_drop_taskcharge.py` — Phase B; drops `TaskCharge` model.
- `apps/jobs/migrations/_phase_a_backfill_helper.py` — Helper module imported by the data migration AND by tests. Underscore prefix keeps Django's migration loader from picking it up as a migration.
- `tests/test_dissolve_taskcharge_phase_a.py` — Phase A backfill verification (new fields populated on Task from TaskCharge).
- `tests/test_task_compute_amount.py` — Phase B: `Task.compute_amount` returns the same numbers `TaskCharge.compute_amount` did.
- `tests/test_plan_task_est_qty_required.py` — Phase B: `PlanTask.clean()` rejects null est_qty across every PlanTask creation path; `Task.clean()` accepts null.
- `tests/test_task_est_qty_carry_over.py` — Phase B: `est_qty` carries from PlanTask to Task for all algorithms.

### Files to create (frontend)

- `frontend/src/components/WorkItemForm.svelte` — shared form (template mode + manual mode).

### Files to modify (backend)

- `apps/jobs/models.py`
  - **Phase A**: add `Task.rate_scheme` (FK nullable for now), `Task.active_modifiers`, `Task.actual_qty`. Add `est_qty` to `TaskBase` (nullable). Drop `est_qty` field declaration from `PlanTask` (it inherits from base now).
  - **Phase B**: add `Task.compute_amount`, `Task.effective_rate`, `Task.effective_accounting_category`. Drop `Task.clean()`'s `hasattr(self, 'charge')` requirement. Update `RateScheme.is_referenced()` / `reference_counts()` / `get_actual_qty()` to query Task. Drop `TaskCharge` model. Add `PlanTask.clean()` enforcing non-null `est_qty`.
- `apps/jobs/services.py`
  - **Phase B**: rewrite `TaskService.create_from_template`, `TaskService.create_direct`, `TaskService.copy_from_worksheet` to write fields directly on Task (no TaskCharge). Update labor-cost reader at `services.py:985` to read from `task.rate_scheme`.
- `apps/estimates/carry_over.py`
  - **Phase B**: rewrite `_carry_over_plan_tasks` and `_create_task_from_line_item` to set `est_qty`/`active_modifiers`/`rate_scheme` directly on Task instead of creating a TaskCharge.
- `apps/estimates/models.py`
  - **Phase B**: rewrite `TaskTemplate.generate_task` Job branch to store `est_qty` and `active_modifiers` directly on Task; drop the TaskCharge create path.
- `apps/invoicing/services.py`
  - **Phase B**: switch `InvoiceWizardService.get_source_pool` and `_atom_*` helpers from `task.charge.*` to `task.*`. `WizardAtomLabels.qty_source_label` accepts a Task instead of a charge.
- `apps/api/tasks/serializers.py`
  - **Phase B**: drop `TaskChargeSerializer`/`TaskChargeReadSerializer`. Flatten Task payload (rate_scheme, active_modifiers, est_qty, est_worker_time, actual_qty as top-level fields). Drop `_estimated_hours` workaround (just use `task.est_qty`).
- `apps/api/tasks/views.py`
  - **Phase B**: drop `task_charge_view` function and the `/charge/` URL it serves. Update Task POST/PATCH path to accept the new direct fields.
- `apps/api/jobs/views.py`
  - **Phase B**: update `add_from_template` action so the `est_qty` argument is actually stored on the Task (today it's silently dropped at the model layer).
- `apps/api/plan_tasks/serializers.py`
  - Verify `est_qty` is still serialized correctly when its column declaration moves to `TaskBase` (likely no change needed, but confirm).
- `apps/api/worksheets/views.py`
  - **Phase B**: accept `est_worker_time` in the worksheet add-task and add-from-template endpoints.
- `apps/api/urls.py`
  - **Phase B**: remove the `task_charge_view` URL registration.

### Files to modify (frontend)

- `frontend/src/components/RateSchemeFieldset.svelte`
  - **Phase C**: relax the hard-required `est_qty` (becomes context-dependent: required on plan side, optional on real side); add an `estWorkerTime` bindable input. Or: fold entirely into `WorkItemForm.svelte` and delete this file. Implementation choice — prefer keeping as a sub-component for testability.
- Any worksheet/job page that mounts `PlanTaskModal` / `TaskModal` / `SubtaskModal`
  - **Phase C**: replace mount points and the "Add Task" buttons with the two-button entry pattern (Add From Template / Add Manual Task) and `WorkItemForm.svelte`.
- `frontend/src/routes/jobs/TaskDetailPage.svelte` (path approximate)
  - **Phase C**: change actual qty input to read/write `task.actual_qty` (top-level) instead of `task.charge.actuals.qty`.

### Files to delete (frontend, Phase C)

- `frontend/src/components/PlanTaskModal.svelte`
- `frontend/src/components/TaskModal.svelte`
- `frontend/src/components/SubtaskModal.svelte`

### Test strategy

- TDD throughout. Each behavior-changing task starts with a failing test, runs it to confirm it fails for the expected reason, then implements minimally, then confirms green.
- Migration tasks (data migrations) get a follow-up assertion test instead of pre-test (you can't write a failing test against a migration that doesn't yet exist).
- Tests live in `/tests/`. Use `BaseTestCase` from `tests/base.py` (loads `unit_test_data.json` fixture).
- Existing test files are extended in place where appropriate (e.g., `test_rate_scheme.py`, `test_jobs_models.py`, `test_carry_over.py`).
- **Run tests serially** — never spawn parallel test runners.

---

## Phase A — Backend Additive

> **Phase A goal:** Add new Task columns and TaskBase.est_qty as nullable. Backfill from existing TaskCharge rows. No reader / writer changes — existing TaskCharge code paths continue to work. No constraints tightened.

### Task A1: Add new fields to Task and TaskBase models

**Files:**
- Modify: `apps/jobs/models.py:126-160` (TaskBase + PlanTask region)
- Modify: `apps/jobs/models.py:194-275` (Task region)

- [ ] **Step 1: Add `est_qty` field to TaskBase**

In `apps/jobs/models.py`, replace the `TaskBase` class body:

```python
class TaskBase(models.Model):
    """Abstract base for PlanTask (worksheet) and Task (work order)."""
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    sort_order = models.PositiveIntegerField(blank=True, null=True)
    est_worker_time = models.DurationField(
        null=True, blank=True,
        help_text="Estimated worker time for scheduling"
    )
    est_qty = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text=(
            "Estimated billable quantity in the rate scheme's units. "
            "Required at the application layer on PlanTask; optional on Task."
        ),
    )

    class Meta:
        abstract = True

    def __str__(self):
        return self.name
```

- [ ] **Step 2: Drop the now-redundant `est_qty` declaration on PlanTask**

In the `PlanTask` class body, remove the `est_qty = models.DecimalField(...)` line. The field is now inherited from `TaskBase`. The rest of the class is unchanged. After removal `PlanTask` looks like:

```python
class PlanTask(TaskBase):
    """Planning task on an EstWorksheet. No lifecycle, no hierarchy, no bleps."""
    plan_task_id = models.AutoField(primary_key=True)
    est_worksheet = models.ForeignKey(
        'estimates.EstWorksheet', on_delete=models.CASCADE, related_name='plan_tasks'
    )
    rate_scheme = models.ForeignKey(
        'jobs.RateScheme', on_delete=models.PROTECT,
    )
    active_modifiers = models.JSONField(default=list, blank=True)
    # est_qty is now inherited from TaskBase (nullable at DB level; PlanTask.clean()
    # enforces non-null in Phase B).

    class Meta:
        db_table = 'plan_tasks'
    # ... rest of the class unchanged
```

- [ ] **Step 3: Add new fields to Task**

In the `Task` class body, after the existing `worker_queue` field and before the `Meta` class, add:

```python
    # Billing fields (Phase A: nullable; Phase B: rate_scheme tightens to NOT NULL).
    rate_scheme = models.ForeignKey(
        'jobs.RateScheme',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='+',
    )
    active_modifiers = models.JSONField(default=list, blank=True)
    actual_qty = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text=(
            "Worker-entered actual quantity for ENTERED_QTY schemes. "
            "Null for ELAPSED_TIME (qty derived from bleps) and FLAT_FEE."
        ),
    )
    # est_qty inherited from TaskBase (nullable on Task).
```

Note: `related_name='+'` prevents Django from creating a reverse accessor `RateScheme.task_set` that would conflict with what we'll add in Phase B (proper `task_set` reverse). We'll fix this in Phase B by removing the `+`.

- [ ] **Step 4: Generate migration**

Run:

```bash
python manage.py makemigrations jobs --name phase_a_add_task_billing_fields
```

Expected: produces `apps/jobs/migrations/0033_phase_a_add_task_billing_fields.py` containing four operations — `AlterField` for `PlanTask.est_qty` (NOT NULL → nullable), `AddField` for `TaskBase.est_qty` on `Task`, `AddField` for `Task.rate_scheme`, `AddField` for `Task.active_modifiers`, `AddField` for `Task.actual_qty`.

- [ ] **Step 5: Inspect the generated migration**

Open `apps/jobs/migrations/0033_phase_a_add_task_billing_fields.py` and confirm:
- It depends on `('jobs', '0032_remove_ratescheme_minimum_charge')`.
- All new Task fields are `null=True, blank=True`.
- The `PlanTask.est_qty` alteration changes the field to nullable.

If makemigrations decided to remove + re-add `est_qty` instead of altering, edit the file to use `migrations.AlterField` for `PlanTask.est_qty` (preserving data).

- [ ] **Step 6: Verify the model loads cleanly**

Run:

```bash
python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 7: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/0033_phase_a_add_task_billing_fields.py
git commit -m "$(cat <<'EOF'
feat(phase-a): add Task billing fields and promote est_qty to TaskBase

Adds Task.rate_scheme (nullable), Task.active_modifiers, Task.actual_qty
as nullable columns. Promotes est_qty from PlanTask onto TaskBase abstract
(nullable at DB level so Task can leave it unset; PlanTask.clean() will
enforce non-null in Phase B). No reader changes yet.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task A2: Data migration backfilling Task fields from TaskCharge

**Files:**
- Create: `apps/jobs/migrations/0034_phase_a_backfill_task_from_taskcharge.py`
- Create: `tests/test_dissolve_taskcharge_phase_a.py`

- [ ] **Step 1: Write the failing backfill verification test**

Create `tests/test_dissolve_taskcharge_phase_a.py`:

```python
from decimal import Decimal
from django.test import TestCase
from django.db import connection

from apps.jobs.models import Task, TaskCharge, RateScheme, Job
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory


class PhaseABackfillTest(TestCase):
    """After Phase A, every Task must have rate_scheme/active_modifiers/actual_qty
    backfilled from its TaskCharge."""

    def setUp(self):
        ac = AccountingCategory.objects.create(name='Labor')
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50.00'), unit_label='hour',
            accounting_category=ac,
        )
        biz = Business.objects.create(business_name='Acme')
        contact = Contact.objects.create(business=biz, first_name='A', last_name='B')
        self.job = Job.objects.create(
            job_number='JOB-2026-0001', contact=contact, status=Job.STATUS_DRAFT,
        )

    def test_backfill_copies_rate_scheme_from_taskcharge(self):
        # Create Task without going through Phase B paths — set fields manually
        # to simulate Phase A starting state (TaskCharge has values, Task does not).
        task = Task.objects.create(job=self.job, name='Bench work')
        TaskCharge.objects.create(
            task=task, rate_scheme=self.scheme,
            active_modifiers=['messy'],
            actuals={'qty': '5.5'},
        )
        # Pre-condition: Task has no billing fields populated.
        task.refresh_from_db()
        self.assertIsNone(task.rate_scheme_id)
        self.assertEqual(task.active_modifiers, [])
        self.assertIsNone(task.actual_qty)

        # Run the backfill (idempotent — call same logic the migration uses).
        from apps.jobs.migrations import _phase_a_backfill_helper
        _phase_a_backfill_helper.run(Task, TaskCharge)

        task.refresh_from_db()
        self.assertEqual(task.rate_scheme_id, self.scheme.pk)
        self.assertEqual(task.active_modifiers, ['messy'])
        self.assertEqual(task.actual_qty, Decimal('5.5'))

    def test_backfill_handles_missing_actuals_qty(self):
        task = Task.objects.create(job=self.job, name='Flat fee')
        scheme_flat = RateScheme.objects.create(
            name='Setup', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('100.00'), unit_label='job',
            accounting_category=self.scheme.accounting_category,
        )
        TaskCharge.objects.create(
            task=task, rate_scheme=scheme_flat,
            active_modifiers=[], actuals={},
        )

        from apps.jobs.migrations import _phase_a_backfill_helper
        _phase_a_backfill_helper.run(Task, TaskCharge)

        task.refresh_from_db()
        self.assertEqual(task.rate_scheme_id, scheme_flat.pk)
        self.assertIsNone(task.actual_qty)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test tests.test_dissolve_taskcharge_phase_a -v 2
```

Expected: `ImportError: cannot import name '_phase_a_backfill_helper'` (the helper doesn't exist yet).

- [ ] **Step 3: Create the backfill helper module**

Create `apps/jobs/migrations/_phase_a_backfill_helper.py` (note: leading underscore so Django's migration loader ignores it):

```python
"""Helper used by the Phase A data migration AND by tests.

Pulled into a module so the migration's RunPython callable can import it
and the test suite can verify the backfill logic against live ORM models.
The migration uses historical models via apps.get_model; the test uses live
ORM. The helper takes both Task and TaskCharge classes as arguments so it
works in both worlds.
"""
from decimal import Decimal, InvalidOperation


def run(Task, TaskCharge):
    """Copy rate_scheme, active_modifiers, actuals.qty from TaskCharge → Task.

    Idempotent. If Task already has rate_scheme set (from a previous run), it
    is left alone. Tasks without a TaskCharge are left alone.
    """
    for charge in TaskCharge.objects.select_related('rate_scheme').all():
        task = charge.task
        # Idempotency: skip if already backfilled.
        if task.rate_scheme_id and task.active_modifiers:
            continue
        task.rate_scheme_id = charge.rate_scheme_id
        task.active_modifiers = list(charge.active_modifiers or [])
        raw_qty = charge.actuals.get('qty') if charge.actuals else None
        if raw_qty not in (None, ''):
            try:
                task.actual_qty = Decimal(str(raw_qty))
            except (InvalidOperation, ValueError):
                task.actual_qty = None
        task.save(update_fields=['rate_scheme', 'active_modifiers', 'actual_qty'])
```

- [ ] **Step 4: Create the data migration**

Create `apps/jobs/migrations/0034_phase_a_backfill_task_from_taskcharge.py`:

```python
from django.db import migrations


def forwards(apps, schema_editor):
    Task = apps.get_model('jobs', 'Task')
    TaskCharge = apps.get_model('jobs', 'TaskCharge')
    from apps.jobs.migrations._phase_a_backfill_helper import run
    run(Task, TaskCharge)


def backwards(apps, schema_editor):
    # Reverse leaves the backfilled Task fields populated. The TaskCharge
    # rows still exist (Phase A doesn't drop them). Re-running forwards
    # would be a no-op because of the idempotency check.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('jobs', '0033_phase_a_add_task_billing_fields'),
    ]
    operations = [
        migrations.RunPython(forwards, backwards),
    ]
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python manage.py test tests.test_dissolve_taskcharge_phase_a -v 2
```

Expected: both tests PASS.

- [ ] **Step 6: Confirm Task.clean() still tolerates the new field shape**

Existing tests should still pass. Spot check:

```bash
python manage.py test tests.test_jobs_models -v 2
```

Expected: PASS. If anything fails because `Task.clean()` is checking `hasattr(self, 'charge')` and the test fixture lacks a TaskCharge, that's a pre-existing test issue unrelated to this change. Don't fix here.

- [ ] **Step 7: Commit**

```bash
git add apps/jobs/migrations/0034_phase_a_backfill_task_from_taskcharge.py \
        apps/jobs/migrations/_phase_a_backfill_helper.py \
        tests/test_dissolve_taskcharge_phase_a.py
git commit -m "$(cat <<'EOF'
feat(phase-a): backfill Task billing fields from TaskCharge

Data migration walks every TaskCharge and copies rate_scheme,
active_modifiers, and actuals.qty (typed as Decimal) onto the corresponding
Task. Helper extracted to apps/jobs/migrations/_phase_a_backfill_helper.py
so the same logic is callable from a test against live ORM models.
Idempotent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## CHECKPOINT — Manual Data Fix Window

> **Stop here.** The plan implementer should pause and verify with the human before proceeding to Phase B. The user will:
>
> 1. Apply migrations 0033 and 0034 to the dev DB (`python manage.py migrate jobs` — only the human runs this).
> 2. Spot-check that every existing Task has `rate_scheme_id` set, `active_modifiers` is a list, and `actual_qty` is set where `TaskCharge.actuals['qty']` had a value.
> 3. If any Task has no TaskCharge (which would leave `rate_scheme_id` null), the user fixes the data — either by deleting the orphan Task, or by creating a TaskCharge for it and re-running the backfill, or by directly setting the new fields via shell. The user owns this step.
> 4. Confirm the dataset is ready for Phase B by signing off in the conversation.
>
> Only then proceed to Phase B.

---

## Phase B — Backend Cleanup

> **Phase B goal:** Switch every reader and writer from TaskCharge to Task. Add `Task.compute_amount`. Add `PlanTask.clean()` for est_qty. Tighten `Task.rate_scheme` to NOT NULL. Drop the TaskCharge model.

### Task B1: Add Task.compute_amount, effective_rate, and effective_accounting_category

**Files:**
- Modify: `apps/jobs/models.py:194-275` (Task class)
- Create: `tests/test_task_compute_amount.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_task_compute_amount.py`:

```python
from decimal import Decimal
from django.test import TestCase

from apps.jobs.models import Task, RateScheme, Blep, Job
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory


class TaskComputeAmountTest(TestCase):
    """Task takes over compute_amount / effective_rate / effective_accounting_category
    that previously lived on TaskCharge."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Labor')
        biz = Business.objects.create(business_name='Acme')
        contact = Contact.objects.create(business=biz, first_name='A', last_name='B')
        self.job = Job.objects.create(
            job_number='JOB-2026-0001', contact=contact, status=Job.STATUS_DRAFT,
        )

    def test_compute_amount_flat_fee(self):
        scheme = RateScheme.objects.create(
            name='Setup', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('100.00'), unit_label='job',
            accounting_category=self.ac,
        )
        task = Task.objects.create(
            job=self.job, name='Setup',
            rate_scheme=scheme, active_modifiers=[],
        )
        self.assertEqual(task.compute_amount(), Decimal('100.00'))

    def test_compute_amount_entered_qty(self):
        scheme = RateScheme.objects.create(
            name='Pieces', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('5.00'), unit_label='piece',
            accounting_category=self.ac,
        )
        task = Task.objects.create(
            job=self.job, name='Polish',
            rate_scheme=scheme, active_modifiers=[],
            actual_qty=Decimal('12'),
        )
        self.assertEqual(task.compute_amount(), Decimal('60.00'))

    def test_compute_amount_returns_zero_when_no_scheme(self):
        # Phase A allowed nullable rate_scheme; we tolerate during transition
        task = Task.objects.create(job=self.job, name='Orphan')
        self.assertEqual(task.compute_amount(), Decimal('0.00'))

    def test_effective_accounting_category_reads_from_scheme(self):
        scheme = RateScheme.objects.create(
            name='Setup', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('100.00'), unit_label='job',
            accounting_category=self.ac,
        )
        task = Task.objects.create(
            job=self.job, name='Setup', rate_scheme=scheme,
        )
        self.assertEqual(task.effective_accounting_category, self.ac)

    def test_effective_rate_applies_modifiers(self):
        scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50.00'), unit_label='hour',
            modifiers=[{'key': 'rush', 'label': 'Rush', 'percent': 20}],
            accounting_category=self.ac,
        )
        task = Task.objects.create(
            job=self.job, name='Rushy',
            rate_scheme=scheme, active_modifiers=['rush'],
        )
        self.assertEqual(task.effective_rate(), Decimal('60.00'))
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test tests.test_task_compute_amount -v 2
```

Expected: `AttributeError: 'Task' object has no attribute 'compute_amount'`.

- [ ] **Step 3: Add compute_amount, effective_rate, effective_accounting_category to Task**

In `apps/jobs/models.py`, replace the existing `Task.effective_accounting_category` property and add the new methods:

```python
    @property
    def effective_accounting_category(self):
        if not self.rate_scheme_id:
            return None
        return self.rate_scheme.accounting_category

    def compute_amount(self, active_modifiers=None):
        """Uniform atom interface: total billable amount for this task.

        Ignores the active_modifiers argument (uses self.active_modifiers).
        Parameter is accepted to match the BillableAtom interface shared
        with PlanTask/Material/PlanMaterial.
        Returns Decimal('0.00') when rate_scheme is unset.
        """
        from decimal import Decimal
        if not self.rate_scheme_id:
            return Decimal('0.00')
        qty = self.rate_scheme.get_actual_qty(self)
        return self.rate_scheme.compute_charge(qty, self.active_modifiers)

    def effective_rate(self):
        if not self.rate_scheme_id:
            return None
        return self.rate_scheme.effective_rate(self.active_modifiers)
```

- [ ] **Step 4: Update RateScheme.get_actual_qty to read Task.actual_qty**

Still in `apps/jobs/models.py`, update `RateScheme.get_actual_qty`:

```python
    def get_actual_qty(self, task):
        """Resolve actual quantity based on algorithm."""
        if self.algorithm == self.ELAPSED_TIME:
            total_seconds = sum(
                b.elapsed.total_seconds()
                for b in task.blep_set.all() if b.elapsed is not None
            )
            return Decimal(total_seconds) / 3600
        elif self.algorithm == self.ENTERED_QTY:
            return task.actual_qty or Decimal('0')
        else:  # FLAT_FEE
            return Decimal('1')
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python manage.py test tests.test_task_compute_amount -v 2
```

Expected: PASS.

- [ ] **Step 6: Run the broader jobs/billing tests to confirm no regressions**

```bash
python manage.py test tests.test_jobs_models tests.test_atom_compute_amount -v 2
```

Expected: PASS. Note: `test_atom_compute_amount` may have tests pinned to TaskCharge.compute_amount — those will be updated in a later task. If any FAIL with `task.charge.compute()` still being read, that's expected; we'll fix in B5.

If `test_atom_compute_amount` fails, note which assertions, and move on. They'll be fixed in B5.

- [ ] **Step 7: Commit**

```bash
git add apps/jobs/models.py tests/test_task_compute_amount.py
git commit -m "$(cat <<'EOF'
feat(phase-b): Task gets compute_amount/effective_rate; RateScheme reads actual_qty

Task takes over the billable-atom interface (compute_amount, effective_rate,
effective_accounting_category) that previously lived on TaskCharge.
RateScheme.get_actual_qty reads task.actual_qty (typed Decimal) for
ENTERED_QTY schemes instead of task.charge.actuals['qty'] (JSON).

TaskCharge still exists; readers haven't all switched yet.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B2: Update RateScheme.is_referenced and reference_counts to count Task

**Files:**
- Modify: `apps/jobs/models.py:410-427` (RateScheme reference helpers)
- Modify: `tests/test_rate_scheme.py` (extend existing)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_rate_scheme.py` (or create if missing — check first with `ls tests/test_rate_scheme*.py`):

```python
def test_is_referenced_counts_task_not_taskcharge(self):
    """After Phase B, RateScheme.is_referenced checks Task instead of TaskCharge."""
    from apps.jobs.models import Task, RateScheme, Job
    from apps.contacts.models import Contact, Business
    from apps.core.models import AccountingCategory

    ac = AccountingCategory.objects.create(name='Labor')
    scheme = RateScheme.objects.create(
        name='Test', algorithm=RateScheme.FLAT_FEE,
        rate=Decimal('10.00'), unit_label='job',
        accounting_category=ac,
    )
    self.assertFalse(scheme.is_referenced())

    biz = Business.objects.create(business_name='X')
    c = Contact.objects.create(business=biz, first_name='A', last_name='B')
    job = Job.objects.create(
        job_number='JOB-T1', contact=c, status=Job.STATUS_DRAFT,
    )
    Task.objects.create(job=job, name='Direct', rate_scheme=scheme)

    self.assertTrue(scheme.is_referenced())
    counts = scheme.reference_counts()
    self.assertEqual(counts['task_count'], 1)
    self.assertNotIn('task_charge_count', counts)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test tests.test_rate_scheme.RateSchemeTest.test_is_referenced_counts_task_not_taskcharge -v 2
```

Expected: FAIL with KeyError on `'task_count'` (current code returns `'task_charge_count'`).

- [ ] **Step 3: Update is_referenced and reference_counts**

In `apps/jobs/models.py`, replace these two methods on `RateScheme`:

```python
    def is_referenced(self):
        """True if any PlanTask, Task, or TaskTemplate points at this scheme."""
        from apps.estimates.models import TaskTemplate
        if PlanTask.objects.filter(rate_scheme=self).exists():
            return True
        if Task.objects.filter(rate_scheme=self).exists():
            return True
        if TaskTemplate.objects.filter(rate_scheme=self).exists():
            return True
        return False

    def reference_counts(self):
        """Return reference counts for the outdated-schemes UI."""
        from apps.estimates.models import TaskTemplate
        return {
            'plan_task_count': PlanTask.objects.filter(rate_scheme=self).count(),
            'task_count': Task.objects.filter(rate_scheme=self).count(),
            'task_template_count': TaskTemplate.objects.filter(rate_scheme=self).count(),
        }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python manage.py test tests.test_rate_scheme.RateSchemeTest.test_is_referenced_counts_task_not_taskcharge -v 2
```

Expected: PASS.

- [ ] **Step 5: Run the rest of the rate_scheme tests for regressions**

```bash
python manage.py test tests.test_rate_scheme tests.test_rate_scheme_api -v 2
```

Expected: most pass. Any test that asserts `'task_charge_count'` is in `reference_counts()` output should be updated to `'task_count'` here too — find them with:

```bash
grep -rn "task_charge_count" tests/
```

Update each occurrence to `task_count`.

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/models.py tests/
git commit -m "$(cat <<'EOF'
feat(phase-b): RateScheme references count Task, not TaskCharge

is_referenced and reference_counts switch from filter(TaskCharge,
rate_scheme=self) to filter(Task, rate_scheme=self). The semantic is
identical — every TaskCharge had exactly one Task — but the new query
matches the model where rate_scheme will live after this refactor.
Outdated-schemes UI will see task_count instead of task_charge_count.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B3: Add PlanTask.clean() enforcement of est_qty

**Files:**
- Modify: `apps/jobs/models.py:143-192` (PlanTask class)
- Create: `tests/test_plan_task_est_qty_required.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_plan_task_est_qty_required.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.jobs.models import PlanTask, RateScheme, Job, Task
from apps.estimates.models import EstWorksheet
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory


class PlanTaskEstQtyRequiredTest(TestCase):
    """PlanTask.clean() rejects null est_qty at the application layer.
    Task.clean() accepts null est_qty (asymmetric enforcement).
    """

    def setUp(self):
        ac = AccountingCategory.objects.create(name='Labor')
        self.scheme = RateScheme.objects.create(
            name='Setup', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('100.00'), unit_label='job',
            accounting_category=ac,
        )
        biz = Business.objects.create(business_name='X')
        c = Contact.objects.create(business=biz, first_name='A', last_name='B')
        self.job = Job.objects.create(
            job_number='JOB-PT1', contact=c, status=Job.STATUS_DRAFT,
        )
        self.ws = EstWorksheet.objects.create(job=self.job)

    def test_plantask_rejects_null_est_qty(self):
        with self.assertRaises(ValidationError) as cm:
            PlanTask.objects.create(
                est_worksheet=self.ws, name='Bad',
                rate_scheme=self.scheme, est_qty=None,
            )
        self.assertIn('est_qty', cm.exception.message_dict)

    def test_plantask_accepts_non_null_est_qty(self):
        pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Good',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        self.assertEqual(pt.est_qty, Decimal('1'))

    def test_task_accepts_null_est_qty(self):
        # Task is the asymmetric side — null is fine.
        t = Task.objects.create(
            job=self.job, name='Looser',
            rate_scheme=self.scheme,
            est_qty=None,
        )
        self.assertIsNone(t.est_qty)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test tests.test_plan_task_est_qty_required -v 2
```

Expected: `test_plantask_rejects_null_est_qty` FAILS — currently PlanTask accepts null because the field is now nullable at DB level and there's no clean() check.

- [ ] **Step 3: Add the clean() rule on PlanTask**

In `apps/jobs/models.py`, add `clean()` to `PlanTask`:

```python
    def clean(self):
        super().clean()
        if self.est_qty is None:
            raise ValidationError({
                'est_qty': 'Required: every PlanTask must have an estimated quantity.',
            })
```

(The `ValidationError` import is already at the top of the file.)

- [ ] **Step 4: Run test to verify it passes**

```bash
python manage.py test tests.test_plan_task_est_qty_required -v 2
```

Expected: all three PASS.

- [ ] **Step 5: Run worksheet/PlanTask tests for regressions**

```bash
python manage.py test tests.test_jobs_models tests.test_carry_over -v 2
```

Expected: PASS. If anything fails because a test creates a PlanTask without est_qty, fix the test by passing `est_qty=Decimal('1')` (or whatever fits the test's intent).

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/models.py tests/test_plan_task_est_qty_required.py tests/
git commit -m "$(cat <<'EOF'
feat(phase-b): PlanTask.clean() enforces non-null est_qty

est_qty is now nullable at the DB level (TaskBase declaration), so the
worksheet-side requirement is enforced in clean() instead of via the
schema. Same two-layer pattern Task uses for "must have a TaskCharge".
Task.clean() continues to accept null est_qty.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B4: Update TaskService and carry-over to write Task fields directly

**Files:**
- Modify: `apps/jobs/services.py:330-424` (TaskService.copy_from_worksheet, create_from_template, create_direct)
- Modify: `apps/estimates/carry_over.py:46-129` (_carry_over_plan_tasks, _create_task_from_line_item)
- Modify: `apps/estimates/models.py:429-469` (TaskTemplate.generate_task)
- Create: `tests/test_task_est_qty_carry_over.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_task_est_qty_carry_over.py`:

```python
from decimal import Decimal
from django.test import TestCase

from apps.jobs.models import Task, PlanTask, RateScheme, Job
from apps.estimates.models import EstWorksheet, TaskTemplate
from apps.estimates.carry_over import AtomCarryOverService
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory


class TaskEstQtyCarryOverTest(TestCase):
    """Phase B carry-over: PlanTask.est_qty lands on Task.est_qty for ALL algorithms."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Labor')
        biz = Business.objects.create(business_name='Y')
        c = Contact.objects.create(business=biz, first_name='A', last_name='B')
        self.job = Job.objects.create(
            job_number='JOB-CO1', contact=c, status=Job.STATUS_DRAFT,
        )
        self.ws = EstWorksheet.objects.create(job=self.job)

    def _create_pt(self, scheme, est_qty):
        return PlanTask.objects.create(
            est_worksheet=self.ws, name='X',
            rate_scheme=scheme, active_modifiers=[],
            est_qty=est_qty,
        )

    def test_carry_over_elapsed_time_sets_task_est_qty(self):
        scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50'), unit_label='hour',
            accounting_category=self.ac,
        )
        pt = self._create_pt(scheme, Decimal('5'))
        AtomCarryOverService._carry_over_plan_tasks(self.ws, self.job)
        task = Task.objects.get(source_plan_task=pt)
        self.assertEqual(task.est_qty, Decimal('5'))
        self.assertIsNone(task.actual_qty)  # estimate, not actual

    def test_carry_over_entered_qty_sets_task_est_qty(self):
        scheme = RateScheme.objects.create(
            name='Pieces', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('5'), unit_label='piece',
            accounting_category=self.ac,
        )
        pt = self._create_pt(scheme, Decimal('12'))
        AtomCarryOverService._carry_over_plan_tasks(self.ws, self.job)
        task = Task.objects.get(source_plan_task=pt)
        self.assertEqual(task.est_qty, Decimal('12'))
        # actual_qty is null at carry-over — worker enters it later
        self.assertIsNone(task.actual_qty)

    def test_template_generate_task_for_job_persists_est_qty(self):
        scheme = RateScheme.objects.create(
            name='T', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('100'), unit_label='job',
            accounting_category=self.ac,
        )
        template = TaskTemplate.objects.create(
            template_name='Setup',
            rate_scheme=scheme,
            default_billable_qty=Decimal('1'),
        )
        task = template.generate_task(self.job, est_qty=Decimal('3'))
        self.assertEqual(task.est_qty, Decimal('3'))
        self.assertEqual(task.rate_scheme_id, scheme.pk)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test tests.test_task_est_qty_carry_over -v 2
```

Expected: all three FAIL — `task.est_qty` is None because no code path currently sets it on Task.

- [ ] **Step 3: Update `_carry_over_plan_tasks`**

In `apps/estimates/carry_over.py`, replace the body of `_carry_over_plan_tasks`:

```python
    @staticmethod
    def _carry_over_plan_tasks(worksheet, job):
        from apps.jobs.models import PlanTask, Task
        count = 0
        for pt in PlanTask.objects.filter(
            est_worksheet=worksheet,
        ).select_related('rate_scheme'):
            if Task.objects.filter(job=job, source_plan_task=pt).exists():
                continue
            Task.objects.create(
                job=job,
                name=pt.name,
                description=pt.description,
                source_plan_task=pt,
                rate_scheme=pt.rate_scheme,
                active_modifiers=list(pt.active_modifiers or []),
                est_qty=pt.est_qty,
                est_worker_time=pt.est_worker_time,
                actual_qty=None,
            )
            count += 1
        return count
```

Note: TaskCharge is no longer created here. The legacy "carry as a Task without a TaskCharge" branch is also gone (it was a workaround for unpriced PlanTasks; PlanTask now requires rate_scheme).

- [ ] **Step 4: Update `_create_task_from_line_item`**

In `apps/estimates/carry_over.py`:

```python
    @staticmethod
    def _create_task_from_line_item(line_item, job):
        from apps.jobs.models import Task
        template = line_item.source_template
        if Task.objects.filter(job=job, source_template=template).exists():
            return False
        Task.objects.create(
            job=job,
            name=template.template_name,
            description=template.description or '',
            source_template=template,
            rate_scheme=template.rate_scheme,
            active_modifiers=list(template.default_active_modifiers or []),
            est_qty=line_item.qty,
            est_worker_time=None,
            actual_qty=None,
        )
        return True
```

The `from apps.jobs.models import RateScheme, Task, TaskCharge` import becomes `from apps.jobs.models import Task` (RateScheme isn't referenced; TaskCharge is gone). Update the import line accordingly.

- [ ] **Step 5: Update `TaskTemplate.generate_task` (Job branch)**

In `apps/estimates/models.py`, replace the Job-container branch of `TaskTemplate.generate_task`:

```python
        if isinstance(container, Job):
            with transaction.atomic():
                task = Task.objects.create(
                    job=container,
                    name=self.template_name,
                    description=self.description,
                    assignee=assignee,
                    sort_order=sort_order,
                    rate_scheme=self.rate_scheme,
                    active_modifiers=list(self.default_active_modifiers or []),
                    est_qty=est_qty,
                )
            return task
```

Update the import at the top of the function: drop `TaskCharge` from `from apps.jobs.models import Job, Task, PlanTask, TaskCharge` → `from apps.jobs.models import Job, Task, PlanTask`.

- [ ] **Step 6: Update `TaskService.copy_from_worksheet`**

In `apps/jobs/services.py:330-358`, replace the inner loop:

```python
        for plan_task in PlanTask.objects.filter(
            est_worksheet=ws
        ).prefetch_related('plan_materials'):
            new_task = Task.objects.create(
                job=job,
                name=plan_task.name,
                description=plan_task.description,
                sort_order=plan_task.sort_order,
                rate_scheme=plan_task.rate_scheme,
                active_modifiers=list(plan_task.active_modifiers or []),
                est_qty=plan_task.est_qty,
                est_worker_time=plan_task.est_worker_time,
            )
            for pm in plan_task.plan_materials.all():
                MaterialService.create_on_job(
                    job=job, task=new_task,
                    description=pm.description,
                    quantity=pm.quantity,
                    unit_cost=pm.unit_cost,
                    sell_price=pm.sell_price,
                    price_list_item=pm.price_list_item,
                    accounting_category=pm.accounting_category,
                )
```

(The `from apps.jobs.models import TaskCharge` import inside the function and the `TaskCharge.objects.create(...)` block both come out.)

- [ ] **Step 7: Update `TaskService.create_from_template` and `TaskService.create_direct`**

In `apps/jobs/services.py:373-424`, replace both methods:

```python
class TaskService:
    """Service class for Task creation workflows."""

    @staticmethod
    def create_from_template(template, job, assignee=None, est_qty=None):
        from apps.core.services import SchemeSupersededError

        if not template.is_active:
            raise ValidationError(f"Template {template.template_name} is not active.")
        if template.rate_scheme_id and template.rate_scheme.replaced_by_id is not None:
            raise SchemeSupersededError(
                f'Template "{template.template_name}" references a superseded RateScheme.'
            )
        if not template.rate_scheme_id:
            raise ValidationError(
                f'Template "{template.template_name}" has no rate_scheme.'
            )
        with transaction.atomic():
            task = Task.objects.create(
                job=job,
                name=template.template_name,
                assignee=assignee,
                rate_scheme=template.rate_scheme,
                active_modifiers=list(template.default_active_modifiers or []),
                est_qty=est_qty if est_qty is not None else template.default_billable_qty,
            )
        return task

    @staticmethod
    def create_direct(job, name, rate_scheme_id=None, active_modifiers=None,
                      est_qty=None, est_worker_time=None, actual_qty=None,
                      **task_fields):
        """Create Task directly. Requires rate_scheme_id."""
        if not rate_scheme_id:
            raise ValidationError({'rate_scheme': 'Required.'})
        scheme = RateScheme.objects.get(pk=rate_scheme_id)
        if scheme.replaced_by_id is not None:
            raise ValidationError(
                {'rate_scheme': 'Selected RateScheme is superseded.'}
            )
        with transaction.atomic():
            task = Task.objects.create(
                job=job, name=name,
                rate_scheme=scheme,
                active_modifiers=active_modifiers or [],
                est_qty=est_qty,
                est_worker_time=est_worker_time,
                actual_qty=actual_qty,
                **task_fields,
            )
        return task
```

- [ ] **Step 8: Update the labor-cost reader**

Find `apps/jobs/services.py:985`:

```python
                rate = blep.task.charge.rate_scheme.rate
            except (TaskCharge.DoesNotExist, AttributeError):
```

Replace with:

```python
                rate = blep.task.rate_scheme.rate
            except AttributeError:
```

Update the imports at the top of the file: drop `TaskCharge` from `from apps.jobs.models import Job, Task, Blep, RateScheme, TaskCharge` → `from apps.jobs.models import Job, Task, Blep, RateScheme`.

- [ ] **Step 9: Run tests**

```bash
python manage.py test tests.test_task_est_qty_carry_over tests.test_carry_over tests.test_jobs_services -v 2
```

Expected: PASS. If existing tests fail because they assert the old TaskCharge shape, update them — change `task.charge.rate_scheme` to `task.rate_scheme`, `task.charge.actuals['qty']` to `task.actual_qty`, etc.

- [ ] **Step 10: Commit**

```bash
git add apps/jobs/services.py apps/estimates/carry_over.py apps/estimates/models.py \
        tests/test_task_est_qty_carry_over.py tests/
git commit -m "$(cat <<'EOF'
feat(phase-b): carry-over and Task creation paths set fields directly on Task

_carry_over_plan_tasks, _create_task_from_line_item, TaskTemplate.generate_task
(Job branch), TaskService.create_from_template, TaskService.create_direct,
and TaskService.copy_from_worksheet all now write rate_scheme/active_modifiers/
est_qty/est_worker_time/actual_qty directly on Task. No TaskCharge.objects.create
calls remain in any of these paths.

est_qty carries from PlanTask to Task for ALL algorithms (not just ENTERED_QTY).
TaskTemplate.generate_task's est_qty argument is finally honored when the
container is a Job.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B5: Update invoice wizard to read from Task instead of charge

**Files:**
- Modify: `apps/invoicing/services.py:175-450` (WizardAtomLabels and InvoiceWizardService helpers)
- Modify: `tests/test_invoice_wizard_*.py` (extend / fix)

- [ ] **Step 1: Survey what needs to change**

Run:

```bash
grep -n "charge\." apps/invoicing/services.py
```

Note every `charge.` and `task.charge` reference. Each one needs to switch to a corresponding direct Task attribute.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_invoice_wizard_per_task_atoms.py` (create the file if it doesn't exist):

```python
from decimal import Decimal
from django.test import TestCase

from apps.jobs.models import Task, RateScheme, Job
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory
from apps.invoicing.models import Invoice
from apps.invoicing.services import InvoiceWizardService


class WizardReadsTaskDirectlyTest(TestCase):
    """Phase B: wizard atom rendering uses task.compute_amount and
    task.rate_scheme, not task.charge.*."""

    def setUp(self):
        ac = AccountingCategory.objects.create(name='Labor')
        biz = Business.objects.create(business_name='Z')
        c = Contact.objects.create(business=biz, first_name='A', last_name='B')
        self.job = Job.objects.create(
            job_number='JOB-WIZ', contact=c, status=Job.STATUS_APPROVED,
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('5.00'), unit_label='piece',
            accounting_category=ac,
        )
        self.task = Task.objects.create(
            job=self.job, name='Polish',
            rate_scheme=self.scheme, active_modifiers=[],
            est_qty=Decimal('12'), actual_qty=Decimal('12'),
        )
        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT,
        )

    def test_source_pool_reads_task_directly(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        # Find our task in the tree
        task_entry = next(
            t for t in pool['tasks']
            if t['task_id'] == self.task.pk
        )
        self.assertEqual(len(task_entry['atoms']), 1)
        atom = task_entry['atoms'][0]
        self.assertEqual(atom['atom_type'], 'task')
        self.assertEqual(atom['atom_id'], self.task.pk)
        self.assertEqual(atom['computed_amount'], Decimal('60.00'))
        self.assertIn('Polish', atom['description'])
        self.assertIn('Hourly', atom['description'])  # scheme name in label
        self.assertIn('12', atom['sub_info'])  # qty source label
```

- [ ] **Step 3: Run test to verify it fails (or note current failure)**

```bash
python manage.py test tests.test_invoice_wizard_per_task_atoms -v 2
```

If you wrote a new test, expected: FAIL because `task.charge` doesn't exist on a Task without a TaskCharge — and Phase B Task creation paths no longer create TaskCharges.

If existing tests are now failing for the same reason (good — we know what to fix), proceed to Step 4.

- [ ] **Step 4: Replace charge.* with direct task.* in InvoiceWizardService**

In `apps/invoicing/services.py`:

Replace `WizardAtomLabels.qty_source_label`:

```python
class WizardAtomLabels:
    @staticmethod
    def qty_source_label(task):
        """Describe where the billable quantity came from for a Task atom."""
        scheme = task.rate_scheme
        if scheme.algorithm == 'elapsed_time':
            qty = scheme.get_actual_qty(task)
            return f'{qty:.2f} {scheme.unit_label} from bleps'
        if scheme.algorithm == 'entered_qty':
            qty = scheme.get_actual_qty(task)
            return f'{qty} {scheme.unit_label} entered'
        return 'flat fee'
```

Replace the per-task atom block in `get_source_pool`:

```python
        tasks = (
            Task.objects.filter(job=job)
            .exclude(status=Task.STATUS_CANCELLED)
            .select_related('rate_scheme')
            .order_by('sort_order', 'pk')
        )
        task_list = []
        for task in tasks:
            atoms = []

            if task.rate_scheme_id:
                amount = task.compute_amount().quantize(Decimal('0.01'))
                key = (InvoiceLineItemSource.SOURCE_TASK, task.pk)
                state_info = claims.get(key, default_state)
                atoms.append({
                    'atom_type': 'task',
                    'atom_id': task.pk,
                    'description': f'{task.name} ({task.rate_scheme.name})',
                    'sub_info': WizardAtomLabels.qty_source_label(task),
                    'computed_amount': amount,
                    **state_info,
                })

            # Material atoms (unchanged)
            materials = (
                Material.objects.filter(task=task, quantity__gt=0)
                .order_by('pk')
            )
            for mat in materials:
                # ... unchanged ...
```

Replace `_atom_computed_amount`:

```python
    @staticmethod
    def _atom_computed_amount(atom_instance):
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        if isinstance(atom_instance, Task):
            return atom_instance.compute_amount().quantize(Decimal('0.01'))
        if isinstance(atom_instance, Material):
            return (atom_instance.quantity * atom_instance.sell_price).quantize(Decimal('0.01'))
        raise ValueError(f"Unknown atom instance type: {type(atom_instance)}")
```

Replace `_atom_units`:

```python
    @staticmethod
    def _atom_units(atom_instance):
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        if isinstance(atom_instance, Task):
            if atom_instance.rate_scheme_id:
                return atom_instance.rate_scheme.unit_label
            return 'none'
        if isinstance(atom_instance, Material):
            if atom_instance.price_list_item_id:
                return atom_instance.price_list_item.units
            return 'none'
        return 'none'
```

`_atom_category` reads `task.effective_accounting_category` which already works (we updated that property in B1). No change needed.

- [ ] **Step 5: Run all invoice wizard tests**

```bash
python manage.py test tests.test_invoice_wizard_per_task_atoms tests.test_invoice_wizard_service tests.test_invoice_wizard_api -v 2
```

Expected: PASS. Update any tests that assert via `task.charge.*` — change them to `task.*` directly.

- [ ] **Step 6: Run the full test suite for regressions**

```bash
python manage.py test -v 1
```

Expected: PASS. Note any `task.charge` failures and fix them in the same commit. Common culprits: assertions in `tests/test_atom_compute_amount.py`, `tests/test_invoice_line_item_source.py`, `tests/test_board_service.py`.

- [ ] **Step 7: Commit**

```bash
git add apps/invoicing/services.py tests/
git commit -m "$(cat <<'EOF'
feat(phase-b): invoice wizard reads from Task directly

InvoiceWizardService.get_source_pool, _atom_computed_amount, _atom_units,
WizardAtomLabels.qty_source_label all switch from task.charge.* to task.*.
The wizard's source rows already key on Task PK (SOURCE_TASK) — no source
row migration needed. compute_amount calls go through Task instead of
TaskCharge.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B6: Update Task and PlanTask serializers

**Files:**
- Modify: `apps/api/tasks/serializers.py` (entire file rewrite-ish)
- Modify: `apps/api/plan_tasks/serializers.py` (verify est_qty)

- [ ] **Step 1: Survey existing serializer**

Read `apps/api/tasks/serializers.py` end to end. Identify what the frontend depends on. Key fields exposed today:

- TaskSerializer fields: `task_id`, `name`, `description`, `sort_order`, `status`, `blocked_reason`, `parent_task`, `assignee`, `assignee_name`, `worker_queue`, `charge` (nested), `actual_hours`, `estimated_hours`.
- TaskDetailSerializer adds `job` nested.
- The `_estimated_hours(task)` helper reads `task.source_plan_task.est_qty` — workaround.
- The `_serialize_charge(obj)` helper returns `TaskChargeReadSerializer(charge).data`.

- [ ] **Step 2: Write the failing test**

Extend `tests/test_api_job_tasklist.py` with (use the existing test class's `setUp` / authenticated client / `self.job`):

```python
def test_task_serializer_flattens_billing_fields(self):
    """Phase B: rate_scheme, active_modifiers, est_qty, est_worker_time,
    actual_qty are top-level fields. 'charge' is no longer in the payload."""
    from decimal import Decimal
    from apps.jobs.models import Task, RateScheme
    from apps.core.models import AccountingCategory

    ac = AccountingCategory.objects.create(name='Labor')
    scheme = RateScheme.objects.create(
        name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
        rate=Decimal('50'), unit_label='hour',
        accounting_category=ac,
    )
    Task.objects.create(
        job=self.job, name='Test',
        rate_scheme=scheme, active_modifiers=['rush'],
        est_qty=Decimal('5'),
    )
    resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/')
    self.assertEqual(resp.status_code, 200)
    body = resp.json()
    payload = body['results'] if isinstance(body, dict) and 'results' in body else body
    row = next(t for t in payload if t['name'] == 'Test')
    self.assertEqual(row['rate_scheme'], scheme.pk)
    self.assertEqual(row['active_modifiers'], ['rush'])
    self.assertEqual(row['est_qty'], '5.00')
    self.assertIsNone(row['actual_qty'])
    self.assertNotIn('charge', row)
```

- [ ] **Step 3: Run test to verify it fails**

```bash
python manage.py test tests.test_api_job_tasklist -v 2
```

Expected: FAIL because `'charge'` is still nested.

- [ ] **Step 4: Rewrite TaskSerializer**

Replace `apps/api/tasks/serializers.py` content (preserve MaterialSerializer / MaterialWriteSerializer at top — only change task-related serializers):

```python
from rest_framework import serializers

from apps.jobs.models import Task, RateScheme
from apps.inventory.models import Material


# (MaterialSerializer + MaterialWriteSerializer unchanged — keep them.)


class TaskSerializer(serializers.ModelSerializer):
    """Serializer for tasks nested under /api/jobs/{id}/tasks/."""
    assignee_name = serializers.SerializerMethodField()
    actual_hours = serializers.SerializerMethodField()
    scheme_name = serializers.CharField(source='rate_scheme.name', read_only=True, default=None)
    scheme_algorithm = serializers.CharField(source='rate_scheme.algorithm', read_only=True, default=None)
    scheme_unit_label = serializers.CharField(source='rate_scheme.unit_label', read_only=True, default=None)
    effective_rate = serializers.SerializerMethodField()
    computed_charge = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'sort_order', 'status',
            'blocked_reason',
            'parent_task', 'assignee', 'assignee_name', 'worker_queue',
            'rate_scheme', 'active_modifiers',
            'est_qty', 'est_worker_time', 'actual_qty',
            'scheme_name', 'scheme_algorithm', 'scheme_unit_label',
            'effective_rate', 'computed_charge',
            'actual_hours',
        ]
        read_only_fields = ['task_id', 'sort_order', 'status']

    def get_assignee_name(self, obj):
        if obj.assignee:
            name = obj.assignee.get_full_name()
            return name if name else obj.assignee.username
        return None

    def get_actual_hours(self, obj):
        total_seconds = sum(
            b.elapsed.total_seconds()
            for b in obj.blep_set.all() if b.elapsed is not None
        )
        return round(total_seconds / 3600.0, 2)

    def get_effective_rate(self, obj):
        rate = obj.effective_rate()
        return str(rate) if rate is not None else None

    def get_computed_charge(self, obj):
        try:
            return str(obj.compute_amount())
        except Exception:
            return None


class TaskDetailSerializer(TaskSerializer):
    job = serializers.SerializerMethodField()

    class Meta(TaskSerializer.Meta):
        fields = TaskSerializer.Meta.fields + ['job']

    def get_job(self, obj):
        job = obj.job
        return {
            'id': job.pk,
            'job_number': job.job_number,
            'name': job.name,
            'status': job.status,
        }
```

The `TaskChargeSerializer`, `TaskChargeReadSerializer`, `_serialize_charge`, `_actual_hours`, `_estimated_hours` helpers all go away. The `estimated_hours` field is replaced by direct `est_qty` (callers can interpret via `scheme_unit_label`).

- [ ] **Step 5: Verify PlanTask serializer**

Open `apps/api/plan_tasks/serializers.py`. Confirm `est_qty` is in the field list. After moving the field declaration to TaskBase, DRF still picks it up via Meta.model = PlanTask. Run:

```bash
python manage.py test tests.test_api_worksheet_plan_tasks -v 2
```

Expected: PASS. If anything fails, the serializer's field list may need an explicit `est_qty` entry — add it.

- [ ] **Step 6: Run task-list tests**

```bash
python manage.py test tests.test_api_job_tasklist tests.test_task_serializer_flatten -v 2
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/tasks/serializers.py apps/api/plan_tasks/serializers.py tests/
git commit -m "$(cat <<'EOF'
feat(phase-b): flatten Task serializer; drop TaskCharge nested + estimated_hours hack

TaskSerializer / TaskDetailSerializer surface rate_scheme, active_modifiers,
est_qty, est_worker_time, actual_qty as top-level fields. scheme_name /
scheme_algorithm / scheme_unit_label / effective_rate / computed_charge are
denormalized for client display.

The _estimated_hours workaround (which reached through source_plan_task.est_qty
and only worked for ELAPSED_TIME) is removed — callers use the now-direct
task.est_qty + scheme_unit_label.

TaskChargeSerializer / TaskChargeReadSerializer deleted.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B7: Update Task API views to accept the new flat payload

**Files:**
- Modify: `apps/api/tasks/views.py` (Task POST/PATCH paths, drop task_charge_view)
- Modify: `apps/api/jobs/views.py` (`add_from_template` action — pass est_qty)
- Modify: `apps/api/worksheets/views.py` (worksheet add-task — accept est_worker_time)
- Modify: `apps/api/urls.py` (drop the `/charge/` URL)

- [ ] **Step 1: Survey current accepted payload shape**

```bash
grep -n "request\.data\|actuals\|rate_scheme" apps/api/tasks/views.py apps/api/jobs/views.py apps/api/worksheets/views.py
```

Note where `actuals` is parsed and where `rate_scheme` is set on creation.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_api_job_tasklist.py` (use the existing test class's setUp / authenticated client):

```python
def test_post_task_accepts_flat_billing_fields(self):
    """POST /api/jobs/<id>/tasks/ accepts rate_scheme, active_modifiers,
    est_qty, est_worker_time, actual_qty as direct fields (not nested in
    'actuals')."""
    from decimal import Decimal
    from apps.jobs.models import Task, RateScheme
    from apps.core.models import AccountingCategory

    ac = AccountingCategory.objects.create(name='Labor')
    scheme = RateScheme.objects.create(
        name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
        rate=Decimal('50'), unit_label='hour',
        accounting_category=ac,
    )
    payload = {
        'name': 'Bench work',
        'description': 'Test',
        'rate_scheme': scheme.pk,
        'active_modifiers': [],
        'est_qty': '5.00',
        'est_worker_time': 'PT5H',
    }
    resp = self.client.post(
        f'/api/jobs/{self.job.pk}/tasks/', payload,
        content_type='application/json',
    )
    self.assertEqual(resp.status_code, 201)
    task = Task.objects.get(pk=resp.json()['task_id'])
    self.assertEqual(task.rate_scheme_id, scheme.pk)
    self.assertEqual(task.est_qty, Decimal('5.00'))
    self.assertIsNotNone(task.est_worker_time)
    self.assertIsNone(task.actual_qty)
```

(`self.client` and `self.job` come from the existing test class's setUp — verify and adjust if your local class uses different attribute names.)

- [ ] **Step 3: Run test to verify it fails**

Expected: FAIL — current code likely puts `est_qty` into `actuals`.

- [ ] **Step 4: Update the Task POST/PATCH handler**

Find the relevant handler in `apps/api/tasks/views.py` (or wherever Task creation lives — possibly `apps/api/jobs/views.py:tasks` action via JobTaskMixin). Update to pass:

- `rate_scheme` → `rate_scheme_id`
- `active_modifiers` → `active_modifiers`
- `est_qty` → `est_qty`
- `est_worker_time` → `est_worker_time`
- `actual_qty` → `actual_qty`

To `TaskService.create_direct(...)`. Drop any `actuals: { qty: ... }` parsing.

- [ ] **Step 5: Drop the task_charge_view function and URL**

In `apps/api/tasks/views.py`, delete the `task_charge_view` function (lines ~212-252).

In `apps/api/urls.py`, delete:

```python
from apps.api.tasks.views import TaskViewSet, task_charge_view
```

becomes:

```python
from apps.api.tasks.views import TaskViewSet
```

And delete the `path('jobs/<int:job_pk>/tasks/<int:task_pk>/charge/', task_charge_view, name='task-charge'),` line.

- [ ] **Step 6: Update `add_from_template` to forward est_qty into the new path**

In `apps/api/jobs/views.py` `add_from_template` action, the existing code calls `template.generate_task(job, est_qty)` which we updated in Task B4 to actually store the est_qty. Confirm the call site already passes est_qty (it does — `apps/api/jobs/views.py:313`). No further change needed here.

- [ ] **Step 7: Update worksheet add-task to accept `est_worker_time`**

In `apps/api/worksheets/views.py` add-plan-task action, ensure `est_worker_time` from `request.data` is passed through to `PlanTask.objects.create(...)`. If the existing serializer drives the create (most likely), the field should already flow through — confirm with a test.

- [ ] **Step 8: Run tests**

```bash
python manage.py test tests.test_api_job_tasklist tests.test_api_bleps tests.test_task_lifecycle_api -v 2
```

Expected: PASS. Update any test that posts `actuals: {qty: ...}` to instead post `est_qty: ...`.

- [ ] **Step 9: Commit**

```bash
git add apps/api/tasks/views.py apps/api/jobs/views.py apps/api/worksheets/views.py \
        apps/api/urls.py tests/
git commit -m "$(cat <<'EOF'
feat(phase-b): API accepts flat Task billing payload

Task POST/PATCH endpoints accept rate_scheme, active_modifiers, est_qty,
est_worker_time, actual_qty as direct fields. The 'actuals: {qty: ...}'
JSON shape is no longer accepted (and no longer needed — it was a
workaround for the missing est_qty field).

The /api/jobs/{job_pk}/tasks/{task_pk}/charge/ endpoint and its
task_charge_view backend are deleted (no longer in the model or URL set).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B8: Tighten Task.rate_scheme to NOT NULL via migration

**Files:**
- Create: `apps/jobs/migrations/0035_phase_b_tighten_task_rate_scheme.py`
- Modify: `apps/jobs/models.py` (Task.rate_scheme field declaration)

- [ ] **Step 1: Verify all live Tasks have rate_scheme set**

Open the dev DB or run the diagnostic logic from a shell. Since the Phase A backfill ran in the manual fix window, every Task with a TaskCharge now has rate_scheme. If any Tasks were created in Phase B before this point (via the new code paths), they also have it (Phase B paths require it).

```python
# Optional one-shot check via Django shell — user runs:
from apps.jobs.models import Task
Task.objects.filter(rate_scheme__isnull=True).count()  # Expect 0
```

- [ ] **Step 2: Tighten the field declaration**

In `apps/jobs/models.py`, change Task.rate_scheme:

```python
    rate_scheme = models.ForeignKey(
        'jobs.RateScheme',
        on_delete=models.PROTECT,
        related_name='task_set',  # was '+'; reverse accessor is now useful for is_referenced
    )
    # Drop null=True, blank=True
```

- [ ] **Step 3: Generate migration**

```bash
python manage.py makemigrations jobs --name phase_b_tighten_task_rate_scheme
```

Inspect output: should produce an `AlterField` operation making `rate_scheme` NOT NULL. Verify it depends on `0034_phase_a_backfill_task_from_taskcharge`.

- [ ] **Step 4: Drop the `hasattr(self, 'charge')` requirement from Task.clean()**

In `apps/jobs/models.py:247-260`, replace `Task.clean()`:

```python
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.pk:
            old_status = Task.objects.get(pk=self.pk).status
            if old_status != self.status:
                allowed = self.VALID_TRANSITIONS.get(old_status, [])
                if self.status not in allowed:
                    raise ValidationError(
                        {'status': f"Cannot transition from '{old_status}' to '{self.status}'."}
                    )
        # rate_scheme is now NOT NULL at the DB level; no defensive check needed.
```

- [ ] **Step 5: Run the test suite**

```bash
python manage.py test -v 1
```

Expected: PASS. If anything fails because a test creates Task without rate_scheme, fix the test by passing one.

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/0035_phase_b_tighten_task_rate_scheme.py tests/
git commit -m "$(cat <<'EOF'
feat(phase-b): tighten Task.rate_scheme to NOT NULL; drop TaskCharge requirement

Task.rate_scheme is now NOT NULL at the DB level (replaces the previous
"every Task must have a TaskCharge" rule). Task.clean() drops its
hasattr(self, 'charge') defensive check — no longer needed.

related_name on Task.rate_scheme switches from '+' to 'task_set' so
RateScheme.is_referenced can use the reverse manager naturally.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B9: Drop the TaskCharge model

**Files:**
- Create: `apps/jobs/migrations/0036_phase_b_drop_taskcharge.py`
- Modify: `apps/jobs/models.py` (remove TaskCharge class)

- [ ] **Step 1: Search for any remaining TaskCharge references**

```bash
grep -rn "TaskCharge\|task_charges" apps/ --exclude-dir=migrations --exclude-dir=__pycache__
grep -rn "task\.charge\|\.charge\." apps/ --exclude-dir=migrations --exclude-dir=__pycache__
grep -rn "TaskCharge\|task_charges" tests/
```

If any production references remain, fix them before proceeding. Tests still allowed to mention TaskCharge if they're testing migration behavior; otherwise update them.

- [ ] **Step 2: Delete the TaskCharge class definition**

In `apps/jobs/models.py:483-518`, delete the entire `class TaskCharge(models.Model):` block.

- [ ] **Step 3: Generate migration**

```bash
python manage.py makemigrations jobs --name phase_b_drop_taskcharge
```

Inspect output: should produce a `DeleteModel` operation for `TaskCharge`. The `task_charges` table will be dropped.

- [ ] **Step 4: Verify check passes**

```bash
python manage.py check
```

Expected: clean.

- [ ] **Step 5: Run full test suite**

```bash
python manage.py test -v 1
```

Expected: PASS. If any failures reference TaskCharge, fix them.

- [ ] **Step 6: Update fixtures**

```bash
grep -l '"jobs\.taskcharge"' fixtures/
```

For each fixture file that contains TaskCharge entries, the entries become orphaned and break loading. Choose:
- Option A (simpler for pre-prod): regenerate fixtures from the dev DB after Phase B applies (`python manage.py dumpdata jobs > fixtures/jobs_basic_data.json`).
- Option B (mechanical): hand-edit the fixture JSON to delete every `"model": "jobs.taskcharge"` block, AND populate the corresponding `Task` entries with `rate_scheme`, `active_modifiers`, and `actual_qty` reflecting what the TaskCharge held.

Pick Option A unless the dev DB is in a state you don't want preserved.

After updating, run:

```bash
python manage.py test -v 1
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/0036_phase_b_drop_taskcharge.py fixtures/ tests/
git commit -m "$(cat <<'EOF'
feat(phase-b): drop TaskCharge model

The task_charges table is dropped. All readers and writers were converted
in earlier Phase B tasks. Fixtures regenerated from the dev DB to reflect
the new shape (rate_scheme, active_modifiers, actual_qty on Task; no
TaskCharge entries).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase C — Frontend Convergence

> **Phase C goal:** Build `WorkItemForm.svelte` and replace TaskModal / SubtaskModal / PlanTaskModal usage. Two-button entry pattern (Add From Template / Add Manual Task) replaces the freeform/template radio toggle. `est_worker_time` becomes editable; `est_qty` is required only on the worksheet side.

### Task C1: Create WorkItemForm.svelte

**Files:**
- Create: `frontend/src/components/WorkItemForm.svelte`

- [ ] **Step 1: Survey existing PlanTaskModal as reference**

Open `frontend/src/components/PlanTaskModal.svelte`. Note the props, the template-vs-freeform mode logic, the field layout, the API call shape.

- [ ] **Step 2: Write the WorkItemForm shell**

Create `frontend/src/components/WorkItemForm.svelte`:

```svelte
<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';

  let {
    open = false,
    mode = 'manual', // 'manual' | 'template'
    context = 'job', // 'job' | 'worksheet' | 'subtask'
    contextId = null, // job pk, worksheet pk, or parent task pk
    item = null,     // for edit mode; null for create
    isEdit = false,
    templates = [],
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let templateId = $state('');
  let rateSchemeId = $state('');
  let name = $state('');
  let description = $state('');
  let activeModifiers = $state([]);
  let estQty = $state('');
  let estWorkerTime = $state(''); // accepts "HH:MM" or "" for null
  let busy = $state(false);
  let error = $state('');

  let schemes = $state([]);
  let loading = $state(true);

  onMount(async () => {
    try {
      const resp = await api.get('/api/rate-schemes/');
      schemes = resp.results || resp;
    } catch (e) {
      error = e.message || 'Could not load rate schemes.';
    } finally {
      loading = false;
    }
  });

  // Populate when opening or when prefill changes
  $effect(() => {
    if (!open) return;
    if (isEdit && item) {
      name = item.name || '';
      description = item.description || '';
      rateSchemeId = item.rate_scheme ?? '';
      activeModifiers = [...(item.active_modifiers || [])];
      estQty = item.est_qty ?? '';
      estWorkerTime = formatDuration(item.est_worker_time);
      templateId = '';
    } else {
      name = ''; description = '';
      rateSchemeId = ''; activeModifiers = [];
      estQty = ''; estWorkerTime = '';
      templateId = '';
    }
    error = '';
  });

  // In template mode, when the user picks a template, defaults flow downward.
  const selectedTemplate = $derived(
    templates.find(t => String(t.template_id) === String(templateId)) || null
  );
  $effect(() => {
    if (mode !== 'template') return;
    if (!selectedTemplate) return;
    if (!name) name = selectedTemplate.template_name || '';
    if (!description) description = selectedTemplate.description || '';
    activeModifiers = [...(selectedTemplate.default_active_modifiers || [])];
    if (!estQty && selectedTemplate.default_billable_qty) {
      estQty = selectedTemplate.default_billable_qty;
    }
    rateSchemeId = selectedTemplate.rate_scheme ?? '';
  });

  const selectedScheme = $derived(
    schemes.find(s => s.rate_scheme_id === Number(rateSchemeId)) || null
  );

  const estQtyRequired = $derived(context === 'worksheet');

  function formatDuration(value) {
    // Server returns ISO 8601 like "PT1H30M" or HH:MM:SS — accept either, render HH:MM
    if (!value) return '';
    if (typeof value === 'string') {
      const isoMatch = value.match(/PT(?:(\d+)H)?(?:(\d+)M)?/);
      if (isoMatch) {
        const h = parseInt(isoMatch[1] || '0', 10);
        const m = parseInt(isoMatch[2] || '0', 10);
        return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
      }
      const hmsMatch = value.match(/(\d+):(\d+)/);
      if (hmsMatch) return `${hmsMatch[1].padStart(2, '0')}:${hmsMatch[2]}`;
    }
    return '';
  }

  function durationToISO(input) {
    // "HH:MM" → "PT{H}H{M}M"; "" → null
    if (!input) return null;
    const m = input.match(/^(\d+):(\d+)$/);
    if (!m) return null;
    const hours = parseInt(m[1], 10);
    const mins = parseInt(m[2], 10);
    return `PT${hours}H${mins}M`;
  }

  function toggleModifier(key, checked) {
    if (checked) {
      if (!activeModifiers.includes(key)) {
        activeModifiers = [...activeModifiers, key];
      }
    } else {
      activeModifiers = activeModifiers.filter(k => k !== key);
    }
  }

  async function save() {
    if (estQtyRequired && !estQty) {
      error = 'Estimated qty is required on the worksheet.';
      return;
    }
    if (!isEdit && mode === 'template' && !templateId) {
      error = 'Please pick a template.';
      return;
    }
    if (mode === 'manual' && !rateSchemeId) {
      error = 'Please pick a rate scheme.';
      return;
    }

    busy = true;
    error = '';
    try {
      const payload = {
        name,
        description,
        rate_scheme: rateSchemeId,
        active_modifiers: activeModifiers,
        est_qty: estQty || null,
        est_worker_time: durationToISO(estWorkerTime),
      };

      if (isEdit && item) {
        const url = context === 'worksheet'
          ? `/api/est-worksheets/${contextId}/tasks/${item.plan_task_id || item.task_id}/`
          : `/api/jobs/${contextId}/tasks/${item.task_id}/`;
        await api.patch(url, payload);
      } else if (mode === 'template') {
        const url = context === 'worksheet'
          ? `/api/est-worksheets/${contextId}/add-from-template/`
          : `/api/jobs/${contextId}/add-from-template/`;
        await api.post(url, {
          task_template_id: Number(templateId),
          est_qty: estQty || null,
          active_modifiers: activeModifiers,
          est_worker_time: durationToISO(estWorkerTime),
        });
      } else {
        let url;
        if (context === 'worksheet') {
          url = `/api/est-worksheets/${contextId}/tasks/`;
        } else if (context === 'subtask') {
          url = `/api/tasks/${contextId}/subtasks/`;
        } else {
          url = `/api/jobs/${contextId}/tasks/`;
        }
        await api.post(url, payload);
      }
      onSaved();
    } catch (e) {
      if (e.data && typeof e.data === 'object' && !e.data.detail) {
        error = Object.entries(e.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        error = e.message || 'Could not save.';
      }
    } finally {
      busy = false;
    }
  }
</script>

{#if open}
  <div class="overlay">
    <div class="modal">
      <h3>{isEdit ? 'Edit Task' : (mode === 'template' ? 'Add Task From Template' : 'Add Manual Task')}</h3>

      {#if loading}
        <p>Loading rate schemes…</p>
      {:else}
        {#if !isEdit && mode === 'template'}
          <p>
            <label><strong>Template *</strong><br>
              <select bind:value={templateId}>
                <option value="">-- Select template --</option>
                {#each templates as tmpl (tmpl.template_id)}
                  <option value={tmpl.template_id}>{tmpl.template_name}</option>
                {/each}
              </select>
            </label>
          </p>
        {/if}

        {#if mode === 'manual'}
          <p>
            <label><strong>Rate scheme *</strong><br>
              <select bind:value={rateSchemeId}>
                <option value="">-- select --</option>
                {#each schemes as s (s.rate_scheme_id)}
                  <option value={s.rate_scheme_id}>{s.name}</option>
                {/each}
              </select>
            </label>
          </p>
        {/if}

        <p>
          <label><strong>Name *</strong><br>
            <input type="text" bind:value={name} style="width:100%;box-sizing:border-box;">
          </label>
        </p>
        <p>
          <label><strong>Description</strong><br>
            <input type="text" bind:value={description} style="width:100%;box-sizing:border-box;">
          </label>
        </p>

        {#if selectedScheme}
          {#if mode === 'template'}
            <p>
              <strong>Rate scheme:</strong> {selectedScheme.name} —
              ${selectedScheme.rate}/{selectedScheme.unit_label}
              <small>(from template)</small>
            </p>
          {/if}
          {#if selectedScheme.modifiers && selectedScheme.modifiers.length > 0}
            <fieldset>
              <legend><strong>Modifiers</strong></legend>
              {#each selectedScheme.modifiers as m (m.key)}
                <p>
                  <label>
                    <input
                      type="checkbox"
                      checked={activeModifiers.includes(m.key)}
                      onchange={(e) => toggleModifier(m.key, e.target.checked)}
                    />
                    {m.label} (+{m.percent}%)
                  </label>
                </p>
              {/each}
            </fieldset>
          {/if}

          <p>
            <label><strong>Estimated qty {estQtyRequired ? '*' : ''}</strong><br>
              <input type="number" step="0.01" bind:value={estQty}>
              {#if selectedScheme}<small>{selectedScheme.unit_label}</small>{/if}
            </label>
          </p>
        {/if}

        <p>
          <label><strong>Estimated worker time</strong><br>
            <input type="text" placeholder="HH:MM" bind:value={estWorkerTime}>
            <small>e.g. 1:30 = 1 hour 30 min</small>
          </label>
        </p>

        <div class="buttons">
          <button type="button" onclick={save} disabled={busy}>Save</button>
          <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
        </div>
        {#if error}<p class="error">{error}</p>{/if}
      {/if}
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.4);
    display: flex; align-items: center; justify-content: center; z-index: 200;
  }
  .modal { background: white; padding: 16px; max-width: 500px; width: 90%; border: 1px solid #ccc; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
```

- [ ] **Step 3: Run frontend dev server and smoke check**

```bash
cd frontend && npm run dev
```

In another terminal start the Django server, then visit a worksheet detail page in the browser. The form isn't wired in yet (next task). For now, just confirm `npm run build` succeeds:

```bash
cd frontend && npm run build
```

Expected: build succeeds without component-resolution errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/WorkItemForm.svelte
git commit -m "$(cat <<'EOF'
feat(phase-c): add WorkItemForm.svelte

Shared form for creating/editing PlanTask and Task. Supports template mode
(template picker at top) and manual mode (rate-scheme picker at top).
Exposes est_worker_time as a HH:MM input (new). est_qty required only when
context='worksheet'.

Not yet wired into any page — that comes in C2-C4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task C2: Replace PlanTaskModal usage in worksheet view

**Files:**
- Modify: the worksheet detail page (likely `frontend/src/routes/worksheets/WorksheetDetail.svelte` or similar — find with `grep -rn 'PlanTaskModal' frontend/src/`)

- [ ] **Step 1: Find PlanTaskModal usages**

```bash
grep -rn "PlanTaskModal" /Users/drshiny/Documents/konbini/Minibini/frontend/src/
```

- [ ] **Step 2: Replace with WorkItemForm and two-button entry**

For each file mounting `<PlanTaskModal />`, change:

```svelte
import PlanTaskModal from '../components/PlanTaskModal.svelte';
// ...
<button onclick={() => { modalMode = 'create-freeform'; modalOpen = true; }}>Add Task</button>
<button onclick={() => { modalMode = 'create-template'; modalOpen = true; }}>Add From Template</button>

<PlanTaskModal
  open={modalOpen}
  mode={modalMode}
  task={editingTask}
  worksheetId={worksheet.id}
  templates={templates}
  onSaved={...}
  onClose={() => (modalOpen = false)}
/>
```

To:

```svelte
import WorkItemForm from '../components/WorkItemForm.svelte';
// ...
<button onclick={() => { modalMode = 'template'; modalOpen = true; editingTask = null; }}>Add Task From Template</button>
<button onclick={() => { modalMode = 'manual'; modalOpen = true; editingTask = null; }}>Add Manual Task</button>

<WorkItemForm
  open={modalOpen}
  mode={modalMode}
  context="worksheet"
  contextId={worksheet.id}
  item={editingTask}
  isEdit={!!editingTask}
  templates={templates}
  onSaved={...}
  onClose={() => (modalOpen = false)}
/>
```

(`modalMode` values change from `'create-freeform' | 'create-template' | 'edit'` to `'manual' | 'template'`; the edit boolean becomes `isEdit`.)

- [ ] **Step 3: Smoke test in the browser**

```bash
cd frontend && npm run dev
```

Open a worksheet, click "Add Manual Task" → fill in scheme/name/qty → Save → confirm new PlanTask appears.
Click "Add Task From Template" → pick a template → Save → confirm new PlanTask appears with template defaults.
Click an existing task to edit → confirm fields populate, save round-trips.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/
git commit -m "$(cat <<'EOF'
feat(phase-c): worksheet view uses WorkItemForm with two-button entry

Replaces the freeform/template radio toggle with two top-level buttons
(Add Manual Task / Add Task From Template). Both buttons open the same
WorkItemForm, just with the mode prop set differently. Manual mode shows
the RateScheme picker at top; template mode shows the Template picker
at top, with the chosen template's scheme locked.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task C3: Replace TaskModal usage in job view

**Files:**
- Modify: job-detail-related files mounting `TaskModal` (find with grep)

- [ ] **Step 1: Find TaskModal usages**

```bash
grep -rn "TaskModal" /Users/drshiny/Documents/konbini/Minibini/frontend/src/ | grep -v "SubtaskModal"
```

- [ ] **Step 2: Replace with WorkItemForm and two-button entry**

Same pattern as Task C2 but with `context="job"` and `contextId={job.id}`. The two buttons are now mounted on the job detail page (or whichever component currently shows the "Add Task" button).

- [ ] **Step 3: Smoke test**

In the browser, on a job detail page: click "Add Manual Task" → scheme + name + qty + save → task appears. Click "Add Task From Template" → template picked → save → task appears.

Edit existing task → fields populate. Save round-trips.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/
git commit -m "$(cat <<'EOF'
feat(phase-c): job view uses WorkItemForm with two-button entry

Same pattern as the worksheet view (C2): the freeform/template radio
toggle becomes two top-level buttons.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task C4: Replace SubtaskModal usage

**Files:**
- Modify: TaskDetailPage (or wherever SubtaskModal is mounted)

- [ ] **Step 1: Find SubtaskModal usage**

```bash
grep -rn "SubtaskModal" /Users/drshiny/Documents/konbini/Minibini/frontend/src/
```

- [ ] **Step 2: Replace with WorkItemForm**

Subtasks today are manual-only (no template support — preserved per the design's "open question"). So the entry is one button, "Add Subtask," opening WorkItemForm in `mode='manual'` with `context='subtask'`.

```svelte
import WorkItemForm from '../components/WorkItemForm.svelte';
// ...
<button onclick={() => { subtaskOpen = true; }}>Add Subtask</button>

<WorkItemForm
  open={subtaskOpen}
  mode="manual"
  context="subtask"
  contextId={parentTask.task_id}
  templates={[]}
  onSaved={refresh}
  onClose={() => (subtaskOpen = false)}
/>
```

- [ ] **Step 3: Smoke test**

Drill into a task on a job, click "Add Subtask," fill the form, save. Subtask appears under parent.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/
git commit -m "$(cat <<'EOF'
feat(phase-c): TaskDetailPage uses WorkItemForm for subtasks

Subtasks remain manual-only (no template support per design open question).
WorkItemForm with mode='manual' + context='subtask' is the new mount.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task C5: Update TaskDetailPage actual_qty input

**Files:**
- Modify: `frontend/src/routes/jobs/TaskDetailPage.svelte` (or wherever the actual qty input lives)

- [ ] **Step 1: Find the actual qty input**

```bash
grep -rn "actuals\|actual_qty" /Users/drshiny/Documents/konbini/Minibini/frontend/src/
```

- [ ] **Step 2: Replace `actuals.qty` reads/writes with `actual_qty`**

The input currently reads `task.charge.actuals.qty` (or similar through the nested structure). Change to read/write `task.actual_qty`. The PATCH payload changes from `{ actuals: { qty: ... } }` to `{ actual_qty: ... }`.

- [ ] **Step 3: Smoke test**

Open a task with ENTERED_QTY scheme. Enter an actual qty, save. Reload — value persists. Confirm computed charge updates.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/
git commit -m "$(cat <<'EOF'
feat(phase-c): TaskDetailPage reads/writes actual_qty as flat field

The 'actual qty' input on TaskDetailPage now binds to task.actual_qty
directly. The legacy task.charge.actuals.qty path is gone.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task C6: Delete the old modal files

**Files:**
- Delete: `frontend/src/components/PlanTaskModal.svelte`
- Delete: `frontend/src/components/TaskModal.svelte`
- Delete: `frontend/src/components/SubtaskModal.svelte`

- [ ] **Step 1: Confirm no remaining imports**

```bash
grep -rn "PlanTaskModal\|TaskModal\|SubtaskModal" /Users/drshiny/Documents/konbini/Minibini/frontend/src/
```

Expected: only matches inside the files themselves.

- [ ] **Step 2: Delete the files**

```bash
rm frontend/src/components/PlanTaskModal.svelte
rm frontend/src/components/TaskModal.svelte
rm frontend/src/components/SubtaskModal.svelte
```

- [ ] **Step 3: Build and smoke test**

```bash
cd frontend && npm run build
```

Expected: clean build.

```bash
cd frontend && npm run dev
```

Walk through worksheet add task, job add task, subtask add. All work via WorkItemForm.

- [ ] **Step 4: Commit**

```bash
git add -A frontend/
git commit -m "$(cat <<'EOF'
refactor(phase-c): delete legacy Task/Subtask/PlanTask modals

WorkItemForm.svelte fully replaces them. The freeform/template radio
toggle, the actuals: {qty: estQty} hack, and the three-way modal
duplication are gone.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final Sanity Pass

- [ ] **Step 1: Run the full backend test suite**

```bash
python manage.py test -v 1
```

Expected: PASS.

- [ ] **Step 2: Build the frontend**

```bash
cd frontend && npm run build
```

Expected: clean build.

- [ ] **Step 3: Smoke walkthrough in the browser**

With dev servers running:

1. Create a Job. Open it. Click "Add Manual Task" — fill in scheme/name/qty/worker time → save. Task appears with the right values.
2. Click "Add Task From Template" — pick a template → save. Task appears with template defaults.
3. Drill into a task. Click "Add Subtask" → manual entry → save.
4. For a task with ENTERED_QTY scheme, enter actual qty and save. Refresh; persisted.
5. Open a Worksheet on a Job. "Add Manual Task" and "Add Task From Template" both work.
6. Edit a worksheet task. Empty est_qty → save → form rejects with "Estimated qty is required on the worksheet."
7. Generate an Estimate from a Worksheet. Accept the Estimate. New Tasks land on the Job with `est_qty` carried from the PlanTasks. `actual_qty` null on all of them.
8. Open the Invoice wizard for the Job. Per-task atoms render with computed charges via `task.compute_amount()`. Add to a line item, save invoice.
9. In Settings → RateSchemes, the outdated-schemes UI shows the new `task_count` instead of `task_charge_count`.

If any of these don't work, fix and commit the fix as a follow-up — don't bypass.

- [ ] **Step 4: Final commit if any cleanup**

```bash
git status
# If anything outstanding:
git commit -am "chore: post-walkthrough cleanup"
```

---

## Rollback notes

This refactor is irreversible at the model level once Phase B applies (TaskCharge table dropped). If something goes badly wrong during Phase B:

- Phase A migrations alone leave the system in a healthy "both shapes coexist" state — safe to stop after Phase A applies if needed.
- Between Phase A and Phase B, the dev DB still has TaskCharge rows; you can rebuild from them if needed.
- After Phase B, only restoring from a DB backup or re-deriving TaskCharge data from the new Task fields would let you go back. Pre-production, this should not be necessary.
