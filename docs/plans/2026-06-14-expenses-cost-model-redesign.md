# Expenses — cost-model redesign (PROPOSAL, under review)

**Status:** Proposal for offline review — **not decided.** Captures the redesign
worked through on 2026-06-14. It evolves the *as-built* Expense↔Job feature
(`docs/plans/2026-06-13-expenses-job-attribution-redesign.md`) after testing
surfaced a cost-math bug and a deeper modelling question. Written so the whole
model sits in one place; the **Open questions** at the end are the parts still to
settle. Sections are tagged **[DECIDED]**, **[PROPOSED]**, or **[OPEN]**.

---

## 1. Why revisit — what the as-built model gets wrong

The shipped feature lets an Expense attach to a Job, optionally link/create a
Material, and "actualize" that material's cost. Testing exposed three problems
that share one root:

- **Division/clobber bug.** Linking a $73.33 expense to a 20-unit material set
  `unit_cost = amount / quantity = 73.33 / 20 = 3.67`, destroying the real
  per-unit cost. (Fixed defensively in commit `f57b5bc`, but it pointed at a
  deeper issue.)
- **Multi-item receipts don't fit.** One real receipt is often several things —
  "3 ft of steel **and** 10 brackets." A single material can't represent that.
- **Inventoried "top-up" double-counts.** Need 10 plywood sheets, 7 in stock; a
  worker buys the other 3 and records an Expense. If that becomes a second
  3-sheet material alongside the 10-sheet one, the job has **13 billable/
  consumable sheets for 10 physical sheets** → cost counted twice.

**Root cause:** `Expense.amount` is a *quantity-less total*, and the as-built
code tried to derive a per-unit material cost from it; separately, cost
recognition mixes purchase-time and consumption-time inconsistently, so the same
physical units can be charged twice.

**Key reframing:** the top-up problem is a **quantity** problem, not a cost
problem — no dollar-splitting trick fixes two consumable lines covering the same
physical units.

---

## 2. Decided constraints

**[DECIDED] 2.1 — Single `amount` on Expense; no line items.**
Itemizing (qty × unit_cost per line, with tax/surcharge) *is* a Bill. The app
already has `Bill`/`BillLineItem` on `BaseLineItem` with per-line tax. An Expense
is deliberately the lightweight path: "a Bill that's already been paid, requires
no issuance, and may be owed back to an employee (reimbursement)." Holding this
line is what keeps Expense from becoming a second, drifting Bill engine.

**[DECIDED] 2.2 — Expenses never link to / join an existing Material.**
Joining an existing material was the source of the clobber/division mess. Gone.

**[PROPOSED] 2.3 — An Expense may create its *own* materials: zero, one, or many.**
This is how the multi-item receipt is handled without line items: the expense
spawns N materials, each independently quantified (qty + unit_cost the user
reads off the receipt). **Their costs need not sum to `amount`** — the gap is
unaccounted tax/shipping, and that's fine (no reconciliation, no tax engine).
UI reuses the existing "add another row" line-item pattern.

**[DECIDED] 2.4 — No task attachment.** Not on the Expense, not on the materials
it creates. A material attaches to a task *only* so its inventory is consumed
when the task starts; an Expense records a purchase that already happened, not a
consumption plan, so task-timing has nothing to do. (The existing
"non-inventory material on a task" oddity is left as-is — out of scope.)

**[DECIDED] 2.5 — Expense↔Bill boundary = no per-line tax/surcharge.**

---

## 3. The cost model (the core proposal)

**[PROPOSED] Recognize cost differently for inventoried vs. non-inventoried.**

| | Cost recognized | The expense's role | Creates a job-material? |
|---|---|---|---|
| **Non-inventoried** (freeform material, service, one-off) | at **purchase** | the cost itself (`amount`) | yes — its own cost line |
| **Inventoried PLI** | at **consumption** (`qty × unit_cost`) | a **receipt** (QOH ↑) + recorded cash | no separate consumable line — tops up the shelf the existing material draws from |

Why this resolves everything:

- A **PO already works this way** — POs aren't in `_spent`; the cost lands when
  the material is consumed. Making inventoried expenses behave like receipts just
  makes Expense and PO consistent for inventoried goods.
- The **top-up double-count disappears** because there's only ever the one
  consumable line (the 10-sheet material); the expense refills QOH, the single
  material consumes 10 once. The "second material with no actuals" you described
  is, precisely, *not creating a second consumable line*.
- The two stuck points dissolve:
  - *"If they bought 5 not 3, the extra is lost."* No — the 2 extra stay in QOH
    as real stock for the next job. Nothing lost; it's literally inventory.
  - *"No clean way to subtract the inventory cost from the expense."* You don't
    subtract — under cost-at-consumption an inventoried expense's amount simply
    **isn't a direct job cost**; it's funding realized at consumption. Nothing to
    net out.

This also reframes "join vs. don't join": you don't join for **cost** (no
clobber), but inventoried purchases effectively join at the **inventory** level
(top up QOH/earmark for the existing need). Because inventoried cost is at
consumption, the material's `unit_cost` is never touched by the expense, so the
clobber problem can't even arise.

---

## 4. Interaction grid (the surviving shapes)

Payment method (company vs. personal/reimbursable) is orthogonal — applies to
every row.

| # | Shape | Job | Material it creates | Inventory effect | Cost → Job P&L | Billable in wizard |
|---|---|---|---|---|---|---|
| O | Overhead | — | none | none | not on any job | no |
| 1 | Job service cost | ✓ | none | none | `amount` (purchase) | expense atom |
| 2 | One-off freeform good(s) | ✓ | 1..N freeform | none | `amount` (purchase) | via each material |
| 3 | PLI good, non-inventoried | ✓ | 1..N PLI, cost set by user | none | `amount` (purchase) | via each material |
| 4 | PLI good, **inventoried** | ✓ | **none** — a receipt (QOH ↑) | **QOH ↑ (+ earmark)** | at **consumption** | via the consuming material |
| ✗ | ~~Link existing material~~ | — | — | — | — | — (dropped, §2.2) |
| ✗ | ~~Task-attached expense/material~~ | — | — | — | — | — (dropped, §2.4) |

Row 4 is the behavioural change; rows O–3 are essentially the as-built model with
the cost recognised at purchase.

---

## 5. Worked example — the plywood top-up

Need 10 sheets; 7 in stock (a 10-sheet inventoried Material on the job, earmarked
10). Worker can't start the task (see §6), goes and buys 3 (or 5).

1. Records an Expense for the sheets (the cash actually paid, tax included).
2. Because the item is **inventoried**, the expense is a **receipt**: QOH 7 → 10
   (or 12). No second consumable material is created.
3. Task start now succeeds; the 10-sheet material consumes 10, charging the job
   `10 × unit_cost` **once**.
4. If 5 were bought, 2 remain in QOH as stock for a future job — tracked, not
   lost. The job is charged for the 10 it used.

No double-count; the system "notices at the right time" — which is consumption =
task-start time.

---

## 6. Task-start consumption mechanics (why §3 lands cleanly)

Confirmed in code (`apps/jobs/services.py`):

- First worker to start a task: `start_work` (inside one `transaction.atomic()`)
  → `_promote_pending_task` flips `pending → in_progress` and calls
  `MaterialService.consume()` on **every** `task.materials`.
- `consume()` for an inventoried PLI raises
  `Cannot consume {qty} {units} of {code}: only {qty_on_hand} on hand.` when
  `qty_on_hand < qty`.
- That raise propagates out of the atomic block → **the whole start rolls back**:
  no blep, task stays `pending`, nothing consumed. **A short PLI material
  hard-blocks the task start**, and since all materials consume in one
  transaction, *one* short material blocks the whole task.
- The gate is raw `qty_on_hand`, **not** earmarked-availability — so consumption
  can draw stock another job earmarked (a separate cross-job over-draw nuance).

**This block is the forcing function for the whole scenario.** The worker hits
"only 7 on hand," which is *why* they go buy 3. The inventoried-expense receipt
raises QOH so the blocked start proceeds, and the cost lands at that consumption.

---

## 7. What changes from the as-built code

**Remove:**
- Recost-on-link and recost-on-unlink (`_recost_material_from_expenses`,
  `_recost_after_unlink`).
- The cost-clobber guard (`_assert_no_cost_clobber`).
- The link-to-existing-material path in `submit`/`update`.

**Change:**
- `Expense.material` (single FK) → **`Material.source_expense`** (one expense →
  many materials). The "to-many" suppression in `_spent` and the wizard
  generalises for free (key off "has a source_expense").
- `_spent`: **inventoried-expense amounts no longer counted directly**;
  inventoried cost flows via consumption (`consumed × unit_cost`).
  Non-inventoried expense amounts still counted at purchase. Care needed so an
  inventoried material isn't both consumption-costed *and* expense-costed.
- Inventoried expense entry creates a **receipt** (QOH ↑ + earmark), not a
  consumable job-material (subject to Open Q3).

**Keep (unchanged):**
- Overhead (no-job) expenses; material-less job service costs (row 1).
- Billing: material-less expense = expense atom; expense-created (non-inventoried)
  materials bill via their own material atoms; inventoried goods bill via the
  consuming material as today.
- The invoiced-freeze and the reimbursed-money-lock.
- Document-sourced freeform cost (A5) and the freeform unit-cost UI lock.

---

## 8. Open questions (the parts to decide)

1. **Scope/sequencing — the big one.** Take on the inventoried
   cost-at-consumption rework **now** (sizable; it's real inventory-cost surgery
   and overlaps `docs/plans/2026-06-13-inventory-catalog-vs-lots-protospec.md`),
   *or* ship the simpler non-inventoried model now and **document the inventoried
   top-up double-count as a known gap** the inventory redesign later closes?
   (You said we *must* support humans expensing top-ups, which argues for doing
   it properly — but it's a meaningfully bigger cut.)
2. **Purchase-price variance.** Under cost-at-consumption the job is charged
   `consumed × unit_cost` (standard cost), not the exact cash of the top-up
   expense. The difference (actual vs standard) isn't captured. Accept the
   simplification? (Typical for a job shop.)
3. **First purchase, no existing material.** An inventoried expense-receipt needs
   a consumable line to eventually carry the cost. If none exists for that PLI on
   the job, do we **find-or-create** the consumable material (then it behaves
   like any inventoried material)?
4. **Leftover stock on a cancelled/abandoned job.** Inventoried stock bought but
   never consumed isn't charged to the buying job (it's an asset for future
   jobs). Correct accounting, but is it what the shop wants?
5. **Many-materials UI.** Confirm reusing the line-item add-row pattern; confirm
   each spawned material is independently editable/removable while drafting.
6. **Shortfall-block UX.** Turn the "only 7 on hand" task-start error from a
   dead-end into the entry point to record the top-up expense? (Where the two
   threads naturally meet; not required for the model, but high-value.)
7. **Billing suppression.** Re-verify there's no double-offer in the wizard:
   inventoried goods bill via the consuming material; the inventoried expense
   (a receipt) must never appear as its own atom.

---

## 9. Relationship to other docs

- **Supersedes** parts of `2026-06-13-expenses-job-attribution-redesign.md`:
  the link-to-existing-material path, the recost/clobber machinery, and the
  single `Expense.material` FK.
- **Overlaps** `2026-06-13-inventory-catalog-vs-lots-protospec.md` — the
  inventoried cost-at-consumption work is the same surgery; if Open Q1 says "do
  it properly," fold these together.

## 10. Migration / rollout notes (sketch)

- Data: existing `Expense.material` rows → `Material.source_expense`; review any
  material costs the as-built recost already wrote (they may be wrong, e.g. the
  3.67 case) and decide whether to recompute or leave.
- Phasing option: ship rows O–3 (non-inventoried, single amount, own materials,
  no join) first as a clean increment; tackle row 4 (inventoried
  cost-at-consumption) as a second phase with the inventory redesign.

---

## 11. Decisions (2026-06-14)

- **Open Q1 → DO IT NOW.** Implement the inventoried cost-at-consumption model in
  this pass (not deferred). Rationale: it makes the later inventory work less
  onerous and leaves a functional app at the end.
- **Open Q2 → accept** the standard-cost-at-consumption simplification (purchase-
  price variance not tracked).
- **Open Q4 → accept** that leftover inventoried stock on an abandoned job is an
  asset, not charged to the buyer.
- **New decision — single-mode expenses (no mixing).** A single `amount` can't be
  split between purchase-cost and consumption-cost items, so an expense is **one
  mode**: either a **cost** (amount job-costed at purchase; creates 0..N
  freeform/non-inventoried consumable materials) **or** a **stock receipt** (an
  inventoried PLI purchase: QOH ↑, amount *not* job-costed, cost flows at
  consumption). Mixing inventoried + non-inventoried items in one expense is a
  validation error ("record the stock purchase separately"). This resolves the
  open mechanics behind Q3: an inventoried expense is a **pure receipt** — it does
  **not** create a competing consumable material (which is what would re-introduce
  the quantity double-count). First purchase with no consumable on the job yet:
  the user adds/uses a material as normal; the job realizes the cost when that
  material is consumed (so an inventoried-only job can read $0 spent until
  consumption — the honest cost-at-consumption behavior).

### Workaround note — task blocked by short stock (trust-the-user)

When a worker is blocked from starting a task because a PLI material is short
(§6), and procurement is in flight, they can **edit the task's material down to
the quantity actually on hand** (so the task can start now), and **add a second
Task/Material combo to hold the remainder** until the rest is procured. This is
fully in trust-the-user territory — the system shouldn't force it — but we want
to **surface it as a suggestion in the shortfall-block message** when the
inevitable happens. (Implemented as part of the shortfall-block UX task.)

---

**Implementation:** see
`docs/plans/2026-06-14-expenses-cost-at-consumption-implementation.md`.
