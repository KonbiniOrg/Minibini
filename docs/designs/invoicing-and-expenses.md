# Invoicing and Expenses

The customer-facing billing side of Minibini and the employee/company expense ledger that feeds job costing and reimbursements.

## What this doc owns

- The `Invoice`, `InvoiceLineItem`, and `InvoiceLineItemSource` models.
- The invoice wizard (re-aggregating the job's atoms — `Task`, `Material`, plus `Expense` claims — into invoice line items).
- Agreement-line references, auto-seeding, and the derived `backing`
  model (the invoice side of the three-mode surface built from the
  shared `docsurface` kit — see `estimates-and-prices.md` §12 for the
  estimate side and `architecture-and-conventions.md` §5.5b for the
  kit's own conventions).
- The Minibini-side shape of "send an invoice to QBO": which states transition, which surfaces show what.
- The `Expense` and `Reimbursement` models, services, and viewsets.
- Per-expense permission scoping in the API.

## What this doc does not own

- Service-layer conventions, `LineItemMixin`, `StatusTransitionMixin`, two-phase delete, the line-item delete-and-renumber rule. See `docs/designs/architecture-and-conventions.md` and `CLAUDE.md`.
- `Job`, `Task`, `Blep`, `WorkTemplate` shape. See `docs/designs/jobs-and-tasks.md`.
- The estimate wizard (`EstimateLineItemSource`, the same Job atoms, in-sync rule). The invoice wizard mirrors it; see `docs/designs/estimates-and-prices.md` for the shared structure and the `LineItemSource` claim model.
- `Material` shape, `MaterialService.consume`, `is_expense_bound`, the "Materials (no task)" bucket. See `docs/designs/materials-inventory-and-purchasing.md`.
- Vendor-side AP: bills live entirely in QBO — the konbini Bill domain was retired 2026-07-23. See `docs/designs/materials-inventory-and-purchasing.md` §13.
- OAuth, `QBOSyncLog`, payment polling, sync-failure plumbing. See `docs/designs/quickbooks-integration.md`. This doc references the push points but does not describe their internals.

---

## Invoice

`apps/invoicing/models.py` — `Invoice`.

One per draft, one per real billing event. Linked to `Job` (FK, `CASCADE`). The job is the only structural parent; an invoice does not link to an estimate — it is a lens over the job's atoms (with `copy_from_estimate` as a convenience seeding path).

### Fields

| Field | Type | Notes |
|---|---|---|
| `invoice_id` | AutoField PK | |
| `job` | FK Job (CASCADE) | |
| `invoice_number` | CharField(50), unique, **nullable** | **QBO-assigned** (2026-07-21): NULL until the first QBO push writes QBO's `DocNumber` back. Konbini no longer generates invoice numbers. The `display_number` property (`invoice_number` or `"Draft — {job_number}"`) is what every UI surface renders — serializers expose it read-only. |
| `status` | CharField — see machine below | Default `draft`. |
| `created_date` | DateTimeField | `default=timezone.now`. |
| `sent_date` | DateTimeField, nullable | Stamped by `Invoice.save()` the first time the invoice transitions `draft → open` (the send-to-customer step; mirrors `Estimate`), if not already set. A row created directly as `open` is not stamped. The serializer's derived `due_date` (`sent_date + 30 days`) and `is_late` read off this. |
| `closed_date` | DateTimeField, nullable | Stamped by `Invoice.save()` the first time the invoice transitions to `paid` (any path), if not already set. |
| `qbo_id` | CharField(50), nullable | Set when `QBOInvoiceSyncService.push_invoice` succeeds. |
| `qbo_payment_status` | CharField(50), default `''` | One of `Paid` / `Partial` / `Unpaid` — written by `QBOPaymentPollingService.poll_all`. |
| `qbo_amount_paid` | Decimal(10,2), nullable | Updated by the polling service. |

`@history(exclude=['invoice_id'])` decorates the model — status changes auto-write `HistoryEntry` rows.

`InvoiceSerializer` additionally exposes a read-only `total`
`SerializerMethodField` (`Σ line.qty × line.price` across the invoice's
line items, quantized to cents) — the authoritative document total,
matching `InvoiceSummarySerializer.total_anno` and
`financials._invoiced`. The job-overview Invoicing block
(`frontend/src/lib/jobOverview.js`) consumes this rather than
recomputing client-side (adjustment/percentage lines make a client-side
`qty*price` walk fragile). It is a per-object method field with no
queryset annotation on the plain (non-`summary=true`) list action, so
an unfiltered `/api/invoices/?job=<id>` pays one extra query per
invoice row — see `docs/designs/LATER.md` for the N+1 note.

### Status machine

| Value | Meaning |
|---|---|
| `draft` | Editable. Wizard works against this state. Default on create. |
| `open` | Sent to customer; awaiting payment. Set by the send-to-customer flow (`InvoiceEmailService.send_invoice` flips `draft → open` on send success, stamping `sent_date`). Payment polling treats `open` (and `partly-paid`) as its input states and promotes `open → paid` / `partly-paid` automatically. |
| `cancelled` | Terminal. Frees its claimed atoms **physically**: entering it deletes the invoice's `InvoiceLineItemSource` rows (`Invoice.save()` → `claims.release_invoice_claims`, 2026-07-28), so a released atom can actually be re-claimed. Before that the rows survived and only the *readers* skipped them, so the pool offered an atom the `(source_type, source_pk)` unique constraint then refused. Line items stay put — the void invoice keeps its frozen snapshot, exactly like a rejected estimate. Set via `InvoiceService.cancel` (API: `InvoiceViewSet.cancel`), which loads the invoice and calls `.save()` so the completion gate fires — a cancelled invoice counts as resolved, so cancelling the last unresolved invoice on a `work_complete`, all-shipped job auto-completes it. |
| `superseded` | Defined in choices, no current transition. |
| `partly-paid` | Set by `QBOPaymentPollingService.poll_all` when QBO reports a partial payment (some balance paid, some outstanding). |
| `paid` | Set by the polling service when QBO reports the invoice fully paid (balance zero); also reachable by any other path that writes `STATUS_PAID`. When written, `Invoice.save()` stamps `closed_date` (if unset) and calls `_maybe_complete_job()` (also fired on entry to `cancelled`), which delegates to `JobService.maybe_complete_if_resolved(job)` — the single completion gate (see "All-shipped completion gate" below). The gate completes the job (via `JobService.update_job`) only if the job's **work is finished** (`work_complete`, or `approved`/`in_progress` with ≥1 task, all terminal — the loose-material-stranded case) **and** all of the job's invoices are resolved (paid or cancelled) **and** every Deliverable on the job is fully picked up. A job whose work is open (including a deposit-invoiced task-less job) is left untouched. Before the walk it releases any loose pending Materials on the job — `JobService.release_loose_materials`; claimed ones become `released` history, unclaimed delete — so the `work_complete` materials gate cannot strand the job on this unattended path. A `cancelled` job is never auto-completed (the state machine forbids `cancelled → completed`). |
| `defaulted` | Defined in choices, no current transition. |

`InvoiceViewSet.status_actions` registers only `cancel`, which delegates to `InvoiceService.cancel` (loads the invoice and calls `.save()` so the completion gate runs — not a bypassing queryset update). Everything else is set by direct `save()` or by code that has not yet been written.

`Invoice.clean()` blocks transitioning out of `draft` if there are zero `InvoiceLineItem` rows.

### "One draft per job" — design vs. reality

Guaranteed by the application-level get-or-create in `InvoiceWizardService.open_for_job`, which returns the existing draft when one is found. A `unique_draft_invoice_per_job` partial unique constraint (on `status='draft'`) is declared on `Invoice`, but it is **not** created on MySQL — which doesn't support conditional unique constraints (Django emits `models.W036`) — so the invariant rests on the service, not the DB.

`InvoiceViewSet.perform_create` routes every direct `POST /api/invoices/` through `InvoiceWizardService.open_for_job` — the same service entry point used by the atom-pull wizard. This means direct invoice creation is also subject to the get-or-create semantics (returns the existing draft if one exists) and the billable-job-status guard (returns HTTP 400 if the job's status is not in `BILLABLE_JOB_STATUSES`). There is no separate creation path that bypasses the service.

### Document numbering

**QBO owns invoice numbering** (2026-07-21). `Invoice.save()` no longer auto-generates a number; the `'invoice'` NumberGenerationService pattern is retired (its `Configuration` rows are harmless leftovers, and the settings UI no longer offers the invoice pattern). On the first QBO push, `send_invoice` writes QBO's `DocNumber` into `invoice_number`; a retry send backfills it from QBO if missing. Rationale: future tenants arrive with QBO already numbering their invoices — konbini attaches to that scheme instead of competing. Drafts render `display_number`'s placeholder (`"Draft — {job_number}"`; unambiguous because of single-draft-per-job).

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

`_live_sources()` excludes sources whose invoice is in
`DEAD_INVOICE_STATUSES` — `cancelled` **or** `superseded`. Since
2026-07-28 that exclusion is belt-and-braces: entering either status
deletes the rows outright (below), so there are normally none left to
exclude. The filter still guards rows written before that change, and any
written by a path that bypasses `save()` (`QuerySet.update`).

**The release lives in `Invoice.save()`**, not in `InvoiceService.cancel`,
so every writer is covered — matching `Estimate.save()` /
`ChangeOrder.save()` on the other lens (`estimates-and-prices.md` §6.2).

**`superseded` is included ahead of its writer.** Nothing sets it yet —
there is no invoice-revision flow (see `LATER.md`, "Invoice revisions") —
but the invariant "a dead document holds no claims" shouldn't wait for
one, and the SPA's `INVOICE_DEAD_STATUSES` has always counted it dead, so
including it keeps the two ends in agreement. **Note for whoever builds
invoice revision:** move or re-point the source rows onto the new revision
*before* flipping the parent to `superseded`, the way
`EstimateService.revise_estimate` does — the release fires on that
transition and would otherwise drop rows the revision still wanted.

`paid` is emphatically not a dead status: a paid invoice's claims are what
stop the same atom being billed twice.

---

## InvoiceLineItem and InvoiceLineItemSource

`apps/invoicing/models.py`.

### InvoiceLineItem

Inherits `BaseLineItem` (description, qty, units, price, accounting_category, etc. — see `apps/core/models.py`; the per-line `taxable_override`/`tax_rate_override` fields were removed 2026-07-21 — taxability reads `accounting_category.taxable` directly). Has no direct `task` FK; `task` is exposed as a `@property` returning `None` purely so `BaseLineItem.clean()`'s "task XOR inventory_item" rule passes. Source linkage is via the `InvoiceLineItemSource` join table.

`db_table = 'invoice_li'`. Parent field name (for `LineItemMixin`) is `invoice`.

Deletion goes through `LineItemService.delete_line_item_with_renumber(line_item)` per the project rule — never `.delete()` directly. `InvoiceService.delete_line_item` does this.

**Adjustment fields** (parallel to `EstimateLineItem`):

- `adjustment_service` — nullable FK to `RateScheme` (PROTECT). Set when
  this line is a percentage adjustment (e.g. rush surcharge, volume discount).
  A line with `adjustment_service_id` set is an **adjustment line**.
- `adjustment_target_categories` — M2M to `AccountingCategory`. The
  categories the adjustment applies to. Empty = all non-adjustment lines.
- The serializer exposes a read-only `adjustment_service_detail` dict
  `{name, rate, algorithm}` for display when `adjustment_service` is set.

**Agreement-line reference fields (2026-08, skeleton phase).**
`agreement_estimate_line` (FK → `estimates.EstimateLineItem`,
`on_delete=SET_NULL`, null/blank, `related_name='invoice_lines'`) and
`agreement_co_line` (FK → `estimates.ChangeOrderLineItem`, same shape) —
which `compose_agreement` line (§"Agreement-line references and
seeding" below) this invoice line was seeded or restored from, or
`None` on a hand line. `SET_NULL` (never `CASCADE`): an invoice line
must survive its agreement line vanishing. The `agreement_line`
property returns whichever of the two is set (or `None`) — the single
read path every consumer (the serializer's `agreement_ref`, the
backing derivation) uses instead of checking both fields itself.
Migration: `apps/invoicing/migrations/0023_invoicelineitem_agreement_co_line_and_more.py`
(two plain `AddField` operations, no data migration).

### InvoiceLineItemSource

Polymorphic join between `InvoiceLineItem` and the job atom it represents (a `Task`, `Material`, or `Expense`) — or, for `source_type='deposit'`, another `InvoiceLineItem` (see Deposits below). "Polymorphic" only in the sense that the atom side may be one of several model types; this is not a Django generic relation.

| Field | Type | Notes |
|---|---|---|
| `source_id` | AutoField PK | |
| `invoice_line_item` | FK InvoiceLineItem (CASCADE) | `related_name='sources'`. |
| `source_type` | CharField(20), choices `'task'` / `'material'` / `'expense'` / `'deposit'` | `SOURCE_TASK`, `SOURCE_MATERIAL`, `SOURCE_EXPENSE`, `SOURCE_DEPOSIT`. |
| `source_pk` | PositiveIntegerField | The `Task.pk` / `Material.pk` / `Expense.pk` — or, for `'deposit'`, the **deposit `InvoiceLineItem.pk`** being claimed (`resolve()` looks it up on `InvoiceLineItem` itself rather than a Job-atom model). |

`db_table = 'invoice_line_item_sources'`.
`unique_together = [('source_type', 'source_pk')]` — DB-level enforcement of whole-atom claim. An atom cannot appear in two `InvoiceLineItemSource` rows. For `'deposit'` rows this is what makes the credit **unsplittable**: a paid deposit line can be claimed by at most one deduction, ever (see Deposits below) — the same mechanism that blocks double-billing a Task/Material/Expense, applied to a deposit line instead of a Job atom.

`InvoiceLineItemSource.resolve()` returns the concrete `Task` / `Material` / `Expense` instance.

### Atoms — same Job atoms as the estimate

Both the estimate and the invoice are **lenses** over the **same Job atoms** (see `estimates-and-prices.md` §7) — `Task`, `Material` — plus, invoice-only, material-less `Expense`s. (The `Fee` atom was retired with the `Fee` model, 2026-08 — a plain hand-line no longer crystallizes into a job atom on accept; it transits to an invoice via agreement-line references instead — see "No fee-claim-on-copy" and "Agreement-line references and seeding" below.)

| Atom | Invoice billable amount | Billable when |
|---|---|---|
| `Task` | `task.compute_amount()` — actuals (bleps / `actual_qty`) via the `RateScheme` | `status == complete` |
| `Material` | `quantity × sell_price` | `consumption_state == consumed` |
| `Expense` (material-less) | the expense amount | always (submitted) |

See `InvoiceWizardService._atom_computed_amount`. The estimate side projects `est_qty` (`Task.compute_estimate_amount`) instead — the lens difference.

### Whole-atom claim constraint

The invoice side uses a flat, global unique constraint — `unique_together = [('source_type', 'source_pk')]`. A job atom is a single physical thing and is not duplicated across invoices, so the constraint enforces the project's "no double billing" rule directly at the DB. (The estimate side uses the same shape — see estimates doc — and on revision *moves* the source rows to the new revision rather than duplicating.)

When the wizard hits a race, `InvoiceWizardService` catches `IntegrityError` and raises `ClaimConflict(atom_ids=...)`. The viewset translates this to HTTP 409 with `{'error': 'atoms_already_claimed', 'atom_ids': [...]}`.

### Cascades

- Deleting an `InvoiceLineItem` deletes its `InvoiceLineItemSource` rows (CASCADE).
- Deleting an `Invoice` cascades to its line items, then to their sources. All claimed atoms become available again.
- Deleting a `Task` / `Material` / `Expense` does not affect `InvoiceLineItemSource` rows directly (no FK; the join uses `source_type`+`source_pk`). A claimed atom that gets deleted leaves a dangling source whose `resolve()` raises `DoesNotExist`. Atom deletion is gated upstream — Tasks with bleps don't get hard-deleted in normal flows.

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
  the flat `TaskViewSet.materials` GET action builds
  `InvoiceClaimService.claims_for_job(task.job)` and passes it as
  `invoice_claims` context to the tasks-app `MaterialSerializer`, so
  materials fetched there also carry `invoice`. (That serializer gained the
  `invoice` field via `InvoiceRefMixin` too; the subtasks endpoint was
  removed 2026-08 — better-fees spec §3.)
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
  status column: for an invoiced task it **replaces** the activity/status
  indicator (an invoiced task is necessarily `complete`), and for an invoiced
  material it fills the otherwise-empty status cell. Both link to the invoice.
- `TaskDetailPage.svelte` (the single-task view) shows the **"INVOICED"** link on
  the Status row (replacing the activity indicator) and beside each invoiced
  material in its inline materials table. The task's own `invoice` field is
  populated by a `retrieve` override on `TaskViewSet` that passes the
  `claims_for_job` map as context.
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

`InvoiceEditView.svelte`'s `AtomChildRow` (`docsurface/`, shared with the
estimate side — `estimates-and-prices.md` §12.1) renders these as
indented rows nested directly beneath the line, with a per-source
Remove button. The **estimate** side has a parallel implementation:
`EstimateLineItemSerializer` includes `EstimateLineItemSourceSerializer`
with the same `description` + `computed_amount` fields (resolved via
`EstimateWizardService._atom_description` / `_atom_computed_amount`),
nested the same way.

---

## Agreement-line references and seeding

**Design authority:** `docs/plans/2026-08-06-better-fees.md` §7.1/§7.2
(rationale) and §9 + the wireframe artifact it links (the settled
surface). Shipped 2026-08, "skeleton phase" — the invoice's job changed
from "compose lines from a pool of atoms" to "start from the agreement,
then reconcile against actuals."

### The invariant

An agreement line (an `EstimateLineItem` or `ChangeOrderLineItem` line
surfaced by `compose_agreement`) is referenced by **at most one live
(non-cancelled) invoice**, enforced under a row lock
(`InvoiceService._assert_agreement_line_unclaimed`, `select_for_update`
on the agreement line's own pk) inside both `seed_from_agreement` and
`restore_agreement_line`. A violation raises `ValidationError('This
agreement line is already on invoice INV-….')`
(`display_number` in the message, not the raw pk). `LIVE_INVOICE_STATUSES`
(module-level in `apps/invoicing/services.py`) is every `Invoice` status
except `cancelled` — deliberately broader than `claims.py`'s
`DEAD_INVOICE_STATUSES` (which also treats `superseded` as dead): the
agreement-line invariant was scoped to "not cancelled" specifically.
`apps/core/management/commands/validate_data.py`'s
`check_agreement_line_invoice_exclusivity` re-checks this at rest — see
`data-constraints.md` §1.16.

Removing a line from a draft (`InvoiceService.remove_line`, below) or
cancelling its invoice (`InvoiceService.cancel`) releases the reference
— the two ref FKs (`agreement_estimate_line`/`agreement_co_line`) are
set back to `None` on the surviving/remaining line, so the agreement
line becomes eligible again. `cancel` NULLs both fields by iterating and
calling `.save()` per line (never `QuerySet.update()` — the project's
usual rule), in addition to `Invoice.save()`'s existing claim release
via `claims.release_invoice_claims`.

### `remaining_agreement_lines(job)`

Returns the `compose_agreement(job)['lines']` minus any line already
referenced by a **live** invoice on the job — including the caller's
own draft, if it already carries that reference. This is deliberate: a
line already on a live invoice never reappears as "remaining", even
when that invoice is the one asking, which is exactly what stops the
restore picker from re-offering a line the current draft already
carries, and what stops `seed_from_agreement` from double-seeding a
partially-seeded draft.

### `seed_from_agreement(invoice) -> int`

Called automatically the first time a **new** draft invoice is created
on a job with an agreement (see "Auto-seed on creation" below) — its
only caller today is `InvoiceWizardService.open_for_job`; there is no
UI button that calls it a second way (the older "Apply everything" /
"Copy from estimate" buttons call different, unrelated methods — see
"Auto-seed on creation" below). Inside one `transaction.atomic()`:

1. Walks `remaining_agreement_lines(invoice.job)` in order.
2. Re-checks the invariant per line (`_assert_agreement_line_unclaimed`,
   `exclude_invoice=invoice`).
3. Builds the `InvoiceLineItem` straight from the agreement dict
   (description/qty/units/price; AC from the source line's AC;
   adjustment lines copy `adjustment_service`/`adjustment_percent` +
   target categories) and saves it with a **plain `.save()`**, not
   `LineItemService.save_line_item` — that helper would recompute
   adjustment prices immediately, before the batch's own sibling lines
   and target-category M2M exist yet. A single
   `InvoiceService._recompute_adjustments(invoice)` pass runs once
   after the whole batch instead.
4. **Claim mirroring** (`_mirror_agreement_claims`): for an
   estimate/CO-origin line, pulls the accepted line's own
   `EstimateLineItemSource`/`ChangeOrderLineItemSource` rows and, for
   each, tries `InvoiceWizardService._assert_atom_billable` — a `Task`
   must be `complete` **or** `cancelled` (terminal, not complete, is the
   billability line — a cancelled task's recorded actuals are still
   work done), a `Material` must be `consumed`, a deposit line must
   belong to a `paid` invoice; Expense atoms have no gate and
   always pass. An atom that fails the gate is simply **skipped** (not
   fatal) — "referenced but unclaimed", claimable later once ready; the
   uncovered-work pool still shows it.
5. **Actuals re-derivation** (`_rederive_price_from_actuals`): for a
   non-adjustment line that just acquired ≥1 claim in step 4, price is
   immediately recomputed from those claimed atoms — the same
   `price = round(Σ compute_amount / qty, 2)` rule the wizard's own
   in-sync check uses (`InvoiceWizardService._sum_sources` +
   `BaseWizardService._expected_per_unit`) — and saved with another
   plain `.save()`. Qty/units/description stay the agreement's values;
   only price moves. A line with zero claims (a hand line, or every
   claimable atom failed step 4's billability gate) is left on the
   agreement's estimate values — there's no completed work yet to price
   from. This step runs for every line in the batch **before** the
   batch's single deferred `recompute_adjustments` pass (step 3's
   "single pass after the whole batch"), so a percentage-adjustment line
   targeting a re-derived sibling computes its percentage off the
   sibling's actuals amount, not its stale estimate snapshot.

Returns the number of lines created.

A backed agreement line therefore arrives **already on `actuals`**
(§"Backing model" below) whenever its work is ready, and priced from
that work's actuals rather than the estimate snapshot if the two have
drifted — case 1 of the design doc's acceptance criteria ("the estimate
went to plan") is genuinely boring: read and send. A plain agreement
line arrives with no claims, still on its estimate values — reconciling
it is the invoicer pulling the relevant atoms *in*, same "Add selected
here" gesture as any uncovered-work row.

### `restore_agreement_line(invoice, *, estimate_line_id=None, co_line_id=None)`

Re-adds exactly one previously-removed (or never-seeded) agreement line
to a draft — exactly one of the two kwargs is required
(`ValidationError` otherwise). Looks the line up in
`compose_agreement(invoice.job)['lines']` (`ValidationError('Agreement
line not found.')` if absent), re-checks the invariant, and builds/
mirrors/re-derives the line the same way `seed_from_agreement` does for
one line (steps 3-5 above, including the actuals re-derivation). This is
the **"add from agreement"** picker's backing call — it lists exactly
the remaining lines not already on the draft (see the struck-row UI
below).

### `remove_line(invoice, line_item)`

The single removal path for a seeded/restored/hand line — routes
through `LineItemService.delete_line_item_with_renumber` (dropping the
agreement ref FKs and cascading the line's `InvoiceLineItemSource` rows
along with the row itself), so an agreement line removed this way
becomes "remaining" again. **Every DELETE on an invoice line item goes
through this** — `InvoiceService.delete_line_item` (the `LineItemMixin`
generic entrypoint, `DELETE /api/invoices/{id}/line-items/{lid}/`)
delegates to `remove_line` rather than calling `LineItemService`
directly, so a removal from the API, the wizard, or any future caller
releases the reference and mirrored claims identically.

### Auto-seed on creation; `seed: false` opt-out

`InvoiceWizardService.open_for_job(job, seed=True)`: when it actually
**creates** a new draft (not when it returns an existing one — a
get-or-create hit is never re-seeded), it calls
`InvoiceService.seed_from_agreement(invoice)` unless `seed=False`. There
is deliberately **no "start from agreement" button** — every invoice on
a job with an agreement starts from it automatically (provisional, per
RM 2026-08-06 — "not sure about this but I want to try it and see";
revisit after real use). An estimate-less job (or one with a fully-
consumed agreement) simply seeds empty, same as before.

`POST /api/invoices/` (`InvoiceViewSet.perform_create`) reads `seed`
straight off `request.data` (default `True`, not routed through the
serializer) and passes it to `open_for_job`. The **only** opt-out caller
is `DepositInvoiceModal.svelte`, which sends `{job, seed: false}` on its
first of two create calls — a deposit invoice wants an empty,
deposit-only draft, not one pre-populated with agreement lines it isn't
billing yet.

**Not the same mechanism as the older "Apply everything" / "Copy from
estimate" buttons.** `InvoiceEditView` still shows both (only while
`canEdit && lineItems.length === 0` — now a rare state, reachable mainly
via a `seed: false` deposit draft before its own line is added, or an
estimate-less/agreement-less job), but neither calls
`seed_from_agreement`: **"Apply everything"** (`POST .../apply-everything/`)
calls the pre-existing `InvoiceWizardService.seed_all_atoms` — one line
per available job **atom**, unrelated to the agreement — and **"Copy
from estimate"** (`POST .../copy-from-estimate/`) calls the pre-existing
`InvoiceService.copy_from_estimate` (below), which copies
`compose_agreement` values onto plain lines **without** writing
`agreement_estimate_line`/`agreement_co_line` refs or mirroring claims —
those lines get no `agreement_ref`, no est-vs-actual reference, no
Restore, and read `backing: null` until something claims them by hand.
Both buttons predate this phase and were **not** changed by it; they
remain because their zero-lines precondition still occasionally holds.

### Endpoints

| Verb + path | Behavior |
|---|---|
| `GET /api/invoices/{id}/remaining-agreement-lines/` | Returns `{lines: [...]}` — the picker's feed; each `compose_agreement` line dict with Decimals stringified. Permission: `CanManageFinancials`. |
| `POST /api/invoices/{id}/restore-line/` | Body: `{estimate_line_id}` or `{co_line_id}` (exactly one). 201 with the serialized new `InvoiceLineItem`. Permission: `CanManageFinancials`. |

### Frontend: restore / "Remove from invoice" struck rows

`InvoiceEditView.svelte` keeps its own **client-side, session-local**
list of removed agreement-backed lines (`removedRefs`, a `$state`
array) — not a server list. `handleRemoveItem` calls `DELETE
.../line-items/{id}/` (single-phase, no confirm — the word "delete"
never appears; the button reads **"Remove from invoice"**); if the
removed line carried an `agreement_ref`, its `{kind, line_id,
description, qty_display, price, amount}` is pushed onto `removedRefs`
and rendered as a struck `tr.doc-offdoc` row (amounts parenthesized in
spirit, description/qty/price/amount still legible, dashed-hatched
background) with a **Restore** button. Restore POSTs `/restore-line/`
with `{estimate_line_id}` or `{co_line_id}` per the entry's `kind`, then
drops it from `removedRefs`. A hand line (no `agreement_ref`) simply
vanishes on Remove — the server-side delete already released whatever
it needed to release; there's nothing to restore. Either way the line
reseeds on the **next** invoice's `seed_from_agreement` regardless of
whether it was ever restored on this one — removal always frees the
agreement line for `remaining_agreement_lines`.

---

## Invoice wizard

The invoice wizard re-aggregates the job's atoms into the invoice line items the customer wants to see. It is the structural parallel of the estimate wizard (both are lenses over the same Job atoms).

For the shared concepts — source pool, claim semantics, in-sync vs. override rule, two-pane UI shape, manual vs. bundled line items — see `docs/designs/estimates-and-prices.md`.

### Service

`InvoiceWizardService` (in `apps/invoicing/services.py`). Composes on top of `InvoiceService`; manual line item CRUD continues to go through `InvoiceService` and the `LineItemMixin`.

The line-items-from-atoms logic (`add_atoms_to_new_line_item`, `add_atoms_to_line_item`, `remove_atoms_from_line_item`, and the in-sync / bundle-summary helpers) lives in `BaseWizardService` (`apps/core/wizard.py`), shared with `EstimateWizardService`. `InvoiceWizardService` subclasses it, supplies a config block plus model hooks, and keeps the invoice-specific methods (`open_for_job`, `get_source_pool`, `BILLABLE_JOB_STATUSES`).

| Method | Responsibility |
|---|---|
| `open_for_job(job, seed=True)` | Returns the job's draft `Invoice`. Creates one if none exists — a newly-**created** draft auto-seeds from the agreement (`InvoiceService.seed_from_agreement`) unless `seed=False`; an **existing** draft is returned as-is and never re-seeded. Raises `ValidationError` if the job's status is not in `BILLABLE_JOB_STATUSES = {APPROVED, IN_PROGRESS, WORK_COMPLETE, COMPLETED, CANCELLED}`. `CANCELLED` is included so a job stopped early ("stop and bill") can still be invoiced for work done. See "Agreement-line references and seeding" above. |
| `send_all_atoms(invoice)` | One-click "send all": one new line item per `available` atom in the pool. Claimed atoms are skipped, so it composes with existing lines — unlike `seed_all_atoms` (the fresh-document "Apply everything"), which requires an empty invoice. `POST /api/invoices/{id}/send-all-atoms/` → `{'created': N}`; the wizard's "Send all to Invoice" button. |
| `get_source_pool(invoice)` | Returns `{'tasks': [...]}` — a group per real Task on the job (cancelled included since 2026-07-12, plan C3), plus three synthetic groups appended in order: "Materials (no task)" for task-less materials with `quantity > 0`, "Expenses" for material-less, non-rejected `Expense`s on the job, and — only when at least one qualifying line exists (see "Deposits" → "The credit atom" below) — "Deposit credits" for unclaimed deposit lines on `paid` invoices of this job. Each atom carries `type`/`id`/`description`, the `qty`/`rate`/`units`/`amount` breakdown (from the shared `BaseWizardService._atom_detail`), state (`available` / `claimed_by_current` / `claimed_by_other`), and (for claimed atoms) the claiming line item or invoice. **Terminal — not complete — is the task billability line**: `complete` and `cancelled` tasks are billable (the same doctrine that keeps cancelled *jobs* in `BILLABLE_JOB_STATUSES`); anything else is `not_billable` (`task_incomplete`). A cancelled task's atom carries `task_cancelled: true`; `InvoiceEditView`'s `UncoveredWorkSection` renders it as an amber "cancelled — work done" chip so the biller makes a conscious choice (§"Uncovered-work section chips" below); a cancelled task with zero actuals is simply a $0 row. Task and material atoms also carry `struck_from_agreement` (`task.descoped_by_id is not None`, `and task.status != CANCELLED` for tasks; no suppression clause for materials) and `descoped_by_co_number` (`atom.descoped_by.change_order_number`, else `None`) — both read straight off the **stored** `descoped_by` stamp (§ "Uncovered-work section chips" below; rewritten 2026-08-09, CO amend-in-place — previously `struck_from_agreement` was derived per pool build via the now-deleted `ChangeOrderService.struck_atom_keys(job)`), rendered as an amber "descoped by {coShortLabel}" chip; suppressed on cancelled tasks (one prompt suffices). `.select_related('descoped_by')` on the per-job Task/Material querysets keeps this N+1-free. See estimates-and-prices §14.11 for the acceptance-time mechanics. The *estimate* pool is the opposite — cancelled tasks are excluded there (estimates project planned work). Atom keys are normalized to match the estimate wizard so the same pool shape feeds both surfaces. |
| `add_atoms_to_new_line_item(invoice, atoms)` | Creates a new `InvoiceLineItem` plus N `InvoiceLineItemSource` rows in one transaction. Defaults table below. |
| `add_atoms_to_line_item(line_item, atoms)` | Appends source rows. Recomputes per the in-sync rule. |
| `remove_atoms_from_line_item(line_item, source_ids)` | Removes the matching source rows. Recomputes per the in-sync rule. Returns `{'line_item_deleted': bool}`. If the removal empties the source list, the line item is hard-deleted (via `LineItemService.delete_line_item_with_renumber`) regardless of override state. |

`InvoiceService.discard_draft(invoice)` is the discard path — validates draft status, then hard-deletes the invoice (cascade frees all claimed atoms).

### Copy from estimate (`copy_from_estimate`)

`InvoiceService.copy_from_estimate(invoice)` (`POST /api/invoices/{id}/copy-from-estimate/`) seeds a fresh draft invoice from the job's **accepted-estimate agreement** (`compose_agreement(invoice.job)`) — one `InvoiceLineItem` per agreement line (description, qty, price, units, accounting_category; adjustment lines also carry `adjustment_service` + target categories). Preconditions (else `ValidationError`): the invoice is `draft`, has no existing line items, and is the only non-cancelled invoice for the job (i.e. it's the first invoice).

**No fee-claim-on-copy (removed 2026-08, fee-removal Task 3).** The
`source_fee_id` agreement channel is gone: `compose_agreement` line dicts no
longer carry the key, and `copy_from_estimate` writes **no**
`InvoiceLineItemSource` rows of any kind — a legacy `SOURCE_FEE` row on an
estimate/CO line no longer transits into an invoice fee claim on copy.

**Predates, and is distinct from, `seed_from_agreement` (2026-08).**
This method does **not** write `agreement_estimate_line`/
`agreement_co_line` refs — its output
lines carry no `agreement_ref`, get no est-vs-actual reference, support
no Restore, and read `backing: null`/`edited` rather than
`estimate`/`actuals`. It survives today only as the "Copy from
estimate" button's backing call for the now-rare case of a draft with
zero lines under auto-seeding — see "Agreement-line references and
seeding" above for the mechanism that actually seeds new invoices by
default.

### Defaults when bundling N atoms into a new line item

| Case | Description | Units | Qty | Price | Accounting category |
|---|---|---|---|---|---|
| Single atom | Atom's name/description | Atom's units (rate scheme unit, or PLI units, or `'none'`) | Atom's intrinsic qty (`Material.quantity`; an ENTERED_QTY task's actual qty; `1` for ELAPSED_TIME tasks) | Atom-derived (`Material.sell_price`; an ENTERED_QTY task's `effective_rate()`; the blep roll-up total for ELAPSED_TIME) | Atom's effective category |
| Multi-atom — uniform task bundle | `''` (UI prompts user to name) | Rate scheme `unit_label` | Summed actual quantities | Common effective rate | Uniform-or-null |
| Multi-atom — anything else | `''` (UI prompts user to name) | `'none'` | `1` | Sum of atom amounts | Uniform-or-null (set if all atoms share one category) |

A multi-atom bundle is a "uniform task bundle" when every atom is a Task
sharing one `RateScheme` and identical `active_modifiers`. `add_atoms_to_line_item`
/ `remove_atoms_from_line_item` re-derive the same way on an in-sync line
item (re-summarize a uniform bundle, else keep qty and recompute the
per-unit price).

The line's taxability is whatever `accounting_category.taxable` says at push time (no per-line override field exists — removed 2026-07-21).

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

The invoice detail view lives at `#/jobs/:jobId/invoice[/:docId]` →
`JobInvoicePage.svelte` (`frontend/src/routes/jobs/`), which hosts
`InvoicePanel.svelte` (`frontend/src/components/invoices/`) inside the
job workspace shell (`JobShell` — header + nav rail + collapsible
context band; see `jobs-and-tasks.md` §9.6). The bare
section route restores whichever invoice the user last viewed for this
job (or the latest); picking a different invoice via the panel's
subnav (`DocSubnav.svelte`, one pill per invoice with a status badge)
updates the URL to `/:docId` in place — no remount, no job refetch. The
old `#/invoices/:id` route still works: `InvoiceDetailPage.svelte` is
now a small redirect shim into the job-scoped URL.

**Retired 2026-08 (skeleton + three-mode surface).** The old two-mode
(`'lines'`/`'reconcile'`) panel and the two-column `ReconcileMode.svelte`
atom-pull wizard it rendered in place are **gone**, along with
`WizardSourcePool.svelte`, `WizardLineItemCard.svelte`, and
`WizardActions.svelte`. In their place: `InvoicePanel` renders a
`DocModeBar` (three buttons, **Edit** / **Customer** / **Reorder**,
`aria-pressed` on the active one) that flips its `mode` in place at the
same URL — never a navigation, never a remount. **Edit** mode renders
`InvoiceEditView.svelte` (`frontend/src/components/invoices/`) — one
merged surface combining what used to be the separate lines view and
reconcile mode: the line-items table (each row's atom claims and
backing nested inline) plus an uncovered-work pool below it. **Customer**
and **Reorder** modes render the shared `docsurface/DocCustomerView.svelte`
/ `DocReorderView.svelte` — the collapsed, read-only document (Customer)
or the same rows plus an arrows column (Reorder). All three modes, and
the equivalent estimate-side surface, are built from one shared
`docsurface` component kit — see `estimates-and-prices.md` §12 for the
estimate side (which documents the kit's shared vocabulary in full) and
`architecture-and-conventions.md` §5.5b for the kit's cross-cutting
conventions.

The old route `#/invoices/:id/wizard` is still a redirect shim
(`InvoiceWizardRedirect.svelte`), but it now remembers **`'edit'`** mode
for that invoice (`rememberMode`, `stores/jobWorkspace.js`) before
bouncing to the job-scoped URL — old wizard bookmarks land on the merged
Edit view. **Mode persistence and normalization** work exactly as on
the estimate side (`estimates-and-prices.md` §12 intro): the store keeps
whatever was written, unmigrated; the read site (`InvoicePanel`) folds a
remembered `'lines'`/`'reconcile'` to `'edit'`, and falls a remembered
`'reorder'` back to `'edit'` if the invoice is no longer editable
(`canEditLineItems = can_manage_financials && status === 'draft'`).

`InvoicePanel` (formerly `InvoiceDetailPage.svelte`'s inline logic) is
the standard detail view of an invoice. It shares the same **JobHeader**
band (via `JobShell`) as every mode — same page, same shell. On
`draft` invoices, users with `can_manage_financials` can add, edit,
delete, and reorder line items (Edit mode for add/edit/delete, Reorder
mode for reordering).

**Adding a line item** (2026-07-25 — adopted the estimate flow) opens
`PriceListPicker.svelte` (shared with the estimate/CO add-line paths),
which offers **services**, **inventory** (catalog PLIs), and **manual**
entry. `PriceListPicker` carries no surface-specific logic (task/estimate
surfaces are unaffected) — deposits are no longer created through it (see
below). The picked choice is handed to `InvoiceAddLineForm.svelte`, which
POSTs the right shape per choice: `{inventory_item, qty}` (from-PLI, copies
description/units/selling_price/accounting_category), or `{service_item,
qty}` (from-service — see below). `LineItemModal.svelte` (the modal
shared with the estimate panel) is **edit-only** on invoices now —
opening it always starts in `modalMode = 'edit'`; there is no longer a
manual/from-inventory toggle inside it on the invoice surface. Editing an
existing line item edits its fields only.

**Ad-hoc service billing** (`POST /api/invoices/{id}/line-items-from-service/`,
`InvoiceService.add_line_item_from_service`) is the invoice-only "From
Price List → service" pick: it snapshots `description` (the
`ServiceItem.template_name`), `units`, `price`
(`RateScheme.effective_rate(service_item.default_active_modifiers)` —
the *default*-modifier rate, not a live-editable modifier set), and
`accounting_category` straight onto a plain `InvoiceLineItem` — no
`Task` is created and no `InvoiceLineItemSource` row is written. This is
a pure billing line for work done outside the app that still needs
invoicing (no job side effects, no actuals tracking); it is distinct
from the atom-pull wizard, which always bills a real Task/Material/
Expense/deposit atom.

**"Show Billables" is retired** — there is no separate button to reach the
job's uncovered work anymore; `InvoiceEditView`'s `UncoveredWorkSection`
(§"Backing model" below) is always part of Edit mode, visible to any
`canEdit` user on a `draft` invoice regardless of whether the job has
billable atoms (an empty pool renders `emptyText`, never a hidden
section).

On `open` or `partly-paid` invoices a disabled **"Revise (coming soon)"** placeholder button appears in the toolbar — invoice revision is not yet implemented.

### Discard

`DELETE /api/invoices/{id}/` calls `InvoiceService.discard_draft`, which validates draft status and hard-deletes. The viewset returns 200 with `{'message': 'Invoice discarded'}` per the project's all-DELETE-returns-JSON convention. There is no two-phase confirmation on this endpoint (the wizard owns the confirmation in the UI; cascade impact is implicit — all claimed atoms become free).

---

## Backing model

**Design authority:** `docs/plans/2026-08-06-better-fees.md` §7.3
("actuals by default") and §9.2 (the chip vocabulary). Every invoice
line carries a **backing** — what its amount currently stands on —
rendered as the "Backing" column's `BackingChip`. Both fields below are
`SerializerMethodField`s on `InvoiceLineItemSerializer`
(`apps/api/invoicing/serializers.py`) — **never stored**, recomputed on
every read from the line's own state.

### `agreement_ref`

`null`, or `{kind: 'estimate'|'change_order', line_id, est_qty,
est_price, est_amount}` sourced from the referenced agreement line's own
stored qty/price (`_agreement_ref_payload`) — never from the invoice
line's current values, so it stays a stable comparison point as the
invoice line is edited. All four numeric values are **stringified
explicitly** (not left to DRF's default JSON encoding of a bare
`Decimal`, which falls back to `float()`): an un-stringified payload
would silently ship floats, breaking the frontend's string-equality
"synced" check and 400ing a PATCH that sends one straight back as
qty/price (`DecimalValidator` rejects most floats' imprecise binary
expansion).

**CO-line provenance (2026-08-09).** When `kind == 'change_order'`,
`_agreement_ref_payload` additionally sets `co_number`
(`ref.change_order.change_order_number`) and `co_line_number`
(`ref.line_number`) — omitted for an estimate-origin ref. Kept N+1-free
by the existing `agreement_co_line` select_related/prefetch on
`LineItemMixin._get_line_items_qs` and `InvoiceViewSet.get_queryset`
extending one hop further to `change_order`. On the frontend,
`frontend/src/lib/agreementReference.js` exposes `coShortLabel(number)`
(derives `"CO-1"` from the trailing `-CO<n>` suffix, null-safe) and
`estReferenceText(li)` — for a CO-origin ref this reads as pure
provenance, `"{coShortLabel} line {co_line_number}"` (spec §9.3
"CO-N line M"), with **no** "est was $X" value-drift clause (that
clause is estimate-origin-only, unchanged — see the est-reference
caption below).

### `backing`

One of `'deposit'` / `'deposit_credit'` / `'actuals'` / `'estimate'` /
`'edited'` / `null`, via the module-level `derive_backing(line)`
function (written duck-typed — the CO surface will reuse it for
`ChangeOrderLineItem` too). In order:

1. `is_deposit_line` → `'deposit'`; `is_deposit_deduction` →
   `'deposit_credit'` (see "Deposits" below).
2. Has claimed source rows **and** is in sync with them (the existing
   wizard rule — `price == round(sum(sources) / qty, 2)`) →
   `'actuals'`.
3. Has an `agreement_ref` **and** qty/price still equal the ref's stored
   qty/price → `'estimate'`.
4. Has an `agreement_ref` or sources, but matched neither rule above
   (hand-edited since seeding, or a claimed-but-out-of-sync line) →
   `'edited'`.
5. Otherwise (a plain hand line) → `null`.

A seeded backed line therefore arrives already on `'actuals'` whenever
its work is ready (§"Agreement-line references and seeding" above) —
the boring case is read-and-send. `actuals_total` is a third field: the
sum of `compute_amount()` over the line's claimed work atoms, `null`
when there are none — independent of `backing` itself, so an
out-of-sync `'edited'` claimed line still reports its actuals total as
the est-vs-actual reference figure. (A `SOURCE_DEPOSIT` claim resolves
to another `InvoiceLineItem`, not a work atom with `compute_amount()`,
so it's skipped in the sum, same as a dangling/unresolvable source.)

The list/retrieve queryset prefetches `sources` and
`select_related('agreement_estimate_line', 'agreement_co_line',
'accounting_category')` to keep all three fields N+1-free.

### Chip labels (`docsurface/BackingChip.svelte`)

`estimate` → "estimate", `actuals` → "actuals" (or **"actuals =
estimate ✓"**, class `synced`, when `syncedWithEstimate` — the invoice
side's own check: `backing === 'actuals' && actuals_total ===
agreement_ref.est_amount`), `edited` → "edited", `deposit` → "deposit",
`deposit_credit` → "deposit credit". (The estimate-only enum values —
`planned_work`/`planned_materials`/`from_catalog`/`hand`/`adjustment` —
live in `estimates-and-prices.md` §12.2.) `null` renders nothing.

### Est-reference caption and backing controls (`InvoiceEditView`)

Under the Backing chip, a line with an `agreement_ref` shows a small
reference caption, via `estReferenceText(li)`
(`frontend/src/lib/agreementReference.js`) — the text differs by the
ref's origin:

- **Estimate-origin**: `"est was {fmtMoney(est_amount)}"`, followed by
  `" · {sign}{fmtMoney(delta)}"` when `delta = current − est_amount` is
  nonzero (`current` = `actuals_total` if claimed, else the line's own
  current amount) — e.g. `"est was $500.00 · +$25.00"`. The `· +$Δ`
  clause is suppressed entirely at `delta === 0` (`fmtMoney(0)` renders
  `'-'`, the shared "no amount" sentinel — showing the clause there
  would print the nonsense `"· +-"`).
- **CO-origin (2026-08-09)**: pure provenance, no value comparison —
  `"{coShortLabel(co_number)} line {co_line_number}"` (e.g. `"CO-1 line
  3"`) — which document and line this invoice line was seeded/restored
  from. A CO-origin line's whole point is that it's freshly amended, so
  "what it used to say" isn't the interesting fact; see "Agreement-line
  references and seeding" above and `estimates-and-prices.md` §14.6's
  `estimate_line_id`/`co_line_id` line-identity note.

Two backing controls render conditionally in the Actions cell (while
`canEdit`), alongside the always-present **Edit…**:

| Control | Renders when | Does |
|---|---|---|
| **Use estimate** | `agreement_ref != null && backing !== 'estimate'` | `PATCH .../line-items/{id}/` `{qty: agreement_ref.est_qty, price: agreement_ref.est_price}` — resets the line to the agreement's own stored values |
| **Use actuals** | `(backing === 'estimate' \|\| backing === 'edited') && actuals_total != null` | `PATCH .../line-items/{id}/` `{price: round(actuals_total / qty, 2)}` — re-derives the per-unit price from claimed actuals |

Both are ordinary field PATCHes — no dedicated endpoint — so "Edit…"
(the full field-edit modal, `LineItemModal`) always remains available
as the general escape hatch; editing price by hand there is what drives
a line to `'edited'` (rule 4 above) when it doesn't happen to land back
on the estimate's exact values.

**Attachment recalculates immediately** (design doc §7.3 — reversing an
earlier "attachment never moves money" position): claiming or releasing
an atom (`add-atoms`/`remove-atoms`, or an atom from the uncovered-work
pool) re-derives an in-sync line's price on the spot via the existing
wizard in-sync rule, so the invoice total visibly moves the moment work
attaches — attachment IS a billing decision, reversible by detaching or
by **Use estimate**.

### Uncovered-work section chips

`InvoiceEditView`'s `UncoveredWorkSection` (title "Uncovered work") is
fed from `GET .../source-pool/`, flattened and filtered to atoms not
already claimed by this invoice (`claimed_by_current` rows are the
`AtomChildRow` nests above, not pool rows) and excluding the "Deposit
credits" group (its own section — below). Each row's optional `chip`
prop (`UncoveredWorkSection`/`AtomChildRow`'s generic `{label, cls}`
shape, kit Task 9) surfaces provenance the pool already computes
server-side — `atomChip()` in `InvoiceEditView.svelte`, in precedence
order:

1. `state === 'claimed_by_other'` → **"invoiced — {invoice number}"**
   (class `invoiced-elsewhere` — no dedicated `app.css` rule; falls back
   to the base grey `.backing-chip` look). Wins over the other two even
   when they'd also apply — a cancelled task already claimed on another
   invoice is uninteresting to bill *here*.
2. `task_cancelled` → **"cancelled — work done"** (reuses the `edited`
   chip class/tan color) — the terminal-not-complete billability
   doctrine (§"Atoms — same Job atoms as the estimate" above): a
   cancelled task's recorded actuals are still real, billable work, but
   the invoicer must consciously choose to bill it rather than have it
   fold into an undifferentiated row.
3. `struck_from_agreement` → **"descoped by {coShortLabel}"** (same
   `edited` class; `coShortLabel`, `frontend/src/lib/agreementReference.js`,
   derives `"CO-1"` from the trailing `-CO<n>` suffix of a
   `change_order_number`) — an accepted CO's `remove` line targeted the
   estimate line that used to claim this atom, but the atom
   itself was left alone (complete task, consumed material — see
   `estimates-and-prices.md` §14.11's REMOVE step). Server-side the flag
   is `task.descoped_by_id is not None` / always-true-when-set on a
   Material (no suppression clause there); `descoped_by_co_number`
   (`task.descoped_by.change_order_number` /
   `mat.descoped_by.change_order_number`) is what feeds the chip's label
   — both stamped **once, at CO acceptance**
   (`ChangeOrderAcceptanceService`'s REMOVE loop), never derived at read
   time. A **replace** target is never stamped — replace moves the claim
   onto the CO line instead of descoping the atom, so a replaced task/
   material never carries this chip. Suppressed on a task that's also
   `task_cancelled` (one amber chip is a prompt, two is noise).
4. No chip when none of the above apply — an unmarked row means nothing
   special (positive-only marking, design doc §7.3): a hand-line
   agreement legitimately covers work with no task-level claim.

A `unselectableNote` (plain text, not a chip) additionally explains why
a `claimed_by_other` or `not_billable` row's checkbox is disabled:
`"Invoiced on {invoice number}"`, `"Task not complete yet"`, or
`"Material not yet consumed"`.

---

## Invoice adjustment lines

Percentage adjustments (rush surcharges, volume discounts, etc.) can be added
as `InvoiceLineItem` rows backed by a `PERCENTAGE` `RateScheme`. The
mechanics mirror the estimate side exactly — see
`docs/designs/estimates-and-prices.md` §2.2 and §5.3b for the
`compute_adjustment_amount` helper and the `percentage` algorithm semantics.

### Service methods

**Auto-recompute:** Adjustment lines recompute automatically on every line-item
mutation — `add_line_item`, `update_line_item`, `delete_line_item`,
`add_line_item_from_pli`, and `add_adjustment_line`. There is no manual
recalculate step. Freeze is implicit: all mutations are draft-gated, so once
an invoice leaves `draft` the stored price is frozen automatically.

`InvoiceService` (`apps/invoicing/services.py`) provides:

| Method | Behavior |
|---|---|
| `add_adjustment_line(invoice, *, adjustment_service_id, target_category_ids=[])` | Creates a new `InvoiceLineItem` backed by a PERCENTAGE `RateScheme` at the end of the invoice's line list, calls `_recompute_adjustments`, and returns the saved line. Raises `ValidationError` if the invoice is not `draft` or the service is not `PERCENTAGE`. |
| `_recompute_adjustments(invoice)` | Internal helper. Calls `recompute_adjustments()` over all `InvoiceLineItem` rows for the invoice. Called after every line-item mutation. |

### API endpoints

| Verb + path | Behavior |
|---|---|
| `POST /api/invoices/{id}/adjustment-lines/` | Body: `{adjustment_service: <PK>, target_category_ids: [<AC PKs>]}`. Returns 201 with the serialized line item (price already computed). Returns 400 if not draft or service is not PERCENTAGE. Permission: `CanManageFinancials`. |
| `GET /api/invoices/{id}/agreement-adjustments/` | Returns `{adjustments: [{adjustment_service_id, description, percent, target_category_ids, already_added}, ...]}` — the adjustment lines from the job's accepted-estimate agreement (via `compose_agreement`), annotated with whether this invoice already has a matching adjustment line. This endpoint is **path-independent**: it reads the agreement, not the wizard atom pool, so it works regardless of how line items were added. Permission: `CanManageFinancials`. |

### Agreement-adjustments panel (invoice wizard / detail page)

`frontend/src/components/invoices/AgreementAdjustmentsPanel.svelte` is
rendered on the invoice detail page when the invoice is `draft` and the job
has a composed agreement with adjustment lines.

On mount it calls `GET /api/invoices/{id}/agreement-adjustments/` and
renders each returned entry as a row: description, percent label, and an
**Add** button (disabled, labeled "Added", when `already_added` is true).
Clicking Add calls `POST /api/invoices/{id}/adjustment-lines/` with the
entry's `adjustment_service_id` and `target_category_ids`, then reloads the
panel. The panel only renders when at least one adjustment exists — it is
hidden while the list is empty or loading.

The panel surfaces agreement adjustments through the agreement composition
layer, not through the wizard atom pool. This means it works on `draft`
invoices that were created either through the wizard or directly, and
regardless of which line items have already been added.

---

## Deposits

A deposit is a non-taxable charge collected before work starts, covering
no atoms — the shop typically does no work until it's paid (the money
buys materials). A paid deposit is later deducted **in full** from
exactly one subsequent invoice on the same job. Full design rationale:
`docs/plans/deposit-invoices-spec.md` (2026-07-25).

### What makes a line a deposit line

**The accounting category is the deposit indicator, not a stored flag on
the line or the invoice.** `AccountingCategory.is_deposit` (BooleanField,
default `False`; see `data-constraints.md` §1.3) is the one source of
truth:

- `InvoiceLineItem.is_deposit_line` — `True` when the line's
  `accounting_category.is_deposit` is set **and** the line carries no
  `InvoiceLineItemSource` row with `source_type='deposit'` (i.e. it's a
  charge, not a deduction of one).
- `InvoiceLineItem.is_deposit_deduction` — `True` when the line **does**
  carry such a source row.
- **An invoice *is* a deposit invoice iff it contains a deposit line**
  (`InvoiceSerializer`/`InvoiceSummarySerializer.get_is_deposit`: `any(li.is_deposit_line for li in ...)`).
  Nothing is stored on `Invoice` itself.

Both properties iterate `self.sources.all()` (never `.filter()`) so a
`prefetch_related('invoicelineitem_set__sources')` on the parent Invoice
queryset actually serves them (`InvoiceViewSet.get_queryset` prefetches
`invoicelineitem_set__sources` and `__accounting_category` on the
detail/list-non-summary path for exactly this).

Because deposit-ness is derived from the category, **draft-time
recategorization is coherent editing, not corruption**: a manual line
hand-assigned a deposit AC *becomes* a deposit line with no special
handling, and re-categorizing it away un-does that — line CRUD is
draft-only, so everything load-bearing (the board pill from a *sent*
invoice, the credit atom from a *paid* one) always reads frozen lines.
Mixing is legal: a deposit line may coexist with ordinary lines on one
invoice; the invoice still gets the deposit pill, and the deposit line
still becomes a credit atom once the whole invoice is paid. Multiple
deposits per job (and even multiple deposit *categories*) are legal —
each paid deposit line is its own credit atom.

### Category invariants (enforced on `AccountingCategory`, not the line)

- **Non-taxable by construction:** `is_deposit=True` requires
  `taxable=False` — `AccountingCategory.clean()` raises
  `ValidationError({'is_deposit': [...]})` otherwise. (`taxable_override`
  no longer exists — see the `taxable` row change note above — so this is
  the only taxability lever for a deposit category, and the QBO push
  derives `TaxCodeRef` from it directly.)
- **Targeted freeze once referenced:** `ConfigurationService.FROZEN_WHEN_REFERENCED
  = ('taxable', 'is_deposit')`. Once `AccountingCategory.is_referenced()`
  is `True` (any line item, expense, inventory item, material, rate
  scheme, **or `adjustment_target_categories` M2M** points at it —
  the M2M coverage was a 2026-07-25 fix; a category referenced *only* as
  an adjustment target used to report `is_referenced() == False`),
  `ConfigurationService.update_accounting_category` refuses to change
  either field, coaching "retire this category and create a replacement
  instead." Name, code, and QBO mappings stay editable on a used category
  (a QBO reconnect must still be able to remap them). This is a
  *targeted* freeze — full `AccountingCategory` immutability/supersession
  (RateScheme-style) is a separate future effort, tracked in
  `docs/designs/LATER.md`.

### Creating a deposit line

`POST /api/invoices/{id}/line-items/` (the `LineItemMixin` manual-line
endpoint) with `deposit: true` in the body. `InvoiceService.add_line_item`
sees the flag and stamps `accounting_category` server-side from the
`default_deposit_accounting_category` Configuration key (§1.1 in
`data-constraints.md`) — resolved by `InvoiceService._resolve_deposit_category()`,
which raises a field-keyed coaching `ValidationError` on
`accounting_category` ("No default deposit accounting category is
configured...") if the key is unset, or if it points at a category that
no longer exists, is inactive, or isn't a deposit category. Amount and
description are user-entered; the frontend prefills description
`"Deposit on {job_number}"`. This is draft-only, like all line CRUD (a
manual line hand-assigned a deposit AC is equally a deposit line — same
semantics, no special-casing). This contract is unchanged by the Task 21
frontend rework below — only the entry point moved.

**Frontend (Task 21, 2026-07 — replaced the picker's Add Deposit entry;
refined 2026-07-26 into three states):** `InvoicePanel.svelte` offers a
deposit-creation action whose presence and label are derived from the job's
own `invoices` list — no separate fetch is needed, since `InvoicePanel`'s
`GET /api/invoices/?job=` call carries no `?summary=` param, so every entry
is the full `InvoiceSerializer` (nested `line_items` included, same shape
as the single-invoice GET):

1. **No draft on the job** → **"Add Deposit Invoice"**, placed next to
   **Start Invoice** in the empty state, and next to the version bar's
   **+ New invoice** trailing action once the job has (non-draft) invoices.
2. **A draft exists with zero line items** → relabels to **"Make this a
   deposit invoice"** (same version-bar placement). The button stays
   offered because `InvoiceWizardService.open_for_job` is idempotent — see
   step 1 below — so Create simply adds the deposit line to that existing
   empty draft.
3. **A draft exists WITH line items already** → the action is **suppressed
   entirely**, in both placements — "mixing" a deposit line with ordinary
   lines on one invoice is legal (see below), it's just no longer offered
   as a *fresh* deposit-invoice starting point once the draft has any
   content.

**Deposit→progress relabel (spec §7.2, landed 2026-08-09):** once the job
carries a **live invoice** — any status but `cancelled`, mirroring the
backend's `LIVE_INVOICE_STATUSES`; the zero-line draft the modal would
convert doesn't count, since converting it is still the job's first
advance — states 1 and 2 swap their wording to **"Add Progress Invoice"**
/ **"Make this a progress invoice"**, and the modal retitles and prefills
the line description **`"Progress billing on {job_number}"`** instead of
`"Deposit on {job_number}"`. Words only: a progress billing *is* a
deposit taken mid-job, so both variants run the identical two-step create
below (unseeded draft + deposit-rail line) and no invoice type is stored
(`InvoicePanel`'s `depositVariant`, passed to the modal as `variant`).

**Agreement machinery withheld on a deposit invoice (RM 2026-08-09):** in
`InvoiceEditView`, an invoice whose lines are **all deposit lines** (≥1;
derived per render from the line serializer's `is_deposit` — content,
never a stored type, per the no-invoice-mode principle) hides the
**Uncovered work** pool and the **Add from agreement…** picker button —
advance money bills against the job as a whole, never against atoms. A
mixed invoice (deposit line alongside ordinary lines) keeps both
offerings. The Deposit credits section is unaffected.

All three states share Start Invoice's gates (`jobBillable`,
`job.can_manage`) and, in states 1/2, are additionally disabled with a "Set
a deposit category in Settings first" title when `hasDepositCategory` is
false (no active deposit category exists — same `categories` check as
before, loaded independent of `invoiceId` so it's available in the empty
state too).

Clicking it opens `DepositInvoiceModal.svelte` — a single **Amount** field
(client-validated `> 0` via a `FieldError` slot) plus Create/Cancel. On
Create it does a two-step sequence:

1. `POST /api/invoices/` `{job, seed: false}` — the same call
   `InvoicePanel`'s Start Invoice makes, **plus** the `seed: false` opt-out
   (§"Agreement-line references and seeding" above — added 2026-08 when
   invoice creation started auto-seeding by default). Without it, a fresh
   deposit draft on a job with an agreement would arrive pre-populated
   with agreement lines the invoicer isn't billing yet, defeating the
   point of "Make this a deposit invoice." `InvoiceWizardService.open_for_job`
   is idempotent: if the job already has an open draft, it returns that
   draft instead of erroring (and never re-seeds it, seed flag or not),
   so state 2's button is safe to offer — the deposit line lands on the
   existing draft, seeded or not.
2. `POST /api/invoices/{id}/line-items/` `{deposit: true, description:
   "Deposit on {job_number}", qty: '1', units: 'none', price: amount}` —
   the same deposit line-item contract described above.

**Post-create freshness:** `InvoicePanel` compares the returned invoice id
against the currently-viewed `invoiceId`. If the user was already viewing
the draft that just received the line (state 2, triggered from that
draft's own page), the panel calls `loadInvoice()` to reload it **in
place** — the established convention (same as `handleLineAdded`'s reload
after any other add-line save), not a full page refresh. Otherwise (state
1's brand-new draft, or state 2 triggered from a different document) it
navigates to the draft via `window.location.hash`, same as Start Invoice.
Either path also reloads the job's `invoices` list so the three-state gate
above reflects the new line count immediately.

Errors route through `triageError`: an overlay-worthy failure (5xx, no
JSON body) goes to the global overlay; a field-keyed/`detail` failure from
step 1 renders on the modal's own `FormMessage`/`FieldError` (the invoice
was never created, so there's nothing else to show). A step-2 failure
(e.g. the deposit-category coaching message) is different: **the draft
already exists** at that point, so the modal still resolves the draft (in
place or via navigation, per the freshness rule above) and surfaces the
coaching text via the global overlay instead of a form message on a modal
that's about to close — the user can fix the Settings config and add the
deposit line by hand afterward.

### The credit atom (invoice wizard source pool)

`InvoiceWizardService.get_source_pool` adds a **"Deposit credits"** group.
Unlike the other pool groups (which always render, showing a "(no billable
items)" placeholder when empty), this group is emitted only when at least
one qualifying line exists — jobs with no deposit history get no
placeholder row. Its `has_billable_atoms` is presence-based
(`len(atoms) > 0`), matching the other groups' formula, so a fully-claimed
credit still renders its row with the claimed marker. A line qualifies
when:

- it's a deposit line (deposit-category AC, no deposit-source row);
- on an invoice that is `paid` (`Invoice.STATUS_PAID`) — **you can't
  deduct money you don't hold**, so `open`/`partly-paid` deposits never
  offer a credit;
- on the **same job** as the invoice whose pool is being built;
- with **no live claim** — a claim from a *cancelled* invoice doesn't
  count (and since 2026-07-28 no such row survives cancellation anyway).

Pulling the atom (`type: 'deposit'`) creates the deduction line via the
normal atom-pull endpoints (`line-items-from-atoms`/`add-atoms`), with
deposit-specific rules enforced by `InvoiceWizardService._assert_deposit_atom_rules`:

- **No bundling** — a deposit credit must be pulled as its own line (not
  combined with other atoms, and nothing can be appended to a deduction
  line afterward: `'A deposit deduction line cannot take other atoms.'`).
- **Same-job only** — pulling a deposit whose invoice belongs to a
  different job raises `'A deposit can only be deducted on its own job.'`
- **Locked, unsplittable amount** — the deduction's `qty` is `1` and its
  `price` is the deposit line's **full total, negated**
  (`(-li.total_amount).quantize(Decimal('0.01'))`); qty/price/AC edits on
  a deduction line are rejected (see the "Not a deposit line" /
  "can only be deducted once its invoice is paid" guards in
  `InvoiceWizardService._assert_atom_billable`).
- **Description default:** `"Less deposit ({deposit invoice's display_number})"`
  (e.g. `Less deposit (INV-1042)`), editable like any line description.
- **Accounting category:** copied from the source deposit line.
- **Source row:** `InvoiceLineItemSource(source_type='deposit',
  source_pk=<deposit line pk>)` — the whole-atom unique constraint on
  `(source_type, source_pk)` is what makes the claim unsplittable; a
  second pull attempt on the same deposit line raises `ClaimConflict` →
  409 `atoms_already_claimed`, exactly like a Task/Material/Expense
  double-claim.

Deleting the deduction line (`delete_line_item_with_renumber`, as
always), discarding its draft invoice, or cancelling its invoice releases
the claim — the credit returns to the pool (modulo the cancelled-claims
caveat in `docs/designs/LATER.md`: the source row survives cancellation,
so the pool's *display* frees the credit but a stale row still exists at
the DB level). A deposit line never appears in the pool as a *billable*
atom — it covers no work — only ever as a credit.

**seed-all-atoms / send-all-atoms deliberately pull deposit credits too**
— they're ordinary available atoms in the pool, same as any Task/
Material/Expense, so "Apply everything" / "Send all to Invoice" will
include an outstanding deposit credit on the same job without special-
casing it.

### `DepositCreditsSection` — a dedicated one-click picker (2026-08)

`InvoiceEditView.svelte` re-homes the credit-pull gesture as
**`DepositCreditsSection`** — an inline section (not a separate
component file; not part of the shared `docsurface` kit, since it's
invoice-only) rendered while `canEdit` and only when the pool's
"Deposit credits" group has at least one `available` atom. Each row
shows the credit's description (+ an optional sub-info line), amount,
and a single **"Apply to this invoice"** button (busy label "Applying…")
— `POST .../line-items-from-atoms/` `{atoms: [{type: 'deposit', id}]}`,
the same endpoint the generic uncovered-work "Add selected here" flow
uses. Deliberately **not** the checkbox-then-merge object-first gesture
the rest of Edit mode uses: pulling a credit is a distinct act (a
deduction against money already collected, not a claim on job work), so
it gets its own section and a direct one-click action instead.

**Parked for RM (design call, not yet resolved as of this writing):**
`InvoicePanel` **also** still renders its own pre-existing top-of-panel
**"Unapplied deposit credit"** banner (§"Unapplied deposit credit"
below) — a second, independently-derived "credit available" surface.
The two currently coexist with different derivations (the banner is
client-side math over the job-scoped `invoices` list,
`lib/depositCredits.js`; `DepositCreditsSection` reads the server's
`GET .../source-pool/` "Deposit credits" group) and different gestures
(banner: `applyDepositCredit` in `InvoicePanel`; section: the same-named
function local to `InvoiceEditView`, posting the identical payload
through its own state/`onChanged` callback). A 2026-08 code review
recommended keeping the banner and dropping the section (or the
reverse); RM has not yet made the call. Do not "fix" this
unilaterally — it's a design decision pending browser review, not a
bug.

### Indicators (all derived, no stored state)

- **Invoices list** (`InvoiceListPage.svelte`): a **DEPOSIT** doc-pill
  next to the status pill, driven by the invoice's serialized `is_deposit`.
- **Job overview `InvoicingBlock`** (`lib/jobOverview.js`): a deposit
  invoice's row label gains `" · deposit"` (`${display_number} · deposit`)
  — it already lists invoices chronologically, so a deposit reads first
  naturally; no separate badge component.
- **Job Board `JobCard.svelte`** (see `jobs-and-tasks.md` §8.5): a
  banner — **"DEP REQUESTED"** while a deposit invoice is `open` or
  `partly-paid`; **"DEP PAID"** once a deposit line is on a `paid`
  invoice with no live claim on it; nothing otherwise (draft deposits,
  fully-consumed deposits). Computed job-wide by
  `BoardService._deposit_states` (one query for `open`/`partly-paid`/`paid`
  deposit lines on the given job ids, one query for live — non-cancelled
  — deposit-source claims against them): with multiple deposits,
  **`'requested'` wins over `'paid'`** — any outstanding request shows.
  Present on every board payload's job rows (Pipeline, In Progress,
  Unpaid, Closed), but only `JobCard.svelte` (Pipeline column cards, and
  the In Progress chip-hover card via `JobChipStrip.svelte`) renders the
  banner today — `UnpaidCard.svelte`/`ClosedCard.svelte` don't. The
  existing manual `on_hold` + "awaiting deposit" reason remains available
  and unrelated to this derived signal.

### Unapplied deposit credit — draft-panel notice + send-time confirm (Task 22, frontend-only)

**This is the "banner" side of the two-surface duplication parked for
RM** — see "`DepositCreditsSection` — a dedicated one-click picker"
above. Both exist in the shipped app today.

The concept is called an **"unapplied deposit credit"** everywhere
user-visible (never "unconsumed" — the wording is deliberate, matching the
RM's terminology). No backend changes: both surfaces below re-derive the
same set the backend's "Deposit credits" pool group computes, client-side,
from data already loaded — `frontend/src/lib/depositCredits.js` exports one
function, `unappliedDepositCredits(invoices)`, used by both surfaces so
they can't drift apart:

- **Candidate:** a line with `is_deposit === true` on an invoice with
  `status === 'paid'` (parity with "on an invoice that is paid" above).
- **Applied (excluded):** any line, on any invoice in the same `invoices`
  array, whose `status !== 'cancelled'`, carries a `sources` entry with
  `source_type === 'deposit'` and `source_pk === ` the candidate's
  `line_item_id` (exact parity with "no live claim" above — a claim from a
  cancelled invoice doesn't count).
- The input `invoices` array is the same job-scoped list `InvoicePanel`
  already loads (`GET /api/invoices/?job=`, no `?summary=` → full
  `InvoiceSerializer`, nested `line_items`/`sources`) and
  `InvoiceSendPage` additionally fetches once (keyed off the loaded
  invoice's `job` id) for the same purpose.

**Part 1 — draft-panel notice + Apply** (`InvoicePanel.svelte`): while
viewing a **draft** invoice, one row per unapplied credit renders above
"Line Items" (boxed banner, same amber "needs a decision" vocabulary as
`JobDetail.svelte`'s `.change-request-banner`): `Unapplied deposit credit —
$<amount> from <source invoice's display_number>` (amount = the credit
line's `qty × price`, formatted `${n.toFixed(2)}` — this file's own money
convention, e.g. `Amount Paid` above; distinct from the shared `fmtMoney`
helper (`lib/taskTotals.js`) the `docsurface` kit and `InvoiceEditView`
use everywhere else, which renders `'-'` for a zero/falsy amount instead
of `$0.00`). The notice
text itself shows to any viewer of the draft; only the **Apply deposit
credit** button is gated on `canEditLineItems` (same permission as any
other line-item mutation). Apply posts
`POST /api/invoices/{draftId}/line-items-from-atoms/` with `{atoms:
[{type: 'deposit', id: <line_item_id>}]}` — the same atom-pull endpoint
`InvoiceEditView`'s own `DepositCreditsSection`/uncovered-work "Add
selected here" use — then reloads the invoice and the job's `invoices`
list; the deduction line appears and the notice row disappears because
the credit is now applied. Errors route through `triageError` to the
overlay (no form here), covering the 409 `atoms_already_claimed` case if
the credit was claimed elsewhere in the interim; the invoices list is
also refreshed on that error path so the notice reflects the new
reality. `InvoicePanel`'s `handleEditChanged` — the callback every Edit-mode
gesture in `InvoiceEditView` fires — also refreshes `invoices`, not just
the single invoice, since `InvoiceEditView`'s own atom-pull gestures
(including its `DepositCreditsSection`) can claim/release a credit too,
and that only shows up in the job-scoped list this banner's derivation
reads.

**Part 2 — send-time confirm** (`InvoiceSendPage.svelte`, not
`InvoicePanel` — the actual `POST /api/invoices/{id}/send/` lives on this
separate route, reached via the panel's Send/Resend link): `handleSubmit`
(the `onSubmit` callback `DocumentSendForm` invokes after its own "Send
this email to `<recipient>`?" confirm) checks
`unappliedDepositCredits(jobInvoices).length > 0` and, if so, interposes a
second `confirm()`: *"There's an unapplied deposit credit on this job —
send anyway?"*. OK proceeds to the send POST; Cancel returns immediately,
leaving `submitting`/`submitError` untouched (the dialog was never
disturbed). No confirm at all when there are no unapplied credits. This is
a **soft guard** — deducting the credit on a later invoice is legitimate;
the point is only that silence isn't the default when money is sitting
unclaimed.

### QBO and the negative-total guard

No new QBO mechanics: the deposit line pushes as an ordinary
`SalesItemLine` (`TaxCodeRef` `'NON'` via its AC — guaranteed by the
category invariant above), and a deduction line pushes as a negative-
amount `SalesItemLine` — legal in QBO. **Nothing in Minibini prevents a
deduction larger than an invoice's other lines** (a negative-total
invoice); QBO itself rejects a negative-total invoice at push time, and
that rejection is accepted as the guard rather than pre-validating
client- or server-side. Revisit if this bites in practice.

### Out of scope (deliberate)

- **Partial/split deduction.** A deposit is claimed whole by one invoice;
  a remaining-balance model is a future effort if a real need appears.
- **Refund/undo of a paid deposit** — cancelling a **paid** deposit
  invoice is out of scope (no refund flow exists); the pool rule is
  *paid* status, so a cancelled deposit invoice's line simply stops being
  offered as a credit. Already-taken deductions are untouched.
- **Any invoice-readiness gate beyond the deposit-line coaching error** —
  standard invoicing works without the deposit default configured; only
  creating a deposit line requires it.

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
     the QBO Invoice **per-line** — one `SalesItemLine` per
     `InvoiceLineItem` in line order, Description verbatim, ItemRef
     from the line's catalog entity (lazily minting QBO Items) or the
     category fallback, per-line TaxCodeRef from
     `accounting_category.taxable`, `CustomerMemo` carrying the job
     reference, BillEmail, and online-payment flags — see
     `docs/designs/quickbooks-integration.md` for the full push
     mechanics. Saves it; stores `qbo_id` **and adopts QBO's
     `DocNumber` as `invoice_number`**; marks the QBO invoice as
     Sent. Logs to `QBOSyncLog`.
   - **If `invoice.qbo_id` is set:** skips the push entirely (this is
     the retry path — the previous version had a bug where retries
     re-pushed and duplicated the QBO Invoice). Backfills
     `invoice_number` from QBO if the row predates the writeback.
   - Fetches the hosted-invoice **payment link**
     (`include=invoiceLink`) and substitutes it wherever the
     `{payment_link}` placeholder appears in the subject/body (the
     placeholder survives the send dialog literally; substitution
     happens at send time).
   - Downloads the QBO-rendered invoice PDF — the only
     auto-attachment (the job-statement PDF was dropped from the send
     2026-07-22; `apps/invoicing/pdf.py` and
     `templates/invoicing/job_statement.html` were deleted 2026-07-23).
   - Calls `OutboundEmailService.send_tracked` with
     `associate_with={'job': invoice.job}` and the QBO PDF attached;
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

QBO renders the invoice PDF (and computes tax; the payment link rides
in the email body via `{payment_link}`). It goes out as an attachment
on *our* outbound email so reply correlation, threading, and the
Email-panel view all work uniformly across Estimate / PO / Invoice.

Configuration keys for the body/subject templates:
`invoice_email_subject_template`, `invoice_email_body_template`
(defaults documented in
`architecture-and-conventions.md` §7.10). The common template
variable set is available, with three **send-time-only** tokens:
`{invoice_number}` / `{document_number}` (aliases; both render
`display_number`) and `{payment_link}` (QBO's hosted-invoice
pay-online URL). All three show literally in the compose dialog and
are substituted during the send itself — the QBO-assigned number and
link don't exist until the push happens, so compose-time substitution
would bake in the draft placeholder (a bug fixed 2026-07-22).

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

- **The job's work is finished.** `work_complete`, or `approved`/`in_progress` with at least one task and every task terminal — the loose-material-stranded case, where a pending task-less material blocked the `work_complete` transition; this unattended path releases those materials (claimed → `released` history, unclaimed → deleted) and walks the job up. Anything else is a no-op: an `in_progress` job with open tasks (a follow-up to send plans/photos, a post-job meeting), a deposit invoice paid before any work starts (task-less job), and `draft`/`submitted` jobs have no finished work at all; a held job never auto-completes either — status changes are blocked while the `on_hold` flag is set.
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
| `stock_pli` / `stock_qty` | FK InventoryItem (inventoried) + Decimal | Stock-receipt mode: an inventoried purchase that bumped QOH. Mutually exclusive with `material`; `amount` is not job-costed (cost-at-consumption). |
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
expense is one of two modes:

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
  require a **terminal** status — `complete` or `cancelled`; Materials require
  `consumed`; Expenses are billable from the moment they are submitted.) See
  `docs/designs/estimates-and-prices.md` §7 for the wizard-pool billability
  rules.

### Status machine

Two parallel tracks branching on `payment_method`.

**Personal:**

```
submitted ──► reimbursed     (batch created — QBO Purchase push owned by the batch)
     │
     └──────► rejected       (terminal; never pushes to QBO)
```

`ExpenseService.reject` only accepts personal expenses in `submitted` status. Rejecting also unwinds any associated Materials: clears their inventory earmark, reverses the ad-hoc PLI receipt, and deletes the Material — refusing if any material is already `consumed` **or claimed by an estimate/change-order line** (deletion doctrine Rule 1: block the upstream event so reject's delete is always of an unreferenced row; remove the claiming line first).

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

`ExpenseService.submit` accepts an optional `new_material={'job_id', 'description', 'quantity', 'price', 'inventory_item_id'}` payload that creates a Material on the expense's job inline:

- Calls `MaterialService.create_on_job(job=..., task=None, ...)` — the material has no parent task. The "Materials (no task)" bucket from the wizard's source pool surfaces these.
- If a `InventoryItem` is provided and `is_inventoried`, calls `InventoryService.receive_ad_hoc_purchase(material)` to record the receipt.
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
| `delete(*, expense, actor)` | Voids the QBO Purchase if `qbo_id` and not in a batch. Hard-deletes the row. (Reimbursed expenses' QBO state is owned by the batch, so this path doesn't void QBO for them.) Reverses a stock receipt's QOH bump — **unless the expense is already `rejected`**, because `reject` reversed it first; without that guard, reject-then-delete double-reversed and drove stock negative (fixed 2026-07-19, mirroring the attach path's already-unwound guard). |
| `reject(*, expense, actor) -> Expense` | Personal + `submitted` only. Unwinds materials (earmark, ad-hoc receipt, delete) — refuses if any material is `consumed` or claimed by an estimate/CO line. Sets `STATUS_REJECTED`. |
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
| Invoice detail (glue) | `frontend/src/routes/jobs/JobInvoicePage.svelte` (route `#/jobs/:jobId/invoice[/:docId]`) |
| Invoice detail (panel) | `frontend/src/components/invoices/InvoicePanel.svelte` — hosted by `JobInvoicePage` inside `JobShell` |
| Old detail route (shim) | `frontend/src/routes/invoices/InvoiceDetailPage.svelte` (route `#/invoices/:id`, redirects into the job-scoped URL) |
| Mode bar (Edit/Customer/Reorder) | `frontend/src/components/docsurface/DocModeBar.svelte` — shared with the estimate side |
| Edit mode | `frontend/src/components/invoices/InvoiceEditView.svelte` — a mode of `InvoicePanel`, not a route |
| Customer / Reorder modes | `frontend/src/components/docsurface/DocCustomerView.svelte` / `DocReorderView.svelte` — shared with the estimate side |
| `docsurface` kit (backing chips, atom rows, uncovered-work pool, placeholder row) | `frontend/src/components/docsurface/` — see `estimates-and-prices.md` §12, `architecture-and-conventions.md` §5.5b |
| Old wizard route (shim) | `frontend/src/routes/invoices/InvoiceWizardRedirect.svelte` (route `#/invoices/:id/wizard`, remembers `'edit'` mode then redirects) |
| Deposit-credits picker | `InvoiceEditView.svelte`'s inline `DepositCreditsSection` — invoice-only, not part of the shared kit |
| Line item modal (shared with estimates) | `frontend/src/components/LineItemModal.svelte` |
| Send-to-QBO dialog | `frontend/src/components/invoices/SendToQBODialog.svelte` |

**Retired 2026-08:** `frontend/src/components/wizards/ReconcileMode.svelte`,
`WizardActions.svelte`, `WizardLineItemCard.svelte`, `WizardAtomRow.svelte`,
and both `WizardSourcePool.svelte` files (estimate and invoice) — deleted,
not renamed. See "Frontend" under "Invoice wizard" above.

### Invoice list page

`InvoiceListPage.svelte` is the SPA route at `#/invoices`, accessible via the **Financials** sidebar section (gated on `can_manage_financials`).

**Columns:** Invoice#, Job, Customer, Status, Sent, Due (with a late flag when past due and unpaid), Amount, Paid, Balance.

**Default view:** status preset **Open** (includes `open` + `partly-paid` invoices), sorted by due date ascending — most overdue first, nulls last.

**Status presets:** Open / Paid / Draft / Cancelled / All.

**Filters:** status preset, due-date range (from/to), and a `CustomerPicker` component that emits `{type: 'business'|'contact', id}`. A business selection maps to `?business=<id>`, rolling up invoices for all of that business's contacts; a contact selection maps to `?contact=<id>`.

**Backend — `?summary=true` opt-in (dual contract).** The financials list page calls `GET /api/invoices/?summary=true`. Only in **summary mode** does `InvoiceViewSet` switch to the lightweight `InvoiceSummarySerializer`, apply the annotated totals, default the status filter to **open** (open + partly-paid), and apply the status presets / due-date range / `?business=` / `?contact=` / ordering. **Without** `summary=true`, the list endpoint keeps its original contract — the full `InvoiceSerializer` (with nested `line_items`) and **all** statuses (no default filter). This preserves the pre-existing consumer `GET /api/invoices/?job=<id>`, which the **job overview** page (`JobDetailPage` → `JobDetail.svelte` → `InvoicingBlock`) uses for its Invoicing block, reading each invoice's computed `total` field (above) rather than walking `line_items` itself. (Switching the bare list action to the summary serializer + default-open unconditionally was a regression that left the Job overview showing invoices with no line items and no totals.) List read permission stays `IsAuthenticated` in both modes — the Financials sidebar gate is a UI convention only.

`InvoiceEditView` tracks its ticked uncovered-work selection with local
`$state`; "Add selected here" / "New line from selected" both POST and
await the panel's silent refresh. A 409 (claim conflict) clears the
selection, refreshes, and surfaces a specific "…refreshed" message via
the global overlay (`handleMutationError`,
`architecture-and-conventions.md` §5.5b's 409-refresh idiom) rather than
a form message — there is no form on this surface anymore.

### Starting an invoice — Create/View model

**Superseded by the 2026-07-08 job-workspace restructure and the
2026-07-09 overview redesign:** there is no longer an "invoice pillar"
on the job overview — the overview has no authoring affordances at all
(display-only summary blocks; see `jobs-and-tasks.md` §9).
The Create/View model now lives entirely on the Invoices section
(`InvoicePanel.svelte`, when the job has no invoices yet):

- **"Start Invoice"** — shown when the job's status is billable (`approved`, `in_progress`, `work_complete`, `completed`, or `cancelled`) **and** no draft invoice exists. POSTs `{job}` to `/api/invoices/` (routed through `InvoiceWizardService.open_for_job`) and reloads the panel onto the new draft — **auto-seeded from the job's agreement** (§"Agreement-line references and seeding" above) when one exists; an estimate-less job's draft simply arrives empty, same as before. Shown/allowed for users with `can_manage_jobs` **or** `can_manage_financials` (the `create` action of `InvoiceViewSet` is `(CanManageJobs | CanManageFinancials)`, matching the frontend gate; all other invoice write actions, including line-item editing, stay `can_manage_financials`-only). On a manageable but **not-yet-billable** job (draft/submitted) the button is hidden and the empty state explains: "Invoicing becomes available once the job is approved." (2026-07-19 — the button previously showed regardless of status, so its only outcome on a draft job was the service's refusal; the refusal message itself now names the real billable set in UI terms.)
- **Viewing** — once an invoice exists, `InvoicePanel`'s own subnav
  (`DocSubnav.svelte`) lists every invoice for the job; picking one
  shows it in place (no separate "View" button — the Invoices section
  route *is* the view). The overview's Invoicing block shows a stat
  summary only, with no link into the panel (the rail is the
  navigation).

"Start Invoice" and the subnav's existing invoices can both be present at once: a job may have a sent (`open`) invoice and no draft, in which case the subnav shows the `open` invoice and "Start Invoice" is still offered (it would open a second draft for the new billing event). One draft per job is guaranteed by the application-level get-or-create in `InvoiceWizardService.open_for_job` — a second "Start Invoice" while a draft already exists returns the existing draft rather than creating a new one. (The `unique_draft_invoice_per_job` partial unique constraint is declared on the model but is **not** created on MySQL, which doesn't support conditional unique constraints — Django emits `models.W036` — so the invariant rests on the service, not the DB.)

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

The Job P&L view consumes invoices, expenses, and bleps to compute revenue and cost on a job (vendor bills live in QBO since 2026-07-23; their cost side would arrive via a future QBO pull). Invoices and Expenses produce the data; the consumer side is not yet built. See "Unfinished work."

---

## Unfinished work

- **Job P&L view** — consumes Invoices + Expenses + Bleps (plus, eventually, QBO-side vendor-bill actuals). Was Phase 5 of the QBO integration roadmap. Data is being captured today; the view is not built.
- **`superseded` and `defaulted` statuses.** Both are defined in the status machine's choices but have no transition path that sets them. (Payment polling now drives `partly-paid` / `paid` — see "Payment polling" above — so those two are no longer dead.)
- **One-click invoice generation.** Auto-create a draft invoice from all uninvoiced atoms when a Job hits `work_complete`, without going through the wizard. Will share the data model with the wizard. Out of scope per the 2026-04-09 design. (Distinct from the 2026-08 agreement auto-seeding above, which fires at invoice *creation* time, not on a job-status transition, and seeds from the agreement rather than sweeping all uninvoiced atoms.)
- **Two deposit-credit surfaces, not yet unified.** `InvoicePanel`'s top-of-panel "Unapplied deposit credit" banner and `InvoiceEditView`'s `DepositCreditsSection` both offer the same credit pull today, independently derived. See "Deposits" → `DepositCreditsSection` above — parked for an explicit RM design call, not a bug to fix ad hoc.
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
- **`accounting_category` required on `InvoiceLineItem` — RESOLVED, opposite direction (Phase 3 nullable-AC plan, 2026-08).** The
  "make it NOT NULL everywhere" migration this TODO used to track was
  superseded: the field stays nullable by design. A hand line
  (`InvoiceService.add_line_item`) may be null pre-send; an
  agreement-seeded adjustment line may be null even at rest
  (`InvoiceService._agreement_category_id`'s adjustment exemption).
  What's actually enforced: `InvoiceEmailService._assert_all_lines_categorized`
  blocks `send_invoice` (the sole `draft`-exit path) while any line —
  adjustment or not — is null, so every non-`draft`/non-cancelled
  invoice is guaranteed fully categorized.
  `validate_data.check_invoice_line_categories` cross-checks exactly
  that at rest (Phase 3 Task 8) — see `data-constraints.md` §1.16.

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
