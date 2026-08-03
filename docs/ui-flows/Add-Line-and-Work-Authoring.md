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
> §3). Reference:
> `docs/designs/estimates-and-prices.md` §6/§8/§9,
> `jobs-and-tasks.md` §9.

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
  results; rows show label, sub-label, price/unit). Footer: an **"Is this a
  material?"** checkbox + **Add Line** for free-typed text.
- [ ] **Service pick → deferred service line.** A qty form opens (base unit
  shown beside qty); saving adds a line snapshotting the service's price.
  **No Task is created at authoring** — it crystallizes at acceptance (§4).
  The line's description is editable afterwards without touching the price.
- [ ] **Inventory pick → catalog material line** carrying the item's
  description/units/price.
- [ ] **Freeform + material checked → material line.** The typed search text
  pre-fills the description; Accounting Category pre-fills from the material
  default (overridable).
- [ ] **Freeform + material unchecked → fee line.** Same form; **AC is
  required** — saving without one shows "Accounting Category is required."
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

## 4. Acceptance — hand-lines crystallize

Accepting the estimate (customer portal or shop-side) turns document lines into
job atoms:

- [ ] **Service line → Task** (named after the Service Item, description from
  the line, qty as the estimate).
- [ ] **Inventory line → Material** + earmark.
- [ ] **Bare material line → provisional Material** (no inventory link).
- [ ] **Bare fee line → Fee** at qty × price.
- [ ] **Atom-backed lines (wizard-built) don't duplicate** — their atoms already
  exist.
- [ ] **Adjustment lines stay document-only.**
- [ ] **Send guard backs this up:** an estimate can't be sent while a hand-line
  lacks an AC, so acceptance never fails on it.

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

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Start | Start Estimate (direct, no worksheet) · gating (persona/status/live estimate) · past-quoting hint (approved estimate-less) |
| Picker | dual-source search · no initial list · labeled rows · typed-text carry-over · estimate footer (material checkbox) vs task-surface footer (Task/Material/Fee buttons) · live cross-window search (full-item pick) |
| Estimate lines (deferred) | service (no Task yet) · inventory · freeform material (AC default) · freeform fee (AC required) · edit/reorder/delete draft-only |
| Task-list atoms (immediate) | service → Task · manual task (scheme pick) · material (catalog/freeform, earmark) · fee · open to all users |
| Crystallization | service → Task · inventory → Material+earmark · bare material → provisional Material · bare fee → Fee · atom-backed skip · adjustments document-only · AC send guard |
| Wizard | job-atom pool + claim states · released materials absent · grouping/summarize · in-sync vs overridden · last-atom removal |
| Guards | draft-only authoring · on-hold freeze · deletion-doctrine cross-ref |
