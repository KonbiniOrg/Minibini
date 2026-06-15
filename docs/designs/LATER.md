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

- **Should a superseded estimate's tab navigate to the current estimate?** — _added 2026-06-03_
  In job view, clicking a superseded estimate's tab shows that (old) estimate in the pillar, and
  its "View Full Estimate" link correctly points to the old one. Open question: should clicking
  the tab itself jump straight to the current live estimate instead of showing the superseded
  one? Unsure which is less confusing. _Done when:_ the superseded-tab click behavior is decided
  and consistent.

---

## Email

Outbound sending, inbound correlation, the reply/forward composer, threading, and the
email-association pickers. Grouped here because they share the EmailRecord / TempEmail /
IMAP-SMTP machinery and tend to be worked together.

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
  `EmailContent.svelte` and the deprecated `email_detail.html` template both render
  attachments as `<strong>{filename}</strong> ({content_type}, {size} bytes)` — no
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

- **Invoice `cancel` action bypasses `Invoice.save()` (no job auto-complete).** — _added 2026-06-13_
  `InvoiceViewSet.status_actions['cancel']` does `Invoice.objects.filter(pk=pk).update(status=STATUS_CANCELLED)`,
  which skips `Invoice.save()` → `_maybe_complete_job()`. `JobService.maybe_complete_if_resolved` counts
  `cancelled` invoices as resolved, so cancelling the last unresolved invoice on an all-shipped job will NOT
  auto-complete the job (it stays in its prior status until some other trigger). Pre-existing (predates the
  2026-06 financials-list work; surfaced during that review). Also conflicts with the CLAUDE.md "QuerySet.update()
  bypasses Model.save()" rule. _Done when:_ cancel routes through a service method that loads the invoice and
  calls `.save()` (or otherwise invokes the completion gate), with a test that a cancelled last-invoice on an
  all-shipped job completes the job.

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

- **Hidden-tombstone pruner for finished lots.** — _added 2026-06-15_
  Finished transient lots (not catalog, QOH 0, no earmarks) are **hidden, not
  deleted** — line items and template associations PROTECT-reference items, so
  physical deletion raises `ProtectedError`. Hidden rows accumulate slowly in
  `inventory_item`. Not a problem yet; merge removes some. If the table ever
  bloats, add a pruner — but it must handle the PROTECT FKs (only truly
  reference-free finished lots are deletable; the rest stay hidden forever).
  _Done when:_ either the table is shown to stay small enough to ignore, or a
  pruner deletes reference-free finished lots on a schedule.
