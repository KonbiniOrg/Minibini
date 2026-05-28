# Invoicing and Expenses

The customer-facing billing side of Minibini and the employee/company expense ledger that feeds job costing and reimbursements.

## What this doc owns

- The `Invoice`, `InvoiceLineItem`, and `InvoiceLineItemSource` models.
- The invoice wizard (re-aggregating real-side atoms — `Task`, `Material` — into invoice line items).
- The Minibini-side shape of "send an invoice to QBO": which states transition, which surfaces show what.
- The `Expense` and `Reimbursement` models, services, and viewsets.
- Per-expense permission scoping in the API.

## What this doc does not own

- Service-layer conventions, `LineItemMixin`, `StatusTransitionMixin`, two-phase delete, the line-item delete-and-renumber rule. See `docs/designs/architecture-and-conventions.md` and `CLAUDE.md`.
- `Job`, `Task`, `Blep`, `WorkTemplate` shape. See `docs/designs/jobs-tasks-and-worksheets.md`.
- The estimate wizard (`EstimateLineItemSource`, plan-side atoms, in-sync rule). The invoice wizard mirrors it; see `docs/designs/estimates-and-prices.md` for the shared structure and the `LineItemSource` claim model.
- `Material` shape, `MaterialService.consume`, `is_expense_bound`, the "Materials (no task)" bucket. See `docs/designs/materials-inventory-and-purchasing.md`.
- `Bill` (vendor-side AP, lives next to `PurchaseOrder`). See `docs/designs/materials-inventory-and-purchasing.md`.
- OAuth, `QBOSyncLog`, payment polling, sync-failure plumbing. See `docs/designs/quickbooks-integration.md` (forthcoming). This doc references the push points but does not describe their internals.

---

## Invoice

`apps/invoicing/models.py` — `Invoice`.

One per draft, one per real billing event. Linked to `Job` (FK, `CASCADE`). The job is the only structural parent; an invoice does not link to an estimate or to the worksheet that produced the job.

### Fields

| Field | Type | Notes |
|---|---|---|
| `invoice_id` | AutoField PK | |
| `job` | FK Job (CASCADE) | |
| `invoice_number` | CharField(50), unique | Auto-generated on first save via `NumberGenerationService.generate_next_number('invoice')` if blank. See "Document numbering" in CLAUDE.md. |
| `status` | CharField — see machine below | Default `draft`. |
| `created_date` | DateTimeField | `default=timezone.now`. |
| `sent_date` | DateTimeField, nullable | Currently unused by code paths; reserved for the open-transition flow. |
| `closed_date` | DateTimeField, nullable | Stamped by `Invoice.save()` the first time the invoice transitions to `paid` (any path), if not already set. |
| `qbo_id` | CharField(50), nullable | Set when `QBOInvoiceSyncService.push_invoice` succeeds. |
| `qbo_payment_status` | CharField(50), default `''` | One of `Paid` / `Partial` / `Unpaid` — written by `QBOPaymentPollingService.poll_all`. |
| `qbo_amount_paid` | Decimal(10,2), nullable | Updated by the polling service. |

`@history(exclude=['invoice_id'])` decorates the model — status changes auto-write `HistoryEntry` rows.

### Status machine

| Value | Meaning |
|---|---|
| `draft` | Editable. Wizard works against this state. Default on create. |
| `open` | Sent to customer; awaiting payment. Defined in choices but the codebase has no transition path that *sets* it yet (the `draft → open` send-to-customer gap — see "Unfinished work"). Payment polling treats `open` (and `partly-paid`) as its input states, so once that gap is closed, polling promotes `open → paid` / `partly-paid` automatically. |
| `cancelled` | Terminal. Frees its claimed atoms (the wizard treats cancelled-invoice claims as available). |
| `superseded` | Defined in choices, no current transition. |
| `partly-paid` | Set by `QBOPaymentPollingService.poll_all` when QBO reports a partial payment (some balance paid, some outstanding). |
| `paid` | Set by the polling service when QBO reports the invoice fully paid (balance zero); also reachable by any other path that writes `STATUS_PAID`. When written, `Invoice.save()` stamps `closed_date` (if unset) and calls `_maybe_complete_job()`, which delegates to `JobService.maybe_complete_if_resolved(job)` — the single completion gate (see "All-shipped completion gate" below). The gate walks the job through `approved → in_progress → work_complete → completed` (each step via `JobService.update_job`) only if **both** all of the job's invoices are resolved (paid or cancelled) **and** every Deliverable on the job is fully picked up. Before the walk it releases any loose pending Materials on the job — `JobService.release_loose_materials` restocks them and a `HistoryEntry` logs it — so the `work_complete` materials gate cannot strand the job on this unattended path. A `cancelled` job is never auto-completed (the state machine forbids `cancelled → completed`). |
| `defaulted` | Defined in choices, no current transition. |

`InvoiceViewSet.status_actions` registers only `cancel` (writes `STATUS_CANCELLED` directly via a queryset update). Everything else is set by direct `save()` or by code that has not yet been written.

`Invoice.clean()` blocks transitioning out of `draft` if there are zero `InvoiceLineItem` rows.

### "One draft per job" — design vs. reality

Enforced by a partial unique constraint on `Invoice` (`unique_draft_invoice_per_job`, partial on `status='draft'`). `InvoiceWizardService.open_for_job` also enforces this at the application level by returning the existing draft if one is found.

### Document numbering

`Invoice.save()` calls `NumberGenerationService.generate_next_number('invoice')` if `invoice_number` is blank. Counter and pattern keys live in `Configuration` (`invoice_number_sequence`, `invoice_counter`). See "Document Numbering" in `CLAUDE.md`.

---

## InvoiceLineItem and InvoiceLineItemSource

`apps/invoicing/models.py`.

### InvoiceLineItem

Inherits `BaseLineItem` (description, qty, units, price, accounting_category, taxable_override, etc. — see `apps/core/models.py`). Has no direct `task` FK; `task` is exposed as a `@property` returning `None` purely so `BaseLineItem.clean()`'s "task XOR price_list_item" rule passes. Source linkage is via the `InvoiceLineItemSource` join table.

`db_table = 'invoice_li'`. Parent field name (for `LineItemMixin`) is `invoice`.

Deletion goes through `LineItemService.delete_line_item_with_renumber(line_item)` per the project rule — never `.delete()` directly. `InvoiceService.delete_line_item` does this.

### InvoiceLineItemSource

Polymorphic join between `InvoiceLineItem` and the atom it represents (a real-side `Task` or `Material`). "Polymorphic" only in the sense that the atom side may be one of two model types; this is not a Django generic relation.

| Field | Type | Notes |
|---|---|---|
| `source_id` | AutoField PK | |
| `invoice_line_item` | FK InvoiceLineItem (CASCADE) | `related_name='sources'`. |
| `source_type` | CharField(20), choices `'task'` / `'material'` | `SOURCE_TASK = 'task'`, `SOURCE_MATERIAL = 'material'`. |
| `source_pk` | PositiveIntegerField | The `Task.pk` or `Material.pk`. |

`db_table = 'invoice_line_item_sources'`.
`unique_together = [('source_type', 'source_pk')]` — DB-level enforcement of whole-atom claim. An atom cannot appear in two `InvoiceLineItemSource` rows.

`InvoiceLineItemSource.resolve()` returns the concrete `Task` or `Material` instance.

### Atoms on the real side

Invoice atoms differ from estimate atoms:

| Side | Atoms |
|---|---|
| Estimate (plan) | `PlanTask`, `PlanMaterial` (estimate-side atom names — see estimates doc). |
| Invoice (real) | `Task`, `Material`. |

A `Task`'s billable amount is `task.compute_amount()` — driven by the task's `RateScheme` (elapsed-bleps, entered qty, or flat fee). A `Material`'s amount is `quantity * sell_price`. See `InvoiceWizardService._atom_computed_amount`.

### Unique-constraint difference vs. the estimate side

The estimate wizard's `EstimateLineItemSource` unique constraint is **not estimate-scoped**, because plan-side atoms get duplicated on worksheet revisions and a flat global unique constraint would block the dup-and-revise pattern. See estimates doc.

The invoice side uses a flat, global unique constraint — `unique_together = [('source_type', 'source_pk')]` — and that is correct here. Real-side atoms (`Task`, `Material`) are not duplicated across invoices; an atom is a single physical thing, and the constraint enforces the project's "no double billing" rule directly at the DB.

When the wizard hits a race, `InvoiceWizardService` catches `IntegrityError` and raises `ClaimConflict(atom_ids=...)`. The viewset translates this to HTTP 409 with `{'error': 'atoms_already_claimed', 'atom_ids': [...]}`.

### Cascades

- Deleting an `InvoiceLineItem` deletes its `InvoiceLineItemSource` rows (CASCADE).
- Deleting an `Invoice` cascades to its line items, then to their sources. All claimed atoms become available again.
- Deleting a `Task` or `Material` does not affect `InvoiceLineItemSource` rows directly (no FK; the join uses `source_type`+`source_pk`). A claimed atom that gets deleted leaves a dangling source whose `resolve()` raises `DoesNotExist`. Atom deletion is gated upstream — Tasks with bleps don't get hard-deleted in normal flows.

---

## Invoice wizard

The invoice wizard re-aggregates real-side atoms into the invoice line items the customer wants to see. It is the structural parallel of the estimate wizard.

For the shared concepts — source pool, claim semantics, in-sync vs. override rule, two-pane UI shape, manual vs. bundled line items — see `docs/designs/estimates-and-prices.md`.

### Service

`InvoiceWizardService` (in `apps/invoicing/services.py`). Composes on top of `InvoiceService`; manual line item CRUD continues to go through `InvoiceService` and the `LineItemMixin`.

The line-items-from-atoms logic (`add_atoms_to_new_line_item`, `add_atoms_to_line_item`, `remove_atoms_from_line_item`, and the in-sync / bundle-summary helpers) lives in `BaseWizardService` (`apps/core/wizard.py`), shared with `EstimateWizardService`. `InvoiceWizardService` subclasses it, supplies a config block plus model hooks, and keeps the invoice-specific methods (`open_for_job`, `get_source_pool`, `BILLABLE_JOB_STATUSES`).

| Method | Responsibility |
|---|---|
| `open_for_job(job)` | Returns the job's draft `Invoice`. Creates one if none exists. Raises `ValidationError` if the job's status is not in `BILLABLE_JOB_STATUSES = {APPROVED, IN_PROGRESS, WORK_COMPLETE, COMPLETED, CANCELLED}`. `CANCELLED` is included so a job stopped early ("stop and bill") can still be invoiced for work done; the wizard pool draws from non-cancelled Tasks, whose actuals stay billable. |
| `get_source_pool(invoice)` | Returns `{'tasks': [...]}` — non-cancelled tasks for the job, plus a synthetic "Materials (no task)" group for task-less materials with `quantity > 0`. Each atom carries `type`/`id`/`description`, the `qty`/`rate`/`units`/`amount` breakdown (from the shared `BaseWizardService._atom_detail`), state (`available` / `claimed_by_current` / `claimed_by_other`), and (for claimed atoms) the claiming line item or invoice. Atom keys are normalized to match the estimate wizard so the frontend `WizardAtomRow` component is shared. |
| `add_atoms_to_new_line_item(invoice, atoms)` | Creates a new `InvoiceLineItem` plus N `InvoiceLineItemSource` rows in one transaction. Defaults table below. |
| `add_atoms_to_line_item(line_item, atoms)` | Appends source rows. Recomputes per the in-sync rule. |
| `remove_atoms_from_line_item(line_item, source_ids)` | Removes the matching source rows. Recomputes per the in-sync rule. Returns `{'line_item_deleted': bool}`. If the removal empties the source list, the line item is hard-deleted (via `LineItemService.delete_line_item_with_renumber`) regardless of override state. |

`InvoiceService.discard_draft(invoice)` is the discard path — validates draft status, then hard-deletes the invoice (cascade frees all claimed atoms).

### Defaults when bundling N atoms into a new line item

| Case | Description | Units | Qty | Price | Accounting category |
|---|---|---|---|---|---|
| Single atom | Atom's name/description | Atom's units (rate scheme unit, or PLI units, or `'none'`) | Atom's intrinsic qty (`Material.quantity` or `1` for tasks) | Atom-derived (`Material.sell_price` or `task.compute_amount()`) | Atom's effective category |
| Multi-atom — uniform task bundle | `''` (UI prompts user to name) | Rate scheme `unit_label` | Summed actual quantities | Common effective rate | Uniform-or-null |
| Multi-atom — anything else | `''` (UI prompts user to name) | `'none'` | `1` | Sum of atom amounts | Uniform-or-null (set if all atoms share one category) |

A multi-atom bundle is a "uniform task bundle" when every atom is a Task
sharing one `RateScheme` and identical `active_modifiers`. `add_atoms_to_line_item`
/ `remove_atoms_from_line_item` re-derive the same way on an in-sync line
item (re-summarize a uniform bundle, else keep qty and recompute the
per-unit price).

`taxable_override` is left null on creation (uses the category default).

### In-sync vs. override

Per the estimate wizard's rule (see estimates doc) — derived from data equality, no flag stored. The invoice version defines "in sync" as `line_item.price == round(sum_of_atom_amounts / line_item.qty, 2)` (rounding-safe). When atoms are added/removed:

- If in sync before: recompute the price from the new sum.
- If overridden before: leave the price alone.
- If the source list becomes empty: hard-delete the line item, regardless of override.

### Endpoints

| Method | URL | Purpose |
|---|---|---|
| `POST` | `/api/jobs/{id}/start-invoice-wizard/` | Returns `{invoice_id}` for the job's draft (creating one if needed). Permission: `IsAuthenticated` AND (`CanManageJobs` OR `CanManageFinancials`). |
| `GET` | `/api/invoices/{id}/source-pool/` | Returns the source pool tree. Decimals serialized as strings. |
| `POST` | `/api/invoices/{id}/line-items-from-atoms/` | Body: `{atoms: [{type, id}, ...]}`. Returns the new line item. 409 on claim conflict, 400 on validation error. |
| `POST` | `/api/invoices/{id}/line-items/{lid}/add-atoms/` | Same body shape. 409 on claim conflict. |
| `POST` | `/api/invoices/{id}/line-items/{lid}/remove-atoms/` | Body: `{source_ids: [...]}`. Returns `{line_item_deleted: bool, line_item: {...}|null}`. |

Manual-line-item endpoints come from `LineItemMixin` (see architecture doc): `POST /api/invoices/{id}/line-items/`, `PATCH /api/invoices/{id}/line-items/{lid}/`, `DELETE /api/invoices/{id}/line-items/{lid}/`, `POST /api/invoices/{id}/line-items/reorder/`.

### Permissions

All wizard endpoints require `IsAuthenticated` + `CanManageFinancials` (`InvoiceViewSet.get_permissions`). Read endpoints (`list`, `retrieve`, `GET line-items`) require only `IsAuthenticated`. The `start-invoice-wizard` action on `JobViewSet` accepts `CanManageJobs` OR `CanManageFinancials` (so a job-managing user can spawn a draft for a financials user to fill out).

### Frontend

`frontend/src/routes/invoices/InvoiceWizardPage.svelte` is the SPA route at `#/invoices/:id/wizard`. Two panes:

- Left: `frontend/src/components/invoices/WizardSourcePool.svelte` — invoice-specific source pool (renders the real-side `Task → atoms` tree, with the synthetic "Materials (no task)" group). The estimate wizard has its own source-pool component because the atom shape and grouping differ.
- Right: `frontend/src/components/wizards/WizardLineItemCard.svelte` — shared with the estimate wizard. One card per line item, in-sync/override price display, atom remove buttons.

Footer actions use `frontend/src/components/wizards/WizardActions.svelte` — also shared.

`InvoiceDetailPage.svelte` (`frontend/src/routes/invoices/InvoiceDetailPage.svelte`) is the standard non-wizard view of a finalized invoice.

### Discard

`DELETE /api/invoices/{id}/` calls `InvoiceService.discard_draft`, which validates draft status and hard-deletes. The viewset returns 200 with `{'message': 'Invoice discarded'}` per the project's all-DELETE-returns-JSON convention. There is no two-phase confirmation on this endpoint (the wizard owns the confirmation in the UI; cascade impact is implicit — all claimed atoms become free).

---

## Send to QBO

`InvoiceViewSet.send_to_qbo` (action endpoint `POST /api/invoices/{id}/send-to-qbo/`).

### Minibini-side flow

1. Caller posts `{send_to, cc?, bcc?}` (email addresses).
2. View dispatches to `QBOInvoiceSyncService.push_invoice(invoice, send_to, cc, bcc)`.
3. The service:
   - Resolves a QBO customer ref (creates one for the job's business or contact if needed).
   - Builds the QBO Invoice via `InvoiceGroupingService.group_for_qbo(invoice)` — line items grouped by `(accounting_category, taxable)`. One QBO line per group, with `Description = "Job {number}: {category} (taxable|non-taxable)"`.
   - Saves it to QBO; stores `qbo_id` immediately so retries don't duplicate.
   - Generates a job-statement PDF (`apps/invoicing/pdf.generate_job_statement_pdf`), attaches it to the QBO invoice.
   - Marks the QBO invoice as Sent; downloads the QBO-rendered PDF (which carries the Pay Now link).
   - Sends both PDFs via Minibini's email infrastructure to the recipients.
   - Logs to `QBOSyncLog` (success or failure).
4. Returns `{qbo_id, status: 'sent'}`.

### Minibini state changes

- `Invoice.qbo_id` is populated.
- `Invoice.status` is **not** changed by the push. It stays `draft`. There is no automated `draft → open` transition path in the codebase. (See "Unfinished work.")
- `HistoryEntry` rows are written by the `@history` decorator on `Invoice` — but only when fields actually change. `qbo_id` is the field that changes here, so a history entry is recorded for the push.
- `QBOSyncLog` records the push attempt with status `success` or `failed`.

### Why Minibini does not email invoices itself

The send pipeline goes Minibini → QBO → back to Minibini email. QBO is the source of truth for the customer-facing PDF (it has the Pay Now link, the calculated tax, the QBO branding). Minibini's email simply delivers what QBO produced.

For OAuth, the `QBOSyncLog` model, payment polling internals, the customer-sync flow, and connection lifecycle, see `docs/designs/quickbooks-integration.md`.

### Payment polling

`QBOPaymentPollingService.poll_all()` (in `apps/qbo/services.py`) is wrapped by the `poll_qbo_payments` management command (`apps/invoicing/management/commands/poll_qbo_payments.py`), run every 15 minutes by the docker cron service (see `architecture-and-conventions.md` §9). It walks every Invoice with a `qbo_id` that is still `open` or `partly-paid`, fetches the QBO invoice, and derives both the raw cache and the Minibini status from QBO's `Balance` / `TotalAmt`:

- **fully paid** (`Balance == 0`) → cache `qbo_payment_status='Paid'`, status → `paid`;
- **partial** (`amount_paid > 0`) → cache `'Partial'`, status → `partly-paid`;
- **unpaid** (nothing paid) → cache `'Unpaid'`, no status change.

`qbo_payment_status` and `qbo_amount_paid` are the **raw cache** of what QBO reported; the service now also **drives `Invoice.status`**. On a status change it does a full `invoice.save()` — which stamps `closed_date` and (on `paid`) fires `_maybe_complete_job`, auto-completing the job when all its invoices are resolved — and writes a `system`-attributed `action` HistoryEntry recording the payment-synced transition. No active QBO connection → the command records a `skipped` run (it does not fail).

**First-run healing.** Because the redesign is the first thing to drive status from the cache, any invoice sitting at `open` with a stale cached `qbo_payment_status='Paid'` (written by the old cache-only polling) will transition to `paid` on the first run under the new code — and, via `_maybe_complete_job`, complete its job. This is intended, but it means the first poll after deploy may move a batch of already-paid-in-QBO invoices and their jobs to terminal in one sweep.

### All-shipped completion gate

`JobService.maybe_complete_if_resolved(job)` (in `apps/jobs/services.py`) is the single auto-completion gate. It runs from two triggers:

- `Invoice._maybe_complete_job` (on entry to `paid` / `cancelled`) — delegates to it.
- `ShipmentService.mark_picked_up` — calls it at the end of every shipment pickup.

Whichever lands last — the final payment or the final shipment — completes the job, provided **both** of these hold:

- **All invoices resolved.** Every `Invoice` for the job is `paid` or `cancelled`.
- **All deliverables shipped.** `DeliverableService.all_deliverables_shipped(job)` returns True only when every `Deliverable` on the job has `qty_picked_up == qty_ordered`. Prepared-but-not-picked-up does not count; a job with zero deliverables is vacuously shipped.

Manual `JobService.update_job(status=completed)` enforces the same all-shipped precondition and raises `ValidationError('All deliverables must be shipped before completing the job.')` otherwise.

`cancelled` jobs are exempt for free — the state machine forbids `cancelled → completed`, so the gate never applies.

### Unpaid lane sources from invoices, not job status

`BoardService.get_unpaid_data` (`apps/jobs/services.py`) selects jobs that have at least one outstanding invoice (`open` or `partly_paid`) **regardless of the job's status**. A `cancelled` (or `completed`) job with an unpaid invoice surfaces in the Unpaid column with its status badged on the card. This naturally covers the stop-and-bill flow: a job that was cancelled but billed for partial work stays visible until its invoices clear.

---

## Expense

`apps/expenses/models.py` — `Expense`.

Tracks two kinds of business expenses:
- **Company-paid** — purchases made on a company account. Push to QBO immediately on save as a `Purchase`.
- **Personal** — out-of-pocket purchases that need reimbursement. Sit as `submitted` until batched into a `Reimbursement`.

### Fields

| Field | Type | Notes |
|---|---|---|
| `entered_by` | FK User (PROTECT, `entered_expenses`) | Always the logged-in user doing the data entry. |
| `purchased_by` | FK User (PROTECT, nullable, `purchased_expenses`) | Who physically made the purchase. **Required for personal expenses**; optional for company. |
| `amount` | Decimal(10,2) | |
| `purchased_on` | DateField | When the purchase happened (separate from `created_at`). |
| `description` | TextField, blank | |
| `accounting_category` | FK AccountingCategory (PROTECT) | Required. Drives the QBO line-item `AccountRef` via `AccountingCategory.qbo_expense_account_id`. |
| `payment_method` | CharField — `'company'` or `'personal'` | Two values, no other options. |
| `payment_account_id` | CharField(50), blank | References `Configuration['qbo_payment_accounts'][*].qbo_account_id`. **Required for company**, **forbidden for personal** (validated in `clean()`). |
| `reference_number` | CharField(50), blank | Check number, confirmation number, etc. Always optional. |
| `material` | FK Material (SET_NULL, nullable, `expenses`) | Optional job-costing link. `SET_NULL` because the expense outlives any particular material link. |
| `status` | CharField — see machine | Default `submitted`. |
| `qbo_id` | CharField(50), blank | Set when the QBO push succeeds (company-paid only — personal expenses' QBO IDs live on their reimbursement batch). |
| `qbo_sync_error` | TextField, blank | |
| `reimbursement` | FK Reimbursement (PROTECT, nullable, `expenses`) | Set when the expense is batched. PROTECT prevents deleting a Reimbursement that still has expenses pointing at it; the unwind path clears these refs first. |
| `created_at`, `updated_at` | Timestamps | |

`db_table = 'expenses'`. Default ordering: `['-purchased_on', '-created_at']`.

`clean()` enforces:
- Personal: `purchased_by` required, `payment_account_id` must be blank.
- Company: `payment_account_id` required.

The model is **not** decorated with `@history` — Expense changes do not write to the audit log automatically.

### Status machine

Two parallel tracks branching on `payment_method`.

**Personal:**

```
submitted ──► reimbursed     (batch created — QBO Purchase push owned by the batch)
     │
     └──────► rejected       (terminal; never pushes to QBO)
```

`ExpenseService.reject` only accepts personal expenses in `submitted` status. Rejecting also unwinds any associated Materials: clears their inventory earmark, reverses the ad-hoc PLI receipt, and deletes the Material — refusing if any material is already in the `consumed` state.

**Company-paid:**

```
(on save) ──► synced          (QBO Purchase created; qbo_id stored)
                │
                └──► sync_failed  (push failed; retry available)
```

No `rejected` for company-paid; deletion is the escape hatch (voids the QBO Purchase if it was synced).

| Status | Used by |
|---|---|
| `submitted` | personal — initial state |
| `reimbursed` | personal — batched |
| `rejected` | personal — terminal |
| `synced` | company-paid — QBO push succeeded |
| `sync_failed` | company-paid — QBO push failed; retryable |

### Per-expense permission scoping

`ExpenseViewSet.get_permissions`:

| Action | Permission |
|---|---|
| `list`, `retrieve`, `create` | `IsAuthenticated` |
| `update`, `partial_update`, `destroy`, `reject`, `retry-sync` | `IsAuthenticated` + `CanManageFinancials` |

`ExpenseViewSet.get_queryset` further scopes the list/retrieve view: callers without `can_manage_financials` see only expenses where `purchased_by=request.user`. A user can submit and view their own personal expenses; only `CanManageFinancials` can edit, delete, reject, or retry sync.

The form does not gate on permission — workers can submit company-paid expenses (full payment account dropdown is shown). The trust model is "data entry is open; correction is privileged."

The previous `can_approve_expenses` permission atom is retired. `apps/api/permissions.py` no longer defines `CanApproveExpenses` and the atom is no longer in the `User` model. There is no separate "approval" state — categorize-as-you-enter is the review.

### Material attachment

`Expense.material` is the optional job-costing link. When an expense is linked to a Material, the Material is "expense-bound" — see `docs/designs/materials-inventory-and-purchasing.md` for `Material.is_expense_bound` and `MaterialService.consume`.

`ExpenseService.submit` accepts an optional `new_material={'job_id', 'description', 'quantity', 'price', 'price_list_item_id'}` payload that creates a Material on the expense's job inline:

- Calls `MaterialService.create_on_job(job=..., task=None, ...)` — the material has no parent task. The "Materials (no task)" bucket from the wizard's source pool surfaces these.
- If a `PriceListItem` is provided and `is_inventoried`, calls `InventoryService.receive_ad_hoc_purchase(material)` to record the receipt.
- Whole flow runs in one transaction with the `Expense.save()`.

### `purchased_by` vs. `entered_by`

`entered_by` is always the logged-in user. `purchased_by` is who physically made the purchase. Same person for self-submissions; different when an admin enters expenses on behalf of someone (e.g., from a pile of receipts). There is no `submitted_by` or `approved_by`.

### Reimbursement link

`Expense.reimbursement` is null until the expense is batched. `ReimbursementService.create_batch` flips `submitted` → `reimbursed` and sets the FK. Cascade rules: a Reimbursement cannot be deleted while expenses point at it (PROTECT); the `delete` service path clears the FK first.

---

## Reimbursement

`apps/expenses/models.py` — `Reimbursement`.

Batches one or more personal `Expense` rows into a single payback transaction. Pushes to QBO as one `Purchase` with N lines.

### Fields

| Field | Type | Notes |
|---|---|---|
| `purchased_by` | FK User (PROTECT, `reimbursements`) | Who is being paid back. Lives on the batch (not derived from expenses) to prevent batches that mix two employees' expenses. Enforced in `ReimbursementService.create_batch`. |
| `paid_on` | DateField | |
| `payment_account_id` | CharField(50) | The QBO account the money came from. |
| `reference_number` | CharField(50), blank | Check number. |
| `notes` | TextField, blank | |
| `created_by` | FK User (PROTECT, `created_reimbursements`) | The financials user who built the batch. |
| `status` | CharField — see machine | Default `pending`. |
| `qbo_id` | CharField(50), blank | |
| `qbo_sync_error` | TextField, blank | |
| `created_at` | Timestamp | |

`db_table = 'reimbursements'`. Default ordering: `['-paid_on', '-created_at']`.

`@property total` sums `expense.amount` across `self.expenses`.

### Status machine

```
pending ──► synced          (QBO Purchase created with N lines)
    │
    └────► sync_failed      (retryable)
```

The batch owns the QBO sync state for personal reimbursements. The expenses in the batch are in Minibini's `reimbursed` state regardless of the batch's QBO sync outcome — the real-world event (the check being cut) is authoritative; QBO is the thing that needs to catch up.

### QBO push

See `docs/designs/quickbooks-integration.md`. One `Purchase` per batch, with one `AccountBasedExpenseLine` per expense in the batch (each line carries the expense's category as `AccountRef`). The expense-side helper `_build_expense_line(expense)` is reused by both `push_expense` and `push_reimbursement`.

---

## ExpenseService and ReimbursementService

`apps/expenses/services.py`.

### ExpenseService

| Method | Responsibility |
|---|---|
| `submit(*, entered_by, payment_method, amount, purchased_on, accounting_category, description='', payment_account_id='', reference_number='', purchased_by=None, material=None, new_material=None) -> Expense` | Atomic create. Inline-creates a Material via `MaterialService.create_on_job` if `new_material` is provided. Calls `_push_and_set_status` for company-paid (sets `synced` or `sync_failed`); leaves personal as `submitted`. |
| `update(*, expense, actor, **fields) -> Expense` | Whitelist of editable fields: amount, purchased_on, description, accounting_category, payment_method, payment_account_id, reference_number, purchased_by, material. Calls `_resync` if `expense.qbo_id` is set. |
| `delete(*, expense, actor)` | Voids the QBO Purchase if `qbo_id` and not in a batch. Hard-deletes the row. (Reimbursed expenses' QBO state is owned by the batch, so this path doesn't void QBO for them.) |
| `reject(*, expense, actor) -> Expense` | Personal + `submitted` only. Unwinds materials (earmark, ad-hoc receipt, delete) — refuses if any material is `consumed`. Sets `STATUS_REJECTED`. |
| `retry_sync(*, expense, actor) -> Expense` | `sync_failed` only. Re-pushes via `_push_and_set_status`. |

`_resync` is QBO-aware: if the expense is in a reimbursement batch, it re-pushes the whole batch (`QBOExpenseSyncService.update_reimbursement`); otherwise it re-pushes the standalone expense (`QBOExpenseSyncService.update_expense`). On failure, it flips the owner (batch or expense) to `sync_failed`.

### ReimbursementService

| Method | Responsibility |
|---|---|
| `create_batch(*, purchased_by, expense_ids, paid_on, payment_account_id, reference_number, notes, created_by) -> Reimbursement` | Validates: at least one expense; all expenses exist, all belong to `purchased_by`, all are personal, all are `submitted`. In one transaction, creates the batch and flips each expense to `reimbursed` with the batch FK. After commit, attempts the QBO push; flips batch to `synced` or `sync_failed`. The DB commit stands either way. |
| `retry_sync(*, batch, actor) -> Reimbursement` | `sync_failed` only. Re-pushes; flips to `synced` on success, leaves `sync_failed` with updated error on failure. |
| `delete(*, batch, actor)` | Voids the QBO Purchase if `qbo_id`. In a transaction: clears each expense's batch FK and sets it back to `submitted`, then deletes the batch. |

### Two-phase delete on Reimbursement

`ReimbursementViewSet.destroy` follows the project's two-phase pattern (see "Delete confirmation" in `docs/designs/architecture-and-conventions.md`):

- First `DELETE /api/reimbursements/{id}/` returns 200 with `{confirm_required: true, expense_count, qbo_void_required, message}`.
- Second `DELETE /api/reimbursements/{id}/?confirm=true` actually unwinds the batch (calls `ReimbursementService.delete`) and returns 200 with `{message: 'Reimbursement batch deleted.'}`.

`ExpenseViewSet.destroy` is a single-shot delete returning 200 with `{message: 'Expense deleted.'}`. No confirmation step.

### Outstanding-summary endpoint

`ReimbursementViewSet.outstanding_summary` (`GET /api/reimbursements/outstanding-summary/`, requires `CanManageFinancials`) returns:

```json
{
  "users": [
    {"purchased_by": 7, "username": "dana", "full_name": "Dana ...",
     "count": 3, "total": "138.25", "oldest_purchased_on": "2026-04-02"},
    ...
  ]
}
```

Sorts users by `-total`. Powers the "Outstanding reimbursements" card on the global expenses page.

### API endpoints

| Method | URL | Purpose | Permission |
|---|---|---|---|
| `GET` | `/api/expenses/` | List, filterable by `purchased_by`, `status`, `payment_method`, `accounting_category`, `from`, `to` | `IsAuthenticated` — auto-scoped to `purchased_by=user` unless `CanManageFinancials` |
| `POST` | `/api/expenses/` | Create | `IsAuthenticated` |
| `GET` | `/api/expenses/{id}/` | Retrieve | `IsAuthenticated` (queryset-scoped) |
| `PATCH` | `/api/expenses/{id}/` | Edit | `CanManageFinancials` |
| `DELETE` | `/api/expenses/{id}/` | Delete (voids QBO) | `CanManageFinancials` |
| `POST` | `/api/expenses/{id}/reject/` | Reject personal | `CanManageFinancials` |
| `POST` | `/api/expenses/{id}/retry-sync/` | Retry failed push | `CanManageFinancials` |
| `GET` | `/api/reimbursements/` | List, filter by `?purchased_by=` | `CanManageFinancials` |
| `POST` | `/api/reimbursements/` | Create batch | `CanManageFinancials` |
| `GET` | `/api/reimbursements/{id}/` | Retrieve | `CanManageFinancials` |
| `POST` | `/api/reimbursements/{id}/retry-sync/` | Retry failed batch | `CanManageFinancials` |
| `DELETE` | `/api/reimbursements/{id}/` | Two-phase unwind | `CanManageFinancials` |
| `GET` | `/api/reimbursements/outstanding-summary/` | Per-user pending totals | `CanManageFinancials` |

DELETE responses on these viewsets all return 200 with a JSON body per the project convention.

---

## UI: Invoice list, detail, wizard

| Surface | Component |
|---|---|
| Invoice detail | `frontend/src/routes/invoices/InvoiceDetailPage.svelte` |
| Invoice wizard | `frontend/src/routes/invoices/InvoiceWizardPage.svelte` (route `#/invoices/:id/wizard`) |
| Source pool | `frontend/src/components/invoices/WizardSourcePool.svelte` |
| Line item card (shared with estimates) | `frontend/src/components/wizards/WizardLineItemCard.svelte` |
| Footer actions (shared with estimates) | `frontend/src/components/wizards/WizardActions.svelte` |
| Send-to-QBO dialog | `frontend/src/components/invoices/SendToQBODialog.svelte` |

`InvoiceWizardPage` tracks `selectedAtoms` with `$state`; "Add to line item" and "Create new line item" both POST and reload. 409 from the API surfaces as an alert prompting the user to reopen the wizard for a fresh source pool.

There is currently no separate `InvoiceListPage.svelte` route in `frontend/src/routes/invoices/` — invoice listing happens via the job board's "unpaid" view (`/api/jobs/board/unpaid/`) and per-job filters. A standalone invoice list is "Unfinished work."

---

## UI: Expenses and Reimbursements

| Surface | Component |
|---|---|
| Expense form | `frontend/src/components/expenses/ExpenseForm.svelte` |
| Material picker on the form | `frontend/src/components/expenses/MaterialPicker.svelte` |
| Per-user reimbursement panel | `frontend/src/components/expenses/UserReimbursementPanel.svelte` |
| Global expense list | `frontend/src/routes/expenses/ExpenseListPage.svelte` (route `#/expenses`) |
| Per-user reimbursement page | `frontend/src/routes/reimbursements/ReimbursementDetailPage.svelte` (route `#/reimbursements/:user_id`) |

The home card surface (self-service personal expense submission) consumes the same `ExpenseForm.svelte`. A Bookkeeper sees an "Expenses" sidebar link; a Worker does not. Owners see the same `UserReimbursementPanel.svelte` embedded as an Expenses tab on the User Detail page.

Per-user reimbursement page sections:

- Outstanding reimbursable expenses (checkbox table, running total, "Reimburse selected" inline form).
- Past reimbursement batches (with QBO sync state and retry button on `sync_failed`).
- "Show rejected" toggle (read-only, off by default).

---

## Job P&L (unfinished)

The Job P&L view consumes invoices, bills, expenses, and bleps to compute revenue and cost on a job. Invoices and Expenses produce the data; the consumer side is not yet built. See "Unfinished work."

---

## Unfinished work

- **Job P&L view** — consumes Invoices + Bills + Expenses + Bleps. Was Phase 5 of the QBO integration roadmap. Data is being captured today; the view is not built.
- **Auto `draft → open` transition when an invoice is sent to the customer.** The user-facing action is "send to customer" — today that's wired through QBO (`QBOInvoiceSyncService.push_invoice`), but the action's name should reflect the customer-side intent, not the integration channel. The codebase has the `STATUS_OPEN` choice and a `sent_date` field, but nothing currently flips the status. The invoice stays `draft` even after the customer has received it. Needs design (does `cancel` on a sent invoice still hard-delete via `discard_draft`? probably not).
- **`superseded` and `defaulted` statuses.** Both are defined in the status machine's choices but have no transition path that sets them. (Payment polling now drives `partly-paid` / `paid` — see "Payment polling" above — so those two are no longer dead.)
- **One-click invoice generation.** Auto-create a draft invoice from all uninvoiced atoms when a Job hits `work_complete`, without going through the wizard. Will share the data model with the wizard. Out of scope per the 2026-04-09 design.
- **Standalone invoice list page in the SPA.** No `#/invoices/` route today — discovery is via the job board.
- **Direct invoice editor** (non-wizard tweaks to existing invoices). The override mechanism on bundled line items is already designed to coexist with this.
- **Flat-rate task billing without bleps or materials.** Current workaround: model the charge as a Material row.
- **Direct invoice email from Minibini.** Today the customer-facing send always goes through QBO. If Minibini ever emails invoices directly, follow the PO email pattern (status change captured by `@history`; manual `action` HistoryEntry for the send event with the recipient list). See `apps/purchasing/services.py` `PurchaseOrderEmailService.send_po`.
- **Receipt photo upload** on `Expense` (`FileField` + storage backend). Listed in the 2026-04-11 design as future.
- **Employee-as-Vendor QBO sync** for personal-payment expenses (currently `EntityRef` is unset on the `Purchase`). 1099 tracking depends on this.
- **Reassign job/task on a locked expense.** Today an expense's job/task link is locked once the expense is reimbursed. A narrow reassignment action that only changes the `material` link (and re-pushes the QBO line) is needed.
- **Recurring expense templates / OCR receipt capture / bulk CSV import** of credit-card statements.
- **Multi-account default hinting** (remembered default per user/shop for the payment-account dropdown).
- **Spending dashboards** — vendor totals, category totals over time.
- **QBO → Minibini reverse sync** for Purchases entered directly in QBO. CDC-based polling is the recommended path; research in the appendix below.
- **History coverage on `Expense`.** The `Expense` model is not decorated with `@history`. Edits do not write `HistoryEntry` rows. Reimbursement state changes also live outside the audit log.
- **`accounting_category` required on `InvoiceLineItem`** — part of the project-wide line-item AC-NOT-NULL migration tracked in `architecture-and-conventions.md`.

---

## Appendix: Research — pulling Minibini-external expenses out of QBO

**Not in scope for current work.** Captured here so future work doesn't have to rediscover it. The use case: bookkeeper enters an expense directly in QBO during periodic reconciliation (skipping Minibini); we want Minibini to notice and surface it.

### QBO mechanisms for reading Purchase data

**1. Direct query by `MetaData.LastUpdatedTime`** — the simplest path:

```sql
SELECT * FROM Purchase
WHERE MetaData.LastUpdatedTime > '2026-04-01T00:00:00-08:00'
ORDER BY MetaData.LastUpdatedTime
```

Works for every entity with metadata. Supports `STARTPOSITION` / `MAXRESULTS` pagination. Caller tracks the last-sync timestamp locally.

**2. Change Data Capture (CDC)** — purpose-built for this:

```
GET /v3/company/<realmId>/cdc?entities=Purchase,Bill&changedSince=<ISO8601>
```

- Multi-entity in one call (Purchase + Bill + Vendor + Customer → single request).
- **30-day max look-back.** `changedSince` must be within the last 30 days; longer gaps require a full resync via direct query.
- **Max 1000 objects per response.** Pagination needed for high-volume shops.
- **Full payloads**, not just diffs. Easy to reconcile locally.
- **Includes deletes** with tombstone markers so Minibini can mirror them.

**3. Webhooks** — real-time push. Supports Create/Update/Delete/Merge/Void events on "most entities" (Account, Bill, Customer, Invoice, Item, Payment, Vendor explicitly listed). **Whether `Purchase` specifically gets webhook events is not clearly documented** — Intuit's own docs are JS-rendered and resist scraping. Would need sandbox verification or a forum question. Downsides regardless: requires a publicly-accessible HTTPS endpoint (Minibini dev environment isn't), must respond within 3 seconds with 200, adds a webhook-verifier-token auth surface.

**Recommendation:** CDC-based polling, not webhooks. Hourly or daily poll via a management command following the existing `QBOPaymentPollingService` pattern. Matches bookkeeper work cadence, avoids webhook infrastructure.

### Inherent lossiness

The bigger problem is that QBO doesn't carry Minibini-specific metadata. A Purchase entered directly in QBO has:

- ✅ Amount, date, category (reverse-lookup via account ID)
- ✅ Payment account (reverse-lookup via the `qbo_payment_accounts` config)
- ✅ Description, reference number, QBO vendor ref
- ❌ **No `purchased_by` user** — QBO has no concept of "which Minibini user made this purchase"
- ❌ **No Material/Task link** — unless Minibini starts pushing job linkage via QBO Class or Customer fields (explicitly deferred)
- ❌ **No distinction between company-paid and reimbursement batch** — both look like the same `Purchase` entity in QBO

### Distinguishing Minibini-originated vs. external

Easy because of the `PrivateNote` tag this design already plans to write on every push: `"Minibini expense #N — ..."` or `"Reimbursement to <username> — Minibini batch #N"`. On pull, any `Purchase` whose `PrivateNote` doesn't start with `"Minibini"` is external. Plus Minibini's own `qbo_id` → Expense/Reimbursement lookup gives a direct reverse index for known ones.

### Sketch of the future import flow

1. New management command polls CDC for `Purchase` entities since last sync, persists the new last-sync timestamp in `Configuration`.
2. For each returned `Purchase`:
   - If `qbo_id` matches a local record → update the local record in place (reverse re-sync).
   - Else if `PrivateNote` starts with `"Minibini"` → log an anomaly (we pushed it but lost the local link — probably a DB restore or migration bug).
   - Else → create a local `Expense` stub: `status=synced`, `qbo_id` populated, `entered_by` set to a synthetic system user, `purchased_by=null`, `material=null`. Amount/date/description/reference/payment account all come from the QBO payload. Accounting category via reverse lookup from the line's `AccountRef`.
3. Surface imported stubs in the `/#/expenses` global list with a visual "Imported from QBO" badge and a prompt to link each one to a Material for job costing.

### Limits to plan around

The job-costing path is inherently lossy for QBO-first entries. The only real fix is a shop policy: bookkeepers enter job-bound expenses through Minibini, non-job overhead through QBO directly. Minibini can enforce this by refusing to attribute imported stubs to jobs automatically — the admin has to do the linking by hand in the global list.

### Sources consulted

- [QBO Change Data Capture](https://developer.intuit.com/app/developer/qbo/docs/learn/explore-the-quickbooks-online-api/change-data-capture)
- [QBO Webhooks](https://developer.intuit.com/app/developer/qbo/docs/develop/webhooks)
- [QBO Query operations](https://developer.intuit.com/app/developer/qbo/docs/learn/explore-the-quickbooks-online-api/data-queries)
- [Intuit blog — Stay in sync with CDC](https://blogs.intuit.com/2023/08/24/building-smarter-with-intuit-stay-in-sync-with-cdc/)
- [Intuit blog — Webhook best practices](https://blogs.intuit.com/2023/04/18/best-practices-for-using-webhooks-with-quickbooks-online/)
