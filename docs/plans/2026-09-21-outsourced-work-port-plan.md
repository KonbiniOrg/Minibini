# Outsourced-Work Port — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Port Phase 5 (outsourced-work POs: reconciliation + rate prompt + linked-PO variance) from `feature/fees` onto `feature/estimating`, per the spec's rulings.

**Architecture:** Faithful port of the fees implementation with three re-shapes: parent_task machinery excised, `current_rate = effective_rate()`, e2e/docs re-grounded on agreement-skeleton invoicing. Implementers read source from `git show feature/fees:<path>` (read-only; NEVER check out or switch branches) and re-apply.

**Tech Stack:** Django 5.2 + DRF, Svelte 5, Vitest, Playwright.

**Spec:** `docs/plans/2026-09-21-outsourced-work-port.md`. **Analysis (per-component verdicts, exact field defs, service semantics, file paths):** `docs/plans/2026-09-21-phase5-port-analysis.md` — every implementer reads its sections named in their task.

## Global Constraints

- Branch **feature/estimating**; commit there; never merge/push/PR; never create/switch/checkout branches (fees content only via `git show feature/fees:<path>`).
- NEVER write the dev database. `makemigrations` allowed (Task 1 ports migration 0025); NEVER `migrate`.
- Django tests: foreground single Bash call, timeout param 600000, `--noinput`, judged ONLY by the `Ran N tests`/`OK`/`FAILED` summary, one run at a time, targeted modules per task.
- Vitest: `cd frontend && npm run test:run` (never watch). Playwright: `cd e2e && npx playwright test <dir>` foreground, judged by summary.
- Subagents NEVER spawn sub-agents, background anything, arm Monitors, or wait for notifications.
- No user-visible "atom"/"wizard"/"blep". Error contract: field-shaped ValidationError for field problems, sentence otherwise. Model constants. `<tr>` in `<tbody>`. Line-item deletes only via `delete_line_item_with_renumber`. Iterate+save, never QuerySet.update for side-effect fields.
- `Task.parent_task` is dormant: no ported code may read or write it (spec ruling 1).
- TDD per task; commits end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Schema + model layer

**Files:** Create `apps/purchasing/migrations/0025_po_reconciliation_fields.py` (port fees'); modify `apps/purchasing/models.py`; create `tests/test_po_reconciliation.py` (model-level cases only this task).
**Source:** analysis §1; `git show feature/fees:apps/purchasing/models.py` and the fees migration (`git show 09a1e920`).
**Steps:** port the four PurchaseOrder fields + `PurchaseOrderQuerySet.awaiting_reconciliation()` + `is_awaiting_reconciliation`/`ordered_total`/`variance` properties + the two line fields (`final_price`, `invoice_only`) verbatim; `PurchaseOrderLineItem.clean()` gets ONLY the job-bearing task check (drop the fees top-level/parent_task branch — spec ruling 1). TDD: port the model-level tests (awaiting matrix, variance math, clean() job-bearing accept/reject; DROP subtask cases). Run the new module + `tests.test_purchasing_api` (or the existing PO test modules — grep) with `--noinput`. Commit.

### Task 2: Reconcile service + receiving exclusions

**Files:** Modify `apps/purchasing/services.py`; extend `tests/test_po_reconciliation.py`.
**Source:** analysis §2 (reconcile semantics: past-draft gate incl. cancelled, editable re-reconcile, input coercion, line_finals REPLACE with ownership all-or-nothing, appended-lines whitelist mirror with in-place update / create / delete-unsent via `delete_line_item_with_renumber`, full_clean on every write, one transaction); receiving exclusions (`_update_po_status`, `receive_all`, direct-receive reject, `cancel_line_item` reject); `_default_markup_percent` returning `(Decimal|None, found)`; plus spec ruling 4: the ordinary line-item create path must refuse caller-supplied `invoice_only` at the service level (find where PO line creation lands — the mixin/service — and reject the key with a field-shaped error; test it).
**Steps:** TDD the full service matrix from fees' test file (analysis §6 first bullet lists every case; drop subtask ones). Run the module foreground. Commit.

### Task 3: API — reconcile endpoint, serializers, prompts

**Files:** Modify `apps/api/purchasing/views.py`, `apps/api/purchasing/serializers.py`; add `PurchaseOrderService.compute_rate_prompts`; create `tests/test_api_po_reconciliation.py`.
**Source:** analysis §2 (compute_rate_prompts: qualifying rule = final_price set AND task set AND not `InvoiceClaimService.is_invoiced(SOURCE_TASK, pk)`; suggested = `(final_price × (1+markup/100)).quantize(0.01)`; markup_applied flag) and §3 (endpoint, serializer fields read-only, list filter, task-strip removal at views.py:137-138).
**Re-shape (spec ruling 2):** each prompt's `current_rate` = `task.effective_rate()`; ALSO include `has_active_modifiers` (bool) so the dialog can note "modifiers apply on top". Everything else verbatim.
**Steps:** TDD from fees' API test file (analysis §6 second bullet; drop subtask cases; add an effective_rate-vs-raw-rate case and a has_active_modifiers case). Permission matrix tests included. Run module foreground. Commit.

### Task 4: Job financials + validate_data + converter check

**Files:** Modify `apps/jobs/financials.py` (+ serializer exposure — check how `compute_job_financials` keys surface), `apps/core/management/commands/validate_data.py` (or wherever the checks live — grep); extend `tests/test_job_financials.py`, `tests/test_validate_data.py`.
**Source:** analysis §2 (`_linked_po_variances` — task-linked OR material-linked discovery, multi_job, quantization, no proration) and §2's validate_data list (port the invoice_only-receiving ERROR and stale-final WARN; DROP the subtask ERROR — superseded by `check_no_parent_task`).
**Steps:** TDD both. Then run `tests.test_neals_builders` (converter emits POs; fees verified no changes needed — re-verify, expect green with zero converter edits). Commit.

### Task 5: Frontend — task link authoring

**Files:** Create `frontend/src/components/TaskLinkPicker.svelte`; modify `frontend/src/components/purchaseorders/LineItemForm.svelte`; create/extend Vitest (`frontend/tests/components/TaskLinkPicker.test.js`, LineItemForm tests).
**Source:** analysis §4. **Re-shape:** drop the `parent_task == null` client filter — all of a job's tasks are eligible.
**Steps:** port picker + the optional "Task Link" row (independent of material jobId; sends `task` on create; merge around the current file's `is_fallback` AC-filter line). Vitest: port fees' cases minus the filter test. Full Vitest run. Commit.

### Task 6: Frontend — reconcile UI + rate prompt + list surfaces

**Files:** Create `frontend/src/components/purchaseorders/ReconciliationSection.svelte`, `RatePromptDialog.svelte`; modify `PurchaseOrderDetailPage.svelte`, `PurchaseOrderList.svelte`, `PurchaseOrderListPage.svelte`, `ReceiveItemsForm.svelte`; Vitest for all six.
**Source:** analysis §4 — port faithfully including: mount-seed + send-the-complete-picture-every-save (REPLACE mirror), persisted-removal notice with one-click re-add (no confirm — reversible pre-save), the `{#key po_id:reconciled_date}` remount (KEEP the load-bearing comment), pre-reload `reconciled` read for first-save toast wording, `triageError` routing, awaiting badge + list checkbox filter, invoice_only exclusion in ReceiveItemsForm.
**Re-shape (spec ruling 2):** RatePromptDialog shows `current_rate` (now effective) and, when `has_active_modifiers`, the note "modifiers apply on top of the accepted rate"; keep the no-markup note. Accept = GET task → `PATCH /api/jobs/{job}/tasks/{id}/ {rate: suggested_rate}`; per-row resolve with retry; Decline local-only. Gate UI on `canManageFinancials` as fees did.
**Steps:** TDD (port fees' Vitest set incl. remount-key and removal-notice cases). Full Vitest + `cd frontend && npm run build`. Commit.

### Task 7: E2E — the whole journey, rebuilt

**Files:** Create `e2e/specs/purchasing/po-reconciliation.spec.js` (new dir).
**Source:** analysis §6 (the fees flow outline) — REBUILD against current conventions: current personas/seed helpers (read an existing spec dir for the harness), sell-side setup via current authoring (flat-fee ServiceItem pick or Add Task with a typed rate), and the final assertion in agreement-skeleton terms: after Accept, seed/restore a backed invoice line for that task via the current invoice surface and assert its price reflects the new rate (actuals re-derivation) — NOT "wizard reads rate". Include: awaiting badge + filter, reconcile save (bill total, per-line final, invoice-only append, persisted-removal notice), prompt Accept on one line + Decline on another, success-overlay dismissal handling (see e2e/specs/task-view-bundling for the dismiss pattern).
**Steps:** run `cd e2e && npx playwright test specs/purchasing` to green; also run `specs/invoice-skeleton` once (regression on the invoice assertion surface). Commit.

### Task 8: Docs

**Files:** `docs/designs/materials-inventory-and-purchasing.md` (§10a port + §9 supersessions + line-table `task` row), `docs/designs/data-constraints.md`, `docs/designs/invoicing-and-expenses.md`, `docs/designs/estimates-and-prices.md`, `docs/designs/quickbooks-integration.md`, new `docs/ui-flows/Purchasing.md`, `docs/designs/LATER.md`.
**Source:** spec §4 list; fees' docs commit (`git show f9218be8`) as raw material — every claim verified against THIS branch's shipped code at HEAD, not fees'.
**Steps:** write, verify claims file:line, LATER updates (resolve items 1-2, fix-noted item 3, carry linked-PO-variance display). Commit.

---

## Execution notes (controller)

- Order 1→8 strictly (each backend task builds on the prior; frontend needs 3's serializer shape; e2e needs 6).
- One agent runs Django/Playwright tests at a time; full Django suite once at final review, not per task.
- Final whole-branch review at the end per SDD, most capable model, with the ledger's deferred minors.
