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

## Open

- **Audit `$state` seeded from a prop — stale on prop change.** — _added 2026-06-04_
  The Svelte compiler warns `state_referenced_locally` in `Accordion.svelte`
  (`let isOpen = $state(open)`) and `TagEditor.svelte` (`let tags = $state([...initialTags])`):
  local `$state` initialized from a prop captures only the prop's *initial* value, so if the
  parent later changes that prop the component won't react. Harmless where the prop is
  effectively mount-only (current usage), a latent bug if it ever updates. Surfaced while
  writing component tests (the tests don't exercise the prop-change path).
  _Done when:_ the `$state`-seeded-from-prop sites have been grepped, and each is either
  confirmed mount-only or converted (e.g. `$derived`, or a reset via `$effect`).

- **`EstWorksheet.create_new_version` loses fields when cloning PlanTasks/PlanMaterials.** — _added 2026-06-01_
  Noticed while building job-duplication's worksheet copy (`JobService._copy_work_to_worksheet`,
  which copies these correctly). When revising a worksheet, `create_new_version`
  (`apps/estimates/models.py`) copies PlanTasks **without** `sort_order` or `est_worker_time`,
  and PlanMaterials **without** `units`. It also only walks each PlanTask's `plan_materials`,
  so any **task-less** PlanMaterial on the worksheet is silently dropped from the new version.
  Result: a revised worksheet can lose task ordering, scheduling durations, material units, and
  loose materials. _Done when:_ `create_new_version` carries `sort_order` + `est_worker_time`
  on PlanTasks, `units` on PlanMaterials, and includes task-less PlanMaterials.

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
- **Audit Configuration keys for settings-UI coverage.** — _added 2026-05-31_
  Some Configuration keys have no user-facing editor — `our_public_url` had none until
  the Business tab was added, and others likely lack UI too. Review every key the
  backend reads/writes (document-number sequences/counters, units, QBO accounts, email
  templates, retention/expiry days, `our_domain`, schedule keys, etc.) and make sure
  each user-settable one is editable somewhere in Settings. Exclude auto-managed keys
  (e.g. counters that increment on their own) from needing an editor.
  _Done when:_ every user-settable Configuration key has a settings-UI editor, and the
  audit has confirmed nothing is silently un-editable.

- **Send-email form: accept comma-separated recipients in To and Bcc, not just Cc.** — _added 2026-05-31_
  The document-send form (`DocumentSendForm.svelte`) accepts a comma-separated list in
  the Cc box but the To field doesn't take one; Bcc unverified. All three (To / Cc /
  Bcc) should accept a comma-separated list of addresses consistently.
  _Done when:_ To, Cc, and Bcc each accept and correctly send to a comma-separated list.

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

- **Customer-facing public URLs for documents (`{object_url}` real resolution) — ESTIMATES DONE.** — _added 2026-05-29; estimates resolved 2026-05-31_
  Estimates are now fully shipped: `Estimate.public_token` is minted at creation;
  `build_object_url('estimate', id)` resolves to `/portal/?token=<token>`; the
  `/api/portal/estimates/<token>/` read/accept/reject endpoints are live (AllowAny,
  token-authorized); the customer page is at `frontend/portal/` (second Vite entry).
  See `estimates-and-prices.md` §15.1 for the full spec.
  **Remaining:** PO / Invoice / Bill public URLs (no token column, no portal view);
  Change Order customer approval (blocked on CO send-to-customer flow — no CO PDF,
  no CO email service, no CO entry in `build_object_url`).

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

- **Review site-wide `z-index` usage; decide whether to impose a scale.** — _added 2026-05-26_
  We added an ad-hoc `z-index: 30` to `.job-header` (plus `z-index: 1` on
  `.hold-reason-form`) in commit `270c79d` to lift the on-hold reason popover above the
  page body. The SPA has no documented z-index scale, so stacking values are chosen
  one-off across headers, the `lib/api.js` error/success overlays, modals
  (`WorkerTimePromptModal`, `StartWorkConflictModal`), sticky bands (`CurrentBlepBand`),
  and dropdowns. Risk: silent collisions and "why is this behind that?" surprises.
  _Done when:_ we've grepped `frontend/src` for `z-index`, catalogued the values and the
  layers they represent, and either confirmed they're conflict-free or defined a small
  documented scale (e.g. content < sticky < dropdown < popover < modal < toast) and
  migrated the existing values onto it.

- **Job header is cramped for the on-hold reason capture; revisit the fixed 110px height.** — _added 2026-05-26_
  The on-hold reason form now pops over the page (commit `270c79d`), but the job header
  is a fixed `height: 110px` grid with vertically-centered content, so the form has to
  *overflow* the header rather than the header accommodating it. It works, but a
  transient form escaping its container is a layout smell.
  _Done when:_ either the header accommodates the reason capture cleanly (a proper
  modal/popover, or a header that can grow), or we've decided the overflow-popover is
  fine and noted why.

- **Revisit the Change Orders board-pillar color.** — _added 2026-05-26_
  Phase G picked dark red (`#b91c1c`) for the CO pillar; it sits visually between the
  `rejected` red and task orange and may read ambiguously against the accent palette.
  _Done when:_ the CO pillar color is confirmed or changed to read clearly alongside the
  existing pillars/board palette.

- **CO detail "target line" should show the estimate line's description, not "Line #id".** — _added 2026-05-26_
  The CO detail page reads the referenced estimate line for remove/replace rows; if the
  `ChangeOrderLineItem` serializer doesn't surface the target `EstimateLineItem`'s
  description/number, the UI falls back to an opaque "Line #id".
  _Done when:_ the CO line-item serializer exposes the target line's description (+ line
  number) and the CO detail renders it.

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

- **Should an Estimate with a change order on it stay `accepted`, or become `superseded`?** — _added 2026-05-26_
  The CO display paradigm treats estimate ⊕ CO as the current agreement and pushes the
  prior estimate into a superseded-like history slot — but the backend keeps the estimate
  `accepted`. Decide whether the *model* should actually supersede the estimate when a CO
  is accepted (cleaner model↔display match) or keep it `accepted` and let the display
  relabel (current). Interacts with the "one accepted estimate per job" rule and the
  `ChangeOrder.estimate` FK.
  _Done when:_ we've decided and either changed the model or written down why `accepted` stays.

- **Audit confirmations site-wide — confirm only the irreversible.** — _added 2026-05-27_
  We removed `confirm()` dialogs from the change-order line/deliverable edits (Change /
  Delete-of-a-draft-delta / Undo / New) — all exactly undoable by another local action.
  Sweep the SPA for `confirm(...)` and remove any guarding a reversible action; keep them
  only where the action is irreversible or extremely arduous to undo (deleting a persisted
  record, sending to a customer). Convention recorded in CLAUDE.md "UI Decisions".
  _Done when:_ confirmations across the SPA match the rule.

- **Validate the multi-change-order display (2+ COs).** — _added 2026-05-27_
  We spec'd `ch-1`/`ch-2` per-line tags but haven't built/validated how the CO view reads
  with two or more COs on a job: how the 1st CO's lines/deliverables show once a 2nd
  exists, and how the 2nd (and further) indicate they're later versions layered on the
  prior agreement. Look at this before closing the branch.
  _Done when:_ the CO view is legible with ≥2 COs (version layering + ch-N tags read clearly).

- **Distinguish on-hold job varieties on the pipeline panel?** — _added 2026-05-27_
  An on-hold job shows a single "on-hold" sub-status. Consider surfacing whether it has a
  CO and the CO's state (none / draft / open / accepted-awaiting-release). May only matter
  while testing — decide if it's worth the extra signal.
  _Done when:_ decided (implemented or dropped).

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

- **`Blep.user` is nullable — it shouldn't be.** — _added 2026-05-30_
  `Blep.user = ForeignKey('core.User', ..., null=True, blank=True)`. A logged time
  entry with no worker attached is meaningless, and it complicates the work-shifts
  enclosure invariant (a null-`user` blep can't belong to anyone's shift — see the
  backfill addendum in `docs/plans/2026-05-30-work-shifts-design.md` §14). Make `user`
  required once any existing null-`user` bleps are cleaned up.
  _Done when:_ `Blep.user` is non-nullable and the data has no orphaned (null-`user`) bleps.

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
