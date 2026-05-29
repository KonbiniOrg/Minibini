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
