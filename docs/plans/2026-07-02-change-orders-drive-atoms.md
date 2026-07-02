# Change orders drive work atoms (CO-acceptance crystallization) — starter spec

> **Status: rough starter spec.** Follow-on work, parked alongside the freeform-material
> procurement, expenses, and schedule passes — the current billing-only CO behavior is
> **acceptable and ships as-is** (no bugs; 166 CO tests green). Design-level, not a TDD plan.
> Decisions tagged **[SETTLED]** (agreed), **[DEFAULT]** (chosen here; flag to change),
> **[OPEN]** (to resolve during full speccing).
> Companion: `docs/designs/estimates-and-prices.md` §9 (estimate acceptance — the model to
> mirror) and §"change orders"; the crystallization-timing reconciliation in
> `docs/designs/LATER.md`.

## The problem

Change orders today live entirely in the **document / agreement layer** and never touch the
Job's work atoms:

- `ChangeOrderLineItem` is a pure document delta — `action ∈ {add, remove, replace}`,
  `target_line_item` → an `EstimateLineItem`, no atom-source link.
- `ChangeOrderService._handle_accepted` (`apps/estimates/change_order_service.py:168`) only
  flips the Job `on_hold → approved`. Its docstring: "**no Task/Material mutations**."
- Billing *does* reflect COs — `compose_agreement(job)` (`apps/estimates/agreement.py`)
  overlays accepted-CO deltas on the accepted estimate's lines, and `InvoiceService` bills
  from that — but the Job's `Task`/`Material`/`Fee` atoms are untouched.

Consequence in the job-owns-atoms world (atoms drive scheduling, time/bleps, COGS, earmarks):

- A CO **add** line bills work with **no atom behind it** — not schedulable, not blep-trackable,
  no COGS/earmark.
- A CO **replace** on an atom-backed line changes billing while the underlying atom keeps its
  original qty/rate → schedule/time/COGS diverge from billing.
- A CO **remove** stops billing a line while its atom stays live on the Job.

**Decision (Option 1): CO acceptance should crystallize its deltas onto Job atoms, mirroring
`EstimateAcceptanceService.on_accept`, so amended work becomes real.** **[SETTLED]**

## Scope — two parts

### Part A — CO line authoring gets inventory + service picks

The CO line-add today supports **manual** and **inventory** (`add_line_item_from_pli` exists)
but **not service items**. Bring CO authoring to parity with the estimate "Add line" flow:

- Add a **service pick** to CO line authoring, reusing the estimate pattern
  (`AddServiceItemModal.svelte` + `add-from-template` → Task). **[SETTLED]**
- Keep the **inventory pick** (already present). **[SETTLED]**
- The pick determines the atom **type** crystallized at acceptance — inventory → `Material`,
  service → `Task`, otherwise (freeform/manual) → `Fee` — the same discriminator estimate
  acceptance uses. **[DEFAULT]**
- **[OPEN]** Immediate vs deferred for the service pick, mirroring the estimate
  `AddServiceItemModal` decision (immediate: create the Task now; deferred: crystallize at CO
  acceptance). Whatever the estimate side settles in the LATER "inventory vs service
  crystallization" reconciliation, the CO side must match — do not let them diverge.

### Part B — `ChangeOrderAcceptanceService.on_accept` (new)

A new service, parallel to `EstimateAcceptanceService.on_accept`, invoked from
`_handle_accepted` **after** the Job flips to `approved` (atom mutations are blocked while
`on_hold` by `_assert_job_not_on_hold`, so crystallize once the status is `approved`, inside
the same `transaction.atomic()`). It walks the CO's `ChangeOrderLineItem`s in `line_number`
order and applies each delta to Job atoms:

- **add** → crystallize a new atom by type (inventory → `Material` via
  `MaterialService.create_on_job`; service → `Task` via `ServiceItem.generate_task`; else →
  `Fee`), exactly as estimate acceptance does for hand-lines, and **link it back to the CO
  line** (provenance — see [OPEN] #1). **[DEFAULT]**
- **remove** → resolve `target_line_item` → its source atom → **cancel the Task**
  (`TaskLifecycleService.cancel_task`, which preserves bleps — cancelled-task time stays
  **billable**). **[SETTLED for Task targets.]** **[OPEN]** for Material / Fee targets
  (release earmark / restock / unconsume a Material? delete or tombstone a Fee?).
- **replace (changed)** → likely **cancel-then-re-add**: cancel the target's old atom
  (bleps preserved) and crystallize a new atom from the CO line's values. **[OPEN — work out
  the mechanics during full speccing]** (preserving billable bleps on the cancelled Task,
  the est/actual split on the new Task, and ordering).
- After the walk, run `InventoryService.create_earmarks_for_job(job)` so any crystallized
  Materials earmark — same as estimate acceptance. **[DEFAULT]**

## Key design questions [OPEN]

1. **CO-line → atom provenance link (avoid double-billing).** `compose_agreement` already
   emits accepted-CO deltas as billing lines, and the invoice also has `InvoiceLineItemSource`
   atom links. If acceptance *also* crystallizes atoms, the same work could be billed twice
   (once as a CO agreement line, once as an atom). Estimate acceptance solves the analogous
   problem by linking a crystallized Fee back to its estimate hand-line
   (`EstimateLineItemSource(source_type='fee')`, surfaced as `source_fee_id` in
   `compose_agreement`). The CO path needs an equivalent — a `ChangeOrderLineItemSource` (or a
   field) linking each CO line to the atom it created/cancelled — so billing traces the atom
   and counts it once.

2. **Billing source of truth after crystallization.** Decide whether the invoice keeps
   billing from `compose_agreement` (document-of-record) or shifts to the atoms. They must
   agree so CO work bills exactly once. Simplest likely answer: agreement stays the billing
   record; crystallized atoms are the *work* mirror, linked via #1 so `compose_agreement`
   knows they exist. Confirm against `InvoiceService` + `apply-everything`.

3. **`target_line_item → atom` resolution.** `target_line_item` is an `EstimateLineItem`;
   resolve to its atom via `EstimateLineItemSource`. Handle all three cases the target can be:
   atom-backed (Task/Material), or a hand-line that was crystallized into a `Fee` at estimate
   acceptance, or an adjustment line (no atom — reject as a remove/replace target?).

4. **Remove/replace semantics per atom type.** Task = cancel (settled). Material: release its
   earmark, restock, and/or unconsume if already consumed? Fee: hard-delete or tombstone (a
   removed Fee may still owe a billable trace)?

5. **`on_hold` timing / guard.** Crystallize within the accept transaction after
   `status → approved`; or give `ChangeOrderAcceptanceService` the same scoped guard-bypass
   `EstimateAcceptanceService` uses. Confirm no `_assert_job_not_on_hold` trips mid-accept.

6. **Multi-CO ordering.** Crystallization must apply accepted COs in acceptance order without
   double-applying, and dovetail with the known `compose_change_order_diff` multi-CO baseline
   weakness (its docstring: baseline is the flat accepted estimate, not `compose_agreement`).
   Fixing the multi-CO diff baseline likely belongs in this pass too.

## Relationship to existing work

- **Mirrors** `EstimateAcceptanceService.on_accept` (`apps/estimates/acceptance.py`) — copy its
  shape (per-line type discrimination + `create_earmarks_for_job`).
- **Reuses** the estimate "Add from Service" pattern (`AddServiceItemModal` +
  `add-from-template` + `line-items-from-atoms`) for Part A.
- **Shares** the inventory-vs-service crystallization-timing reconciliation (LATER) — resolve
  the CO and estimate sides to the same model.

## Rollout / testing

- No data migration; new behavior applies to COs accepted after it ships. Current billing-only
  COs stay valid until then.
- TDD, parallel to `tests/test_acceptance_fees.py`. Cases: CO **add** → Material/Task/Fee
  crystallized + earmarked; **remove** → target Task cancelled with **bleps preserved and
  still billable**, atom gone from the live work set; **replace** → cancel-then-re-add;
  **no double-billing** (agreement vs crystallized atoms count once); multi-CO acceptance order.
