# Invoice changes — implementation plan

> **For agentic workers:** execute task-by-task with TDD. Source of truth for behavior is
> `2026-06-28-invoice-changes-spec.md`. This plan turns that into bite-sized tasks.

**Goal:** Add the two invoice seed buttons (Apply everything / Copy from estimate), flag
lines missing an accounting category, and gate Send until every line has one — keeping
per-line editing and the existing adjustment mechanism.

**Branch:** `feature/est-consolidation`. **Do not** branch, worktree, push, or merge.

## Global constraints (every task)

- **NEVER write the dev DB** — no `migrate`, no `manage.py shell`/`-c` ORM writes, no
  `loaddata`, no runserver mutations, no direct SQL writes. Tests use the test DB (auto).
  Read-only `SELECT` only if needed.
- **TDD**: write the failing test first, watch it fail for the right reason, implement, green.
- **Tests**: backend `python manage.py test tests.<module>` — judge pass/fail by the
  `OK` / `FAILED (...)` line + `Ran N tests`, never a piped exit code. Frontend
  `cd frontend && npm run test:run -- <file>`. One test process at a time.
- Use model constants (`Invoice.STATUS_DRAFT`, etc.). Line-item deletes via
  `LineItemService.delete_line_item_with_renumber`. Adjustment lines carry
  `adjustment_service`. Multi-model writes in `transaction.atomic()`.
- Subagents: make edits + run tests, **do not commit** (the controller commits).

## Current state (confirmed)

- `InvoiceViewSet` (`apps/api/invoicing/views.py`) keeps full `LineItemMixin`; has
  `source_pool`, `line_items_from_atoms`, `adjustment_lines`, `agreement_adjustments`,
  `send`.
- `InvoiceWizardService.get_source_pool(invoice)` (`apps/invoicing/services.py:430`) walks
  job tasks→atoms + loose materials + expenses, annotating each atom `state` =
  `available` | `claimed_by_current` | `claimed_by_other` | `not_billable`.
- `BaseWizardService.add_atoms_to_new_line_item(container, atoms)` (`apps/core/wizard.py:216`)
  creates one line from a list of `{type,id}` atoms (single atom → one line).
- `compose_agreement(job)` (`apps/estimates/agreement.py`) → `{lines: [...], grand_total}`;
  each line dict has `description`, `qty`, `price`, `accounting_category`, `is_adjustment`,
  `adjustment_service_id`, `percent`, `target_category_ids`, `origin`, `units`.
- `InvoiceLineItem.accounting_category` is nullable; editable via `LineItemModal` (`<select>`
  with `-- None --`). `LineItemTable` shows `—` for a missing category (not yet flagged).
- `InvoiceEmailService.send_invoice(invoice, *, to, ...)` (`apps/invoicing/services.py:247`)
  is the send entry; the `send` action maps `DjangoValidationError` → 400.

---

## Task 1 — Backend: "Apply everything" (all available atoms, one line each)

**Files:** `apps/invoicing/services.py` (new `InvoiceWizardService.seed_all_atoms`),
`apps/api/invoicing/views.py` (new action), `tests/test_invoice_apply_everything.py`.

**Behavior:**
- `seed_all_atoms(invoice)`: require `invoice.status == Invoice.STATUS_DRAFT` and the invoice
  has **no** line items (else `ValidationError`). Enumerate every atom in
  `get_source_pool(invoice)` whose `state == 'available'` (tasks, nested materials, loose
  materials, expenses), and create **one line per atom** via
  `add_atoms_to_new_line_item(invoice, [{'type': a['type'], 'id': a['id']}])`. Already-claimed
  and not-billable atoms are naturally skipped (only `available`). Wrap in
  `transaction.atomic()`. Return the count (or the invoice).
- Action `POST /api/invoices/{id}/apply-everything/`, `url_path='apply-everything'`,
  permission `CanManageFinancials`. On `ValidationError` → 400 `{'detail': ...}`. Success →
  200 with `{'created': N}` (or the serialized invoice).

**Tests (`tests/test_invoice_apply_everything.py`):**
- A job with a completed task + consumed material → one line each; both atoms now
  `claimed_by_current`.
- Re-running on an invoice that already has lines → 400.
- A second draft invoice on a job whose atoms are already claimed by a prior invoice →
  seeds only the unclaimed/remaining atoms (claimed ones skipped, no error).
- Not-billable atoms (incomplete task / unconsumed material) are skipped.

---

## Task 2 — Backend: "Copy from estimate" (agreement-of-record)

**Files:** `apps/invoicing/services.py` (new `InvoiceService.copy_from_estimate`),
`apps/api/invoicing/views.py` (new action + a `job_has_other_invoices` serializer flag),
`apps/api/invoicing/serializers.py`, `tests/test_invoice_copy_from_estimate.py`.

**Behavior:**
- `copy_from_estimate(invoice)`: require draft + empty invoice; require **no other
  non-cancelled invoice exists for the job** (else `ValidationError` — copying the full
  agreement would double-bill). Call `compose_agreement(invoice.job)`. For each agreement
  line create an `InvoiceLineItem` (via `LineItemService.save_line_item`) copying
  `description`, `qty`, `price`, `units`, `accounting_category`; for adjustment lines
  (`is_adjustment`) set `adjustment_service_id` and `adjustment_target_categories` from the
  agreement dict so dedup + recompute work. Preserve order with `line_number`. Atomic.
- Action `POST /api/invoices/{id}/copy-from-estimate/`, `CanManageFinancials`,
  ValidationError → 400.
- Add `job_has_other_invoices` (bool) to `InvoiceSerializer` (SerializerMethodField:
  any non-cancelled invoice for the job other than this one) so the UI can disable the
  button.

**Tests (`tests/test_invoice_copy_from_estimate.py`):**
- Accepted estimate with base + adjustment line → invoice gets matching lines; the
  adjustment line carries `adjustment_service`; `agreement-adjustments` reports it
  `already_added` (no double-copy).
- Empty draft required (400 if it already has lines).
- Disabled when a prior invoice exists (400).
- `job_has_other_invoices` true when a sibling invoice exists, false otherwise.

---

## Task 3 — Backend: Send-gate on missing accounting category

**Files:** `apps/invoicing/services.py` (`send_invoice` precheck), `tests/test_invoice_send_category_gate.py`.

**Behavior:**
- At the top of `InvoiceEmailService.send_invoice`, before any QBO/PDF/email work, raise
  `django.core.exceptions.ValidationError` if any of the invoice's line items has
  `accounting_category_id is None`. Message e.g. *"Every line item needs an accounting
  category before sending (line(s) N)."* The `send` action already maps this to 400.

**Tests:**
- An invoice with a category-less line → `send_invoice` raises `ValidationError` (assert at
  the service level; no real email/QBO). Use a line with `accounting_category=None`.
- An invoice whose lines all have categories → passes the gate (mock/avoid the actual
  external send; assert the gate does not raise — structure so the test stops before
  external calls, or asserts the precheck independently).

---

## Task 4 — Frontend: seed buttons + Send-gate on InvoiceDetailPage

**Files:** `frontend/src/routes/invoices/InvoiceDetailPage.svelte`,
`frontend/tests/components/invoices/InvoiceDetailPage*.test.js` (extend/add).

**Behavior:**
- On a **draft** invoice with **no line items**, show two buttons in the Line Items area:
  - **Apply everything** → `POST /api/invoices/{id}/apply-everything/` then `loadInvoice()`.
  - **Copy from estimate** → `POST /api/invoices/{id}/copy-from-estimate/` then
    `loadInvoice()`; **disabled** when `invoice.job_has_other_invoices`.
  - Both **hidden/disabled once the invoice has any line** (they are starting points).
- **Send-gate (frontend):** when any line item has no `accounting_category`, replace the
  Send link with a disabled control + a short note ("Assign an accounting category to every
  line before sending"). Use a `$derived` `allLinesHaveCategory`.
- Surface API errors via the existing error overlay (`api.js`).

**Tests:** buttons render only on an empty draft; Copy disabled when
`job_has_other_invoices`; buttons call the right endpoints; Send is disabled when a line
lacks a category and enabled when all have one.

---

## Task 5 — Frontend: flag line items missing an accounting category

**Files:** `frontend/src/components/LineItemTable.svelte`,
`frontend/tests/LineItemTable.test.js`.

**Behavior:**
- When the table is editable (`canEdit`) and a line has no `accounting_category`, visibly
  flag that cell (e.g. a `needs-category` class + a "needs category" marker) instead of a
  bare `—`, so the user knows what's blocking Send. Adjustment lines are exempt only if
  they legitimately have a category (they carry `svc.accounting_category`); treat them the
  same — a null category is flagged.

**Tests:** a line with `accounting_category = null` renders the flag when `canEdit`; a line
with a category does not; no flag when `!canEdit` (read-only/sent invoice).

---

## Execution order

Backend T1 → T2 → T3, then frontend T4 → T5 (sequential; shared test DB, T4 depends on the
T1/T2 endpoints + the T2 serializer flag, T4 send-gate pairs with T3). Controller reviews +
commits after each.
