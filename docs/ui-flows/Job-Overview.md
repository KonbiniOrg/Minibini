# Job Overview — UI flow

**Purpose:** The overview page (`#/jobs/{id}`) summarizes a job as six read-only
lifecycle blocks in fixed order — Scope → Work → Materials → Spend → Invoicing →
Delivery — each rendered at one of three temperatures: **active** (white card
with a colored left edge and stats), **frozen** (flat grey one-liner of settled
facts), or **dormant** (dashed ghost one-liner, "hasn't started"). This flow
verifies the temperatures, the clocks (customer-response aging, working-day due
countdown, payment latency, pickup aging), and the page furniture around them
(context band, nav rail, change-request banner).

## Personas

- **Any authenticated user** — the whole page is read-only; no permission atom
  changes what the blocks render. (Header/band actions and the rail's target
  pages have their own permission behavior, covered by their own flows.)

## Dev notes

- Block data comes from the job payload plus `GET /api/jobs/{id}/overview/`;
  the due countdown counts **working days** from the shop-schedule envelope in
  Settings (`schedule_week_envelope`), so weekend-spanning expectations differ
  from calendar days.
- Billed % and Remaining to bill use the server's `invoiced_amount`
  (drafts/cancelled/superseded excluded) — the same figure as the header P&L.
  A draft invoice appears as a row but never moves these numbers.
- **Known issue (LATER.md):** a `partly-paid` invoice's row sub-label reads
  "sent N days ago, unpaid" — the aging clock is correct but the word "unpaid"
  overstates it. Report other deviations as likely bugs.

## 1. Fresh job — full dormant stack

- [ ] **Setup:** create a draft job with no estimate, tasks, materials, POs, invoices, or deliverables; open `#/jobs/{id}`.
- [ ] **All six blocks are dashed ghost one-liners:** Scope "no estimate yet", Work "starts when the scope is accepted", Materials "nothing on order", Spend "nothing spent yet", Invoicing "none yet", Delivery "none ready yet".
- [ ] **Furniture renders:** job header, context band (expanded by default), and nav rail all appear above the blocks.
- [ ] **Pre-planned tasks variant:** add tasks to the still-draft job → Work stays dormant but reads "N tasks planned · starts when the scope is accepted".

## 2. Quoting job — Scope active with response clock

- [ ] **Setup:** job with an `open` estimate sent to the customer; open the overview.
- [ ] **Scope is the only white card:** stats show Estimate (version + status pill), Total, Sent date, Change orders count, Deliverables count. Blocks below remain dormant/frozen.
- [ ] **Quiet clock under 7 days:** estimate sent <7 days ago → the "No customer response in N days" line renders uncolored.
- [ ] **Red clock at 7+ days:** estimate sent ≥7 days ago → the response line is red.
- [ ] **Open change order reheats Scope:** on an accepted job, send a CO → Scope returns to an active card and the response clock applies to the CO.

## 3. In-production job — heat mid-page

- [ ] **Setup:** an `in_progress` job with accepted estimate, due date, tasks with estimated time, materials, and at least one PO.
- [ ] **Scope frozen:** grey one-liner with the accepted total and date.
- [ ] **Work active — progress:** progress bar proportioned by estimated time and a "N / M tasks" stat.
- [ ] **Work due countdown:** Due stat shows "N working days left" — uncolored >5, amber ≤5, red when overdue.
- [ ] **Working-now line:** clock a blep in on a task → green "● {worker} working now — {task}" line appears on Work.
- [ ] **Materials coverage:** Coverage stat reads `OK` when nothing needs ordering; add a material that is short with no incoming supply → `SHORT` (red) with "N materials need ordering".
- [ ] **Materials vs POs temperature:** open POs → Materials active with per-PO stats; all POs received and nothing short → frozen "N POs, all received".
- [ ] **Spend active:** Labor $ (with hours), Materials $, and Total with "% of the $X scope" — figures match the header P&L.

## 4. Invoicing block states

- [ ] **Active with latency:** a paid invoice with sent and closed dates shows "paid in N days" (green).
- [ ] **Unpaid aging:** an `open` invoice sent N days ago shows "sent N days ago, unpaid" (red).
- [ ] **Draft row is inert:** a draft invoice renders as a row labeled "draft" — no clock, no tone.
- [ ] **Draft stays out of the math:** with one $3,000 paid invoice and one $9,400 draft on a $12,400 scope, Billed reads 24% and Remaining to bill $9,400.
- [ ] **Guard — draft alone never freezes:** a job whose only invoice is a draft for the full scope stays active at Billed 0%.
- [ ] **Collapse at >4:** five or more live invoices → the oldest paid ones collapse into one "N earlier invoices — all paid" row; exactly four stay individual.
- [ ] **Frozen:** fully billed and every invoice paid → grey "N invoices, all paid · $X billed".

## 5. Delivery block

- [ ] **Dormant with counts:** deliverables defined but nothing prepared → "N deliverables defined · none ready yet".
- [ ] **Pickup aging:** a shipment `prepared` more than 3 working days ago → red "ready since {day}, not picked up".
- [ ] **Frozen:** all shipments picked up → grey "N shipments picked up · last {date}".

## 6. Fully-done job — frozen stack

- [ ] **Setup:** a `completed`, fully invoiced-and-paid, fully shipped job.
- [ ] **All six blocks are grey one-liners** (Scope facts, "N tasks · Nh logged", "N POs, all received", spend figures, "N invoices, all paid · $X billed", "N shipments picked up · last M/D") — no white cards anywhere.

## 7. Page furniture and guards

- [ ] **Band collapse persists across nav:** collapse the context band, go to Tasks via the rail and back → still collapsed (and expand persists likewise).
- [ ] **Band collapse persists across reload:** reload the page → collapse state kept.
- [ ] **Guard — blocks have no links:** hover/click everywhere inside every block — no anchors or buttons; status pills and clock lines are inert text.
- [ ] **Rail navigates:** all eight rail links work from the overview; Overview is underlined as current; empty sections land on their create-affordance pages.
- [ ] **Change-request banner:** a `draft` job with a pending customer change request shows the orange "Customer requested changes: …" banner between the rail and the blocks; the banner contains no links.
- [ ] **Guard — banner absent otherwise:** any job without a pending change request (or not draft) shows no banner.

## Coverage matrix

| Dimension | Cases |
|---|---|
| Block temperature | active / frozen / dormant — each of the six blocks in each reachable state (§1–6) |
| Clocks | response quiet / response red (§2) · due normal / amber / red (§3) · paid latency / unpaid aging (§4) · pickup aging (§5) |
| Invoice statuses | draft / open / partly-paid (known issue) / paid · alone and mixed (§4) |
| Billed math | drafts excluded · full-scope draft not frozen · collapse at >4 (§4) |
| Job lifecycle | fresh draft → quoting → in production → completed (§1, 2, 3, 6) |
| Furniture | band persistence (nav + reload) · rail · change-request banner present/absent (§7) |
| Guards | no links in blocks · draft-alone never frozen · banner absence (§4, 7) |
