# Schedule view

The `#/schedule` page visualizes each worker's assigned work on a time-axis
calendar over a rolling N-day horizon. Tasks render as horizontal bars in
queue order, anchored to actual blep times where work has happened and
projected forward by estimate where it hasn't, pivoting at a live "now" line.
Drag-to-reorder rearranges a worker's queue without reassigning.

Audience: shop manager (capacity planning) and workers (reading their own
row). All authenticated users can view; the drag is gated only by the
existing `/api/tasks/reorder/` permissioning.

The backend is `apps.schedule` — a model-less, service-only app (like
`apps.search`). `ScheduleService` (`apps/schedule/services.py`) builds the
layout from existing data; `calendar_arithmetic.py` holds the pure
work-time helpers. The HTTP layer is `apps/api/schedule/views.py`.

---

## 1. Inputs

No schema is owned by the schedule. It reads:

- `Task.assignee`, `Task.worker_queue` (queue position, shared with the Job
  Board), `Task.est_worker_time` (required once a task has an assignee),
  `Task.status`.
- `Blep.start_time` / `Blep.end_time` — actuals; an open blep (`end_time IS
  NULL`) is the running session.
- `Job.accent_color` — a stable per-job color (`CharField(7)`). On
  `Job.save()` an unset color is filled from `BoardService.ACCENT_COLORS`,
  picking the least-used color among active Jobs (ties by palette order).
  Persisted; the Board and the schedule both read it.

---

## 2. Configuration

Lazy string KV in `apps.core.Configuration` (defaults written on first read,
mirroring `email_retention_days`):

| Key | Default |
|---|---|
| `schedule_workday_start` | `08:00` |
| `schedule_workday_end` | `17:00` |
| `schedule_task_buffer_minutes` | `10` |
| `schedule_horizon_days` | `3` (clamped 1–14) |

The workday is **continuous** — there is no lunch break (it was removed; see
Future work). Saturdays and Sundays are hardcoded non-working. A "Schedule"
section in `SettingsPage.svelte` writes these via the existing
`/api/settings/` endpoint.

---

## 3. The cascade algorithm

`ScheduleService.get_schedule(now, horizon_days, offset)`:

**Window.** `horizon_start` is midnight of the working day at `offset`
working days from today (`offset` drives past/future scrolling); the window
spans `horizon_days`. Each `days[]` entry carries `date`, `label`,
`is_working`.

**Workers.** Every active `User` with at least one task assigned to them that
is `pending`/`in_progress`/`blocked`, or `complete` with a blep ending today.
Ordered by name.

**Per-worker walk.** Tasks in `(worker_queue, pk)` order. A monotonic
`cursor` advances forward only; after each advance it is normalized past
workday-end / weekends via `next_workable_moment`. Each task emits one or
more **bars**:

| `kind` | Source | Layers |
|---|---|---|
| `historical` | Past blep groups | Dark actual; light estimate coextensive for completed |
| `active` | The current in-progress session | Light (estimate) + dark (elapsed), both anchored at the session's first blep |
| `forecast` | Projected slot for a pending task | Light only |
| `parked` | A blocked task | Hatched marker in a secondary lane band; does not consume cursor time |

A bar's `segments` split the wall-clock interval at every overnight / weekend
boundary; each segment carries `est_fill_to` / `actual_fill_to` (where the
light / dark layers end) and `continues_left` / `continues_right` flags that
drive the zigzag edges. Pending bars advance the cursor by `est_worker_time +
buffer`; an in-progress bar advances it past the later of its estimate
projection and its actual end (`now` if running). Completed bars end at the
actual end, so finishing early or running long shifts downstream tasks.

The work-time math lives in `calendar_arithmetic.py` as pure functions over a
`DayShape(workday_start, workday_end, task_buffer_minutes)`:
`next_workable_moment`, `add_work_time` (adds work-time, skipping
overnight/weekend), `segments_for`, `work_minutes_between`,
`shift_working_days`.

**Off-hours in-progress widening.** If a worker has an open blep running
outside configured hours, the *display* day shape widens (start floored / end
ceiled to the hour) to cover that work plus its estimate projection.
Forecasts still cascade on the configured hours — config drives the cascade,
display drives the axis. The response carries both so the frontend shades the
off-hours margins.

---

## 4. API

```
GET /api/schedule/?days=<int>&offset=<int>      Permission: IsAuthenticated
```

`days` defaults to `schedule_horizon_days` (clamped 1–14); `offset` is the
working-day scroll offset (clamped ±60). Response envelope:

```json
{
  "now": "…", "horizon_start": "…", "horizon_end": "…",
  "horizon_days": 3, "offset": 0,
  "day_shape": {
    "workday_start": "08:00", "workday_end": "17:00",
    "task_buffer_minutes": 10,
    "config_workday_start": "08:00", "config_workday_end": "17:00"
  },
  "days":    [ { "date": "…", "is_working": true, "label": "Mon · May 19" } ],
  "jobs":    [ { "job_id": 110, "name": "…", "accent_color": "#dc2626", … } ],
  "workers": [ { "user": { "id": 5, "name": "…", "initials": "RP" },
                 "bars": [ { "task_id": …, "kind": "active", "segments": [ … ] } ] } ]
}
```

`day_shape` reports the (possibly widened) display shape plus the configured
hours. Reordering reuses `POST /api/tasks/reorder/` (`{"task_ids": [...]}`);
the SPA refetches after a successful reorder.

---

## 5. Frontend

`frontend/src/routes/schedule/SchedulePage.svelte` plus
`frontend/src/components/schedule/` (`WorkerLane`, `TaskBar`, `NowLine`,
`TaskQuickCard`) and the `stores/schedule.js` store (load + 5-minute
auto-refresh + reorder). The Board's `JobChipStrip` is reused at the top.

- **Layout math** (client): each working day gets an equal panel; a segment
  maps to an absolutely-positioned div, with light/dark layer widths derived
  from `est_fill_to` / `actual_fill_to`. Zigzag edges via `clip-path` on
  segments flagged `continues_left/right`. Completed bars render dimmed.
- **Now line** seeds from the payload `now` and ticks client-side each minute;
  hidden when "now" is off the scrolled window. ‹/› and "Today" drive
  `offset`; a day-count control drives `?days=N`.
- **Drag-to-reorder**: only `forecast` / `parked` bars are draggable; a 3px
  drop indicator snaps to buffer midpoints and hides on a no-op move. No
  cross-lane drag (reassignment is out of scope).
- **Job focus**: clicking a chip in `JobChipStrip` toggles `focusedJobIds`,
  dimming non-focused jobs' bars across lanes.
- **Clickable bars** open `TaskQuickCard` — task identity, live-blep banner,
  embedded `TaskActions` (start/stop/complete/block/unblock/cancel), reassign
  via `AssignModal`, and a link to the full task. For `can_manage_time`
  managers it also offers on-behalf "Start/Stop for «worker»" targeting the
  lane worker (the on-behalf path is gated server-side; see
  `jobs-tasks-and-worksheets.md` §4.5/§5.2).

---

## 6. Future work

- **Per-worker lunch / breaks** — lunch was removed; it returns as a
  per-`User` break each lane computes itself (re-adds a break notion to
  `DayShape` + `calendar_arithmetic` + the response + frontend panel math).
- **Configurable weekend / holiday list** and **per-worker schedule shapes**.
- **Mid-stream estimate adjustment** — bump `est_worker_time` on a running
  task without restarting tracking (the algorithm already handles changed
  estimates; only the UI is missing).
- **User-pickable job colors** (currently admin-editable only).
- **Cross-lane drag (reassignment)** and **pin-to-specific-time drag**.
- **"+N more" off-horizon indicator** when a queue extends past the horizon.
