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
