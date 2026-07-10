# Later — small issues & tech-debt log

A running list of **small** issues and tech-debt notes worth tracking but not worth a
full spec or bug report. Add an item when you notice debt or a minor rough edge in
passing; remove it once it's addressed. Keep entries short.

**What belongs here:** minor rough edges, "we picked X ad-hoc, should we standardize?",
small cleanups, follow-ups too small to spec. **What does *not*:** anything that grows
into a real feature or a genuine bug — those graduate to `docs/plans/` (a spec) or a
proper issue.

**Entry format:**

```
- **<short title>** — _added YYYY-MM-DD_
  One or two lines of context / why it matters.
  _Done when:_ the concrete condition that lets us delete this entry.
```

---

## Oversized route pages to componentize

The `src/routes/**` page components were intentionally left out of the front-end
test sweep — routes are integration glue (params → API load → pass to child
components → navigate), and that glue belongs to a future E2E track, not unit
tests (see `docs/designs/frontend-testing.md`). Most route pages are thin glue
and fine as-is. But several have grown large by mixing that glue with significant
**inline logic and sub-views** that were never extracted into components.

When the UI-organization / clarity pass reaches each of these, break the inline
logic and sub-views out into components (and lib helpers) — the same pattern that
made the rest of the SPA testable — then unit-test the extracted pieces. Don't
wrap a 1000-line page in heavy mocks; extract first.

**Primary (≥ 400 lines, as of 2026-06-04):**

- `change-orders/ChangeOrderDetailPage.svelte` — **1038**, now **1117** (by far the largest; top
  priority). As of 2026-07-09 it's pulled **into** the job workspace: it lives at the job-scoped
  route `/jobs/:jobId/change-order/:coId` (old `/change-orders/:id` redirects via
  `ChangeOrderRedirect.svelte`) and renders JobHeader + JobContextBand + JobNavRail (current
  "estimate") + the shared estimate/CO version subnav inline — but it is **not yet extracted**
  into a panel component hosted by `JobShell` the way estimates/invoices are. That extraction is
  the remaining work; sequenced last once the shell pattern is boring on simpler documents.
- `jobs/TaskDetailPage.svelte` — 527
- `Search.svelte` — 499
- `purchaseorders/PurchaseOrderDetailPage.svelte` — 461
- `worksheets/WorksheetDetailPage.svelte` — 407

**Extracted by the 2026-07-08 job-workspace restructure** (no longer oversized — thin route
glue now hosts a tested panel component through `JobShell`):
`jobs/JobTaskListPage.svelte` (was 427 → `TasksPanel.svelte`),
`jobs/JobShipmentsPage.svelte` (was 418 → `ShipmentsPanel.svelte`),
`estimates/EstimateDetailPage.svelte` (was 344 → `EstimatePanel.svelte`, and the route file
itself is now a 12-line redirect shim), `invoices/InvoiceDetailPage.svelte` (→
`InvoicePanel.svelte`, also now a 12-line redirect shim).

**Watch list (300–365 lines):** `schedule/SchedulePage.svelte` (365),
`users/UserDetailPage.svelte` (306), `contacts/ContactListPage.svelte` (301).

_Done when:_ each oversized route has had its UI pass with inline logic/sub-views
extracted into (tested) components, or a deliberate note recorded for why a given
page stays whole.

> Resolved 2026-07-09: `components/jobs/JobDetail.svelte`'s deep
> derivations (version timeline, CO delta layering, etc.) were the
> accordion-pillar era's logic. The 2026-07-09 overview redesign
> replaced the pillars with six summary blocks and extracted every rule
> into `lib/jobOverview.js` (pure functions, unit-tested) + one dumb
> renderer (`components/jobs/overview/SummaryBlock.svelte`) + six thin
> wrapper components — `JobDetail.svelte` itself is now ~120 lines of
> glue. No longer oversized; no longer carries untested deep logic.

---

## Job & estimate lifecycle (decisions)

Status coupling, transitions, and what a job may do at each stage.

- **Release-to-floor should require at least one Task — placement undecided.** — _added 2026-07-02_
  A job with no Tasks shouldn't be releasable to the floor (`approved → in_progress`).
  A first pass built this but it was **removed pending a design decision** — the code
  (view-layer guard in `JobViewSet.perform_update`, a `hasTasks` disable on
  `JobHeader.svelte`'s "Release to floor" button, and `tests/test_release_to_floor_guard.py`)
  was reverted so it doesn't ship half-decided.
  **Gating question (blocks any implementation):** *is a taskless, hand-billed, paid job a
  supported flow?* This determines where the guard belongs — and it must be decided on
  merits, not on test blast radius (see CLAUDE.md → Engineering Principles):
    - **If NO** — `in_progress ⇒ has tasks` is a true invariant → enforce deep (in
      `Job.clean()` or `JobService.update_job`). Then `maybe_complete_if_resolved` (which
      today mechanically steps `approved → in_progress → work_complete → completed` because
      `Job.VALID_TRANSITIONS` has no direct `approved → completed` edge) must be fixed so a
      never-worked job doesn't fake-traverse `in_progress` — likely a direct terminal path.
    - **If YES** — the completion cascade legitimately completes taskless jobs, so a hard
      invariant would wrongly block it. Guard the *user action* at the view layer (as the
      reverted pass did), justified by "release to floor is a deliberate user action distinct
      from the cascade's status walk" — NOT by cascade-breakage/test convenience.
  _Note:_ `mark_work_started` (blep-start) always reaches `in_progress` with the just-started
  Task present, so it's unaffected either way. _Done when:_ the gating question is answered and
  the guard is (re)placed accordingly, with the cascade fixed if the answer is "no".

- **Job status can be changed independently of estimate status → incoherent states.** — _added 2026-07-03_
  Observed in browser: while testing acceptance crystallization, a Job was set directly to **Approved**
  while its Estimate was still **Open**, and the transition was allowed. This is incoherent: Job
  approval is meant to flow from **estimate acceptance** (the `estimate_accepted` signal both approves
  the Job *and* runs `EstimateAcceptanceService.on_accept` crystallization). Setting `Job → Approved`
  directly bypasses acceptance entirely — no crystallization runs, the estimate never leaves Open, and
  the Job looks committed with nothing crystallized behind it. Decide the coupling: either gate direct
  Job status transitions so `approved` can only be reached via estimate acceptance (not a bare
  status edit), or make a direct Job approval with a live Open estimate a validation error, or reconcile
  the two on transition. Also audit which UI affordance let the Job status be edited directly here.
  _Done when:_ Job↔Estimate status coherence is enforced (a Job can't be `approved` with an un-accepted
  live estimate, or the transition drives acceptance) and the stray edit path is closed.

- **Task creation on a terminal `completed` job — block it or define a reopen path.** — _added 2026-06-17; narrowed 2026-07-04_
  (The `work_complete` half is delivered: `JobService.mark_work_reopened` pulls
  the job back to `in_progress` when an incomplete task lands.) Remaining:
  task creation is still allowed on a **terminal `completed`** job (only
  `on_hold` is blocked), which has no outgoing transition to reopen — either
  block adding tasks there or define a reopen path. Related: an on-hold job
  released back to `work_complete` *after* a CO added incomplete tasks would
  be incoherent (release restores prior status without re-checking) — decide
  with the same pass.
  _Done when:_ the `completed`-job case is decided (blocked or reopenable) and
  the on-hold-release path re-checks task state.

- **Deliverable freeze under the no-estimate case.** — _added 2026-06-01_
  The job-duplicate "immediately approved" path produces a Job with **no estimate** —
  deliverables, tasks, materials only. `DeliverableService.is_editable` keys on estimate /
  CO state, so a no-estimate job's deliverables stay **editable in any status**, tightening
  only as rows **anchor** (gain a `ShipmentItem`). Accepted for now, but we may want a
  harder freeze point for no-estimate jobs (e.g. freeze on `in_progress`, or on first
  shipment regardless of which row) so the agreed scope can't drift indefinitely. Revisit
  if loose-forever deliverables on a duplicated approved job cause trouble in practice.
  _Done when:_ we've decided whether no-estimate jobs need a status-based deliverable
  freeze and either added one or recorded why anchoring alone is sufficient.

- **Pull `description` off `ServiceItem`; specifics live on the Task/line description.** — _added 2026-07-02_
  A `ServiceItem` is meant to be a *rough work type* (name + rate scheme); the per-job specifics
  belong on the **Task description**, sourced from the estimate line's editable description. So
  `ServiceItem.description` should be removed. Confirmed direction from the add-line/picker work: a
  service-picked estimate line prefills its description from the ServiceItem *name*, the user can
  edit it, and at crystallization `Task.name` = the ServiceItem's name while `Task.description` = the
  line's description. Once the line description carries the specifics, `ServiceItem.description` is
  redundant. (Ties to the add-line/picker plan and the earlier "service item = rough work type" note.)
  _Done when:_ `ServiceItem.description` is removed (migration + code + fixtures) and specifics are
  sourced from the Task/line description everywhere.

- **Terminology: rename worksheet / estimate / wizard for the consolidated flow.** — _added 2026-06-25_
  Under the planning-consolidation direction (worksheet = the single authoring
  surface; estimate = a frozen customer-facing projection), reconsider the
  user-facing names: **Worksheet → "Estimate"** (it's where you build the estimate),
  the current frozen **Estimate → "Customer View"**, and the **wizard →
  "Consolidate Lines"** (its actual job is grouping atoms into lines). UI
  labels/terminology only — internal model names can stay. Revisit with
  `docs/plans/2026-06-24-planning-billing-consolidation-draft.md` (§11 already flags
  the worksheet-naming question).
  _Done when:_ the consolidation design settles on user-facing names and the UI is
  relabeled (or the idea is explicitly dropped).

- **`Fee.task` is a dormant field — decision record so nobody re-researches it.** — _added 2026-07-03_
  RM decision: **leave it alone** (keep the field; don't wire it, don't drop it). The research, so it
  never needs redoing:
  - *Origin:* the job-owns-atoms lenses spec (`2026-06-29-job-owns-atoms-documents-as-lenses.md`,
    commit `23345f83`; retired from the tree in `c85fac6c`) defined Fee with "an optional `task` link
    (for 'the work behind it')". Motive: `flat_fee` was removed from RateScheme ("its job is now
    Fee's"); "Task stays pure work; money never sits on it" — so the link was the designed home for
    **fixed-price work**: Task carries the labor (bleps/schedule/completion), Fee carries the frozen
    price. Successor to the May flat-fee-on-task design (`2026-05-17-flat-fee-pricing-design.md`).
  - *Why it's dormant:* both planned hooks fell out during implementation. Acceptance was to "link a
    task if one was named" but `EstimateLineItem` never grew a task-naming field; the impl plan's
    Task 7.3 specced `FeeModal` with an "optional task link" but the modal shipped with only an unused
    `taskId` prop. No production reader exists: the invoice wizard pool is task-grouped yet files every
    fee under a flat "Fees" group (`task_id: None`); only `validate_data` reads it (job-consistency).
    The API PATCH accepts `task` but no UI sends it.
  - *The unsolved design hole (why not to wire it casually):* a fee-linked Task is still metered
    (`rate_scheme` NOT NULL), so it would bill in the invoice pool *alongside* the Fee that is its
    price — fixed-price work needs either a $0/internal-scheme convention or pool logic suppressing a
    task's metered billing when a linked Fee covers it. Neither exists.
  - *Hazards while it sleeps:* it's a **OneToOne** — any future Fee-retirement state must null the link
    or a retired fee blocks a replacement fee on the same task (MySQL: no conditional uniqueness; the
    2026-07-03 deletion doctrine deferred the Fee `retired` state to this same future pass).
    `Task.delete()` SET_NULLs it.
  _Done when:_ fixed-price work gets designed as its own feature (Fee↔Task pairing + the
  pool-suppression rule, perhaps with the deferred `FeeItem` catalog) — or the field is dropped in
  that design's place.

- **Job status pill jumped draft→Approved when "Submitted" was chosen (possible double-select).** — _added 2026-07-09_
  Observed once on a job freshly created from an email: using the header status pill
  (`JobHeader.svelte`'s `<select>` trigger pill) to set **Submitted** landed the job on
  **Approved** instead. The transition graph is `draft → submitted → approved`, and the pill
  re-renders its valid-next options after each change — so a stray second `change` (an
  accidental double-click, or an event firing against the just-re-rendered option list) would
  walk `draft → submitted → approved` in a single gesture. Not reproduced deliberately; may be a
  pure double-click artifact or a real re-render/handler race in the trigger pill. Worth checking
  `handleStatusChange` for whether a rapid second selection can chain past the intended status
  (e.g. debounce, or ignore a change while a transition is in flight).
  _Done when:_ reproduced and fixed (one selection = one transition), or confirmed a stray
  double-click that can't reasonably recur.

## Job overview (2026-07-09 six-block redesign)

The overview replaced its accordion pillars with six lifecycle summary
blocks this pass (`docs/plans/2026-07-09-job-overview-redesign.md`;
durable reference `docs/designs/jobs-tasks-and-worksheets.md` §9). Debt
and open questions specific to that redesign:

- **`ShipmentsPillar.svelte` and `Accordion.svelte` are orphaned.** — _added 2026-07-09_
  `components/jobs/ShipmentsPillar.svelte` (the read-only shipments
  matrix that used to sit in the accordion between Invoices and
  Purchase Orders) has zero importers now that the accordion pillars
  are gone — the overview's Delivery block shows aggregate stats only,
  and the full matrix already lives on the Shipments section page
  (`ShipmentsPanel.svelte`). Same story one layer down:
  `components/Accordion.svelte` (+ its private `css/accordion.css`) had
  exactly one consumer, `JobDetail.svelte`'s pillar expand/collapse,
  which is also gone — nothing else in the app imports `Accordion.svelte`
  today (only its own test, `tests/components/Accordion.test.js`, still
  references it directly). _Done when:_ RM confirms nothing planned
  wants either component, then both (`ShipmentsPillar.svelte`,
  `Accordion.svelte` + `accordion.css` + their tests) are deleted — or a
  future reuse is identified and they stay.
- **Overview Coverage stat counts only `materialStatus` "Needed" as SHORT.** — _added 2026-07-09_
  The Materials block's Coverage signal (`JobDetail.svelte`'s `coverage`
  derivation, consumed by `materialsBlock()` in `lib/jobOverview.js`)
  flags `SHORT` only when a job material's status is exactly **Needed**
  (established, stock short, no PO link). Materials in **Needs pricing**
  or **Awaiting customer** are also short of stock with no incoming
  supply lined up, but don't count toward `SHORT` — so a job stuck
  waiting on pricing or a customer-supplied item can show a clean `OK`
  Coverage stat while materials are, in practice, not covered. Revisit
  if RM wants those statuses folded into the SHORT count (or a separate
  signal for them) once the block has lived a while.
  _Done when:_ RM has decided whether Needs-pricing/Awaiting-customer
  materials should affect the Coverage stat, and the behavior matches.

## Change orders

The CO surface and its estimate-parallel code.

- **Validate the multi-change-order display (2+ COs).** — _added 2026-05-27_
  We spec'd `ch-1`/`ch-2` per-line tags but haven't built/validated how the CO view reads
  with two or more COs on a job: how the 1st CO's lines/deliverables show once a 2nd
  exists, and how the 2nd (and further) indicate they're later versions layered on the
  prior agreement. Look at this before closing the branch.
  _Done when:_ the CO view is legible with ≥2 COs (version layering + ch-N tags read clearly).
  Related: the **customer portal** CO line-item diff baselines off the flat
  accepted estimate (`compose_change_order_diff` uses `co.estimate`), not
  `compose_agreement`, mirroring the shop edit page. With multiple accepted COs
  this can understate the true current agreement the customer sees. Resolve as
  part of the multi-CO validation above. (Note 2026-07-03: this is now
  **display-only** — CO-acceptance *crystallization* resolves targets through
  the accepted-CO replace chain correctly; see `estimates-and-prices.md`
  §14.11.)

- **Surface CO-remove atoms that crystallization deliberately skipped.** — _added 2026-07-03_
  `ChangeOrderAcceptanceService` (estimates doc §14.11) leaves an atom alone when a
  CO remove/replace targets it but it is already consumed / complete /
  expense-bound / PO-linked / on a live invoice — physical or billed reality is
  not unwound by a document. Right now that skip is silent (the atom just stays
  on the job while the agreement line is struck); the human has to notice the
  mismatch themselves. Consider surfacing it — a history entry per skipped atom,
  or a "struck from agreement" badge on the task/material row — so the
  reconciliation is prompted rather than remembered.
  _Done when:_ decided and either implemented or recorded as acceptable-silent.

- **Consolidate the estimate↔change-order parallel code.** — _added 2026-06-08_
  Building COs "as parallel to estimates as reasonably can be" deliberately
  produced sibling duplicates that now drift independently: `ChangeOrderEmailService`
  vs `EstimateEmailService` (get_email_defaults / notify_shop_of_decision / send_*
  are near-identical); `apps/api/portal/change_order_views.py` vs `views.py`
  (`_money`, `_not_available`, `_actor_for`, `_is_actionable`, the `_decide`
  skeleton); `ChangeOrderPortal.svelte` vs `EstimatePortal.svelte` (~120 shared
  lines of the confirm/submit state machine + fieldsets); and `change_order_pdf.html`
  vs `estimate_pdf.html` (shared CSS + header-info block + party-context resolution
  in pdf.py). Candidates: a `DocumentEmailService` base with class-level subject/body
  + config keys + a pdf-generator hook; a `portal/common.py`; a `<PortalDocument>`
  wrapper with a slot for the body table; a shared PDF header `{% include %}` +
  `_pdf_party_context(job)` helper. (A diff-logic note: `compose_change_order_diff`
  is also a Python re-implementation of the frontend `mergedRows`; keep them in
  lockstep until/unless the shop view reads the server composer too.)
  _Done when:_ the shared paths live in one place (or we record why the duplication
  is acceptable).

- **Hide "Create Change Order" on the estimate once a CO exists — further COs chain off the prior CO.** — _added 2026-07-09_
  The estimate panel's Create Change Order button (offered on an accepted estimate,
  restored temporarily this session) should disappear once the job already has a
  change order. The *first* CO is created from the accepted estimate; every
  subsequent CO is seeded from the previous one via the CO page's "Start new change
  order" (`seed-new`) flow, so COs chain off one another rather than each branching
  fresh from the estimate. Gate the estimate-panel button on "no CO exists yet" and
  rely on `seed-new` for the rest.
  _Done when:_ the estimate's Create Change Order button is hidden once any CO exists
  on the job, and additional COs are created only via the seed-new chain.

- **Change order with only deliverable changes (no line items) is refused at Send.** — _added 2026-07-09_
  A change order that changes only deliverables — no line-item edits — can't be
  sent to the customer; the send path treats a CO with no line items as empty
  and refuses it. But a deliverables-only amendment (e.g. quantity/spec change
  with no price impact) is a legitimate thing to send for sign-off. Decide
  whether this is correct (a CO must carry a line-item change to be sendable) or
  whether deliverable-only COs should be sendable, and adjust the send gate
  accordingly.
  _Done when:_ the deliverables-only-CO send behaviour is decided and either the
  refusal is kept with a recorded reason or the send gate accepts them.

## Invoicing, expenses & payments

Billing mechanics and money-record lifecycle.

- **"Start Invoice" on a draft job errors with misleading wording — reword and reconsider the gate.** — _added 2026-07-09_
  Clicking the lone **Start Invoice** button on a fresh (draft) job's invoice panel raises
  `InvoiceWizardService.open_for_job`'s error (`apps/invoicing/services.py`): *"Cannot start
  invoice wizard for job in status 'draft'. Job must be approved or completed."* Two problems:
  - **Wording:** the UI button says "Start Invoice", not "invoice wizard"; and "approved or
    completed" mislists the actual `BILLABLE_JOB_STATUSES` (approved, in_progress, work_complete,
    completed, cancelled). At minimum reword to match the UI term and the real allowed set.
  - **Gate placement:** the Start-Invoice button shows on a non-billable job at all, so the only
    outcome of clicking it is an error. Reconsider — likely hide/disable it (with a hint) until
    the job is billable, the way the estimate panel gates Create Change Order, so the error is
    unreachable through the UI.
  _Done when:_ the message is reworded (UI term + accurate status list) and the Start-Invoice
  affordance is gated to billable jobs (or a decision is recorded that the raw error is the
  intended UX).

- **Re-billing Task actuals across multiple invoices.** — _added 2026-06-02_
  Invoices can be raised before a job is finished (e.g. progress billing). If invoice #1 is
  finalized and bills the actuals of Task A, then Task A gets more work logged, and later
  invoice #2 is generated for the same job, it's unclear how Task A's actuals are handled on
  the second invoice — does it re-bill the full actual (double-billing the earlier portion),
  bill only the delta since invoice #1, or refuse the atom as already-claimed? The atom-claim
  model (`InvoiceLineItemSource`) tracks which invoice claimed an atom, but a Task whose
  actuals *grew* after being billed has no defined delta-billing behavior. Decide and enforce
  the rule (likely: disallow billing anything on an incomplete Task).
  _Done when:_ there is no conflict or confusion between items billed on an earlier vs on a later invoice.

- **Invoice revisions — back the "Revise (coming soon)" placeholder.** — _added 2026-06-04_
  `InvoiceDetailPage.svelte` shows a **disabled** "Revise (coming soon)" button on sent
  invoices (`canSeeRevise`), shipped as a placeholder — there is no invoice-revision backend
  (no `InvoiceService.revise`, no supersede/version chain like estimates have). Decide
  whether invoices need a revise flow at all (vs. cancel + new invoice) and, if so, build the
  backend + wire the button. _Done when:_ either the placeholder is backed by a working
  invoice-revise flow, or it's removed with a recorded decision that invoices don't revise.

- **Voided-not-vanished for post-approval Expenses and BillPayments.** — _added 2026-07-04 (deferred from the deletion-doctrine pass)_
  An approved, uninvoiced Expense is still hard-deletable, and `delete_payment`
  removes money actuals outright. QBO already thinks in voids, so a `voided`
  status (retained record, excluded from money math) fits the deletion doctrine
  better than delete for both. Explicitly deferred out of the 2026-07-03
  doctrine implementation; each deserves its own small pass.
  _Done when:_ both have a voided path (or a recorded decision that delete is
  fine), consistent with the doctrine's actuals-gravity rule.

- **Adjustment amount on a superseded estimate looks inconsistent (possible doubling).** — _added 2026-06-27_
  Observed in dev data: estimate **110** (superseded by estimate **116**) shows a **$44**
  percentage adjustment where, for consistency with that estimate's own line values, it
  should be **$22**. $44 ≈ 2×$22 smells like a **doubling**. Adjustments are document-scoped
  today: `compute_adjustment_amount` (`apps/core/adjustments.py`) = `(rate/100) × Σ(non-adjustment
  sibling totals in the target-category set)`, re-run by `recompute_adjustments` via
  `LineItemService.save_line_item` after any line mutation; and `revise_estimate`
  (`apps/estimates/services.py` ~L149–153) **copies** `adjustment_service` + re-sets the
  `adjustment_target_categories` M2M onto the new revision. Things to check: (a) whether a
  superseded estimate's adjustment line is **frozen** at supersession or still gets
  recomputed against a changed/duplicated sibling set; (b) whether `revise_estimate` double-counts
  (e.g. the adjustment computed over a sibling set that includes copied/duplicated lines, or the
  M2M set applied twice); (c) whether the value is simply stale vs. the displayed lines. Capture
  est 110 / 116's line items + the adjustment's `adjustment_service.rate` and target categories
  when investigating. NOTE: this whole area is slated to change in **Phase 8** (job-scoped,
  auto-applied adjustments — `docs/plans/2026-06-26-phase8-job-scoped-adjustments.md`); decide
  whether to fix the document-scoped bug now or fold the check into that rework.
  _Done when:_ the superseded-estimate adjustment is confirmed correct (or root-caused + fixed),
  with the doubling explained.

- **Customer-facing public URLs for documents (`{object_url}` real resolution) — ESTIMATES DONE.** — _added 2026-05-29; estimates resolved 2026-05-31_
  Estimates are now fully shipped: `Estimate.public_token` is minted at creation;
  `build_object_url('estimate', id)` resolves to `/portal/?token=<token>`; the
  `/api/portal/estimates/<token>/` read/accept/reject endpoints are live (AllowAny,
  token-authorized); the customer page is at `frontend/portal/` (second Vite entry).
  See `estimates-and-prices.md` §15.1 for the full spec.
  Change Orders are now shipped too (_2026-06-07_): `ChangeOrder.public_token`,
  `build_object_url('change_order', id)` → `/portal/?token=<token>&doc=change_order`,
  the `/api/portal/change-orders/<token>/` read/accept/reject/request-changes
  endpoints (AllowAny), `ChangeOrderEmailService` (send-to-customer link +
  shop notification), and the `ChangeOrderPortal` customer view (dispatched by
  the `doc` query param off the same `/portal/` entry). See
  `estimates-and-prices.md` §14.10.
  CO PDF generation is now done too (`generate_change_order_pdf` renders the
  diff via `change_order_pdf.html`; the CO send email attaches it alongside the
  portal link).
  **Remaining:** PO / Invoice / Bill public URLs (no token column, no portal
  view).

- **Expense invoice-freeze has no billability-readiness gate, by design.** — _added 2026-06-17_
  Expense atoms have an invoice-freeze (`ExpenseService._assert_not_invoiced`)
  but no separate billability-readiness gate — they appear as selectable in the
  wizard pool from the moment they are submitted (unlike Tasks, which require
  `complete`, and Materials, which require `consumed`). This is deliberate: an
  expense is ready to bill as soon as it exists. Revisit only if a
  "not ready to bill" expense state is ever needed.

## Wizard & line-item UX

The atom-pull surfaces on estimates and invoices.

- **Wizard's by-hand line item uses an inline editor, not the LineItemModal.** — _added 2026-06-03_
  Adding a manual line item from the detail page uses the new `LineItemModal` (manual/catalog
  toggle), but adding one inside the wizard uses a separate inline editor (likely the same one
  used when grouping atoms). Two different entry surfaces for "add a line item by hand" is
  confusing. Converge on one. _Done when:_ adding a manual line item uses the same component
  whether on the detail page or in the wizard.

## Purchasing & inventory

(The procurement-machinery items moved into the freeform-materials plan
2026-07-04; the plan shipped 2026-07-05 and the still-open ones returned below.)

- **PO line form needs an explicit "attach to existing material" picker.** — _added 2026-06-20; returned 2026-07-05 from the freeform-materials plan (not built)_
  When adding a PO line for a job that already has materials, there's no way to
  deterministically attach the line to a *specific* existing pending material — the
  resolver only auto-claims on an exact single match, else silently creates a
  duplicate. (The `material_id` explicit path exists on the API and is used by the
  one-shot "order this material" prefill, but the manual add-line form never offers
  it.) Fix: once a Job is selected on the PO line form, surface that job's pending
  unlinked materials and let the user pick "attach to this one" (explicit
  `material_id`) or "create new". _Done when:_ deterministic attach with tests.

- **Mixed-receipt expense loses the non-inventory cost.** — _added 2026-06-14; returned 2026-07-05 from the freeform-materials plan (consciously punted)_
  An expense is single-mode (cost OR stock receipt). One trip buying both an
  inventoried shortfall and a special non-item finish silently drops one side.
  Dropping `is_catalog` changed the classification rule (any item-backed purchase =
  stock receipt) but did **not** fix the mixed case. _Done when:_ multi-item
  expenses or a split prompt exist so a non-inventory cost can never be silently
  swallowed.

- **Expense didn't count as a cost in the job overview (no catalog item picked) — investigate.** — _added 2026-06-18; returned 2026-07-05, possibly obsolete_
  Reported pre-rework: an expense missing from job cost with no catalog item
  selected, so the stock-receipt classification shouldn't have fired — cause never
  found. The expense-attach flow was rebuilt by the freeform-materials work
  (attach == receipt, establishes provisional materials), so the original repro
  context is gone. Re-test on the new flow; if it can't reproduce, delete this
  entry. _Done when:_ reproduced and fixed with a test, or shown obsolete.

- **Decide whether "drops" (offcuts/scraps) get an unbacked-material lane or lightweight lots.** — _added 2026-07-05 (parked during the freeform-materials design)_
  The "no permanently-unbacked Material" rule (every Material establishes to a lot)
  serves drops worst. RM deliberately parked this: exercise the
  provisional→established/lot process first, then decide whether drops justify a
  genuine unbacked category. Note: mark-on-hand + lot reuse may already cover most
  drops in practice (a $0-ish minted lot marked on-hand). _Done when:_ RM has
  decided drops get an unbacked lane, lightweight lots, or the status quo, and the
  materials doc records it.

- **Show a material's earmarks on the PO when ordering it.** — _added 2026-07-05_
  Certain items are needed by more than one job at once. When adding/receiving a PO
  line for such an item, the buyer can't see the total demand — the per-job earmarks
  against the line's inventory item — so they can't easily decide to order for
  several jobs in one purchase. Surface the item's earmark list (job + quantity)
  on the PO line (and/or in the order-from-material flow) so multi-job demand is
  visible at order time. _Done when:_ ordering an item with earmarks from multiple
  jobs shows those earmarks on the PO surface, and the buyer can size the line
  accordingly.

- **Delete-after-reject of a `stock_pli` expense double-reverses QOH.** — _added 2026-07-05 (found during the freeform-materials Task 9 review; pre-existing)_
  `ExpenseService.reject` already reverses a stock-receipt expense's QOH bump. But
  the **delete** branch has no status guard: deleting an already-rejected
  `stock_pli` expense reverses the QOH a **second time**, driving stock negative.
  This is the same shape the freeform-materials attach fix guarded (the shared
  `_unwind_attach` is skipped on delete when the expense was already unwound at
  reject) — the stock-receipt delete path needs the same "already reversed?"
  guard. _Done when:_ deleting a rejected stock-receipt expense doesn't
  double-reverse QOH, with a regression test.

- **PO/Bill vendor field: let users search by contact name but resolve to the business.** — _added 2026-06-21_
  The PO and Bill forms pick a vendor with `BusinessPicker` (searches businesses, returns a
  `business_id`). But a user often knows the *contact* name, not the business name. Idea:
  use a `CustomerPicker`-style picker that **searches contact names too** yet, on selecting a
  contact, **returns that contact's business** (the PO/Bill vendor must be a Business). This
  isn't quite today's `CustomerPicker`, which emits `{type, id}` and can return a standalone
  contact — here we always need a business id, so it'd be an extended/variant picker. Edge
  case to handle: a contact with **no business** can't be used as a vendor — reject it in
  some way (disable that result row with a hint like "no business on file", or block the pick
  with a message), rather than silently returning nothing. _Done when:_ we've decided whether
  to extend `CustomerPicker` or add a vendor-specific picker, defined the contact→business
  resolution + the no-business rejection UX, and wired it into the PO/Bill vendor fields.

- **Inventory merge is still awkward — rework the keep/discard selection + add a preview.** — _added 2026-06-18_
  The merge UI in `CatalogInventoryPage.svelte` (`frontend/src/routes/catalog/`, the `{#if showMerge}` panel, ~lines 147-167) is
  a top-of-page block with two raw `<select>` dropdowns — "keep" and "discard" (`mergeKeep`/
  `mergeDiscard`, discard limited to non-catalog `lotOptions`) — disconnected from the table
  the user is looking at. On a long catalog you re-hunt both items by name in unsearchable
  selects, the merge is **irreversible** (line ~55) yet there's **no preview** of what will
  move (QOH, earmarks, line-item/template references) or which item wins, and it shares the
  top-of-page scroll problem. Directions to make it less awkward: drive selection **from the
  rows** (e.g. pick a discard row's "merge into…" action, or select two rows in the table)
  so you act on what you see; use `InventoryItemPicker` (server-side `?search=`) instead of
  raw `<select>`s; show a **confirmation preview** of the resulting merged item (combined QOH,
  moved references, which id survives) before committing; and put it in a modal/in-place
  surface rather than a top-of-page panel. Related: the inventory-edit-modal note above.
  _Done when:_ merging is driven from the list rows with a searchable picker and an explicit
  before-commit preview of the outcome, no top-of-page dropdown hunting.

## Time tracking (shifts & bleps)

- **Time managers can't reach the shift request queue / payroll report.** — _added 2026-05-31_
  `ShiftRequestQueue` + `PayrollReport` live on the **Shifts tab of the Users page**
  (`routes/users/UserListPage.svelte`), but the "Users" sidebar link is gated on
  `can_manage_config` (`Sidebar.svelte`). A manager with `can_manage_time` (or
  `can_manage_financials` for the report) but not `can_manage_config` has no nav path to
  it — exactly the people meant to approve requests / run payroll. Likely fix: a dedicated
  "Shifts"/"Time" sidebar link gated on `can_manage_time OR can_manage_financials` routing
  to a small page that hosts the queue + report, decoupled from user-admin.
  _Done when:_ a `can_manage_time`/`can_manage_financials` manager can navigate to the
  request queue and payroll report without `can_manage_config`.

- **Surface the conflicting *shift* for a blep change request that needs a wider shift.** — _added 2026-05-31_
  The request queue now lists conflicting records (`conflicts`): a shift request shows the
  bleps it would orphan, and a blep request shows the worker's *overlapping* shifts to
  widen. But a blep request whose new time has **no** overlapping shift at all (worked a
  span with no shift) surfaces nothing to open — the manager must create a shift, and there's
  no manager UI to create/edit an arbitrary worker's shift outside this queue's modal.
  _Done when:_ a manager can resolve a blep request that needs a brand-new shift (create one)
  directly from the review flow.

- **BUG (investigate): Shift & Blep start times display ~1 hour early, unmodified.** — _added 2026-06-25_
  Observed in browser review: a Shift's and a Blep's `start_time` came through about
  **one hour earlier** than the actual time, with no edit made to the record. A
  one-hour (not whole-timezone) offset smells like a **timezone / DST** handling
  issue (naive-vs-aware datetime, or a standard-vs-daylight conversion) in
  serialization or display — note it's currently DST. Suspects: `Shift.save()` /
  `Blep.save()` `floor_to_minute` (`apps/core/timeutils.py`), the blep/shift
  serializers, or the SPA's time rendering. This is a genuine bug — promote to a
  proper issue/spec once reproduced; logged here per request so it isn't lost.
  _Done when:_ a Shift/Blep start_time displays the exact time entered across DST,
  with a regression test pinning the timezone behavior.

## Cross-client refresh & notifications

All three want the same shared live-refresh/notification mechanism (see the general-repolling project note).

- **Notify the requester when an approval request is approved/denied.** — _added 2026-05-31_
  Workers get no feedback when a manager acts on their request — they only find out by
  re-checking the list. Applies to **time-change requests** (shift + blep, the
  `ShiftChangeRequest`/`BlepChangeRequest` approve/deny actions) AND **expense
  reimbursements** (the expense approve/reject flow). Want some notification channel
  (in-app banner/badge, email, or a "what changed since you last looked" surface) so the
  requester learns the outcome without polling. Ties into the broader cross-client
  live-refresh idea ([[project_general_repolling]]).
  _Done when:_ a requester is notified (by whatever agreed channel) of approve/deny
  outcomes for both time-change requests and expense reimbursements.

- **Stale-view error handling + live refresh after a concurrent change.** — _added 2026-06-03_
  Two users with the same job open: one creates the estimate, the other's Create-Estimate
  button is still present and clickable. The backend correctly rejects the second create with
  a note, but the stale view doesn't refresh — the dead button stays. General pattern: a page
  showing another client's mutable state should both (a) surface the rejection cleanly and
  (b) re-fetch so the now-invalid affordance disappears. A small live-refresh system already
  exists for bleps/shifts; the natural move is to generalize it into one shared cross-client
  refresh mechanism (see the "general repolling" project note) rather than bolt on per-page
  polling. Not for this round. _Done when:_ a view that loses an action to a concurrent change
  refreshes to hide the stale affordance, and the rejection is shown without a raw error.

- **Phantom blep in the UI after a sub-minimum auto-clock-in start.** — _added 2026-06-28_
  _(Low priority — rarely if ever happens in practice.)_ Scenario: a user who is **not**
  clocked in starts a blep (which auto-clocks them in **and** creates the open blep),
  then clocks out **before** `blep_minimum_minutes` has elapsed. The backend is correct
  — the clock-out close path (`BlepService._resolve_open_blep` → `_cancel_blep`, the
  under-minimum full-undo in `apps/jobs/services.py`) **deletes** the open blep, so no
  row is created. But the SPA still shows the blep as created: the UI optimistically
  reflects the blep from the start call and never reconciles it against the server's
  silent discard on clock-out. _Fix direction:_ have the clock-out / close response
  report which open bleps were discarded as sub-minimum (or have the UI refetch
  open/recent bleps after clock-out) so the front end drops the phantom. **Likely folds
  into the planned push-notification / live-refresh work** — a shared mechanism so pages
  affected by work elsewhere can refresh themselves (still future); this phantom blep is
  one instance of UI state drifting from the server, so fix it as part of that effort
  rather than as a one-off. _Done when:_ clocking out under the minimum after an
  auto-clock-in start leaves no blep visible in the UI, matching the (already-correct)
  DB state.

## Email

Outbound sending, inbound correlation, the reply/forward composer, threading, and the
email-association pickers. Grouped here because they share the EmailRecord / TempEmail /
IMAP-SMTP machinery and tend to be worked together.

- **Email can be linked to a Job unrelated to its already-linked PO.** — _added 2026-06-21_
  When an email is associated with a PO and also with a Job, nothing checks that the Job
  matches any job referenced by the PO's line items — I was able to link an email to a Job
  that appears on no line item of that email's existing linked PO. The email-association
  actions (`linkToJob` / `linkToPo`, used by the email-association pages) validate each
  link independently, with no cross-consistency guard. Open questions before fixing: a PO's
  lines can legitimately span **multiple** jobs (per-line job via the linked material), so a
  strict "must match" rule may be wrong — maybe it's a soft warning ("this job isn't on the
  linked PO — link anyway?") rather than a block, and we need to decide what "related" means
  when a PO touches several jobs. _Done when:_ we've decided whether/how to constrain or warn
  on email↔job vs email↔PO consistency, and either added the guard or recorded why
  independent links are intentional.

- **Outbound drafts: save composed-but-not-sent state.** — _added 2026-05-30_
  Both the document-send pages (Estimate / PO / Invoice) and the inline reply composer
  intentionally have no draft state. SMTP failure with a page reload loses whatever the
  user typed. Acceptable until real complaints surface — at which point the natural shape
  is a `direction='outbound', sent_at=null, last_send_error=''` EmailRecord (the "in
  flight" state currently never persists) plus a SPA list of "Drafts" on the inbox page.
  Reply drafts probably want the most attention since freeform replies can be long.
  _Done when:_ user can leave a send page mid-compose, come back later, and the form
  pre-fills with what was there.

- **Send outbound documents as a reply to the customer's most recent inbound thread.** — _added 2026-05-30_
  When sending an Estimate / PO / Invoice, look up the latest `direction='inbound'`
  EmailRecord linked to the document's Job (or PO / Bill), and set the outbound's
  `In-Reply-To` + `References` headers so the customer sees the doc in the same Gmail
  thread as their inquiry. Today we always send a fresh standalone email — works fine
  but means customers see two separate threads. Probably a per-document Configuration
  toggle ("thread document emails into recent customer threads by default") when this
  lands. _Done when:_ outbound document emails optionally thread into the parent
  conversation and customer mail clients see proper threading.

- **Sent-folder upload via IMAP APPEND.** — _added 2026-05-30_
  Outbound emails sent by Minibini don't appear in the user's Gmail web "Sent" folder
  — they go out through SMTP and we keep our own EmailRecord, but the user's mail
  client doesn't know about them. Append each successful outbound to the configured
  Sent folder via IMAP so the user sees a consistent picture across our app and Gmail.
  Off the critical path; nice-to-have. _Done when:_ sent emails from Minibini appear
  in the user's Gmail Sent folder alongside emails they sent through Gmail directly.

- **Forward action in the reply composer.** — _added 2026-05-30_
  Standard mail-client Forward — different prefill from Reply (no recipient, `Fwd:`
  subject, body becomes the quoted original, original attachments included). Not in
  the inline composer today. _Done when:_ the action panel has a Forward button
  alongside Reply / Reply All and the composer handles the Forward prefill shape.

- **Subject-line parsing fallback for forwarded-rather-than-replied correlation.** — _added 2026-05-30_
  Reply correlation uses In-Reply-To / References, which most replies preserve.
  Forwards typically drop the threading headers, so a forwarded reply lands
  unassociated. Could grep the subject for our outbound document numbers
  (`EST-2026-0001`, `PO-…`, `INV-…`) as a fallback. Only worth doing if forwards
  turn out to be a noticeable miss rate. _Done when:_ a measurable rate of
  forwarded-replies-to-documents auto-associate to the right object.

- **Multiple "our own" addresses for Reply-All filtering.** — _added 2026-05-30_
  The Reply-All CC computation strips only the single `EMAIL_HOST_USER` address from
  the list of original recipients. If the shop ever polls multiple accounts or
  accepts mail at aliases, the user could see their own alias end up in CC. _Done
  when:_ Reply-All strips any of the configured "our own" addresses (probably a
  small list pulled from a new Configuration key).

- **Thread view in the SPA.** — _added 2026-05-30_
  Show all emails in a thread together (with their shared and individual
  associations) instead of inbox rows that hide the structure. The
  thread-association propagation feature ensures the data is now correctly
  per-thread, so a thread view would just render what's already coherent. Real UX
  improvement; out of scope when the propagation feature shipped. _Done when:_ the
  email inbox has a thread-grouped view; clicking a thread shows the conversation
  with the shared FK associations at the top and per-email details below.

- **Bulk operations across a thread.** — _added 2026-05-30_
  "Mark whole thread as read," "delete whole thread," "disassociate the whole
  thread from Job X." Different from per-email actions (already present) — these
  would operate over the thread membership set computed by
  `collect_thread_member_ids`. Pair with the thread-view follow-up since the UI
  surface for invoking these is the natural place. _Done when:_ the SPA has at
  least one thread-level bulk action wired up.

- **Email attachments aren't downloadable.** — _added 2026-05-28_
  `EmailContent.svelte` renders attachments as
  `<strong>{filename}</strong> ({content_type}, {size} bytes)` — no
  download link. The IMAP service used to ship the raw `payload` bytes inside the JSON
  response, which 500'd for any non-UTF-8 attachment (commit `<this-one>` strips
  `payload` from the service contract); the SPA never used the bytes anyway. _Done
  when:_ a streaming endpoint exists (e.g. `GET /api/emails/{id}/attachments/{index}/`)
  that re-fetches by UID, returns the bytes with correct `Content-Type` and
  `Content-Disposition: attachment; filename=…`, and the email detail page wraps the
  filename in an `<a href>` to it. Decide at that time whether to cache attachment
  bytes on `TempEmail` (avoids IMAP-per-click) or keep the streaming-from-IMAP shape.

## Platform & conventions

Cross-cutting UI/API conventions and shared components.

- **Notes should come out of History as a first-class sub-object.** — _added 2026-07-08 (RM, during the job-workspace design)_
  Notes today are just history entries (`entry_type='note'`, write-only via
  `POST /{jobs,contacts,businesses}/{id}/notes/`, immutable, rendered inside
  history feeds). But notes bridge two distinct uses: **live time-gapped
  communication between workers during a job** and **after-the-fact review**
  — bundling them inside History buries the live-communication half where
  nobody looks until something goes wrong. Promote Notes to a first-class
  sub-object with its own surface (likely its own panel or header-band slot
  in the job workspace restructure; decide the model/API shape then).
  _Done when:_ notes have their own UI surface (and whatever model/API
  separation that requires), with the history feed still recording them (or
  a recorded decision otherwise).

- **JobCard's `.doc-pill-*` should join the global `.status-badge` family.** — _added 2026-07-08 (CSS review pass); narrowed 2026-07-09_
  Originally paired with `JobDetail.svelte`'s `.pill-*` palette, both
  private re-implementations of the consolidated global `.status-{status}`
  palette. **JobDetail's half is done**: the 2026-07-09 overview redesign
  deleted the `.pill-*` palette along with the accordion pillars —
  `SummaryBlock.svelte` renders document-status pills via the shared
  `.status-badge status-{tone}` classes directly. `components/board/JobCard.svelte`
  still carries its own `.doc-pill-*` set (`DOC_PILL_STYLES`,
  draft/open/accepted/rejected/expired), untouched. _Done when:_
  document-status colors on board cards come from the global classes too.
- **In-content tab bars (history tablist) have no shared idiom.** — _added 2026-07-08 (CSS review pass); narrowed 2026-07-09_
  Originally three variants: JobDetail's `.est-tabs`/`.inv-tabs`/`.po-tabs`
  plus `JobHistorySection.svelte`'s tablist. **JobDetail's three are gone**
  — the 2026-07-09 overview redesign deleted them with the accordion
  pillars, and the Estimates/Invoices sections' own in-content document
  switcher is now the shared `DocSubnav.svelte` (one pill per version/
  invoice, status badge inline) rather than a bespoke tab bar.
  `JobHistorySection.svelte`'s `.tabs`/`role="tablist"` remains the one
  outlier with its own underline weight, not yet reconciled with
  `DocSubnav` or `.page-tabs`. _Done when:_ `JobHistorySection`'s tablist
  adopts a shared idiom (`DocSubnav`-style or `.page-tabs`) or a
  deliberate exception is recorded.
- **No shared form-layout vocabulary.** — _added 2026-07-08 (CSS review pass); scoped 2026-07-08_
  Zero `.form-row`/`fieldset`/label conventions exist; every form page and
  modal lays out label+input rows ad hoc (the modal *shell* is shared via
  `Modal.svelte`, the inner form styling is not). Worth defining a small
  form kit in app.css before many more page passes touch forms.
  **Scope (decided with RM):** the kit is for *record forms* — the
  create/edit pages (contacts, businesses, jobs, expenses, users, settings)
  and modal interiors — and it is **opt-in** (a class on the form, like
  `.data-table`/`.page-body`), never default styling on bare
  `<form>`/`<label>`. The app's inline-edit surfaces must NOT adopt it:
  wizard line-item cards (`WizardLineItemCard`), the CO deliverables
  drafting grid (`ChangeOrderDetailPage`), the shipment qty matrix
  (`JobShipmentsPage`), and the small single-purpose widgets (hold-reason,
  add-qty chip, note textareas, TagEditor, status selects, login). Those
  three grid/card surfaces are a *separate* inline-edit vocabulary to
  design during their own page passes — currently three unrelated
  implementations. Mark each with a one-line "inline-edit surface,
  deliberately not the form kit" comment when the kit lands.
  _Done when:_ app.css has an opt-in form-row vocabulary, new/touched
  record forms use it, and the inline-edit surfaces carry the
  do-not-convert comment.
- **Grey literals instead of text-color tokens.** — _added 2026-07-08 (CSS review pass)_
  Secondary text is written as raw hexes across ~40 files (`#999` ×18,
  `#888` ×16, `#666` ×15, `#6b7280` ×11, `#9ca3af` ×11 — five different
  "muted"s). Border tokens now exist (`--border-control`, `--border-subtle`);
  text-grey tokens should follow and be adopted opportunistically as pages
  get their passes. _Done when:_ tokens exist and the design docs name them
  as the way to write muted text.
- **Bespoke table headers drift (teal vs yellow vs bare).** — _added 2026-07-08 (CSS review pass)_
  `.data-table`'s teal band is the house style, but `.materials-table`
  (task page) uses yellow, ChangeOrder's `.diff-table` and JobDetail's
  inline tables use their own `th` treatments. Decide per page-pass whether
  each opts into `.data-table` or records why not.
  _Done when:_ each bespoke table either adopts the house style or carries
  a comment naming the reason.

- **Four schedule tests are midnight-flaky.** — _added 2026-07-08 (found running the full suite just after midnight)_
  `tests.test_api_schedule`: `test_lane_bar_carries_job_number_and_name`,
  `test_work_complete_task_present_in_worker_lane`,
  `test_blocked_task_with_history_shows_actual_not_forecast`,
  `test_held_job_history_renders_but_never_forecasts`. Each seeds bleps at
  `now − 1..2h` and asserts the worker lane renders them — run shortly after
  midnight, that history lands on *yesterday* and falls outside the schedule
  window, so the lane is empty/absent (3 FAIL + 1 StopIteration ERROR).
  Reproduced on a clean tree (unrelated to any pending change); green again
  later in the day. Fix shape: pass a fixed `now` (mid-afternoon) into
  `ScheduleService.get_schedule` / seed times relative to that fixed point
  instead of wall-clock `timezone.now()`.
  _Done when:_ the schedule suite passes at any time of day (spot-check by
  passing a just-past-midnight `now`).

- **Convert the remaining local-state tab pages to per-tab routes.** — _added 2026-07-05 (RM, during the Catalog-area design)_
  The Catalog area set the pattern: real routes per tab (bookmarks, refresh, and
  back-button land on the right tab; the tab strip is `<a use:link>`). Settings
  (`SettingsPage.svelte`, six tabs) and the job history section
  (`JobHistorySection.svelte`, formerly `JobHistoryPage.svelte`) still use
  local `$state` tabs under a single URL.
  _Done when:_ those pages' tabs are routes (or a deliberate exception is
  recorded for them).

- **Modal stacking on the schedule quick card — Escape closes both layers.** — _added 2026-07-04 (found during the Modal-shell sweep)_
  The one real modal-on-modal spot: `TaskQuickCard` (schedule bar click → popup
  card at `--z-popover`, its own window-level Escape → onClose) hosts
  `TaskActions`, which can open `ActualQtyModal` / `BlepEditModal→TimeEditModal`,
  and the card itself mounts `AssignModal` + `StartWorkConflictModal` — all at
  `--z-modal`, stacked above the card. Two issues to check in depth: (a) one
  **Escape** fires both the modal's `modalKeys` cancel AND the card's own
  listener — the card vanishes out from under the modal; (b) with top-anchored
  modals the stack now visibly overlaps near the top. Note `--z-modal-nested`
  (900) already exists in the scale but has **zero users** — it anticipated
  exactly this. Fix shape to discuss: the card suspends its Escape/backdrop
  handlers while a child modal is open (or the shell exposes an "is any modal
  open" signal), and stacked modals take the nested tier.
  _Done when:_ Escape on a stacked modal closes only the modal, and the layers
  read clearly.

- **Audit error-message surfacing across the SPA for consistency.** — _added 2026-05-29_
  Inconsistencies noticed in passing: some pages surface API errors via the global
  `lib/api.js` overlay, some via inline `<p><strong>Error:</strong> {message}</p>` rows
  under the form, some via field-level errors derived from DRF's `e.data`, and the
  Invoice send dialog uses `e.data?.error || e.message`. The set of envelope shapes the
  backend returns is also a bit mixed — some endpoints return `{'detail': '…'}`, some
  `{'<field>': ['…']}`, some `{'error': '…'}`. The user-visible result is that the same
  kind of failure can look quite different depending on where it happens. _Done when:_ a
  quick pass has catalogued the variants, agreed on a small set of envelope shapes the
  backend uses consistently, and the SPA's error display has been normalized to match
  (probably: lean on `lib/api.js` overlays for unexpected errors, inline rows for
  field-validation responses).

- **Decide a consistent primary-key naming convention for line items (and documents).** — _added 2026-05-26_
  The codebase uses explicit PK names (`line_item_id`, `estimate_id`, `change_order_id`)
  instead of Django's default `id`. This bit us in the CO UI — the frontend assumed
  `.id`, producing the `/change-orders/undefined` redirect + empty links (fixed in
  `a1c4ff2`). Note: all line-item types **already share `line_item_id`** (via
  `BaseLineItem`), so DRY-ing the repeated line-item code (a shared base serializer,
  `LineItemMixin`, the shared `LineItemTable`/`WizardLineItemCard`) is *already* possible
  on that common name — switching to `id` wouldn't unlock new consolidation; it would
  match Django/DRF defaults and stop the recurring "I assumed `.id`" bug.
  _Options:_ (a) keep the explicit names and document the convention loudly;
  (b) expose a read-only `id` alias in the line-item serializers — cheap, no DB
  migration, lets shared frontend code rely on `.id`; (c) full rename to `id` — large,
  risky, and leaves parent docs inconsistent unless they're renamed too.
  _Done when:_ we've picked one and either applied it or recorded the decision.

- **Remove "Edit" from the job header for closed jobs.** — _added 2026-07-08_
  The JobHeader's Edit button (opens `JobEditModal.svelte`) shows regardless of
  status; a closed job (completed/rejected/cancelled) shouldn't offer it.
  _Done when:_ the Edit button is hidden (or disabled with a reason) for terminal-status
  jobs in `JobHeader.svelte`, with a component test.

- **`TaskTree`'s `showStatus={false}` branch is dead code — drop it.** — _added 2026-07-09_
  `TaskTree.svelte`'s `showStatus` prop defaults to `true`, and both render
  sites resolve to `true` (`TaskDetailPage` passes it explicitly;
  `TasksPanel` omits it and takes the default). So the `{#if !showStatus}`
  branches never execute — including the fallback at `TaskTree.svelte:339`,
  `:409`, `:449` that appends `matStatusChip` into the *description* cell
  when there's no Status column. RM: likely leftover from when the worksheet
  object was torn out. Remove the prop and all `!showStatus` branches (or,
  if a status-less compact rendering is ever wanted, add a caller + a test
  that pins it — but RM doesn't expect to use it).
  _Done when:_ the unused `showStatus` prop and its `{#if !showStatus}`
  branches are removed from `TaskTree.svelte`, or a caller + test exercise
  the compact mode.

- **Per-row `total` on the unfiltered estimate/CO/invoice list serializers is an N+1.** — _added 2026-07-09_
  `EstimateSerializer.get_total`, `ChangeOrderSerializer.get_total`, and
  `InvoiceSerializer.get_total` (all added/extended 2026-07-09 for the
  job-overview redesign — `docs/designs/estimates-and-prices.md` §5.5,
  §14.2; `docs/designs/invoicing-and-expenses.md`) are per-object
  `SerializerMethodField`s: each re-queries its line items (or, for
  `ChangeOrderSerializer`, calls `compose_change_order_diff`) with no
  queryset-level annotation. Fine for the job-overview fetch (page-sized:
  the current estimate + a handful of COs/invoices for one job), but
  a genuinely unfiltered list (e.g. `GET /api/estimates/`,
  `GET /api/invoices/` without `?job=` or `?summary=true`) pays one extra
  query per row. `InvoiceSummarySerializer` (the `?summary=true` path)
  already avoids this via `InvoiceViewSet.get_queryset` annotations
  (`total_anno`) — the same `prefetch_related`/annotation treatment is
  the candidate fix for the other list paths, if/when one of them is
  used at real scale unfiltered. _Done when:_ the unfiltered list
  endpoints' `total` computation is annotated/prefetched (or a decision
  is recorded that current call sites never hit this at scale).

- **`TagViewSet` implicit CRUD — the last `serializer.save()` bypass, left for its original author.** — _added 2026-05-27; narrowed 2026-07-04_
  Sole remainder of the three-layer bypass sweep (A holes, B metadata
  tails, and C config CRUD were all extracted to services 2026-07-04;
  auth/users serializers are an accepted exemption —
  `apps/api/users/services.py` guards the dangerous operations).
  `TagViewSet` (`contacts/views.py`) still has full implicit DRF CRUD:
  a global rename/delete surface with no confirm flow, which the SPA
  only reads. The tag *actions* on contacts/businesses already route
  through `TagService.attach`/`detach` — the viewset itself is the gap.
  Hands-off by request: the Tags feature belongs to its original author.
  _Done when:_ the author routes TagViewSet writes through `TagService`
  (or records an exemption).
