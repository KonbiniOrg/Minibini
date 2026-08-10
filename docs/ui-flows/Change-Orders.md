# Change Orders — UI flow

**Purpose:** A from-the-user's-perspective walkthrough of amending an accepted
estimate with a change order: pausing the job, editing the CO's amended
agreement in place (deliverables + line items, including the unified add-line
picker and the atom-claiming uncovered-work pool), sending it, and what
**acceptance crystallizes/moves/retires onto the job's work** (tasks/materials
created, claims moved, atoms descoped and retired — plain hand-lines
crystallize into nothing; see §6). **2026-08-09 (CO amend-in-place)**
replaced the old client-derived flat line-item diff table with one
server-composed table showing the agreement **as it will read if this CO is
accepted**, plus the same Edit/Customer/Reorder Views surface the
estimate/invoice pages use. Reference:
`docs/designs/estimates-and-prices.md` §14 (esp. §14.4, §14.9, §14.11).

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
  chrome renders around it — job header, context band, nav rail — and
  the estimate/CO subnav shows full document codes
  (`{estimate_number}-{version}` pills plus the CO number) with this CO
  marked current. In **Edit** mode (the default — see §3a for the Views
  bar) both sections render: the Deliverables diff grid (`.diff-table`)
  and the Line items amended-agreement table (`.co-edit-table`, §3 — not a
  diff grid; see §3's note).
- [ ] **Baseline vs live.** The Deliverables section shows the snapshot taken at
  CO creation as the baseline; editing a live deliverable renders a **changed**
  row (new value) above its struck original, deleting renders a struck
  **removed** row with **Undo**, and **+ New deliverable** appends an **added**
  (green) row.
- [ ] **Shipped rows are frozen.** A deliverable already on a shipment shows
  "shipped" instead of Change/Delete.

## 3. The CO page — the amended agreement (Edit mode)

**2026-08-09 rewrite.** The Line items table is no longer a diff — it's ONE
table showing the agreement **as it will read if this CO is accepted**
(`GET .../amended-agreement/`, `compose_amended_agreement`), with gesture
buttons instead of a diff. Four row kinds:

- [ ] **Untouched agreement rows** show a Backing chip and, while editable,
  **Remove via CO** and **Replace…**.
  - **Remove via CO** posts a `remove` CO line targeting the row; the row
    turns into a **removed** row (below) with **Undo**.
  - **Replace…** opens a modal prefilled from the row's current
    description/qty/price (or, on an adjustment-backed row, just its
    percent — see below) and POSTs a `replace` CO line.
  - **Billed-on gating.** Once a live (non-cancelled) invoice references the
    row, both buttons are `disabled` with a `title="Billed on {invoice
    number}"` tooltip and a matching caption underneath — a billed line
    can't be struck or replaced from the CO surface at all.
  - **Stale-adjustment caption.** A row backed by a percentage adjustment
    whose amount has drifted (a sibling this CO removed/replaced shrank or
    grew the basis) shows a muted "recomputes to {amount} if replaced"
    caption — the number **Replace…**'s adjustment variant would compute if
    used right now.
- [ ] **Replaced rows** (tinted, tagged **CO N**) show the replacement's
  description/qty/price/amount above its struck original (parenthesized
  amount, excluded from totals), plus read-only **"inherited from line
  N"** child rows previewing the claims the original line held — actions
  **Edit** (re-opens the same modal on the CO's own line, PATCHes it) and
  **Undo** (deletes the CO line — the row reverts to an untouched
  agreement row; no confirmation, fully reversible).
- [ ] **Removed rows** show only the struck original, with **Undo**
  (deletes the CO line, reverting to an untouched agreement row).
- [ ] **Added rows** (tinted, tagged **CO N**) show their own claimed-atom
  child rows (each independently detachable) and a Backing chip — actions
  **Edit** / **Remove**, plus **Add selected here** whenever an
  uncovered-work atom below is ticked.
- [ ] **Replace on an adjustment-backed row** opens a different modal
  variant — description + **percent only**, no qty/price fields. Saving
  POSTs the percent; the server recomputes the dollar amount against the
  amended agreement (everything this CO changes, factored in) and the
  modal shows the computed result as a readback with an explicit **Done**
  button — it never auto-closes on save.
- [ ] **Footer math.** Original total → this CO's delta → revised total,
  the delta signed.
- [ ] **Add line** (button, was "+ New line") opens the same
  `PriceListPicker` as the estimate page (§4) to start a fresh **added**
  row.
- [ ] **Uncovered work** (below the table): the CO's own atom pool — Tasks
  and Materials on the job not yet covered by the agreement or this CO.
  Ticking one or more rows reveals **Add selected here** on every existing
  **added** row and a **"New line from selected"** footer prompt (creates
  a fresh added row from the ticked atoms, then opens it for editing). An
  atom already claimed by the estimate or another CO shows as
  unselectable with a "Claimed by estimate {number}" / "Claimed by change
  order {number}" note.
- [ ] **Undo/Remove are local and free.** No confirmation prompt anywhere
  on this table — every gesture here is reversible (Undo restores the
  original row; Remove deletes a CO-authored row the user can re-add).

### Views — Edit / Customer / Reorder

- [ ] **A mode bar** (same as the estimate/invoice pages) offers **Edit**
  (the table above), **Customer**, and — only while the CO is still
  draft/editable — **Reorder**.
- [ ] **Customer mode** shows only the lines this CO actually **changes** —
  a **replaced** row's amount column is the signed delta (new − old), a
  **removed** row shows the negated original amount, an **added** row
  shows its own full amount. Untouched agreement lines don't appear at
  all. Footer: **Change total** and **Revised agreement total**.
- [ ] **Reorder mode** shows only this CO's own added/replaced rows (each
  labeled `CO N — {description}`), with the usual up/down arrows;
  removed rows aren't listed as reorderable.
- [ ] **Deliverables only show in Edit mode** — Customer and Reorder are
  read-only document projections.

## 4. Adding a line — the unified picker (2026-07-03)

Entry: **Add line** on a draft CO (§3).

- [ ] **Opens the same picker as the estimate page** (`PriceListPicker`): one
  search box over Service Items + catalog Inventory Items, plus the freeform
  footer with the **"Is this a material?"** checkbox and **Add Line**.
- [ ] **Service pick → deferred service line.** Choosing a Service Item opens a
  qty form (unit shown beside qty); saving adds an *added* line snapshotting the
  service's price. **No Task is created yet** — the task crystallizes at CO
  acceptance (§6), unless the line was instead built by claiming atoms from
  Uncovered work (§3), in which case there's nothing left to crystallize.
- [ ] **Inventory pick → catalog line.** Choosing an Inventory Item opens a qty
  form; the line lands with the item's description/units/price.
- [ ] **Freeform, material checked → material line.** Description/qty/units/
  price + Accounting Category (pre-filled from the configured material default,
  overridable).
- [ ] **Freeform, material unchecked → plain hand-line.** Same form;
  **Accounting Category is required** — saving without one shows "Accounting
  Category is required." (An added line claiming atoms from Uncovered work is
  exempt from this guard — a claimed atom already carries its own AC.)
- [ ] **Edit modal carries AC.** Editing an added line shows an Accounting
  Category select; replace lines don't (they inherit from the row they
  replace, or — on an adjustment replace — carry no AC field at all).

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

## 6. Acceptance — the deltas become real work (2026-07-03; claim-move rewrite 2026-08-09)

Entry: open CO → **Record Accepted** (or the customer's portal Accept).

- [ ] **Job auto-advances** `on_hold → approved`; the CO shows `accepted`; the
  estimate's status pill reads **amended**.
- [ ] **Added service line → new Task.** The job's task list gains a pending
  Task named after the Service Item, with the line's qty as its estimate.
  (Skipped if the line already claimed an atom from Uncovered work while
  drafting — §3 — there's nothing left to crystallize.)
- [ ] **Added inventory line → new Material** with an earmark for its quantity
  (check Inventory: earmarked rises).
- [ ] **Added freeform material line → provisional Material** (no inventory
  link).
- [ ] **Added plain hand-line crystallizes nothing.** No Task, no Material —
  it stays a document-only line on the CO/agreement.
- [ ] **Removed task line → Task cancelled, bleps preserved, and stamped
  descoped-by-this-CO.** The target line's Task flips to `cancelled`; its
  recorded time is still on the task detail page. A task already
  **complete** is stamped but otherwise left alone (see the billing badge
  below either way).
- [ ] **Removed material line → Material released, and stamped
  descoped-by-this-CO.** The Material row stays on the job greyed out with
  quantity 0 (its planned quantity moved to the released record); its
  earmark is gone from Inventory. A **consumed** material is stamped but
  otherwise left alone.
- [ ] **Removed plain hand-line → line gone** from the agreement (it never had
  a job atom to retire, so nothing is stamped).
- [ ] **Replaced task/material line → the SAME atom, just reassigned to the
  CO's line — no cancel, no new Task/Material.** (2026-08-09 rewrite: a
  replace used to cancel the old atom and mint a mirrored replacement; it
  now moves the existing claim onto the CO's replacement line, so the
  physical task/material — its pk, bleps, status — is completely
  untouched. It is **not** stamped descoped-by either; only a remove
  stamps.) An adjustment-backed replace (§3) crystallizes nothing at all —
  it only changes the percent/target categories.
- [ ] **Removed adjustment line → document-only.** The agreement drops it;
  no job work changes.
- [ ] **Left-alone atoms are badged at billing (2026-07-20, badge mechanism
  rewritten 2026-08-09).** A complete task / consumed material an accepted
  CO removed (not replaced) shows a **"descoped by CO-N"** badge in the
  invoice wizard's uncovered-work pool (`Invoice-Seeding-and-Send.md` §6;
  mechanics: `docs/designs/invoicing-and-expenses.md`
  "Uncovered-work section chips") — read off the stamped `descoped_by`
  field, not re-derived each time.
- [ ] **Agreement view** (`Job → agreement` / invoice **Copy from estimate**)
  reflects the composed result: removed lines gone, replacements in place
  (same underlying claims), added lines appended — and each agreement line
  (atom-backed or a plain hand-line) bills exactly once, via its
  agreement-line reference on the invoice.
- [ ] **A remove/replace targeting an already-billed line can't even be
  saved.** Attempting one on the CO edit page (§3) shows both gesture
  buttons disabled with "Billed on {invoice number}" before acceptance is
  ever reached.

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
| Amended agreement (Edit mode) | agreement row (Remove via CO/Replace…, billed-on disables both) · replaced row (tinted, struck original, inherited claims, Edit/Undo) · removed row (struck, Undo) · added row (tinted, own claims, Edit/Remove/Add selected here) · adjustment Replace… (percent-only, server-computed readback) · stale-adjustment caption · footer totals |
| Views modes | Edit (table above) · Customer (changed-lines-only delta rows + Change total/Revised total) · Reorder (CO's own add/replace rows only) |
| Uncovered work / claiming | tick atoms → Add selected here / New line from selected · claimed-elsewhere note (estimate or another CO) · authored-claim add line skips crystallization on accept |
| Add-line source | service (deferred, no Task yet) · inventory · freeform material (AC default) · plain hand-line (AC required, exempt if claiming atoms) |
| Send | send page + PDF + portal link · resend · AC send guard (pre-email) · empty-CO guard (deliverables-only IS sendable) |
| Acceptance crystallization/move/retire | add → Task / Material+earmark / provisional Material / plain hand-line crystallizes nothing / skipped if already claimed · remove → task cancelled (bleps kept) + descoped_by stamp / material released (qty 0, earmark gone) + descoped_by stamp / plain hand-line just drops · complete task + consumed material stamped but otherwise left alone · replace → claim MOVED onto the CO line, same atom untouched, never stamped · adjustment replace → percent/price only, crystallizes nothing |
| After accept | job approved · estimate "amended" · agreement composed · each agreement line (atom or plain hand-line) bills exactly once via its reference · "descoped by CO-N" badge in the wizard pool (removed atoms only) · billed-on guard blocks remove/replace on an already-invoiced line before acceptance is reachable |
| Reject/revise | rejected stays on hold · seed-new copies deltas · discard draft · portal request-changes supersedes |
| Personas | worker read-only · jobs full · PM scoped |
