# Services & Adjustments — UI flow

**Purpose:** A from-the-user's-perspective walkthrough of the **Services** price
list (formerly "Rate Schemes") and the **percentage adjustments** (rush fees /
discounts) that ride on estimate and invoice line items. It guides manual/user
testing today and is intended to seed the automated UI test platform later —
each checklist item maps to an assertion. Keep it current as the pricing UI
evolves.

**Model (2026-06 ServiceItem reframe + percentage adjustments):** a **Service**
(`ServiceItem`, the renamed `RateScheme`) is one priced thing the shop charges
for. Its `rate` is the price for **every** algorithm — including flat-fee, whose
price used to live on the task/template. So flat-fee services proliferate (one
per priced item) and tasks/templates carry **no price of their own**; they read
it from the linked Service. A fourth algorithm, **`percentage`**, is a
*document adjustment*: its `rate` is a percent (negative = discount), it never
backs a Task, and it is applied to a draft estimate or invoice as its own line
whose amount = `percent × (sum of the other lines it targets)`, scoped by
accounting category. The amount **recalculates while the document is a draft and
freezes when the document is sent/finalized**. Agreement adjustments surface in
the invoice wizard so they can't be missed when billing. See
`docs/plans/2026-06-23-service-price-list-and-percentage-adjustments.md` and the
phase plans beside it.

## Personas

- **Worker** — no permission atoms. Adds/completes tasks (picking a Service for
  the task); cannot manage Services and cannot add adjustments.
- **Jobs / PM** — holds `can_manage_jobs`, **or** is the Job's `project_manager`
  (scoped to that job). Can add/recalculate adjustments on that job's **draft
  estimates**.
- **Financials** — holds `can_manage_financials`. Can add/recalculate
  adjustments on **draft invoices** and use the invoice wizard's Agreement
  Adjustments panel.
- **Config** — holds `can_manage_config`. Creates/edits/supersedes **Services**
  in Settings.

## Dev note — these are document-only

A `percentage` Service is meaningless on a task. The backend rejects assigning
one to a Task/PlanTask/TaskTemplate (HTTP 400) and excludes it from
`GET /api/service-items/?task_applicable=true`. **Known gap (verify / likely
bug):** the task and template Service pickers (`WorkItemForm`,
`TaskTemplateManager`) currently fetch `/api/service-items/` *without*
`task_applicable=true`, so a percentage Service may still appear in those
dropdowns — picking one errors only on save. Treat its appearance there as a bug
to fix (wire the filter), not as intended behavior. See §2 and §9.

## Prerequisites (test-data setup)

Without these, whole branches below are silent no-ops:

- [ ] **A Service of each task algorithm** — one `elapsed_time` (e.g. "CNC
  Router", rate 85/hour), one `entered_qty`, and one **`flat_fee`** (e.g. "Std
  Setup Fee", rate 50/job). The flat-fee one is needed for the price-on-rate
  reframe checks (§1, §2).
- [ ] **A `percentage` "Rush" Service** (rate **15**) and a **`percentage`
  "Discount" Service** (rate **-10**). Without these, no adjustment can be added.
- [ ] **At least two AccountingCategories** (e.g. **Labor** and **Materials**) so
  category-scoped targeting is observable.
- [ ] **A draft Estimate** with line items spanning both categories — e.g. a
  **Labor** line `qty 2 × $50 = $100` and a **Materials** line `qty 1 × $40 =
  $40` (base subtotal **$140**). Adjustment math in §3 assumes these numbers.
- [ ] **An accepted Estimate that carries a percentage adjustment**, plus a
  **draft Invoice** on the same Job — required for the agreement-surfacing /
  wizard panel (§8).
- [ ] **Four users** — worker, a `can_manage_jobs` user (and/or a Job whose PM is
  a non-atom user), a `can_manage_financials` user, and a `can_manage_config`
  user.

---

## 1. Services manager (Config persona)

Entry: **Settings** (`#/settings`) → the **Catalog** tab → the **Services**
section (`ServiceItemManager`, heading **"Services"**).

- [ ] **Lives under Catalog.** The Services list is on the **Catalog** tab
  (alongside the material markup and templates) — *not* on the Setup tab.
- [ ] **List + add.** The heading reads **Services** (not "Rate Schemes").
  **Add Service** opens the create form (legend **"New Service"**).
- [ ] **List stays visible while adding.** After **Add Service**, the existing
  services remain listed above the form (the list is not suppressed); the
  **Add Service** button is hidden while the form is open.
- [ ] **Flat-fee has a single price field.** Create a Service with algorithm
  **"Fixed charge"** → there is **one Rate field** (no separate "flat-fee
  price"); enter the price there. Save → it lists with that rate.
- [ ] **Percentage type.** Choose algorithm **"Percentage of other lines"** → the
  form shows a **"Rate (%)"** field, **no modifier menu**, and **no unit/quantity
  fields**; the AccountingCategory selector stays. Save a "Rush" at **15**.
- [ ] **Negative percent (discount) allowed.** Create/save a percentage Service
  with **Rate (%) = -10** → saves (no "must be ≥ 0" block). *(Honest note: a
  negative rate is **only** accepted for percentage; a negative rate on any other
  algorithm is rejected.)*
- [ ] **Supersede a referenced Service.** Editing a Service that's already in use
  surfaces a **"New Version of Service"** path (supersession) rather than an
  in-place edit of frozen fields — the old version stays, work keeps its price.

## 2. A Service in the task & template forms (reframe + applicability)

Entry: task list **Add Work Item** (`#/jobs/{id}/tasklist`, `WorkItemForm`); and
**Settings → Templates** (`TaskTemplateManager`).

- [ ] **No flat-fee price input.** Select a **flat-fee** Service in the task (or
  template) form → there is **no** per-task/per-template price field; instead the
  form shows the Service's price read-only: **"Rate: $50/job (from service)"**.
- [ ] **Modifiers only for time/qty.** A flat-fee Service shows **no modifier
  checkboxes**; an `elapsed_time`/`entered_qty` Service still shows its modifier
  menu.
- [ ] **Guard — percentage not selectable for a task.** A **percentage** Service
  should **not** appear in the task/template Service picker. *(Known gap, §Dev
  note: it may currently appear because the picker omits `?task_applicable=true`.
  If it appears, that's a bug.)* If one is somehow selected and saved, the server
  **rejects it with a 400** ("Percentage services … cannot bill a task").

## 3. Add an adjustment to a draft estimate (Jobs / PM persona)

Entry: estimate detail (`#/estimates/{id}`) on a **draft** estimate. The
**Add Adjustment** button shows only when `can_manage_jobs` (or PM) **and** the
estimate is `draft`.

- [ ] **Open the modal.** **Add Adjustment** opens **"Add Percentage
  Adjustment"** with a **"Percentage Service"** picker (lists only percentage
  Services) and a **"Target Categories"** checklist labeled *"leave all unchecked
  to apply to all"*.
- [ ] **Whole-order rush (empty target).** Pick **Rush (15%)**, leave all
  categories unchecked → **Add Adjustment**. A new line appears at the **bottom**
  with badge **"+15% Rush"** and amount **$21.00** (15% of the $140 base).
- [ ] **Category-scoped rush.** Add **Rush** again (or re-add) with **only
  Labor** checked → amount **$15.00** (15% of the $100 Labor line only); badge
  reads **"+15% Rush on Labor"**.
- [ ] **Discount (negative).** Add **Discount (-10%)** targeting all → a line of
  **-$14.00** (−10% of $140); the grand total drops accordingly.
- [ ] **Adjustments don't stack.** An adjustment's amount is computed from the
  **base (non-adjustment) lines only** — adding a second adjustment never changes
  the first, and neither sums the other.

## 4. Recalculate & freeze (estimate)

- [ ] **Recalculate after editing a base line.** With the rush line present, edit
  a base line (e.g. bump the Labor line to qty 3 = $150, base now $190) → the
  rush amount is now stale. Click the adjustment row's **Recalculate** →
  it updates to **$28.50** (15% of $190).
- [ ] **Freeze on send.** Send the estimate (it leaves `draft`). The
  **Recalculate** button and **Add Adjustment** disappear; the adjustment amount
  is now frozen. *(If a stale browser tab still posts a recalculate, the server
  refuses with **HTTP 409**.)*

## 5. Estimate detail — how an adjustment line reads

- [ ] **Distinct row.** The adjustment line is visually distinct
  (`adjustment-row`) with its **badge** (`+15% Rush on Labor, Materials`) rather
  than a normal description.
- [ ] **Sorted last.** Adjustment lines render **after** all base lines.
- [ ] **Badge is legible (regression guard).** The badge shows the **percent and
  Service name and category names** — never `NaN%` or `undefined`. *(This was a
  real bug: the line serializes the service as an id; the row resolves the
  display from `adjustment_service_detail` + the category list. If you see
  `NaN%`/`undefined`, report it.)*

## 6. Revision preserves adjustments

- [ ] **Revise carries the adjustment.** From an `open` estimate that has a rush
  line, **Revise Estimate** → the new draft revision still contains the rush
  adjustment line with the **same Service and the same target categories** (it is
  not silently dropped).

## 7. Invoice adjustments (Financials persona)

Entry: invoice detail (`#/invoices/{id}`) on a **draft** invoice. **Add
Adjustment** shows only when `can_manage_financials` **and** the invoice is
`draft`. Behavior mirrors §3–§5 exactly:

- [ ] **Add / target / discount.** Same **"Add Percentage Adjustment"** modal,
  same badge, same `percent × targeted-subtotal` math, negative = discount.
- [ ] **Recalculate while draft; freeze on send.** Same **Recalculate** button;
  after the invoice leaves `draft` the controls disappear and a stale recalculate
  is refused (**409**).
- [ ] **Permission split.** A `can_manage_jobs`-only user does **not** get Add
  Adjustment on an **invoice** (that's financials); a `can_manage_financials`
  user does.

## 8. Invoice wizard — Agreement Adjustments panel

Entry: from invoice detail, **Show Billables** → invoice wizard
(`#/invoices/{id}/wizard`). This surfaces adjustments from the **agreement of
record** (the accepted estimate + accepted change orders) so they aren't missed —
and it works **whether or not the invoice was built from the estimate**.

- [ ] **Panel lists agreement adjustments.** With an accepted estimate that
  carried a rush adjustment, the wizard shows an **"Agreement Adjustments"** panel
  listing that rush (description + percent) with an **Add** button.
- [ ] **Add drops it onto the invoice.** Click **Add** → an adjustment line is
  created on the invoice (recomputed against the **invoice's own** lines, which
  may differ from the estimate's), and the panel entry flips to **Added**
  (disabled).
- [ ] **Already-on-invoice shows Added.** Re-opening the wizard, an adjustment the
  invoice already has shows **Added** (disabled), not **Add**.
- [ ] **Not in the atom pool.** The agreement adjustment appears **only** in the
  Agreement Adjustments panel — **not** mixed into the billable-atoms source pool
  (it isn't work/goods done).
- [ ] **Empty agreement → no panel.** A job whose agreement has no percentage
  adjustments shows no Agreement Adjustments panel (no empty clutter).

## 9. Guards & permissions (the most-missed, highest-value)

- [ ] **Add Adjustment hidden when not draft.** Estimate `open`/accepted or
  invoice non-draft → no **Add Adjustment**, no **Recalculate**.
- [ ] **Add Adjustment hidden for the wrong persona.** Worker sees neither control
  on estimates or invoices; a `can_manage_jobs`-only user sees them on estimates
  but not invoices; financials the reverse.
- [ ] **Recalculate refused server-side on non-draft (409).** Even if a control is
  forced, the server refuses to recompute a frozen document.
- [ ] **Percentage Service rejected on a task (400).** Assigning a percentage
  Service to a task/template is refused by the server (and should be hidden from
  the picker — §2 known gap).
- [ ] **Negative rate only for percentage.** Saving a negative rate on a
  non-percentage Service is rejected.

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Service algorithm | elapsed_time · entered_qty · flat_fee (price on `rate`) · **percentage** |
| Reframe | flat-fee shows one Rate field · task/template show service rate read-only (no price input) · modifiers only on time/qty |
| Adjustment scope | whole-order (empty target) · single category · multi-category · no stacking |
| Sign | positive (rush) · negative (discount) |
| Lifecycle | add (draft) · recalculate (draft) · freeze on send/finalize · revision preserves |
| Surface | estimate detail · invoice detail · invoice wizard Agreement panel (path-independent) · NOT atom pool |
| Persona | worker (none) · jobs/PM (estimate) · financials (invoice) · config (Services manager) |
| Guards | non-draft hides controls + 409 on recalc · percentage rejected on task (400) + picker filter (known gap) · negative-rate non-percentage rejected |
| Display | badge shows percent + service + categories (no `NaN%`/`undefined`) · adjustment row distinct · sorted last |
