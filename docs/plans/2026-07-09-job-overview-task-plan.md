# Job Overview Redesign Implementation Plan (workspace step 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the overview's accordion pillars/midband with the six-block lifecycle summary per `docs/plans/2026-07-09-job-overview-redesign.md` (THE SPEC — its block rules, copy, and mockup `overview-lifecycle-v4.html` are canonical; this plan only sequences the build).

**Architecture:** One backend aggregate endpoint for what the SPA can't compute (working-day countdown, spend split, progress); a pure frontend lib that turns fetched data into per-block view-models (temperature + contents); six small block components on shared summary-block chrome; JobDetail rebuilt around them through JobShell.

**Tech Stack:** Django/DRF + `apps/jobs/financials.py` + `apps/schedule/calendar_arithmetic.py`; Svelte 5; Vitest + Django TestCase.

## Global Constraints

- Branch: `feature/job-overview` only. Never merge/push. NEVER write the dev DB (`manage.py test` only). Vitest from `frontend/` only; one Django runner at a time; judge by `OK`/`FAILED` summary lines. `<tr>` inside `<tbody>`.
- THE SPEC governs content: block names (Scope/Work/Materials/Spend/Invoicing/Delivery), fixed order, temperature rules per block, clock thresholds (7d response, 5wd due, 3wd pickup — constants), copy strings from mockup v4, top-aligned stats, **no anchors inside blocks**, no actions.
- Spend split derives from `apps/jobs/financials.py` internals — never parallel math. `spent == labor + materials_bought` must hold by construction.
- Shared chrome in `app.css` with generic names; components arrange only.
- Backend tests: fixed dates/envelopes only (no wall-clock-relative data — the schedule suite's midnight flake is the cautionary tale).

## Verified facts

- `financials.py`: `_spent = expenses_total + materials_total + _labor_cost` (L92-127); `_labor_cost` = blep hours × `average_labor_cost` config (L69).
- `calendar_arithmetic.py`: `WeekEnvelope`, `is_working_day(d, env)`, `shift_working_days`, `work_minutes_between`. Shop envelope = `schedule_week_envelope` Configuration (schedule.md §2: worker envelopes deliberately NOT used here).
- `Estimate.sent_date` stamped on draft→open (models.py:131); `ChangeOrder.sent_date` (models.py:260); `Invoice.sent_date`/`closed_date` (closed = paid stamp); `Shipment.STATUS_PREPARED/PICKED_UP` + `picked_up_date`.
- JobDetailPage already parallel-fetches contacts/estimates/invoices/purchase-orders/emails/expenses (`JobDetailPage.svelte:21-28`); blocks additionally need change-orders, shipments, deliverables, and the new overview aggregate.
- JobDetail.svelte carries the accordion/pillars, est/inv/po in-content tabs, `.pill-*` palette — all slated to die (LATER.md entries retire with them).

---

### Task 1: `spend_breakdown` in financials + overview aggregates service (backend, TDD)

**Files:** Modify `apps/jobs/financials.py`; create `tests/test_job_overview_endpoint.py` (service part).

**Produces:** `spend_breakdown(job) -> {'labor': Decimal, 'labor_hours': Decimal, 'materials_bought': Decimal, 'total': Decimal}` where `materials_bought` = the existing expenses+materials terms and `total == _spent(job)` **by construction** (`_spent` refactored to sum the breakdown).

- [ ] RED: tests — breakdown terms on a fixtured job (bleps + expense + consumed material + labor-cost config); invariant test `breakdown['total'] == fin['spent']` via `compute_job_financials`; zero-config labor = 0.
- [ ] GREEN: extract the two terms `_spent` already computes into `spend_breakdown`; `_spent` returns its total. Run `tests.test_jobs_financials` (find exact module via grep) + new module → OK.
- [ ] Commit: `feat(api): spend_breakdown — labor/materials split from the financials source of truth`

### Task 2: `GET /api/jobs/{id}/overview/` (backend, TDD)

**Files:** Modify `apps/api/jobs/views.py` (+serializer-free dict response), `apps/jobs/services.py` or new `apps/jobs/overview.py` (service `JobOverviewService.summary(job, today=None, envelope=None)`); extend `tests/test_job_overview_endpoint.py`.

**Produces** (response contract — frontend Task 4 consumes verbatim):
```json
{
  "due": {"date": "2026-07-24", "working_days_left": 11},     // null when no due_date; negative = overdue
  "spend": {"labor": "2340.00", "labor_hours": "41.5", "materials_bought": "1176.00", "total": "3516.00"},
  "work": {
    "tasks_total": 14, "tasks_complete": 9, "tasks_blocked": 1, "tasks_terminal": 10,
    "est_time_total_hours": "64.0", "est_time_complete_hours": "41.0",
    "working_now": [{"task_name": "CNC cut shelving parts", "worker_name": "Dana"}]
  }
}
```
- `working_days_left`: count of working days (shop `schedule_week_envelope`, `is_working_day`) strictly after `today` through `due.date`, negated when past due ("due today" = 0). Service takes `today`/`envelope` params for testability; the view passes real ones.
- IsAuthenticated (read-only summary, same as job detail reads). One extra route on the existing JobViewSet as `@action(detail=True)`.
- [ ] RED: endpoint tests — countdown against a fixed Mon–Fri envelope and pinned dates (incl. weekend spans, overdue, no due date → null, "due today" = 0); aggregates on a fixtured job; auth 403 anonymous.
- [ ] GREEN → run module + `tests.test_api_jobs` → OK. Frontend suite untouched.
- [ ] Commit: `feat(api): job overview aggregate endpoint (countdown, spend split, progress)`

### Task 3: summary-block + stat-spread CSS vocabulary (app.css)

**Files:** Modify `frontend/src/css/app.css` (SHARED section — this vocabulary isn't banner-specific forever, but place beside the banner kit with a comment).

**Produces (generic classes, values from mockup v4):** `.summary-blocks` (column, 16px gap); `.summary-block.active` (white card, `border-left: 5px solid #1d4ed8`, radius 8, shadow, padding 18px 26px 20px) / `.summary-block.frozen` (flat `#f8fafc`, 17px, baseline flex, 22px gap) / `.summary-block.dormant` (1.5px dashed ghost, 16px); `.summary-block-title` (13px/700/caps, `#475569`; min-width 170px inside frozen/dormant); `.stat-spread` (**`align-items: flex-start`**, space-between, 28px gap, wrap); `.stat` > `.stat-label` (12px caps `#94a3b8`) / `.stat-value` (26px/700, `.unit` 15px/500 muted) / `.stat-sub` (14px muted); `.clock-line` (full-width, hairline top border, 16px) + `.clock-bad`/`.clock-warn`/`.clock-good` (`#b91c1c`/`#b45309`/`#15803d`); `.stat-progress` bar (12px track, blue fill).

- [ ] Add classes + header comment; `npm run build` clean. (No component consumers yet — the unused selectors live in app.css, which Svelte doesn't prune; verify no build warning appears.)
- [ ] Commit: `feat(ui): summary-block + stat-spread vocabulary for lifecycle summaries`

### Task 4: `jobOverview` view-model lib (frontend, TDD-heavy)

**Files:** Create `frontend/src/lib/jobOverview.js`; test `frontend/tests/lib/jobOverview.test.js`.

**Produces:** pure functions, no fetching:
```js
export const RESPONSE_CLOCK_DAYS = 7, DUE_PRESSURE_WORKING_DAYS = 5, PICKUP_CLOCK_WORKING_DAYS = 3;
export function scopeBlock({estimates, changeOrders, deliverableCount, now})   // -> {state:'active'|'frozen'|'dormant', ...view fields per spec}
export function workBlock({job, overview /* endpoint payload */, tasksPlanned})
export function materialsBlock({pos, coverage})
export function spendBlock({job, overview, scopeTotal})
export function invoicingBlock({invoices, scopeTotal, now})
export function deliveryBlock({shipments, deliverableCount, job, now})
```
Each returns `{state, stats:[{label, value, unit?, sub?, subTone?}], clock?: {text, tone}, frozenText?, dormantText?}` — components render, the lib decides. All spec rules live HERE: temperatures (incl. Scope's open-CO reactivation with the CO response clock; Work's planned-tasks dormant line), clock texts + thresholds, copy strings from mockup v4, percent maths.

- [ ] RED: fixture the four stages (fresh / quoting / mid-production / done) + edge tests: open CO reactivates frozen scope + runs its clock; response clock quiet at 6 days, red at 7; overdue countdown copy; no-due-date omits the stat; count-fallback progress; invoice overflow (>4 → collapse rule); pickup clock at 3 working days (the lib takes working-day helpers as data — the ENDPOINT supplies due countdown; pickup "working days" may approximate with calendar days if no helper exists client-side — decide, document, test what you build).
- [ ] GREEN, minimal. Run lib tests + full suite.
- [ ] Commit: `feat(ui): jobOverview view-model lib — block temperatures, clocks, copy`

### Task 5: SummaryBlock + six block components (frontend, TDD)

**Files:** Create `frontend/src/components/jobs/overview/SummaryBlock.svelte` (chrome: takes `{title, model}` where model is a lib block result — renders active card w/ stat spread + clock line, frozen line, or dormant line; NO anchors) and `ScopeBlock/WorkBlock/MaterialsBlock/SpendBlock/InvoicingBlock/DeliveryBlock.svelte` (thin: call the lib, pass to SummaryBlock; Work adds the progress bar inside its wide stat). Tests: `frontend/tests/components/jobs/overview/SummaryBlock.test.js` + one per block exercising its stage renders against lib fixtures.

- [ ] RED (component tests: temperature classes applied, stats render label/value/sub, clock tones, zero `<a>` elements inside `.summary-block`) → GREEN → suite.
- [ ] Commit: `feat(ui): overview summary blocks`

### Task 6: JobDetail rebuild (the big one)

**Files:** Modify `frontend/src/components/jobs/JobDetail.svelte` (gut: pillars/accordion, midband, est/inv/po tab strips, `.pill-*` palette, `.panel` grid layout — replaced by JobShell adoption + `.summary-blocks` hosting the six blocks), `frontend/src/routes/jobs/JobDetailPage.svelte` (fetch additions: `/api/change-orders/?job=`, `/api/shipments/?job=`, deliverables count, `/api/jobs/{id}/overview/`; drop fetches only the pillars used — check each), tests `frontend/tests/components/jobs/JobDetail.test.js` + `JobDetail.invoiced.test.js` (rewrite: the accordion assertions die; page-level tests assert shell + six blocks in order + data threading; block behavior itself is Task 4/5's coverage).

- [ ] Study current JobDetail/JobDetailPage FIRST (they changed 2026-07-09 — top-sections consistency commit). Preserve anything the spec doesn't kill (verify: the "latest change request" banner — spec is silent; KEEP it, it's a live workflow aid; place above the blocks).
- [ ] RED (new page tests) → rebuild → GREEN → full suite + build (expect large deletions; no new warnings from touched files).
- [ ] Commit: `feat(ui): overview becomes the six-block lifecycle summary (pillars retired)`

### Task 7: Docs, LATER closures, verification, FINAL WHOLE-BRANCH REVIEW

- [ ] Docs: `jobs-tasks-and-worksheets.md` §9 (overview = six-block summary; pillars gone), architecture doc §5.5a (summary-block vocabulary; overview now uses JobShell — Category I note updates), design docs status notes (step 4 shipped), `frontend/README.md` if routes/stores text touched.
- [ ] LATER.md: retire the JobDetail `.pill-*` palette + in-content est/inv/po tab entries (they died with the pillars); update the oversized-pages JobDetail line; keep the status-pill double-select bug entry (untouched).
- [ ] Verification: frontend suite + build; backend full suite in background, read summary lines (midnight-flake caveat if applicable).
- [ ] Commit docs; then the **final whole-branch review** (pending since steps 1-3): review package `4d2675cd..HEAD` (now includes RM's interim commits + merges from main + steps 4), most capable model, with the SDD ledger's Minor-findings list for triage.

## Self-review notes
- Spec coverage: six blocks + temperatures (T4/T5), no-links rule (T5 test), stat alignment (T3), countdown/spend/progress (T1/T2), CO reactivation clock (T4), planned-tasks dormant (T4), deliverables in Scope (T4/T6 data), pillar/CSS retirement (T6), thresholds-as-constants (T4), no actions (T5 test), docs (T7).
- Deliberately open (per spec): pickup-clock working-day precision (T4 decides + documents), fetch-set pruning in T6.
