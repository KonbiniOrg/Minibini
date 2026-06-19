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

- `change-orders/ChangeOrderDetailPage.svelte` — **1038** (by far the largest; top priority)
- `jobs/TaskDetailPage.svelte` — 527
- `Search.svelte` — 499
- `purchaseorders/PurchaseOrderDetailPage.svelte` — 461
- `jobs/JobTaskListPage.svelte` — 427
- `jobs/JobShipmentsPage.svelte` — 418
- `worksheets/WorksheetDetailPage.svelte` — 407

**Watch list (300–365 lines):** `schedule/SchedulePage.svelte` (365),
`estimates/EstimateDetailPage.svelte` (344), `users/UserDetailPage.svelte` (306),
`contacts/ContactListPage.svelte` (301).

_Done when:_ each oversized route has had its UI pass with inline logic/sub-views
extracted into (tested) components, or a deliberate note recorded for why a given
page stays whole.

> Related: `components/jobs/JobDetail.svelte` is a similarly oversized
> **component** (not a route). It has a mount-only test today; its deep
> derivations (version timeline, CO delta layering) warrant the same
> extract-and-unit-test treatment. Noted in `docs/designs/frontend-testing.md`.

---

## Open

- **Earmarking is done per-material and then overwritten — do we need both layers?** — _added 2026-06-05_
  `MaterialService.create_on_job` calls `_mutate_earmark` (incremental; its docstring
  calls it "the sole writer of Earmark rows"), but the bulk job-population paths then
  call `InventoryService.create_earmarks_for_job`, which aggregates all the job's
  inventoried Materials by PLI and **overwrites** each Earmark to the absolute total.
  In a copy/population path the per-material increments already produce the correct
  total, so the final aggregate sweep looks redundant. Work out the intended division
  of labor (steady-state incremental edits vs one-shot bulk-population sweep), whether
  any path materializes Materials *without* `create_on_job` (which is what would make
  the sweep load-bearing), and whether one layer can be dropped without breaking
  idempotency. _Done when:_ we've documented why both exist (in
  `materials-inventory-and-purchasing.md`) or removed the redundant layer.
  _History (for context):_ earmarking was originally an `auto_earmark_inventory`
  signal on `estimate_accepted`, which only fired on the acceptance path (template and
  worksheet-copy paths got zero earmarks). Commit `9848a4c` (2026-04-05) deleted that
  signal and made earmarking a step inside *each* materialization path, establishing the
  invariant "every path that materializes work earmarks." Two weeks later `AtomCarryOverService`
  (`fdc3650`/`09031e3`, 2026-04-20) re-attached materialization to `estimate_accepted`
  but **without** the earmark step — silently breaking that invariant. A stale test
  (`test_accepting_estimate_does_not_create_earmarks`, also from `9848a4c`) kept passing
  because it guarded "the signal is gone," not "materialization earmarks," so it masked
  the regression. Fixed 2026-06-05 by routing carry-over through the shared
  `materialize_worksheet_onto_job` core, which earmarks; the test was inverted to
  `test_accepting_estimate_creates_earmarks`. So both earmark layers now run on that path:
  `create_on_job`'s incremental writes **plus** the final aggregate sweep — which is the
  redundancy this item is about.

- **Audit `$state` seeded from a prop — stale on prop change.** — _added 2026-06-04_
  The Svelte compiler warns `state_referenced_locally` in `Accordion.svelte`
  (`let isOpen = $state(open)`) and `TagEditor.svelte` (`let tags = $state([...initialTags])`):
  local `$state` initialized from a prop captures only the prop's *initial* value, so if the
  parent later changes that prop the component won't react. Harmless where the prop is
  effectively mount-only (current usage), a latent bug if it ever updates. Surfaced while
  writing component tests (the tests don't exercise the prop-change path).
  _Done when:_ the `$state`-seeded-from-prop sites have been grepped, and each is either
  confirmed mount-only or converted (e.g. `$derived`, or a reset via `$effect`).

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

- **Job header is cramped for the on-hold reason capture; revisit the fixed 110px height.** — _added 2026-05-26_
  The on-hold reason form now pops over the page (commit `270c79d`), but the job header
  is a fixed `height: 110px` grid with vertically-centered content, so the form has to
  *overflow* the header rather than the header accommodating it. It works, but a
  transient form escaping its container is a layout smell.
  _Done when:_ either the header accommodates the reason capture cleanly (a proper
  modal/popover, or a header that can grow), or we've decided the overflow-popover is
  fine and noted why.

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

- **Should an Estimate with a change order on it stay `accepted`, or become `superseded`?** — _added 2026-05-26; RESOLVED 2026-06-07_
  **Decision: keep it `accepted`** and let the display relabel to "amended". Reasoning: the
  estimate is still the base of the agreement-of-record (a CO is a delta, usually on only
  part of it), `compose_agreement` keys off `status = accepted`, and the "one accepted
  estimate per job" rule + `ChangeOrder.estimate` FK both depend on it. `superseded` was
  rejected because it already means "replaced by a newer *revision*" (the `revise_estimate`
  path) and would overstate a partial change; a new stored `altered`/`amended` state was
  rejected because the fact is fully derivable and a stored copy can drift. Instead "amended"
  is a **derived** read: `EstimateSerializer.is_amended` (+ board pipeline payload), true when
  the estimate is accepted and ≥1 *accepted* CO references it; the UI renders the word
  "amended" off that flag (see `estimates-and-prices.md` §14.9). If "amended" ever needs to
  *drive behavior* (transitions, board columns, reporting) rather than just label, revisit
  promoting it to a real state.

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
  part of the multi-CO validation above.

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

- **`is_amended` is an N+1 / duplicated derivation.** — _added 2026-06-08_
  `EstimateSerializer.get_is_amended` runs `ChangeOrder.objects.filter(estimate=...,
  status=accepted).exists()` per serialized estimate (bounded to accepted estimates
  by a short-circuit), and `BoardService._serialize_pipeline_job` repeats the same
  rule inline. Fine at current scale (mirrors the existing per-row `get_worksheet`
  query) but worth folding into one place — e.g. an `Exists()` annotation on the
  estimate queryset, or an `Estimate.is_amended()` method both call sites share.
  _Done when:_ the rule lives once and list endpoints don't pay a per-row query.

- **Distinguish on-hold job varieties on the pipeline panel?** — _added 2026-05-27_
  An on-hold job shows a single "on-hold" sub-status. Consider surfacing whether it has a
  CO and the CO's state (none / draft / open / accepted-awaiting-release). May only matter
  while testing — decide if it's worth the extra signal.
  _Done when:_ decided (implemented or dropped).

- **Should an on-hold job keep its place in the In Progress board area instead of dropping back to Pipeline?** — _added 2026-06-07_
  Currently putting a job on_hold moves it back to the Pipeline panel. But a job that was
  already being worked (approved / in_progress) and is paused for a change order is
  conceptually still "in the shop" — bouncing it to Pipeline loses its position and visual
  context, and it has to be re-found when work resumes. Consider keeping such a job in the
  In Progress area with an on-hold treatment (greyed/badged) so its place is preserved,
  while jobs that were never started stay in Pipeline. Interacts with the on-hold
  sub-status display above and the schedule's exclusion of on_hold jobs.
  _Done when:_ decided — either keep on_hold jobs in In Progress (implemented) or record why
  Pipeline is the right home.

- **Sweep `apps/api/` for `serializer.save()` bypasses — every mutation must go through a Service.** — _added 2026-05-27_
  We just found four API paths that called DRF `serializer.save()` (or `.update()`) directly
  instead of routing through the service-layer method that holds the guards: the task PATCH,
  the task-materials create + update, and the materials PATCH. Each one silently bypassed the
  on_hold freeze and would similarly bypass any future service-layer guard, side-effect, or
  invariant. The convention is **every mutating endpoint goes through a Service** — that's
  where validation, guards, and side-effects live, with `ValidationError` translated to 400.
  Direct DRF saves in views should be effectively zero in this codebase. Grep `apps/api/` for
  `is_valid` + `serializer.save()` / `.update()` and route any remaining bypasses through the
  appropriate service.
  _Done when:_ no mutating API view writes via the DRF serializer directly; all go through a
  Service.

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

- **Live blep timer can start at a high seconds value (minute-flooring artifact).** — _added 2026-06-18_
  The active-blep timer in `CurrentBlepBand.svelte` counts seconds (`elapsedSeconds`/
  `elapsedText`, ticks every 1s) as `now − start_time`, but `start_time` is the server's
  **minute-floored** value (`Blep.save` → `floor_to_minute`, `apps/jobs/models.py:462`):
  start a blep at 10:23:45 and it persists as 10:23:00, so the timer immediately reads ~45s
  instead of climbing from 0/1. Correct for billing (minute granularity is the point), but a
  jarring effect for the worker who just hit Start. Mitigation options to weigh:
  (a) drive the *display* from the true click instant captured client-side (store the
  unfloored wall-clock start in the `currentBlep` store / localStorage), independent of the
  floored persisted value, falling back to `start_time` on reload/other device;
  (b) show the live timer at **minute resolution** (e.g. "0 min" → "1 min", no seconds) so
  the sub-minute artifact never shows and the display matches how time is actually
  counted — the shift band (`ClockBand.svelte`) already effectively does this (ticks 30s,
  shows minutes), so only the blep band exhibits the seconds jump;
  (c) floor `now` to the same minute when computing elapsed so it ticks 0,1,2… whole minutes.
  _Done when:_ the live blep timer no longer appears to start mid-minute (by hiding seconds,
  or by timing the display off the real start instant), with the billed/floored value
  unchanged.

- **Re-billing Task actuals across multiple invoices.** — _added 2026-06-02_
  Invoices can be raised before a job is finished (e.g. progress billing). If invoice #1 is
  finalized and bills the actuals of Task A, then Task A gets more work logged, and later
  invoice #2 is generated for the same job, it's unclear how Task A's actuals are handled on
  the second invoice — does it re-bill the full actual (double-billing the earlier portion),
  bill only the delta since invoice #1, or refuse the atom as already-claimed? The atom-claim
  model (`InvoiceLineItemSource`) tracks which invoice claimed an atom, but a Task whose
  actuals *grew* after being billed has no defined delta-billing behavior. Decide and enforce
  the rule (likely: bill the unbilled delta, tracked per source).
  _Done when:_ generating a later invoice for a Task already partially billed produces the
  correct (non-duplicated) amount, with a test covering the grow-after-bill case.

- **Invoice revisions — back the "Revise (coming soon)" placeholder.** — _added 2026-06-04_
  `InvoiceDetailPage.svelte` shows a **disabled** "Revise (coming soon)" button on sent
  invoices (`canSeeRevise`), shipped as a placeholder — there is no invoice-revision backend
  (no `InvoiceService.revise`, no supersede/version chain like estimates have). Decide
  whether invoices need a revise flow at all (vs. cancel + new invoice) and, if so, build the
  backend + wire the button. _Done when:_ either the placeholder is backed by a working
  invoice-revise flow, or it's removed with a recorded decision that invoices don't revise.

- **Merge the source-pull ("wizard") view into the detail page as an in-place toggle.** — _added 2026-06-02_
  The estimate/invoice detail pages link out to a separate `/…/:id/wizard` route for the
  atom-pull view ("Show Worksheet" / "Show Billables"). That's approach (a): a rename + a
  navigation. Approach (b) — deferred here — is to make the source-pull surface an in-place
  *view toggle* on the detail page itself (no separate route), so the "normal" and "pull from
  source" views share one page, one header, and one load. Bigger restructure (folds
  `EstimateWizardPage`/`InvoiceWizardPage` into the detail components). Until then, the two
  views' headers are kept visually matched so the navigation feels seamless.
  _Done when:_ the detail page can switch between the line-item view and the atom-pull view
  without a route change, and the standalone wizard routes are retired.

- **Permission-store migration — residual cleanup.** — _added 2026-06-06_
  The gating-parity mismatches are fixed and gates now route through
  `frontend/src/stores/permissions.js`. Remaining: (a) **contact/business** gating
  (`ContactDetail`/`BusinessDetail`) was done but each hand-rolls an identical read-only
  tag list — converge on a `readonly` prop for `TagEditor` (or a shared `TagList`);
  (b) the `userPermissions` **prop chain** (TaskDetailPage → TaskActions → BlepEditModal →
  TimeEditModal/BlepList) is now dead after the store migration but can't be removed without
  touching `TaskDetailPage` (deliberately left alone this pass). _Done when:_ the tag display
  is de-duplicated and the dead `userPermissions` prop is removed end-to-end.

- **Superuser still referenced in test fixtures + fixture JSON.** — _added 2026-06-06_
  App code is now superuser-free (authorization is atoms-only), but several test files create
  `is_superuser=True` users as a privileged-actor shortcut (they still pass because Django
  grants superusers every perm) and `fixtures/unit_test_data.json` seeds a superuser. Migrate
  these to grant the four atoms explicitly so nothing references superuser. _Done when:_ no
  test fixture or fixture JSON relies on `is_superuser` for authorization.

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

- **Make the Estimate and Invoice atom/source-pull UIs consistent.** — _added 2026-06-03_
  The atom-pull ("wizard") surfaces for Estimates and Invoices look noticeably different, so a
  user who learns one doesn't recognize the other. They should share interaction vocabulary and
  layout so the pattern transfers. _Done when:_ the Estimate and Invoice atom-pull views present
  the same structure and controls (differing only where the domains genuinely differ).

- **Wizard's by-hand line item uses an inline editor, not the LineItemModal.** — _added 2026-06-03_
  Adding a manual line item from the detail page uses the new `LineItemModal` (manual/catalog
  toggle), but adding one inside the wizard uses a separate inline editor (likely the same one
  used when grouping atoms). Two different entry surfaces for "add a line item by hand" is
  confusing. Converge on one. _Done when:_ adding a manual line item uses the same component
  whether on the detail page or in the wizard.

- **Material added to an already-started Task is never consumed.** — _added 2026-06-17_
  Adding a Material to a Task *after* the Task has started is allowed (correct), but the
  newly-added material stays `pending` forever — continued work on the task doesn't consume
  it. Consumption of a task's materials is a one-shot side effect triggered when the task is
  *promoted* from `pending → in_progress` (the first blep: `start_work` /
  `_promote_pending_task` → `MaterialService.consume` over `task.materials.all()`,
  `apps/jobs/services.py`). A material attached later misses that already-fired trigger, so it
  never consumes (no QOH/earmark decrement, never billable since billable ⟺ consumed). Decide
  the intended behavior: e.g. consume a material on add when its task is already `in_progress`
  (and only then), or re-run the consume sweep on subsequent bleps for not-yet-consumed
  materials. Watch the `unconsume`/blep-cancel-undo interaction either way.
  _Done when:_ a material added to an in-progress task gets consumed by continued work (with a
  test), or a recorded decision says it must be added before start.

- **Single task on an entered-qty scheme collapses to qty 1 / price = total.** — _added 2026-06-17_
  Sending ONE Task atom with a user-entered-quantity scheme to a new line item shows qty 1 and
  price = the full amount (observed: entered qty 2.2 × rate 22 → line item qty 1, price 48.40),
  instead of qty 2.2 / price 22 with the total computed from them. Units copy fine here. Root
  cause: `InvoiceWizardService._task_qty_and_price` (`apps/invoicing/services.py`) returns
  `(Decimal('1'), total_price)` for *every* single task ("no single qty/price is meaningful across
  all algorithms"). But for entered-qty (and flat) schemes a real qty×rate *does* exist —
  `_atom_detail` already computes `qty = _task_actual_qty(task)` and `rate = effective_rate()` for
  the source-pool display. Fix direction: for single-task lines, use the scheme's actual qty and
  effective rate when the algorithm has a meaningful per-unit qty (entered/flat), falling back to
  qty 1 / total only where it genuinely doesn't (e.g. elapsed bleps, if that's still desired).
  _Done when:_ a single entered-qty task lands on the line item as qty=actual / price=rate with
  the total derived, with a test; revisit the elapsed-scheme case deliberately.

- **Adding a Task to a `work_complete` job doesn't reopen the job.** — _added 2026-06-17_
  A new Task can be added to a Job that's already at `work_complete`, and the job stays
  `work_complete` — even though it now has unfinished work, which contradicts what that status
  means (all tasks done). Task creation (`TaskCreationService.create_direct` /
  `create_from_template`, `apps/jobs/services.py`) only gates on `_assert_job_not_on_hold`, and
  the only auto-advance is `JobService.mark_work_started`, which fires `approved → in_progress`
  on a blep/complete — never on task creation, and a no-op for `work_complete`. The transition
  map *does* allow `work_complete → in_progress`, so the fix is to pull the job back to
  `in_progress` when an incomplete task is added (or its work begins) on a `work_complete` job.
  Related, decide the harder case: task creation is also allowed on a **terminal `completed`**
  job (only `on_hold` is blocked), which has no outgoing transition to reopen — so either block
  adding tasks there or define a reopen path. _Done when:_ adding an incomplete task to a
  `work_complete` job returns it to `in_progress` (with a test), and the `completed`-job case is
  decided (blocked or reopenable).

- **Should a superseded estimate's tab navigate to the current estimate?** — _added 2026-06-03_
  In job view, clicking a superseded estimate's tab shows that (old) estimate in the pillar, and
  its "View Full Estimate" link correctly points to the old one. Open question: should clicking
  the tab itself jump straight to the current live estimate instead of showing the superseded
  one? Unsure which is less confusing. _Done when:_ the superseded-tab click behavior is decided
  and consistent.

- **Neal's-data conversion emits some timestamps in the future.** — _added 2026-06-18_
  Generated (Neal's-dataset) data contains timestamps that fall **after now**, which should
  never happen for recorded activity. The converter anchors time to `_dataset_now(c)`
  (`nealsdata/converter/build.py:1687`) and `convert.md:306` says bleps are "clamped to ≤
  `_dataset_now` (no future bleps)" — so the leak is one of: (a) `_dataset_now` itself sits
  ahead of the real load date (it's derived from the dataset's latest activity, so loading an
  already-future-anchored dataset, or a stale `latest-time.json`, plants everything near a
  future "now"); or (b) timestamp generators **other than** bleps aren't clamped — candidates
  to chase: the per-task/schedule stamps built as `base_dt + timedelta(days=ordinal,
  minutes=intra)` (`build.py:~2204`), forecast/scheduled/due dates, and any `created_date`
  derivations — none of which obviously share the blep clamp. Pin down which field(s) and
  which path produce the future values, capture an example row + its source field, then either
  clamp those generators to `_dataset_now` too or re-anchor `_dataset_now` to the real load
  time. _Done when:_ a freshly converted/loaded Neal's dataset contains no timestamps after
  the load moment (with a check/test asserting it), or the future-dating is shown to be
  intended and documented.

- **Neal's-data generator: one blep per day, shift coterminal — want longer shifts with multiple bleps.** — _added 2026-06-18_
  `build_bleps_and_shifts` (`nealsdata/converter/build.py:1809`) emits **one Blep per complete
  Task** and then gives each (user, calendar day) **one Shift tightly enclosing that day's
  bleps** (~lines 1903-1911), so in practice each worker-day shows a single blep with a shift
  hugging its exact start/end. Unrealistic — a real workday is one longer shift containing
  several bleps (different tasks/jobs) with gaps between them and slack at the ends. Make the
  generated data look like that: (a) pack **multiple bleps per (user, day)** — let several
  tasks' bleps land in the same day within the synthetic workday (`build.py:24`), via
  `_place_blep`/`_earliest_slot` (~1750-1809) rather than spreading one-per-day; and (b) make
  the enclosing Shift a **realistic workday span** (e.g. fixed start-to-end, or bleps + slack)
  instead of coterminal with the bleps, so shift > sum-of-bleps and the shift↔blep enclosure
  has breathing room. Keep the existing invariants (blep inside its job window, no per-user
  overlap, shift encloses its bleps, `_dataset_now` upper clamp). _Done when:_ a generated
  dataset shows workers with multi-blep days inside longer, non-coterminal shifts (with the
  enclosure/overlap invariants still holding).

- **Pipeline job card hardcodes worksheet status to "Draft" (contradicts the estimate).** — _added 2026-06-18_
  On the job board's Pipeline cards, a worksheet chip shows **"Draft"** even when the job's
  estimate is **"Sent"** — and the worksheet page itself correctly shows **"Frozen"**. The
  card is wrong: `PipelineColumn.svelte` (the `worksheets` loop, ~lines 21-23) pushes a chip
  with a **hardcoded** `status: 'draft', statusLabel: 'Draft'` for every worksheet, while the
  estimate chip beside it renders the estimate's real status. Worksheets no longer have an
  independent status of their own — their editable-vs-**frozen** state is **derived** from the
  job's live estimate ("editable while the estimate is draft/absent, frozen once sent" —
  `apps/api/worksheets/serializers.py:101`; the worksheet page badge at
  `WorksheetDetailPage.svelte:274`), and the pipeline payload
  (`JobService._serialize_pipeline_job`, `apps/jobs/services.py:~1594`) emits only
  `est_worksheet_id`/name, no status — so the card has nothing real to show and fakes "Draft".
  Fix direction: either drop the worksheet status chip on the card entirely (worksheets have no
  standalone status), or surface the **derived** state — add the same `editable`/frozen flag the
  worksheet serializer computes to the pipeline payload and render "Frozen"/"Editable" — so the
  card can never contradict the estimate.
  _Done when:_ the pipeline card's worksheet indicator reflects the worksheet's real (derived)
  state and never shows "Draft" against a sent/frozen estimate.

---

## Email

Outbound sending, inbound correlation, the reply/forward composer, threading, and the
email-association pickers. Grouped here because they share the EmailRecord / TempEmail /
IMAP-SMTP machinery and tend to be worked together.

- **IMAP fetch crashes a message on naive-vs-aware datetime compare.** — _added 2026-06-18_
  Seen in fetch stats: `Error processing <…@…ip6.arpa>: can't compare offset-naive and
  offset-aware datetimes` (the weird `ip6.arpa` Message-ID is incidental — any message can
  trip it). In `EmailService.fetch_emails_by_date_range` the cursor `date_threshold` is read
  back via `datetime.fromisoformat(latest_email_date)` (`apps/core/services.py:449`) and
  compared against the IMAP `msg.date` at `msg.date > most_recent_email_date`
  (`apps/core/services.py:485`, again at ~529). `msg.date` is usually tz-**aware** (parsed
  from the Date header's offset) but is **naive** for messages with a missing/malformed Date
  header, and the persisted cursor's awareness depends on what last wrote it
  (`timezone.now()` is aware, but a naive `most_recent_email_date.isoformat()` round-trips
  back naive) — so a mismatch on either side raises. It's caught per-message (appended to
  `stats['errors']`), so it doesn't crash the run, but that email is **skipped** and the
  cursor may not advance past it. Fix: normalize both operands to tz-aware before comparing
  (coerce naive ones via `timezone.make_aware`, default UTC) at both compare sites, and store
  the cursor aware so the `fromisoformat` round-trip stays aware.
  _Done when:_ a message with a naive/missing Date header fetches without error (with a test
  covering a naive `msg.date` against the stored cursor), and the cursor advances correctly.

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

- **Email-association pickers cap the dropdown at 100 entries and sort poorly.** — _added 2026-05-28_
  `EmailAssociatePage.svelte` (jobs) and, once they land, the equivalent PO and Bill
  pickers all request `?page_size=500` to populate a `<select>`, but
  `StandardPagination.max_page_size = 100` silently caps it. Fine while each table is
  under 100 rows; once any of them crosses that, only the most recently-created entries
  are reachable. The pickers also lean on each list endpoint's default ordering, which
  isn't always what a human would call "most recent" — `Job` sorts by `-created_date`
  (fine), but PO/Bill defaults need a deliberate decision (a job's `start_date` or last
  status change is arguably more relevant than its creation; a PO's issue/sent date
  beats its created_at; a Bill's bill_date or due_date may matter more than its
  created_at). _Done when:_ each picker either paginates / searches server-side
  (typeahead against `?search=`) or filters to "active" statuses only AND sorts by a
  human-meaningful lifecycle date per entity (decide which per entity at that time),
  whichever is cheaper than scrolling a long `<select>`.
  - _Pattern to copy (added 2026-06-01):_ `ContactPicker.svelte` (used by
    `DuplicateJobPage`) does server-side `?search=` typeahead against `/api/contacts/`
    with prefill-by-id — the shape these capped pickers should move to.

- **Link-email Job picker is an oversized `<select>` — swap to the existing `JobPicker`.** — _added 2026-06-18_
  The "Associate Email with Existing Job" page (`EmailAssociatePage.svelte`) populates a
  plain `<select>` of every job via `api.get('/api/jobs/?page_size=500')` (lines ~22/88-95)
  — both unwieldy to scroll and silently capped at 100 by `StandardPagination`, so older jobs
  aren't reachable. The inline-search component already exists: `components/JobPicker.svelte`
  does server-side `?search=` typeahead (`/api/jobs/?search=…&page_size=10`) and is already
  used by `ExpenseForm` and the PO forms. Just replace the `<select>` with `<JobPicker>`
  (bind the chosen `job_id` into `selectedJobId`, keep the existing required-field guard).
  This is the concrete fix for the job case of "Email-association pickers cap the dropdown at
  100 entries" (above). _Done when:_ the link-email page selects the job via the typeahead
  picker, reaching any job regardless of count, and the bulk `?page_size=500` load is gone.

- **Track bill partial-payment amounts (add `Bill.qbo_amount_paid`).** — _added 2026-06-12_
  `Bill` records only `qbo_payment_status` (a string), not an amount paid, so a
  `partly_paid` bill's outstanding balance can't be computed. The Financials Bill
  list (shipped 2026-06) shows a coarse balance — full total for any non-fully-paid
  status — which overstates `partly_paid` bills (footnoted in the UI). _Done when:_
  `Bill` grows a `qbo_amount_paid` field (mirroring `Invoice.qbo_amount_paid`), the
  forthcoming bill QBO payment polling populates it, and the Bill list/detail balance
  becomes exact. See `docs/plans/2026-06-12-financials-list-views-design.md`.

- **Consolidate the customer/contact pickers around `CustomerPicker`.** — _added 2026-06-12_
  Once the new `CustomerPicker` (dual-source contact+business typeahead, emits
  `{type, id}`; from `docs/plans/2026-06-12-financials-list-views-design.md`) ships,
  revisit the existing single-source pickers. `ContactPicker.svelte` is currently used
  only by `DuplicateJobPage.svelte`; in places that conceptually pick "a customer" we
  may actually want `CustomerPicker` (which can surface a standalone business, not just
  a contact). Audit each `ContactPicker` site (and consider whether `JobPicker` shares
  enough shape to fold into a generic typeahead too). _Done when:_ each picker site has
  been deliberately assigned to the right component, and any genuinely-duplicated
  picker bodies are collapsed into a shared base — or a note records why they stay
  separate. Don't churn working code without a reason; this is a consolidation pass,
  not a mandate to merge everything.

- **Consolidate `BillSerializer.get_balance` and `BillSummarySerializer.get_balance` into a shared helper.** — _added 2026-06-13_
  The two serializers duplicate the coarse-balance definition: 0 for `paid_in_full`/`cancelled`/`refunded`,
  otherwise the line-item sum. `BillSerializer.get_balance` computes it in Python (looping over
  line items); `BillSummarySerializer.get_balance` reads a DB annotation (`balance_anno`).
  If the balance definition changes — e.g. when bill partial-payment tracking lands and
  `partly_paid` bills need an exact `total − qbo_amount_paid` figure — both must be updated
  in sync. A shared helper (or a model method) would consolidate the rule.
  See `docs/plans/2026-06-12-financials-list-views-design.md`.
  _Done when:_ the balance logic lives once and both serializers reference it.

- **Reimbursement QBO push fails consistently with an error.** — _added 2026-06-14_
  Surfaced during Expenses UI testing: creating a `Reimbursement` batch (`ReimbursementService.create_batch`
  → `QBOExpenseSyncService.push_reimbursement`) fails on the QBO push, leaving the batch in `sync_failed`
  every time. The DB commit stands (expenses still flip to `reimbursed`), but the QBO sync never succeeds.
  Error text not yet captured here — paste it in when reproducing. Could be env-only (QBO connection/
  credentials in this dev env) or a real defect in the reimbursement push payload; needs triage to tell which.
  _Done when:_ the push succeeds against a connected QBO sandbox, or the failure is root-caused to an env/config
  issue and documented (with the retry path via `ReimbursementService.retry_sync` confirmed working).

- **Mixed-receipt expense loses the non-inventory cost.** — _added 2026-06-14_
  An expense is single-mode (cost OR stock receipt) and records one purchased item.
  Real corner case: on one trip a worker buys 3 sheets of an **inventoried** PLI (the
  shortfall) **and** a special **non-PLI finish** the job needs. If they record the
  inventoried item, the expense becomes a stock receipt — its `amount` is treated as
  inventory (cost-at-consumption, excluded from `_spent`), so the finish's cost is
  effectively **dropped** (absorbed into the amount as if it were tax/fee). If they
  record the finish instead, the plywood never hits QOH and the task stays blocked.
  Today the workaround is to record **two separate expenses** (one stock receipt, one
  cost), but nothing surfaces that, so the cost can silently vanish. Not super likely,
  but real. See `docs/plans/2026-06-14-expenses-cost-model-redesign.md` (single-mode
  decision) and the deferred many-materials/line-item direction.
  _Done when:_ either an expense supports multiple purchased items with per-item mode
  handling (inventoried rows → receipts, cost rows → job cost), or the form detects a
  mixed receipt and prompts the user to split it — so a non-inventory cost can never be
  silently swallowed by a stock receipt.

- **Write-off → QBO?** — _added 2026-06-15_
  Inventory write-off (`InventoryService.write_off`) zeroes a lot's QOH and books
  the remainder to `qty_wasted`, recording an `InventoryHistory` entry. It does
  **not** push anything to QBO. Decide whether written-off inventory should post
  to QBO as an expense / COGS / shrinkage adjustment, or stay inventory-only.
  _Done when:_ a decision is recorded — either a QBO push path for write-offs
  exists, or it's documented that write-offs are deliberately inventory-only.

- **Revisit finished-lot collection (hide vs. delete) comprehensively.** — _added 2026-06-15_
  Background: the original plan was *delete-on-spend*, but the code review surfaced
  that line items (estimate/invoice/PO/bill) and `TemplateMaterialAssociation`
  reference items via **PROTECT**, so unconditional deletion raises
  `ProtectedError`. The shipped model is **hide-on-spend**: a finished transient
  lot (not catalog, QOH 0, no earmarks) is hidden by the list filter, not deleted.
  On top of that, `InventoryService.collect_if_finished` now **deletes a finished
  lot when it is genuinely reference-free** (`can_be_deleted`), else hides it —
  but only at **demote** (`update_item`) and **write-off**, the deliberate,
  non-undoable transitions. It is deliberately **NOT** applied at:
  - **consume** — reversible via `unconsume()` (blep-cancel undo), which needs the
    item to restore stock; deleting on consume would break that undo.
  - **`release_earmarks_for_job`** (job cancel/complete) — a bulk
    `Earmark.objects.filter(job=job).delete()` that can leave a QOH-0 lot
    reference-free, but the cleanup hook isn't wired there yet.
  Also note `can_be_deleted` ignores Materials (SET_NULL) by design, so a
  consumed lot is "reference-free" even though a Material points at it — fine
  because Materials are self-contained and history survives, but worth a
  deliberate decision.
  To revisit: (a) should consume/job-cancellation also collect, with a
  reversibility-safe approach (e.g. collect on job close, or on unconsume-window
  expiry)? (b) a periodic **pruner** for hidden tombstones that have since become
  reference-free; (c) whether demote-deletes-when-unreferenced is the right UX or
  should prompt. _Done when:_ a single documented policy covers every finished-lot
  transition (demote, write-off, consume, job-cancel) and tombstone cleanup.

- **Warn before unchecking Catalog can delete the item.** — _added 2026-06-15_
  Unchecking "Catalog" on an empty (QOH 0, no earmarks), reference-free item now
  hard-deletes it (`collect_if_finished` on demote). The InventoryItemForm gives
  no warning — a user demoting to reorganize can lose the row unexpectedly. Add a
  confirm/notice on the Catalog checkbox (or on save) when the item would become
  a deletable finished lot — e.g. "This item has no stock and isn't referenced;
  unchecking Catalog will remove it." _Done when:_ demoting an item that would be
  collected prompts the user first (and ideally distinguishes delete vs. hide).

- **Generic server-side search picker (and the picker 100-cap).** — _added 2026-06-15_
  `PriceListItemPicker` (used in 5 places — MaterialModal, PlanMaterialModal,
  LineItemModal, expenses/MaterialPicker, PO LineItemForm) loads the catalog and
  filters **client-side**, but the load request is clamped to 100 by
  `StandardPagination` (see architecture-and-conventions.md §3.3) — so once the
  active catalog passes 100 items, the rest can't be selected when adding a
  material / line item, silently. The Contact/Business picker already does
  **server-side `?search=`** for *two* models; we'd deferred a generic version
  because two-model felt like a one-off. We've since hit it again: the now-deleted
  `CatalogPicker` was a built-but-never-wired two-model (TaskTemplate +
  InventoryItem) picker — the same shape — and this single-model one is capped.
  Direction: build a generic **`EntitySearchPicker`** parameterized by *sources*
  (`{endpoint, kind, render}`) doing server-side `?search=`; migrate
  `PriceListItemPicker`'s call sites to it (one source) and **rename/retire
  PriceListItemPicker → InventoryItemPicker**; a multi-source config covers the
  task-template-or-material "catalog" case if that feature is ever wanted. Fixes
  the cap for free. Deferred to keep the inventory feature branch scoped.
  _Done when:_ one server-search picker backs the material/line-item pickers,
  reaching any active item regardless of catalog size, and PriceListItemPicker is
  renamed/retired.

- **"Qty on order" column on the inventory list.** — _added 2026-06-15_
  The inventory list shows on-hand / earmarked / available but not how much is
  already **on order** (outstanding on open POs). Add a "On order" column: per
  `InventoryItem`, sum the un-received quantity of `PurchaseOrderLineItem`s
  referencing it on non-cancelled POs (`qty − qty_received − qty_cancelled`,
  floored at 0) — the same outstanding calc `MaterialSerializer.get_qty_on_order`
  already does for a single PO-linked material, but aggregated across all POs for
  the item. Needs a computed field on the inventory-item serializer (annotate or
  property) + the column in `InventoryListPage`. Helps decide whether to hit the
  new per-row "order" button or wait on stock already coming.
  _Done when:_ the inventory list shows an accurate on-order quantity per item.

- **Material "order" link should default the qty, not just the inventory data.** — _added 2026-06-18_
  Clicking **order** on a material in the job view (`JobDetail.svelte:997`,
  `#/purchase-orders/new?job={job_id}&material={material_id}`) opens the PO line-item form
  with the material's inventory data (item/description/price) prefilled, but **qty is left
  blank** — the link passes only `job` + `material`, no quantity. The plumbing to carry it
  already exists: `PurchaseOrderFormPage.svelte` forwards `prefill_material=…` to the PO
  detail page (~lines 63-66), and `LineItemForm.svelte` already applies `prefill.qty` when
  present (`if (prefill.qty != null && prefill.qty !== '') form.qty = …`, ~line 36). The gap
  is the step that derives the prefill **from the Material** — it sets the inventory fields
  but not qty. Fix: include a default qty in that material-derived prefill. Decide the default:
  the material's full needed `quantity`, or the **outstanding shortfall** (needed − on-hand/
  earmarked − already on order) which is the more useful "how much to actually buy" number and
  ties into the "Qty on order" / earmark data above. _Done when:_ ordering from a material
  pre-fills the PO line with both the inventory data and a sensible default qty (with the
  full-vs-shortfall default decided).

- **Inventory add/edit form opens at the top of the page — make it a modal.** — _added 2026-06-18_
  `InventoryListPage.svelte` shows the create/edit form **inline at the top of the page**
  (`{#if showForm}` block, ~lines 138-143; `editItem` just flips `showForm = true`). On a
  catalog that can run **hundreds of rows long**, clicking "edit" on a row far down the list
  pops the form up top — off-screen — so the user has to scroll up to use it and loses their
  place in the list, and the row being edited isn't visible next to the form. Move the form
  into a **modal/overlay** (or an in-row expander / side panel) so editing happens in place
  without scrolling away. There's already an established modal pattern in the SPA to follow
  (`MaterialModal`, `LineItemModal`, `PlanMaterialModal`). Keep the existing `{#key
  editingItem}` re-seed behavior when switching rows. _Done when:_ adding/editing an inventory
  item no longer jumps the user to a top-of-page form — the form appears in place (modal or
  equivalent) and the list keeps its scroll position.

- **Inventory merge is still awkward — rework the keep/discard selection + add a preview.** — _added 2026-06-18_
  The merge UI in `InventoryListPage.svelte` (the `{#if showMerge}` panel, ~lines 147-167) is
  a top-of-page block with two raw `<select>` dropdowns — "keep" and "discard" (`mergeKeep`/
  `mergeDiscard`, discard limited to non-catalog `lotOptions`) — disconnected from the table
  the user is looking at. On a long catalog you re-hunt both items by name in unsearchable
  selects (same picker problem as elsewhere), the merge is **irreversible** (line ~55) yet
  there's **no preview** of what will move (QOH, earmarks, line-item/template references) or
  which item wins, and it shares the top-of-page scroll problem. Directions to make it less
  awkward: drive selection **from the rows** (e.g. pick a discard row's "merge into…" action,
  or select two rows in the table) so you act on what you see; use the search/typeahead picker
  the other notes call for (the planned `EntitySearchPicker`) instead of raw `<select>`s; show
  a **confirmation preview** of the resulting merged item (combined QOH, moved references,
  which id survives) before committing; and put it in a modal/in-place surface rather than a
  top-of-page panel. Related: the inventory-edit-modal note above and the generic
  server-side search picker note. _Done when:_ merging is driven from the list rows with a
  searchable picker and an explicit before-commit preview of the outcome, no top-of-page
  dropdown hunting.

- **Inventory merge should probably accept an incoming `'none'` unit.** — _added 2026-06-19_
  `InventoryService.merge` hard-blocks when `keep.units != discard.units`
  (`apps/inventory/services.py:151`) — the QOH addition is nonsense across real
  unit mismatches (sheets into lbs). But `'none'` means *unknown*, not a real
  unit, so blocking a `'none'` discard from merging into a `'sheets'` keep is
  over-strict. Consider: when the discard's unit is `'none'`, allow the merge and
  adopt the keep's unit (and symmetrically, a `'none'` keep adopts the discard's).
  Surfaced by the Neal's converter: the minted transient lots (`LOT-xxxx`,
  `is_catalog=False`, from `build._mint_transient_lot`) all carry `units='none'`,
  so deduping one into its real `'sheets'` catalog item is currently blocked.
  Note this is *also* a data-gen roughness, not purely a model gap: in the
  converter **every** Material (and therefore every minted lot) comes out
  `units='none'` because FreeAgent estimate/invoice line items carry no unit
  signal — `parsing.resolve_li_units_and_qty` only ever returns `'hours'`/`'none'`
  — whereas catalog items get `'sheets'` from their description
  (`_unit_from_description`). So the cleaner converter-side fix may be to infer
  raw-stock Material units from the description the same way catalog items do (or
  default sheet-stock to `'sheets'`), which would also shrink how often the merge
  ever sees a `'none'`. Decide whether the fix belongs in merge, the converter, or
  both. _Done when:_ merge handles a `'none'`-unit incoming sensibly (with a test),
  and the converter's blanket `'none'` material units are either justified or
  fixed.

- **Expense invoice-freeze has no billability-readiness gate, by design.** — _added 2026-06-17_
  Expense atoms have an invoice-freeze (`ExpenseService._assert_not_invoiced`)
  but no separate billability-readiness gate — they appear as selectable in the
  wizard pool from the moment they are submitted (unlike Tasks, which require
  `complete`, and Materials, which require `consumed`). This is deliberate: an
  expense is ready to bill as soon as it exists. Revisit only if a
  "not ready to bill" expense state is ever needed.

- **Expense didn't count as a cost in the job overview — and NO catalog item was picked. Investigate.** — _added 2026-06-18_
  Observed: an expense didn't show up as an expense/cost in the job overview. The obvious
  suspect is the single-mode classification — `ExpenseService.create`
  (`apps/expenses/services.py:38-42`) silently treats a purchase as a **stock receipt**
  (sets `stock_pli`/`stock_qty`, no consumable `Material`, `amount` excluded from `_spent`
  / not job-costed) whenever the selected item resolves to an *inventoried* (catalog)
  `InventoryItem`. BUT the user reports **no catalog item was selected at all**, so that
  path shouldn't have fired — which means the real cause is unknown and needs digging.
  Lines to chase: how did the expense get classified / what `stock_pli` vs `material` vs
  neither did it end up with; whether a non-catalog expense can still land as a stock
  receipt (e.g. `new_material` resolving to an inventoried item unexpectedly, or a default);
  whether `material`/`job` even got linked; and what the overview's "spent" actually sums
  (does it require a linked `Material`/`job`, so a cost expense with no material or a
  detached `job` FK silently drops out?). Capture the actual row (`stock_pli_id`,
  `material_id`, `job_id`, `amount`) when reproducing. Related: "Mixed-receipt expense
  loses the non-inventory cost" (above) and
  `docs/plans/2026-06-14-expenses-cost-model-redesign.md`.
  _Done when:_ the cause of a non-catalog expense missing from the job-cost overview is
  root-caused and fixed (or shown to be expected), with a test.
