# Job owns the work; documents are lenses

> **Status: design spec (direction agreed; mechanics being pinned).** This replaces the
> earlier pricing-redesign exploration (the fee-model and current-state-by-example drafts,
> now deleted) — the model below is the one to build toward. Design-level, not yet a TDD
> task plan. Decisions are tagged **[SETTLED]**, **[DEFAULT]** (chosen here; flag to
> change), **[DEFERRED]** (out of immediate scope).

## The core move

Today work is split across two parallel representations: **plan-stage** atoms
(`PlanTask`, `PlanMaterial` on an `EstWorksheet`) and **job-stage** atoms (`Task`,
`Material` on the `Job`), bridged by carry-over at estimate-accept. The estimate
projects the plan atoms; the invoice projects the job atoms.

Collapse it. **The Job owns one live set of work objects. Documents are optional lenses
over that set.**

- **Remove `PlanTask`, `PlanMaterial`** (and never introduce `PlanFee`). A `Task`
  already carries both axes — `est_qty` (the quote) and `actual_qty` (the actual) — so
  it is a strict superset of `PlanTask`. The estimate reads `est_qty`; the invoice reads
  `actual_qty`; **same object**, no carry-over bridge.
- **Retire `EstWorksheet` as an atom container.** Work hangs directly on the Job. (This
  finishes the est-consolidation direction — one Plan per job, the Plan as a view on the
  job — rather than reversing it.)
- **Documents (`Estimate`, `Invoice`) become line-item lists** where each line *may*
  link to a live job atom, but isn't required to. Projection is permitted, not mandated.

### Why (the payoffs this unlocks)

1. **It removes the forced work↔line-item linkage** that has caused recurring friction
   (the one-off-charge problem, the Phase-6 "every line must trace to an atom" rigidity).
   Make the link optional and those problems dissolve — you just write the line.
2. **Est-vs-actual variance is trivial** — one Task holds `est_qty` and `actual_qty`
   side by side; no `PlanTask`↔`Task` join to reconstruct it.
3. **Pre-approval work becomes first-class and correctly costed.** A customer meeting,
   site visit, or material-research task can be worked and blepped against the Job
   *before* any estimate is approved. If the job is never approved, that effort shows up
   — appropriately — as a **loss** on the Job, instead of being invisible because it had
   nowhere to live in the plan stage. (This is *why* Tasks must be internal work markers
   owned by the Job, not estimate-stage artifacts.)
4. **Fee collapses from a triple to a single, well-motivated object** (next section).
5. **Half the work-object model and all the carry-over machinery go away** (the accept
   signal, the copy, claim-uniqueness as a hard global constraint).

## The three atom types (all owned by the Job)

| Atom | Backed by | Pricing | Quantity |
|---|---|---|---|
| **Task** | `RateScheme` (NOT NULL) | metered: `rate × qty` (+ modifiers) | `est_qty` (quote) / `actual_qty` (bleps or entered) |
| **Material** | `InventoryItem` (or freeform) | `quantity × sell_price` | quantity (snapshot) |
| **Fee** | free-text amount; optional `FeeItem` | fixed `quantity × unit_rate`, frozen | quantity × unit_rate, no actual |

**[SETTLED] `Task.rate_scheme` stays NOT NULL.** Every Task is metered work. The
scheme-less-task / one-off-amount-on-task idea is **dropped** — one-off amounts are
**Fees**, not tasks. Task stays pure work; money never sits on it (only the scheme FK +
modifiers, as today). `RateScheme` keeps `elapsed_time`, `entered_qty`, `percentage`;
**`flat_fee` is removed** (its job is now Fee's).

**[SETTLED] Fee is one object, not three.** There is no Plan layer, so there is no
PlanFee. A Fee is the **crystallized form of an accepted hand-line**: born at estimate
acceptance, it lives on the Job as a billable atom and joins the invoice's atom pool. It
carries `quantity`, a snapshotted `unit_rate`, an `accounting_category`, an optional
`task` link (for "the work behind it"), and an optional `fee_item` source. Charge =
`quantity × unit_rate`, computed, frozen (no `actual_qty` — the moment you want one, the
thing was metered, so model it as an `entered_qty` Task instead).

**[DEFAULT] `FeeItem` (the fixed-charge catalog) is optional / deferred.** Hand-lines
work without a catalog. Build Fee first; add `FeeItem` (a reusable named amount, parallel
to `InventoryItem`/`ServiceItem`) only if cataloguing common fees earns its keep.

## Documents as lenses

A line item (`EstimateLineItem` / `InvoiceLineItem`) carries its own snapshot
(description, qty, price — the existing `BaseLineItem` pattern) **and** an *optional,
severable* link to a Job atom. Three kinds of line:

- **Atom-backed line** — links to a Task, Material, or Fee on the Job. On a **draft**
  document it is *live* (re-derives from its atom; see Liveness below).
- **Hand-authored line** — a free-typed description + amount, no atom. Crystallizes into a
  **Fee** at acceptance.
- **Frozen snapshot line** — was atom-backed, link since dropped (see supersession). Keeps
  its last snapshot as a historical record; never reprojects.

**Picking from the Materials list generates a `Material` on the Job — it is an
atom-backed line, not a hand-line.** The "Add line" flow has two shortcuts out of
free-text into the atom world: pick an `InventoryItem` (or enter a freeform material) and
a real **`Material` is created on the Job** (COGS / inventory / earmark flows intact);
pick a **Service** and a **`Task`** is created the same way. Only genuinely free-typed
text with no catalog pick stays a hand-line → Fee. Materials are the one place
hand-authoring and atoms overlap, which is why that pick produces a first-class atom
rather than a flat amount.

### Liveness — what re-derives, and when

Liveness is a property of the **(line, document-state)** pair, and in practice it is an
**estimate-side** concern:

- **Draft estimate** → atom-backed lines are **live**: each tracks its atom's `est_qty`
  and shows **out-of-sync** if the user edits the Task, reconciled via the Phase-4 "keep
  mine / re-pull" machinery. This is the only place reprojection runs.
- **Invoice (any state)** → lines **do not track a moving value**. An atom is invoiceable
  only once its **Task is marked complete**, and a complete task's `actual_qty` is
  **locked** — actuals are actual, they don't drift. So an invoice draws from
  already-frozen values; the only draft-invoice freedom is *which* locked atoms to bill
  and across *how many* invoices, never per-line recomputation. **[SETTLED — keeps current
  behavior.]**
- **Sent / accepted / superseded** documents freeze their lines outright (a historical
  record — a sent $500 invoice must not silently change).

**Atoms are never locked by a backing line. [SETTLED]** A Task/Material can always be
edited or deleted regardless of what references it (Tasks are internal work markers; work
never stops because a document exists). The *document* absorbs the consequence: a live
draft-estimate line surfaces as out-of-sync and the user reconciles; an invoice line's
source is already locked at task-completion, so there's nothing to drift; a frozen line
simply doesn't move.

### Add-line: one affordance everywhere

Estimate and Invoice share one "Add line" picker over the Job's catalogs:
- **Service** (`ServiceItem` / `RateScheme`) → creates/links a **Task**.
- **Material** (`InventoryItem`, or freeform) → creates/links a **Material**.
- **Free-text / `FeeItem`** → a **hand-line** (which becomes a **Fee** at acceptance), or
  directly a **Fee** on an already-approved job / an invoice.

### Estimate revision & supersession **[SETTLED]**

**Tasks are always the latest plan.** When an Estimate is superseded:
- The superseded document **keeps its line items** as a frozen snapshot (its lines drop
  their live atom links — they become frozen snapshot lines). It is a historical record;
  it does not come back and does not hold atoms.
- The live atoms (Tasks/Materials) belong to the Job, so the **new** Estimate references
  them by default. The user may then **release** them (the line goes away; the atom stays
  on the Job, now **flagged as unclaimed** — informational, never forced), **hold** them,
  or **modify the Tasks and regenerate** the lines.

**Unclaimed atoms are flagged, not pruned.** A Task/Material on the Job that no current
document references is surfaced as unclaimed (e.g. pre-approval work, released work) but
is allowed to persist indefinitely. Trust the user; Tasks are internal markers.

### Acceptance **[SETTLED] / [DEFAULT]**

Accepting an Estimate **approves the Job**. At that moment:
- Each **hand-line** (free-text, non-atom) on the accepted estimate **crystallizes into a
  Fee** on the Job (snapshot its amount → `unit_rate`/`quantity`; carry its AC; link a
  task if one was named). Material-picked and Service-picked lines already have their
  atoms — nothing to convert.
- **[DEFAULT] Earmarking is acceptance-triggered:** the Job's current Materials earmark
  inventory when the Job goes approved (a speculative quote must not reserve stock). Same
  trigger as today, now over the live set instead of carried-over rows.
- **No Tasks are pruned.** The shop may have created pre-approval or exploratory tasks;
  they remain, usable however the shop wants. Post-approval, further changes flow through
  the **change-order** process.

### Invoice **[SETTLED] / [DEFAULT]**

**Only complete Tasks are invoiceable**, and a Task's `actual_qty` **locks at
completion** — current behavior, and it stays. Invoice lines therefore never drift (see
Liveness). **Fees join the atom pool the invoice draws from** (Tasks via the locked
`actual_qty`, Materials, Fees); a charge discovered at invoice time is just a new Fee (or
a hand-line on the invoice).

The expected flexibility is at the **scope** level, not the line-value level: Tasks that
weren't on the Estimate get added for all sorts of reasons, and **additional invoices** are
generated to capture them. **[DEFAULT]** an atom may be claimed by one estimate line and
one invoice line, but **at most one invoice** — so the same completed Task can't be billed
across two progress invoices.

## Job lifecycle gating **[SETTLED, with detail to confirm]**

The only new gating: operational surfaces (board, schedule, worker queues, cross-job
task views) must continue to scope by **Job status**, so a quote-stage Job's tasks don't
appear in shop operations until the Job is approved. This filter already exists at the
job level; pre-approval work is visible *on its Job* (correct — that's the estimate/early
work you're building) but not in cross-job operational views. No per-task "speculative"
flag is required.

## Out of scope / deferred

- **[DEFERRED] Change-order ↔ Fee interaction.** COs are the post-approval editing
  channel; exactly how a CO adds/modifies/supersedes Fees is a follow-on, not a blocker.
- **[DEFERRED] `FeeItem` catalog** (above).
- **Deposits** — still a separate animal (negative, deferred credit); not modeled here.

## Schema change + regenerate — no data migration

This reshapes too much to backfill. **No data migrations.** The plan: ship the **schema**
migrations, **wipe the dev DB**, revise the **generator**, and **regenerate the dataset
from the spreadsheet inputs**. (The dev-DB wipe/regen is the user's action — the agent
never writes the dev DB.)

**Schema migrations (structure only):**
- Drop `PlanTask`, `PlanMaterial`; retire `EstWorksheet` as an atom container.
- Add `Fee` (and `FeeItem` if/when the catalog is built).
- Drop `flat_fee` from `RateScheme.ALGORITHM_CHOICES` (keeps `elapsed_time` /
  `entered_qty` / `percentage`).
- Make the line-item → atom link optional + severable; line items keep their snapshot
  fields.
- Retarget template generation to the Job (`generate_tasks_for_job` / materials-for-job);
  drop the worksheet generators.
- Move earmarking to the acceptance hook over the Job's live Materials.

**Generator (nealsdata converter) revision, then regen:**
- Emit Tasks/Materials directly on Jobs — no plan atoms, no worksheet container.
- Emit **Fees** instead of minting `Flat Fee $X` RateSchemes
  (`nealsdata/converter/build.py` flat-fee path): one-off amounts → off-catalog Fees; a
  recurring delivery-style fee → a Fee (or a `FeeItem` if that catalog is built).
- Regenerate the dataset from the spreadsheet inputs.

> Reminder for implementation: never write the dev DB. All model behavior is verified via
> `python manage.py test` (test DB), one test process at a time; fresh build (no
> `--keepdb`) after any migration. Line-item deletes route through
> `LineItemService.delete_line_item_with_renumber`.
