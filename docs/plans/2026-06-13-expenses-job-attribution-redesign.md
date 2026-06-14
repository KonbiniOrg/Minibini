# Expenses ↔ Job attribution — redesign (deferred)

**Status:** Deferred. Captured 2026-06-13 mid-discussion; to revisit after the
financials list-views feature is done. No code written yet — there is one open
question (below) to settle before specing.

## Problem

An Expense that is a **service cost with no physical good** has nowhere to
attach to a Job. The triggering case: a **shipping fee paid to a delivery
service**. It's a real cost of a job, but it isn't a Material, and today the
*only* path from an Expense to a Job runs through a Material.

Forcing a fake "FedEx shipping" Material would work mechanically but models a
cost as inventory — wrong, and it pollutes Materials/earmarks/QOH.

Related real-world framing the user raised: in-house delivery is modeled as a
flat-fee `RateScheme` **Task** (billable work we perform). Shipping via a
third-party service is **not** a task we perform — it's a cost we pay. So it
doesn't fit the "delivery = Task" pattern; it's an Expense.

## Current model (as of 2026-06-13)

- **No `Expense.job` FK exists.** `apps/expenses/models.py` `Expense` has
  `material` (FK SET_NULL, nullable) but no job field.
- Job is **derived through the material**: `ExpenseSerializer._job(obj)`
  (`apps/api/expenses/serializers.py`) returns `expense.material.job`
  (legacy fallback: `expense.material.task.job`). The expense list's
  `job_id`/`job_number`/`job_name` come from this — all `null` when there is no
  material, so the **Job column is blank** for material-less expenses.
- Creation: `ExpenseService.submit(..., new_material={...})` inline-creates a
  Material on a job (`MaterialService.create_on_job`) and, for inventoried PLIs,
  records an ad-hoc receipt. The expense's job linkage is a side effect of that
  material.

### UX trap (the symptom that started this)

`frontend/src/components/expenses/MaterialPicker.svelte` ("Link to job
(optional)") is a **two-step** control:
1. Pick a **Job** — `pickJob()` loads that job's materials and *clears* any
   material selection (`materialId = null; newMaterial = null`).
2. Then **pick an existing material** OR click **"+ Add new material"**.

If the user stops after step 1 (picks the job, sees it in the field, hits Save),
`ExpenseForm.svelte` submits `material: null` with no `new_material` → the
expense is created with **no material → no job**. Selecting a job alone links
nothing, silently. This violates the app's "don't lose work as a side effect"
convention. Whatever we land on should remove this silent drop.

## Proposed direction (not yet finalized)

Make **Job the anchor**, decoupling "which job's cost is this" from "what did it
pay for":

- Add a **nullable `Expense.job` FK** = "this cost belongs to this job"
  (`null` = overhead). Job P&L groups expenses by `expense.job` directly.
- Keep **`Expense.material`** as an *optional refinement* for the physical-good
  case — its inventory-receiving behavior (earmark, ad-hoc receipt, reject/unwind
  that deletes the material) stays exactly as is, gated on a material being
  present.
- **Consistency rule:** if `material` (and/or `task`, see open question) is set,
  it must belong to `expense.job`.
- **Serializer:** read `job` directly; material/task become optional extra info.
- **Migration:** backfill `Expense.job` from `material.job` (then
  `material.task.job`) for existing rows. Backward compatible.
- **UX:** picking a Job is sufficient and meaningful on its own; Material becomes
  a separate optional "this paid for a specific inventory item" step. Kill the
  silent-drop behavior.

### Cost vs. billing (keep separate — important)

An Expense is **only ever a cost** (reduces job profit). Whether the customer is
**charged** for shipping is an independent decision that lives on the **invoice**
(a line item — flat-fee task or a "shipping" material via the invoice wizard).
This redesign must not introduce any path where an Expense flows onto an invoice.

## OPEN QUESTION (resolve before specing)

**Do we need per-Task cost attribution now, or is Job-level enough for the first
cut?**

- **Job-level only (leaner):** `Expense.job` + keep `Material`. "This $40
  shipping fee is a cost of Job 21." Add task attribution later, the day Job P&L
  actually consumes task-level cost rollups (YAGNI).
- **Add optional `Expense.task`:** also pin an expense to a specific Task on the
  job ("…the Delivery task"), with the rule task.job == expense.job, for
  task-level cost rollups.

User is leaning undecided; deferred along with the rest.

## Things unaffected / out of scope

- **QBO sync:** job linkage to QBO is already deferred (the QBO `Purchase` push
  doesn't carry job/class info today). Adding `Expense.job` doesn't change QBO
  behavior.
- **Inventory receiving:** unchanged — still triggered only when a Material/PLI
  is involved.
- **Reimbursements:** unaffected (batching is orthogonal to job attribution).

## Pointers

- Models: `apps/expenses/models.py` (Expense)
- Service: `apps/expenses/services.py` (ExpenseService.submit / update / reject)
- Serializer: `apps/api/expenses/serializers.py` (ExpenseSerializer._job)
- Frontend: `frontend/src/components/expenses/ExpenseForm.svelte`,
  `frontend/src/components/expenses/MaterialPicker.svelte`
- Durable doc to update when built: `docs/designs/invoicing-and-expenses.md`
  (Expense section) and `docs/designs/materials-inventory-and-purchasing.md`
  (Material job-costing link).
- Related: the `MaterialPicker` silent-drop is the concrete bug this redesign
  should also resolve.
