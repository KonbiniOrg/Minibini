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

- **Estimate-less draft jobs: allow direct →Approved, gate →Submitted on an estimate.** — _added 2026-07-19 (RM notes review)_
  Follow-up to the direct-approval gate (2026-07-19): `submitted` means
  "awaiting customer response", which presupposes an estimate — so a draft job
  with **no** estimate should be blocked from `submitted`, and instead allowed
  a direct `draft → approved` edge (today that edge doesn't exist; an
  estimate-less job must fake-traverse submitted to be hand-approved).
  Touches `Job.clean()`'s `VALID_TRANSITIONS`, the `update_job` guard, and
  `JobHeader`'s pill options (both keyed on `has_estimates`). Wrinkle to
  decide during implementation: `_advance_to_approved` (duplicate-as-approved)
  currently walks draft→submitted→approved — with the new edge it should
  probably go direct.
  _Done when:_ an estimate-less draft job can be hand-approved in one step,
  cannot be submitted, and the duplicate walk is coherent with the new graph.

- **Gate manual Job →Submitted behind the estimate transition; expose direct mark-Open on the Estimate.** — _added 2026-07-19 (RM)_
  Same shape as the direct-approval gate (fixed 2026-07-19): just as the Job
  used to be hand-movable to `approved` without an estimate acceptance driving
  it, a draft Job can today be hand-moved to `submitted` via the status pill /
  `update_job` without any estimate going `open`. `submitted` should only be
  reachable through the estimate's `draft → open` transition (the signal in
  `apps/estimates/signals.py` already drives job → submitted with
  `system_transition=True`); block the manual edge.
  **Prerequisite escape hatch:** the SPA's only `draft → open` path today is
  Send Email (`POST /api/estimates/{id}/send` flips status on success) — if
  in-app emailing is broken, blocking manual job→submitted would strand the
  job in draft. `EstimateService.mark_open` already exists and is registered
  as the `mark-open` API action, but no frontend calls it; expose a direct
  "mark as Open" affordance in the UI (same guards apply: deliverables
  present, hand-lines have ACs), which then moves the job to `submitted` via
  the existing signal.
  _Done when:_ a job cannot be hand-moved to `submitted` (only the estimate's
  draft→open transition gets it there), and an estimate can be marked Open
  from the UI without sending email.

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

## Change orders

The CO surface and its estimate-parallel code.

- **Converter fabricates estimate claims → false "descoped by CO-N" badges.** — _added 2026-07-20, mechanism updated 2026-08-09_
  Root-caused on dev job 61: `build_synthetic_estimate_sources`
  (`nealsdata/converter/build.py` ~L1715) round-robins EVERY unclaimed task
  across a job's estimate lines so converted jobs project atoms in the Client
  View — fabricating many-to-one `EstimateLineItemSource` rows. At the time
  this was found, the struck-badge was a *derived* query
  (`ChangeOrderService.struck_atom_keys`, since deleted); CO amend-in-place
  (2026-08-09) replaced it with a stamp written once at CO acceptance
  (`ChangeOrderAcceptanceService`'s REMOVE loop sets `Task`/
  `Material.descoped_by`, read by the invoice pool as
  `descoped_by_co_number` for the "descoped by CO-N" chip — see
  `estimates-and-prices.md` §14.11) — but the underlying bug is identical:
  acceptance still resolves the remove/replace target's *current* atom
  through the same `EstimateLineItemSource`/`ChangeOrderLineItemSource`
  chain the converter corrupts, so a fabricated multi-task claim still
  stamps (or fails to stamp) the wrong task. The badge logic is
  correct; fix the converter (claim at most one plausible task per line, or drop
  the pass and accept sourceless converted lines). MUST run
  `tests.test_neals_builders`; `nealsmall.json` is RM-managed — never regenerate.
  Separately, RM hand-repairs the existing dev rows (job 61: source_ids 327,
  331, 335, 339 at minimum — Claude drafts the SQL, RM runs it).
  _Done when:_ the converter emits no fabricated multi-task claims, builders
  suite green, and job 61's synthetic rows are repaired.

- **`ChangeOrderLineItem.clean()` doesn't validate the target belongs to the CO's estimate.** — _added 2026-07-20, corrected 2026-08-09_
  Found while clearing suspects on the badge investigation: nothing enforces
  `target_line_item.estimate_id == change_order.estimate_id`, so a CO line
  could target another estimate's line. Latent (no observed corruption); add
  the validation. (Superseded intent, 2026-08-09: this note originally said
  "REPLACE targets stay in the struck-atom set" — CO amend-in-place settled
  the opposite: a REPLACE **moves** the target's claim onto the CO line and
  never stamps `descoped_by` at all; only a REMOVE target gets stamped. See
  `estimates-and-prices.md` §14.11.)
  _Done when:_ the clean() check exists with a test.

- **Expose *estimate* claims somewhere after acceptance.** — _added 2026-07-20 (RM)_
  `EstimateLineItemSource` (what the agreement SOLD per line) is invisible in
  the daily UI once the estimate is accepted and the estimate wizard is gone —
  which is why fabricated claims sat unnoticed until the struck badge read them.
  The invoice wizard shows only the BILLING ledger (`InvoiceLineItemSource`).
  Consider a surface for agreement claims post-acceptance — e.g. on the estimate
  panel's line items (expand a line to see its atoms), the task detail page
  ("sold on line N"), or the job overview. _Done when:_ RM picks a surface and
  agreement claims are inspectable after acceptance (or the idea is dropped).

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

- **Consolidate the estimate↔change-order parallel code.** — _added 2026-06-08,
  consolidated 2026-07-19_
  The sibling duplicates were consolidated as a pure refactor:
  `EstimateEmailService` / `ChangeOrderEmailService` now subclass a shared
  `DocumentEmailService` base (`apps/estimates/services.py`); the portal view
  twins share `apps/api/portal/common.py` (`money`, `not_available`,
  `actor_for`, `visible_document`, the `decide` skeleton — each side keeps its
  own `_is_actionable` rule and payload builder); the two portal pages render
  through the shared `components/PortalDocument.svelte` shell; and both PDF
  generators use `_pdf_party_context(job)` (`apps/estimates/pdf.py`).
  Deliberately still duplicated: `estimate_pdf.html` vs `change_order_pdf.html`
  (shared CSS + header-info block) — PDF templates are self-contained by
  convention (no extends/include, per CLAUDE.md), so the Python-side helper is
  the consolidation; touch the two templates in tandem. (A diff-logic note,
  updated 2026-08-09: the frontend merged-rows logic
  [`buildMergedRows`/`lineDiffTotals` in `frontend/src/lib/changeOrderDiff.js`]
  this used to be kept in lockstep with was **retired** when `COEditView`
  moved the shop edit page onto the server-composed
  `compose_amended_agreement` — see the unify item below; `changeOrderDiff.js`
  now only holds `buildDeliverableRows`.)
  _Remaining done when:_ either the PDF-template convention changes (allowing a
  shared header include) or the template pair drifts enough to force a rethink.

- **Unify `compose_change_order_diff` / the CO PDF / the customer portal onto
  `compose_amended_agreement`.** — _added 2026-08-09 (CO amend-in-place Task
  7/12)_ The shop edit page (`COEditView`) now reads the server-composed
  `compose_amended_agreement(co)` (§14.6), but `compose_change_order_diff`
  (`apps/estimates/agreement.py`) — the function backing the CO PDF
  (`generate_change_order_pdf`) and the customer portal
  (`build_change_order_payload`) — is a separate, older composer that still
  baselines off the flat accepted estimate (`co.estimate`) rather than
  `compose_amended_agreement`'s baseline-through-prior-accepted-COs walk.
  Single-CO is the validated path for both composers today (see "Validate the
  multi-change-order display" above); with ≥2 accepted COs the diff/PDF/portal
  baseline can understate the true current agreement even though
  crystallization itself resolves the replace chain correctly (§14.11). Fold
  the PDF and portal onto `compose_amended_agreement`'s rows (or a shared
  baseline helper) so all three CO-facing surfaces — shop edit, PDF, portal —
  read one composer and can't drift.
  _Done when:_ `compose_change_order_diff` is retired or reimplemented on top
  of `compose_amended_agreement`, and the PDF/portal render correctly for a
  ≥2-accepted-CO chain.

- **No DB-level guard against a cross-lens claim race.** — _added 2026-08-09
  (CO amend-in-place Task 7, reviewer-accepted scope)_ The estimate wizard's
  pool correctly *displays* a CO-claimed atom as `claimed_by_other` and vice
  versa (`EstimateWizardService`/`ChangeOrderWizardService.get_source_pool`
  union both claim lenses), but the two claim tables
  (`EstimateLineItemSource`, `ChangeOrderLineItemSource`) each enforce
  whole-atom uniqueness only within themselves — there is no DB constraint
  spanning both. A determined or racing pair of requests (one hitting the
  estimate wizard, one the CO wizard, near-simultaneously) could still create
  an estimate claim and a CO claim on the same atom; only the pool-level
  display stops the ordinary UI from offering it. Accepted as scope for the
  amend-in-place phase (no observed occurrence; the estimate is normally
  terminal — `accepted`/superseded — by the time a CO exists, which narrows
  the window in practice).
  _Done when:_ a cross-table DB constraint (or an application-level lock
  spanning both source models) closes the race, or the risk is judged not
  worth one.

- **`_assert_target_not_billed` isn't chain-aware.** — _added 2026-08-09 (CO
  amend-in-place final review)_ `ChangeOrderService._assert_target_not_billed`
  (the remove/replace guard) only checks `InvoiceLineItem.agreement_estimate_line`
  — so a target line that a *prior accepted CO* already replaced (whose
  invoice reference lives on `agreement_co_line`, not `agreement_estimate_line`)
  isn't caught, and a second CO could remove/replace an already-billed line
  out from under the invoice. `apps/estimates/agreement.py`'s `_billed_on`
  (the CO edit page's display helper, feeding `compose_amended_agreement`)
  already checks both branches correctly — only the write-side guard is
  behind. Only reachable once a multi-CO chain exists, so single-CO testing
  never exercises it.
  _Done when:_ `_assert_target_not_billed` walks the same
  estimate-line-or-prior-replace-CO-line chain `_billed_on` does.

- **No guard against two lines in one CO targeting the same estimate
  line.** — _added 2026-08-09 (CO amend-in-place final review)_ Nothing
  stops `add_line_item`/`update_line_item` from creating two remove/replace
  lines on the same draft CO with the same `target_line_item` — a raw-API-only
  gap (the wizard/UI never offers it). `ChangeOrderAcceptanceService.on_accept`
  applies both against the target's current atom(s) without checking for the
  collision, which is undefined behavior rather than a clean rejection. Related:
  `target_line_item` is also never validated to belong to `co.estimate` — see
  the existing "`ChangeOrderLineItem.clean()` doesn't validate the target
  belongs to the CO's estimate" entry above, still open; a one-line ownership
  check for that entry and the duplicate-target check here are natural
  companions to add in the same pass.
  _Done when:_ `ChangeOrderLineItem.clean()` (or the service) rejects a
  second draft-CO line targeting an estimate line already targeted by
  another remove/replace line on the same CO, with a test.

- **Per-row `_billed_on` query in `compose_amended_agreement` is an
  N+1.** — _added 2026-08-09 (CO amend-in-place final review)_ The
  `'agreement'`-row loop in `compose_amended_agreement` (`apps/estimates/agreement.py`)
  calls `_billed_on(line)` once per surviving baseline row, each a fresh
  `InvoiceLineItem` query — roughly one query per agreement line on the CO
  edit page. Fine at today's line counts; candidate for a single
  prefetch/batched lookup (keyed by estimate-line-id/co-line-id) if a job's
  agreement grows large enough to notice.
  _Done when:_ `compose_amended_agreement` resolves `billed_on` for every row
  in O(1) queries instead of one per row (or the cost is judged not worth
  batching at current scale).


## Invoicing, expenses & payments

Billing mechanics and money-record lifecycle.

- **Invoice revisions — back the "Revise (coming soon)" placeholder.** — _added 2026-06-04_
  `InvoiceDetailPage.svelte` shows a **disabled** "Revise (coming soon)" button on sent
  invoices (`canSeeRevise`), shipped as a placeholder — there is no invoice-revision backend
  (no `InvoiceService.revise`, no supersede/version chain like estimates have). Decide
  whether invoices need a revise flow at all (vs. cancel + new invoice) and, if so, build the
  backend + wire the button.
  **Groundwork already laid** (_2026-07-28_): `superseded` is in
  `DEAD_INVOICE_STATUSES` (`apps/invoicing/claims.py`), so entering it already
  releases the invoice's atom claims and `InvoiceClaimService._live_sources`
  already excludes it — backend and the SPA's `INVOICE_DEAD_STATUSES` agree.
  **The one thing a revise flow must get right:** move or re-point the
  `InvoiceLineItemSource` rows onto the new revision *before* flipping the
  parent to `superseded`, exactly as `EstimateService.revise_estimate` does.
  The release fires on that transition and would otherwise delete rows the
  revision still wanted.
  _Done when:_ either the placeholder is backed by a working
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
  auto-applied adjustments — 2026-06-26 plan, since deleted); decide
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

- **`AccountingCategory.adjustment_target_categories` M2M N+1 on invoice/estimate detail.** — _added 2026-07-25_
  Pre-existing, rediscovered twice during the deposits work: once via the
  `is_referenced()` freeze-check gap (fixed — see
  `apps/core/models.py` `AccountingCategory.is_referenced`, which now
  queries `EstimateLineItem`/`InvoiceLineItem.adjustment_target_categories`
  explicitly since hidden `related_name='+'` M2Ms don't show up in
  `_meta.related_objects`), and again while reviewing the invoice detail
  N+1 fix (`InvoiceViewSet.get_queryset` prefetches
  `invoicelineitem_set__sources` and `__accounting_category` for
  `is_deposit`, but not `adjustment_target_categories`). `InvoiceLineItemSerializer`
  / `EstimateLineItemSerializer` both expose `adjustment_target_categories`
  as a plain M2M field, so any invoice/estimate detail response with
  adjustment lines pays one extra query per adjustment line to serialize
  the field. Candidate for a `Prefetch('invoicelineitem_set__adjustment_target_categories')`
  (and the estimate-side equivalent) alongside the existing prefetch.
  _Done when:_ adjustment-line-heavy documents render without an
  `adjustment_target_categories` N+1, verified with `assertNumQueries` or
  equivalent.

## Purchasing & inventory

(The procurement-machinery items moved into the freeform-materials plan
2026-07-04; the plan shipped 2026-07-05 and the still-open ones returned below.)

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

- **Expense-created materials are left provisional despite having a cost.** — _added 2026-07-28 (found tracing needs-pricing for the overview Coverage work)_
  `ExpenseService.attach` handles the two branches of the same real-world event
  inconsistently. With `material_id` (attach to an existing material) it
  establishes a provisional target — minting the lot at the expense's unit cost
  with `cost_source=EXPENSE` — and then calls `receive_ad_hoc_purchase`; the
  docstring says it outright: *"attach == receipt."* The `new_material` branch
  (`apps/expenses/services.py` ~L85), for a freeform material with no catalog
  item, passes the same `cost_source=EXPENSE` and then does **neither** — no
  `establish`, no receive. `create_on_job`'s mint gate deliberately excludes
  document-sourced costs, so the material is born provisional with a real
  recorded cost and zero stock.
  Consequences: it reads **"Needs pricing"** on every material row though its
  cost is known; the job overview's Coverage stat counts it as *needs ordering*
  though it is physically in the shop; `InventoryService.consume` refuses it;
  and **task completion blocks** on it (`apps/jobs/services.py` ~L1404,
  "not yet priced/received") — RM: that gate should not fire for material
  that's actually in hand. Fix the state, not the gate: once expense-created
  materials establish, provisional means "no cost, not ordered, not received",
  which is worth blocking on.
  Parts already exist — `MaterialService.establish` mints the lot,
  `InventoryService.receive_ad_hoc_purchase` books the stock, and
  `_default_markup_percent` is there (`establish_reverse_markup` runs it
  sell→cost; this needs cost→sell). Design question to settle in the pass: does
  an expense-created material receive its full quantity, or only what the
  expense paid for?
  _Done when:_ a material created from an expense is established and stocked
  like the attach branch, with a markup-derived sell price, and no longer reads
  "Needs pricing".

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
  top-of-page scroll problem (the create/edit form itself is a modal now). Directions to make it less awkward: drive selection **from the
  rows** (e.g. pick a discard row's "merge into…" action, or select two rows in the table)
  so you act on what you see; use `InventoryItemPicker` (server-side `?search=`) instead of
  raw `<select>`s; show a **confirmation preview** of the resulting merged item (combined QOH,
  moved references, which id survives) before committing; and put it in a modal/in-place
  surface rather than a top-of-page panel.
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
  _Refined 2026-07-19 (RM notes review):_ the Time page should show lists of
  **shifts and bleps**; `can_manage_financials` holders get **view-only**,
  `can_manage_time` holders get **editing plus the visible change-request
  queue**.
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

- **Shift self-delete: UI offers a Delete button the server refuses (decide the rule, then align).** — _added 2026-07-13_
  A worker (`IsAuthenticated` only) is shown Delete on their own fully-today
  shift, but `ShiftService.delete` requires `can_manage_time` — which is the
  DOCUMENTED rule (`users-and-permissions.md` twice; `data-constraints.md`
  §1.2a's self-edit window deliberately says edit/create only). This is a
  documented **asymmetry with bleps**, where own create/edit/**delete** is
  allowed within the 30h window (`jobs-and-tasks.md` §5.2). RM's
  expectation was symmetric self-service. Decide: (a) open shift deletion to
  the own-30h-window rule (service + docs + tests change; the orphaned-bleps
  guard stays for everyone), or (b) keep manager-only and hide the worker's
  Delete button (`TimeEditModal.svelte` shows it ungated). Deliberately not
  fixed on `feature/tasks`.
  **Same shape, second case — the invoiced-task freeze** (_added 2026-07-28_):
  `BlepService.update` and `.delete` both refuse, for *every* actor, when the
  blep's task is on a live invoice (`data-constraints.md` §1.12; `update`
  joined the freeze 2026-07-28). The blep serializer exposes no
  invoiced/frozen flag and the SPA does no gating on it, so `TimeEditModal`
  offers Save and Delete on a billed task's time and the user only learns on
  submit — the same UI-offers-what-the-server-refuses pattern, just driven by
  document state rather than permissions. Fixing the affordance wants a
  serializer flag (e.g. `actuals_frozen`) the modal can disable and explain
  on; worth doing in one pass with the shift-delete decision above, since
  both land in `TimeEditModal`.
  _Done when:_ the shift rule is decided and UI, service, docs, and tests
  agree — and the modal no longer offers edit/delete on a blep whose actuals
  are frozen.

## Platform & conventions

Cross-cutting UI/API conventions and shared components.

- **`#/jobs` (JobListPage) has no nav link.** — _added 2026-07-31_
  The tabular job list is a destination RM uses and wants kept (2026-07-31)
  — `JobFormPage`'s Cancel lands there deliberately — but nothing in the SPA
  navigates to it: the sidebar's "Jobs" goes to `#/jobs/board`, and the only
  other links in are the PM-filtered `#/jobs?pm=N` ones. So it's reachable by
  URL or by cancelling out of the new-job form, and not otherwise.
  _Done when:_ the plain list is reachable from the nav (or from the board).

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
  drafting grid (`CODeliverablesSection`), the shipment qty matrix
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

- **`ContactListPage.loadAll()` has no stale-response guard — suspected cause of a flaky e2e.** — _added 2026-07-28_
  `e2e/specs/contacts/import-skip-report.spec.js` fails intermittently (~2 of 4
  full-suite runs; always passes run alone or with only the contacts specs) at
  the step after the letter-index click: `getByRole('link', {name: 'Zenith
  Imports E2E'})` not found. Leading hypothesis, **not yet confirmed**: two
  `loadAll()` fetches are in flight at once — `ContactsImportPanel`'s
  `onCommitted={loadAll}` fires on Apply, then clicking "Z" sets `letterFilter`
  and the `$effect` fires another — and nothing sequences them. The earlier
  unfiltered response can land last and overwrite `allItems`, leaving the A-page
  rendered while the filter says Z. Under load the suite is slow enough for the
  responses to invert. If that's right it's a real (if narrow) user-facing bug,
  not just test flake: any fast filter change during an in-flight load can show
  the wrong list. Fix shape: a request epoch/token in `loadAll` that discards
  responses older than the latest issued (or an abort on supersede).
  _Done when:_ the race is confirmed or ruled out; if confirmed, `loadAll`
  ignores superseded responses and the spec stops flaking in full-suite runs.
  _2026-07-31:_ failed on two consecutive full-suite runs (once with unrelated
  login/logout work in the tree, once with that work stashed — identical
  failure at the same assertion), and passed run alone in between. So on this
  machine it currently reproduces every full-suite run, not ~2 of 4; the
  ordering that provokes it is stable enough to debug against directly.

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

- **`deposit-creation.spec.js` is order-dependent — it picks the first
  invoice-less job.** — _added 2026-07-30_
  `findInvoicelessJob` (`e2e/specs/deposits/deposit-creation.spec.js` ~L31)
  scans the backdrop for the *first* billable job with zero invoices. The
  suite runs `workers: 1` against one shared `minibini_e2e` with no per-spec
  reset, so any earlier spec that invoices a billable job changes which job
  this one gets — or consumes the last candidate. Solo it always lands on the
  same clean job and passes (verified 8/8 on fresh DBs); it failed once inside
  a full-suite run. Deterministic under ordering, not timing noise, and the
  spec does discard its own draft, so it's downstream of others rather than
  self-poisoning. Same shape as the "filter-change + stale page race" family
  of shared-state fragilities. Fix shape: have it create its own job (as
  `rate-scheme-modal` and `coverage-signal` do for their shapes) instead of
  hunting the seed for an unclaimed one.
  _Done when:_ the spec's job is one it made, so full-suite ordering can't
  reach it.

- **`contacts/import-skip-report.spec.js` is flaky (~50% locally).** — _added 2026-08-08_
  A client render race in `ContactListPage`'s letter filter, unrelated to
  QBO import itself and untouched by the skeleton-phase branch that
  surfaced it (confirmed on the `feature/better-fees` full e2e suite,
  Task 14). Reproduces both inside the full suite and standalone on a
  fresh DB; not yet root-caused.
  _Done when:_ the race is identified and fixed (or the spec is
  rewritten to wait on the right condition instead of a fixed render
  assumption), and the spec passes reliably solo and in the full suite.

- **Two more intermittently-flaky e2e specs, catalogued 2026-08-08 (skeleton-phase final verification).**
  `production-lifecycle/completion.spec.js` §6 (a timing flake around the
  work-complete cascade) and `deposits/deposit-creation.spec.js` (a
  `.deposit-pill` list-timing race; failed once in a full run, passes in
  isolation and passed earlier full runs). Both pre-date and are
  untouched by the `feature/better-fees` skeleton phase; evidence in that
  phase's task reports. Same treatment as the contacts flake above.
  _2026-08-09 (fee-removal Task 10):_ the cascade timing flake reproduced
  once more in a full run. Separately, the file's OTHER §6 test
  ("Completion settle-up") fails deterministically when the spec runs
  SOLO on a fresh DB: its seed-hunt picks the PT-MIS216 job whose task
  carries an out-of-stock material, so the (correct, pre-existing)
  completion stock-gate blocks it — order-dependent candidate selection,
  same family as the deposit-creation entry, not timing. Not caused by
  the fee strip (the stripped seed differs from the old one only in
  `jobs.fee` + fee source rows — verified row-for-row). Fix shape: the
  hunt should also require the candidate task's materials to be
  completable (in stock or absent), or build its own job.
  _Done when:_ each spec waits on its real condition and passes reliably
  solo and in the full suite.

- **Convert the remaining local-state tab pages to per-tab routes.** — _added 2026-07-05 (RM, during the Catalog-area design)_
  The Catalog area set the pattern: real routes per tab (bookmarks, refresh, and
  back-button land on the right tab; the tab strip is `<a use:link>`). Settings
  (`SettingsPage.svelte`, six tabs) and the job history section
  (`JobHistorySection.svelte`, formerly `JobHistoryPage.svelte`) still use
  local `$state` tabs under a single URL.
  **The history section has a caller waiting on it** (_2026-07-28_): the job
  overview's Spend block links to `#/jobs/:id/history` as a *placeholder*,
  because Spend's honest destination is a job-profitability analysis that
  doesn't exist and there's no URL that means "Analysis" while the tabs are
  local state. Three things land together when this entry is worked:
  per-tab routes for the section, a third **Analysis** tab (a "not yet
  implemented" placeholder until the profitability work is specced), and
  retitling the page **History → "History and Analysis"** (page `<h2>` only —
  the rail label stays "History"; the strip has no room). Then repoint Spend's
  href in `spendBlock()` (`lib/jobOverview.js`) at the Analysis tab.
  _Done when:_ those pages' tabs are routes (or a deliberate exception is
  recorded for them), and Spend links to the Analysis tab rather than the
  history index.

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

- **Ctrl/Cmd-click should always open navigation in a new tab.** — _added 2026-07-19 (RM notes review)_
  Sometimes it works, sometimes it doesn't. Root causes found: (a)
  `svelte-spa-router`'s `use:link` click handler calls `event.preventDefault()`
  **unconditionally** — no ctrl/meta/shift check — so every `use:link` anchor
  swallows modified clicks and navigates in-tab, while plain `href="#/…"`
  anchors open a new tab fine; (b) any navigation implemented as a `<button>`
  + `push()` can never be modifier-clicked (see the "links navigate; buttons
  act" convention). Fix shape: a modifier-aware link wrapper (or drop
  `use:link` in favor of plain hash hrefs where no params are needed), plus an
  audit of button-shaped navigations.
  _Done when:_ ctrl/cmd-clicking any navigation affordance opens a new tab.

- **Service/model validation raises one error at a time — accumulate instead.** — _added 2026-07-19 (RM notes review)_
  Observed on the rate-scheme form: submitting with several invalid fields
  surfaces only one message per attempt. DRF serializer errors arrive
  all-fields-at-once, but `ConfigurationService`'s rate-scheme checks and
  `RateScheme.clean()` raise sequentially — first failure wins, so the user
  fixes one field, resubmits, and meets the next error. Sweep the service/model
  checks (rate schemes first; note any other multi-check services while there)
  to collect failures into a single `ValidationError({field: [...]})`.
  Distinct from the error-*surfacing* audit below — this is about the backend
  reporting completely, not where errors render.
  _Done when:_ a rate-scheme submit with N invalid fields reports all N in one
  response (and the pattern is noted for other services).

- **Accounting category: delete-if-unused UI (retire-if-used already exists via Active).** — _added 2026-07-19 (RM notes review)_
  `AccountingCategories.svelte` has an **Active** checkbox, which covers the
  retire-when-used case in substance. There is no delete affordance for a
  category nothing references — an unused/mistyped category lives forever.
  Add delete (two-phase confirm per the app convention), refused server-side
  when referenced; possibly label/present Active as the retire story while
  in there.
  _Done when:_ an unreferenced category can be deleted from Settings, a
  referenced one can only be retired, and the distinction is visible.

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

- **Job History Summary hides an "accidental start cancelled" task revert.** — _added 2026-07-13_
  A task's accidental-start-cancelled revert is recorded only as a standalone action entry (no status diff), so `frontend/src/lib/historyLog.js`'s standalone-action rule excludes it and the Summary shows "started" with no visible revert row. Revisit if this confuses users in practice.

- **Catalog renames don't propagate to mirrored QBO Items.** — _added 2026-07-21_
  A ServiceItem/InventoryItem renamed after its QBO Item was minted keeps the
  old Item Name in QBO (line Descriptions carry the real text, so invoices are
  unaffected; only QBO-side Item reporting shows the stale name).
  _Done when:_ a rename sync (or an explicit "update QBO Item" action) exists,
  or we record a decision that drift is acceptable.

- **Business-level tax exemption is display-only.** — _added 2026-07-21_
  `Business.tax_exemption_number` / `tax_multiplier` are editable in the UI but
  nothing consumes them. Planned as its own QBO changeset: map onto the QBO
  Customer's taxable/exempt settings. Note: QBO is binary taxable/exempt per
  customer — the multiplier's fractional-rate idea won't map cleanly.
  _Done when:_ the business-level exemption changeset ships (spec first).

- **`tests.test_api_schedule` has date-sensitive failures.** — _added 2026-07-22_
  4 tests (`ScheduleWorkCompleteHistoryTest` ×2, `ScheduleForecastScopeTest`,
  `ScheduleWorkDrivenScopeTest`) fail on 2026-07-22 on `main` as well as
  feature branches — worker lanes come back empty, so likely a weekday/window
  assumption in the fixtures. Unrelated to the QBO work; discovered by its
  final full-suite run crossing midnight.
  _Done when:_ the fixtures pin their dates (or derive them from today) and
  the module passes on every weekday.

- **Bill tables are schema-only leftovers — a drop migration is owed.** — _added 2026-07-23_
  The Bill domain was retired (bills live in QBO; see
  `docs/plans/bill-removal-spec.md`), but `Bill`, `BillLineItem`, and
  `BillPayment` models were kept as bare schema declarations so the branch
  carries no destructive migration and the change stays revertible.
  `EmailRecord.bill` and `Business.qbo_vendor_id` columns likewise remain.
  Legacy rows still load (dev DB, e2e/neals fixtures may carry them) and
  passive deletion-protection still references them.
  _Done when:_ either the removal is reverted, or — once RM declares the
  retirement permanent — a migration drops the three tables (+
  `EmailRecord.bill`), the schema-stub models are deleted, and the passive
  references (contacts deletion checks, inventory merge/has_document_line_refs
  clauses) go with them.

  link-email-to-PO (and ideally create-PO-from-email).

- **Email password change should re-authenticate via a modal.** — _added 2026-07-23_
  Settings → Email currently lets any config admin overwrite the stored mail
  password by typing a new one into the form. RM wants a "change email
  password" modal that requires re-entering the user's own app password
  before granting access to the change (same shape as sensitive-action
  confirmation flows elsewhere).
  _Done when:_ the password field on Settings → Email is read-only behind a
  modal that verifies the requesting user's app password before allowing a
  new mail password to be entered and saved.

- **Setup callouts should link to the settings they point at.** — _added 2026-07-23_
  The sidebar's setup arrows name their unlock path in prose ("Settings →
  Email") but aren't clickable. Add an in-callout link navigating to the
  named surface (Settings tab, Contacts, etc.) — the callout already
  survives hovering onto it, so a link is workable; needs hint text/link
  pairs in `frontend/src/lib/setupHints.js`.
  _Done when:_ each callout carries a working "take me there" link.

- **QBO import panels need a usability pass.** — _added 2026-07-23_
  RM's first hands-on run (against the Intuit sample company) found the flow
  "very confusing and unclear" despite the agreed design: barren
  parent-account category candidates read as noise, the collapse-group
  column needs explaining, unit/scheme columns needed fixes, and the
  step-to-step handoff (categories → schemes → catalog) is not
  self-narrating. Also open: cluster-by-top-level-account toggle (pending
  RM's accountant's read on real-world Item-tree usage), and a possible
  marked name-match guess for the expense-account pulldown.
  _Done when:_ a dedicated usability revision of the four panels ships,
  informed by RM's full walkthrough notes and the accountant conversation.

- **No way to see whether a contact is QBO-linked.** — _added 2026-07-23_
  Contacts (and businesses) carry `qbo_customer_id` / `qbo_vendor_id`, but
  no konbini surface shows whether a given contact has a QBO ID or not —
  relevant when judging import states and future sync behavior. (The
  payment-terms manager's green "QBO" badge is the pattern to reuse.)
  _Done when:_ contact/business detail (and/or list) indicates QBO
  linkage.

- **Contacts import needs a dedupe process.** — _added 2026-07-23_
  QBO happily holds multiple customers ("locations") sharing one email or
  company name; konbini's unique constraints (contact email, business
  name) reject them. The commit now skips such rows and reports why
  (2026-07-23), but there's no way to resolve them: merge locations into
  one konbini business, pick a winner, or edit-then-retry inline.
  _Done when:_ a deliberate dedupe/merge flow exists for skipped
  contact imports.

- **Full AccountingCategory immutability/supersession.** — _added 2026-07-25_
  The deposits work (`docs/plans/deposit-invoices-spec.md`) freezes only
  `is_deposit`/`taxable` on a used category; RM wants the RateScheme
  pattern generalized — a used AC can't be edited, only retired and
  replaced. Needs its own design: which fields freeze (QBO account/item
  mappings must likely stay editable for reconnects; name/code are labels),
  whether replacement repoints anything, and the touch spans every
  line-item surface plus expenses.
  _Done when:_ a used AC's semantic fields are immutable behind a
  retire-and-replace flow, per a dedicated spec.

- **Generic `PATCH /api/settings/` bypasses the units endpoint's validation.** — _added 2026-08-01 (found during the hour-unit research)_
  `settings_view` PATCH (`apps/api/templates_config/views.py`) has per-key
  validators for the blep/schedule/labor keys but falls through to
  `ConfigurationService.set(key, str(value))` for anything else — including
  `units_list`. A `PATCH /api/settings/ {"units_list": ["none","ea"]}` writes
  the Python repr `['none', 'ea']` (not JSON) and skips the
  non-empty/`none`-first/no-dup/`hour`-present checks that
  `/api/settings/units/` enforces. Either route `units_list` through the same
  validation or reject it on the generic endpoint ("use /settings/units/").
  _Done when:_ the generic endpoint can no longer write an invalid or
  non-JSON `units_list`.

- **`get_units_list()` doesn't survive a malformed `units_list` row.** — _added 2026-08-01 (found during the hour-unit research)_
  `apps/core/units.py` catches only `Configuration.DoesNotExist`; a
  non-JSON value (e.g. written via the generic-settings bypass above) raises
  `json.JSONDecodeError` out of every unit dropdown, every line-item save,
  and the settings page — one bad config row bricks most forms in the app.
  Catch decode errors and fall back to `DEFAULT_UNITS` (arguably log too).
  _Done when:_ a garbage `units_list` value degrades to the default list
  instead of 500ing across the SPA.

- **Email settings fields attract browser password autofill.** — _added 2026-07-26_
  `EmailAccountSettings.svelte` uses a bare `type="email"` input next to a
  `type="password"` input with no `autocomplete` attributes, so browsers
  treat the pair as a login form and offer/save the user's stored
  passwords there. Rename the fields and/or add
  `autocomplete="off"`/`autocomplete="new-password"` (and non-credential
  `name` attributes) so the shop's IMAP/SMTP credentials form stops
  triggering the browser's password manager.
  _Done when:_ the email settings form no longer prompts browser
  autofill/save for the password field.

- **Outgoing email flows don't check that email is configured.** — _added 2026-07-26_
  Nothing gates the send flows on a working email account: with the
  DB-backed email config unset (post-migration from environment config,
  RM recalls intending this but no suppression exists in code), the
  Send buttons on invoices, estimates, change orders, and POs still open
  their dialogs and fail only at send time, and the Email area still
  offers fetch/compose. Wanted: a shared "email configured" signal
  (config rows present + non-blank) that suppresses or disables every
  outgoing-email affordance (invoice/estimate/CO/PO send, Email area
  actions) with a pointer to Settings → Email, instead of a late
  failure.
  _Done when:_ with no email account configured, every send/compose
  affordance is disabled or hidden with a Settings hint, and enabling
  config restores them without a reload dance.

- **Filter-change + stale page race on paginated lists.** — _added 2026-07-26_
  `InvoiceListPage.svelte` resets `page = 1` in each filter control's
  `onchange`, but the fetch `$effect` (keyed on page + filters) can flush
  between Svelte's `bind:value` listener and the reset — firing one
  request with the new filter and the stale page. Past page 1, switching
  to a filter with fewer pages 404s ("Invalid page" error note) before
  the corrected page-1 fetch lands. Reproduced on the invoices list
  (All p.2 → Open). Fix pattern: compose a filter signature inside the
  effect; when it changed and `page !== 1`, set `page = 1` and bail
  (effect re-runs cleanly) — then drop the per-control onchange resets.
  Audit every paginated list with filters for the same shape (contacts,
  businesses, POs, expenses, catalog tabs, search, email list …).
  _Done when:_ list pages share one race-free reset idiom and a filter
  change from a deep page never issues a stale-page request.

- **Migration cleanup must preserve the hand-written operations.** — _added 2026-07-26_
  28 migrations carry `RunSQL`/`RunPython`. Two buckets for the planned
  squash/regeneration: (a) MUST survive into any new initial migrations —
  `invoicing/0008_unique_draft_invoice_per_job` (MySQL stored generated
  column `draft_job_id` + unique index = the only DB-level
  one-draft-per-job enforcement; invisible in models.py) and
  `core/0027_seed_setup_defaults` (baseline Configuration rows for fresh
  installs); check `core/0005`/`0007` (default-groups create+cleanup —
  Groups are unused, the pair may net to nothing and can likely be
  dropped outright). (b) Safe to lose on from-scratch regeneration — all
  one-time data backfills (`backfill_*`, `migrate_*`, `rewrite_*`,
  `copy_*`, `normalize_*`, `cleanup_*`, phase-A), which no empty DB
  needs; they only matter if some environment must still migrate forward
  from an old schema. Also: `jobs/migrations/_phase_a_backfill_helper.py`
  is a plain module imported by `0034`, not a migration — prune
  accordingly. `squashmigrations` preserves these blocks but fragments
  around them; regeneration re-authors bucket (a) by hand. After any
  cleanup, run the full suite WITHOUT --keepdb (fresh from-scratch
  build) per house rule.
  _Done when:_ the cleanup lands with bucket (a) re-authored, fresh
  `migrate` + full suite green from an empty DB, and the e2e seed still
  loads.


- **Unstyled `<select>` elements read as "greyed out / disabled" on
  Chrome-on-macOS (and likely other browser/OS combos).** — _added
  2026-08-04_
  The app has no `select` styling anywhere (`app.css` has none;
  components render bare selects), so every dropdown gets the native
  chrome — on Chrome/macOS that's a grey rounded button, which sits
  next to white `<input>` fields and misreads as a permission-disabled
  control. RM hit exactly this on the task edit modal (Rate Scheme /
  Unit / Accounting Category selects beside the white Rate input) and
  confirmed the controls were fully functional. Decision for now:
  change nothing; *maybe* adopt an app-wide default select style (white
  field look matching inputs — border/background/padding) later.
  _Done when:_ either an app-wide `select` rule lands in `app.css`
  (matching the input look, checked across the major pages), or the
  team decides native chrome is acceptable and this entry is closed.


- **Hand-line material-ness should derive from the accounting category —
  drop the Material checkbox.** — _added 2026-08-09 (RM)_
  When adding a freeform hand line, choosing the Materials accounting
  category should itself mark the line as a material (`is_material`);
  a separate "Material" checkbox is then probably unnecessary. Today the
  checkbox drives it and the AC merely defaults
  (`_apply_material_ac_default` fills the configured
  `default_material_accounting_category` when the box is checked) —
  RM's point is the causality should run the other way. Touches the
  estimate/invoice/CO add-line forms, `is_material` handling in
  `EstimateService`/`ChangeOrderService`, and the crystallization
  discriminator's `is_material` arm (a bare material line becomes a
  Material at acceptance).
  _Done when:_ selecting the Materials AC on a freeform hand line yields
  material behavior with no separate checkbox (or the team decides the
  checkbox stays and this entry is closed).


- **Job overview Scope card links to the amended estimate instead of the
  latest agreement doc.** — _added 2026-08-10 (RM)_
  On a job with an ACCEPTED change order (no live CO), the Scope block's
  frozen state links to the estimate
  (`scopeFrozen` in `frontend/src/lib/jobOverview.js` — `href:
  estimateHref(jobId, current)`) even though the accepted CO tab is now
  the record of the current agreement (better-fees §11 #6: post-
  acceptance the CO tab is the record; the estimate stays as-was with
  the "amended" badge). It should link to the latest agreement document
  — the most recently accepted CO when one exists, else the estimate.
  Note the live-CO path already gets this right (`scopeActiveChangeOrder`
  gives the warm CO the link); only the frozen/settled state lags.
  _Done when:_ a job whose estimate is amended by an accepted CO has its
  Scope card link land on the latest accepted CO's page (jobOverview
  unit tests updated), falling back to the estimate when no CO exists.


- **PO line items should show the inventory item's code.** — _added
  2026-08-10 (RM)_
  A purchase-order line for a catalog item gives the vendor/shop no
  `InventoryItem.code` (the unique catalog code, inventory/models.py).
  Note the link is indirect: `PurchaseOrderLineItem` has no
  `inventory_item` FK — the route is the line's `linked_material`
  property (`Material.po_line_item` reverse) → `Material.inventory_item`
  → `.code`, so freeform/non-catalog lines simply have none. Surfaces:
  the PO page's line table and probably the PO PDF
  (`templates/purchasing/purchase_order_pdf.html`) where a code column
  is arguably most valuable (it's what the vendor keys on).
  _Done when:_ catalog-backed PO lines display the code on the PO page
  (and PDF if RM wants it there), blank for freeform lines.
