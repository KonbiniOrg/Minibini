# Rate Schemes & Adjustments — UI flow

> **Renamed (2026-06).** This area used to be called "Services." The pricing
> model was renamed **twice**: the priced thing was `RateScheme` → renamed to
> `ServiceItem` (the "reframe") → renamed **back to `RateScheme`**, while the old
> `TaskTemplate` saved-work catalog took over the `ServiceItem` name. So **today**:
> the priced thing is a **Rate Scheme** (`RateScheme`, `/api/rate-schemes/`), and the
> reusable saved-work catalog is a **Service Item** (`ServiceItem`, formerly
> `TaskTemplate`, `/api/service-items/`). This doc covers Rate Schemes + adjustments;
> the Service Item catalog and the "Add Line" picker are touched only where they
> intersect. (Filename kept as `Services-and-Adjustments.md`.)

**Purpose:** A from-the-user's-perspective walkthrough of the **Rate Schemes** price
list and the **percentage adjustments** (rush fees / discounts) that ride on estimate
and invoice line items. It guides manual/user testing today and is intended to seed the
automated UI test platform later — each checklist item maps to an assertion. Keep it
current as the pricing UI evolves.

**Model:** a **Rate Scheme** (`RateScheme`) is one priced thing the shop charges for.
Its `rate` is the price for **every** algorithm — including flat-fee, whose price used
to live on the task. So flat-fee rate schemes proliferate (one per priced item) and
tasks carry **no price of their own**; they read it from the linked Rate Scheme. A
**Service Item** (`ServiceItem`, the saved-work catalog) is a separate thing: a reusable
task definition that bundles a name + default modifiers + a Rate Scheme, added to a Plan
via **Add Line**. A fourth Rate Scheme algorithm, **`percentage`**, is a *document
adjustment*: its `rate` is a percent (negative = discount), it never backs a Task, and it
is applied to a draft estimate or invoice as its own line whose amount =
`percent × (sum of the other lines it targets)`, scoped by accounting category. The
amount **recalculates while the document is a draft and freezes when the document is
sent/finalized**. Agreement adjustments surface in the invoice wizard so they can't be
missed when billing. See `docs/designs/estimates-and-prices.md` and the consolidation
phase plans in `docs/plans/`.

> **Scope — what to test now vs. what's coming (Phase 8 deferred).** Today,
> adjustments are **document-scoped**: you add one per **draft estimate** and again per
> **draft invoice** (the **Add Adjustment** button, §3/§7), and the invoice wizard's
> **Agreement Adjustments** panel (§8) pulls the accepted estimate's adjustments onto an
> invoice. **That is the current, shippable behavior this doc covers — test it as
> written.** **Phase 8 ("job-scoped, auto-applied adjustments") is deferred and NOT
> built yet.** When it lands it will move the adjustment *definition* to the **Job**
> (define a rush/discount once on the job → it auto-applies to every estimate and
> invoice, re-evaluated against each document's own lines, waivable per document) and
> will **replace** both the per-document **Add Adjustment** flow and the
> Agreement-Adjustments panel. So if you're wondering "why is the adjustment on the
> document and not the Job?" — that's correct for now; the Job-level model is future
> work. Everything else in this session (the rename, the atoms-only estimate, removal of
> direct line authoring) **is** built and reflected here.

## Personas

- **Worker** — no permission atoms. Adds/completes tasks (picking a Rate Scheme for
  the task); cannot manage Rate Schemes and cannot add adjustments.
- **Jobs / PM** — holds `can_manage_jobs`, **or** is the Job's `project_manager`
  (scoped to that job). Can add adjustments on that job's **draft estimates**.
- **Financials** — holds `can_manage_financials`. Can add adjustments on
  **draft invoices** and use the invoice wizard's Agreement Adjustments panel.
- **Config** — holds `can_manage_config`. Creates/edits/supersedes **Rate Schemes**
  (and Service Items) in Settings → Catalog. *(Creating a Service Item is also allowed
  for `can_manage_jobs` — the inline "save to catalog" while plan-building — but Rate
  Schemes are config-only.)*

## Dev note — percentage rate schemes are document-only

A `percentage` Rate Scheme is meaningless on a task. The backend rejects assigning one
to a Task (HTTP 400) and excludes it from
`GET /api/rate-schemes/?task_applicable=true`. **Known gap (verify / likely bug):** the
task rate picker (`WorkItemForm`) and the Service Item form's rate picker
(`ServiceItemManager`) currently fetch `/api/rate-schemes/` *without*
`task_applicable=true`, so a percentage Rate Scheme may still appear in those dropdowns —
picking one errors only on save. Treat its appearance there as a bug to fix (wire the
filter), not as intended behavior. See §2 and §9.

## Prerequisites (test-data setup)

Without these, whole branches below are silent no-ops:

- [ ] **A Rate Scheme of each task algorithm** — one `elapsed_time` (e.g. "CNC
  Router", rate 85/hour), one `entered_qty`, and one **`flat_fee`** (e.g. "Std
  Setup Fee", rate 50/job). The flat-fee one is needed for the price-on-rate
  reframe checks (§1, §2).
- [ ] **A `percentage` "Rush" Rate Scheme** (rate **15**) and a **`percentage`
  "Discount" Rate Scheme** (rate **-10**). Without these, no adjustment can be added.
- [ ] **At least two AccountingCategories** (e.g. **Labor** and **Materials**) so
  category-scoped targeting is observable.
- [ ] **A draft Estimate** with line items spanning both categories — e.g. a
  **Labor** line `qty 2 × $50 = $100` and a **Materials** line `qty 1 × $40 =
  $40` (base subtotal **$140**). Adjustment math in §3 assumes these numbers.
  *(Author base lines via the estimate detail page's **Add line** picker or the
  **Show Tasks & Materials** wizard — see `Add-Line-and-Work-Authoring.md`; the
  old worksheet/"Plan" layer was removed in the job-owns-atoms refactor.)*
- [ ] **An accepted Estimate that carries a percentage adjustment**, plus a
  **draft Invoice** on the same Job — required for the agreement-surfacing /
  wizard panel (§8).
- [ ] **Four users** — worker, a `can_manage_jobs` user (and/or a Job whose PM is
  a non-atom user), a `can_manage_financials` user, and a `can_manage_config`
  user.

---

## 1. Rate Schemes manager (Config persona)

Entry: **Settings** (`#/settings`) → the **Catalog** tab → the **Rate Schemes**
section (`RateSchemeManager`, heading **"Rate Schemes"**).

- [ ] **Lives under Catalog.** The Rate Schemes list is on the **Catalog** tab
  (alongside the **Service Items** catalog and the material markup) — *not* on the
  Setup tab.
- [ ] **List + add.** The heading reads **Rate Schemes**. **Add Rate Scheme** opens
  the create form (legend **"New Rate Scheme"**).
- [ ] **List stays visible while adding.** After **Add Rate Scheme**, the existing
  rate schemes remain listed above the form (the list is not suppressed); the
  **Add Rate Scheme** button is hidden while the form is open.
- [ ] **Flat-fee has a single price field.** Create a Rate Scheme with algorithm
  **"Fixed charge"** → there is **one Rate field** (no separate "flat-fee
  price"); enter the price there. Save → it lists with that rate.
- [ ] **Percentage type.** Choose algorithm **"Percentage of other lines"** → the
  form shows a **"Rate (%)"** field, **no modifier menu**, and **no unit/quantity
  fields**; the AccountingCategory selector stays. Save a "Rush" at **15**.
- [ ] **Negative percent (discount) allowed.** Create/save a percentage Rate Scheme
  with **Rate (%) = -10** → saves (no "must be ≥ 0" block). *(Honest note: a
  negative rate is **only** accepted for percentage; a negative rate on any other
  algorithm is rejected.)*
- [ ] **Supersede a referenced Rate Scheme.** Editing a Rate Scheme that's already in
  use surfaces a **"New Version of Rate Scheme"** path (supersession) rather than an
  in-place edit of frozen fields — the old version stays, work keeps its price.

## 2. A Rate Scheme in the task & Service Item forms (reframe + applicability)

Entry: task list **Add Work Item** (`#/jobs/{id}/tasklist`, `WorkItemForm`); and
**Settings → Catalog → Service Items** (`ServiceItemManager`).

- [ ] **No flat-fee price input.** Select a **flat-fee** Rate Scheme in the task (or
  Service Item) form → there is **no** per-task price field; instead the form shows the
  Rate Scheme's price read-only: **"Rate: $50/job (from rate scheme)"**.
- [ ] **Modifiers only for time/qty.** A flat-fee Rate Scheme shows **no modifier
  checkboxes**; an `elapsed_time`/`entered_qty` Rate Scheme still shows its modifier
  menu.
- [ ] **Guard — percentage not selectable for a task.** A **percentage** Rate Scheme
  should **not** appear in the task / Service Item rate picker. *(Known gap, §Dev
  note: it may currently appear because the picker omits `?task_applicable=true`.
  If it appears, that's a bug.)* If one is somehow selected and saved, the server
  **rejects it with a 400** ("Percentage … cannot bill a task").

## 3. Add an adjustment to a draft estimate (Jobs / PM persona)

Entry: estimate detail (`#/estimates/{id}`) on a **draft** estimate. The
**Add Adjustment** button shows only when `can_manage_jobs` (or PM) **and** the
estimate is `draft`. *(Base lines are authored here too — the **Add line** picker
and the **Show Tasks & Materials** wizard; see `Add-Line-and-Work-Authoring.md` —
alongside reorder arrows and the "out of sync with atoms" marker.)*

- [ ] **Open the modal.** **Add Adjustment** opens **"Add Percentage Adjustment"**
  with a **rate dropdown** (placeholder **"-- Select a rate --"**, lists only
  percentage Rate Schemes) and a **"Target Categories"** checklist labeled *"leave all
  unchecked to apply to all"*.
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

## 4. Auto-recompute & freeze (estimate)

- [ ] **Auto-recompute after editing a base line.** With the rush line present,
  change a base line via the wizard (e.g. bump the Labor line to qty 3 = $150, base now
  $190) → the adjustment immediately updates to **$28.50** (15% of $190) with no further
  action required.
- [ ] **Auto-recompute on add/delete.** Add a new base line (wizard) → the adjustment
  recomputes. Remove a base line → the adjustment recomputes. No manual step.
- [ ] **Freeze on send.** Send the estimate (it leaves `draft`). The
  **Add Adjustment** button disappears; the adjustment amount is now frozen
  (line-item edits are blocked once non-draft, so the freeze is automatic).

## 5. Estimate detail — how an adjustment line reads

- [ ] **Distinct row.** The adjustment line is visually distinct
  (`adjustment-row`) with its **badge** (`+15% Rush on Labor, Materials`) rather
  than a normal description.
- [ ] **Sorted last.** Adjustment lines render **after** all base lines.
- [ ] **Badge is legible (regression guard).** The badge shows the **percent and
  Rate Scheme name and category names** — never `NaN%` or `undefined`. *(This was a
  real bug: the line serializes the rate scheme as an id; the row resolves the
  display from `adjustment_service_detail` + the category list. If you see
  `NaN%`/`undefined`, report it.)*

## 6. Revision preserves adjustments

- [ ] **Revise carries the adjustment.** From an `open` estimate that has a rush
  line, **Revise Estimate** → the new draft revision still contains the rush
  adjustment line with the **same Rate Scheme and the same target categories** (it is
  not silently dropped).

## 7. Invoice adjustments (Financials persona)

Entry: invoice detail (`#/invoices/{id}`) on a **draft** invoice. **Add
Adjustment** shows only when `can_manage_financials` **and** the invoice is
`draft`. Behavior mirrors §3–§5 exactly:

- [ ] **Add / target / discount.** Same **"Add Percentage Adjustment"** modal,
  same badge, same `percent × targeted-subtotal` math, negative = discount.
- [ ] **Auto-recompute while draft; freeze on send.** The adjustment
  auto-recomputes on any base-line change while the invoice is draft; after the
  invoice leaves `draft` the controls disappear and the stored amount is frozen.
- [ ] **Permission split.** A `can_manage_jobs`-only user does **not** get Add
  Adjustment on an **invoice** (that's financials); a `can_manage_financials`
  user does.

## 8. Invoice wizard — Agreement Adjustments panel

Entry: from invoice detail, **Show Billables** → invoice wizard
(`#/invoices/{id}/wizard`). This surfaces adjustments from the **agreement of
record** (the accepted estimate + accepted change orders) so they aren't missed —
and it works **whether or not the invoice was built from the estimate**.

> *This whole panel is the current document-scoped carry-over mechanism and is
> slated to be **replaced** by Phase 8's job-scoped auto-apply (deferred). Test it as
> written for now.*

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
  invoice non-draft → no **Add Adjustment** button.
- [ ] **Add Adjustment hidden for the wrong persona.** Worker sees neither control
  on estimates or invoices; a `can_manage_jobs`-only user sees it on estimates
  but not invoices; financials the reverse.
- [ ] **Auto-recompute has no client-visible button.** There is no Recalculate
  button; adjustments update silently on every line-item mutation. Line-item edits
  are blocked on non-draft documents, so frozen state is enforced by the draft gate.
- [ ] **Percentage Rate Scheme rejected on a task (400).** Assigning a percentage
  Rate Scheme to a task is refused by the server (and should be hidden from
  the picker — §2 known gap).
- [ ] **Negative rate only for percentage.** Saving a negative rate on a
  non-percentage Rate Scheme is rejected.

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Rate Scheme algorithm | elapsed_time · entered_qty · flat_fee (price on `rate`) · **percentage** |
| Reframe | flat-fee shows one Rate field · task/Service-Item forms show rate scheme rate read-only (no price input) · modifiers only on time/qty |
| Adjustment scope | whole-order (empty target) · single category · multi-category · no stacking |
| Sign | positive (rush) · negative (discount) |
| Lifecycle | add (draft) · auto-recompute on every mutation (draft) · freeze on send/finalize · revision preserves |
| Surface | estimate detail/Client View · invoice detail · invoice wizard Agreement panel (path-independent) · NOT atom pool |
| Persona | worker (none) · jobs/PM (estimate) · financials (invoice) · config (Rate Schemes manager) |
| Guards | non-draft hides controls · percentage rejected on task (400) + picker filter (known gap) · negative-rate non-percentage rejected |
| Display | badge shows percent + rate scheme + categories (no `NaN%`/`undefined`) · adjustment row distinct · sorted last |
