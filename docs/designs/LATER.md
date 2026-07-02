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

- **Reassigning a PO line's job/material is tricky — rethink the whole flow.** — _added 2026-06-21_
  Changing which job a PO line (and its linked material) belongs to currently has
  awkward, split entry points. On a **draft** PO the inline **Edit** changes the job
  (routed through `onChangeLineJob`); on an **issued/received** PO there's no Edit, so a
  standalone **Change Job** modal is the only path, gated by `canChangeJob` (allowed when
  the linked material's `consumption_state === 'pending'`). The draft-only duplicate
  "Change Job" button was removed 2026-06-21 (Edit covers it), but the underlying model is
  still murky: the rules differ by PO status × material consumption_state, and reassigning
  an already-received line's material to a different job has cost/earmark implications that
  aren't obviously surfaced. Want to think more about the right mental model and UX for
  "this material actually belongs to a different job" before committing to a design.
  _Done when:_ we've settled how (and when) a line's job/material allocation can change
  across the PO lifecycle, with one coherent UX, and documented it in
  `materials-inventory-and-purchasing.md`.

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

- **"Mark Work Complete" button shows on Draft jobs (task list).** — _added 2026-06-30_
  On the job task-list page (`JobTaskListPage.svelte`), the "Mark Work Complete" action is
  offered even on a **Draft** job. Marking work complete is meaningless before the job is
  approved — the button should be hidden for Draft status (decide whether Submitted counts
  too), alongside the existing `jobLocked` gating.
  _Done when:_ "Mark Work Complete" is not shown for Draft jobs, with a test.

- **"Send all to Estimate/Invoice" button on the source-pull (wizard) page.** — _added 2026-06-30_
  On the estimate/invoice source-pull page (`EstimateWizardPage` / `InvoiceWizardPage` — the
  "Show Tasks & Materials" / "Show Billables" view), atoms are added to the document one row at
  a time. When the user just wants to copy **all** the job's atoms onto the document, add a
  one-click **"Send all to Estimate" / "Send all to Invoice"** action that projects every
  available (unclaimed / billable) atom at once. Prior art: the invoice detail page already has
  "Apply everything" (`seed_all_atoms`), and a `send_all_atoms_to_estimate` service existed for
  estimates before the plan-layer removal — re-introduce the equivalent at the wizard level for
  both documents.
  _Done when:_ the source-pull page has a one-click "send all atoms" action for both estimate
  and invoice that projects all available atoms, with a test.

- **Wizard "Done" should auto-save unsaved lines.** — _added 2026-06-30_
  On the estimate/invoice source-pull page, pressing **"Done"** should commit any unsaved
  (dirty/pending) line edits automatically, instead of leaving them unsaved or requiring a
  separate save per line. This stays within the explicit-save convention — "Done" *is* the
  deliberate commit action (not a blur), so flushing pending edits on it is correct.
  _Done when:_ pressing "Done" on the source-pull page persists all pending line edits, with a test.

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

- ~~**Email-association pickers cap the dropdown at 100 entries and sort poorly.**~~ — _delivered 2026-06-21_ All three email-association pickers (jobs, POs, bills) now use `SearchPicker`-based type-ahead against their respective `?search=` endpoints; the bulk `?page_size=500` loads are gone.

- ~~**Link-email Job picker is an oversized `<select>`.**~~ — _delivered 2026-06-21_ Replaced with `JobPicker` (itself built on `SearchPicker`).

- ~~**Consolidate the customer/contact pickers around `CustomerPicker`.**~~ — _superseded 2026-06-21_ The `SearchPicker` consolidation landed instead: a shared behavior core (`SearchPicker.svelte`) backs all per-entity pickers (`JobPicker`, `ContactPicker`, `BusinessPicker`, `PurchaseOrderPicker`, `BillPicker`, `InventoryItemPicker`, `CustomerPicker`). Each picker site was deliberately assigned; no audit of `CustomerPicker` reassignments is outstanding.

- **Consolidate `BillSerializer.get_balance` and `BillSummarySerializer.get_balance` into a shared helper.** — _added 2026-06-13_
  The two serializers duplicate the coarse-balance definition: 0 for `paid_in_full`/`cancelled`/`refunded`,
  otherwise the line-item sum. `BillSerializer.get_balance` computes it in Python (looping over
  line items); `BillSummarySerializer.get_balance` reads a DB annotation (`balance_anno`).
  If the balance definition changes — e.g. when bill partial-payment tracking lands and
  `partly_paid` bills need an exact `total − qbo_amount_paid` figure — both must be updated
  in sync. A shared helper (or a model method) would consolidate the rule.
  See `docs/plans/2026-06-12-financials-list-views-design.md`.
  _Done when:_ the balance logic lives once and both serializers reference it.

- **Invoice `cancel` action bypasses `Invoice.save()` (no job auto-complete).** — _added 2026-06-13_
  `InvoiceViewSet.status_actions['cancel']` does `Invoice.objects.filter(pk=pk).update(status=STATUS_CANCELLED)`,
  which skips `Invoice.save()` → `_maybe_complete_job()`. `JobService.maybe_complete_if_resolved` counts
  `cancelled` invoices as resolved, so cancelling the last unresolved invoice on an all-shipped job will NOT
  auto-complete the job (it stays in its prior status until some other trigger). Pre-existing (predates the
  2026-06 financials-list work; surfaced during that review). Also conflicts with the CLAUDE.md "QuerySet.update()
  bypasses Model.save()" rule. _Done when:_ cancel routes through a service method that loads the invoice and
  calls `.save()` (or otherwise invokes the completion gate), with a test that a cancelled last-invoice on an
  all-shipped job completes the job.

- ~~**Reimbursement QBO push fails consistently with an error.**~~ — _resolved 2026-06-21 (ENV-ONLY)_
  Root-caused: no code defect. `push_reimbursement` is structurally identical to the working expense
  push; a characterization test with a mocked client passes on first run (`tests/test_qbo_reimbursement_push.py`).
  The dev `sync_failed` is purely the missing QBO sandbox: `get_client()` → None →
  `ValueError('No active QBO connection')` → `QBOSyncService.run_create` records `sync_failed`. The local
  commit stands (batch + reimbursed expenses); recovery is the existing `ReimbursementService.retry_sync`
  once a sandbox is connected.

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

- ~~**Write-off → QBO?**~~ — _resolved 2026-06-21_ Decision: write-offs stay **inventory-only**, no QBO
  push. Inventory cost is expensed at purchase time (bills/expenses post to expense/COGS accounts, not a
  capitalized inventory asset), so a write-off has no QBO consequence and pushing one would double-count.
  Recorded in `quickbooks-integration.md` ("Inventory write-offs are not pushed"). Revisit only if QBO is
  ever switched to true inventory-asset tracking.

- **Reimbursement batch delete/unwind isn't exposed in the SPA.** — _added 2026-06-22_
  The backend fully supports unwinding a reimbursement batch — `ReimbursementService.delete`
  voids the QBO Purchase (now symmetric: a failed void refuses the delete and retains the batch
  marked `sync_failed`), flips its expenses back to `submitted`, and deletes the batch row, behind
  the confirm-delete endpoint `DELETE /api/reimbursements/{id}/?confirm=true`. But **no SPA component
  calls it** — `UserReimbursementPanel` only creates batches and retries sync; there's no
  delete/unwind button. So a batch (e.g. one stuck in `sync_failed`) can't be unwound from the UI.
  _Done when:_ the reimbursement panel (or a batch detail view) has a confirm-guarded delete/unwind
  action wired to the existing endpoint, surfacing the 400 the same way the other delete actions do.

- ~~**Failed-*delete* batch vs. retry-sync ambiguity.**~~ — _resolved 2026-06-22_
  Resolved by the `qbo_pending_op` work: every `QBOSyncable` record now stores which operation it
  owes (`create`/`update`/`delete`), set by the orchestrator (`run_create`/`run_update`/`run_delete`)
  on failure. `retry` dispatches on it — a failed-delete row re-runs the delete, a failed-update row
  re-applies the update (the old retry's create-push short-circuit, which silently mis-handled both,
  is gone). See `quickbooks-integration.md` "Retry & sync failures". The broader "should
  Customers/Vendors/Invoices also get this base + appear in the failures view" is the remaining open
  question (they use ad-hoc sync state today) — left below as its own consideration.

- **Maybe fold the invoice push into `save_and_log`?** — _added 2026-06-21_
  Every QBO create/update push now routes through `QBOService.save_and_log` (and the deletes through
  `delete_and_log`). The **invoice send** (`InvoiceEmailService.send_invoice`) is the lone holdout: it does
  create-`save` → persist `qbo_id` → `_mark_as_sent` (a *second* QBO round trip) → *then* `log_sync` success,
  so its success row means "created **and** marked-sent," not just "created." Folding the create-`save` step
  into `save_and_log` would move the success log to right after the create (before mark-sent) — a deliberate
  change to what the log row means (QBO-object-creation vs whole-send success). Possibly worth it for symmetry,
  but it needs more thought about the two-round-trip semantics and the partial-failure window.
  _Done when:_ we've decided whether the invoice create-step joins `save_and_log` (with the log-semantics
  call made) or stays a bespoke sequence, and recorded why.

- **Drop `request.user` threading from imperative history; default to the request context.** — _added 2026-06-22_
  Imperative history sites that fire from an authenticated request (`record_payment`, `cancel_line_item`,
  the inventory/purchasing services, the PO email/cancel/receive paths) **thread `request.user` through
  service-method signatures** purely to hand it to `record_history`. That's redundant: `record_history`
  could default `user` to `current_request_user()` — the same request-scoped `HistoryContext` the `@history`
  decorator already reads (middleware sets it; DRF auth has run by the time a view's service code executes).
  The **deliberate-author sites need no change** — they call `record_history` directly with their own
  explicit `user`, which overrides any default: portal (`user=None` + customer in the changes payload),
  signals & the expiry commands (`user=system_user`), and `backfill_job_history` (a *specific historical
  author* + backdated `timestamp=`, run with no request — the proof that `record_history` must keep an
  *optional* `user=` param). So the refactor is bounded and mechanical: **(a)** make
  `record_history`/`record_action` default `user` to `current_request_user()`; **(b)** drop the `user`/`actor`
  params from the request-driven service methods; **(c)** leave the deliberate-author sites untouched.
  Context: the 2026-06-22 QBO-attribution work (`record_action`, `QBOSyncLog.triggered_by` via `log_sync`)
  already uses the context for its *new* code — deliberately inconsistent with the still-threaded older
  sites; this item converges everything to one attribution style.
  _Done when:_ request-driven services no longer thread a user just for history attribution, the
  deliberate-author sites are unchanged, and there's a single attribution mechanism.

- **`@history` decorator `anchor=` param — route an adjunct's auto-history to its primary.** — _added 2026-06-22_
  The `@history` decorator keys entries to the model's *own* `object_type`, so an adjunct (BillPayment→Bill,
  line item→parent document) can't use it to land its auto create/update entries on the **primary's**
  timeline — those stay imperative (`record_action(object_type='<primary>', …)`). A declarative
  `@history(anchor=('bill', 'bill_id'))` could route a child's auto-history to its parent (and would
  generalize to line items, etc.). Caveats that keep it from being a clean win: parent-anchored *field
  diffs* read ambiguously without a self-describing label ("amount 50→75" on the bill — whose amount?);
  it still wouldn't cover deletes; and a many-anchor case (Reimbursement→many expenses) doesn't fit. It's a
  change to a core mechanism on ~12 models. Deferred — adjunct lifecycle stays imperative via `record_action`.
  _Done when:_ decided whether to add `anchor=` (+ a labeling mechanism) to the decorator, or keep adjunct
  history imperative.

- **`@history` doesn't track deletes (`post_delete`).** — _added 2026-06-22_
  The decorator wires `post_init`/`pre_save`/`post_save` only — **no `post_delete`** — so a tracked model's
  deletion records nothing automatically. Not a problem today: the decorated records (estimates, bills, POs,
  …) and the newly-decorated `Expense` are *created-and-kept forever*; deletions are rare and are recorded
  imperatively where they matter. Revisit only if a frequently-deleted model becomes `@history`-tracked.
  _Done when:_ decided whether `@history` should grow delete tracking, or imperative delete entries remain
  the norm.

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

- ~~**Generic server-side search picker (and the picker 100-cap).**~~ — _delivered 2026-06-21_ `SearchPicker.svelte` is the generic behavior core; `InventoryItemPicker` (renamed from `PriceListItemPicker`) uses server-side `?search=` and is the picker at all material/line-item call sites.

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

- **Money inputs send floats → "no more than 2 decimal places" on non-round values.** — _added 2026-06-20_
  Class bug. `<input type="number" bind:value={x}>` coerces the value to a JS float,
  sent as a JSON number; Django converts a float to `Decimal` via its binary value
  (e.g. `33.33` → `33.3299...`), tripping a `DecimalField(decimal_places=2)` validator.
  Exactly-representable values (`50`, `12.5`) slip through, so it looks intermittent.
  Fixed for the bill-payment path on `feature/bills` (commit `3c931e3`): the Record
  Payment modal amount input is now `type=text`/`inputmode=decimal` (sends the exact
  string) and `BillPaymentService` normalizes via `Decimal(str(value))` server-side.
  **The same pattern remains in other money inputs** — notably
  `frontend/src/components/LineItemModal.svelte` (qty/price on PO/Bill/Invoice/Estimate
  line items), and likely other `type="number"` money/qty fields. Do a sweep:
  switch money inputs to string-valued (`type=text`/`inputmode=decimal`) and/or add a
  shared server-side `Decimal(str(...))` normalize on the line-item/qty write paths,
  keeping the real >2-decimal validation intact.
  _Done when:_ entering a non-round amount (e.g. `19.99`) in any money field saves
  cleanly, with regression tests, and no `type="number"` money input sends a raw float.

- **PO line form needs an explicit "attach to existing material" picker.** — _added 2026-06-20_
  When adding a PO line for a job that already has materials, there's no way to
  deterministically attach the line to a *specific* existing pending material.
  Today the backend resolver (`MaterialService.resolve_or_create_for_line`,
  three steps: explicit `material_id` → claim → create) only auto-links
  ("claim") when job + inventory_item match *exactly one* pending, unlinked
  material on that (job, item); otherwise it **creates a new material** —
  silently producing a duplicate for freeform materials, item mismatches, or
  multiple candidates. The "order this material" flow sets `material_id` for the
  *first* line only (one-shot prefill, cleared after add — see commit f3440447).
  Fix: on the PO line form (`LineItemForm` via `PurchaseOrderDetailPage`), once a
  Job is selected, surface that job's pending **unlinked** materials and let the
  user pick "attach to this one" (sends `material_id`, routing through the
  resolver's explicit path) or "create new". Removes the guessing and makes
  second-line-to-second-material deterministic.
  _Done when:_ a user can add a PO line for a job and explicitly choose which
  existing pending material it links to (or opt to create a new one), with tests.

- **nealsdata converter mints a zero-rate flat-fee ServiceItem for $0 source lines.** — _added 2026-06-23_
  After the ServiceItem reframe, the converter (`nealsdata/converter/build.py`,
  `_match_seed_scheme`) mints one flat-fee `ServiceItem` per distinct price; a
  source line priced at $0 yields a `rate=0.00` flat-fee service (seen in
  regenerated `fixtures/large_datasets/nealsmall.json`, pk 18 "Flat Fee $0.00").
  `validate_data` flags flat-fee services with non-positive `rate`, so this is
  discoverable, but it's untidy dev seed data. Lowest-risk fix: a converter guard
  that skips emitting a flat-fee service when `rate <= 0` (and logs the source
  line) or routes it to a documented sentinel. Dev-data only; not test-path.
  _Done when:_ regenerating the neals fixtures produces no zero-rate flat-fee
  ServiceItem (or the case is deliberately documented), and `validate_data` is
  clean on the regenerated dev data.

- **Percentage-adjustments cleanup bundle (Phase 2 deferred minors).** — _added 2026-06-23_
  Non-blocking follow-ups from the Phase 2 (percentage adjustments) whole-branch
  review, all triaged DEFER. Bundle into one cleanup pass:
  - N+1: add `select_related('adjustment_service')` (and `prefetch_related('adjustment_target_categories')`) to `compose_agreement`'s estimate line query (`apps/estimates/agreement.py`) and to the estimate + invoice line-item querysets feeding `EstimateLineItemSerializer`/`InvoiceLineItemSerializer.get_adjustment_service_detail`.
  - Dead code: remove the never-run `validate_service_item` on `PlanTaskDetailSerializer` (`apps/api/plan_tasks/serializers.py`, read-only serializer); remove the duplicate local `ValidationError` import inside `ServiceItem.clean()` (`apps/jobs/models.py`, already imported at module top).
  - Tests: restore the `assertTrue(...exists())` post-condition dropped from `test_discard_draft_rejects_non_draft` (`tests/test_estimates_services.py`); add a `test_effective_rate_rejects_percentage` (mirrors the tested `get_actual_qty` guard); add a `compute_adjustment_amount` case for a null-AC sibling against a non-empty target set; tidy the dead `find` predicate in `AgreementAdjustmentsPanel.test.js` case 4.
  - UX polish: `AgreementAdjustmentsPanel` "Add" re-fetches its own list but not the wizard's line-item columns — add an `onLineItemAdded` prop wired to the wizard's `reloadLineItems` so the new line appears without a manual reload.
  - Future-coupled: when AC-grouping / multi-target adjustments land, revisit the same-percentage-service-twice case (keyed `{#each}` + `already_added` dedup in the panel assume one line per service).
  _Done when:_ the bundle is swept and the full suite + frontend gate stay green.

- ~~**"Add Manual Task" modal: offer "Save as Template based on this task".**~~ —
  _graduated 2026-06-27 to the "Add Line" rework (Phase 1)._ Inline "save this
  free-text task to the **ServiceItems** catalog" (post-rename: `TaskTemplate` →
  `ServiceItem`) is now a Phase-1 task, including decoupling the catalog *create* from
  `can_manage_config`. See `docs/plans/2026-06-26-phase1-add-from-price-list.md`.

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

- **Sweep for bare string literals that should be class constants.** — _added 2026-06-25_
  Recurring smell: status / algorithm / type values hardcoded as bare strings
  (e.g. `'completed'`, `'flat_fee'`, `'percentage'`, `'draft'`) instead of the
  model's **class constant** (`Job.STATUS_COMPLETED`, `ServiceItem.FLAT_FEE`,
  `ServiceItem.PERCENTAGE`, `Estimate.STATUS_DRAFT`). Per CLAUDE.md "Status
  Constants" rule + the code-review checklist. Periodically grep `apps/` (and JS
  where the value is mirrored, e.g. `algorithm === 'percentage'`) for bare
  choice-value literals and swap in the constant — watch the recent
  ServiceItem / percentage-adjustments code especially. Legitimate exceptions:
  migration files and migration-safe helpers (e.g. `flat_fee_reframe.py`
  intentionally uses the literal `'flat_fee'` so it works against historical models).
  _Done when:_ a sweep finds no bare choice/status/algorithm literals where a class
  constant exists (remaining ones are the deliberate migration-safe cases).

- **DRY: combine the two near-identical material modals.** — _added 2026-06-27_
  `frontend/src/components/PlanMaterialModal.svelte` (PlanMaterial, on the Plan/
  worksheet) and `frontend/src/components/MaterialModal.svelte` (real Material, on the
  Job) are highly similar — same fields (description, qty, units, price, AC),
  inventory-item pre-seed, and freeform path — differing mainly in the API base /
  parent (worksheet plan-material vs job material) and a few field names. Worth
  collapsing into one shared modal parameterized by context (like `WorkItemForm` does
  for job/worksheet/subtask), or a shared inner form both wrap. _Done when:_ one modal
  (or shared form) serves both PlanMaterial and Material, with the component tests for
  both consolidated and green.

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

- **Lost per-material "order" link when the Materials pillar was folded into Tasks & Materials.** — _added 2026-06-28_
  The old standalone Materials pillar on the job overview rendered, per material that
  needed more stock, an **"order"** link (`#/purchase-orders/new?job={job_id}&material={material_id}`)
  plus an **"On Order"** column (showing `qty_on_order` and a link to the existing PO).
  Phase 5 (commit `0f989580`, "combine Tasks & Materials into one pillar via the Task
  View") replaced that pillar with `TaskTree`, and the per-material **order** affordance
  + On Order column did **not** carry over — `TaskTree` shows the sell-side columns and
  grand total (mirroring the invoice projection) but has no "needs more → start a PO"
  control. Surfaced 2026-06-28 while working an invoice flow that got blocked by missing
  inventory. _To decide:_ whether the order-from-material shortcut should be restored
  inside the combined pillar (or live elsewhere — Plan/worksheet materials, or a
  materials/PO view), and whether the On Order / shortfall indicator comes back with it.
  _Done when:_ a user can get from "this job's material is short" to starting/ viewing
  its PO without leaving the job overview, or we've consciously decided that lives
  somewhere else and documented where.

- **Sweep test suite for `self.skipTest('… in fixture')` anti-pattern.** — _added 2026-06-30_
  Several tests silently skip when ambient fixture data is absent (e.g. "Need at least two
  users in fixture", "No ENTERED_QTY RateScheme in fixture"). Seven were fixed 2026-06-30
  (self-setup or hard-assert). Grep the full suite for remaining `self.skipTest` calls that
  rely on fixture content and convert them: either create the required data inline so the
  test is self-sufficient, or replace the skip with `self.fail(…)` so a missing prerequisite
  fails loudly. A skip that hides a broken prerequisite is worse than a red test.
  _Done when:_ no test skips because ambient fixture data is absent; every prerequisite
  is either created by the test itself or triggers a hard failure.

- **Hand-added blep should mirror the start-path side effects (assign + consume materials).** — _added 2026-06-29_
  Starting a blep on a pending/unassigned task runs the "first worker to start the task"
  path (`apps/jobs/services.py` ~1174-1254): it **assigns** the task to that worker,
  promotes it in the worker queue, and **consumes the task's linked materials**
  (`MaterialService.consume`, ~line 1013). But adding a blep **by hand** (the time-edit
  create path) does none of this — the task stays unassigned and its materials stay
  unconsumed. A manually-entered blep should produce the same state as a started one:
  (a) assign the task to the blep's worker, and (b) consume the task's linked materials.
  _To check:_ confirm current hand-add behavior for both; _done when:_ creating a blep by
  hand on a pending task assigns it to the blep's user and consumes its linked materials,
  with tests.

- **Service catalog item = rough work type; Task.Description carries the specifics.** — _added 2026-07-01_
  A service catalog item (RateScheme) should name the _rough category_ of work, with the
  Task's own `Description` field free to add the detail. E.g. pick **"CAM coding"** (a CAD
  RateScheme) from the service catalog when adding a Task, then fill in the Description
  with the specifics: _"V-Carve the lettering, but use AutoCAD to cut the perimeters with
  dogbones."_ The catalog entry is the billing/type bucket; the Description is the
  human instruction. Confirm the add-Task flow lets you set both — a RateScheme for the
  rate/category **and** a distinct free-text Description on that same Task — and that the
  Description isn't overwritten from the RateScheme name.
  _Done when:_ adding a Task lets you choose a service (RateScheme) for the work type while
  independently authoring the Task's Description, and neither clobbers the other.
  _Corollary:_ if the catalog entry only ever supplies the rough type, then RateSchemes /
  service catalog items may not need a `description` field at all — just a `name`. The
  per-use detail lives on the Task. Review whether the RateScheme `description` field earns
  its keep or should be dropped in favor of name-only, with Task.Description as the sole
  place for specifics.

- **Surface session-expiry instead of silently degrading fetched-list components.** — _added 2026-07-01_
  When the session expires, `GET /api/settings/units/` returns 403 and
  `UnitsSelect.svelte` swallows it in a `try/catch`, falling back to `['none']` — so a
  logged-out user just sees a mysteriously empty/`none`-only units dropdown (observed in
  the estimate Add-Line-Item modal) with no hint that they're logged out. Any
  fetch-and-fallback component has the same failure mode. There should be a global
  handler: when an authenticated-only API call returns 401/403, bounce to the login
  screen (or show a "session expired, please log in again" banner) rather than letting
  each component degrade silently. _To check:_ whether `api.js` / the auth store already
  catches 401/403 anywhere. _Done when:_ a 401/403 on any API call surfaces a clear
  session-expiry path instead of a silently broken widget.
