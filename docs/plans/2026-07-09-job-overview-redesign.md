# Job overview redesign (workspace step 4) — design spec

_2026-07-09, RM + Claude. Approved direction; supersedes the pillar/accordion
overview. Mockups: `.superpowers/brainstorm/1591-1783649531/content/`
(`overview-lifecycle-v4.html` is the approved render; v1–v3 show the
iteration). Parent design: `docs/plans/2026-07-08-job-workspace-restructure-design.md`
(this is its deferred step 4)._

## Concept

The overview is the job's **summary**, not a work surface. It answers
"where does this job stand?" stage-appropriately through **six lifecycle
blocks in fixed order**, each with a **temperature** driven by job state:

- **Active** — the block's lifecycle moment is live: full-width white card,
  blue left heat-edge, big stat groups, clock lines.
- **Frozen** — the moment has settled: one flat grey line of facts.
- **Dormant** — not yet: one dashed ghost line.

Where the heat sits on the page tells you the job's stage before you read a
number. Blocks never list rows (tasks, line items, POs — the section pages
do that); they show aggregates, clocks, and one-line facts.

**No block-level links** (RM decision 2026-07-09): the rail sits directly
above — corner "open →" links would duplicate it, and Spend has no honest
destination at all. Deferred, deliberately: links on *specific documents
inside* blocks (the PO number, an invoice number, the estimate version) —
RM will feel out what wants to be clickable once the page is live. Build
this pass with no anchors in the blocks.

**No actions on the overview** (RM decision this pass): clocks and signals
are display-only; if actions prove wanted, they come later once the layout
has lived.

## Page composition

- The overview adopts **JobShell** like every other job page (rail
  `current="overview"`, band shown). Its hand-built midband
  (description/deliverables/email grid) and the accordion pillars are
  **deleted** — the context band replaces the midband; the blocks replace
  the pillars.
- Blocks render inside `.page-body`, stacked full-width, generous vertical
  spacing. The page is expected to be tall; that's fine.
- `JobDetailPage.svelte` stays the glue; `JobDetail.svelte` is rebuilt
  around the blocks (this retires most of its 450+-line style block — fold
  in the LATER.md items: the private `.pill-*` palette and the three cloned
  in-content tab bars die with the pillars).

## Visual grammar (shared, promote to app.css)

- Stat groups: label-over-value ("stat spread"), **top-aligned** so the
  label row forms one straight line; sub-lines hang below their own stat
  without disturbing neighbors. Values ~26px bold; labels 12px caps;
  sub-lines 14px. This generalizes the header P&L grid's grammar — name the
  classes generically (e.g. `.stat-spread`, `.stat`, extending the existing
  kit) since other summary surfaces may adopt them.
- Clock lines: full-width line under a hairline within an active card,
  16px. Colors: **red** = counterparty overdue / bad, **amber** = due-date
  pressure, **green** = good news (paid fast, covered, working now).
- Temperatures: `.blk-active` (white card + 5px blue left edge + shadow),
  `.blk-frozen` (flat `#f8fafc` line, 17px), `.blk-dormant` (dashed ghost,
  16px). Generic names — these are "summary block" vocabulary, not
  overview-specific.

## The six blocks

Fixed order: **Scope → Work → Materials → Spend → Invoicing → Delivery.**
(The two money blocks, Spend and Invoicing, sit adjacent deliberately:
spent vs billed vs scope reads as one story.)

Naming decision trail: blocks name *aspects of the job's health*, not
documents (the rail names the surfaces). "Scope" chosen over
Agreement/Contract/Job (contract overclaims legality; Job collides with
the page itself and with Work). "Scope" is used in inherited copy too:
"28% of the $12,400 scope", "starts when the scope is accepted".

### 1. Scope
The agreed what-and-for-how-much: estimate versions, change orders, and
**deliverables** (they are part of scope; the band previews their content,
this block counts them).

- **Dormant** — no estimate exists (estimates are not auto-created):
  `no estimate yet · N deliverables defined` (deliverables part only when
  N > 0).
- **Active** — current estimate is draft or open. Stats: **Estimate**
  (label is "Estimate", value `v2` + status pill; sub-line for superseded
  priors), **Total**, **Sent** (date), **Change orders** (count or —),
  **Deliverables** (count). Clock: while open,
  `No customer response in N days` from `Estimate.sent_date` — quiet under
  7 days, red at ≥ 7.
- **Frozen** — accepted (or rejected/expired, with that fact), AND no CO is
  draft or open: `$12,400 · v3 accepted 6/12 · CO-1 accepted 6/30 ·
  3 deliverables`. An *accepted* CO doesn't reheat the block; it updates
  the frozen total and appends its fact.
- **A draft or open change order re-activates the block** (RM decision
  2026-07-09): the active card then leads with the CO (number + status
  pill + amount delta) alongside the settled estimate facts, and the
  customer-response clock runs on the open CO's sent date exactly as it
  does for an open estimate (same 7-day threshold). A revision
  (new draft estimate version) re-activates likewise.

### 2. Work
- **Dormant** — job not yet approved. If tasks already exist (planned ahead
  of the estimate, e.g. from a worksheet template):
  `12 tasks planned · starts when the scope is accepted`; otherwise just
  the latter clause.
- **Active** — job approved/in_progress with non-terminal tasks. Stats:
  **Progress** (percent by estimated worker time — completed tasks'
  est_worker_time over total; falls back to task-count percent when
  estimates are absent; wide stat with progress bar), **Tasks** (`9 / 14`,
  blocked-count pill in the sub-line when > 0), **Due** (the job's
  `due_date` + sub-line countdown `N working days left`, computed against
  the shop's `schedule_week_envelope` via `calendar_arithmetic` — amber
  within 5 working days, red when past due as `overdue by N working days`;
  the whole stat is omitted when the job has no due date). Clock line:
  who's working right now (task names), green.
- **Frozen** — all tasks terminal / job work_complete+:
  `14 tasks · 64h logged`.

### 3. Materials
- **Dormant** — no POs touch the job and no shortfall signal:
  `nothing on order`.
- **Active** — any open PO, or coverage short. Stats per open PO (number,
  vendor + sent date sub-line; **Due** date stat with amber pressure),
  **Received** count, **Coverage** (the earmark-aware signal merged from
  main: green `OK` / red `SHORT` with sub-line detail).
- **Frozen** — POs exist, all received: `3 POs, all received`.

### 4. Spend
- **Dormant** — nothing spent: `nothing spent yet`.
- **Active** — anything spent, job not terminal. Stats: **Labor** ($ +
  hours sub-line), **Materials** ($ bought), **Total spent** ($, sub-line
  `NN% of the $X scope`).
- **Frozen** — job terminal: same three figures as settled facts.

### 5. Invoicing
- **Dormant** — no invoices: `none yet`.
- **Active** — anything unbilled or unpaid. Stats: one group per invoice
  (label `Deposit · INV-0088` style, value $amount, sub-line the payment
  clock: green `paid in N days` from sent→closed, or red
  `sent N days ago, unpaid`), **Remaining to bill** ($, sub-line), **Billed**
  (percent of scope). If invoice count outgrows the row (> ~4), collapse
  oldest paid invoices into a `N earlier invoices, all paid` group.
- **Frozen** — fully billed and paid.

### 6. Delivery
- **Dormant** — no shipment prepared yet: `N deliverables defined · none
  ready yet` (count clause when deliverables exist).
- **Active** — any shipment prepared-but-not-picked-up (clock:
  `ready since <day>, not picked up` — red past 3 working days), or work
  complete with nothing shipped. Stats: shipped/total deliverables,
  prepared shipments with ready-since.
- **Frozen** — everything picked up: `3 shipments picked up · last 7/18`.

## Data / backend

One aggregate read: extend the job detail payload or add
`GET /api/jobs/{id}/overview/` (implementation's choice; favor a separate
endpoint so the job detail payload stays lean — the overview is one page,
the job payload feeds ten). It must supply what the SPA can't cheaply
compute:

- **Due countdown**: working days from today to `Job.due_date` per
  `schedule_week_envelope` (reuse `calendar_arithmetic`; negative =
  overdue). Null when no due date.
- **Spend split**: labor $ (bleps × effective rates — the same math as
  task `computed_charge`/spent rollups… verify against how
  `Job.spent_amount` is computed and split it labor/materials rather than
  inventing a parallel formula) + materials bought $ + hours logged.
- **Progress aggregates**: est_worker_time total vs completed-task total,
  task counts by status, working-now (task names + workers — the board
  payload's activity fields have this shape).
- Everything else comes from existing serialized data the page already
  fetches (estimates list, invoices list w/ sent/closed dates, POs w/
  dates, shipments/deliverables states) — reuse those fetches; do not
  duplicate them into the new endpoint.

Clock thresholds (estimate-response 7 days, due-pressure 5 working days,
pickup 3 working days) ship as constants with a comment pointing at
Configuration as the eventual home — do NOT build config UI this pass.

## Testing

TDD both stacks. Backend: endpoint aggregates (countdown math against a
fixed envelope + freezegun-style fixed dates — mind the midnight-flake
lesson: no wall-clock-relative test data). Frontend: block temperature
rules per stage (fresh/quoting/production/done fixtures), clock rendering
+ thresholds, stat alignment is CSS (no test), no-actions invariant
(nothing but links in blocks).

## Out of scope

- Actions on clocks/blocks (revisit after the layout lives).
- Lite-view behavior; combo views; Notes.
- Config UI for thresholds.

## Open at implementation time

- Frozen-block "open →" placement (right edge of the line, per mockups).
- Exact copy strings are the mockups' (v4) — treat as canonical unless
  they fight real data.
