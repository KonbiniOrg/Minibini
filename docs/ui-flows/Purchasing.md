# Purchasing (Purchase Orders) — UI flow

**Purpose:** A from-the-user's-perspective walkthrough of the Purchase Order
lifecycle — draft creation, line items (including optional cost→sell task
attribution), issuing, receiving, and PO-level reconciliation of the vendor
bill (outsourced-work port, `docs/plans/2026-09-21-outsourced-work-port.md`).
Bills themselves stay in QBO — Minibini's own retired Bill model plays no
part here; see `docs/designs/materials-inventory-and-purchasing.md` §10a for
the reconciliation reference and §13 for the bill retirement. Keep this
current as the PO UI evolves.

## Personas

Purchase orders split their gating unevenly — most of the document is
Financials-only, but **receiving is open to any authenticated user**
(`apps/api/purchasing/views.py::get_permissions` puts `receive`,
`receive_all`, `cancel_line_item`, and `reverse_receipt` in the
`IsAuthenticated`-only bucket; the frontend's `canReceive` gate mirrors this
by status alone, with no atom check).

- **Viewer** — any authenticated user, no atoms. Can view the PO list and PO
  detail (including the read-only reconciliation summary once a PO is
  reconciled). On an `issued`/`partly_received` PO can **Receive All**,
  **Receive Items**, **Cancel Line**, and **Reverse Receipt** — these need
  no atom. Sees **no** New PO / Edit / Delete / Issue / Cancel PO /
  reconcile-form / rate-prompt controls (all Financials-only, both in the
  UI and on the server).
- **Financials** — holds `can_manage_financials`. Everything above, plus
  full CRUD on draft POs (including the Task Link picker), issue/send,
  reconcile, and the task-rate prompt.

## Dev notes

- **No PO→QBO push.** A PO issued/sent from Minibini is a document the vendor
  sees (or a note-only "Mark as Issued"); it is never pushed to QBO. The
  vendor's actual invoice/bill is entered in QBO by whoever does payables —
  reconciliation here only records the **delta** (bill total, vendor invoice
  ref, optional per-line final price) as it applies to the PO's ordered
  lines. See `docs/designs/quickbooks-integration.md` "Bills stay in QBO."
- **Reconciliation never blocks invoicing.** Task completion remains the only
  billability gate (§8 below) — a task can be invoiced whether or not its
  linked PO has been reconciled, and a stale unreconciled `final_price` is a
  `validate_data` WARN, not an error.
- **"Change Job" on a post-issue line has no client-side Financials gate**
  (`PurchaseOrderDetail.svelte`'s post-issue Actions column shows it to any
  authenticated user once `canChangeJob(li)` is true), but the underlying
  `PATCH .../line-items/{id}/` with a bare `job` key is Financials-gated
  server-side (the default `get_permissions()` fallback — `line_item_detail`
  isn't in the `IsAuthenticated`-only action list). A Viewer who clicks it
  gets a 403, not a broken page — pre-existing behavior, not part of this
  port; not fixed here.

## Prerequisites (test-data setup)

- [ ] **A Business (vendor)** — every PO needs one before it can be issued;
  the form's Vendor field is a business type-ahead.
- [ ] **A Job with at least one top-level task** whose cost is meant to be
  outsourced — needed to exercise the task-link picker (§1) and the
  task-rate prompt (§7).
- [ ] **An AccountingCategory** — for PO line items and invoice-only
  reconciliation lines.
- [ ] **Two users** — a plain authenticated **Viewer** and a
  `can_manage_financials` **Financials** user.

---

## 1. Creating a PO and its line items

Routes: list `#/purchase-orders`; create `#/purchase-orders/new`; detail
`#/purchase-orders/{id}`; edit `#/purchase-orders/{id}/edit`.

- [ ] **New Purchase Order button (persona):** on `#/purchase-orders`, **New
  Purchase Order** is visible to **Financials** only.
- [ ] **Vendor + optional contact:** the create form picks a Business
  (type-ahead) and, once picked, a Contact from that business (auto-selects
  the business's default contact).
- [ ] **Line items — manual or from inventory:** on a draft PO's detail,
  **Add Line Item** offers **Manual** (description/qty/units/price/category)
  or **From Inventory** (an inventory-item picker that fills
  description/units/price) modes.
- [ ] **Optional job attribution:** a line item may separately carry a **Job
  (optional)** (for a linked Material) and a **Task Link (optional)** — the
  two are independent; a line can attribute cost to a task on a job
  different from its material's job.
- [ ] **Task-link picker — every task on the picked job is eligible:** the
  **Task Link** field cascades a job picker into a `<select>` of that job's
  tasks (`TaskLinkPicker.svelte`) — no client-side filtering (subtasks are
  not a concept on this branch). Linking is optional; `-- No task link --`
  is always available.
- [ ] **Guard — task must belong to a job:** a task with no job cannot be
  linked; a stale/forced value is refused server-side with a field error on
  `task`: "Linked task must belong to a job." (In practice unreachable
  through the picker itself, since every task it lists comes from a job's
  own task list — this exercises the server-side backstop directly, e.g.
  via the API.)
- [ ] **Reorder / edit / delete line items (draft only):** the line-item
  table offers ▲/▼ reorder, Edit, and Delete — all **draft-status only**,
  and all **Financials-only**.

## 2. Issuing

- [ ] **Issue & Send vs. Mark as Issued:** on a draft PO with at least one
  line item, **Financials** sees both **Issue & Send** (opens the email-send
  form) and **Mark as Issued** (a note-only transition — prompts for an
  optional note, then flips status with no email).
- [ ] **Guard — vendor required to issue:** issuing a PO with no Business set
  is refused ("A purchase order needs a vendor before it can be issued.").
- [ ] **Guard — empty PO:** Issue & Send / Mark as Issued are both disabled
  while the PO has zero line items.
- [ ] **Post-issue, no more line edits:** once issued, the line-item
  Edit/Delete/reorder controls are gone (adding/removing lines is a
  draft-only operation).
- [ ] **Resend:** an issued (or partly-received) PO offers **Resend**
  (Financials-only).

## 3. Receiving (open to any authenticated user)

Available once **issued** or **partly_received** — no `can_manage_financials`
required for any action in this section (§ Personas above).

- [ ] **Receive All:** one click receives every remaining line in full — no
  confirmation prompt (reversible via Reverse Receipt).
- [ ] **Receive Items (partial):** opens a form pre-filled with each line's
  remaining quantity; only lines with remaining qty show, and each is
  independently editable (overage allowed) before submit.
- [ ] **Line status pills:** each line shows **Pending** / **Partial** /
  **Received** / **Cancelled** based on qty received vs. ordered/cancelled.
- [ ] **Cancel Line:** a line not yet fully received/cancelled can be
  cancelled with an optional note — if it has a linked, still-pending
  Material, the sever-decision dialog appears first.
- [ ] **Reverse Receipt:** a line with any received quantity can have its
  receipt fully reversed (undoes all received qty), with an optional note.
- [ ] **`invoice_only` lines never appear here:** an invoice-only line
  appended during reconciliation (§6) is excluded from Receive
  All/Items entirely — it was never ordered from the vendor to begin with;
  attempting to receive one directly (e.g. via the API) 400s ("is
  invoice-only and excluded from receiving"), and attempting to cancel one
  400s too ("it cannot be cancelled").

## 4. Changing a line's job (draft and post-receive)

- [ ] **Draft:** the line-item Edit form includes a Job picker inline; saving
  routes a job change through the same "change job" path as post-receive.
  Financials-only.
- [ ] **Post-issue/receive:** a **Change Job** button opens a standalone
  "Change Job" modal (no other fields editable at that point). The button
  itself is visible to any authenticated user, but the underlying write is
  Financials-gated server-side (see Dev notes) — a Viewer's save attempt
  403s.

## 5. Awaiting-reconciliation nudge

Purchasing-side signal, independent of any task's completion status — a PO
that is **fully received but not yet reconciled**.

- [ ] **Badge on the PO list:** on `#/purchase-orders`, a PO with
  `received_in_full` status and `reconciled=false` shows an amber
  **"Awaiting Reconciliation"** badge in its row.
- [ ] **No badge before receiving:** the same PO shows no badge while still
  `draft`/`issued`/`partly_received` — the nudge is receiving-completeness,
  not issue-completeness.
- [ ] **No badge once reconciled:** the badge disappears the moment the PO is
  reconciled (§6), even if a later reconcile call updates it again (re-
  reconcile does not un-set `reconciled`).
- [ ] **List filter:** the **"Awaiting reconciliation only"** checkbox on
  `#/purchase-orders` filters the list to exactly this set
  (`?awaiting_reconciliation=true`).

## 6. Reconciling (recording the vendor bill's delta)

The **Reconciliation** section renders (`ReconciliationSection.svelte`) on
any non-draft PO's detail. Bills are entered **once, in QBO**, by whoever
does payables — this section captures only what differs from the PO as
ordered. Financials-only.

- [ ] **Guard — cannot reconcile a draft PO:** the section doesn't render at
  all on a draft PO.
- [ ] **PO-level fields:** **Bill Total** and **Vendor Invoice Ref** — always
  enterable however the vendor actually billed, independent of what was
  ordered.
- [ ] **Per-line Final Price (optional):** each ordered line shows an
  editable **Final Price** input, placeholder **"as ordered"** — leaving it
  blank means the line's cost is exactly as ordered (`final_price` stays
  `null`).
- [ ] **Invoice-only lines (freight, tax, etc.):** **Add Invoice-Only Line**
  appends a line that was **never ordered or received** — description, qty,
  units, price, optional category, optional task link. These never touch the
  receiving flow (§3).
- [ ] **Variance display:** **Variance** = Bill Total − ordered total (the
  sum of ordered-line qty×price, invoice-only lines excluded) — a plain
  display figure, never prorated across lines.
- [ ] **Save is wholesale-replace, not a diff:** submitting resends the
  **complete current picture** — an ordered line's Final Price left blank on
  this save reverts to "as ordered" even if a prior save had set one; an
  invoice-only line not present in this save's payload is **deleted**.
- [ ] **Persisted invoice-only line removed pre-save shows a notice:**
  removing an **already-saved** invoice-only line (not one just added this
  session) surfaces an inline amber notice — "N recorded line(s) will be
  deleted when you save — re-add it to keep it" — with a **Re-add** button
  that restores it before you save. No confirmation dialog (this is
  reversible pre-save, matching the delete-confirmation-only-for-irreversible
  convention).
- [ ] **Re-reconcile is editable, not locked:** reconciling a second time on
  an already-reconciled PO overwrites the prior bill total/ref/finals — the
  submit button reads **"Update reconciliation"** instead of **"Reconcile"**
  once `reconciled` is true.
- [ ] **Reconciling a cancelled PO is allowed:** `reconcile()` only rejects
  `draft` — a partial shipment that got billed before cancellation can still
  be reconciled.
- [ ] **Viewer sees a read-only summary once reconciled:** a non-Financials
  user sees no form at all pre-reconciliation, and a read-only `<dl>` (Bill
  Total, Vendor Invoice Ref, Reconciled date, Variance) plus the
  invoice-only lines table once reconciled — no inputs, no Remove/Re-add.

## 7. The task-rate prompt

Fires **only** immediately after a successful reconcile (or re-reconcile)
call, and **only** for **Financials** users (`RatePromptDialog.svelte`,
rendered by `PurchaseOrderDetailPage.svelte`).

- [ ] **Qualifying lines:** a line prompts when it has a **clean (non-null)
  Final Price** AND a **linked task** AND that task **has not yet been
  invoiced**. A line with no Final Price, no task link, or an
  already-invoiced task is silently skipped — no prompt, no error. There is
  no additional check that the final price differs from the ordered
  price — even a final price identical to what was ordered prompts.
- [ ] **Dialog contents:** "Update task rates?" lists each qualifying line's
  task name, its **Current Rate** (the task's *effective* rate — modifiers
  already applied, not the bare stored rate), and a **Suggested Rate** (the
  final price marked up by the configured default markup percent, if one
  exists — else the bare final price, with a "No markup configured —
  suggestion equals vendor cost" note).
- [ ] **Modifiers note:** a task with active rate modifiers shows "modifiers
  apply on top of the accepted rate" next to its name — accepting the
  suggestion replaces the *plain* rate, it doesn't strip modifiers.
- [ ] **Accept:** updates that one task's rate to the suggested figure via
  the task's own money-gated update path (same permission gate as editing a
  task's rate directly) — reflected immediately on the task's detail Rate
  chip.
- [ ] **Guard — Accept on an already-complete task 400s:** a terminal task's
  billing inputs are frozen ("Its work and billing are settled; corrections
  belong on the invoice."). `compute_rate_prompts` does not exclude terminal
  tasks from qualifying, so a reconcile that lands after the task is already
  complete can offer a prompt whose Accept then fails with a per-row error
  and a **Retry** button. In the realistic ordering (receive → complete →
  bill → reconcile) this is avoided by accepting before completing the task;
  see `docs/designs/LATER.md` for the open question of whether this should
  change.
- [ ] **Decline:** dismisses that row only — the task's rate is left exactly
  as quoted. Purely local; nothing is sent to the server.
- [ ] **Independent per row:** accepting or declining one prompt's row never
  affects any other row in the same dialog — a multi-line reconcile with
  several qualifying lines resolves each on its own.
- [ ] **Never silent, never automatic:** reconciling never changes a task's
  rate by itself — only an explicit Accept click does, and only when a
  Financials user is present to see the dialog.
- [ ] **Re-viewing after a decision is safe:** re-reconciling (still
  qualifying) re-offers the same prompt with no memory of a prior
  accept/decline — closing it untouched is a no-op; it does not undo an
  earlier Accept.

## 8. Effect on invoicing

- [ ] **Task completion remains the only billability gate:** reconciliation
  status has no bearing on whether a task appears in the invoice pool — an
  unreconciled (or even un-received) PO's linked task invoices exactly as
  any other completed task would.
- [ ] **An available (uninvoiced) atom's row always shows the task's
  current rate:** on `#/jobs/{id}/invoice` → **Reconcile** mode, the source
  pool recomputes `qty × effective_rate` fresh on every load
  (`BaseWizardService._atom_detail`) — accepting a rate prompt (§7) is
  visible here on the very next visit with no extra step, for any task
  still in the *available* (unclaimed) pool.
- [ ] **A NEW invoice seeds an agreement-backed line already re-derived
  onto the accepted rate:** this is the mechanism that actually matters for
  a task whose agreement line was seeded automatically —
  `InvoiceService.seed_from_agreement` calls `_rederive_price_from_actuals`
  on every backed line at seed time, so **starting** an invoice (not
  revisiting an existing one) after accepting a rate prompt produces a
  seeded line priced at the new rate. This is different from "the wizard
  reads the task's rate live" — an existing invoice's already-seeded lines
  are not retroactively repriced by a later rate-prompt accept; only a
  fresh seed (or a manual edit) picks up the change.

## 9. Cancel & delete guards

- [ ] **Cancel requires a reason, issued-only:** **Cancel PO** is offered
  only on `issued` POs, and requires a reason; a linked pending Material
  triggers the sever-decision dialog first. Financials-only.
- [ ] **Delete is draft-only:** **Delete** (with confirmation — irreversible)
  is offered only on `draft` POs. Financials-only.

## 10. Permissions summary

- [ ] **Viewer (no atom):** list + detail (incl. the read-only reconciled
  summary) are visible; Receive All/Items, Cancel Line, and Reverse Receipt
  are usable; every other write control (New PO, line CRUD, Issue, Resend,
  Cancel PO, Delete, the reconcile form, the rate-prompt dialog) is absent.
- [ ] **Financials:** all of the above are available, plus the
  Financials-only set.

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Creation | manual line · from-inventory line · optional job attribution (material side) · optional task link |
| Task-link guard | any task on the picked job accepted · task-with-no-job rejected (server-side) |
| Issue | Issue & Send · Mark as Issued (note-only) · vendor-required guard · empty-PO guard · post-issue lines frozen |
| Receiving (no atom needed) | Receive All · Receive Items (partial, overage) · line status pills · Cancel Line (+ sever dialog) · Reverse Receipt · invoice_only excluded (both entry points) |
| Change Job | draft (via Edit) · post-issue (dedicated button, visible to any user, write Financials-gated) |
| Awaiting-reconciliation | badge shown only received_in_full+unreconciled · absent pre-receive · absent post-reconcile · list filter |
| Reconcile | bill total · vendor ref · per-line final price (blank = as ordered) · invoice-only append · wholesale-replace semantics · persisted-line removal notice + re-add · re-reconcile (Update wording) · reconcile a cancelled PO · variance display · Viewer read-only summary |
| Rate prompt | qualifying-line rule (final price + task + uninvoiced, no "differs" check) · effective-rate Current Rate + modifiers note · Accept updates task rate · Accept on a complete task 400s (Retry shown) · Decline is a no-op · independent per row · re-offered untouched on re-reconcile |
| Invoicing | live pool read for available atoms · fresh-seed re-derivation for backed lines · unaffected by reconciliation status |
| Cancel/delete | cancel issued-only + reason + sever dialog · delete draft-only + confirm |
| Persona | Viewer (read + receiving only) · Financials (full CRUD + reconcile + rate prompt) |
