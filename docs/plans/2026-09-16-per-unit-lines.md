# Per-unit line items ("10 chairs")

Status: DESIGN — discussed RM ↔ Claude 2026-09-16, not yet planned/implemented.
Branch context: feature/estimating (builds on claims-by-construction,
docs/plans/2026-08-15-estimating-structure.md).

## 1. Problem

A job to build 10 identical chairs wants to be estimated per-unit: plan the
steps and materials for ONE chair (cut parts 45 min, assemble 30 min, 4 BF of
oak…), then quote "Dining chair × 10 @ $150". Today the only options are one
lumpy task per line ("build 10 chairs") or baking ×10 into every task's
est_qty, which loses the per-unit structure and makes a qty change touch every
atom.

Resurrecting subtasks (parent "build a chair" qty 10, per-unit children) was
considered and rejected: it re-opens the parent-vs-child estimated/actual
reconciliation problem that got subtasks removed (better-fees §3), and it
forces a leaf-vs-parent decision on every consumer of "the job's tasks"
(board, schedule, bleps, completion, assignment). `Task.parent_task` stays
dormant.

Instead, the multiplier lives in the **projection layer**: the estimate line
already has `qty`, and line price semantics are already per-unit
(qty × price = total). This feature makes the line's *derivation from its
atoms* optionally per-unit too.

The Deliverable is explicitly NOT involved: `Deliverable.source_line` is
provenance-only with no compute path (better-fees §6) and deliverables are
optional. The line is the origin of the "10"; the deliverable mirrors it.

## 2. Design principle

> **Atoms always speak operational totals; claims carry the per-unit
> agreement snapshot.**

- Task `est_qty`, `est_worker_time`, and Material `quantity` always hold
  whole-job totals (7.5 h, 40 BF). Everything operational — the schedule
  forecast, the assignment gate, procurement, earmarks, the job overview,
  est-vs-actual on the task pane — keeps reading atom fields exactly as
  today, with no claim lookups anywhere outside the estimate surface.
- The per-unit numbers (45 min/chair, 4 BF/chair) are agreement facts. They
  live on the **source rows** (`EstimateLineItemSource`,
  `ChangeOrderLineItemSource`) — the table whose whole job is recording how a
  line projects an atom. They move with the claims across revisions for free
  (revise_estimate moves source rows), and they die when the claim dies, so
  an un-bundled atom is always self-coherent (a total is meaningful with no
  line attached; a per-unit number would not be).

Why per-unit must be *stored*, not derived by division: after a CO cuts 10
chairs to 8 with 40 BF already on the job, `quantity ÷ line.qty` would
silently reprice the line at 5 BF/chair. The customer agreed to 4/chair;
procurement surplus must not leak into the agreed price.

## 3. Data model

- `EstimateLineItem.per_unit` — BooleanField, default False. Same field on
  `ChangeOrderLineItem`. NOT on InvoiceLineItem (invoice rework is a later
  design area; see §11).
- `EstimateLineItemSource.per_unit_qty` — DecimalField(10,2), null=True.
  Same field on `ChangeOrderLineItemSource`. Populated only for claims on
  per-unit lines; always NULL otherwise.
- Copy propagation: `revise_estimate`'s line copy and the CO replace-line
  copy must carry `per_unit` (source rows move, so `per_unit_qty` travels by
  itself).

Jurisdiction: `per_unit` is only settable on lines with no catalog identity
and no adjustment — exactly the set MintService accepts, plus bundled lines.
Catalog lines never offer it: their 1:1 crystallization already speaks totals
(`generate_task(est_qty=li.qty)`, `Material.quantity=li.qty`).

## 4. Derivation and sync

Per-unit amount of one claim:

- task source: `per_unit_qty × task.effective_rate()`
- material source: `per_unit_qty × material.sell_price`

(Rates stay live from the atom — a rate edit reprices the per-unit sum, same
as today's derivation. Only the quantity is snapshotted.)

Sync check (`BaseWizardService._is_in_sync`) branches on the line's flag:

- per_unit=False (today's rule, unchanged): `price == round(Σ atom_amounts / qty, 2)`
- per_unit=True: `price == round(Σ per_unit_amounts, 2)` — no division; the
  line total is qty × that price by the existing qty×price math.

Backing chips: a per-unit in-sync line reads e.g. "planned work · per unit".
Kind-preserving edited split unchanged ("planned work · edited").
`_resync_in_sync_line_item` gets a per-unit branch: recompute price as the
per-unit sum.

## 5. Plan-first flow (primary): the bundle modal

User plans one chair's tasks/materials in the Tasks pane with per-unit
values, then bundles them into a line.

Reframing (RM 2026-09-16): keep-total and per-unit are not a toggle plus a
feature — they are the TWO interpretations of how atom values relate to the
line's qty, one binary choice: **"the atom values you selected describe
___"** — *the whole line* (keep-total: total = Σ atoms; per-unit price
derived as Σ ÷ qty — today's behavior) or *one unit* (per-unit: price =
Σ atoms; total derived as qty × Σ). Same inputs, opposite derivation
direction, never both. The modal models this as one choice, not stacked
checkboxes.

Bundle modal additions:

1. **The interpretation choice** (whole-line vs one-unit, above; defaults to
   whole-line, today's behavior). When "one unit" is chosen:
   - The modal shows a per-atom preview table: each atom's current value is
     treated as per-unit, with a before → after column
     ("cut parts: 45 min → 7 h 30 m total"; "oak: 4 BF → 40 BF total").
     The reinterpretation must be visible, never implicit — the checkbox is
     re-reading numbers the user entered earlier in another surface (§12 Q1).
   - qty must be entered before/with the choice (the multiplication needs
     it); price derives as the per-unit sum and the total updates live.
2. **On confirm**, atomically:
   - create the line (`per_unit=True`) and claims, each claim stamped with
     `per_unit_qty` = the atom's pre-multiplication value;
   - **stamp the atoms to totals** — task `est_qty ×= qty`,
     `est_worker_time ×= qty`, material `quantity ×= qty`. This is the first
     time estimate composition mutates atoms; it is deliberate, announced by
     the preview table, and happens exactly once at the moment the
     multiplier becomes known.
   - For non-hour tasks with no `est_worker_time`, the modal offers a
     per-unit schedule-time input (optional — the assignment gate remains
     the net; see §8).
3. **"Split materials onto their own line" checkbox** (only meaningful with
   ≥1 task and ≥1 material selected): emits TWO sibling per-unit lines from
   one gesture — a labor line claiming the task atoms and a materials line
   claiming the material atoms, both with the same qty. No structural link
   between the siblings (no line-group object — that's parent-task
   complexity sneaking back in via the document); drift badges and the CO
   reminder (§9) are the net.

## 6. Mint-first flow (post-acceptance checklist)

A plain hand line "10 chairs @ $150" accepted → checklist → "Generate
work…". The mint modal gains the per-unit question, asked ONCE per line:

- "Will the tasks and materials you plan here describe one chair, or all
  10?" → sets `line.per_unit`; subsequent mints against the same line
  inherit the answer (the question disappears).
- Each minted atom is created directly WITH totals (per-unit input × qty
  stamped before first save — the established `stamp_from_scheme` pattern),
  and its claim records the per-unit input.
- Multiple mints per line already work (answeredness = the line has ≥1
  source row); nothing in the checklist/auto-release machinery changes.

MintService guards unchanged; `claim_atom_for_line` additionally accepts and
stores `per_unit_qty` when the line is per-unit.

## 7. What explicitly does NOT change

- **Schedule**: forecast reads `est_worker_time` (a total) exactly as today.
  No claim lookups in ScheduleService, the overview, or the board.
- **Assignment gate**: AssignModal + service-level checks (missing/zero
  `est_worker_time` blocks assignment) unchanged — and since atoms speak
  totals, the number the assigner enters or sees is directly correct; no
  "×10 hint" needed (that mitigation died with the atoms-per-unit variant).
- **Invoicing**: bills actuals; per-unit lines don't exist on invoices yet.
- **Pool walk, claim exclusivity, checklist answeredness, auto-release,
  catalog crystallization**: all untouched.
- **Task pane est-vs-actual**: direct comparison of totals, correct as-is.

## 8. Drift detection

After stamping, the atom totals and the agreement can diverge (CO qty
change, hand edits). The document side is always live-derived
(price = Σ per-unit amounts; total = qty × price), so the AGREEMENT never
goes stale — only the atom stamps do. Detection rule, per claimed atom on a
per-unit line:

- task: badge when `est_qty ≠ per_unit_qty × line.qty` (and analogously
  `est_worker_time` vs its stamped expectation, where one was stamped)
- material: badge when `quantity ≠ per_unit_qty × line.qty`

Badges OFFER a one-click restamp; they never auto-apply. For labor the offer
is safe to accept (projections, no physical reality); for materials it is a
human decision (stock may be cut, ordered, earmarked, returnable). Same
interaction shape as the existing deliverable qty mismatch badge.

## 9. Change orders

- Replace-lines copy `per_unit`; the moved source rows keep `per_unit_qty`.
- A CO that re-quantifies a per-unit line leaves the document correct by
  derivation and raises §8 badges on the atoms.
- Sibling reminder: when a CO changes qty on a per-unit line, the CO surface
  lists the job's OTHER per-unit lines sharing the old qty ("Materials for
  dining chairs is also qty 10 — update it too?"). Reminder only, no
  enforcement.

## 10. Editing the per-unit recipe later

Post-bundle, per-unit values are estimate-side data: re-open the bundle
composition (draft docs only, as today), adjust `per_unit_qty`, and the
modal offers the corresponding atom restamp. The task pane is NOT where
per-unit numbers are edited — a task edit is replanning (totals); a
per-unit edit is repricing (agreement). Un-answering rules unchanged:
removing a claim still deletes the line.

## 11. Future synergies (out of scope, recorded so the design leaves room)

- **Progress billing** (better-fees invoicing direction): an explicit
  per-unit price makes "bill 6 of 10 chairs" natural arithmetic.
- **ServiceItem per-unit schedule time**: catalog crystallization of
  non-hour lines currently lands `est_worker_time=None` (assignment gate
  catches it later). A ServiceItem-carried per-unit duration multiplied by
  line qty at crystallization would close that with the same stamp shape.
- **Floor grouping**: if "which steps make a chair" ever matters on the
  board, the claim already knows — a group label from the claiming line is
  cosmetics, not schema.

## 12. Phasing and open questions

**Phasing (RM 2026-09-16): modal UI refinement is the LAST phase.** Build
the functionality first — fields, derivation, stamping, mint flow, drift
badges — against the existing modal with minimal additions, then refine the
bundle modal's structure as a dedicated final phase once the behavior is
real and testable. (The keep-total confusion is independently LATER-logged;
that rework lands in this final phase.)

RM senses a UI problem not yet pinned down. Candidates found while writing:

1. **The reinterpretation moment.** The per-unit checkbox retroactively
   re-reads numbers the user typed in the Tasks pane ("45" meant per-chair
   all along, but the app only learns that at bundle time). If the user
   actually planned totals and checks the box anyway — or plans per-unit and
   forgets the box — every stamp is wrong by ×qty. The preview table (§5) is
   the mitigation; is it enough? There is no way for the Tasks pane to know,
   at planning time, that "per-unit-ness" is coming.
2. **Bundle modal load.** The interpretation choice, split-materials, a
   per-atom preview/edit table, and an optional schedule-time input is a
   lot of modal. The whole-line/one-unit reframing (one choice, not stacked
   toggles) helps; the full restructure is the dedicated final phase above.
3. **Order of entry.** Both interpretations need qty, but derive in
   opposite directions (whole-line: price ← Σ ÷ qty; one-unit: total ←
   qty × Σ). The modal's field order/live-updates must read clearly in
   both. Final-phase concern.
4. **Materials-split sibling qty.** Two lines carrying "10" with no
   structural link — is the CO reminder (§9) discoverable enough, or does
   this want a stronger cue at edit time?
