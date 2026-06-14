# Expenses ↔ Job attribution — design spec

**Status:** Active. Branch `feature/expenses`. Brainstormed & agreed 2026-06-13
(supersedes the earlier deferred stub of the same name). Next step: a
writing-plans implementation plan.

**Goal:** Make a **Job** the anchor for an expense's cost, so any job cost —
including service costs with no physical good (e.g. a third-party shipping fee) —
can attach to a job, be rolled into job P&L, and (when not already represented by
a Material) be surfaced for billing in the invoice wizard.

**Two parts, one feature, sequenced:**
- **Part A — Expense↔Job foundation.** Job becomes the cost anchor; expenses
  become a job-contained list; cost lives on the Material when one is linked;
  full editability with an invoiced-freeze; Job-UI surfacing. Ships and is
  useful on its own.
- **Part B — Billing.** A material-less job expense becomes a first-class
  billable atom in the invoice wizard. Part A is *dangerously incomplete*
  without this (costs you can't recover aren't managed), so it's in the same
  feature, built as a later phase.

---

## Problem

An Expense that is a **service cost with no physical good** has nowhere to attach
to a Job. Triggering case: a **shipping fee paid to a delivery service** — a real
cost of a job, but not a Material, and today the *only* path from an Expense to a
Job runs through a Material. Forcing a fake "FedEx shipping" Material models a
cost as inventory (wrong; pollutes Materials/earmarks/QOH).

Real-world framing: in-house delivery is a flat-fee `RateScheme` **Task**
(billable work we perform); third-party shipping is **not** work we perform —
it's a cost we pay, so it's an Expense, not a Task.

### Current model (pre-change)

- **No `Expense.job` FK.** `Expense` has `material` (FK SET_NULL, nullable) but
  no job field.
- Job is **derived through the material**: `ExpenseSerializer._job(obj)` returns
  `expense.material.job` (legacy fallback `expense.material.task.job`). All of
  `job_id`/`job_number`/`job_name` are `null` when there's no material → the
  **Job column is blank** for material-less expenses (the symptom that started
  this).
- Creation: `ExpenseService.submit(..., new_material={...})` inline-creates a
  Material on a job and, for inventoried PLIs, records an ad-hoc receipt. The
  expense's job linkage is a *side effect* of that material.

### UX trap to remove

`MaterialPicker.svelte` ("Link to job (optional)") is two-step: pick a Job
(`pickJob()` clears any material selection), then pick/create a material. If the
user stops after picking the job and hits Save, `ExpenseForm.svelte` submits
`material: null` with no `new_material` → expense created with **no material → no
job**, silently. Violates the app's "don't lose work as a side effect"
convention. The redesign kills this by construction: picking a job alone is valid
and meaningful.

---

## The model: three independent properties

An expense can independently have:

1. **A job** — cost attribution. The new `Expense.job` anchor. `null` = overhead.
2. **A material line** — "this purchase is a tracked job material" (freeform
   *or* PLI-linked). Optional.
3. **Inventory tracking** — only when that material is a PLI flagged
   `is_inventoried`.

They nest: inventory ⇒ a material; a material ⇒ a job; but a job needs neither a
material nor inventory. A `Material` already does **not** require a PLI
(`price_list_item` is nullable) and inventory receipt only fires for inventoried
PLIs — so the "freeform material = pure job cost, zero inventory" shape already
exists today.

### The four real cases

| Case | job | material | inventory |
|---|---|---|---|
| Steel for Job 21 (stock) | ✓ | ✓ PLI | ✓ QOH/earmark dance |
| Shipping fee for Job 21 | ✓ | — | — |
| One-off bracket, consumed today | ✓ | — (or freeform if desired) | — |
| Shop consumables (tape, sandpaper) | — overhead | — | — |

The common one-off (bracket) is captured **fully by the expense alone**
(description + amount + accounting_category + job). A `Material` object is only
worth creating when you actually want inventory/QOH tracking (the "mini-PO").

---

## Part A — Expense↔Job foundation

### A1. `Expense.job` anchor

- Add nullable `Expense.job = FK('jobs.Job', on_delete=PROTECT or SET_NULL,
  null=True, blank=True)`. (Decide PROTECT vs SET_NULL in the plan; PROTECT is
  safer for cost integrity, but Job cascade behavior for its other children
  should be checked.) `null` = overhead.
- Expenses become a **job-contained list**, alongside Tasks/Materials/
  Deliverables.

### A2. Cost lives on the Material when one is linked (no double-count)

- **Material-linked expense** → the Expense is purely the **payment/accounting
  record** (who paid, payment account, reimbursable?). The *cost* for job P&L
  comes from the **Material** (`unit_cost × quantity`). The expense `amount` is
  **not** a separate job-cost line.
- **Material-less expense** → carries its **own** cost (`amount`) against the
  job.
- Net: on the cost axis, money is counted exactly once.

### A2.1. Material cost provenance & the expense link

**How `Material.unit_cost` is set today** (every path is document-backed except
manual entry):

| Path | Source | Provenance |
|---|---|---|
| `_populate_from_pli()` (fills from `pli.purchase_price` when cost is 0) | PLI catalog | document |
| Carry-over from accepted estimate (`carry_over.py`, always PLI-linked) | PLI catalog | document |
| PO/Bill receiving (`resolve_or_create_for_line(unit_cost=li.price)`) | PO line price | document |
| Expense create-new-material (`submit`, `unit_cost = price or amount`) | Expense amount | document |
| **Manual entry** (`create_on_job` / `update_pricing`, material modal & add-material views) | user-typed | **none** |
| `copy_fields()` clone | inherits source | derived |

**New rule — freeform actual-Material cost is document-sourced only, never
typed.** A freeform (no-PLI) `Material` on a Job may receive its `unit_cost` only
from a **linked Expense** or a **PO line** — the manual-entry path (the cost
field on the material modal / add-material views) is removed/disabled for
freeform actual Materials. Rationale: an *actual* cost should be recorded from a
real document, not guessed; this also makes cost provenance always traceable and
removes the only source of link/unlink ambiguity.

- **PLI-linked materials unaffected** — cost still flows from the catalog
  (`_populate_from_pli`) and may propagate via `update_pricing(propagate_to_pli)`.
- **Estimating unaffected** — `PlanMaterial` costs on the worksheet are
  *estimates* and stay freely editable; carry-over produces PLI-linked materials
  only, so no freeform-with-typed-cost material is ever created that way.
- A freeform material with no expense/PO yet shows cost "—" (informative: "we
  have/plan this, haven't recorded what it cost"), not a fabricated number.

**Link / unlink cost behavior** (follows directly from the rule above):

- **Link** an expense to a material → set `material.unit_cost = amount /
  quantity` (guard `quantity == 0`). If the material already has a non-zero cost
  from another source, **don't silently clobber** — surface the mismatch for
  reconciliation. *(Because manual entry is prohibited for freeform, an existing
  non-zero cost means a PLI/PO basis — exactly the thing not to overwrite.)*
- **Unlink** → reset `unit_cost` to 0 **only when nothing else backs it** (no
  `po_line_item`, no other linked expense). Otherwise leave it. With manual entry
  gone, there is never a hand-typed "legit independent number" to preserve, so
  the rule needs no special case for it.
- `Material.expenses` is **to-many**: if several expenses back one material, its
  cost is the **sum** of their amounts, and "reset on unlink" fires only when the
  **last** one leaves.

This keeps the no-double-count invariant intact through edits: while linked, only
the material counts; on unlink the expense becomes material-less and counts its
own amount, and the copied cost comes off the material so the same money is never
counted twice.

### A3. Entry / edit flow

Pick a **Job** → the job's existing Materials become selectable link targets:
- **(a)** link an existing material (records the actual paid cost against it), or
- **(b)** leave it job-only (the one-off that was never a Material), or
- **(c)** create a new Material — PLI-inventoried → QOH/earmark dance; freeform →
  cost only.

Picking the job alone is **always valid** → structurally removes the silent-drop
trap. Overhead = pick no job.

### A4. No `Expense.task`

Task attachment leaves expenses entirely. (A non-inventory material doesn't do
the consumption dance, so there's no reason to pin it to a Task; the doc's old
"do we need `Expense.task`?" question resolves to **no**.) The vestigial
`task_name` derivation in the serializer goes away with the material-derived job.

### A5. Full editability + invoiced freeze

- **Fully editable after entry, no reason-gating.** Correcting a wrong-job
  mistake is indistinguishable from any other edit, so all of job / material
  link / amount / category stay editable.
- **Moving an expense (and a linked inventoried material) to the right job**
  composes existing primitives — `InventoryService.unconsume()` (already exists;
  restores QOH/qty_sold/earmark, flips to pending) → move earmark via
  `_mutate_earmark` → re-consume if it was consumed. **No new inventory
  machinery.** `ExpenseService.reject()`'s consumed-material wall stays for
  *reject* only (rejecting a reimbursement claim), not for editing/moving.
- **Invoiced freeze (hard lock):** an expense is **immutable while it — or its
  material — is on an invoice** (has a live `InvoiceLineItemSource`). Up to that
  line, full editability; past it, hands off. The freeze tracks *being on an
  invoice*, not "ever touched one": to fix a genuine error, remove it from the
  invoice (possible only while that invoice is still editable) → it thaws → fix →
  re-bill. This is exactly how Materials/Tasks already behave when billed.

### A6. Serializer & API

- `ExpenseSerializer` reads `job` **directly** (not via material);
  `job_id`/`job_number`/`job_name` populate for material-less expenses → fixes
  the blank-Job-column symptom.
- `job` becomes a writable field (subject to the freeze and the consistency
  rule: if a material is linked, `material.job == expense.job`).
- Drop `task_name` (or keep deriving from `material.task` only if a material is
  present — but expenses no longer set tasks).
- `ExpenseService.submit`/`update` accept and persist `job` directly;
  `new_material` path still supported for case (c).

### A7. Migration / backfill

- Add the column; backfill `Expense.job` from `material.job` (then legacy
  `material.task.job`) for existing rows. Backward compatible.

### A8. Job-cost rollup

- Job P&L = material costs **+** material-less expense amounts. Locate the
  existing job profit/cost computation (the "profit blurb" / job overview
  totals) and extend it to sum material-less expenses by `Expense.job`,
  **excluding** material-linked expenses (their material already counts).

### A9. Job-UI surfacing

- **Job overview (`JobDetail.svelte`) — Materials pillar.** Expenses live in the
  Materials pillar (retitle to *Materials & Expenses* or similar).
  - **Material-less** expenses render as their own rows (amount, category,
    payment method, an "expense" badge).
  - **Material-linked** expenses do **not** get a second row — they become a
    small "paid $X via …" annotation on their material's row (preserves an
    honest visual count; no double-show). *(Confirm in review.)*
  - The pillar count includes material-less expenses.
- **Full Task List (`JobTaskListPage.svelte`).** Expenses show at the **job
  level** (no task), the way taskless materials already do. Same material-less /
  material-linked rendering rule as above.

---

## Part B — Billing (later phase, same feature)

### B1. Expense as a first-class `BillableAtom`

- A **material-less** job expense implements the same `BillableAtom` interface
  (`compute_amount(active_modifiers=None)`, etc.) as Material / TaskCharge, so
  the invoice wizard **enumerates, displays, marks already-invoiced, and
  `InvoiceLineItemSource`-links it uniformly** — no special-casing.
- **Material-linked** expenses are **not** billable atoms — they bill *through
  their Material* (which is already an atom). This is what prevents
  double-billing. So "material-less" is the precise trigger for an Expense atom.
- Overhead (no-job) expenses are never billable (no customer/job).

### B2. Pricing: pass-through cost, invoicer sets sell price

- The Expense carries only `amount` (cost). In the wizard, **cost is shown as
  reference** and the **invoicer sets the sell price** on the line (mark up,
  round, or $0 to absorb). No `sell_price` field added to the Expense model —
  the invoice line item is already freely editable.
- Reaffirms cost-vs-billing separation: the cost/price gap is the invoicer's
  decision, made per-invoice.

### B3. Already-invoiced behavior

- Billed expenses are **shown in the candidate list, marked already-invoiced and
  unavailable for the current invoice** — identical to billed Materials/Tasks
  (a job may have several invoices). `InvoiceLineItemSource` is the link.
- Interacts with A5: being on an invoice is exactly what freezes the expense.

---

## Cost vs. billing (keep separate)

An Expense is **only ever a cost** (reduces job profit). Whether the customer is
**charged** is an independent, per-invoice decision (Part B). The "third atom
type" exists *so the invoicer can choose to recover the cost* — it does not make
expenses auto-flow onto invoices. (This intentionally revises the earlier stub's
"no path from expense to invoice" line, which we reversed in design.)

---

## Out of scope / unaffected

- **Inventory reframe (catalog vs. transient lots).** A separate future feature —
  see `docs/plans/2026-06-13-inventory-catalog-vs-lots-protospec.md`. This
  feature builds on **today's** inventory model and stays forward-compatible: the
  "create a Material" path inherits universal tracking for free if/when that
  lands. No partial/fractional-scrap tracking here.
- **QBO sync.** Job linkage isn't carried to QBO today (the `Purchase` push has
  no job/class); adding `Expense.job` doesn't change QBO behavior.
- **Inventory receiving.** Unchanged — still only when a PLI-inventoried Material
  is involved.
- **Reimbursements.** Unaffected (batching is orthogonal to job attribution).

---

## Open items to confirm during spec/plan review

1. `Expense.job` `on_delete`: PROTECT vs SET_NULL (cost integrity vs. job
   deletion ergonomics).
2. Materials-pillar rendering of material-linked expenses (annotation vs. no
   display at all).
3. Exact `BillableAtom` enumeration hook the wizard uses (read invoice-wizard +
   `InvoiceLineItemSource` to mirror it precisely in the plan).
4. Where the job-cost/profit rollup lives, to extend it correctly.

## Pointers

- Models: `apps/expenses/models.py` (Expense), `apps/inventory/models.py`
  (Material, PriceListItem, Earmark).
- Services: `apps/expenses/services.py` (ExpenseService), `apps/inventory/
  services.py` (`InventoryService.consume/unconsume/restock/receive_ad_hoc/
  reverse_ad_hoc/_mutate_earmark`, `MaterialService.create_on_job`).
- Serializer: `apps/api/expenses/serializers.py`.
- Invoice wizard / atoms: `apps/invoicing/` + `apps/api/invoicing/`,
  `InvoiceLineItemSource`; atom interface shared with `MaterialBase.compute_amount`
  / TaskCharge / PlanTask.
- Frontend: `frontend/src/components/expenses/ExpenseForm.svelte`,
  `MaterialPicker.svelte`; `frontend/src/components/jobs/JobDetail.svelte`
  (Materials pillar); `frontend/src/routes/jobs/JobTaskListPage.svelte`.
## Durable docs to update (when the feature lands)

These describe *built* behavior, so edit them as each part ships — not before
(avoids the doc-ahead-of-code drift CLAUDE.md warns against). Concrete points:

- **`docs/designs/invoicing-and-expenses.md`** (Expense section):
  - `Expense.job` anchor; `null` = overhead; expenses are a job-contained list.
  - Cost-on-material rule (material-linked expense = payment record only; cost
    counted via the material) and the no-double-count invariant.
  - Full editability + the **invoiced-freeze** (immutable while it — or its
    material — is on an invoice).
  - **Part B billing:** material-less expense as a `BillableAtom`; pass-through
    cost, invoicer-set sell price; `InvoiceLineItemSource` + already-invoiced
    marking. Revise any prior "no path from expense to invoice" statement.
- **`docs/designs/materials-inventory-and-purchasing.md`**:
  - The **`Material.unit_cost` provenance map** (A2.1) and the new rule:
    *freeform actual-Material cost is document-sourced only (Expense or PO),
    never typed*; PLI/estimating paths unaffected.
  - Link/unlink cost behavior; `Material.expenses` to-many summing.
  - Note that expense-driven job-costing reads material cost for
    material-linked expenses and `Expense.amount` for material-less ones.
- **`docs/designs/jobs-tasks-and-worksheets.md`**:
  - Job-UI surfacing: expenses in the Materials (& Expenses) pillar and at job
    level in the full Task List; material-linked-expense-as-annotation rule.
  - Job P&L rollup = material costs + material-less expense amounts.
