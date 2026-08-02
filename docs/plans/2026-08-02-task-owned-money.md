# Task-Owned Money — design

**Status:** draft for RM review. Disposable plan doc; the durable record lands in
`docs/designs/` (estimates-and-prices, jobs-and-tasks, invoicing-and-expenses,
quickbooks-integration, data-constraints) when implemented.

## Problem

`RateScheme` conflates three jobs: it is the **price of record** (tasks reference
it live for rate/modifiers), the **accounting classification** (a task's AC is
`rate_scheme.accounting_category`), and the **reusable catalog preset** (named,
picked from dropdowns). Every current pain traces to one of those welds:

- **Fee exists** because "price of record lives on a shared catalog object"
  cannot express per-item amounts. Fee is a parallel atom type with its own
  `SOURCE_FEE` triplicate, wizard branches, modal, and a dormant `task`
  OneToOne with a documented double-billing hazard.
- **The AC problem**: one scheme = one AC, but fixed charges (setup fee,
  waste-disposal pass-through, tax-like charges, possibly subcontract work)
  need different ACs. Neither a per-AC scheme family nor a per-task AC
  override field was acceptable.
- **Supersession machinery** (frozen fields, version chains, `(vN)` renames,
  the 409 + `supersede_url` dance) exists only to protect the price-of-record
  role from the catalog role. Note the system *already* treats task pricing as
  a snapshot — superseding never re-prices existing tasks.

## Design

### 1. The task owns its money

`Task` gains a self-contained money block, stamped at creation and
authoritative thereafter:

- **qty source** — where actual quantity comes from: `elapsed_time`
  (timeslips) or `entered_qty` (worker-entered). This is the whole remaining
  "algorithm" axis. `percentage` stays a document-layer concern (§5).
- **rate** — per-unit dollar amount, on the task.
- **unit_label** — on the task. `hours_pair_fill` convenience stays keyed on
  `unit_label == 'hour'`.
- **accounting_category** — nullable FK, on the task (§4).
- **active modifiers** — snapshot of the *resolved* modifiers, i.e. a list of
  `{key, label, percent}` (not bare keys — the task must not read percents
  from the preset after stamping, or preset edits would re-price it).
  `effective_rate = rate × (1 + Σ active percents / 100)`, computed from task
  fields alone. `copy_active_modifiers` and the `validate_data` shape check
  update accordingly.

Picking a preset in any dropdown **stamps** its values onto the task; the
preset is not referenced for pricing afterward. A nullable `source_scheme`
FK (`SET_NULL`, provenance only — same pattern as `service_item` catalog
identity) supports "what came from this preset" reporting and
rate-drift auditing.

### 2. RateScheme becomes a freely editable preset

Since nothing reads a preset's values after stamping:

- **Delete the supersession apparatus**: frozen fields, `replaced_by`/
  `replaced_at`, version chains, `supersede()`, the 409/`supersede_url`
  flow, `(vN)` renames, `is_referenced` edit-blocking.
- **Retirement** is a plain `is_active` flag. Inactive presets vanish from
  pickers; existing tasks are untouched (they're snapshots). Copy the
  existing `ServiceItem.is_active` + superseded-guard patterns for
  "ServiceItem points at a retired preset" warnings.
- **Default preset** is a Configuration key naming the preset that pre-fills
  rate-scheme dropdowns (instead of starting blank). Retiring the default
  clears/reassigns it.

### 3. Fee is eliminated

A flat fee is not an algorithm — it is an `entered_qty` task whose rate was
**typed in** rather than stamped from a preset:

- Work-backed fees (setup, delivery): a flat task collects bleps for
  auditing ("is this fee priced right?") while billing qty × rate — exactly
  the existing entered-qty shape. Billability gates on completion like any
  task (Fee's "always billable" rule is retired deliberately).
- Pass-throughs (waste disposal, tax-like charges): a flat task **born
  complete**, `actual_qty` set at creation (default 1) so the entered-qty
  completion gate never blocks, `est_worker_time` 0/null so it draws no
  schedule bar and never holds up `work_complete` long.
- **Hand-lines** on an accepted estimate/CO crystallize into flat tasks —
  description, rate, qty, AC straight off the line, **no scheme reference**
  (`Task.rate_scheme` NOT-NULL problem dissolves along with the "which
  scheme does a bare hand-line get" question).
- One kind of fee. The distinction work-backed vs pass-through is
  behavioral (born-complete or not), not typal.

Deletions: `Fee` model + `FeeService` + `/api/jobs/{id}/fees/` endpoints,
the `SOURCE_FEE` choices in all three source-row models and their `resolve()`
branches, fee branches of acceptance/CO-acceptance discriminators, agreement
`source_fee_id` plumbing, the invoice wizard's "Fees" group and `_atom_*`
fee branches, `FeeModal.svelte`, TaskTree's Fees section, `taskTotals.feeTotal`,
`check_fees`. Data migration converts existing Fee rows to flat tasks and
repoints source rows `'fee'` → `'task'`. nealsdata converter `_emit_fee`
emits flat tasks instead.

### 4. Accounting: nullable, late-bound, QBO-authoritative

QBO is the authority on income classification and taxability; Minibini's AC
exists to pre-classify the bulk of lines so the accountant rarely intervenes.

- **Task AC is nullable.** Catalog-driven work stamps AC from its preset —
  workers never see an AC field (frontend hides it without the relevant
  perms). **Estimate/CO hand-lines keep the required AC picker at entry**
  (the estimate writer has context; this keeps the fallback rare).
- **Fallback AC**: a Configuration-designated "everything else" category —
  excluded from normal pickers, `taxable=True` by default. At invoice
  compose, a null-AC atom's line gets the fallback **stamped on the line**
  and flagged in the wizard ("Uncategorized → General income · taxable").
  The invoice writer corrects it or sends as-is.
- **Line edits are line-local.** Atoms keep their honest null; deleting a
  line releases atoms unclassified, so the flag *regenerates* on the next
  compose — an uncategorized atom can never silently ride under an AC chosen
  for a dead line. (Cost: a manual correction on a deleted line is re-done;
  acceptable at this volume. A "save back to task" checkbox is a future
  affordance only if this proves irritating.)
- **Tax before send; classification whenever.** QBO income reclassification
  (swap Item / edit the Item's income account with "update historical") is
  total-preserving and safe after payment. Flipping `TAX`/`NON` changes the
  invoice total and is *not* safe after payment — so the wizard's real
  must-check on fallback lines is taxability. Push code
  (`apps/qbo/services.py` ItemRef + TaxCodeRef from `li.accounting_category`)
  is unchanged and never sees a null.

### 5. Percentage stays at the document layer

Percentage presets remain selectable for adjustment lines only. The line
snapshots the percent (it already stores target ACs); the preset FK becomes
provenance, consistent with §1. Uncategorized lines are **never members of a
targeted AC set** (all-lines adjustments unaffected); the wizard warns when
a targeted adjustment coexists with fallback lines.

### 6. Permissions: workers stamp, managers price

The scheme was the old price-governance mechanism; its replacement is
field-level:

- Any authenticated user can create a task **by stamping a preset** — money
  fields arrive verbatim from the preset and are read-only to them.
- Editing the money block (rate, modifiers, AC, qty source) or creating a
  flat task with a typed-in rate requires `can_manage_jobs`, the job's PM
  (`CanManageJobOrPM`), or `can_manage_financials`. Enforced at the
  serializer layer; matches how the Fee modal is permissioned today.

### 7. Outsourced work (service POs)

Powder coating, waterjet, etc. Sell side is a job atom; cost side lives in
purchasing; bills stay in QBO (no Bill resurrection — the retired schema
stubs stay parked; their removal migrations stay unrun until this ships).

**Flow:**

1. **Estimate** — vendor quote informs an estimate line (hand-line or an
   "outsourced X" ServiceItem preset). Sell price = quote × the default-
   markup Configuration value, prefilled, human-confirmed.
2. **Acceptance** — line crystallizes into a flat task (entered-qty, qty 1,
   typed sell rate). NOT born complete: completion = vendor work
   done/received, which is what gates billability. No bleps expected; no
   `est_worker_time`, so no schedule bar.
3. **Order** — PO line at vendor cost, linked to the task via the existing
   reserved `PurchaseOrderLineItem.task` FK. Mirror of the materials
   pattern (`Material.po_line_item`): job-side atom ↔ PO line, atom carries
   sell, PO line carries cost; the FK just lives on opposite ends.
4. **Receive** — existing PO receiving flow. A PO that is received but not
   reconciled surfaces as **awaiting reconciliation** (purchasing-side
   nudge; deliberately NOT tied to task completion — completion is a pure
   work event and never asks about money).
5. **Reconcile** (when the vendor's bill arrives, entered once in QBO by
   whoever does payables; Minibini captures only the delta it needs):
   - **PO-level, authoritative**: bill total, vendor invoice ref,
     `reconciled` state. Always possible no matter how differently the
     vendor billed vs. quoted.
   - **Line-level, optional**: per-line `final_price` (null = as ordered);
     appended invoice-only lines (freight, taxes) with optional attribution
     to an existing line/task. Unattributed variance stays at PO
     granularity — no proration; multi-job POs report variance per-PO.
6. **Task-rate prompt** — only from a clean per-line final on a not-yet-
   invoiced task: "final cost $X (was $Y) — update selling price to
   $X × markup?" Accept updates the task's rate (a permissioned money-block
   edit); decline leaves the quoted rate. Never silent, never live-read:
   the invoice wizard stays dumb and prices qty × current task rate.
7. **Invoice** — any time after task completion, at the task's current
   rate: the quoted sell price if the bill hasn't arrived / prompt
   declined, the updated one if accepted. Reconciliation never blocks
   invoicing; a variance discovered after invoicing is recorded margin, and
   passing it through later is a deliberate new line / CO.

**Future (phase 2, only if variance entry annoys):** pull-only QBO Bill
matcher — poll Bills, match by a PO-number-in-memo convention, prefill the
reconciliation screen. Nothing pushes; QBO stays sole bill
system-of-record; no bidirectional sync.

**Rejected:** entering final price at task completion (completer usually
doesn't know it yet; wrong actor/permissions; would need a second home for
costs). Bill entry originating in Minibini with push-to-QBO (viable, bigger;
revisit only if the PO-actuals rung proves insufficient). Pushing POs to QBO
and pulling bill links back (most duplication, desync risk).

## Unchanged

The document architecture — atoms, source rows, claims, estimates/invoices
as lenses, the wizard flow — is sound and untouched except where fee
branches delete. Job/Task/Blep project-management structure unchanged.
Estimate hand-line AC requirement unchanged.

## Open / deferred

- Example walk-through (2026-08-02, in progress). Resolved as clean under
  this design: resale materials, N-parts-from-material, setup/delivery/site-
  visit fees, hourly CAD, cutting & engraving (presets in machining-minutes;
  wizard translates to per-piece; heavy-material/intricate/flip surcharges
  are modifiers), untracked consumables (absorb, percentage adjustment, or
  flat task — policy choice), deposits (already built). Resolved: outsourced
  work (§7). Still to walk: jigs & customer-funded tooling, credits
  (atom-or-document-line rule needed — a negative hand-line must NOT
  crystallize into a nonsense task), N-finished-items product bundles.
- "Add Fee" button in the work-area modal: dies with Fee, but may survive as
  a preset-filtered "add flat task" shortcut. Pure UI sugar; decide late.
- Multi-Materials-per-PO-line plan (schema already permits; code assumes
  one via `linked_material`'s `.first()`) — interacts with §7 only in that
  multi-job POs keep variance at PO granularity.
- Migration sequencing and phasing (task money block → Fee elimination →
  nullable AC + fallback → preset default/retirement) belongs to the
  implementation plan, not this spec.
- "Save corrected AC back to task" wizard affordance — only if the re-do
  cost proves annoying in practice.
