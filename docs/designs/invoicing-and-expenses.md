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
| `sent_date` | DateTimeField, nullable | Stamped by `Invoice.save()` the first time the invoice transitions `draft → open` (the send-to-customer step; mirrors `Estimate`), if not already set. A row created directly as `open` is not stamped. The serializer's derived `due_date` (`sent_date + 30 days`) and `is_late` read off this. |
| `closed_date` | DateTimeField, nullable | Stamped by `Invoice.save()` the first time the invoice transitions to `paid` (any path), if not already set. |
| `qbo_id` | CharField(50), nullable | Set when `QBOInvoiceSyncService.push_invoice` succeeds. |
| `qbo_payment_status` | CharField(50), default `''` | One of `Paid` / `Partial` / `Unpaid` — written by `QBOPaymentPollingService.poll_all`. |
| `qbo_amount_paid` | Decimal(10,2), nullable | Updated by the polling service. |

`@history(exclude=['invoice_id'])` decorates the model — status changes auto-write `HistoryEntry` rows.

### Status machine

| Value | Meaning |
|---|---|
| `draft` | Editable. Wizard works against this state. Default on create. |
| `open` | Sent to customer; awaiting payment. Set by the send-to-customer flow (`InvoiceEmailService.send_invoice` flips `draft → open` on send success, stamping `sent_date`). Payment polling treats `open` (and `partly-paid`) as its input states and promotes `open → paid` / `partly-paid` automatically. |
| `cancelled` | Terminal. Frees its claimed atoms (the wizard treats cancelled-invoice claims as available). Set via `InvoiceService.cancel` (API: `InvoiceViewSet.cancel`), which loads the invoice and calls `.save()` so the completion gate fires — a cancelled invoice counts as resolved, so cancelling the last unresolved invoice on a `work_complete`, all-shipped job auto-completes it. |
| `superseded` | Defined in choices, no current transition. |
| `partly-paid` | Set by `QBOPaymentPollingService.poll_all` when QBO reports a partial payment (some balance paid, some outstanding). |
| `paid` | Set by the polling service when QBO reports the invoice fully paid (balance zero); also reachable by any other path that writes `STATUS_PAID`. When written, `Invoice.save()` stamps `closed_date` (if unset) and calls `_maybe_complete_job()` (also fired on entry to `cancelled`), which delegates to `JobService.maybe_complete_if_resolved(job)` — the single completion gate (see "All-shipped completion gate" below). The gate moves the job `work_complete → completed` (via `JobService.update_job`) only if the job is already in `work_complete` **and** all of the job's invoices are resolved (paid or cancelled) **and** every Deliverable on the job is fully picked up. A job in any earlier state (including a deposit-invoiced `in_progress` job) is left untouched. Before the walk it releases any loose pending Materials on the job — `JobService.release_loose_materials` restocks them and a `HistoryEntry` logs it — so the `work_complete` materials gate cannot strand the job on this unattended path. A `cancelled` job is never auto-completed (the state machine forbids `cancelled → completed`). |
| `defaulted` | Defined in choices, no current transition. |

`InvoiceViewSet.status_actions` registers only `cancel`, which delegates to `InvoiceService.cancel` (loads the invoice and calls `.save()` so the completion gate runs — not a bypassing queryset update). Everything else is set by direct `save()` or by code that has not yet been written.

`Invoice.clean()` blocks transitioning out of `draft` if there are zero `InvoiceLineItem` rows.

### "One draft per job" — design vs. reality

Guaranteed by the application-level get-or-create in `InvoiceWizardService.open_for_job`, which returns the existing draft when one is found. A `unique_draft_invoice_per_job` partial unique constraint (on `status='draft'`) is declared on `Invoice`, but it is **not** created on MySQL — which doesn't support conditional unique constraints (Django emits `models.W036`) — so the invariant rests on the service, not the DB.

`InvoiceViewSet.perform_create` routes every direct `POST /api/invoices/` through `InvoiceWizardService.open_for_job` — the same service entry point used by the atom-pull wizard. This means direct invoice creation is also subject to the get-or-create semantics (returns the existing draft if one exists) and the billable-job-status guard (returns HTTP 400 if the job's status is not in `BILLABLE_JOB_STATUSES`). There is no separate creation path that bypasses the service.

### Document numbering

`Invoice.save()` calls `NumberGenerationService.generate_next_number('invoice')` if `invoice_number` is blank. Counter and pattern keys live in `Configuration` (`invoice_number_sequence`, `invoice_counter`). See "Document Numbering" in `CLAUDE.md`.

---

## InvoiceClaimService — centralized invoiced-atom predicate

`InvoiceClaimService` (`apps/invoicing/claims.py`) is the **single source of
truth** for "is this atom on a live (non-cancelled) invoice." All service-layer
code that needs to answer that question uses this class — no inline filter
duplication.

```python
InvoiceClaimService.is_invoiced(source_type, source_pk) → bool
    # True if the atom is referenced by any non-cancelled InvoiceLineItemSource.

InvoiceClaimService.claims_for_job(job) → dict
    # {(source_type, source_pk): {'invoice_id': N, 'invoice_number': '…'}, …}
    # Used by JobSerializer to populate the per-atom `invoice` field
    # in one query per job (no N+1).

InvoiceClaimService.claims_for_atoms(source_type, pks) → dict
    # Same shape, scoped to a specific list of PKs of one type.
```

`_live_sources()` excludes sources whose invoice is `cancelled` — a
cancelled invoice frees its claimed atoms back to the pool.

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

### Per-atom `invoice` field (API) and "Invoiced" indicator (UI)

**API:** `TaskSerializer`, `MaterialSerializer`, and `ExpenseSerializer` all
expose a top-level `invoice` field:

```json
"invoice": {"id": 42, "number": "INV-2026-0003"}
// or null when the atom is unclaimed / claimed only by a cancelled invoice
```

The field is populated without N+1:

- **Tasks and Materials** (nested under the job): `JobSerializer._invoice_claims(job)`
  calls `InvoiceClaimService.claims_for_job(job)` once and passes the resulting
  dict as `invoice_claims` context to `TaskSerializer` and `MaterialSerializer`.
  In list contexts (where `view.action == 'list'`), the claims map is skipped
  and `invoice` returns `null` to avoid the per-job overhead.
- **Task-list page atoms** (the `tasklist` view re-fetches per-task children):
  the flat `TaskViewSet.materials` and `subtasks` GET actions each build
  `InvoiceClaimService.claims_for_job(task.job)` and pass it as `invoice_claims`
  context to the tasks-app `MaterialSerializer` / `TaskSerializer`, so materials
  and subtasks fetched there also carry `invoice`. (The tasks-app
  `MaterialSerializer` gained the `invoice` field via `InvoiceRefMixin` too.)
- **Expenses** (via `ExpenseViewSet`): `ExpenseViewSet._claims_context_for`
  calls `InvoiceClaimService.claims_for_atoms('expense', pks)` once per list/
  retrieve response and passes the dict as `invoice_claims` context.

**UI:**
- `JobDetail.svelte` renders an `invoicedLink` snippet next to each task row,
  material row, and loose-expense row in the job overview. When a task's,
  material's, or expense's `invoice` field is non-null, a small **"Invoiced ·
  INV-xxxx"** badge appears, linking to that invoice's detail page. The badge is
  absent when the atom is unclaimed.
- `TaskTree.svelte` (the task-list page) shows an **"INVOICED"** link in the
  status column: for an invoiced task/subtask it **replaces** the activity/status
  indicator (an invoiced task is necessarily `complete`), and for an invoiced
  material it fills the otherwise-empty status cell. Both link to the invoice.
- `TaskDetailPage.svelte` (the single-task view) shows the **"INVOICED"** link on
  the Status row (replacing the activity indicator) and beside each invoiced
  material in its inline materials table; its subtasks render via `TaskTree`, so
  they inherit the indicator. The task's own `invoice` field is populated by a
  `retrieve` override on `TaskViewSet` that passes the `claims_for_job` map as
  context.
- `ExpenseListPage.svelte` shows an **"INVOICED · INV-xxxx"** badge in the Status
  cell of any billed (loose) expense, and **hides the mutating actions** (edit /
  reject / delete) for it — replacing them with a "billed — locked" note — since
  `ExpenseService.update` and `delete` both reject an invoiced expense
  server-side (`_assert_not_invoiced`). Material-bound expenses bill via their
  material, so only loose expenses ever show the badge.

### Per-source stacked list on line items

`InvoiceLineItemSerializer` includes a nested `sources` array
(via `InvoiceLineItemSourceSerializer`):

```json
"sources": [
    {"source_id": 11, "source_type": "task", "source_pk": 5,
     "description": "CNC Router (setup)", "computed_amount": "120.00"},
    {"source_id": 12, "source_type": "material", "source_pk": 3,
     "description": "Plywood — 4×8 (2 sheets)", "computed_amount": "48.00"}
]
```

`InvoiceLineItemSourceSerializer.get_description` resolves the atom via
`obj.resolve()` and delegates to `InvoiceWizardService._atom_description`.
`get_computed_amount` calls `InvoiceWizardService._atom_computed_amount`.

`WizardLineItemCard.svelte` renders these as a stacked `↳ description ✕` list
below the line item's price row, with per-source remove buttons. This replaces
the old "N atoms" count.

The **estimate** side has a parallel implementation: `EstimateLineItemSerializer`
includes `EstimateLineItemSourceSerializer` with the same `description` +
`computed_amount` fields (resolved via `EstimateWizardService._atom_description`
/ `_atom_computed_amount`), shown in the same stacked layout on
`WizardLineItemCard` for estimate line items.

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

`InvoiceDetailPage.svelte` (`frontend/src/routes/invoices/InvoiceDetailPage.svelte`) is the standard detail view of an invoice. It shares the same **JobHeader** band as the atom-pull wizard page. On `draft` invoices, users with `can_manage_financials` can add, edit, delete, and reorder line items using `LineItemModal.svelte` (the shared modal also used on the estimate detail page). Adding a line item offers a toggle between **manual entry** and **"From Price List"** (catalog mode, which POSTs `{price_list_item, qty}` and copies description/units/selling_price/accounting_category from the PLI). Editing an existing line item edits its fields only, with no catalog toggle.

A **"Show Billables"** link is shown on the detail page only to users with `can_manage_financials`, only when the invoice is in `draft` status, and only when the job has at least one task or material (`hasBillables`). If the invoice is not draft, the user lacks the permission, or the job has no billable sources, the link is absent.

On `open` or `partly-paid` invoices a disabled **"Revise (coming soon)"** placeholder button appears in the toolbar — invoice revision is not yet implemented.

### Discard

`DELETE /api/invoices/{id}/` calls `InvoiceService.discard_draft`, which validates draft status and hard-deletes. The viewset returns 200 with `{'message': 'Invoice discarded'}` per the project's all-DELETE-returns-JSON convention. There is no two-phase confirmation on this endpoint (the wizard owns the confirmation in the UI; cascade impact is implicit — all claimed atoms become free).

---

## Sending an Invoice

`InvoiceEmailService.send_invoice` in `apps/invoicing/services.py` is
the orchestrator. SPA route: `/invoices/:id/send`
(`InvoiceSendPage.svelte`). The compose page is mounted from the
detail page's "Send Invoice" link (button text reads "Resend Invoice"
when `qbo_id` is already set).

### Minibini-side flow

1. Caller posts `{to, subject, body, cc?, bcc?}` to
   `/api/invoices/{id}/send/`. Multipart `attachments` files come
   along for the ride.
2. View dispatches to `InvoiceEmailService.send_invoice(invoice, *,
   to, subject, body, cc, bcc, extra_attachments, user)`.
3. The service:
   - **If `invoice.qbo_id` is unset:** resolves a QBO customer ref
     (creates one for the job's business or contact if needed); builds
     the QBO Invoice via
     `InvoiceGroupingService.group_for_qbo(invoice)` — line items
     grouped by `(accounting_category, taxable)`, one QBO line per
     group, with `Description = "Job {number}: {category}
     (taxable|non-taxable)"`; saves it; stores `qbo_id`; marks the QBO
     invoice as Sent. Logs to `QBOSyncLog`.
   - **If `invoice.qbo_id` is set:** skips the push entirely (this is
     the retry path — the previous version had a bug where retries
     re-pushed and duplicated the QBO Invoice).
   - Generates a job-statement PDF
     (`apps/invoicing/pdf.generate_job_statement_pdf`).
   - Downloads the QBO-rendered invoice PDF (which carries the Pay
     Now link, the QBO branding, the calculated tax).
   - Calls `OutboundEmailService.send_tracked` with
     `associate_with={'job': invoice.job}` and both PDFs attached;
     user-uploaded extras append. The send-tracked path persists the
     outbound `EmailRecord` before SMTP runs, so SMTP failures keep
     the row around with `last_send_error` populated.
4. **On send success**, transitions `Invoice.status` `draft → open`.
   Returns `{email_record_id, invoice_status, qbo_id}`.
5. **On QBO failure** (`No active QBO connection`, build error, etc.)
   the view returns 400. **On SMTP failure** the view returns 502 and
   the outbound EmailRecord captures `last_send_error`. From the
   user's perspective there's one Send button either way; the backend
   decides where to resume based on `qbo_id` state.

### Minibini state changes

- `Invoice.qbo_id` is populated on the first send.
- `Invoice.status` flips `draft → open` on send success — Send is the
  status transition. There is no separate "Mark Sent" affordance.
- `Invoice.sent_date` is stamped (by `Invoice.save()`) on that `draft → open`
  transition, which is what the serializer's `due_date` / `is_late` derive from.
- An outbound `EmailRecord` is created, linked to the Invoice's Job
  via FK (so the email shows up in the Job overview Email panel, and
  the customer's reply auto-correlates to the same Job via
  In-Reply-To matching against the outbound's Message-ID).
- `QBOSyncLog` records the QBO push attempt on the first send only.

### Why we own the email pipeline (and QBO is invisible plumbing)

QBO renders the invoice PDF (with Pay Now link and tax). Minibini
generates the job-statement PDF (the detailed breakdown the customer
asks about when there's a question). Both go out as attachments on
*our* outbound email so reply correlation, threading, and the
Email-panel view all work uniformly across Estimate / PO / Invoice.

Configuration keys for the body/subject templates:
`invoice_email_subject_template`, `invoice_email_body_template`
(defaults documented in
`architecture-and-conventions.md` §7.10). The common template
variable set is available; `{invoice_number}` aliases
`{document_number}`.

For OAuth, the `QBOSyncLog` model, payment polling internals, the
customer-sync flow, and connection lifecycle, see
`docs/designs/quickbooks-integration.md`.

### Payment polling

`QBOPaymentPollingService.poll_all()` (in `apps/qbo/services.py`) is wrapped by the `poll_qbo_payments` management command (`apps/invoicing/management/commands/poll_qbo_payments.py`), run every 15 minutes by the docker cron service (see `architecture-and-conventions.md` §9). It walks every Invoice with a `qbo_id` that is still `open` or `partly-paid`, fetches the QBO invoice, and derives both the raw cache and the Minibini status from QBO's `Balance` / `TotalAmt`:

- **fully paid** (`Balance == 0`) → cache `qbo_payment_status='Paid'`, status → `paid`;
- **partial** (`amount_paid > 0`) → cache `'Partial'`, status → `partly-paid`;
- **unpaid** (nothing paid) → cache `'Unpaid'`, no status change.

`qbo_payment_status` and `qbo_amount_paid` are the **raw cache** of what QBO reported; the service now also **drives `Invoice.status`**. On a status change it does a full `invoice.save()` — which stamps `closed_date` and (on `paid`) fires `_maybe_complete_job`, auto-completing the job when all its invoices are resolved — and writes a `system`-attributed `action` HistoryEntry recording the payment-synced transition. No active QBO connection → the command records a `skipped` run (it does not fail).

**First-run healing.** Because the redesign is the first thing to drive status from the cache, any invoice sitting at `open` with a stale cached `qbo_payment_status='Paid'` (written by the old cache-only polling) will transition to `paid` on the first run under the new code — and, via `_maybe_complete_job`, complete its job. This is intended, but it means the first poll after deploy may move a batch of already-paid-in-QBO invoices and their jobs to terminal in one sweep.

### All-shipped completion gate

`JobService.maybe_complete_if_resolved(job)` (in `apps/jobs/services.py`) is the single auto-completion gate. It runs from two triggers:

- `Invoice._maybe_complete_job` (on entry to `paid` / `cancelled`) — delegates to it. `Invoice.save()` fires it whenever the status transitions **into** `paid` or `cancelled`; the API cancel action (`InvoiceViewSet.cancel`) routes through `InvoiceService.cancel`, which loads the invoice and calls `.save()` so the gate runs (it does **not** use a bypassing `QuerySet.update()`).
- `ShipmentService.mark_picked_up` — calls it at the end of every shipment pickup.

Whichever lands last — the final payment or the final shipment — completes the job, provided **all** of these hold:

- **Job is `work_complete`.** This is the only state that means the work itself is finished — a job reaches it only once all of its tasks are complete. Resolving an invoice (or shipping the last deliverable) on a job in any other state is a no-op: an `in_progress` job may still have open tasks (a follow-up to send plans/photos, a post-job meeting), a deposit invoice may be paid before any work starts, and `draft`/`submitted`/`on_hold` jobs have no finished work at all. The job completes later, once it legitimately reaches `work_complete` and an invoice/shipment trigger fires. (This also avoids forcing a transition the state machine forbids, e.g. `on_hold → completed`.)
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
| `job` | FK Job (SET_NULL, nullable, `expenses`) | **The cost anchor.** `null` = overhead. Job P&L groups expenses by this directly. `SET_NULL` mirrors `material` (the financial record outlives a hard-deleted job, becoming overhead). |
| `material` | FK Material (SET_NULL, nullable, `expenses`) | The ONE consumable material this expense *created* (cost-expense mode), or null. Expenses never link an existing material. `material.job` must equal `job`. |
| `stock_pli` / `stock_qty` | FK PriceListItem (inventoried) + Decimal | Stock-receipt mode: an inventoried purchase that bumped QOH. Mutually exclusive with `material`; `amount` is not job-costed (cost-at-consumption). |
| `status` | CharField — see machine | Default `submitted`. |
| `qbo_id` | CharField(50), blank | Set when the QBO push succeeds (company-paid only — personal expenses' QBO IDs live on their reimbursement batch). |
| `qbo_sync_error` | TextField, blank | |
| `reimbursement` | FK Reimbursement (PROTECT, nullable, `expenses`) | Set when the expense is batched. PROTECT prevents deleting a Reimbursement that still has expenses pointing at it; the unwind path clears these refs first. |
| `created_at`, `updated_at` | Timestamps | |

`db_table = 'expenses'`. Default ordering: `['-purchased_on', '-created_at']`.

`clean()` enforces:
- Personal: `purchased_by` required, `payment_account_id` must be blank.
- Company: `payment_account_id` required.
- If `material` and `job` are both set, `material.job == job` (consistency).

The model is **not** decorated with `@history` — Expense changes do not write to the audit log automatically.

### Job anchor + the two expense modes (cost-model redesign 2026-06-14)

A Job is the cost anchor (`Expense.job`; `null` = overhead). A single `amount`;
**expenses never link to an existing material** — they only create their own. An
expense is one of two modes (see `docs/plans/2026-06-14-expenses-cost-model-redesign.md`):

- **Cost expense** — optionally creates ONE consumable **material** (freeform or
  non-inventoried PLI) at the user-entered `unit_cost` (no division, no recost).
  The expense `amount` is the job cost (cost-at-purchase).
- **Stock receipt** — an **inventoried** PLI purchase: `stock_pli` + `stock_qty`
  bump QOH (`InventoryService.receive_stock`); **no consumable material**. The
  `amount` is inventory, **not** job-costed — cost flows at **consumption** (the
  job's own material consuming the stock), same as a PO.

Modes are mutually exclusive (validated). An inventoried `new_material` is routed
to a stock receipt automatically.

- **Job P&L** (`apps/jobs/financials.py` `_spent`) = non-rejected, **non-stock-
  receipt** expenses by `amount` (overhead `job=null` excluded) + consumed
  materials with no expense, at cost (where inventoried stock cost lands) + labor.
  Money is counted exactly once.
- **Plywood top-up** (need 10, have 7, buy 3 as a stock-receipt expense): QOH
  7→10, the 10-sheet material consumes once at cost; overage stays as stock. No
  double-count. The consume short-stock error suggests reducing the material and
  splitting the remainder.

Backfill migration `expenses/0002` set `job` from `material.job` for existing
rows; `expenses/0003` added the stock-receipt fields. (Earlier recost/clobber/
link-existing machinery was removed in the 2026-06-14 rework.)

### Editability and the invoiced freeze

Expenses are **fully editable after entry** (no reason-gating) — correcting a
wrong job is the same as any other edit. Moving a material-linked expense to
another job moves its material too (composing `InventoryService.unconsume` →
move earmark → re-consume for a consumed inventoried material). The one hard
lock: an expense is **immutable while it — or its material — is on a
non-cancelled invoice** (`ExpenseService._assert_not_invoiced`, which delegates
to `InvoiceClaimService.is_invoiced` — the same centralized predicate used by
`MaterialService._assert_not_invoiced`; checked in `update`/`delete`). To edit
a billed expense, remove it from the invoice first.
`reject()`'s consumed-material wall still applies to *rejection* (not to editing).

A second money lock covers reimbursement: once an expense is **reimbursed** (in a
batch — the person has been paid), `_assert_reimbursed_money_unchanged` blocks
changes to `amount` / `payment_method` / `payment_account_id` / `purchased_by`,
and `delete()` is refused. Cost-attribution (`job`, `material`) and clerical
fields stay editable. To change a paid amount, unwind the reimbursement first
(`ReimbursementService.delete` flips the expenses back to `submitted`).

### Billing: expense as a billable atom

A **material-less** job expense is a first-class `BillableAtom` in the invoice
wizard, alongside Task charges and Materials (`Expense.compute_amount()` returns
`amount`). The wizard's source pool exposes an **Expenses** group (material-less,
non-rejected expenses on the job); `InvoiceWizardService` atom hooks
(`_resolve_atom`/`_atom_source_type`/`_atom_units`/`_atom_category`/
`_atom_description`/`_atom_qty_and_price`/`_atom_detail`) handle the `'expense'`
type, and `InvoiceLineItemSource` gained `SOURCE_EXPENSE`.

- **Pass-through cost:** a line built from an expense atom gets `qty=1`,
  `price=amount`; the invoicer edits the line to set the actual sell price (mark
  up / round / zero to absorb). Cost vs. billing stay separate.
- **No double-billing:** material-*linked* expenses are **not** offered as atoms
  — they bill through their material. So "material-less" is the precise trigger.
- **Already-invoiced:** once on a non-cancelled invoice, the expense shows
  `claimed_by_*` in the pool (not removed) — same as Materials/Tasks. This is
  also exactly what freezes the expense (see above).
- **Billability gate:** expenses have **no readiness gate** in the wizard pool —
  they are always selectable as long as they are not already claimed. (Tasks
  require `complete`; Materials require `consumed`; Expenses are billable from
  the moment they are submitted.) See `docs/designs/estimates-and-prices.md` §7
  for the wizard-pool billability rules.

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

In the UI, `ExpenseForm` shows the **Purchased by** picker (defaulting to the current user) only to `can_manage_financials` holders — entering an expense *for someone else* is a financials capability. Everyone else's expense is implicitly their own (the picker is hidden). The task-list "Expenses (no material)" table shows a Purchased-by column.

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
| `submit(*, entered_by, payment_method, amount, purchased_on, accounting_category, description='', payment_account_id='', reference_number='', purchased_by=None, new_material=None, job=None, stock_pli=None, stock_qty=None) -> Expense` | Atomic create. `new_material` with an inventoried PLI → a stock receipt (QOH ↑, no material); otherwise a consumable material at the entered cost. No existing-material linking. Calls `_push_and_set_status` for company-paid; leaves personal `submitted`. |
| `update(*, expense, actor, **fields) -> Expense` | Editable fields: amount, purchased_on, description, accounting_category, payment_method, payment_account_id, reference_number, purchased_by, job, **stock_qty** (adjusts the receipt's QOH by the delta). `material` is not editable post-create. Guards: invoiced-freeze + reimbursed-money lock; a linked material follows a job change. Calls `_resync` if `expense.qbo_id`. |
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
| Invoice list | `frontend/src/routes/invoices/InvoiceListPage.svelte` (route `#/invoices`) |
| Invoice detail | `frontend/src/routes/invoices/InvoiceDetailPage.svelte` |
| Invoice wizard | `frontend/src/routes/invoices/InvoiceWizardPage.svelte` (route `#/invoices/:id/wizard`) |
| Source pool | `frontend/src/components/invoices/WizardSourcePool.svelte` |
| Line item modal (shared with estimates) | `frontend/src/components/LineItemModal.svelte` |
| Line item card (shared with estimates) | `frontend/src/components/wizards/WizardLineItemCard.svelte` |
| Footer actions (shared with estimates) | `frontend/src/components/wizards/WizardActions.svelte` |
| Send-to-QBO dialog | `frontend/src/components/invoices/SendToQBODialog.svelte` |

### Invoice list page

`InvoiceListPage.svelte` is the SPA route at `#/invoices`, accessible via the **Financials** sidebar section (gated on `can_manage_financials`).

**Columns:** Invoice#, Job, Customer, Status, Sent, Due (with a late flag when past due and unpaid), Amount, Paid, Balance.

**Default view:** status preset **Open** (includes `open` + `partly-paid` invoices), sorted by due date ascending — most overdue first, nulls last.

**Status presets:** Open / Paid / Draft / Cancelled / All.

**Filters:** status preset, due-date range (from/to), and a `CustomerPicker` component that emits `{type: 'business'|'contact', id}`. A business selection maps to `?business=<id>`, rolling up invoices for all of that business's contacts; a contact selection maps to `?contact=<id>`.

**Backend — `?summary=true` opt-in (dual contract).** The financials list page calls `GET /api/invoices/?summary=true`. Only in **summary mode** does `InvoiceViewSet` switch to the lightweight `InvoiceSummarySerializer`, apply the annotated totals, default the status filter to **open** (open + partly-paid), and apply the status presets / due-date range / `?business=` / `?contact=` / ordering. **Without** `summary=true`, the list endpoint keeps its original contract — the full `InvoiceSerializer` (with nested `line_items`) and **all** statuses (no default filter). This preserves the pre-existing consumer `GET /api/invoices/?job=<id>`, which the **Job overview** (`JobDetailPage`) uses to render each invoice's line items and compute billed/paid rollups. (Switching the bare list action to the summary serializer + default-open unconditionally was a regression that left the Job overview showing invoices with no line items and no totals.) List read permission stays `IsAuthenticated` in both modes — the Financials sidebar gate is a UI convention only.

`InvoiceWizardPage` tracks `selectedAtoms` with `$state`; "Add to line item" and "Create new line item" both POST and reload. 409 from the API surfaces as an alert prompting the user to reopen the wizard for a fresh source pool.

### Job overview — Create/View model

The Job overview page (invoice pillar) follows a Create/View model:

- **"Create Invoice"** — shown when the job's status is billable (`approved`, `in_progress`, `work_complete`, `completed`, or `cancelled`) **and** no draft invoice exists. POSTs `{job}` to `/api/invoices/` (routed through `InvoiceWizardService.open_for_job`) and navigates to the new invoice detail page. Shown/allowed for users with `can_manage_jobs` **or** `can_manage_financials` (the `create` action of `InvoiceViewSet` is `(CanManageJobs | CanManageFinancials)`, matching the frontend gate and the wizard path; all other invoice write actions, including line-item editing, stay `can_manage_financials`-only).
- **"View Invoice"** — shown whenever any invoice exists for the job, regardless of its status.

Both can appear together: for example, a job may have a sent (`open`) invoice and no draft, in which case "View Invoice" and "Create Invoice" are both shown (the "Create" would open a second draft for the new billing event). One draft per job is guaranteed by the application-level get-or-create in `InvoiceWizardService.open_for_job` — a second "Create" while a draft already exists returns the existing draft rather than creating a new one. (The `unique_draft_invoice_per_job` partial unique constraint is declared on the model but is **not** created on MySQL, which doesn't support conditional unique constraints — Django emits `models.W036` — so the invariant rests on the service, not the DB.)

A standalone invoice list is available at `#/invoices` — see "Invoice list page" above.

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
- **`superseded` and `defaulted` statuses.** Both are defined in the status machine's choices but have no transition path that sets them. (Payment polling now drives `partly-paid` / `paid` — see "Payment polling" above — so those two are no longer dead.)
- **One-click invoice generation.** Auto-create a draft invoice from all uninvoiced atoms when a Job hits `work_complete`, without going through the wizard. Will share the data model with the wizard. Out of scope per the 2026-04-09 design.
- **Invoice list customer filter — cross-contact rollup.** The `CustomerPicker` → `?business=` filter rolls up all of a business's contacts' invoices via an annotated queryset join; this may produce unexpected results for businesses where multiple contacts have separate billing relationships.
- **Invoice revision** — the "Revise" button on `open`/`partly-paid` invoices is a disabled placeholder. The mechanism for creating a revised draft from a sent invoice (parallel to `EstimateService.revise_estimate`) is not yet implemented.
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
