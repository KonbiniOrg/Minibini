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
