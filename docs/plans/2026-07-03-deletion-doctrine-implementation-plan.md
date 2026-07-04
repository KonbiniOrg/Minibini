# Deletion doctrine — TDD implementation plan

> **Status: ✅ EXECUTED 2026-07-03 on `feature/unification` — pending review.**
> All nine tasks done; both suites green (backend fresh, frontend). One deviation
> from the plan text: the invoice wizard pool needed no released-filter (it
> already filters `quantity__gt=0`, which released rows satisfy structurally).
>
> Executes `2026-07-03-deletion-doctrine-named-events.md` (all [SETTLED]/[DEFAULT]
> items; the two [DEFERRED] passes — post-approval expense voiding, bill-payment
> voiding — are out of scope). TDD per task: failing test → verify red → implement
> → green. One agent runs tests at a time; final suite runs fresh (no --keepdb,
> migrations change).

## Task 1 — Material model: `released` state + `restocked_qty` → `released_qty`

**Files:** `apps/inventory/models.py`, new migration, `apps/api/tasks/serializers.py`,
`apps/api/inventory/serializers.py`, `apps/api/tasks/views.py` (QUANTITY_FIELDS),
`apps/inventory/services.py` (expense-void reversal reads the renamed field).
**Tests:** extend `tests/` material model/service coverage.

- `CONSUMPTION_STATE_RELEASED = 'released'` added to choices.
- `RenameField` migration for `restocked_qty` → `released_qty` (verify makemigrations
  emits a rename, not remove+add; hand-write if needed).
- Grep the codebase for `restocked_qty` after the rename (field-rename rule).

## Task 2 — `MaterialService.release()` + the referenced-check

**Files:** `apps/inventory/services.py`, `apps/estimates/claims.py`.
**Tests:** new `tests/test_material_release.py`.

- `claims.atom_is_claimed(source_type, pk)` — any EstimateLineItemSource /
  ChangeOrderLineItemSource row.
- `MaterialService._is_referenced(material, ignore_po_link=False)` — expense-bound,
  PO-linked, `atom_is_claimed('material')`, or `is_invoiced('material')`.
- `release(material)`: requires pending; atomic: earmark −quantity,
  `released_qty += quantity`, `quantity = 0`, state → released. Terminal:
  consume/restock/draw_more/assign/link all already require pending.
- Invariant test: `quantity + released_qty` conserved; earmark gone; claims intact.

## Task 3 — Restock-to-zero rule (covers manual restock + loose release)

**Files:** `apps/inventory/services.py` (`restock`).
**Tests:** extend `tests/test_material_release.py` + existing restock tests.

- Restock always increments `released_qty` (was expense-bound-only) — conservation
  becomes universal.
- At quantity 0: `_is_referenced` → released; else delete (scratch paper).
- Expense-bound qty-0 limbo rows now land in `released` (state, not just kept-pending).
- `JobService.release_loose_materials` needs no change (it calls restock) — test the
  claimed-material path end-to-end: job completion → material released, claim resolvable
  (the acrylic regression, upgraded from “doesn’t 500” to “keeps history”).

## Task 4 — PO sever + CO retirement release instead of delete

**Files:** `apps/inventory/services.py` (`sever`), `apps/estimates/co_acceptance.py`.
**Tests:** existing sever tests; `tests/test_change_order_acceptance.py` updated.

- `sever(…, 'delete')`: unlink the dying PO line, then release-if-referenced else delete.
- CO `_retire` material branch: swap delete+implicit-purge for `release()` — claims
  survive; skip-conditions (consumed / expense-bound / PO-linked / invoiced) unchanged.
- Update acceptance tests: removed/replaced materials are `released` (not deleted),
  estimate-line sources still resolve, earmark math unchanged.

## Task 5 — Expense-reject claimed guard

**Files:** `apps/expenses/services.py` (`reject`).
**Tests:** existing expense tests + new claimed case.

- Reject refuses while the expense-created material is claimed (any lens) — extends the
  existing consumed-guard; then its delete is always Rule-1-legal.

## Task 6 — Rule-1 deletion guards: Fee, Task, Blep, Job

**Files:** `apps/jobs/services.py` (FeeService.delete, TaskService.delete_task,
BlepService.delete, new `JobService.assert_job_deletable`), `apps/api/jobs/views.py`
(destroy).
**Tests:** new `tests/test_deletion_guards.py`.

- **Fee**: refuse while `atom_is_claimed('fee')` or `is_invoiced('fee')` — message points
  at the change-order flow. Unreferenced fees delete as today.
- **Task**: additionally refuse while claimed by a **non-draft** estimate/CO or
  `is_invoiced('task')`. Draft claims stay deletable (purge cleans; “remove from the
  line first” remains available).
- **Blep**: `BlepService.delete` refuses when `is_invoiced('task', blep.task_id)` —
  applies to own-window and manager paths alike. (`cancel_work`’s open-blep delete is
  unreachable for invoiced tasks — they’re complete.)
- **Job**: destroy refuses when the job has bleps, invoices, or any non-draft
  estimate/CO — “cancel instead.” Unworked draft-quote jobs still hard-delete.

## Task 7 — InventoryItem: stop collecting; guard the delete endpoint

**Files:** `apps/inventory/services.py` (`collect_if_finished`, write_off, demote path),
`apps/api/inventory/views.py`.
**Tests:** existing write-off/demote tests updated; new delete-guard cases.

- `collect_if_finished` no longer deletes — finished lots stay as hidden rows
  (hide-on-spend already handles visibility; catalog items already survive at QOH 0).
- The delete endpoint refuses unless never-referenced: `can_be_deleted` (PROTECT lens)
  **and** no Material / Earmark / Expense-stock references.
- Write-off API response no longer has the removed/deleted branch.

## Task 8 — Pool display filters + frontend sweep

**Files:** `apps/estimates/services.py` + `apps/invoicing/services.py`
(`get_source_pool` material queries exclude released), `frontend` (write-off flow no
longer expects `deleted: true`; material state branches tolerate `released`).
**Tests:** wizard-pool tests + Vitest updates; `npm run test:run`.

- Released materials out of both wizard pools (cosmetic — they compute to 0 anyway).
- Job-detail material lists keep released rows visible (history on the job).

## Task 9 — Docs + full verification

- `materials-inventory-and-purchasing.md`: lifecycle table, `released`, restock rule,
  `released_qty`, write-off change. `estimates-and-prices.md` §14.11: CO retirement
  releases materials (claims survive); fee behavior unchanged. `data-constraints.md`:
  Material fields/states, the new guards. `jobs-tasks-and-worksheets.md`: task/blep
  delete guards. `invoicing-and-expenses.md`: reject guard.
- Full backend suite **fresh** (no --keepdb); frontend suite; retire both doctrine plan
  docs to “implemented” status.
