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
identity) supports "what came from this preset" reporting, a name chip on
task detail, and rate-drift auditing (RM confirmed keep, 2026-08-02).
**Invariant: no compute path may ever read `source_scheme`** — that is
what keeps it a label rather than quietly becoming a live link again.

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

### 3. Fee re-scoped: the pure-money atom (NOT eliminated)

The example walk-through (2026-08-02) reversed this spec's original
headline. The original sin was never Fee's existence — it was work-backed
charges (setup, delivery, site visits) being shoehorned into Fee because
RateScheme couldn't price per-item. Those move to flat tasks (§1). What
remains is Fee's honest role — the context-free money charge — and for
that, Fee is already the right shape.

Why an atom and not a document line: a percentage adjustment is a
*function* (its value depends on sibling lines, must recompute per
document, cannot be an atom). A fixed charge is a context-free *value* —
it means the same $80 on any document and must bill **exactly once**,
which is what the claim machinery enforces structurally. The rejected
alternative (a fixed-amount adjustment kind) needed advisory "soft
tracking" against forgetting/double-billing — a shadow claims system.
When the mitigation is a hand-rolled imitation of the thing deleted, keep
the thing.

- **Fee keeps**: job ownership, `quantity × unit_rate` (qty defaults 1),
  its own AC, the `SOURCE_FEE` claims in all three source-row models, the
  invoice wizard's Fees group, FeeModal, and always-billable with no
  completion gate — *correct* for pure money.
- **Fee drops the `task` OneToOne** — the dormant field and its documented
  double-billing hazard die.
- **Amounts become signed: a credit is a negative Fee**, inheriting
  exactly-once (double-crediting is real money too). Validation
  `unit_rate > 0` becomes `≠ 0`. Work/material entry rejects negative
  prices with a message pointing at Fee/Credit.
- **Pass-throughs** (waste disposal, tax-like charges) are Fees. The
  born-complete-task idea is withdrawn; born-complete tasks are not part
  of the design.
- **Post-invoice credits** (refunds, after-the-fact goodwill) are QBO
  credit memos — out of scope, per QBO authority. Credits carried to a
  later invoice: not needed now; an invoice-time Fee covers it if ever.
- **Work-backed charges become flat tasks**: entered-qty, typed rate, no
  preset required (§1 dissolves the NOT-NULL scheme constraint); bleps
  audit the time; completion gates billability — Fee's always-billable
  rule deliberately does NOT transfer to them.

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

### 8. Line-entry vocabulary (estimate, job, invoice)

One "Add line" picker per surface: catalog search on top (ServiceItems +
inventory together — always the first reach, since a pick answers kind,
money, and AC at once), explicit kind buttons below. No checkbox, no
default fallthrough — the writer declares what the thing is:

- **Work** — description, qty + units, rate, AC (required). The form
  opens with the preset dropdown (default preset preselected, §2);
  choosing one stamps rate/units/AC into the visible, editable fields;
  typing over them is fine. At acceptance the line crystallizes verbatim
  into a flat task (qty-source = entered, `source_scheme` = the preset or
  null). Expected population: one-off operations at standard rates
  (stamped), lump-priced work (the population that used to misfile into
  Fee), negotiated rate deviations (stamp, then edit). Recurring freeform
  work is the signal to mint a ServiceItem.
- **Material** — as today, AC prefilled from the config default.
- **Fee / Credit** — description, qty (default 1) × amount (signed — a
  negative amount *is* a credit; the form echoes "this will appear as a
  credit"), AC required. Crystallizes to a Fee atom.
- **Adjustment** — the percentage form; document-layer, never
  crystallizes (§5).

Schema: `EstimateLineItem.is_material` (and the CO twin) generalizes to a
three-value freeform kind (work | material | fee); the acceptance/CO
discriminators branch on it explicitly — the historical bare-hand-line →
Fee default fallthrough is gone. Lines wear a small kind badge from
creation, since kind now acts at acceptance.

Surfaces: the estimate footer gains **Work** (freeform tasks were
previously impossible there — a scar of the NOT-NULL scheme, which is why
the current footer is a material checkbox). The job work area keeps its
three atom buttons; its Add Task flow becomes the same preset-stamp form.
The invoice offers Fee/Credit + Adjustment for invoice-time money. One
mental model everywhere: *search the catalog first; otherwise say whether
it's work, goods, or money.* The "Add Fee" button therefore stays — it is
the money entry, not a casualty.

### 9. Quantity structure: parent × per-unit subtasks

For "make N of a thing" (quote 10 widgets built from many operations).
Built **ad hoc in the work area** — Add Task ("Widgets, 10 ea"), then Add
Subtask per operation. A WorkTemplate can stamp the whole structure for
recurring products (apply asks N); it is a convenience, never a
prerequisite — one-offs live and die as hand-built structures.

Subtasks already exist (one level, `parent_task`, enforced). What made
them troublesome for per-unit estimating was the NOT-NULL rate scheme
forcing every subtask to be an independent billing object; §1 removes
that. Rules:

- **A task with subtasks becomes non-startable**: no bleps, no assignee;
  all project-management functions live on the children.
- **Parent qty is a multiplier** over per-unit children: a laser subtask
  carries 15 min/ea; parent qty 10 ⇒ the system expects 150 min. A qty-1
  parent unifies plain lump-task decomposition (multiplier 1).
- **The parent is the unit of billing.** Claims point at the parent only;
  **subtasks are never wizard-pool atoms**, whatever money values they
  carry. Children's per-unit qty × rate compose the parent's per-unit
  price (Σ children = $45/ea ⇒ the parent bills 10 ea @ $45; line-level
  override applies as ever). A subtask that must bill independently gets
  detached — full stop. Adding execution granularity after acceptance
  (which WILL happen — that is the point of project management) is
  thereby structurally incapable of double-billing.
- **Actuals are always batch totals; est values are always read through
  the helper.** Work happens in batches, so bleps and entered quantities
  land on subtasks as raw totals (147 min), never per-widget. A subtask's
  est fields mean **per-unit when `qty_scales_with_parent` is true**
  (15 min/ea × parent qty 10 ⇒ expected 150) and **per-batch when false**
  (20 min setup ⇒ expected 20 at any N — there, est and actual are
  directly comparable). The asymmetry is explicit, not conventional:
  **one blessed derivation helper** (multiplier = `parent.qty` if parent
  and `qty_scales_with_parent` else 1) is the only path by which schedule
  bars (`est_worker_time` through the same multiplier), expected-vs-logged
  displays, and estimate composition read subtask est values. Nothing may
  compare 15 to 147 raw.
- **`qty_scales_with_parent`** (boolean) lives on Task like any
  state-dependent field (cf. `actual_qty`): functional only when a parent
  exists, inert on top-level rows, rendered only on subtask forms.
  Per-batch work (laser setup, first-article inspection) sets it false —
  expected = est × 1 regardless of N.
- **The multiplier is unit-agnostic — no `ea` requirement on the
  parent.** "Per unit" means per unit of the parent's quantity, whatever
  the unit: "0.5 min per board foot" is the same structure as "15 min per
  widget," and scaling genuinely occurs on bulk units (sanding/finishing
  per bf). A bulk-unit parent decomposed into ordinary steps just sets
  the flag false on every child (multiplier degenerates to 1 — plain
  lump decomposition). Footgun guards, both required:
  1. The subtask form ALWAYS shows the derived expectation inline
     ("20 min/bf × 500 bf = **10,000 min expected**") — a wrong flag is
     visible at entry, not at schedule time.
  2. The flag's **default keys off the parent's unit**: true when the
     parent's units are `ea` (countables decompose per-piece), false
     otherwise (bulk/time quantities decompose into batch steps).
     Freely overridable; upgrades to "is the unit countable" if the
     units-divisibility flag ever lands. Moot on qty-1 parents.
  (RM 2026-08-02: accepted on a we'll-let-users-complain basis — expect
  confusion reports; revisit the defaults if they come.)
- **Parent completion** is offered (not automatic) when children finish,
  and keeps the entered-qty gate: "quantity made?" — that answer (9 good
  widgets, not the estimated 10) is what the invoice wizard bills. For an
  elapsed-billed parent decomposed mid-flight, actual hours roll up:
  pre-decomposition own bleps + children's.

**Wizard facts recorded** (code-verified 2026-08-02, to avoid
re-derivation): presentation qty/units on bundled lines **already
exists** — in-sync is defined as `price == round(Σ atoms / qty, 2)`
(`apps/core/wizard.py`), so "present as 10 ea at the divided price" is
current behavior; an override is the out-of-sync state, resettable to
atom values; resync runs on source-set changes, otherwise recompute is
user-requested only. Atoms claimed by a **non-draft** document (or an
invoice) are locked against edits; draft-claimed atoms remain editable
(`apps/jobs/services.py:1185-1219`). A §9 parent atom presents natively
as N ea × Σ. Post-refactor, `_uniform_scheme_bundle`'s same-scheme test
restates as identical (rate, unit) across atoms. Partial-bundle invoicing
(6 of 10 widgets shipped) is deliberately NOT built — claims are
whole-atom; revisit only when a real case forces it.

## Unchanged

The document architecture — atoms, source rows, claims, estimates/invoices
as lenses, the wizard flow — is sound and untouched except where fee
branches delete. Job/Task/Blep project-management structure unchanged.
Estimate hand-line AC requirement unchanged.

## Open / deferred

- **Example walk-through COMPLETE (2026-08-02).** All fourteen items have
  a defined shape: resale materials, N-parts-from-material,
  setup/delivery/site-visit fees (flat tasks), hourly CAD, cutting &
  engraving (presets in machining-minutes; wizard translates to
  per-piece; surcharges are modifiers), untracked consumables (absorb /
  percentage adjustment / flat task — policy choice), deposits (already
  built), outsourced work (§7), jigs & customer-funded tooling (ordinary
  tasks + materials; NO asset/reuse registry — RM decision; revisit only
  if remade-jig incidents force it), credits (negative Fees, §3),
  pass-throughs (Fees, §3), N finished items (§9).
- **RM verdict pending real use**: build it and work with it a while
  before final judgment — the whole design is provisional until exercised.
- Fee form keeps the qty × unit_rate pair (qty defaults 1); collapsing to
  a single amount field was floated and not pursued.
- Multi-Materials-per-PO-line plan (schema already permits; code assumes
  one via `linked_material`'s `.first()`) — interacts with §7 only in that
  multi-job POs keep variance at PO granularity.
- Deliverables/shipment linkage for §9 structures (10 widgets →
  Deliverable records) untouched by this design; existing machinery.
- Migration sequencing and phasing (task money block → Fee re-scope →
  nullable AC + fallback → preset default/retirement) belongs to the
  implementation plan, not this spec.
- "Save corrected AC back to task" wizard affordance — only if the re-do
  cost proves annoying in practice.
