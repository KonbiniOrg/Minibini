# Change Orders — UI flow

**Purpose:** A from-the-user's-perspective walkthrough of amending an accepted
estimate with a change order: pausing the job, authoring the CO's diff
(deliverables + line items, including the unified add-line picker), sending it,
and — new in the 2026-07-03 batch — what **acceptance crystallizes onto the
job's work** (tasks/materials created, cancelled, and released — plain
hand-lines crystallize into nothing; see §6). Reference:
`docs/designs/estimates-and-prices.md` §14 (esp. §14.11).

## Personas

- **Worker** — no atoms. Read-only: can open a CO page but sees no edit/send/
  accept controls.
- **Jobs / PM** — `can_manage_jobs`, **or** the Job's `project_manager` (scoped
  to that one job via `can_manage`). Full CO lifecycle.
- **Customer (portal)** — no login; acts through the emailed token link.

## Prerequisites (test-data setup)

- [ ] **A job with an accepted estimate** whose lines are atom-backed: at least
  one **service/task line** (a Task exists on the job), one **catalog material
  line** (a Material with an earmark), and one **plain hand-line** (stays a
  document line — no atom behind it — at estimate acceptance). Include an
  **adjustment line** (e.g. 10% rush) to test the document-only case.
- [ ] Some **blepped time** on one of the tasks (start/stop work) — needed to
  observe bleps surviving a CO remove.
- [ ] **A Service Item** and a **catalog Inventory Item** for the add-line picker.
- [ ] The `default_material_accounting_category` setting (Settings → General)
  for the freeform-material add.
- [ ] A jobs/PM user and a plain worker.

## Dev notes

- Sending the CO emails a PDF + portal link — dev needs a working email backend
  (console backend prints it) to complete §5 realistically; **Record Accepted**
  (§6) works without email.

---

## 1. Enter the CO room (job on hold)

Entry: **Job overview** (`#/jobs/{id}`), job `approved` or `in_progress`.

- [ ] **Pause the job.** In the job header, change status to **On Hold** → a
  hold-reason prompt appears; it is required. Job shows `on_hold`.
- [ ] **Open bleps block the pause.** With someone clocked into a task, the
  transition to on-hold is refused — stop work first.
- [ ] **Create Change Order** (estimate panel toolbar, 2026-07-19) is offered
  on an **accepted** estimate only while the job is **on hold** and has **no**
  change orders at all — the first CO comes from the estimate; later ones
  chain via **Start new change order** on the previous CO (§7). On an un-held
  job the button is hidden (and the API refuses creation). Click (held job) →
  creates a draft CO and lands on `#/jobs/{jobId}/change-order/{coId}`.
- [ ] **While on hold, the work surface is frozen.** Task/material mutations and
  new bleps on the job are refused until the hold ends.
- [ ] **Exit guard.** Attempting to move the job off `on_hold` while the CO is
  draft/open is refused ("resolve the change order first").

## 2. The CO page — deliverables diff

Entry: `#/jobs/{jobId}/change-order/{coId}`, draft CO. (The old
`#/change-orders/{id}` route redirects here; the send page stays at
`#/change-orders/{id}/send`.)

- [ ] **The CO page is a job-workspace panel (2026-07-19).** The JobShell
  chrome renders around the diff — job header, context band, nav rail — and
  the estimate/CO subnav shows full document codes
  (`{estimate_number}-{version}` pills plus the CO number) with this CO
  marked current. Both diff grids (Deliverables, Line items) render.
- [ ] **Baseline vs live.** The Deliverables section shows the snapshot taken at
  CO creation as the baseline; editing a live deliverable renders a **changed**
  row (new value) above its struck original, deleting renders a struck
  **removed** row with **Undo**, and **+ New deliverable** appends an **added**
  (green) row.
- [ ] **Shipped rows are frozen.** A deliverable already on a shipment shows
  "shipped" instead of Change/Delete.

## 3. The CO page — line-item diff

The Line items table merges the accepted estimate's lines with the CO's deltas.

- [ ] **Unchanged rows** offer **Change** (opens the modal pre-set to *replace*
  with the line's values) and **Delete** (posts a *remove* delta — the row
  renders struck with **Undo**).
- [ ] **Changed rows** (amber) show the replacement values above the struck
  original, with **Edit** / **Undo**.
- [ ] **Added rows** (green) show **Edit** / **Delete**.
- [ ] **Footer math.** Estimate total (struck) → proposed total, with the
  difference shown signed.
- [ ] **Undo is local and free.** Undoing a change/remove deletes the CO delta
  and the row returns to unchanged — no confirmation prompt (reversible action).

## 4. Adding a line — the unified picker (2026-07-03)

Entry: **+ New line** on a draft CO.

- [ ] **Opens the same picker as the estimate page** (`PriceListPicker`): one
  search box over Service Items + catalog Inventory Items, plus the freeform
  footer with the **"Is this a material?"** checkbox and **Add Line**.
- [ ] **Service pick → deferred service line.** Choosing a Service Item opens a
  qty form (unit shown beside qty); saving adds an *added* line snapshotting the
  service's price. **No Task is created yet** — the task crystallizes at CO
  acceptance (§6).
- [ ] **Inventory pick → catalog line.** Choosing an Inventory Item opens a qty
  form; the line lands with the item's description/units/price.
- [ ] **Freeform, material checked → material line.** Description/qty/units/
  price + Accounting Category (pre-filled from the configured material default,
  overridable).
- [ ] **Freeform, material unchecked → plain hand-line.** Same form;
  **Accounting Category is required** — saving without one shows "Accounting
  Category is required."
- [ ] **Edit modal carries AC.** Editing an added line (or switching the
  Change modal to *add*) shows an Accounting Category select; replace/remove
  lines don't (they inherit from the atom they replace).

## 5. Send + the AC send guard

- [ ] **Send to customer** (draft toolbar) → the send page pre-fills to/subject/
  body with the portal link and attaches the CO PDF; sending flips the CO to
  `open` and the toolbar gains **Resend** + **Record Accepted / Record
  Rejected**.
- [ ] **Guard: bare add line without an AC blocks the send** (via send page *or*
  mark-open) with "every added line item needs an accounting category" — the
  check runs **before the email goes out**, so the customer is never mailed a
  portal link to a still-draft CO. Fix the line, resend. *(This exists so
  acceptance can never fail after the customer says yes.)*
- [ ] **Guard: a truly empty CO blocks the send** — no line-item changes AND
  no deliverable changes → refused (send page *or* mark-open) with "Cannot
  send an empty change order…".
- [ ] **Deliverables-only is sendable (2026-07-20).** A CO with no line items
  but a deliverables diff CAN be sent/marked open — the customer signs off on
  the scope change even when the price doesn't move.

## 6. Acceptance — the deltas become real work (2026-07-03)

Entry: open CO → **Record Accepted** (or the customer's portal Accept).

- [ ] **Job auto-advances** `on_hold → approved`; the CO shows `accepted`; the
  estimate's status pill reads **amended**.
- [ ] **Added service line → new Task.** The job's task list gains a pending
  Task named after the Service Item, with the line's qty as its estimate.
- [ ] **Added inventory line → new Material** with an earmark for its quantity
  (check Inventory: earmarked rises).
- [ ] **Added freeform material line → provisional Material** (no inventory
  link).
- [ ] **Added plain hand-line crystallizes nothing.** No Task, no Material —
  it stays a document-only line on the CO/agreement.
- [ ] **Removed task line → Task cancelled, bleps preserved.** The target
  line's Task flips to `cancelled`; its recorded time is still on the task
  detail page. A task already **complete** is left alone.
- [ ] **Removed material line → Material released.** The Material row stays on
  the job greyed out with quantity 0 (its planned quantity moved to the released
  record); its earmark is gone from Inventory. A **consumed** material is left
  alone.
- [ ] **Removed plain hand-line → line gone** from the agreement (it never had
  a job atom to retire).
- [ ] **Replaced task line → old Task cancelled + new Task** at the CO line's
  qty/description on the same rate scheme (same assignee).
- [ ] **Removed adjustment line → document-only.** The agreement drops it;
  no job work changes.
- [ ] **Left-alone atoms are badged at billing (2026-07-20).** A complete
  task / consumed material whose line an accepted CO struck shows a
  **"struck from agreement"** badge in the invoice wizard pool
  (`Invoice-Seeding-and-Send.md` §4).
- [ ] **Agreement view** (`Job → agreement` / invoice **Copy from estimate**)
  reflects the composed result: struck lines gone, replacements in place, added
  lines appended — and each agreement line (atom-backed or a plain hand-line)
  bills exactly once, via its agreement-line reference on the invoice.

## 7. Reject / revise

- [ ] **Record Rejected** → CO `rejected`; job **stays on hold**; the proposal
  is snapshotted. **Start new change order** (terminal toolbar) seeds a fresh
  draft carrying the same deltas.
- [ ] **Discard** (draft toolbar) hard-deletes a draft CO after a confirm; the
  exit guard clears.
- [ ] **Portal request-changes** supersedes the open CO and seeds a new draft;
  job stays on hold.

## 8. Guards & permissions (most-missed)

- [ ] **Worker sees no controls.** No + New change order, no toolbar actions,
  no line/deliverable editing on the CO page.
- [ ] **PM parity.** A non-atom user who is this job's `project_manager` gets
  the full CO flow for this job only.
- [ ] **Editing is draft-only.** An open/accepted CO's line and deliverable
  editors are gone (read-only diff).
- [ ] **CO creation requires on_hold + accepted estimate.** No button otherwise;
  the API refuses too.

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Entry | pause (hold reason required) · open-blep block · Create Change Order gating (on_hold + accepted estimate + no COs yet; hidden and API-refused un-held) · exit guard |
| Deliverables diff | change (amber + struck) · remove (+Undo) · add · shipped frozen |
| Line diff | unchanged (Change/Delete) · changed (Edit/Undo) · added (Edit/Delete) · footer totals |
| Add-line source | service (deferred, no Task yet) · inventory · freeform material (AC default) · plain hand-line (AC required) |
| Send | send page + PDF + portal link · resend · AC send guard (pre-email) · empty-CO guard (deliverables-only IS sendable) |
| Acceptance crystallization | add → Task / Material+earmark / provisional Material / plain hand-line crystallizes nothing · remove → task cancelled (bleps kept) / material released (qty 0, earmark gone) / plain hand-line just drops · complete task + consumed material left alone · replace → cancel + new mirrored task · adjustment document-only |
| After accept | job approved · estimate "amended" · agreement composed · each agreement line (atom or plain hand-line) bills exactly once via its reference · struck-atom badge in the wizard pool |
| Reject/revise | rejected stays on hold · seed-new copies deltas · discard draft · portal request-changes supersedes |
| Personas | worker read-only · jobs full · PM scoped |
