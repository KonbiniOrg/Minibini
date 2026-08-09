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

**Model (task-owned-money Phase 1, 2026-08).** A **Rate Scheme** (`RateScheme`) is a
**freely editable preset** — a named, priced service the shop performs. There is no
`flat_fee` algorithm (a fixed one-off charge is a plain hand-line on a document, not a
Rate Scheme — see `Add-Line-and-Work-Authoring.md`) and no
supersession: a Rate Scheme's fields can be edited directly at any time, referenced or
not. When a worker or manager creates a Task from a preset, the task **stamps a
permanent copy** of the preset's `rate`/`unit`/`category`/checked modifiers onto itself
at that moment — from then on the task's own copy, not a live link, is its price of
record. Editing (or even deleting) the preset afterward never reprices a task that
already stamped from it. Retiring a preset (`is_active=False`) only hides it from *new*
task creation; it has zero effect on tasks that already stamped from it. A **Service
Item** (`ServiceItem`, the saved-work catalog) is a separate thing: a reusable task
definition that bundles a name + default modifiers + a Rate Scheme, added via **Add
Work**/**Add Line**; unlike a Task, a Service Item keeps a *live* link to its preset (it
has no money of its own to stamp until it generates a Task). A fourth Rate Scheme
algorithm, **`percentage`**, is a *document adjustment*: its `rate` is a percent
(negative = discount), it never backs a Task, and it is applied to a draft estimate or
invoice as its own line whose amount = `percent × (sum of the other lines it targets)`,
scoped by accounting category. The amount **recalculates while the document is a draft
and freezes when the document is sent/finalized**. Agreement adjustments surface in the
draft invoice's Agreement Adjustments panel so they can't be missed when billing. See
`docs/designs/estimates-and-prices.md` §2-§3 (preset semantics + stamping) and §10.3
(adjustment-percent snapshots).

> **Scope — what to test now vs. what's coming (Phase 8 deferred).** Today,
> adjustments are **document-scoped**: you add one per **draft estimate** and again per
> **draft invoice** (the **Add Adjustment** button, §3/§7), and the draft invoice's
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

- **Worker** — no permission atoms. Adds/completes tasks (picking a Rate Scheme preset
  to stamp for the task, but with no editable money fields at create time — §2); cannot
  manage Rate Schemes and cannot add adjustments.
- **Jobs / PM** — holds `can_manage_jobs`, **or** is the Job's `project_manager`
  (scoped to that job). Can add adjustments on that job's **draft estimates**; can write
  a task's money fields (rate/unit/category/modifiers) at create and edit time (§2).
- **Financials** — holds `can_manage_financials`. Can add adjustments on
  **draft invoices** and use the draft invoice's Agreement Adjustments panel; shares
  the same task money-field write access as Jobs/PM.
- **Config** — holds `can_manage_config`. Creates/edits/retires/reactivates **Rate
  Schemes** (and Service Items) in Settings → Catalog. *(Creating a Service Item is
  also allowed for `can_manage_jobs`/`can_manage_financials` — the shared Catalog
  management widening — but Rate Schemes stay config-only.)*

## Dev note — percentage rate schemes are document-only

A `percentage` Rate Scheme is meaningless on a task. `Task.stamp_from_scheme` rejects
one with `ValueError` (surfaced as a field error / 400), and it's excluded from
`GET /api/rate-schemes/?task_applicable=true`. **The task picker (`WorkItemForm`) is
now fixed:** it fetches with `?task_applicable=true`, so a percentage Rate Scheme never
appears there. **The Service Item form's rate picker (`ServiceItemManager`) still has
the gap:** it fetches plain `/api/rate-schemes/` (active, unfiltered by algorithm), so a
percentage Rate Scheme can still be selected there — the server's
`ServiceItemSerializer.validate_rate_scheme` rejects it with a 400 on save. Treat its
appearance in `ServiceItemManager` as a bug to fix (wire the filter), not as intended
behavior. See §2 and §9.

## Prerequisites (test-data setup)

Without these, whole branches below are silent no-ops:

- [ ] **A Rate Scheme of each task algorithm** — one `elapsed_time` (e.g. "CNC
  Router", rate 85/hour) and one `entered_qty` (e.g. "Tap a hole", rate 5/unit).
  Needed for the stamping checks (§1, §2). (No `flat_fee` algorithm exists —
  fixed one-off charges are a plain hand-line on a document, out of this
  doc's scope.)
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
  **draft Invoice** on the same Job — required for the agreement-surfacing
  Agreement Adjustments panel (§8).
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
- [ ] **Only three algorithms.** The **Algorithm** dropdown offers **"Based on time
  worked"** (`elapsed_time`), **"Worker enters quantity"** (`entered_qty`), and
  **"Percentage of other lines"** (`percentage`) — no "Fixed charge"/flat-fee option
  (removed; fixed one-off charges are a plain hand-line on a document, out of
  this doc's scope).
- [ ] **Percentage type.** Choose algorithm **"Percentage of other lines"** → the
  form shows a **"Rate (%)"** field, **no modifier menu**, and **no unit/quantity
  fields**; the AccountingCategory selector stays. Save a "Rush" at **15**.
- [ ] **Negative percent (discount) allowed.** Create/save a percentage Rate Scheme
  with **Rate (%) = -10** → saves (no "must be ≥ 0" block). *(Honest note: a
  negative rate is **only** accepted for percentage; a negative rate on any other
  algorithm is rejected.)*
- [ ] **Freely editable, even when stamped onto tasks — no supersession.**
  Editing a Rate Scheme already stamped onto live tasks saves **in place** — there is
  no "New Version"/frozen-fields block. The already-stamped tasks' own rate/unit/
  category/modifiers are unaffected (they hold their own permanent copy, not a live
  link); only *future* task creation sees the new values.
- [ ] **Retire / Reactivate.** Each row shows **Retire** (active row) or
  **Reactivate** (inactive row) — a reversible toggle, no confirmation prompt.
  Retiring flips the **Active** column to **No** and removes the row from the
  default (active-only) list view; it does **not** delete the scheme or touch any
  task that already stamped from it.
- [ ] **Show inactive rate schemes.** The **"Show inactive rate schemes"** checkbox
  toggles the list between active-only (default) and all schemes
  (`?include_inactive=true`).
- [ ] **Default preset picker.** The **Default preset** dropdown lists only **active**
  schemes; picking one and clicking **Save default preset** persists it (explicit
  button — not auto-saved on change) as the `default_rate_scheme` Configuration key,
  which preselects the Rate Scheme dropdown on a fresh manual task-creation form
  (§2) for every user. Retiring the current default clears the dropdown back to
  **"-- None --"**.

## 2. A Rate Scheme in the task form — stamping and money-field gating

Entry: task list **Add Work** (`#/jobs/{id}/tasklist`, `WorkItemForm`, manual and
template modes); and **Settings → Catalog → Service Items** (`ServiceItemManager`).

- [ ] **Create is a stamp, not a live link.** Picking a Rate Scheme (manual mode) or a
  Service Item template (template mode) and saving copies the preset's
  rate/unit/category/checked-modifiers onto the new task permanently
  (`Task.stamp_from_scheme`, server-side). The picked preset's own fields are never
  touched by this.
- [ ] **Create-time money fields are always read-only, for every persona.** At create
  time nobody — worker or manager — gets an editable rate/unit input: the form shows
  a read-only preview (**"Rate: $X/unit (from rate scheme)"** in manual mode,
  **"Rate Scheme: Name — $X/unit (from template)"** in template mode), because the
  server always stamps those fields from the chosen preset regardless of what's
  submitted. A manual-mode preview also shows the preset's Accounting Category,
  read-only.
- [ ] **Modifier checkboxes are the one create-time gate.** If the picked preset has
  modifiers, checkboxes render for everyone, but are only **enabled** for a manager/PM
  (`can_manage_jobs` or the job's PM) or `can_manage_financials`; a worker sees the
  same checkboxes **disabled** — visible so they know what's available, un-checkable
  so they can't change the price. This applies in both manual and template mode
  (template mode gates the `active_modifiers` override the same way `add-from-template`
  does server-side).
- [ ] **Editing an existing task's money is manager/PM/financials-only.** Open an
  existing task for edit: a manager sees **editable** Rate, Unit, and Accounting
  Category inputs plus enabled modifier checkboxes (built from the task's original
  stamped-from preset, when it's still resolvable); a worker sees the same fields as
  **read-only text** (`Rate: $X/unit`, category name) and disabled checkboxes. There is
  **no Rate Scheme re-pick dropdown in edit mode** — a static **"Scheme: {name}"** line
  names the preset the task was originally stamped from (provenance only; editing the
  task's own rate never changes what this line shows).
- [ ] **Retiring/deleting the stamped-from preset doesn't touch the task.** A task
  whose `source_scheme` was later retired or deleted still edits and displays its own
  money fields normally; the "Scheme:" provenance line falls back to **"—"** only if
  the preset was deleted (retiring alone leaves the name resolvable).
- [ ] **Guard — percentage not selectable for a task.** A **percentage** Rate Scheme
  does **not** appear in the task rate picker (`WorkItemForm` fetches
  `?task_applicable=true` — fixed, §Dev note). The **Service Item** form's rate picker
  still has no such filter (known gap, §Dev note) — if one is somehow selected and
  saved there, the server rejects it with a 400 ("Percentage … cannot bill a task").

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
  adjustment line with the **same Rate Scheme, the same percent, and the same target
  categories** (it is not silently dropped, and the percent doesn't re-read the live
  scheme — see `adjustment_percent` in `estimates-and-prices.md` §10.3).

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

## 8. Agreement Adjustments panel (invoice Edit mode)

Entry: any **draft** invoice's **Edit** mode (`InvoiceEditView.svelte`) —
the **Agreement Adjustments** panel renders at the bottom of the surface,
below the uncovered-work section, whenever the panel has something to
show. There is no separate wizard route to open first: the old **"Show
Billables" → invoice wizard** entry path is retired (the wizard merged
into this one edit surface — see `Invoice-Seeding-and-Send.md`). The
panel surfaces adjustments from the **agreement of record** (the
accepted estimate + accepted change orders) so they aren't missed — and
it works **whether or not the invoice was built from the estimate**.

> *This whole panel is the current document-scoped carry-over mechanism and is
> slated to be **replaced** by Phase 8's job-scoped auto-apply (deferred). Test it as
> written for now.*

- [ ] **Panel lists agreement adjustments.** With an accepted estimate that
  carried a rush adjustment, opening the invoice's Edit mode shows an
  **"Agreement Adjustments"** panel listing that rush (description + percent)
  with an **Add** button.
- [ ] **Add drops it onto the invoice.** Click **Add** → an adjustment line is
  created on the invoice (recomputed against the **invoice's own** lines, which
  may differ from the estimate's), and the panel entry flips to **Added**
  (disabled).
- [ ] **Already-on-invoice shows Added.** Reloading (or re-navigating back to)
  the invoice, an adjustment it already has shows **Added** (disabled), not
  **Add**.
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
  Rate Scheme to a task is refused by the server; the `WorkItemForm` task picker
  already hides it, the `ServiceItemManager` template picker doesn't yet (§2 known
  gap).
- [ ] **Negative rate only for percentage.** Saving a negative rate on a
  non-percentage Rate Scheme is rejected.
- [ ] **Money-field write is gated on presence, not value.** A worker who somehow
  POSTs `active_modifiers: []` on task create still 403s — the server gate triggers
  on the key being present in the request at all, not on what it's set to (mirrors
  `Add-Line-and-Work-Authoring.md` §6).

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Rate Scheme algorithm | elapsed_time · entered_qty · **percentage** (no `flat_fee` — removed) |
| Preset lifecycle | freely editable, referenced or not (no supersession) · retire/reactivate · default-preset picker |
| Stamping | create copies preset's money onto the task permanently · retiring/deleting the preset afterward doesn't touch already-stamped tasks |
| Money-field gating | create-time fields always read-only for everyone · modifier checkboxes enabled (manager/PM/financials) vs disabled (worker) · edit-time fields editable (manager) vs read-only (worker) |
| Adjustment scope | whole-order (empty target) · single category · multi-category · no stacking |
| Sign | positive (rush) · negative (discount) |
| Lifecycle | add (draft) · auto-recompute on every mutation (draft) · freeze on send/finalize · revision preserves |
| Surface | estimate detail/Client View · invoice detail · invoice Edit-mode Agreement Adjustments panel (path-independent) · NOT atom pool |
| Persona | worker (stamp-only, no money writes) · jobs/PM (estimate + task money) · financials (invoice + task money) · config (Rate Schemes manager) |
| Guards | non-draft hides adjustment controls · percentage rejected on task (`ValueError`/400) + picker filter (fixed in `WorkItemForm`, still gapped in `ServiceItemManager`) · negative-rate non-percentage rejected |
| Display | badge shows percent + rate scheme + categories (no `NaN%`/`undefined`) · adjustment row distinct · sorted last |
