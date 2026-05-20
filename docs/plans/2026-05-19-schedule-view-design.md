# Schedule view — Design

A new top-level page, `#/schedule`, that visualizes assigned work for each
worker on a time-axis calendar. Tasks display as horizontal bars in queue
order, anchored to actual blep times where work has happened and projected
forward by estimate where it hasn't. Lunch and overnight breaks split bars
visually without splitting the underlying tasks. Drag-to-reorder rearranges
a worker's queue without reassigning.

Audience: shop manager (primary, capacity planning) and workers (secondary,
reading their own row). All authenticated users can view the page; only the
existing `/api/tasks/reorder/` permissioning gates the drag.

---

## 1. Goals and non-goals

**Goals**

- Show what each worker is doing across a rolling N-day horizon (default 3).
- Bars in queue order, sized by `est_worker_time`.
- Past time = actuals (bleps); future time = plan (estimates). Pivot at "now".
- Tasks completed early or running long shift downstream tasks accordingly.
- Lunch and overnight breaks split bars visually; one Task remains one Task.
- Configurable work-day shape and inter-task buffer (Configuration KV).
- Drag-to-reorder within a worker's row (existing `worker_queue` mechanic).
- Auto-refresh on a ~5-minute cadence; client-side "now" line advances minute
  to minute without server round-trips.
- Stable per-job color across the board and the schedule.

**Non-goals (v1)**

- Reassigning tasks between workers from this view (no cross-row drag).
- Configurable weekend / holiday list. Saturdays and Sundays are hardcoded
  as non-working in v1 and shown as tiny greyed columns.
- Per-worker schedule shapes.
- Mid-stream estimate adjustment.
- Pinning a task to a specific start time.
- User-pickable job colors (assigned automatically; admin can edit if needed).
- Add-worker affordance from this view.
- Workers without assigned tasks appearing as empty rows.

---

## 2. Data model and configuration

### 2.1 No schema changes to Task, Blep, User

Everything we need is already on the existing models:

- `Task.assignee` — which worker owns the task.
- `Task.worker_queue` — position in the worker's queue (existing field used by
  the Job Board for drag-to-reorder).
- `Task.est_worker_time` — `DurationField`, required when a task has an
  assignee (enforced by `Task.clean()`).
- `Task.status` — `pending`, `in_progress`, `blocked`, `complete`, `cancelled`.
- `Blep.start_time`, `Blep.end_time` — actuals. `Blep.elapsed` derives.

### 2.2 New field: `Job.accent_color`

The Job Board currently assigns colors by enumeration position in a query
ordered by `due_date`. Adding a new in-progress job shifts colors of jobs
later in the ordering. Acceptable for a transient board glance; not OK for
a multi-day calendar where the user is expected to recognize a color over
time.

- Add `Job.accent_color = CharField(max_length=7, null=True, blank=True)`.
- On `Job.save()` when `accent_color is None`, pick the least-used color from
  the existing 8-color palette (`BoardService.ACCENT_COLORS`) among Jobs
  currently in `submitted`, `approved`, or `in_progress` status. Ties broken
  by palette order.
- Persisted forever. Race conditions tolerated (an 8-color palette with
  occasional doubles is fine).
- Data migration backfills colors for all existing Jobs in PK order, using the
  same least-used heuristic against the live state at backfill time.
- `BoardService` and `ScheduleService` both read `job.accent_color`. The
  round-robin assignment in `BoardService.get_approved_data` is removed.

### 2.3 New Configuration keys

Added to `apps.core.Configuration` (existing string KV pattern). Lazy
defaults written on first read, matching the pattern in
`apps/core/services.py` (`email_retention_days`, etc.).

| Key | Default | Type |
|---|---|---|
| `schedule_workday_start` | `"08:00"` | `HH:MM` |
| `schedule_workday_end` | `"17:00"` | `HH:MM` |
| `schedule_lunch_start` | `"12:00"` | `HH:MM` |
| `schedule_lunch_length_minutes` | `"60"` | string-encoded int |
| `schedule_task_buffer_minutes` | `"10"` | string-encoded int |
| `schedule_horizon_days` | `"3"` | string-encoded int (1–14 effective range) |

A Settings UI section ("Schedule") in `SettingsPage.svelte` writes these via
the existing `/api/settings/` endpoint. Validation: HH:MM keys must parse to
times within the day; `workday_start < lunch_start`, `lunch_end < workday_end`
where `lunch_end = lunch_start + lunch_length_minutes`; buffer and lunch
length must be non-negative ints; horizon clamped to 1..14.

---

## 3. New app: `apps.schedule`

Follows the pattern of `apps.search` — a model-less, service-only Django app.

```
apps/schedule/
  __init__.py
  apps.py                  # ScheduleConfig
  services.py              # ScheduleService — the cascading algorithm
  calendar_arithmetic.py   # pure functions (no Django imports beyond utils)
  tests/
    __init__.py
    test_calendar_arithmetic.py
    test_schedule_service.py
```

`apps.api.schedule/` for the HTTP layer (matches `apps.api.jobs/`):

```
apps/api/schedule/
  __init__.py
  views.py                 # GET /api/schedule/
  tests.py
```

Registered in `INSTALLED_APPS` after `apps.jobs`. Wired into
`apps/api/urls.py` as `path('schedule/', schedule_view, name='api-schedule')`
and listed in `api_root()`.

---

## 4. Schedule algorithm

### 4.1 Inputs

- `now: datetime` (timezone-aware) — defaults to `django.utils.timezone.now()`.
- `horizon_days: int` — defaults to `Configuration['schedule_horizon_days']`,
  clamped to 1..14.
- Day shape (from Configuration): `workday_start`, `workday_end`,
  `lunch_start`, `lunch_end`, `task_buffer_minutes`.
- Non-working days: hardcoded weekend pattern (Sat=5, Sun=6 per Python's
  `date.weekday()`). Encapsulated so a future holiday list slots in.

### 4.2 Horizon window

- `horizon_start` = midnight at the start of `now.date()` (local time).
- `horizon_end` = `horizon_start + timedelta(days=horizon_days)`.
- `days` list returned in payload: one entry per day in `[horizon_start, horizon_end)`
  with `date`, `label`, `is_working` (False for Sat/Sun in v1).

### 4.3 Worker selection

Include every active `User` who has at least one Task that is either:

- assigned to them with status in `{pending, in_progress, blocked}`, OR
- assigned to them with status `complete` AND has at least one Blep whose
  `end_time` falls on `today` (local).

Order workers by `first_name, last_name` (matches `BoardService` convention).

### 4.4 Per-worker bar emission

Pull the worker's relevant tasks in (`worker_queue`, `pk`) order. Walk the
queue, maintaining a `cursor: datetime` initialized to
`max(now, workday_start_today)`.

For each task, emit zero or more bars and advance the cursor.

A "bar" is the unit the frontend renders. Each bar has:

```python
{
    'task_id': int,
    'job_id': int,
    'name': str,
    'status': str,
    'accent_color': str,           # from Job.accent_color
    'est_minutes': int,            # total est_worker_time in minutes
    'elapsed_minutes': int,        # total elapsed bleps in minutes (excl. lunch)
    'is_running': bool,            # is there a currently-open Blep
    'kind': 'historical' | 'active' | 'forecast' | 'parked',
    'segments': [
        {
            'start': iso8601,
            'end': iso8601,
            'est_fill_to': iso8601 | None,    # x where light layer ends in this segment
            'actual_fill_to': iso8601 | None, # x where dark layer ends in this segment
            'continues_left': bool,
            'continues_right': bool,
        }, ...
    ],
}
```

`kind` semantics:

| `kind` | Source | Layers |
|---|---|---|
| `historical` | A contiguous group of past bleps (any task with bleps in the past) | Dark (and light coextensive for completed) |
| `active` | The current contiguous work session of an in-progress task | Light + dark layered, both anchored at first blep of the session |
| `forecast` | The projected future slot for a pending/in-progress task | Light only |
| `parked` | A blocked task's placeholder next to the current task | Distinctive marker (small, hatched) |

### 4.5 Emission rules by task status

**Pending / Blocked / In-progress branches share these helpers:**

- `_emit_historical_bars(task)` — group bleps with `end_time <= now` and
  emit one `historical` bar per contiguous group (gap threshold = 1 minute;
  finer grouping is YAGNI for v1).
- `_emit_active_bar(task, anchor_start, est_remaining, elapsed_so_far_in_session)` —
  one `active` bar anchored at `anchor_start`. Light layer extends
  `est_worker_time` of work time from `anchor_start`. Dark layer extends
  `elapsed_so_far_in_session` of work time from `anchor_start`. Both walks
  skip lunch / overnight / non-working via `add_work_time`.

**Pending:**
- Emit one `forecast` bar starting at `cursor`, width = `est_worker_time`.
- Advance: `cursor = forecast_end + buffer`.

**Blocked:**
- Emit historical bars for any past bleps.
- Emit one `parked` bar with a fixed minimal width (e.g. 30 minutes of work
  time) starting at the worker's "parking anchor" (the next slot after their
  current active task, or `cursor` if none). Multiple blocked tasks stack
  side-by-side at the parking anchor in `worker_queue` order — but they do
  not consume cursor time.
- Cursor unchanged.

**In-progress with bleps:**
- Emit historical bars for past blep groups that are not the current session
  (i.e., contiguous-with-now is treated as the active session).
- Identify the "current session": the most recent contiguous blep group that
  either has an open blep (`end_time IS NULL`) or whose latest `end_time` is
  within a small window of `now` (1 minute). If no such group, treat the
  most recent blep group as already closed (still emit an active bar but
  with `is_running=False`).
- Emit one `active` bar with `anchor_start = first blep of current session`,
  `elapsed_minutes` = total bleps across all sessions for this task,
  `est_minutes = est_worker_time`.
- Cursor advances to `max(active_light_end, active_dark_end) + buffer`,
  where:
  - `active_light_end` = `add_work_time(anchor_start, est_worker_time)`.
  - `active_dark_end` = `now` if running, else `last_blep.end_time`.

**In-progress without bleps (unusual but possible):**
- Treat as pending — emit one `forecast` bar, advance cursor by est + buffer.

**Completed today:**
- Emit one historical bar (or multiple if non-contiguous) spanning the bleps'
  actual wall-clock range. Light layer coextensive with dark within each
  segment (estimate is consumed by the actuals; bar ends at actual end so
  downstream tasks bump backwards).
- No cursor advance for historical bars — they are in the past.

### 4.6 Cascade discipline

- The cursor advances forward only — `cursor` is monotonic across the
  task list.
- After every cursor advance, normalize via `next_workable_moment(cursor)`
  which jumps past lunch / workday_end / non-working days as needed.
- The `parked` bars don't move the cursor; they're a visual annotation,
  not a scheduling slot.
- Bars whose segments fall partly or wholly past `horizon_end` are still
  returned. The renderer decides what to do with overhang (a future "+N more"
  indicator is out of scope).

### 4.7 Calendar arithmetic helpers

In `apps/schedule/calendar_arithmetic.py`. All pure functions; no Django
model imports. Accept a `DayShape` dataclass and a `non_working_days_in(start, end)`
callable for testability.

- `DayShape` — `workday_start: time`, `workday_end: time`,
  `lunch_start: time`, `lunch_end: time`, `task_buffer_minutes: int`.
- `is_working_day(d: date) -> bool` — Sat/Sun False in v1.
- `workday_start_on(d, shape) -> datetime` / `workday_end_on(d, shape)` /
  `lunch_window_on(d, shape) -> (datetime, datetime)`.
- `next_workable_moment(dt, shape, is_working_day) -> datetime` — advances
  past lunch / EOD / weekend if `dt` lands in one.
- `add_work_time(start, work_duration, shape, is_working_day) -> datetime` —
  adds `work_duration` of *work time* (skipping lunch / overnight / weekend)
  to `start`. The pivotal helper. Returns the wall-clock time at the end.
- `segments_for(start, end, shape, is_working_day) -> list[(datetime, datetime)]` —
  splits the wall-clock interval `[start, end]` at every lunch / overnight /
  non-working boundary, returning the list of work-time-bearing sub-intervals.
- `work_minutes_between(a, b, shape, is_working_day) -> int` — counts
  work-time minutes between two datetimes (for computing elapsed-in-session
  and similar).

These are exhaustively unit-tested. The service code stays declarative on
top of them.

### 4.8 Edge cases

- **In-progress task whose first blep was before today.** Visual `active`
  bar starts at `workday_start_today` with `continues_left=True` on the
  first segment. `elapsed_minutes` reflects total elapsed across all bleps.
  Light layer extends `est_worker_time` from the visual start (not from the
  true first-blep time). This loses fidelity for the off-screen history but
  keeps the visible math coherent. Acceptable for v1.
- **Bar extends past `workday_end` (overrun into evening).** Segments may
  have `end > workday_end_on(date)`. Renderer overflows the panel boundary
  visually rather than clipping.
- **Concurrent blep on the same task across users.** Should not occur per
  current Blep semantics, but if encountered, sum elapsed across all bleps
  on the task — assignment is what matters for the queue.
- **`est_worker_time = 0`.** Should not occur (assigned tasks require a
  non-zero estimate per `Task.clean()`). If encountered, emit a zero-width
  forecast (probably degenerate but coherent).

---

## 5. API

### 5.1 Endpoint

```
GET /api/schedule/?days=<int>
Permission: IsAuthenticated
```

`days` query parameter is optional; if omitted, `schedule_horizon_days` from
Configuration is used. Clamped to 1..14.

### 5.2 Response envelope

```json
{
  "now": "2026-05-19T14:23:00-07:00",
  "horizon_start": "2026-05-19T00:00:00-07:00",
  "horizon_end": "2026-05-22T00:00:00-07:00",
  "horizon_days": 3,
  "day_shape": {
    "workday_start": "08:00",
    "workday_end":   "17:00",
    "lunch_start":   "12:00",
    "lunch_end":     "13:00",
    "task_buffer_minutes": 10
  },
  "days": [
    { "date": "2026-05-19", "is_working": true,  "label": "Mon · May 19" },
    { "date": "2026-05-20", "is_working": true,  "label": "Tue · May 20" },
    { "date": "2026-05-21", "is_working": true,  "label": "Wed · May 21" }
  ],
  "jobs": [
    { "job_id": 110, "job_number": "JOB-2025-0110", "name": "Smith fence",
      "accent_color": "#dc2626", "contact_name": "Smith",
      "due_date": "2026-05-25" }
  ],
  "workers": [
    {
      "user": { "id": 5, "name": "Riley Park", "initials": "RP" },
      "bars": [
        {
          "task_id": 521, "job_id": 110, "name": "J-110 large fab",
          "status": "in_progress", "accent_color": "#dc2626",
          "est_minutes": 480, "elapsed_minutes": 540, "is_running": true,
          "kind": "active",
          "segments": [
            { "start": "...T08:00:00", "end": "...T12:00:00",
              "est_fill_to": "...T12:00:00", "actual_fill_to": "...T12:00:00",
              "continues_left": false, "continues_right": true },
            { "start": "...T13:00:00", "end": "...T17:00:00",
              "est_fill_to": "...T16:00:00", "actual_fill_to": "...T17:00:00",
              "continues_left": true, "continues_right": true }
          ]
        }
      ]
    }
  ]
}
```

### 5.3 Drag / reorder

Reuses `POST /api/tasks/reorder/` from `apps/api/jobs/board_views.py`:

```
POST /api/tasks/reorder/
Body: { "task_ids": [3, 1, 2] }
```

After a successful reorder, the SPA refetches `/api/schedule/`.

---

## 6. Frontend

### 6.1 Files

```
frontend/src/routes/schedule/
  SchedulePage.svelte

frontend/src/components/schedule/
  ScheduleHeader.svelte    # day labels across the top
  WorkerLane.svelte        # one worker row (avatar + bars)
  TaskBar.svelte           # one bar (kind = historical/active/forecast/parked)
  NowLine.svelte           # vertical absolute line, full chart height

frontend/src/stores/
  schedule.js              # data + auto-refresh + reorder action
```

`SchedulePage` reuses `frontend/src/components/board/JobChipStrip.svelte`
as-is at the top. The global `Sidebar.svelte` (already mounted in
`App.svelte`) gets a new `<a href="/schedule" use:link>Schedule</a>` link,
placed immediately after the Jobs link. Visible to all authenticated users.

### 6.2 Routing

Add to `frontend/src/App.svelte`:

```js
'/schedule': SchedulePage,
```

### 6.3 Store

`frontend/src/stores/schedule.js` exports:

- `schedule` — writable; initial value `null` (loading).
- `loadSchedule(days?)` — fetches `/api/schedule/?days=<days>`, sets store.
- `reorderTasksInLane(workerId, newOrderedTaskIds)` — POSTs to
  `/api/tasks/reorder/`, then `loadSchedule()`.
- `startAutoRefresh()` / `stopAutoRefresh()` — `setInterval(loadSchedule, 5*60*1000)`.

`SchedulePage` calls `loadSchedule()` and `startAutoRefresh()` on mount,
`stopAutoRefresh()` on destroy.

### 6.4 Layout math (pure client)

Measured via a `ResizeObserver` on the chart container:

```
container_width
lane_label_width = 90px              # left gutter for avatar + name
chart_width      = container_width - lane_label_width
nonworking_width = 12px              # per non-working day
working_days     = days.filter(is_working).length
nonworking_days  = days.length - working_days
panel_width_for_working_day = (chart_width - nonworking_days * nonworking_width)
                              / max(working_days, 1)
```

Within a working-day panel of width `W`:

```
time_to_x_within_panel(t) = (t - workday_start_minutes)
                          / (workday_end_minutes - workday_start_minutes) * W
```

A bar segment maps to an absolutely-positioned `<div>` with `left` and
`width` computed from the segment's `start` and `end`. The light and dark
layers are children of the segment, each with their own width derived from
`est_fill_to` / `actual_fill_to`.

### 6.5 Layered visual + zigzag

CSS classes in `TaskBar.svelte`:

```css
.zig-right { clip-path: polygon(
  0 0, 100% 0,
  calc(100% - 5px) 25%, 100% 50%,
  calc(100% - 5px) 75%, 100% 100%,
  0 100%); }
.zig-left  { clip-path: polygon(
  5px 0, 100% 0, 100% 100%, 5px 100%,
  0 75%, 5px 50%, 0 25%); }
.zig-both  { clip-path: polygon(
  5px 0, 100% 0, calc(100% - 5px) 25%, 100% 50%,
  calc(100% - 5px) 75%, 100% 100%, 5px 100%,
  0 75%, 5px 50%, 0 25%); }
```

Applied to the segment background and both layers. The light and dark colors
for a bar come from the bar's `accent_color`:

- Light: the accent_color directly.
- Dark: the accent_color blended toward black by ~30%, computed in JS.

`parked` bars use a single hatched fill in the accent color at half opacity,
no light/dark split, fixed minimum width. To avoid visual collision with
pending bars at the same x-position, parked bars render in a thin sub-strip
*below* the main task row within the worker's lane (the lane has a primary
band for `historical`/`active`/`forecast` and a smaller secondary band
underneath for `parked`). The secondary band only exists if the worker has
any parked tasks.

`historical` bars for completed tasks: light + dark coextensive, both at
half opacity (visibly dimmed to indicate done).

### 6.6 Now line

`NowLine.svelte` — a single absolutely-positioned `<div>` over the chart,
1px wide, full chart height. Position is `time_to_x_in_chart(now)`. A
`setInterval(updateNow, 60_000)` recomputes; the server's `now` (from the
schedule payload) seeds the clock, drifted forward by `Date.now()` between
payloads. If the drift between server-reported `now` and client clock
exceeds 2 minutes on a fetch, force a refetch (clock-skew safeguard).

### 6.7 Drag-to-reorder

HTML5 DnD, following `frontend/src/components/board/WorkerColumns.svelte`:

- Only `forecast` and `parked` bars are `draggable=true`.
- `dragstart` writes `task_id` into `dataTransfer`; sets local
  `draggingTaskId` state.
- `dragover` on the worker's lane finds the drop index by comparing the
  drop x-coordinate against the centers of existing forecast/parked bars
  in queue order.
- `drop` computes the new `task_ids` order for that worker (the worker's
  current task list, with the dragged task moved to the drop index) and
  calls `reorderTasksInLane()`. The cascade is recomputed server-side on
  the refetch.
- Drops onto a different worker's lane are rejected (no cross-lane drag).
- `historical` and `active` bars have `draggable=false` — pinned to actuals.

### 6.8 States

- Loading: `schedule === null` → "Loading schedule…" placeholder.
- Empty: workers list is empty → "No assigned work in the visible horizon."
- Error: `lib/api.js` red-overlay convention (consistent with other pages).

---

## 7. Settings UI

Add a "Schedule" section to `frontend/src/routes/SettingsPage.svelte`:

```
Work day start    [ 08:00 ]
Work day end      [ 17:00 ]
Lunch start       [ 12:00 ]
Lunch length      [ 60 ] minutes
Buffer between tasks [ 10 ] minutes
Default horizon   [ 3 ] days
                                      [ Save ]
```

Save dispatches to the existing `/api/settings/` endpoint, which writes
`Configuration` rows. No new endpoint required.

Validation (server-side, in the same Configuration save handler that handles
other keys):
- HH:MM times parse.
- `workday_start < lunch_start`, `lunch_end < workday_end`.
- `lunch_length_minutes >= 0`, `task_buffer_minutes >= 0`.
- `horizon_days ∈ [1, 14]`.

---

## 8. Testing strategy

Test-Driven per CLAUDE.md. Write tests first; verify they fail; implement.

### 8.1 Calendar arithmetic — `apps/schedule/tests/test_calendar_arithmetic.py`

Each helper gets focused tests:

- `is_working_day` — Mon..Fri True, Sat/Sun False.
- `workday_start_on` / `workday_end_on` / `lunch_window_on` — given a date,
  return the right datetime in the local zone.
- `next_workable_moment` — input mid-morning → unchanged; input during lunch
  → returns lunch_end; input after workday_end → next working day's
  workday_start; input on Saturday → Monday's workday_start.
- `add_work_time` — wide table of cases:
  - Fits within a single workday morning.
  - Crosses lunch only.
  - Crosses overnight only.
  - Crosses both lunch and overnight (one full day worked).
  - Crosses a weekend.
  - Starts during lunch (clamped to lunch_end).
  - Starts after workday_end (clamped to next day's workday_start).
  - Starts before workday_start (clamped to workday_start).
  - Zero duration (returns input clamped to next workable).
  - Multi-day span (e.g., 20 hours of work).
- `segments_for` — same matrix. Output must be contiguous, non-overlapping,
  in chronological order, each segment within a single workday.
- `work_minutes_between` — sanity checks.

### 8.2 ScheduleService — `apps/schedule/tests/test_schedule_service.py`

Integration against the test DB. Use `BaseTestCase` / `FixtureTestCase`
where appropriate. Each scenario seeds tasks + bleps + Configuration and
asserts on the emitted bars.

Scenarios:

1. Empty world → empty `workers`.
2. One pending task, default config → one `forecast` bar starting at "now"
   (or workday_start if before-hours), single segment if it fits in today.
3. Pending task that crosses lunch → two segments, `continues_right=True`
   on first, `continues_left=True` on second.
4. Pending task that crosses overnight → segments on day 1 and day 2.
5. Pending task that crosses a weekend → segments on Fri and Mon.
6. In-progress task with one running blep → one `active` bar with light +
   dark layers, `is_running=True`, `elapsed_minutes > 0`.
7. In-progress task at exactly its estimate → dark and light coextensive.
8. In-progress task running long (overrun) → dark extends past light;
   cascade pushes next task later.
9. Completed-today task that finished early → one historical bar; next
   task in queue starts at the actual end (earlier than est_end).
10. Blocked task with no prior bleps → one `parked` bar; downstream
    pending tasks cascade without delay.
11. Blocked task with prior bleps → historical bars in past slots + one
    `parked` bar.
12. Non-contiguous bleps on one task → multiple `historical` bars.
13. Multiple workers with interleaved tasks.
14. Yesterday's completed task is excluded.
15. In-progress task started before today → `active` bar's first segment
    has `continues_left=True`, visual start = today's `workday_start`.
16. Task whose segments all fall past `horizon_end` → still returned.
17. `?days=` parameter respected; clamped to [1, 14].

### 8.3 API — `apps/api/schedule/tests.py`

- Unauthenticated GET → 401.
- Authenticated GET → 200, expected envelope keys present.
- `?days=2` → `horizon_days == 2`.
- `?days=99` → clamped to 14.
- `?days=0` → clamped to 1.
- Smoke: render a small but non-trivial schedule end-to-end.

### 8.4 Job color — `apps/jobs/tests/test_accent_color.py`

- Fresh Job on first save gets a non-null `accent_color` from the palette.
- Save of an existing Job with a color preserves it.
- Backfill data migration assigns colors deterministically given a seed
  state.
- `BoardService` reads `Job.accent_color` (no longer round-robin).

### 8.5 Frontend

Manual QA. The codebase has no Svelte test infrastructure. Test plan in
`docs/plans/2026-05-19-schedule-view-implementation.md` lists scenarios to
walk through.

### 8.6 Test-running discipline

Per CLAUDE.md, only one agent may run `python manage.py test` at a time
against the shared MySQL test database. This work is single-threaded.

---

## 9. Rollout / phasing

Sequenced. Phases may run in parallel only where explicitly noted.

| Phase | Work | Depends on |
|---|---|---|
| 0 | App skeletons (`apps/schedule/`, `apps/api/schedule/`), `INSTALLED_APPS` and `api/urls.py` wiring, lazy Configuration defaults in a helper module. | — |
| 1 | `Job.accent_color` model field + `makemigrations` migration + data migration backfilling existing Jobs. `BoardService.get_approved_data` / `get_board_data` updated to read `Job.accent_color`. Tests. | 0 |
| 2 | `calendar_arithmetic.py` + tests. | 0 |
| 3 | `ScheduleService` + tests. | 1, 2 |
| 4 | `GET /api/schedule/` + view tests. Register in `apps/api/urls.py` and `api_root`. | 3 |
| 5 | Frontend store + skeleton page (renders raw JSON for verification). Add route in `App.svelte`. Add Sidebar link. | 4 |
| 6 | Components: ScheduleHeader, WorkerLane, TaskBar (light/dark layers + zigzag clip-paths), NowLine. Layout math. Reuse JobChipStrip. | 5 |
| 7 | Drag-to-reorder wiring. | 6 |
| 8 | Settings UI: "Schedule" section in `SettingsPage.svelte`. Validation. | 4 |
| 9 | Manual QA across seeded scenarios. Doc updates: add `apps.schedule` row to CLAUDE.md's apps table. | 6, 7, 8 |

Phases 2 and 8 can be done in parallel with phase 1 if convenient.

**Rollout posture.** Minibini is pre-production; no feature flag. The new
view is additive (new route, new app, additive migration). If anything
breaks, the existing board is untouched.

**DB writes constraint.** Per CLAUDE.md, the implementer never runs
`python manage.py migrate`. `makemigrations` produces the migration files;
the human user runs `migrate`. Tests use their own test database.

---

## 10. Future work (out of scope; tracked as carry-forwards)

- **Mid-stream estimate adjust** — a UI affordance to bump `est_worker_time`
  on an in-progress task without restarting time tracking. The schedule
  algorithm already handles changes in `est_worker_time`; only the UI is
  missing.
- **Configurable weekend / holiday list** — replace the hardcoded Sat/Sun
  with a Configuration-driven list of dates and a weekly pattern.
- **Per-worker schedule overrides** — User fields for personal workday
  start/end (part-timers, early starts).
- **User-pickable job colors** — currently admin-only.
- **Add-worker / cross-lane reassignment from the schedule** — purposely
  excluded from v1.
- **Pin-to-specific-time drag** — calendar-style scheduling instead of
  queue-position scheduling.
- **"+N more" off-horizon indicator** — when a worker's queue extends past
  the visible horizon.
- **Sub-minute "now" line tick** — animate the now line every second
  instead of every minute, for higher visual fidelity.
