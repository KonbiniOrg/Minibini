# Better Fees — lines, work, and reconciliation

**Status:** draft for RM review. Disposable plan doc; the durable record lands
in `docs/designs/` (estimates-and-prices, jobs-and-tasks,
invoicing-and-expenses, data-constraints, schedule) when implemented.

**Branch:** `feature/better-fees` (based on main). Supersedes the
`feature/fees` branch's Phases 2 and 4; adopts its Phases 1, 3, and 5 (§2).
Design conversation: 2026-08-06 session.

## Problem

An estimate line is a **commercial** statement (what the customer buys, at
what estimated price). A Task or Material is an **operational** one (what the
shop does or consumes). Sometimes they coincide — hourly labor, where the
task is the sellable unit — and the atoms-and-lenses architecture is built on
that coinciding case. When they don't coincide, the system forces the
commercial unit to masquerade as an operational type:

- On main, a typed hand-line ("3 chairs @ $500") crystallizes into a
  `Fee(quantity=3, unit_rate=500, task=NULL)` — a pure money row with no
  units, no lifecycle, no schedule presence, and no connection to the
  Deliverables that those same chairs must also (separately, manually)
  become. The work to build the chairs is entered as Tasks with no relation
  to any of it.
- On `feature/fees`, the same line became a flat work Task, and Phase 4 built
  parent×per-unit-subtask quantity structures so real work could hang under
  it. That made a Task simultaneously a billing container and a work item,
  and the price-derivation between them is where it broke: a per-minute CNC
  parent with a "go buy a bit" subtask has no intuitive invoice shape —
  either the parent's unit rate wobbles to absorb the child (the shipped
  behavior; judgment item #6) or the child bills as its own weird line.
- At invoice time there is no view of what the estimate said.
  `copy_from_estimate` replays agreement lines as bare values and claims only
  the crystallized Fees; task- and material-backed lines arrive with no
  source rows, so the wizard cannot reconcile them against actuals
  (`apps/invoicing/services.py:282-290`). §7 owns this problem outright
  (it was briefly a LATER.md entry; removed — this spec is its fix).

## Principles

1. **A sell price is stamped, never derived.** The money on a bag of
   heterogeneous work does not sum to a customer-facing price; a price is a
   decision informed by costs. Any container whose price is derived from its
   contents will confuse (this is the generalization of feature/fees
   Phase 1's stamp-don't-derive, and the lesson of Phase 4).
2. **Crystallization means becoming work.** Acceptance turns a line into a
   job-side object only where the line genuinely describes an operational
   thing the job needs: a Task from a service item, a Material from catalog
   or a bare material line. Lines that were never work (charges, outcomes)
   crystallize into nothing.
3. **Every line price is an estimate.** There is no fixed-price mode. Work is
   tracked precisely so the invoicer can bill more or less than estimated,
   with evidence. Invoicing is therefore *reconciliation, always*: what did
   we say, what did we do, what do we charge.
4. **Document money lives on documents.** A charge that is not work (rush
   fee, disposal, credit) exists as a line on the estimate and transits to a
   line on the invoice. It never takes up residence on the Job.
5. **Structural guarantees where they're cheap; an informed human where they
   aren't.** Atoms stay exactly-once-claimable. Agreement lines get a
   quantity-sum invariant. The remaining seam — knowing that a given pile of
   work "is" a given hand line — is closed by the invoicer declaring it at
   reconcile time, which is the one moment anyone actually knows.

## 1. What this changes, in one breath

Subtasks are removed from main. The outcome hand-line stops crystallizing
into a Fee and gains a become-a-Deliverable gesture. Fee lines dissolve into
plain lines that ride the invoice skeleton; the `Fee` model is deleted
outright. Invoices start from the agreement skeleton: claim-mirroring for
backed lines, invoicer-driven atom attachment for plain lines, quantified
line references with a Σ-qty invariant, progress billing via explicit
deduction lines, and est-vs-actual as the wizard's central display. Adopted
from `feature/fees`: task-owned money + supersession deletion + flat tasks
(Phase 1), nullable AC + fallback stamping (Phase 3), outsourced-work PO
reconciliation (Phase 5), and the negative-total invoice send gate.

## 2. Adopted from feature/fees

- **Phase 1 wholesale** (task-owned money): `Task` gains `qty_source`,
  `rate`, `unit_label`, nullable `accounting_category`, resolved-modifier
  snapshots; `source_scheme` is provenance-only (invariant: no compute path
  reads it); RateScheme becomes a freely editable preset with `is_active`
  retirement and a default-preset Configuration key; the supersession
  apparatus (frozen fields, `replaced_by` chains, `(vN)` renames, the
  409/`supersede_url` dance) is deleted; adjustment lines snapshot their
  percent (`adjustment_percent`). **Flat tasks** — scheme-less, typed rate,
  entered qty — are the shape for work-backed charges: setup, delivery, site
  visits. Plan: cherry-pick the Phase 1 commit range from `feature/fees`
  (`73ac97cf..8acc4d10` plus the applicable post-close-out fixes); expect
  doc conflicts, resolve toward this spec.
- **Phase 3** (nullable AC + fallback): task AC optional end-to-end;
  `fallback_accounting_category` Configuration key; invoice compose stamps
  the fallback **on the line** (never back on the atom) and flags it in the
  wizard; QBO push guard against null AC. May need re-implementation rather
  than clean cherry-pick (its commits touch Phase 2 code).
- **Phase 5** (outsourced work): PO-level reconciliation (`bill_total`,
  `vendor_invoice_ref`, per-line `final_price`, `invoice_only` lines,
  REPLACE semantics), rate prompts from `default_material_markup_percent`,
  `linked_po_variances` job costing. The sell side is a flat task; nothing
  in this spec disturbs it. Same cherry-pick caveat as Phase 3.
- **Phase 2, only these fragments:** the negative-total invoice send gate
  (QBO rejects negative-total invoices) and negative-money rendering in
  `frontend/src/lib/format.js`. The rest of Phase 2 (Fee re-scope, signed
  Fee atoms, `freeform_kind`) is superseded — see §4, §5.

**Not adopted:** Phase 4 in its entirety (quantity structures,
`qty_scales_with_parent`, `derived_unit_price`, non-startable parents,
pool child-exclusions, the deliverables `source_task` bridge), and
Phase 2's `freeform_kind` migration chain.

## 3. Subtasks removed

`Task.parent_task` is deleted from main (it predates everything —
2025-08-13 initial structure). One level of task; if work needs sequencing
or reference to another task, the user says so in the description and/or
reorders. Scope of removal:

- Model field + migration; **flatten** existing subtask rows to top-level
  (dev data: 26 rows) rather than delete.
- ~18 uses across `apps/jobs/services.py`, `apps/schedule/services.py`,
  `apps/api/tasks/` — audit each; scheduling simplifies (no parent
  dereference in `expected_worker_time`).
- `TasksPanel.svelte` tree rendering and `TaskDetailPage.svelte` parent
  affordances → flat list.
- The "materials on subtasks?" open question (memory, 2026-08-04) dissolves:
  parent-only attachment, trivially.

## 4. Line taxonomy: material or plain

The **only** behavioral distinction on an unbacked line is whether it
describes a material, because that changes crystallization. Main's
`is_material` flag already encodes it — no `freeform_kind` migration, no
fee kind, no work kind. The system does not need to know a line "is a fee":
fee-ness is just a fact about a plain line (nobody will ever attach work to
it), not a model property.

Line shapes on an estimate, post-change:

| Line | Backed by | At acceptance |
|---|---|---|
| Wizard-composed | ≥1 `EstimateLineItemSource` (task/material) | nothing (atoms already on job) |
| Service line | `service_item` FK | crystallizes → Task (incl. flat tasks: setup, delivery) |
| Catalog material | `inventory_item` FK | crystallizes → Material |
| Bare material | `is_material=True` | crystallizes → established Material (reverse-markup cost, earmark) — unchanged from main |
| Adjustment | `adjustment_service` (+ snapshot percent) | nothing; document-only, recomputes per document |
| **Plain** | nothing | **nothing** |

A plain line covers: outcomes ("3 chairs @ $500"), charges (rush, disposal,
government), credits (negative price — sign rules per the adopted Phase 2
fragments). Its price is an estimate like every other line's. Entry-time AC
requirement on hand-lines is unchanged (`assert_all_hand_lines_have_ac`).

The four-way acceptance discriminator in `acceptance.py` loses its default
branch: service → Task, inventory → Material, bare material → Material,
**else → skip** (no source row is written; the line stays a document line).
Idempotency is unaffected (crystallized lines still gain source rows; plain
lines are simply never candidates). Earmarks step unchanged. CO acceptance
(`co_acceptance.py`) simplifies identically: its crystallizing branches keep
service/inventory/material; its Fee fallback and work-line branches die, and
with them the `claiming_kind` threading — a CO's add/replace of a plain line
is document-level composition only, and adjusting the *work* to match an
accepted CO is the planner's job, same as post-acceptance planning (§8).

## 5. Fee is deleted

With estimate-side charges living as plain lines (§4) and transiting to the
invoice via the skeleton (§7), and with the ad-hoc case handled by "start a
draft invoice and add a hand line" (RM decision, 2026-08-06), the Fee atom
has no remaining territory. Delete:

- `jobs.Fee` model + migration (existing Fee rows: crystallize-in-reverse —
  see Migration, §10), `FeeService`, the `/api/jobs/{id}/fees/` endpoints,
  `FeeModal.svelte`, the "Add fee" affordance on the work surface.
- `SOURCE_FEE` in `EstimateLineItemSource`, `ChangeOrderLineItemSource`,
  `InvoiceLineItemSource` (+ serializer branches, `resolve()` arms).
- The invoice wizard's "Fees" group and always-billable carve-out.
- Fee checks in `validate_data`; Fee references in docs.

There is no pure-money atom. Pure money lives on documents.

## 6. Become-a-Deliverable gesture

A per-line action on the estimate (draft or accepted — deliverable
editability rules unchanged): copy this line's description / qty / units
into a new `Deliverable` on the job, and remember the linkage.

- Available on **any** line, not just plain lines: on an MQ44-type job the
  estimator may spawn the "100× MQ44" deliverable from the backed cutting
  line, or type deliverables directly as today. The gesture is a
  convenience wherever a line happens to correspond to a shippable thing —
  never a classification.
- Linkage is a provenance FK (`Deliverable.source_line` → EstimateLineItem,
  SET_NULL) in the `source_scheme` pattern: display and mismatch-badging
  only, **no compute path, no sync**. CO changes qty 10 → 12: a human
  updates the deliverable; at most a passive mismatch badge (line qty vs
  `qty_ordered`). This re-affirms the feature/fees walk-through decision
  (no live sync, no auto-generation at acceptance, no deliverables driving
  task structure).
- Deliverables otherwise unchanged: unpriced, contract scope, ship-tracked,
  send-gate (≥1 deliverable to send an estimate) intact. **No price field
  is ever added to Deliverable.**

## 7. The invoice: agreement skeleton + reconciliation

The wizard's job changes from "compose lines from a pool of atoms" to
"reconcile the agreement against the actuals." Both sources remain visible;
the skeleton leads.

### 7.1 Quantified line references

New provenance on `InvoiceLineItem`: a reference to the agreement line it
bills — `(agreement_line, qty)` where agreement_line is an EstimateLineItem
or ChangeOrderLineItem (nullable; hand lines on the invoice have none).
Implementation shape: either a nullable FK pair + qty column on
`InvoiceLineItem`, or a reference row table parallel to
`InvoiceLineItemSource`; pick at implementation time (the row table
composes better with multiple deduction rows, §7.4).

**Invariant (Σ-qty):** across *live* (non-cancelled) invoices, the sum of
non-settlement reference qtys against one agreement line ≤ that line's qty.
Enforced in the service under a row lock (NumberGenerationService pattern).
Over-billing beyond the line's qty is a conscious override (charging more
than estimated is legitimate), not a hard wall — surfaced, never silent.
Cancelling an invoice releases its references (mirrors
`release_estimate_claims`). Estimate revision **moves** references to the
new revision's lines alongside the existing source-row move; a CO
remove/replace of an agreement line with live references is blocked, same
family as the can't-retire-invoiced-atoms guard.

### 7.2 Skeleton creation

"Copy from estimate" becomes "start from agreement": one invoice line per
`compose_agreement` line, carrying the agreement's description / qty /
units / price as starting values plus the §7.1 reference (default qty =
remaining). Per-line, at creation:

- **Backed agreement line** → the copy is born with invoice-side claims on
  the same atoms (`InvoiceLineItemSource` rows mirroring the estimate's
  source rows), subject to billability gates: an incomplete task or
  unconsumed material arrives *referenced but unclaimed*, flagged, and
  claimable when ready. This is the piece that lets the wizard populate
  estimate copy-lines with atoms rather than duplicate them.
- **Plain agreement line** → the copy arrives with no claims. The
  reconcile act is the invoicer pulling the relevant atoms *into* it
  (existing add-atoms gesture). This closes the double-billing seam at the
  moment someone actually knows which work was sold by which line.
- **Adjustment line** → copies with its snapshot percent; recomputes
  against this invoice's lines (existing behavior).

Partial skeletons are fine: the invoicer can pull individual agreement
lines instead of the whole document (the cabinets case), and can still add
atoms directly from the pool or add hand lines, as today.

### 7.3 Est-vs-actual is the display

For any invoice line with an agreement reference, the wizard shows:
**estimated** (agreement qty × price), **actuals** (Σ `compute_amount()`
over the line's claimed atoms), and the stored billing values, with
"bill actuals / keep estimate / type something else" as the per-line
gesture. This is the existing in-sync/override machinery presented as the
point of the page rather than a "⚠ out of sync" warning. Atoms remain
whole-claim; there is no per-unit atom slicing.

The **pool** is reframed, not removed: it shows the job's atoms with their
claim state, and its empty state is "every atom is mapped into an
agreement line." Leftover atoms are not "extras" — they are actuals not
yet reflected in any line, and the wizard prompts: bill, fold into a line,
or consciously absorb. Unreferenced pool billing (T&M jobs, estimate-less
jobs) works exactly as today.

### 7.4 Progress billing: per-line lifecycle, family arithmetic, deductions

**No invoice-level mode.** An invoice has no progress-vs-final identity —
each *line pull* does. Settlement is a per-agreement-line event: one
invoice may settle the cabinets line, progress-pull the millwork line, and
T&M-bill the CAD line in the same document. An invoice consisting only of
non-settlement pulls may **display a derived "Progress billing" label**
(customers should know a draw isn't the final accounting); that label is
presentation computed from the pulls, never a stored type.

Kinds of pull against an agreement line:

- **Progress pull:** partial qty at the agreement rate. Typically no atoms
  attached — the work is mid-flight. Counts against Σ-qty.
- **Bill-as-you-go pull (T&M):** claims completed atoms and bills their
  computed amount. Legitimate on *any* invoice — atoms are deliberately
  **not** restricted to settlement invoices (monthly T&M billing is
  atom-billing on non-final invoices and is the most ordinary pattern
  there is). No enforcement is needed; the family arithmetic below cannot
  be lied to.
- **Settlement:** ends the line. Two gestures, chosen per line by the
  invoicer — a choice about the *customer document*, both netting the same
  money:
  - **Settle whole line** — reference at full qty (`settles=True`, exempt
    from Σ-qty); whole-line est-vs-actual comparison; the wizard
    auto-adds **one deduction line per prior live pull** ("Less progress
    billing INV-0012 — −$500"), each carrying the **same AC as the parent
    line** (income nets correctly per category), provenance-linked to the
    prior invoice line, excluded from Σ-qty, editable, deletion warned.
    This re-prices the whole quantity in light of actuals.
  - **Bill remainder** — remaining qty, no deductions; prior pulls' prices
    stand as final for their slices (the pickup cabinet's $500 was a
    sale, not a draw).

**Family arithmetic** (the invariant view over all live pulls against one
agreement line): `billed-to-date` = Σ reference-row amounts — regardless
of which mechanism produced each amount; `actuals` = Σ `compute_amount()`
over atoms claimed by **any** pull in the family; suggested settlement =
actuals − billed-to-date. Draw-then-settle and bill-as-you-go are the
*same arithmetic*: in pure T&M each pull bills exactly its own atoms, so
the settlement suggestion collapses to the newly attached atoms' worth and
the deductions net out by construction. There is no reachable state where
the display lies — atom double-billing is blocked by claims, silent
over-quantity by Σ-qty, and everything else is pricing judgment
(principle 3) taken with true numbers on screen.

- Billed-to-date comes from the reference rows of live invoices — the
  structural record that early money went out the door. Nothing is
  remembered by hand.
- The existing deposit-credit machinery (negative pull of paid deposit
  lines) is the same shape; unification is a later cleanup, not part of
  this work.
- QBO: pushes as ordinary lines; the adopted negative-total send gate
  still applies to the invoice total.

Degenerate cases: a single full pull (the overwhelmingly common case) has
no prior pulls, no deductions, no label, and trivially satisfies Σ-qty —
the invoicer never sees any of this machinery.

### 7.5 What stays structural vs. human

Structural: atoms exactly-once (existing claims); agreement-line Σ-qty
(§7.1); billed-to-date arithmetic (§7.4); mirrored claims for backed lines
(§7.2). Human, by design: deciding that a given set of atoms "is" a plain
line's work (declared at reconcile time, with full context on screen); the
final price of every line (principle 3).

## 8. Acceptance and planning

On a hand-line-heavy job, acceptance now produces deliverables (if the
estimator used the gesture) and an approved job — possibly with few or no
tasks. That is the honest shape: winning the work and planning the work are
different acts, and the **Approved → In Progress** transition has always
existed to hold that gap (planning happens in Approved; releasing to the
floor means it's set up enough to start). No new mechanism; at most a
UI-clarity pass on the Approved state (out of scope here; LATER.md
candidate if it stings in practice).

## 9. User-facing complexity checkpoints

The standing concern is UI complexity, not code complexity. Checks this
design must pass in implementation review:

1. **"3 chairs" is one gesture:** type the line. Become-a-Deliverable is
   one optional click. No kind pickers beyond the existing material
   checkbox, no "priced deliverable" concept anywhere.
2. **The estimator's flow is unchanged** on both archetype jobs (chairs and
   MQ44). Nothing new is required at authoring time.
3. **The common invoice is boring:** start from agreement → every line
   pre-filled, backed lines pre-claimed → adjust → send. Progress/settlement
   machinery invisible unless a line is actually split.
4. **The invoicer never meets** reference rows, Σ-qty, or claim mirroring
   by name — they see est vs. actual per line, billed-to-date on split
   lines, and a pool whose goal state is empty.
5. **Settlement is one plain-language question** on a split line — "Final
   bill for this line: re-price the whole quantity (shows deductions for
   earlier invoices) or bill just the remainder?" — and the "Progress
   billing" label appears on the document automatically, never as a mode
   the user sets.

**UI simplification is a first-class workstream, not a polish pass** (RM,
2026-08-06: the reconcile surface is still super complicated from a user's
perspective). The §10 phase that builds the skeleton/reconcile UI starts
with wireframes or a throwaway prototype reviewed with RM *before*
implementation, with these checkpoints as the acceptance criteria.
**The wireframes are a ground-up redesign of the reconcile surface — not
an increment on the current `ReconcileMode`/wizard UI, which RM rates
suboptimal.** Improving that surface is in scope for this effort, since
the skeleton flow digs through the same territory anyway. Reusable pieces
(claims plumbing, in-sync services) survive underneath; the presentation
starts from the est-vs-actual reconciliation framing, not from the
two-column atom-picker. Default posture: hide every mechanism until the
job's shape forces it into view.

## 10. Migration and sequencing

Phased, each phase leaving main green:

1. **Cherry-pick Phase 1** from `feature/fees` (task money, preset
   RateScheme, flat tasks, adjustment snapshots). Fresh-DB suite run
   (house rule after migration changes).
2. **Subtask removal** (§3): flatten, drop field, simplify services/UI.
3. **Skeleton + references** (§7): reference schema, agreement-start flow,
   claim mirroring, est-vs-actual display. This is the largest UI phase —
   it opens with the §9 wireframe/prototype review with RM before any
   implementation.
4. **Deduction/progress billing** (§7.4) — separable from 3 if needed.
5. **Crystallization narrowing + Fee deletion** (§4, §5): acceptance/CO
   discriminator change; delete Fee. Existing Fee rows: those claimed by a
   live estimate line become nothing (the line is already the record —
   drop the fee source rows; the line reverts to plain); those claimed by
   invoice lines have already been billed (drop source rows, keep the
   invoice lines' stored values); unclaimed job fees are surfaced to RM
   for manual disposition before the migration (expected count: small).
   `validate_data` sweep updated in the same phase.
6. **Phase 3 + Phase 5 adoption** (re-implement or cherry-pick per §2).
7. **Docs pass**: estimates-and-prices, jobs-and-tasks,
   invoicing-and-expenses, data-constraints, schedule.

Each phase: TDD, targeted backend modules + Vitest per task, full suite at
final verification, e2e for user-reachable flows in the same phase.

## 11. Open questions

- §7.1 implementation shape: FK-pair-on-line vs. reference-row table.
- Settlement with **multiple** prior pulls: one deduction row per prior
  invoice (current spec) — confirm the customer document reads well with
  3+ deductions, or allow an aggregate row.
- CO replacing a partially-billed agreement line: blocked (§7.1) — is
  "block" right, or should it force a settlement first? Decide when a real
  case appears.
- Where the draft-invoice-as-charge-parking-lot flow (§5) needs UI help,
  if anywhere.

*(Resolved 2026-08-06: settlement actuals aggregate the whole family's
atoms — folded into §7.4. Atoms-only-on-final-invoices was considered and
rejected: T&M billing is atom-billing on non-final invoices; the family
arithmetic needs no such restriction.)*

## 12. Acceptance walkthrough — the fifteen items

The RM list (2026-08-02 session; compressed record in the feature/fees
spec). Every item must have a defined shape here:

| # | Item | Shape under this design |
|---|---|---|
| 1 | N finished items we manufacture | Plain line ("3 chairs @ $500") + become-a-Deliverable. Work planned as ordinary flat/preset tasks in Approved. Invoice: skeleton line, invoicer attaches the chair-work atoms, est-vs-actual, bill. |
| 2 | Resale material (after cutting parts) | Catalog/bare material line → Material (unchanged). |
| 3 | N parts from a material | Cutting task(s) (preset, machine-minutes) + material line; deliverable via gesture or typed. |
| 4 | Setup fee | Service line → **flat task** (it's work). |
| 5 | Delivery | Flat task (work) — or plain line if nobody tracks it. |
| 6 | CAD/design time | Hourly preset task (unchanged). |
| 7 | Engraving | Preset task, modifiers (unchanged). |
| 8 | Cutting charges | Preset tasks in machine-minutes; wizard translates to per-piece on the document (existing bundle presentation). |
| 9 | Jigs kept for re-use | Ordinary tasks + materials; no asset registry (standing RM decision). |
| 10 | Customer-funded specialized tools | Same as 9. |
| 11 | Outsourced work | Phase 5: flat task sell side, PO link, reconciliation (adopted, §2). |
| 12 | Site visits | Flat task (work, priced up front). |
| 13 | Untracked consumables | Plain line, or percentage adjustment, or absorbed — the policy choice remains open and nothing here forecloses any option. |
| 14 | Deposits | Already built; deposit credits unchanged (§7.4 notes the shape kinship). |
| 15 | Credits | Plain line with negative price on estimate or invoice; negative-total send gate. |
