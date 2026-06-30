# Job-Owns-Atoms / Documents-as-Lenses — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Spec:** `docs/plans/2026-06-29-job-owns-atoms-documents-as-lenses.md` — read it first.
>
> **Plan convention (read this):** This is a destructive, cross-cutting refactor of an
> existing ~40-file surface, not greenfield work. Novel code (the `Fee` model, the
> acceptance hook, source-type additions, converter Fee emission, validator changes) is
> written out in full. **Mechanical refactor/delete/repoint steps cite the exact
> `file:line` to change and the existing pattern to follow** rather than reproducing
> hundreds of lines of current code verbatim — the executing agent reads the live file.
> These citations are instructions, not placeholders.

**Goal:** Collapse the plan/job work split so the **Job owns one live set of atoms**
(Task, Material, Fee); make Estimates and Invoices optional **lenses** over those atoms;
remove `PlanTask`/`PlanMaterial`/`EstWorksheet`, drop `flat_fee` from `RateScheme`, and
add the `Fee` atom — then rewrite the converter, the validator, and the frontend, and
regenerate the dataset.

**Architecture:** Tasks/Materials/Fees hang directly on `Job` from estimate time onward.
A `Task` already carries `est_qty` (quote) and `actual_qty` (actual), so it subsumes
`PlanTask`. Documents hold line items that *optionally* link to a Job atom via the
existing polymorphic `*LineItemSource` claim rows; a line with no atom is a hand-line that
**crystallizes into a `Fee`** at acceptance. Estimate lines project `est_qty`; invoice
lines bill the locked `actual_qty` of completed tasks. No carry-over copy; no data
migration (schema change + regenerate).

**Tech Stack:** Django 5.2 / DRF / MySQL / Python 3.12 (backend); Svelte 5 runes + Vitest
(frontend); the `nealsdata/converter` pipeline (Excel/CSV → JSON fixture).

## Global Constraints

- **Never write the dev DB.** No `migrate`, no `loaddata`, no ORM writes via shell, no
  `seed_data.sh`. `makemigrations` is fine; tests use a throwaway DB. Dev-DB wipe + regen
  is the **user's** action.
- **Backend tests:** `python manage.py test tests.<module>` — one test process at a time
  (shared MySQL). Judge pass/fail by the `OK` / `FAILED (...)` summary line, never a piped
  exit code. After any migration, run the relevant suite **without `--keepdb`** (fresh
  build) at least once.
- **Frontend tests:** `cd frontend && npm run test:run` (never watch mode).
- **Line-item deletes** always route through `LineItemService.delete_line_item_with_renumber`.
- **Status/algorithm values:** model constants only (`Task.STATUS_COMPLETE`, etc.).
- **Money:** `Decimal`, quantize to `0.01` at the boundary; pass real types to fields.
- Each task ends green + a commit. Commit message trailer:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

## File-structure map (what changes, by phase)

**New:** `apps/jobs/models.py` (`Fee`), `apps/jobs/services.py` (`FeeService`),
`apps/api/fees/{views,serializers}.py`, `apps/estimates/acceptance.py` (replaces
`carry_over.py`), `frontend/src/components/FeeModal.svelte`,
`frontend/src/routes/jobs/JobWorkPage.svelte` (the Plan-on-the-job surface).

**Deleted:** `PlanTask` (`apps/jobs/models.py:248`), `PlanMaterial`
(`apps/inventory/models.py:169`), `EstWorksheet` (`apps/estimates/models.py:298`),
`apps/estimates/carry_over.py`, `apps/api/plan_tasks/`, `apps/api/worksheets/`,
`apps/jobs/flat_fee_reframe.py`, frontend `WorksheetDetailPage.svelte`,
`PlanTaskDetailPage.svelte`, `PlanMaterialModal.svelte`, `WorksheetTaskTable.svelte`.

**Modified (major):** `RateScheme` (drop `flat_fee`), `EstimateLineItemSource` /
`InvoiceLineItemSource` (atom source types), `EstimateWizardService` /
`InvoiceWizardService` / `BaseWizardService` (job-atom source pool), the estimate/invoice
API, `validate_data.py`, `nealsdata/converter/build.py` + `parsing.py`,
`JobDetail.svelte`, the estimate/invoice wizard pages.

---

## Phase 1 — The `Fee` atom (additive, backend)

Adds `Fee` and teaches the wizards/sources to recognise it. Nothing is removed; the suite
stays green throughout.

### Task 1.1: `Fee` model

**Files:**
- Modify: `apps/jobs/models.py` (add `Fee` after `Task`)
- Test: `tests/test_fee_model.py` (create)

**Interfaces:**
- Produces: `Fee(job, task=None, description, quantity, unit_rate, accounting_category, sort_order)`; `Fee.compute_amount(active_modifiers=None) -> Decimal`; `Fee.effective_accounting_category -> AccountingCategory`; `Fee.units -> str` (returns `'none'`); `db_table='fees'`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fee_model.py
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import Fee, Job
from apps.core.models import AccountingCategory

class FeeModelTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Services', code='SVC')
        self.job = Job.objects.create(job_number='JOB-T-1', status=Job.STATUS_DRAFT)

    def test_compute_amount_is_quantity_times_unit_rate(self):
        fee = Fee.objects.create(job=self.job, description='Delivery',
                                 quantity=Decimal('3'), unit_rate=Decimal('50.00'),
                                 accounting_category=self.ac)
        self.assertEqual(fee.compute_amount(), Decimal('150.00'))

    def test_units_is_none_and_category_passthrough(self):
        fee = Fee.objects.create(job=self.job, description='Setup',
                                 quantity=Decimal('1'), unit_rate=Decimal('120.00'),
                                 accounting_category=self.ac)
        self.assertEqual(fee.units, 'none')
        self.assertEqual(fee.effective_accounting_category, self.ac)
```

- [ ] **Step 2: Run it; expect ImportError/AttributeError** — `python manage.py test tests.test_fee_model`

- [ ] **Step 3: Implement `Fee`** (in `apps/jobs/models.py`)

```python
class Fee(models.Model):
    """A fixed charge owned by the Job — the crystallized form of an accepted
    hand-line. Frozen quantity × unit_rate; no actual lifecycle. Optionally
    points at the Task that is the work behind it."""
    fee_id = models.AutoField(primary_key=True)
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE, related_name='fees')
    task = models.OneToOneField('jobs.Task', on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='fee')
    description = models.CharField(max_length=255, blank=True, default='')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1.00'))
    unit_rate = models.DecimalField(max_digits=10, decimal_places=2)
    accounting_category = models.ForeignKey('core.AccountingCategory', on_delete=models.PROTECT)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'fees'

    def compute_amount(self, active_modifiers=None):
        return (self.quantity * self.unit_rate).quantize(Decimal('0.01'))

    @property
    def effective_accounting_category(self):
        return self.accounting_category

    @property
    def units(self):
        return 'none'

    def __str__(self):
        return f'Fee {self.pk}: {self.description} ({self.quantity}×{self.unit_rate})'
```

- [ ] **Step 4: `makemigrations jobs`; run the test; expect PASS.** (Do NOT `migrate`.)

- [ ] **Step 5: Commit** — `feat(jobs): add Fee atom (quantity × unit_rate, optional task link)`

### Task 1.2: Estimate & invoice sources accept atom + `fee` types

**Files:**
- Modify: `apps/estimates/models.py:581` (`EstimateLineItemSource`), `apps/invoicing/models.py:169` (`InvoiceLineItemSource`)
- Test: `tests/test_line_item_sources.py` (create)

**Interfaces:**
- Produces: `EstimateLineItemSource.SOURCE_TASK='task'`, `SOURCE_MATERIAL='material'`, `SOURCE_FEE='fee'`; `InvoiceLineItemSource.SOURCE_FEE='fee'`. `.resolve()` returns the live atom for each. (The legacy `SOURCE_PLAN_TASK`/`SOURCE_PLAN_MATERIAL` stay for now; removed in Phase 4.)

- [ ] **Step 1: Failing test** — assert an `EstimateLineItemSource(source_type='task', source_pk=task.pk).resolve()` returns that `Task`; same for `'material'`→Material and `'fee'`→Fee; and `InvoiceLineItemSource(source_type='fee', ...).resolve()` returns the Fee. Assert the DB `unique_together` still blocks a second claim of the same `(source_type, source_pk)` (expect `IntegrityError`).

- [ ] **Step 2: Run; expect fail** (`'task'`/`'fee'` not in choices, `resolve()` KeyError).

- [ ] **Step 3: Implement** — add the three `SOURCE_*` constants + choices to `EstimateLineItemSource` and `SOURCE_FEE` to `InvoiceLineItemSource`; extend each `resolve()`:

```python
# EstimateLineItemSource.resolve() — add branches
if self.source_type == self.SOURCE_TASK:
    from apps.jobs.models import Task
    return Task.objects.get(pk=self.source_pk)
if self.source_type == self.SOURCE_MATERIAL:
    from apps.inventory.models import Material
    return Material.objects.get(pk=self.source_pk)
if self.source_type == self.SOURCE_FEE:
    from apps.jobs.models import Fee
    return Fee.objects.get(pk=self.source_pk)
```
```python
# InvoiceLineItemSource.resolve() — add Fee branch
if self.source_type == self.SOURCE_FEE:
    from apps.jobs.models import Fee
    return Fee.objects.get(pk=self.source_pk)
```

- [ ] **Step 4: `makemigrations`; run; PASS.**
- [ ] **Step 5: Commit** — `feat(sources): line-item sources resolve Task/Material/Fee atoms`

### Task 1.3: Wizard recognises `Fee` atoms (billable, no completion gate)

**Files:**
- Modify: `apps/core/wizard.py` (`BaseWizardService._atom_detail`/`_atom_units`/`_source_model` mapping), `apps/invoicing/services.py:571` (billability), `apps/invoicing/services.py:764` (`_assert_atom_billable`)
- Test: `tests/test_fee_wizard.py` (create)

**Interfaces:**
- Consumes: Task 1.1 `Fee.compute_amount`; Task 1.2 `SOURCE_FEE`.
- Produces: a `Fee` in an invoice source pool reports `state='available'` (never `not_billable`) and `_atom_detail(fee)` returns `{qty: fee.quantity, rate: fee.unit_rate, units: 'none', amount: fee.compute_amount()}`.

- [ ] **Step 1: Failing test** — build a draft invoice on a job with one Fee; assert `InvoiceWizardService.get_source_pool(...)` includes the fee atom with `state='available'`, `amount == 150.00`; assert `_assert_atom_billable(fee)` does **not** raise.

- [ ] **Step 2: Run; expect fail.**

- [ ] **Step 3: Implement** — in `BaseWizardService._atom_detail` (`apps/core/wizard.py:111`) add a `Fee` branch returning `qty/rate/units/amount` as above (mirror the Material branch but `rate=fee.unit_rate`, `units='none'`). Add `Fee` to the type dispatch the pool uses. In `apps/invoicing/services.py` `billability()` (line 571) and `_assert_atom_billable` (line 764), treat `Fee` as always billable (no status/consumption gate). Ensure the invoice source-pool enumerator (lines 518-697) yields the job's `Fee`s.

- [ ] **Step 4: Run; PASS.**
- [ ] **Step 5: Commit** — `feat(wizard): Fees are billable atoms with no completion gate`

---

## Phase 2 — Work lives on the Job pre-approval (additive, backend)

Make Tasks/Materials creatable directly on a Job at any status, so the Job is the work
container before acceptance. The worksheet still exists; nothing is removed yet.

### Task 2.1: Relax the materialize/create gate; direct Task create on a Job

**Files:**
- Modify: `apps/jobs/services.py:628` (`materialize_worksheet_onto_job` gate at line 636-640) and `TaskService.create_direct`; `apps/api/jobs/views.py` (a `POST /api/jobs/{id}/tasks/` create path)
- Test: `tests/test_job_direct_tasks.py` (create)

**Interfaces:**
- Produces: `TaskService.create_direct(job, rate_scheme, name, est_qty=None, est_worker_time=None, active_modifiers=None, description='', ...) -> Task` callable on a **draft** job; `POST /api/jobs/{id}/tasks/` creates a Task on a job in any non-terminal status.

- [ ] **Step 1: Failing test** — `TaskService.create_direct(job=draft_job, rate_scheme=rs, name='CAD', est_qty=Decimal('2'))` succeeds and the Task is attached to the draft job; `POST /api/jobs/{draft_job.id}/tasks/` returns 201.

- [ ] **Step 2: Run; expect fail** (current gate raises “job approved or in progress” — `apps/jobs/services.py:636`).

- [ ] **Step 3: Implement** — drop the status gate in `create_direct` (keep it only in `materialize_worksheet_onto_job`, which is removed in Phase 4); add/confirm the job-nested task create endpoint following the existing worksheet task-create pattern (`apps/api/worksheets/views.py:tasks`), but pointed at the Job. Permissions: `IsAuthenticated` + `CanManageJobOrPM` (match existing job-task writes).

- [ ] **Step 4: Run; PASS.**
- [ ] **Step 5: Commit** — `feat(jobs): create Tasks directly on a Job at any status`

### Task 2.2: Direct Material create on a Job (catalog + freeform)

**Files:**
- Modify: `apps/inventory/services.py` (`MaterialService.create_on_job` — drop any worksheet/approval coupling), `apps/api/jobs/views.py` (`POST /api/jobs/{id}/materials/`)
- Test: `tests/test_job_direct_materials.py` (create)

**Interfaces:**
- Produces: `MaterialService.create_on_job(job, task=None, inventory_item=None, description, quantity, units, unit_cost, sell_price, accounting_category) -> Material` on any-status job; `POST /api/jobs/{id}/materials/` (201). Picking an `InventoryItem` populates cost/sell from it (existing `_populate_from_pli`).

- [ ] **Step 1: Failing test** — create a catalog-backed Material and a freeform Material on a draft job via the service and the endpoint; assert both attach and the catalog one inherits `sell_price` from its `InventoryItem`.
- [ ] **Step 2: Run; expect fail.**
- [ ] **Step 3: Implement** — mirror Task 2.1: a job-nested materials endpoint following the worksheet `plan-materials` pattern (`apps/api/worksheets/views.py`), creating `Material` (not `PlanMaterial`).
- [ ] **Step 4: Run; PASS.**
- [ ] **Step 5: Commit** — `feat(jobs): create Materials directly on a Job (catalog + freeform)`

---

## Phase 3 — Documents project from Job atoms; acceptance crystallizes Fees

### Task 3.1: Estimate source pool reads the Job's Tasks + Materials

**Files:**
- Modify: `apps/estimates/services.py:1035` (`EstimateWizardService.get_source_pool`), `:1136` (`send_all_atoms_to_estimate`), the `_atom_source_type`/`_resolve_atom` helpers
- Test: `tests/test_estimate_sources_from_job.py` (create)

**Interfaces:**
- Consumes: Phase 2 job-direct atoms; Task 1.2 `SOURCE_TASK`/`SOURCE_MATERIAL`.
- Produces: `get_source_pool(estimate)` (signature changes from `worksheet` to `estimate`) returns the **estimate's job's** Tasks + Materials with claim state; claims are written as `SOURCE_TASK`/`SOURCE_MATERIAL`.

- [ ] **Step 1: Failing test** — a draft estimate whose job has 2 Tasks + 1 Material; assert `get_source_pool(estimate)` returns those 3 atoms (`type` in `{task, material}`) with `state='available'`, and that projecting them writes `EstimateLineItemSource` rows with `source_type='task'/'material'`.
- [ ] **Step 2: Run; expect fail.**
- [ ] **Step 3: Implement** — repoint the source pool from `PlanTask.objects.filter(est_worksheet=...)` / `PlanMaterial...` to `Task.objects.filter(job=estimate.job)` / `Material.objects.filter(job=estimate.job)`; set source types to the atom variants. Reuse `compute_amount()` (Task projects `est_qty`-based amount via its rate scheme; confirm `Task.compute_amount` path for the estimate uses `est_qty`, see note below). Update `_atom_source_type` to map Task→`task`, Material→`material`.
  - **Note on Task estimate amount:** `Task.compute_amount` (`apps/jobs/models.py:408`) resolves qty via `RateScheme.get_actual_qty` (actuals). For the **estimate** projection we want `est_qty`. Add `Task.compute_estimate_amount()` returning `rate_scheme.compute_charge(est_qty or 0, active_modifiers)` and use it in the estimate wizard; the invoice wizard keeps `compute_amount()` (actuals). Cover both with a unit test in this task.
- [ ] **Step 4: Run; PASS.**
- [ ] **Step 5: Commit** — `feat(estimates): estimate sources project the Job's Tasks/Materials (est_qty)`

### Task 3.2: Acceptance crystallizes hand-lines into Fees (replaces carry-over)

**Files:**
- Create: `apps/estimates/acceptance.py`
- Modify: `apps/estimates/signals.py:109` (point the `estimate_accepted` receiver at the new service)
- Delete (in Phase 4): `apps/estimates/carry_over.py`
- Test: `tests/test_acceptance_fees.py` (create)

**Interfaces:**
- Consumes: Task 1.1 `Fee`; Task 1.2 sources.
- Produces: `EstimateAcceptanceService.on_accept(estimate)` — for each accepted-estimate line item with **no** source row, create a `Fee(job=estimate.job, description=line.description, quantity=line.quantity, unit_rate=line.price, accounting_category=line.accounting_category, sort_order=line.line_number)`; then call `InventoryService.create_earmarks_for_job(job)`. Returns `{'fees_created': int}`.

- [ ] **Step 1: Failing test** — accept an estimate with one atom-backed line and one hand-line; assert exactly one `Fee` is created on the job (from the hand-line), with `quantity`/`unit_rate`/`accounting_category` copied from the line, and that earmarks were created.

- [ ] **Step 2: Run; expect fail.**

- [ ] **Step 3: Implement**

```python
# apps/estimates/acceptance.py
from decimal import Decimal
from django.db import transaction

class EstimateAcceptanceService:
    @staticmethod
    @transaction.atomic
    def on_accept(estimate):
        from apps.jobs.models import Fee
        from apps.inventory.services import InventoryService
        job = estimate.job
        job.refresh_from_db()
        fees_created = 0
        for li in estimate.line_items.all():
            if li.sources.exists():       # atom-backed → already on the job
                continue
            if li.is_adjustment:          # percentage adjustments stay document-only
                continue
            Fee.objects.create(
                job=job, description=li.description or '',
                quantity=li.quantity or Decimal('1'),
                unit_rate=li.price or Decimal('0'),
                accounting_category=li.accounting_category,
                sort_order=li.line_number or 0,
            )
            fees_created += 1
        InventoryService.create_earmarks_for_job(job)
        return {'fees_created': fees_created}
```
Point the signal receiver (`apps/estimates/signals.py:109`) at `EstimateAcceptanceService.on_accept`.

- [ ] **Step 4: Run; PASS.**
- [ ] **Step 5: Commit** — `feat(estimates): acceptance crystallizes hand-lines into Fees; earmark on accept`

### Task 3.3: Invoice draws Job Tasks (complete) + Materials (consumed) + Fees

**Files:**
- Modify: `apps/invoicing/services.py:518` (invoice source pool already over job atoms — add Fees), confirm `copy-from-estimate`/`apply-everything` seed paths include Fees
- Test: `tests/test_invoice_includes_fees.py` (create)

**Interfaces:**
- Produces: invoice `seed_all_atoms`/`apply-everything` includes the job's Fees; the at-most-one-invoice claim guard (existing `unique_together`) covers `source_type='fee'`.

- [ ] **Step 1: Failing test** — a job with one complete Task, one consumed Material, one Fee; `InvoiceWizardService.seed_all_atoms(invoice)` creates 3 lines; re-seeding a second invoice for the same Fee raises the claim conflict.
- [ ] **Step 2: Run; expect fail.**
- [ ] **Step 3: Implement** — ensure the invoice atom enumerator yields Fees (Phase 1.3 wired billability; here wire enumeration + seed). Confirm `copy-from-estimate` maps an accepted-estimate hand-line to its crystallized Fee.
- [ ] **Step 4: Run; PASS.**
- [ ] **Step 5: Commit** — `feat(invoicing): invoices seed Job Tasks/Materials/Fees`

### Task 3.4: Create an Estimate on a Job (no worksheet); expose Job atoms + claim state

The job overview (Phase 7) needs two things this task provides: a way to start an estimate
without a worksheet, and per-atom claim state so the UI can show **unclaimed** (pre-approval
/ released) work.

**Files:**
- Modify: `apps/api/estimates/views.py` (estimate `create` accepts `{job}` and makes a draft directly), `apps/api/jobs/serializers.py` (job detail exposes `tasks`/`materials`/`fees`), and the job-atom serializers (add a `claimed` flag)
- Delete (Phase 4): the worksheet `send-all-atoms-to-estimate` / `open-estimate` entry points
- Test: `tests/test_estimate_create_and_claim_state.py` (create)

**Interfaces:**
- Produces: `POST /api/estimates/` with `{job}` → a `draft` `Estimate` (no worksheet, no atoms required). Job-detail Task/Material/Fee serializers each expose `claimed: bool` = "referenced by an `EstimateLineItemSource` on this job's live (non-superseded) estimate." `unclaimed` work = on the job, `claimed=false`.

- [ ] **Step 1: Failing test** — `POST /api/estimates/ {job}` returns 201 with a draft estimate whose job matches; a Task on the job that no live-estimate line references serializes `claimed=false`, and once projected onto a line serializes `claimed=true`.
- [ ] **Step 2: Run; expect fail.**
- [ ] **Step 3: Implement** — add the job-keyed `create` to the estimate viewset (delegating to a service that makes a draft `Estimate` on the job); add a `claimed` `SerializerMethodField` to the Task/Material/Fee serializers computing membership in the live estimate's source rows (one query per atom set; annotate to avoid N+1).
- [ ] **Step 4: Run; PASS.**
- [ ] **Step 5: Commit** — `feat(estimates): create an estimate on a job directly; expose atom claim state`

---

## Phase 4 — Remove PlanTask / PlanMaterial / EstWorksheet / carry-over / flat_fee

Now that documents project from Job atoms and acceptance makes Fees, the plan layer and
`flat_fee` are dead. This phase is destructive; run the **full** backend suite without
`--keepdb` at the end.

### Task 4.1: Drop `flat_fee` from `RateScheme`

**Files:**
- Modify: `apps/jobs/models.py:463` (`RateScheme`: remove `FLAT_FEE` constant + choice; remove the `flat_fee` branches in `effective_rate` line 541 and `get_actual_qty` line 572)
- Test: `tests/test_rate_scheme.py` (update)

- [ ] **Step 1:** Update tests — remove/convert any `algorithm=RateScheme.FLAT_FEE` cases; assert `FLAT_FEE` no longer exists and that `ALGORITHM_CHOICES` is `{elapsed_time, entered_qty, percentage}`.
- [ ] **Step 2: Run; expect fail.**
- [ ] **Step 3: Implement** — delete the constant, the choice, and both algorithm branches. `makemigrations jobs` for the choices change.
- [ ] **Step 4: Run `tests.test_rate_scheme`; PASS.**
- [ ] **Step 5: Commit** — `refactor(rate-scheme): drop flat_fee algorithm (Fees own fixed charges now)`

### Task 4.2: Delete `EstWorksheet`, `PlanTask`, `PlanMaterial` + their API/services

**Files (delete):** `apps/api/plan_tasks/`, `apps/api/worksheets/`, `apps/estimates/carry_over.py`, `apps/jobs/flat_fee_reframe.py`
**Files (modify):** `apps/jobs/models.py:248` (remove `PlanTask`), `apps/inventory/models.py:169` (remove `PlanMaterial`), `apps/estimates/models.py:298` (remove `EstWorksheet`); remove `Task.source_plan_task` (`apps/jobs/models.py:338`) and `Material.source_plan_material` (`apps/inventory/models.py:284`); remove `materialize_worksheet_onto_job`/`copy_from_worksheet` (`apps/jobs/services.py:628,686`); remove `WorksheetService` + plan-material methods (`apps/estimates/services.py:752`, `apps/inventory/services.py`); remove `WorkTemplate.generate_*_for_worksheet` + `ServiceItem.generate_task`'s worksheet branch (`apps/estimates/models.py:332,496`); remove the `est-worksheets`/`plan-tasks` URL registrations (`apps/api/urls.py`); remove `EstimateLineItemSource.SOURCE_PLAN_TASK/SOURCE_PLAN_MATERIAL` + their `resolve()` branches.
**Test:** the whole suite.

- [ ] **Step 1:** Delete the listed model classes, FKs, services, API modules, URL routes, and source-type constants. `grep -rn "PlanTask\|PlanMaterial\|EstWorksheet\|source_plan_task\|source_plan_material\|est-worksheets\|plan-tasks\|carry_over\|materialize_worksheet" apps/` and clear every backend hit (frontend handled in Phase 7; converter in Phase 5; validator in Phase 6).
- [ ] **Step 2:** `makemigrations` (expect table drops + field removals). Inspect the migration: it must `DeleteModel` the three and `RemoveField` the two FKs.
- [ ] **Step 3:** Fix the fallout the compiler/import errors surface (signals, serializers, search indexer `apps/search/services.py`, `apps/jobs/signals.py` is empty already).
- [ ] **Step 4:** Run the **full** suite without `--keepdb`: `python manage.py test`. Triage to green. (Tests that loaded the neals fixture will fail until Phase 8 regen — mark them skipped with a `# re-enable after dataset regen (Phase 8)` note and a ticket in the commit body, OR keep them and accept red only on `tests.test_neals_fixture` until Phase 8. Choose skip to keep the gate meaningful.)
- [ ] **Step 5: Commit** — `refactor!: remove PlanTask/PlanMaterial/EstWorksheet, carry-over, and the plan API`

### Task 4.3: Confirm estimate revision detaches atom links (frozen snapshot)

**Files:** `apps/estimates/services.py` (the `revise`/supersede path)
**Test:** `tests/test_estimate_revision_detaches.py` (create)

- [ ] **Step 1: Failing test** — revise an estimate that has atom-backed lines; assert the **superseded** estimate keeps its line items but its `EstimateLineItemSource` rows are gone (atoms released to the live job), and the new estimate can re-claim them.
- [ ] **Step 2: Run; expect fail.**
- [ ] **Step 3: Implement** — on supersede, delete the old estimate's source rows (drop the live link; the line item retains its frozen snapshot fields). Unclaimed atoms remain on the job (flag handled in serializer Phase 7).
- [ ] **Step 4: Run; PASS.**
- [ ] **Step 5: Commit** — `feat(estimates): superseding an estimate releases its atom claims (frozen snapshot)`

---

## Phase 5 — Converter rewrite (`nealsdata`)

Single emission path: Tasks/Materials/Fees straight on the Job; no plan/dual; Fees instead
of `Flat Fee $X` schemes.

### Task 5.1: Emit Tasks/Materials directly on the Job for every job status

**Files:** `nealsdata/converter/build.py` (`derive_atoms` 1428, delete `_build_plan_*` 1301-1381, delete `build_dual_atoms` ~1763, delete `_build_estworksheet` 1275, delete `_PLAN_STATUSES` branch), `orchestrator.py` (drop `build_dual_atoms` + `cut_plan_task`)
**Test:** `tests/test_converter_atoms.py` (create or extend) — run the converter against a tiny fixture input and assert it emits `jobs.task`/`inventory.material` rows and **no** `jobs.plantask`/`inventory.planmaterial`/`estimates.estworksheet` rows for a draft job.

- [ ] **Step 1: Failing test** (assert no plan-model rows emitted).
- [ ] **Step 2: Run; expect fail.**
- [ ] **Step 3: Implement** — collapse `derive_atoms` to the real-side path for all statuses; delete the plan builders and the dual-atom mirror; drop `EstWorksheet` emission and `source_plan_*` assignments. EstimateLineItemSource now emits `source_type='task'/'material'` (Task 1.2) against the job atoms.
- [ ] **Step 4: Run; PASS.**
- [ ] **Step 5: Commit** — `refactor(converter): emit Tasks/Materials on the Job; drop plan/dual atoms`

### Task 5.2: Emit Fees instead of minting `Flat Fee $X` RateSchemes

**Files:** `nealsdata/converter/build.py:956` (`_match_seed_scheme` — remove the flat-fee minting + `flat_fee_by_rate` cache at 116-118), `:1243` (`assign_est_quantities` — drop the `flat_fee` case), `parsing.py:270` (`infer_algorithm` — return a "fee" sentinel instead of `'flat_fee'`), `build_invoice_line_item_sources:1849` (+ `fee` claim fallback)
**Test:** `tests/test_converter_fees.py` (create)

**Interfaces:** a line the old code classified as `flat_fee` now becomes a `jobs.fee` row (`quantity` from the line qty or 1, `unit_rate` from the line price, `accounting_category` = services AC), claimed by its invoice/estimate line via `source_type='fee'`. No `jobs.ratescheme` row named `Flat Fee $...` is emitted.

- [ ] **Step 1: Failing test** — feed a line that infers to a fixed charge; assert the converter emits a `jobs.fee` with the right `unit_rate`/`quantity` and **zero** `Flat Fee $` RateSchemes.
- [ ] **Step 2: Run; expect fail.**
- [ ] **Step 3: Implement** — replace the `_match_seed_scheme` flat-fee branch and the `infer_algorithm`→`flat_fee` path with Fee emission in `derive_atoms`; delete `flat_fee_by_rate`; teach the invoice/estimate source builders to claim a `fee` atom for fee-classified lines.
- [ ] **Step 4: Run; PASS.**
- [ ] **Step 5: Commit** — `refactor(converter): emit Fee atoms for fixed charges; stop minting Flat Fee schemes`

---

## Phase 6 — Validator rewrite (`validate_data`)

**Files:** `apps/core/management/commands/validate_data.py`; `tests/test_validate_data.py`

### Task 6.1: Drop stale checks, add Fee checks, repoint source checks

- [ ] **Step 1: Update tests** (`tests/test_validate_data.py`):
  - Remove the `FLAT_FEE` zero-rate test (lines ~37-40) and any PlanTask/PlanMaterial/EstWorksheet fixtures.
  - Add: a `Fee` with `unit_rate <= 0` is an error; a `Fee` with a missing `accounting_category` is an error; a `Fee.quantity < 0` is an error.
  - Add: an `EstimateLineItemSource(source_type='task')` whose Task’s job ≠ the estimate’s job is an error (repointed cross-check); same for `'material'` and `'fee'`.
- [ ] **Step 2: Run `tests.test_validate_data`; expect fail.**
- [ ] **Step 3: Implement** in `validate_data.py`:
  - Delete `check_rate_schemes` FLAT_FEE branch (line 511-514); the PlanTask loop (343-349), PlanMaterial loop (363-376), and the empty `check_worksheets` (320).
  - Delete the `SOURCE_PLAN_TASK`/`SOURCE_PLAN_MATERIAL` job-consistency cross-checks (739-773); add equivalents over `SOURCE_TASK`/`SOURCE_MATERIAL`/`SOURCE_FEE` resolving to Job atoms and comparing `atom.job_id == source.estimate_line_item.estimate.job_id`.
  - Add `check_fees()`: `unit_rate > 0`, `accounting_category` present, `quantity >= 0`, and `task` (if set) belongs to the same job. Register it in `handle()`.
- [ ] **Step 4: Run; PASS.**
- [ ] **Step 5: Commit** — `refactor(validate_data): drop plan/flat_fee checks; add Fee + atom-source checks`

---

## Phase 7 — Frontend (Svelte SPA)

Rework the **job overview** to own the work; delete the worksheet surface; add the Fee path;
repoint the wizards. Each task ends with `cd frontend && npm run test:run` green.

### Task 7.1: Job overview page (`JobDetail.svelte`) — the central change

The job overview is where work now lives. Concrete changes:
- **Remove the worksheet pillar** and its fetch (`/api/est-worksheets/?job={id}`, JobDetail.svelte:~328).
- **`startEstimate()`** stops POSTing a worksheet (`POST /api/est-worksheets/`) and instead does **`POST /api/estimates/ {job}`** (Task 3.4), then navigates to the estimate.
- **New "Work" (Plan) section** on the overview listing the job's live **`job.tasks` / `job.materials` / `job.fees`**, each editable, with the unified **"Add line"** picker (service→Task via `/api/jobs/{id}/tasks/`, material→Material via `/api/jobs/{id}/materials/`, fee→hand-line/Fee). This section is visible **regardless of estimate state** — it is where pre-approval work (a site visit, a meeting) is created and shown, so an unapproved job's effort is visible as a loss.
- **Unclaimed badge:** atoms with `claimed=false` (Task 3.4) render an "not on current estimate" marker (informational, never blocking).
- **Estimate pillar Plan/Client View toggle:** *Plan view* now renders the job atoms (a read-only mirror of the Work section); *Client View* renders the estimate/CO line items (largely unchanged).
- **Invoices pillar:** `hasBillables` now reads `job.tasks/materials/fees`; `createInvoiceManual()` endpoint unchanged.

**Files:** modify `frontend/src/components/jobs/JobDetail.svelte`; modify `frontend/src/App.svelte` (estimate-start navigation target). 
**Tests:** update `frontend/tests/components/jobs/JobDetail.test.js` (+ `JobDetail.invoiced.test.js`).

- [ ] **Step 1: Update/add Vitest tests** — the Work section lists `job.tasks`/`job.materials`/`job.fees`; `startEstimate()` posts to `/api/estimates/` (not `/api/est-worksheets/`); an atom with `claimed:false` shows the unclaimed badge; `hasBillables` is true when the job has any atom; the worksheet pillar is gone.
- [ ] **Step 2: Run; expect fail.**
- [ ] **Step 3: Implement** the pillar reorg, the `startEstimate` repoint, the Work section + Add-line wiring, and the unclaimed badge.
- [ ] **Step 4: `npm run test:run`; PASS.**
- [ ] **Step 5: Commit** — `feat(spa): job overview owns the Work section; Start Estimate creates an estimate directly`

### Task 7.2: Delete the worksheet surface; repoint `WorkItemForm`

**Files:** delete `frontend/src/routes/worksheets/WorksheetDetailPage.svelte`, `frontend/src/routes/worksheets/PlanTaskDetailPage.svelte`, `frontend/src/components/WorksheetTaskTable.svelte`, `frontend/src/components/PlanMaterialModal.svelte`; modify `frontend/src/components/WorkItemForm.svelte` (POST `/api/jobs/{id}/tasks/`, drop the worksheet `contextId` branch); remove the worksheet/plan-task routes from `App.svelte`.
**Tests:** delete `frontend/tests/components/worksheets/*.test.js`; update `WorkItemForm.test.js`.

- [ ] **Step 1:** Update `WorkItemForm.test.js` to assert the job-task POST target; delete the worksheet page tests.
- [ ] **Step 2: Run; expect fail** (dangling imports/routes).
- [ ] **Step 3:** Delete the four components + their routes; repoint `WorkItemForm`. `grep -rn "est-worksheets\|plan-tasks\|WorksheetDetail\|PlanTaskDetail\|PlanMaterialModal\|WorksheetTaskTable" frontend/src` → clear every hit.
- [ ] **Step 4: `npm run test:run`; PASS.**
- [ ] **Step 5: Commit** — `refactor(spa): delete the worksheet pages; WorkItemForm targets the Job`

### Task 7.3: Add-line gains a Fee path; `FeeModal`

**Files:** create `frontend/src/components/FeeModal.svelte` (name, quantity, unit_rate, accounting_category, optional task link; POST `/api/jobs/{id}/fees/`); modify `PriceListPicker.svelte` (third free-text branch → “fee/hand-line”), `LineItemModal.svelte` (a hand-line is allowed; no atom required), `wizards/WizardAtomRow.svelte` (label `fee`).
**Tests:** `FeeModal.test.js` (create); update `PriceListPicker.test.js`.

- [ ] **Step 1:** Vitest: `FeeModal` posts the right payload; picker emits `kind:'fee'` for the free-text-fee branch.
- [ ] **Step 2: Run; expect fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: `npm run test:run`; PASS.**
- [ ] **Step 5: Commit** — `feat(spa): add Fee creation (FeeModal + picker branch + wizard label)`

### Task 7.4: Estimate/Invoice wizards + out-of-sync over Job atoms

**Files:** `EstimateWizardPage.svelte`, `InvoiceWizardPage.svelte`, `EstimateDetailPage.svelte` (`lineOutOfSync()` applies to atom-backed draft-estimate lines only), `InvoiceDetailPage.svelte` (`hasBillables` reads `job.tasks/materials/fees`; seed buttons unchanged endpoints).
**Tests:** update the estimate/invoice wizard + detail tests.

- [ ] **Step 1:** Update tests: source pool shape now lists Task/Material/Fee atoms from the job; out-of-sync warning shows only on draft estimates; invoice wizard shows Fees as billable.
- [ ] **Step 2: Run; expect fail.**
- [ ] **Step 3: Implement** the source-pool/`hasBillables` repoint; gate the out-of-sync UI to draft estimates.
- [ ] **Step 4: `npm run test:run`; PASS.**
- [ ] **Step 5: Commit** — `feat(spa): wizards project Job atoms; out-of-sync is estimate-draft-only`

---

## Phase 8 — Regenerate dataset & full validation (user-run DB steps)

### Task 8.1: Regenerate + re-enable fixture tests

- [ ] **Step 1:** Run the converter to emit the new fixture (no DB write): `python -m nealsdata.converter ...` (per `orchestrator.py` entry). Inspect the JSON: no `jobs.plantask`/`inventory.planmaterial`/`estimates.estworksheet`/`Flat Fee $` rows; `jobs.fee` rows present.
- [ ] **Step 2:** Re-enable the fixture tests skipped in Task 4.2; run `tests.test_neals_fixture` + `tests.test_validate_data` against the regenerated fixture; green.
- [ ] **Step 3:** Run the **entire** backend suite without `--keepdb`, then `cd frontend && npm run test:run`. All green.
- [ ] **Step 4: Commit** — `test: regenerate dataset for the job-owns-atoms model; re-enable fixture tests`
- [ ] **Step 5 (user):** Hand off to the user to **wipe the dev DB, apply migrations, and load the regenerated dataset** — the agent must not touch the dev DB.

### Task 8.2: Docs

- [ ] Update `docs/designs/estimates-and-prices.md`, `jobs-tasks-and-worksheets.md`,
  `materials-inventory-and-purchasing.md`, `invoicing-and-expenses.md`, and
  `data-constraints.md` to the new model (no plan layer; Fee atom; documents-as-lenses).
  Commit — `docs(designs): job-owns-atoms model (Fee, documents-as-lenses, no plan layer)`.

---

## Self-review against the spec

- **Remove PlanTask/PlanMaterial/EstWorksheet** → Task 4.2. **Task subsumes PlanTask
  (`est_qty`+`actual_qty`)** → Tasks 2.1, 3.1 (`compute_estimate_amount`).
- **Add Fee (single object, no PlanFee; FeeItem deferred)** → Phase 1; FeeItem intentionally
  absent (spec [DEFAULT]).
- **`Task.rate_scheme` stays NOT NULL; drop `flat_fee`** → Task 4.1 (Task model unchanged).
- **Documents as lenses / optional severable link** → Tasks 3.1, 3.3, 4.3 (sources are
  optional; supersede detaches).
- **Liveness: estimate drafts reconcile; invoice lines lock at completion; never lock
  atoms** → Task 3.1 (`compute_estimate_amount`), 7.4 (out-of-sync draft-only), invoice gate
  retained (Phase 1.3 keeps Task-complete/Material-consumed; Fees always billable).
- **Acceptance crystallizes hand-lines → Fees; earmark on accept** → Task 3.2.
- **At-most-one-invoice claim** → existing `unique_together`, extended to `fee` (Task 3.3).
- **Materials pick → Material atom** → Task 2.2 + 7.3 (picker branch).
- **Job overview owns the work; pre-approval work visible; Start Estimate has no
  worksheet; unclaimed atoms flagged** → Task 3.4 (backend: create-on-job + claim state) +
  Task 7.1 (the JobDetail rework) + Task 7.2 (delete the worksheet pages).
- **No data migration; schema + regenerate; converter + validator updated** → Phases 4-6, 8.
- **Deferred:** FeeItem catalog; change-order↔Fee interaction (spec [DEFERRED]) — not in
  this plan; note in Phase 8 docs as follow-ons.

**Open risk to watch during execution:** Task 4.2 leaves `tests.test_neals_fixture` red
until Phase 8 — skip it explicitly (don’t let it mask other regressions), and confirm it’s
the *only* intentionally-red test at each Phase-4→7 boundary.
