# Add Line & Plan Authoring — UI flow

> **New (2026-06 estimate consolidation).** This walks the **Plan** (the worksheet) and
> the **Add Line** picker — how tasks and materials get onto a job's Plan, which is the
> single source the estimate Client View projects from. It is the companion to
> `Services-and-Adjustments.md` (pricing/adjustments) and overlaps the
> `docs/designs/estimates-and-prices.md` + `jobs-tasks-and-worksheets.md` reference docs.

**Purpose:** A from-the-user's-perspective walkthrough of starting a Plan and authoring
its atoms (tasks + materials) via **Add Line**, including the catalog vs. free-text
forks and "save to catalog." Guides manual/user testing; each checklist item maps to a
future automated assertion.

**Vocabulary (current — note the renames this session):**
- **Plan** = the **worksheet** (`EstWorksheet`). Its page title is literally "Plan"
  (`#/worksheets/{id}`). It holds the job's **atoms**: `PlanTask`s and `PlanMaterial`s.
- **Atom** = one PlanTask or PlanMaterial — a unit of work or goods on the Plan.
- **Rate Scheme** (`RateScheme`, `/api/rate-schemes/`) = a priced thing; a task's billing
  references one. (Formerly "Service"/"ServiceItem" — see `Services-and-Adjustments.md`.)
- **Service Item** (`ServiceItem`, `/api/service-items/`, **formerly `TaskTemplate`**) =
  the **saved-work catalog**: a reusable task definition (name + default modifiers + a
  Rate Scheme) you can drop onto a Plan and optionally grow by "save to catalog."
- **Inventory Item** (`InventoryItem`, catalog goods) = a stocked/priced material you can
  drop onto a Plan as a PlanMaterial.

**The big model idea (consolidation):** you author work on the **Plan**, and the estimate
**Client View** is a *pure projection* of those atoms (+ adjustments). You do **not**
type line items directly onto the estimate anymore — base lines come from here. See
`Services-and-Adjustments.md` §3 and `estimates-and-prices.md`.

## Personas

- **Worker** — no atoms. Can add/edit/complete individual tasks on an existing job, but
  the **Plan** itself (worksheet authoring) needs job-management rights — see below.
- **Jobs / PM** — `can_manage_jobs`, **or** the Job's `project_manager` (scoped to that
  job). Starts the Plan and authors atoms on it.
- **Config** — `can_manage_config`. Manages the **Service Item** and **Rate Scheme**
  catalogs in Settings → Catalog. *(But note: creating a Service Item via the inline
  "save to catalog" while plan-building is allowed for **jobs OR config** —
  `CanManageJobsOrConfig` — not config-only.)*

## Prerequisites (test-data setup)

- [ ] **A job in `draft` or `submitted`** with no worksheet yet (to test **Start
  Estimate**), and a second job that already has a Plan (to test authoring).
- [ ] **At least one Service Item** in the catalog (Settings → Catalog → Service Items)
  with a Rate Scheme, e.g. "Cabinet build" → CNC Router rate scheme.
- [ ] **At least one catalog Inventory Item** (e.g. "3/4 Plywood") so the picker returns
  a material.
- [ ] **At least one `elapsed_time`/`entered_qty` Rate Scheme** for custom tasks.
- [ ] **A `can_manage_jobs` user** (and/or a Job whose PM is a non-atom user) and a
  `can_manage_config` user.

---

## 1. Start the Plan (Phase 2 — plan-first)

Entry: **Job overview** → the **Estimate** pillar.

- [ ] **Start Estimate creates the Plan directly.** With a `can_manage_jobs` user (or
  PM), a job in `draft`/`submitted`, and **no** worksheet yet, the Estimate pillar shows
  a **"Start Estimate"** button. Click it → it `POST`s `/api/est-worksheets/` and
  navigates straight to the **Plan** at `#/worksheets/{id}`. *(There is no separate
  "create worksheet" page anymore — it was removed.)*
- [ ] **Button hidden when not applicable.** No **Start Estimate** when the job already
  has a worksheet, when the job is past `submitted`, or for a user without
  `can_manage_jobs`/PM.
- [ ] **Open Plan again.** Once a Plan exists, the Estimate pillar shows **"Open Plan →"**
  linking to `#/worksheets/{id}`.

## 2. The Plan page (worksheet)

Entry: `#/worksheets/{id}`. Title reads **"Plan"**.

- [ ] **Editable toolbar.** When the Plan is editable (`can_manage` **and** the worksheet
  is `editable`), the toolbar shows: **Add from Template**, **Add line item**, **Show
  Client View**, **Customize Client View**.
- [ ] **Frozen state.** When not editable (e.g. the estimate has been sent), a **"frozen"**
  badge shows and the authoring buttons are hidden — the Plan is read-only.
- [ ] **Sections.** A **tasks** table (`WorksheetTaskTable`) with per-task materials, and
  a separate **Materials** section for task-less (floating) materials. Tasks support
  edit / delete / reorder; materials support edit / del / move (to a task) when editable.

## 3. Add Line — the dual-source picker

Entry: **Add line item** → opens the **"Add item"** picker (`PriceListPicker`).

- [ ] **Search both catalogs at once.** The picker has one search box (placeholder
  **"Search services or materials…"**). Typing searches **Service Items** (saved work)
  *and* catalog **Inventory Items** together. There is **no initial list** — results
  appear only after you type.
- [ ] **Rows are labeled by kind.** Each result shows its label, a sub-label, and (for
  priced rows) a price/unit, so you can tell a Service Item from an Inventory Item.
- [ ] **Pick a Service Item → task form (template mode).** Selecting a service result
  opens **`WorkItemForm`** pre-filled from that Service Item (name, default modifiers,
  its Rate Scheme); saving lands the task via the job's add-from-template path. You set
  the qty before it lands.
- [ ] **Pick an Inventory Item → material modal (pre-seeded).** Selecting a goods result
  opens **`PlanMaterialModal`** bound and locked to that catalog item (description,
  units, costs copied from the item); you set quantity.
- [ ] **Footer always offers the free-text forks.** The picker footer has **"Add custom
  task"**, **"Add freeform material"**, and **Close** — available whether or not the
  search found anything.

## 4. Free-text fork — custom task

Entry: picker footer → **Add custom task** (the one-off-work path when nothing in the
catalog fits).

- [ ] **Opens the task form in manual mode.** `WorkItemForm` opens blank with a **Rate
  Scheme** picker (you attach the price), optional modifiers, name, qty.
- [ ] **Typed search text pre-fills the name (this session).** If you typed something in
  the picker search before clicking **Add custom task**, that text drops into the **Name**
  field. *(Regression guard — type "Special weld", get nothing, click Add custom task →
  Name = "Special weld".)*
- [ ] **Save to catalog (optional).** A checkbox **"Save to catalog (reuse this as a
  service item)"** appears on a manual create. Checking it also creates a **Service Item**
  from what you entered, so it's reusable next time.
- [ ] **Save-to-catalog permission is not config-only.** A `can_manage_jobs` user (no
  `can_manage_config`) **can** use save-to-catalog while plan-building (it goes through
  `CanManageJobsOrConfig`). It is **not** restricted to Config users.
- [ ] **Percentage rate schemes don't belong on a task.** A `percentage` Rate Scheme is
  document-only; if one is somehow selected and saved, the server rejects it (400). See
  `Services-and-Adjustments.md` §2 (known picker-filter gap).

## 5. Free-text fork — freeform material

Entry: picker footer → **Add freeform material** (a one-off material not in inventory).

- [ ] **Opens the material modal in create mode.** `PlanMaterialModal` opens with no
  inventory link: description, quantity, units, unit cost, sell price, accounting
  category.
- [ ] **Typed search text pre-fills the description (this session).** If you typed in the
  picker search before clicking **Add freeform material**, that text drops into the
  **Description** field. *(Regression guard — type "3/4 plywood", click Add freeform
  material → Description = "3/4 plywood".)*

## 6. Add from Template (bulk)

Entry: toolbar → **Add from Template**.

- [ ] **Bulk-add a WorkTemplate.** This adds a whole **WorkTemplate** (a named bundle of
  task associations) onto the Plan at once — distinct from picking a single Service Item
  via Add Line. (WorkTemplates are managed in Settings; see
  `jobs-tasks-and-worksheets.md`.)

## 7. From Plan to the estimate Client View

- [ ] **Show Client View** (toolbar) projects the Plan's atoms onto the estimate as line
  items (`sendAllAtoms`) and takes you to the Client View — base lines are generated from
  atoms, not typed by hand.
- [ ] **Customize Client View** (toolbar) opens the wizard to group atoms into line items
  / curate the customer-facing view.
- [ ] **Edits flow Plan → Client View.** Because the Client View is a projection, changing
  an atom on the Plan and re-projecting updates the corresponding line; a line whose stored
  price has drifted from its atoms shows an **"out of sync with atoms"** marker on the
  Client View. (Full adjustment/Client-View detail: `Services-and-Adjustments.md`.)

## 8. Guards & permissions (most-missed)

- [ ] **Authoring needs job-management + editable.** The Plan's add/edit/delete controls
  appear only when `can_manage` (atom or PM) **and** the worksheet is `editable`. A
  sent/frozen Plan is read-only (frozen badge).
- [ ] **Start Estimate gated.** Only `can_manage_jobs`/PM, only `draft`/`submitted`, only
  when no worksheet exists.
- [ ] **Save-to-catalog = jobs OR config.** Creating a Service Item inline is allowed for
  `can_manage_jobs`; editing/deleting Service Items in Settings is config.
- [ ] **No direct estimate line authoring.** You cannot add a base line on the estimate
  Client View — that authoring lives here on the Plan. (`POST /api/estimates/{id}/
  line-items/` returns **405**.)

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Start | Start Estimate (creates worksheet, navigates to Plan) · hidden when worksheet exists / wrong status / wrong persona · Open Plan link |
| Add Line source | Service Item (→ task form, template mode) · Inventory Item (→ material modal, pre-seeded) · custom task · freeform material |
| Search | dual-source (services + materials) · no initial list · labeled rows |
| Free-text carry-over | typed text → custom-task Name · typed text → freeform-material Description |
| Save to catalog | creates a Service Item · allowed for jobs OR config (not config-only) |
| Bulk | Add from Template (WorkTemplate) |
| Plan → Client View | Show Client View (project atoms) · Customize Client View (wizard) · out-of-sync marker · no direct line authoring (405) |
| Guards | authoring needs can_manage + editable · frozen = read-only · percentage rate scheme rejected on task (400) |
