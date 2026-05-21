# Schedule view — follow-ups

Working notes for the schedule view (`#/schedule`). The view is built and
functional on branch `feature/schedule`. See `2026-05-19-schedule-view-design.md`
for the design and `2026-05-19-schedule-view-implementation.md` for the build.

## Status

Shipped and working:
- Per-worker time-axis calendar; rolling N-day horizon (default 3).
- Light/dark layered bars (estimate over actuals); zigzag continuation
  across lunch and overnight.
- Lunch and overnight rendered as dedicated, bar-free gap slots.
- Full-height "now" line; 5-minute auto-refresh.
- Stable per-job color (`Job.accent_color`).
- Drag-to-reorder within a worker's lane, with a drop-position indicator
  (3px blue bar; snaps to buffer midpoints; hidden on no-op moves).
- Starting a blep promotes the task to position 1 in the worker's queue.
- Settings: work-day shape + buffer + default horizon.

## Open UI follow-ups

- [ ] **Clickable bars.** Navigate to task detail vs. side panel vs. inline
      expand — undecided. Bars are currently drag-only (forecast/parked) or
      static (historical/active).
- [ ] **Selecting a job card.** Clicking a job in the top JobChipStrip should
      focus/dim its tasks across lanes (cf. the board's `focusedJobIds`).
- [ ] **More/fewer days from the page.** A horizon control on the page itself.
      The API already accepts `?days=N`; needs a UI control + store wiring.
- [ ] **Mark done from the page.** Complete a task from the schedule (likely an
      action on the active bar) without navigating away. Needs the status
      transition API call + refetch.

## Deferred

- **Hover text timing.** Browser-native `title` tooltip: first hover ~1.5s,
  subsequent near-instant. Replace with a custom tooltip (div + setTimeout)
  only if a tunable delay / richer content is wanted. Not now.

## Future scope (not v1)

- **Mid-stream estimate adjustment** — bump `est_worker_time` on an
  in-progress task without restarting time tracking.
- **Per-worker lunch times** — lunch is currently global Configuration; make
  it per-User. Each WorkerLane would compute its own panel stretches; the
  structural-slot layout already supports this.
- **Weekend / holiday config** — Saturdays/Sundays are hardcoded non-working
  in v1; replace with a configurable list + weekly pattern.
- **User-pickable job colors** — currently auto-assigned; admin-editable only.
- **Cross-lane drag (reassignment)** — purposely excluded from v1.
- **Pin-to-specific-time drag** — calendar-style scheduling instead of
  queue-position scheduling.
- **"+N more" off-horizon indicator** — when a worker's queue extends past the
  visible horizon.
