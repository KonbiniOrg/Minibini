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

- [x] **Clickable bars (Increment A).** Clicking a bar opens `TaskQuickCard`
      (`frontend/src/components/schedule/TaskQuickCard.svelte`): task identity,
      status, live-blep banner, embedded `TaskActions` (start-me / stop-me /
      complete-with-data-entry / block / unblock / cancel), Reassign via
      `AssignModal`, "Open full task →" link, and ×/Esc/click-outside close.
      Reusable into the job board's task cards with minimal changes.
- [ ] **Clickable bars — Increment B: on-behalf actions.** "Start for
      \<worker\>" and "Stop \<worker\>'s timer" are disabled placeholders in
      the card. Both have time-tracking side effects:
      - Start: must run the `start-work` lifecycle (promote to in_progress,
        consume materials, mark job work-started, queue-promote) but attribute
        the blep to the worker → extend `start-work` with an `on_behalf_of`
        user (gated by `can_manage_time`).
      - Stop: close the worker's open blep (PATCH via the existing
        `can_manage_time` blep machinery), but mind any close side effects.
- [ ] **Selecting a job card.** Clicking a job in the top JobChipStrip should
      focus/dim its tasks across lanes (cf. the board's `focusedJobIds`).
- [ ] **More/fewer days from the page.** A horizon control on the page itself.
      The API already accepts `?days=N`; needs a UI control + store wiring.
- [ ] **Mark done from the page.** Covered by TaskQuickCard's "Mark complete"
      (Increment A). Standalone one-click-on-the-bar variant still possible if
      wanted.

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
