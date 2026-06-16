# Expenses ↔ Job attribution — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make a Job the anchor for an expense's cost (nullable `Expense.job`), with cost-on-material, full editability + invoiced-freeze, freeform-cost-is-document-sourced, Job-UI surfacing, and (Part B) material-less expenses as billable atoms in the invoice wizard.

**Spec:** `docs/plans/2026-06-13-expenses-job-attribution-redesign.md` (authoritative; read A1–A9, B1–B3).

**Tech:** Django 5.2 + DRF (MySQL), Svelte 5 SPA (Vitest). TDD throughout.

**CRITICAL — never write to the dev DB.** No `migrate`, no `shell`/`shell_plus` ORM writes, no `loaddata`, no direct DB writes, no repo seed scripts. `makemigrations` is fine. Tests use a separate auto-created test DB — `python manage.py test` is allowed. **Only one backend test process at a time** (shared MySQL test DB; never run tests from parallel subagents). Frontend tests: `cd frontend && npm run test:run` (never watch mode).

**Decided open items** (from spec review):
- `Expense.job` → `on_delete=SET_NULL` (mirrors `Expense.material`'s SET_NULL; preserves the financial record as overhead if a job is hard-deleted).
- Material-linked expenses render as an **annotation** on their material's row (not a separate row).

**Key file anchors discovered:**
- `apps/expenses/models.py` (Expense), `apps/expenses/services.py` (ExpenseService).
- `apps/api/expenses/views.py` (ExpenseViewSet), `apps/api/expenses/serializers.py`.
- `apps/jobs/financials.py` `_spent()` lines 92-120 — **already** counts material-linked expenses by amount + consumed-no-expense materials at cost, with a documented no-double-count invariant.
- `apps/inventory/services.py` `MaterialService.update_pricing` (335-), `consume/unconsume` (398-449); `MaterialBase._populate_from_pli` (models 153-165).
- Invoice wizard: `apps/invoicing/services.py` `InvoiceWizardService` (346-589) `get_source_pool` (387-518), helpers `_resolve_atom`/`_atom_source_type`/`_atom_units`/`_atom_qty_and_price`; `apps/core/wizard.py` `BaseWizardService` (210-301); `apps/invoicing/models.py` `InvoiceLineItemSource` (160-198).
- Frontend: `components/expenses/ExpenseForm.svelte`, `MaterialPicker.svelte`; `components/MaterialModal.svelte`; `components/jobs/JobDetail.svelte` (pillar-mat ~918-1001); `routes/jobs/JobTaskListPage.svelte` + `components/TaskTree.svelte`; reusable `components/JobPicker.svelte` (emits `{job_id, job_number}`).
- Tests: `tests/test_expense_model.py`, `test_expense_service.py`, `test_api_expenses.py`, `test_job_financials.py` (`SpentTests` 98-186), `test_invoice_wizard*`; frontend `frontend/tests/components/expenses/ExpenseForm.test.js`, `JobPicker.test.js`.

---

## PART A — Expense↔Job foundation

### Task A1: `Expense.job` model field + migration + backfill + consistency

**Files:** Modify `apps/expenses/models.py`; create migration in `apps/expenses/migrations/`; test `tests/test_expense_model.py`.

- [ ] **Step 1 — failing tests** in `tests/test_expense_model.py`:
  - `test_job_optional` — Expense can be created with `job=None` (overhead) and with a job.
  - `test_material_job_must_match_expense_job` — `clean()` raises `ValidationError` when `material` is set and `material.job_id != job_id`.
  - `test_material_without_explicit_job_ok` — material set, job set to material's job → valid.
- [ ] **Step 2** — run, verify they fail (field/validation absent).
- [ ] **Step 3 — implement:**
  - Add to `Expense`:
    ```python
    job = models.ForeignKey(
        'jobs.Job', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='expenses',
    )
    ```
  - In `Expense.clean()` (after existing payment checks), add:
    ```python
    if self.material_id and self.job_id and self.material.job_id != self.job_id:
        errors['job'] = 'Expense job must match the linked material’s job.'
    ```
    (merge into the existing `errors` dict before the final raise).
  - `makemigrations expenses`. Then **add a data migration** (same or follow-on migration file) that backfills `job` from material: for rows with `material_id` and null `job`, set `job_id = material.job_id` (fallback `material.task.job_id`). Use a `RunPython` with the historical models; guard reverse as `noop`.
- [ ] **Step 4** — `python manage.py test tests.test_expense_model -v` → pass.
- [ ] **Step 5** — commit: `feat(expenses): add nullable Expense.job FK + backfill + consistency`.

### Task A2: ExpenseService — accept `job`, link/unlink cost, invoiced-freeze (material case), move-between-jobs

**Files:** Modify `apps/expenses/services.py`; new helper(s); test `tests/test_expense_service.py`.

Read `apps/inventory/services.py` `MaterialService.update_pricing`, `consume`, `unconsume`, `_mutate_earmark` first.

- [ ] **Step 1 — failing tests** (`tests/test_expense_service.py`, follow existing `_seed_job_config`/TestCase pattern):
  - `test_submit_accepts_job` — `submit(..., job=job)` persists `expense.job`.
  - `test_update_can_change_job` — `update(expense=e, actor=u, job=other_job)` moves it (material-less).
  - `test_link_existing_material_sets_cost` — material with `unit_cost=0`, `quantity=2`; linking an expense with `amount=50` sets `material.unit_cost == Decimal('25.00')` (= amount/quantity).
  - `test_link_does_not_clobber_existing_cost` — material already `unit_cost=10` (PLI-backed) → linking does **not** overwrite; surfaces a mismatch (raise `ValidationError` with a clear message, OR record a flag — choose raise for now).
  - `test_unlink_clears_expense_sourced_cost` — material whose only cost source was the expense (no `po_line_item`, no other expenses) → unlinking resets `unit_cost` to 0.
  - `test_unlink_keeps_cost_when_po_backed` — material with `po_line_item` set → unlink leaves `unit_cost` unchanged.
  - `test_frozen_when_material_on_invoice` — material has a non-cancelled `InvoiceLineItemSource` (SOURCE_MATERIAL) → `update(...)` raises `ValidationError` (immutable while on invoice).
  - `test_move_consumed_material_to_other_job` — material `consumed` + inventoried PLI → moving expense+material to another job composes `unconsume` → re-`_mutate_earmark` to new job → re-`consume`; ends consumed on the new job with QOH/earmark consistent.
- [ ] **Step 2** — run; verify failures.
- [ ] **Step 3 — implement:**
  - Add `'job'` to the `update()` `allowed` set; add `job=None` param to `submit()` and pass into the `Expense(...)` construction.
  - Add a freeze guard helper `_assert_not_invoiced(expense)`: raises `ValidationError('Cannot edit an expense that is on an invoice; remove it from the invoice first.')` when the expense **or its material** has a live (non-cancelled-invoice) `InvoiceLineItemSource`. Call it at the top of `update()` and `delete()`. (Expense-atom source handled in Part B; here check material sources via `InvoiceLineItemSource.objects.filter(source_type='material', source_pk=expense.material_id).exclude(invoice cancelled)`.)
  - **Cost link/unlink:** when `update()` (or `submit`) changes the `material` link:
    - On **link** (material newly set): if `material.unit_cost == 0` → set `unit_cost = (sum of linked-expense amounts incl. this) / material.quantity` (guard qty 0 → leave 0); else if non-zero and differs → raise mismatch `ValidationError`.
    - On **unlink** (material cleared/replaced): if the departing material now has no `po_line_item` and no remaining expenses → set its `unit_cost = 0` via `MaterialService.update_pricing(material, unit_cost=Decimal('0.00'))`.
    - Route cost writes through `MaterialService.update_pricing` (respects job-on-hold guard) — do **not** bypass `save()`.
  - **Move-between-jobs:** when `job` changes and a material is linked, the material moves too: if consumed → `unconsume`, set `material.job`, then `consume` again (so QOH/earmark land on the new job). Wrap in `transaction.atomic()`. Keep `reject()`'s consumed-material wall unchanged (reject ≠ move).
- [ ] **Step 4** — `python manage.py test tests.test_expense_service -v` → pass.
- [ ] **Step 5** — commit: `feat(expenses): service job field, cost link/unlink, invoiced-freeze, move-between-jobs`.

### Task A3: Serializer + ViewSet — job read direct & writable; select_related

**Files:** `apps/api/expenses/serializers.py`, `apps/api/expenses/views.py`; test `tests/test_api_expenses.py`.

- [ ] **Step 1 — failing tests** (`tests/test_api_expenses.py`, `Client()` pattern):
  - `test_create_with_job_no_material` — POST `/api/expenses/` with `job` and no material → 201; GET shows `job_id/job_number/job_name` populated (the blank-column fix).
  - `test_patch_job` — PATCH `/api/expenses/{id}/` `{job: other}` → moves (needs `can_manage_financials`).
  - `test_list_filter_by_job` — `?job=<id>` filters.
  - `test_overhead_expense_has_null_job` — create with no job → `job_id` null.
- [ ] **Step 2** — run; verify failures.
- [ ] **Step 3 — implement:**
  - Make `job` a writable `PrimaryKeyRelatedField(queryset=Job.objects.all(), required=False, allow_null=True)`; remove `job_id`/`job_number`/`job_name` from `read_only` derivation via material — instead derive from `obj.job` directly (`get_job_id` → `obj.job_id`, etc.). Keep `task_name` only if `obj.material` has a task; otherwise drop it (expenses no longer set tasks — safe to keep returning None).
  - `_job(obj)` → `return obj.job` (drop material derivation).
  - ViewSet `get_queryset`: add `'job'` (and keep `'material__job'`) to `select_related`; add `?job=` filter param.
- [ ] **Step 4** — `python manage.py test tests.test_api_expenses -v` → pass.
- [ ] **Step 5** — commit: `feat(api): expense job field read/write + filter`.

### Task A4: Job-cost rollup includes material-less expenses

**Files:** `apps/jobs/financials.py` `_spent()`; test `tests/test_job_financials.py`.

- [ ] **Step 1 — failing tests** (`SpentTests` in `tests/test_job_financials.py`):
  - `test_includes_material_less_job_expense` — a material-less expense (`job=job`, `material=None`, status submitted) is summed into spent.
  - `test_excludes_overhead_expense` — an expense with `job=None` is **not** in any job's spent.
  - `test_no_double_count_material_linked_expense` (extend existing) — a material-linked expense counts once (its amount), and its material is not also counted.
- [ ] **Step 2** — run; verify failures.
- [ ] **Step 3 — implement:** in `_spent()`, change the expense aggregation from `Expense.objects.filter(material__job=job)` to `Expense.objects.filter(job=job)` (this now covers **both** material-linked and material-less expenses; overhead `job=None` is excluded automatically). Keep the consumed-no-expense materials term unchanged. Update the docstring to state the three-way no-double-count: all non-rejected expenses on the job count by amount; consumed materials with no expense count at cost; overhead (job=None) excluded.
- [ ] **Step 4** — `python manage.py test tests.test_job_financials -v` → pass.
- [ ] **Step 5** — commit: `feat(jobs): job cost includes material-less expenses (no double-count)`.

### Task A5: Backend — freeform actual-Material cost is document-sourced only

**Files:** `apps/inventory/services.py` (`MaterialService.create_on_job` / `update_pricing` or the material API view), `apps/api/inventory/views.py` (and `apps/api/tasks/views.py`, `apps/api/jobs/views.py`, `apps/api/worksheets/views.py` material-create endpoints); test `tests/test_inventory_*` (find the existing material service/API test module).

Goal: a **freeform** (no-PLI) **actual `Material`** may not receive a manually-supplied `unit_cost` (must come from an Expense or PO). PLI-linked materials and PlanMaterial/estimating are unaffected.

- [ ] **Step 1 — failing tests** (locate the existing material create/update test module first):
  - `test_freeform_material_rejects_manual_cost` — creating/updating a no-PLI Material with a non-zero `unit_cost` from the manual path raises `ValidationError` (or silently ignores → coerces to 0; **choose: reject with a clear message**).
  - `test_pli_material_cost_unaffected` — PLI-linked material still gets/keeps cost.
  - `test_expense_link_can_set_freeform_cost` — cost set via the expense link path (Task A2) still works (the prohibition is only on the *manual* path).
- [ ] **Step 2** — run; verify failures.
- [ ] **Step 3 — implement:** in the manual cost entry path (`MaterialService.update_pricing` and `create_on_job` when called from user-facing material endpoints), reject a non-zero `unit_cost` when `price_list_item is None`. Provide an internal bypass flag (e.g. `cost_source='document'`) used by the expense-link and PO-receiving paths so they can still set cost. Ensure `_populate_from_pli` (PLI path) is untouched. Confirm carry-over (`carry_over.py`, always PLI-linked) is unaffected.
- [ ] **Step 4** — run the material test module → pass; also run `tests.test_expense_service` to confirm A2 cost-setting still works.
- [ ] **Step 5** — commit: `feat(inventory): freeform material cost is document-sourced only`.

### Task A6: Frontend — rework ExpenseForm + MaterialPicker (job anchor, no silent-drop)

**Files:** `frontend/src/components/expenses/ExpenseForm.svelte`, `frontend/src/components/expenses/MaterialPicker.svelte`; reuse `components/JobPicker.svelte`; test `frontend/tests/components/expenses/ExpenseForm.test.js`, new `MaterialPicker.test.js`.

New UX: ExpenseForm has a **Job** field (JobPicker, emits `{job_id, job_number}`) bound to a new `job` payload field. The (renamed) material sub-control is optional: once a job is chosen, show its existing Materials to link, an explicit "leave job-only" default, and an "Add new material" affordance. Picking a job alone submits `{job: id, material: null, new_material: null}` — valid, no silent drop.

- [ ] **Step 1 — failing tests** (mirror existing ExpenseForm test mocking of `@/lib/api.js`, `user` store, `getPaymentAccounts`):
  - `submits job with no material` — choose job, save → POST body has `job` set, `material` null, no `new_material`.
  - `links an existing material` — choose job → existing materials load (`/api/jobs/{id}/` + per-task `/api/tasks/{tid}/materials/`, plus job-level `job.materials`) → pick one → POST has `material` id, `job` set.
  - `create-new-material still works` — POST has `new_material` with `job_id`.
  - `editing preserves job` — edit mode loads `expense.job` into the picker.
- [ ] **Step 2** — run `cd frontend && npm run test:run -- ExpenseForm MaterialPicker` → fail.
- [ ] **Step 3 — implement:** add `job` to ExpenseForm state + payload; embed `JobPicker`; refactor `MaterialPicker` to take the chosen `job` as a prop (no internal job search duplication) and emit material/new_material without clearing on unrelated changes (kill the `pickJob` clear-on-reselect drop). Include job-level materials (`job.materials.filter(m=>!m.task)`) in the link list, not just task materials. Default state = job-only (material null).
- [ ] **Step 4** — frontend tests pass.
- [ ] **Step 5** — commit: `feat(ui): expense form anchored on job; remove silent-drop`.

### Task A7: Frontend — material-modal freeform cost lock + Job-UI surfacing

**Files:** `frontend/src/components/MaterialModal.svelte`; `frontend/src/components/jobs/JobDetail.svelte` (pillar-mat); `frontend/src/components/TaskTree.svelte` + `routes/jobs/JobTaskListPage.svelte`; tests alongside.

- [ ] **Step 1 — failing tests:**
  - MaterialModal: `unit cost disabled when freeform` — when no PLI selected, the Unit Cost input is `disabled` (and not submitted); enabled/auto behavior for PLI unchanged.
  - JobDetail: `materials pillar shows material-less expenses as rows and annotates material-linked ones` — given a job with `expenses`, render expense rows (amount/category/payment badge) and a "paid $X" annotation on linked material rows. (Add `job.expenses` to the data the page consumes; confirm `/api/jobs/{id}/` returns expenses or fetch `/api/expenses/?job=`.)
  - TaskTree/JobTaskListPage: `job-level expenses render in the no-task section`.
- [ ] **Step 2** — run; fail.
- [ ] **Step 3 — implement:** disable the cost input in MaterialModal when `pliId` is null (freeform). Surface expenses on the job: prefer fetching `/api/expenses/?job={id}` in `JobDetail`/`JobTaskListPage` load (or extend the job serializer to embed `expenses`). Render per the spec A9 (Materials & Expenses pillar; job-level rows in TaskTree's "Materials (no task)" area). Material-linked expense → annotation on the material row; material-less → own row. Update the pillar count.
- [ ] **Step 4** — frontend tests pass.
- [ ] **Step 5** — commit: `feat(ui): freeform cost lock + expenses on job overview/task list`.

---

## PART B — Billing

### Task B1: Expense as a billable atom (backend)

**Files:** `apps/expenses/models.py` (atom interface), `apps/invoicing/models.py` (`InvoiceLineItemSource`), `apps/invoicing/services.py` (`InvoiceWizardService`); migration for the new source_type choice; tests `tests/test_invoice_wizard*` (find module).

- [ ] **Step 1 — failing tests:**
  - `test_expense_atom_compute_amount` — `Expense.compute_amount()` returns `amount`.
  - `test_source_pool_lists_material_less_expenses` — wizard `get_source_pool` for a job includes an "Expenses" group containing material-less, non-rejected expenses; material-linked expenses are **absent** (they bill via material).
  - `test_add_expense_atom_creates_line_item` — POST `/api/invoices/{id}/line-items-from-atoms/` with `{type:'expense', id}` creates a line item with `price == expense.amount` (pass-through) and an `InvoiceLineItemSource(source_type='expense', source_pk=expense.id)`.
  - `test_expense_already_invoiced_marked` — once on a non-cancelled invoice, the expense shows `claimed_by_*` in the pool (not removed).
  - `test_overhead_expense_not_offered` — expense with `job=None` never appears.
- [ ] **Step 2** — run; fail.
- [ ] **Step 3 — implement:**
  - `Expense`: add `compute_amount(self, active_modifiers=None): return self.amount` and `@property effective_accounting_category: return self.accounting_category` (and ensure it exposes `description`).
  - `InvoiceLineItemSource`: add `SOURCE_EXPENSE = 'expense'` to constants + `source_type` choices; extend `resolve()` to return `Expense` for that type. `makemigrations invoicing` (choices change → migration).
  - `InvoiceWizardService.get_source_pool`: after the "Materials (no task)" group, add an **Expenses** group enumerating `Expense.objects.filter(job=job, material__isnull=True).exclude(status=REJECTED)`, with claim state keyed `(SOURCE_EXPENSE, expense.pk)`. Extend the claimed-sources query/dict to include expense sources.
  - Wizard hooks: `_resolve_atom` (type `'expense'` → Expense), `_atom_source_type` (Expense → SOURCE_EXPENSE), `_atom_units` (Expense → `'none'`), and single-atom qty/price (`_atom_qty_and_price`): Expense → `qty=1`, `price=expense.amount`, `description=expense.description or category name`. Confirm `BaseWizardService.add_atoms_to_new_line_item` needs no change (duck-typed).
- [ ] **Step 4** — run the wizard test module (single test process) → pass.
- [ ] **Step 5** — commit: `feat(invoicing): expense as billable atom (material-less, pass-through cost)`.

### Task B2: Invoiced-freeze extends to expense-on-invoice

**Files:** `apps/expenses/services.py` `_assert_not_invoiced`; test `tests/test_expense_service.py`.

- [ ] **Step 1 — failing test:** `test_frozen_when_expense_on_invoice` — a material-less expense with a non-cancelled `InvoiceLineItemSource(source_type='expense')` → `update()`/`delete()` raise.
- [ ] **Step 2** — fail.
- [ ] **Step 3 — implement:** extend `_assert_not_invoiced` to also check `InvoiceLineItemSource.objects.filter(source_type='expense', source_pk=expense.pk).exclude(invoice cancelled).exists()`. (Material case already added in A2.)
- [ ] **Step 4** — `python manage.py test tests.test_expense_service` → pass.
- [ ] **Step 5** — commit: `feat(expenses): freeze extends to expense-on-invoice`.

### Task B3: Frontend — wizard surfaces Expenses group

**Files:** `frontend/src/components/invoices/WizardSourcePool.svelte` (+ `WizardAtomRow.svelte` if type-specific rendering); tests alongside.

- [ ] **Step 1 — failing test:** source pool renders an "Expenses" group; an expense atom row shows amount; an already-invoiced expense shows the claimed badge; selecting it posts `{type:'expense', id}`.
- [ ] **Step 2** — fail.
- [ ] **Step 3 — implement:** render the new group/type from the source-pool payload; reuse existing claim-state styling; ensure the atom ref sent is `{type:'expense', id}`.
- [ ] **Step 4** — frontend tests pass.
- [ ] **Step 5** — commit: `feat(ui): invoice wizard surfaces expense atoms`.

---

## Final: durable docs

### Task D1: Update durable docs (behavior now exists)

**Files:** `docs/designs/invoicing-and-expenses.md`, `docs/designs/materials-inventory-and-purchasing.md`, `docs/designs/jobs-tasks-and-worksheets.md`.

- [ ] Apply the concrete per-doc checklist from the design spec's "Durable docs to update" section: `Expense.job` anchor + cost-on-material + no-double-count + invoiced-freeze + Part B billing (invoicing-and-expenses); unit_cost provenance map + freeform-document-sourced rule + link/unlink + job-costing read rule (materials-inventory-and-purchasing); Job-UI surfacing + P&L rollup (jobs-tasks-and-worksheets). Remove any stale "no path from expense to invoice" statement.
- [ ] Commit: `docs: expenses↔job redesign reference updates`.

---

## Self-review checklist (run before final)
- Spec coverage: A1–A9 → Tasks A1–A7 (A8 rollup = A4; A9 UI = A7); B1–B3 → Tasks B1–B3. ✓
- No-double-count: enforced in A4 (`filter(job=job)` covers both expense kinds; consumed-no-expense at cost). ✓
- Invoiced-freeze: material case (A2) + expense case (B2). ✓
- Freeform cost rule: backend (A5) + frontend lock (A7); link/unlink (A2). ✓
- Type consistency: atom ref `{type:'expense', id}`; source_type `'expense'`; `compute_amount` signature matches duck-typed interface. ✓
