# Add Line & Work Authoring — UI flow

> **Rewritten 2026-07-04 for the job-owns-atoms world.** The worksheet/"Plan"
> layer this doc previously described (`EstWorksheet`/`PlanTask`/`PlanMaterial`,
> `#/worksheets/{id}`, "Show Client View") was **removed**: the Job now owns one
> live set of work atoms and documents are lenses over them. This walks the two
> authoring surfaces — the **estimate detail page** (document lines, deferred)
> and the **job task list** (work atoms, immediate) — which share one unified
> picker. Companions: `Change-Orders.md` §4 (the same picker on a CO) and
> `Services-and-Adjustments.md` (pricing — the Rate Scheme preset
> lifecycle itself, incl. retire/reactivate/default preset, is covered by
> `e2e/specs/settings/rate-scheme-presets.spec.js`; this doc's own manual
> task-creation coverage is `e2e/specs/add-line-and-work-authoring/stamped-task-money.spec.js`,
> §3; the estimate-side three-kind footer and Work-line crystallization
> below (§2/§4) is covered by
> `e2e/specs/add-line-and-work-authoring/hand-line-kinds.spec.js`).
> Reference: `docs/designs/estimates-and-prices.md` §6.4/§8/§9,
> `jobs-and-tasks.md` §9.
>
> **Rescoped 2026-08-03 (task-owned-money Phase 2)** for the three-value
> `freeform_kind` (work | material | fee) that replaced the retired
> `is_material` boolean on estimate/CO hand-lines — see §2 and §4 below.
>
> **Extended 2026-08-04 (task-owned-money Phase 4)** with §7, "quantity
> structures" — a parent task priced from its subtasks. Covered by
> `e2e/specs/add-line-and-work-authoring/quantity-structure.spec.js`.
> Reference: `docs/designs/jobs-and-tasks.md` §4a (the definitive
> reference), `estimates-and-prices.md` §4.1a/§7, `schedule.md` §3.

**Purpose:** From-the-user's-perspective walkthrough of getting work and lines
onto a job: the unified service/inventory/freeform picker, the
material-vs-fee marker, deferred crystallization at acceptance, and the wizard
that groups atoms into customer-facing lines.

**Vocabulary (current):**
- **Atom** = a `Task`, `Material`, or `Fee` owned by the **Job** — the live work
  set. Documents (estimate, invoice) are *lenses*: their lines may link to atoms.
- **Service Item** = the saved-work catalog entry (name + Rate Scheme).
  **Inventory Item** = catalog goods. **Rate Scheme** = the priced thing a
  task bills against.
- **Hand-line** = an estimate line with no atom behind it *yet* — it
  **crystallizes** into an atom when the estimate (or a change order) is
  accepted.

## Personas

- **Worker** — no atoms needed: may add tasks/materials/fees on the job task
  list (`Add Work`), and track time.
- **Jobs / PM** — `can_manage_jobs` or the job's `project_manager` (scoped):
  estimate authoring, sending, wizard.
- **Config** — manages the Service Item / Rate Scheme catalogs in Settings.

## Prerequisites (test-data setup)

- [ ] A job in `draft`/`submitted` with no estimate (to test **Start Estimate**).
- [ ] At least one **Service Item** (with Rate Scheme) and one **catalog
  Inventory Item** so the picker returns both kinds.
- [ ] The `default_material_accounting_category` setting for the freeform
  material fork; at least one other AccountingCategory for fee lines.
- [ ] A jobs/PM user and a plain worker.

---

## 1. Start the estimate

Entry: **Job overview** → Estimate pillar.

- [ ] **Start Estimate** (jobs/PM; job `draft`/`submitted`; no live estimate)
  creates a draft estimate directly and navigates to
  `#/estimates/{id}` — there is no intermediate worksheet.
- [ ] Button hidden for workers / wrong status / when a live estimate exists.
- [ ] **Past the quoting phase, no estimate ever (2026-07-19):** on a job
  beyond `draft`/`submitted` with no estimates at all (hand-approved), Start
  Estimate is hidden and the panel reads "No estimates. This job is past the
  estimating phase." The backend refuses the create too — new estimates only
  on quoting-phase jobs.

## 2. Estimate detail — "Add line" (document authoring, deferred)

Entry: `#/estimates/{id}`, draft estimate → **Add line**.

- [ ] **The unified picker opens** (`PriceListPicker`): one search box across
  Service Items *and* catalog Inventory Items (no initial list — type to see
  results; rows show label, sub-label, price/unit). Footer (task-owned-money
  Phase 2): three explicit buttons — **Add Work**, **Add Material**, **Add
  Fee-Credit** — instead of the retired "Is this a material?" checkbox.
- [ ] **Service pick → deferred service line.** A qty form opens (base unit
  shown beside qty); saving adds a line snapshotting the service's price.
  **No Task is created at authoring** — it crystallizes at acceptance (§4).
  The line's description is editable afterwards without touching the price.
- [ ] **Inventory pick → catalog material line** carrying the item's
  description/units/price.
- [ ] **Add Work → a `freeform_kind='work'` line.** An optional **preset
  dropdown** (task-applicable, non-percentage Rate Schemes; the
  `default_rate_scheme` setting preselects it when present) picking a
  preset **stamps** its rate/unit/Accounting-Category into the still-editable
  fields client-side — no scheme id is ever sent, only the stamped plain
  values. Description/qty/units/rate/AC (AC required); a negative rate is
  rejected client-side ("Negative price is only allowed on a Fee/Credit
  line.").
- [ ] **Add Material → a `freeform_kind='material'` line.** The typed search
  text pre-fills the description; Accounting Category pre-fills from the
  material default (overridable, and optional — the backend fills it if
  blank).
- [ ] **Add Fee-Credit → a `freeform_kind='fee'` line.** Description/qty
  (default 1)/signed amount/AC (**AC required**); a **negative amount** is
  allowed here only, and shows an inline "This will appear as a credit."
  note; a **zero amount** is rejected ("unit_rate must not be zero" on the
  crystallized Fee) — saving without an AC shows "Accounting Category is
  required."
- [ ] **Kind badges** (`.kind-badge`: Work / Material / "Fee/Credit") render
  next to the description on any line carrying `freeform_kind`; negative
  amounts render `-$X.XX` (shared `formatMoney`), not the mangled `$-X.XX`.
- [ ] **`freeform_kind` is immutable after creation** — editing an existing
  bare line shows its kind read-only, no kind switcher.
- [ ] **Lines are editable/reorderable/deletable while draft** (per-line Edit,
  arrows, delete with renumbering); all of it disappears once sent.

## 3. Job task list — "Add Work" (atoms, immediate)

Entry: `#/jobs/{id}/tasklist` → **Add Work**. Same picker, task-surface footer:
three explicit buttons — **Add Task**, **Add Material**, **Add Fee**.

- [ ] **Service pick → Task now.** `WorkItemForm` opens pre-filled from the
  Service Item; saving creates a real Task on the job immediately.
- [ ] **Add Task (freeform) → manual task.** `WorkItemForm` in manual mode: you
  pick the Rate Scheme; typed search text pre-fills the name.
- [ ] **Inventory pick / Add Material → Material now** (`MaterialModal`,
  pre-seeded from the item or freeform); on a committed job it earmarks
  immediately.
- [ ] **Add Fee → Fee now** (`FeeModal`: description, qty, unit rate, AC).
- [ ] **Any authenticated user** can do all of §3 — worker self-service is
  deliberate.
- [ ] **Live search across windows (2026-07-19).** The picker searches the
  server per keystroke: a Service Item created in another window *after* this
  page loaded is findable WITHOUT reloading, and picking it opens **Add Task
  From Template** with the template selected and the name prefilled — the
  pick carries the full item, not an index into the stale mount-time list.
- [ ] **Manual task creation stamps a permanent money copy (task-owned-money
  Phase 1).** Picking a Rate Scheme in `WorkItemForm` is open to a worker,
  but only a manager/PM/financials user sees editable rate/unit/category
  inputs and an enabled modifier checkbox at create time — a worker sees a
  read-only rate preview and a disabled checkbox (`active_modifiers` is a
  money field). The stamp lands on the task server-side either way; a
  manager can edit the task's own rate afterward without disturbing the
  Scheme provenance chip. E2E: `e2e/specs/add-line-and-work-authoring/stamped-task-money.spec.js`.
- [ ] **A task's accounting category can be left unset (task-owned-money
  Phase 3).** The manager/PM/financials-only Accounting Category dropdown in
  `WorkItemForm` includes a **"— none (categorize at invoicing) —"** option;
  picking it creates/leaves the task with no AC. On `TaskDetailPage` a
  null-category task shows "—". This is not an error state — it's resolved
  later, when the task is composed onto an invoice (fallback stamping — see
  `Invoice-Seeding-and-Send.md` §6a). Clearing an *existing* stamped task's AC
  to null is gated the same as setting any other money field. Estimate/CO
  hand-lines (Work/Fee-Credit, §1–§2 above) are a different, unrelated field
  and still require an AC at entry — this "none" option is Task-only.

## 4. Acceptance — hand-lines crystallize

Accepting the estimate (customer portal or shop-side) turns document lines into
job atoms:

- [ ] **Service line → Task** (named after the Service Item, description from
  the line, qty as the estimate).
- [ ] **Inventory line → Material** + earmark.
- [ ] **Bare `freeform_kind='material'` line → established Material**
  (reverse-markup placeholder cost, QOH-0 lot, cost flagged "cost
  unconfirmed" ⚠ until a real document arrives) — no inventory link.
- [ ] **Bare `freeform_kind='work'` line → a flat Task** (task-owned-money
  Phase 2, Task 3): entered qty, typed rate/unit/AC from the line, **no
  RateScheme** — the task detail page's provenance chip shows a dash "—"
  where a stamped task would show its scheme. Reopens a `work_complete`
  job the same way a manually-added task does.
- [ ] **Bare `freeform_kind='fee'`/legacy-null line → Fee** at qty × price
  (signed — a negative price crystallizes into a credit Fee).
- [ ] **Atom-backed lines (wizard-built) don't duplicate** — their atoms already
  exist.
- [ ] **Adjustment lines stay document-only.**
- [ ] **Send guard backs this up:** an estimate can't be sent while a hand-line
  lacks an AC, so acceptance never fails on it.
- [ ] **E2E:** `e2e/specs/add-line-and-work-authoring/hand-line-kinds.spec.js`
  walks a Work hand-line (preset prefill → flat Task, dash provenance chip)
  and a negative Fee-Credit hand-line (credit note → negative Fee) through
  acceptance and into the invoice wizard's source pool.

*(The change-order page repeats this same authoring + crystallization pattern
against an accepted estimate — `Change-Orders.md` §4/§6.)*

## 5. The wizard — grouping atoms into lines

Entry: estimate detail → **Show Tasks & Materials** (`#/estimates/{id}/wizard`).

- [ ] **Source pool = the job's atoms** (tasks + materials) with claim state
  (available / claimed by this estimate / claimed by another). **Released
  materials don't appear** (they're job history, not quotable work).
- [ ] **Add atoms to a new line / an existing line;** single-atom lines copy the
  atom's values; a uniform same-scheme task bundle summarizes (qty summed, rate
  shared).
- [ ] **In-sync behavior:** a line whose price matches its atoms re-derives when
  atoms change; a manually overridden price sticks.
- [ ] **Removing the last atom removes the line.**

## 6. Guards & permissions (most-missed)

- [ ] **Estimate authoring is jobs/PM + draft-only.** Sent estimates are
  read-only; a worker sees no Add line.
- [ ] **Task-list authoring is open** to any authenticated user, but respects
  the job state: on-hold jobs refuse task/material/fee mutations.
- [ ] **Fee hand-lines require an AC** at authoring and again at send.
- [ ] **Deleting authored things follows the deletion doctrine** — a fee/task
  claimed by a sent document refuses with "cancel / change order" messaging;
  see `Deletion-and-Retirement.md`.

## 7. Quantity structures — a parent task priced from its subtasks

Entry: `#/jobs/{jobId}/tasks/{taskId}` on a top-level task with ≥1
subtask (build one with **Add Task** then **Add Subtask**, or apply a
product-structure template — §7a below). Reference:
`docs/designs/jobs-and-tasks.md` §4a.

- [ ] **Add Subtask, per-unit.** From a parent task's page, **Add
  Subtask** opens `WorkItemForm` with a `qty_scales_with_parent`
  checkbox, defaulted to checked when the parent's unit is `ea` (and
  unchecked otherwise). Checked shows an inline line: `"{per-unit qty}
  {unit} × {parent qty} {parent unit} = {expected} expected"`.
- [ ] **Add Subtask, per-batch.** Unchecking the box switches the
  inline line to `"{qty} {unit} per batch — fixed regardless of parent
  quantity."`
- [ ] **Parent quantity not set.** A flag-checked subtask under a
  parent with no `est_qty` yet shows `"Parent quantity not set —
  treated as ×1."` instead of a bare number — both here and in the
  parent's children table (next bullet).
- [ ] **Children table** on the parent's page: Name / Status / Per-unit
  Est / Expected / Logged-Actual, one row per subtask.
- [ ] **Non-startable parent.** On the parent's own page: no Start
  Work button, no "Add Entry" (historical blep) button, no assign
  control on the Assignee chip. **Complete** is absent, replaced by
  "Complete will be available once every subtask is complete or
  cancelled," until every subtask reaches `complete`/`cancelled`.
- [ ] **Derived Rate chip.** When the parent's own `rate` is unset, its
  Rate chip reads `"derived from children: $X/unit"` instead of a
  plain rate — computed from its children's own rates weighted by
  `qty_scales_with_parent` (§4a.3).
- [ ] **Job board.** A parent task's card is never draggable (dragging
  assigns, which the server rejects for a parent).
- [ ] **Estimate/invoice wizard pool.** The parent appears in the
  source pool at `{parent est_qty} {unit} × {derived rate} = {amount}`;
  **no subtask ever appears** in the pool, claimed or otherwise —
  neither wizard offers one to pick.
- [ ] **Worker time tracking happens on the subtask**, never the
  parent — Start Work on a subtask works normally.
- [ ] **Add as Deliverable** (button on a top-level task's page, hidden
  once already linked or on a subtask) copies name/qty/units into a new
  Deliverable, linked via provenance. The Deliverables panel shows a
  `from {task name}` link on a linked row.
- [ ] **Mismatch badge.** Editing the linked task's `est_qty` to a
  value different from the deliverable's `qty_ordered` shows a passive
  `mismatch` badge on the Deliverables panel row (est vs. ordered, not
  actuals) — nothing auto-corrects either side.
- [ ] **Create work structure** (reverse direction, on an unlinked
  Deliverables row) mints a scheme-less top-level task (no Rate chip at
  all) with the deliverable's qty/units copied over.

### 7a. Applying a product-structure template

Entry: `#/jobs/{id}/tasklist` → **Apply Template**.

- [ ] Selecting a template with `is_product_structure` set shows a
  required **Quantity** field; selecting a flat template hides it.
- [ ] Submitting mints one parent task plus its per-unit subtasks in
  one call — same shape as building the structure by hand (§7 above).
- [ ] A `WorkTemplate`'s `is_product_structure` flag itself has **no UI
  to set** — it's API-only (`PATCH /api/work-templates/{id}/`,
  `can_manage_config`); this modal only *consumes* an
  already-configured template, it does not author one.

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Start | Start Estimate (direct, no worksheet) · gating (persona/status/live estimate) · past-quoting hint (approved estimate-less) |
| Picker | dual-source search · no initial list · labeled rows · typed-text carry-over · estimate footer (Add Work / Add Material / Add Fee-Credit, `freeform_kind`) vs task-surface footer (Task/Material/Fee buttons, still `is_material`-shaped) · live cross-window search (full-item pick) |
| Estimate lines (deferred) | service (no Task yet) · inventory · freeform work (preset dropdown prefill, AC required, negative rejected) · freeform material (AC default) · freeform fee/credit (AC required, signed, zero rejected) · kind badges · kind immutable post-create · edit/reorder/delete draft-only |
| Task-list atoms (immediate) | service → Task · manual task (scheme pick) · material (catalog/freeform, earmark) · fee/credit (signed) · open to all users |
| Crystallization | service → Task · inventory → Material+earmark · bare material → established Material (reverse-markup) · bare work → flat Task (no scheme) · bare fee/credit → Fee (signed) · atom-backed skip · adjustments document-only · AC send guard |
| Wizard | job-atom pool + claim states · released materials absent · grouping/summarize · in-sync vs overridden · last-atom removal |
| Guards | draft-only authoring · on-hold freeze · deletion-doctrine cross-ref |
| Quantity structures | per-unit vs per-batch subtask · parent-qty-unset disclosure · non-startable parent (no start/blep/assign) · completion offer gate · derived Rate chip · pool exclusion of subtasks · deliverables bridge both directions · mismatch badge · product-structure template apply |
