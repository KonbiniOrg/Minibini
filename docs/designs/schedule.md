# Schedule view

The `#/schedule` page visualizes each worker's assigned work on a time-axis
calendar over a rolling N-day horizon. Past work renders as dark `actual` bars
straight from the bleps; future work as light `forecast` bars sized by
`est_worker_time` — the two split at a live "now" line. Drag-to-reorder
rearranges a worker's queue (the forecast bars) without reassigning.

Audience: shop manager (capacity planning) and workers (reading their own
row). All authenticated users can view; the drag is gated only by the
existing `/api/tasks/reorder/` permissioning.

The backend is `apps.schedule` — a model-less, service-only app (like
`apps.search`). `ScheduleService` (`apps/schedule/services.py`) builds the
layout from existing data; `calendar_arithmetic.py` holds the pure
envelope/work-time helpers. The HTTP layer is `apps/api/schedule/views.py`.

---

## 1. Inputs

The schedule owns no schema of its own. It reads:

- `Task.assignee`, `Task.worker_queue` (queue position, shared with the Job
  Board), `Task.est_worker_time` (required once a task has an assignee),
  `Task.status`.
- `Task.expected_worker_time()` — not the raw `est_worker_time` field —
  is what the schedule actually sizes bars from (see the note at the end
  of §3). For a subtask under a quantity structure this scales by the
  parent's `est_qty`; for every other task it equals the raw field.
  `Task.parent_task` — a task with ≥1 subtask (a **parent**, see
  `jobs-and-tasks.md` §4a) draws no bar of its own; its schedulable work
  lives entirely on its children.
- `Blep.start_time` / `Blep.end_time` — actuals; an open blep (`end_time IS
  NULL`) is the running session.
- `Job.status`, `Job.on_hold` — the work-driven scoping below.
- `User.schedule_envelope` — the worker's personal weekly envelope (§2).
- `Job.accent_color` — a stable per-job color (`CharField(7)`). On
  `Job.save()` an unset color is filled from `BoardService.ACCENT_COLORS`,
  picking the least-used color among active Jobs (ties by palette order).
  Persisted; the Board and the schedule both read it.

---

## 2. Weekly envelopes (the configurable work week)

A **weekly envelope** is 7 days, each an ordered list of non-overlapping
`[start, end)` intervals. Empty list = day off; one interval = a continuous
workday; gaps between intervals = breaks (lunches are not a special case,
and scheduled breaks are entirely optional — a shop that doesn't schedule
lunches just uses one interval per day). Canonical JSON:

```json
{"mon": [["08:00", "12:00"], ["12:30", "17:00"]],
 "tue": [["08:00", "17:00"]], "wed": [["08:00", "17:00"]],
 "thu": [["08:00", "17:00"]], "fri": [["08:00", "17:00"]],
 "sat": [], "sun": []}
```

Validation (`calendar_arithmetic.validate_week_envelope`, shared by every
write path): exactly the seven keys; zero-padded `HH:MM` (00:00–23:59);
`start < end`; strictly increasing across a day's boundaries — no overlap,
no zero length, no touching intervals (merge instead). All-days-off is
valid (such a worker simply never forecasts).

**Resolution — the only rule:** a worker uses their own envelope
(`User.schedule_envelope`, nullable JSONField; null = unset) if set, else
the shop's (`schedule_week_envelope` Configuration key). Malformed stored
JSON falls back to the shop default (logged, never a 500).

`WeekEnvelope` (frozen dataclass in `calendar_arithmetic.py`) is the parsed
form: a 7-tuple indexed by `date.weekday()`, each a tuple of `(time, time)`
pairs, with `from_json` / `to_json` / `intervals_on(date)` /
`is_working_day(date)`.

### Configuration

Lazy string KV in `apps.core.Configuration` (defaults written on first read):

| Key | Default |
|---|---|
| `schedule_week_envelope` | Mon–Fri `08:00–17:00`, weekend off (JSON) |
| `schedule_task_buffer_minutes` | `10` |
| `schedule_horizon_days` | `3` (clamped 1–14) |

(The former `schedule_workday_start` / `schedule_workday_end` keys are
retired — the envelope replaces them.) The Settings → Schedule section
edits these via `/api/settings/` (envelope validated there; stored as a
JSON string; accepted as dict or string on PATCH).

### Editing surfaces

One Svelte component — `components/schedule/EnvelopeEditor.svelte`
(controlled; seven day rows, add/remove intervals, "Day off" state, and for
user envelopes a "Using the shop schedule" / Customize / "Use shop default"
affordance) — mounted three ways:

| Surface | Who | Route |
|---|---|---|
| Settings → Schedule (shop week) | `can_manage_config` | `PATCH /api/settings/` (`schedule_week_envelope`) |
| Home → Shifts tab, top (`MyEnvelopeEditor`) | any authenticated user, self | `PUT /api/auth/me/schedule-envelope/` (`{"schedule_envelope": {...}\|null}`, null = reset) |
| Users → user profile page | `can_manage_time` **or** `can_manage_config` | `PUT /api/users/{id}/schedule-envelope/` |

Saves are explicit (Save buttons; the editor only reports changes). The
admin envelope action is the ONE user-admin route open to time managers —
the rest of `/api/users/` stays `can_manage_config`.

---

## 3. The cascade algorithm

`ScheduleService.get_schedule(now, horizon_days, offset)`:

**Window.** `horizon_start` is midnight of the working day at `offset`
working days from today (`offset` drives past/future scrolling); the window
spans `horizon_days` WORKING days. Working-day counting and offset stepping
use the **shop** envelope's calendar (deterministic for everyone). A day the
shop skips still renders full-width when any displayed worker works it
(`days[].is_working` = shop works it OR any displayed worker does); other
non-working days render as thin strips. A 31-day span cap bounds long
non-working stretches.

**Workers.** Every active `User` with at least one of: a **planned** task
(below); a `complete` task with a blep ending in the window; or an open /
in-window blep. Ordered by name.

**Planned vs. history scope (work-driven).** "Planned" work — what cascades
into forecast bars — is assigned `pending`/`in_progress` tasks on **unheld
work-active jobs**: `in_progress` ∪ pre-approval (`draft`/`submitted`).
Assignment is the deliberate act that puts quote-stage work-ahead (a site
visit, material research) on the schedule; such bars carry
`pre_approval: true` and render distinctly. `approved` stays excluded —
release-to-floor is the forecast gate. `blocked` is not planned (no ETA) and
a held job (`on_hold`) never forecasts. History — `actual` bars from logged
bleps — is unrestricted by job/task status **including held jobs**: past
work happened and renders; only the future is paused.

**Jobs (chip strip).** The `jobs` payload that feeds the top `JobChipStrip`
is the board's In Progress column payload, **verbatim** — both surfaces
consume `BoardService.strip_jobs_payload()` (see
`jobs-and-tasks.md`), which owns the set
(`in_progress_column_jobs()`: every `in_progress` job, held or not, plus
unheld pre-approval jobs with ≥1 assigned, still-planned task, by
`due_date`) AND the serialization (`sub_status`, `pre_approval` /
`on_hold` / `hold_reason`, `task_total` / `task_completed`, accent-color
fallback) — so board and schedule can't drift on membership, order, or
shape. The strip is broader than the lane bars in one direction (an
in_progress job with nothing scheduled still shows) and narrower in
another (a `work_complete` job drops off the strip while its completed
work still renders as `actual` bars). Lane bars are self-describing
(`job_number`/`job_name`/`accent_color` travel on the bar).

**Per-worker walk.** Tasks are walked in pure `(worker_queue, pk)` order —
exactly the job board's order — with each worker's own envelope driving
their cascade. Each task emits two kinds of bar, divided by the live
now-line:

| `kind` | Source | Colour |
|---|---|---|
| `actual` | one per contiguous blep session (immutable past); the session holding an open blep ends at `now` and is flagged `is_running` | dark (darkened accent) |
| `forecast` | the assignee's remaining estimate of unfinished **planned** work — full estimate if unstarted, `expected − logged` otherwise, floored at `MIN_FORECAST` (10 min) | light (accent) |

Actual pieces are wall-clock-anchored and `<= now`; forecasts cascade from a
`cursor` (queue order, floored at `now`) and are `>= now`, so no two bars in
a lane overlap. A non-assignee blepper shows only their own sessions.

**Segmentation — the planned/actual asymmetry:**

- **Forecast** segments split at every envelope boundary — overnights, days
  off, AND the gaps between a day's intervals (`segments_for`) — with
  `continues_left/right` flags driving the zigzag edges. Forecasts advance
  the cursor by `duration + buffer`.
- **Actual** segments split ONLY at local midnight and are never split or
  clipped by envelope gaps (`day_segments_clamped`) — logged work draws
  straight over a shaded break. The envelope is where work is *planned*,
  not a claim about where it happened.

**The axis & overnight compression (three rules):**

1. Days are columns of axis-hours only; overnight is always compressed to a
   boundary — there is never an hours-between-days band.
2. The axis (`axis.start`/`axis.end`) is the union of displayed workers'
   envelope hours across the visible days, widened (floor/ceil to the hour)
   for off-hours logged work *ending on its own start date* within the
   window (plus a running blep's estimate projection) — temporary and
   self-healing once the late session scrolls out.
3. Work the axis still doesn't cover (midnight-crossers, fully off-axis
   sessions) **clips at the axis edge** with the `continues_*` zigzag; the
   true duration is on the bar (`elapsed_minutes`). A fully-clipped or
   zero-width session renders a one-minute visibility sliver. No widening
   cap for now — add one only if rule 2 proves too generous in practice.

The pure math lives in `calendar_arithmetic.py` over `WeekEnvelope`:
`next_workable_moment`, `add_work_time`, `segments_for`,
`work_minutes_between`, `is_working_day`, `shift_working_days`,
`day_segments_clamped`.

**Quantity structures (task-owned-money Phase 4).** Every place this
service used to read `task.est_worker_time` directly — the running-blep
remaining-time projection, the per-worker remaining-time calc, and each
forecast bar's `est_minutes` — reads `task.expected_worker_time()`
instead (`jobs-and-tasks.md` §4a.2): a flag-`True` subtask's bar is
sized by its own per-unit estimate × its parent's `est_qty`, not the
raw per-unit number. A **parent task draws no bar at all**: `_build_lane`'s
task queryset excludes any task with subtasks
(`.exclude(Exists(Task.objects.filter(parent_task_id=OuterRef('pk'))))`)
at the query level, not just via the `assign()` guard that normally
keeps a parent from acquiring `worker_queue`/assignee state in the
first place — a task can become a parent (gain its first subtask)
*after* it already carried planning state from before it had children,
and the query-level exclusion covers that case too. Every queryset that
feeds `expected_worker_time()`/`expected_qty()` (`window_bleps` and
`_build_lane`'s `tasks_qs`) carries `select_related('parent_task')`, so
a lane with several same-parent subtasks costs one JOIN, not one query
per sibling.

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
  "axis": { "start": "07:00", "end": "18:00", "task_buffer_minutes": 10 },
  "days":    [ { "date": "…", "is_working": true, "label": "Mon · May 19" } ],
  "jobs":    [ { "job_id": 110, "name": "…", "accent_color": "#dc2626",
                 "pre_approval": false, "on_hold": false, "hold_reason": "",
                 "task_total": 4, "task_completed": 1,
                 "project_manager_name": "…", … } ],
  "workers": [ { "user": { "id": 5, "name": "…", "initials": "RP" },
                 "envelope_by_day": [ [["08:00","12:00"],["12:30","17:00"]], … ],
                 "bars": [ { "task_id": …, "kind": "actual",
                             "pre_approval": false, "is_running": true,
                             "segments": [ … ] } ] } ]
}
```

`axis` is the page display axis (rule 2 above). `envelope_by_day` is the
lane's resolved working intervals per visible day, parallel to `days[]` —
it drives the per-lane shading. Reordering reuses `POST /api/tasks/reorder/`
(`{"task_ids": [...]}`); the SPA refetches after a successful reorder.

Envelope editing endpoints are in §2.

---

## 5. Frontend

`frontend/src/routes/schedule/SchedulePage.svelte` plus
`frontend/src/components/schedule/` (`ScheduleHeader`, `WorkerLane`,
`TaskBar`, `NowLine`, `TaskQuickCard`, `EnvelopeEditor`) and the
`stores/schedule.js` store (load + 5-minute auto-refresh + reorder). The
Board's `JobChipStrip` is reused at the top.

- **Header bar** (`ScheduleHeader`): a persistent **Today** button sits in the
  left corner above the lane-name column (disabled when already on today);
  the ‹ / › day-scroll arrows are paired at the far-right end; day labels are
  centered in their columns. The top toolbar holds only the title and the
  working-days control.
- **Layout math** (client): each working day gets an equal panel; the panel
  time axis maps from the payload `axis`. A segment maps to an
  absolutely-positioned div, filled with one solid colour by kind
  (`forecast` bright accent, `actual` darkened). Zigzag edges via `clip-path`
  on segments flagged `continues_left/right` (which now also mark axis
  clipping). `actual` bars recede slightly; the running session keeps full
  opacity with a bright ring. A `pre_approval` **forecast** bar gets a
  dashed outline; a pre-approval job's `actual` bars render plain — logged
  past work is immutable fact whatever the job's current status.
- **Per-lane shading**: each `WorkerLane` shades its OWN off-envelope
  regions from `envelope_by_day` — the margins before/after that worker's
  hours, the gaps between their intervals, and whole panels on their days
  off — so a 7–3 worker and a 9–5 worker read correctly side by side.
  (There is no page-level off-hours band anymore.)
- **Now line** seeds from the payload `now` and ticks client-side each
  minute; hidden when "now" is off the scrolled window.
- **Drag-to-reorder**: `forecast` bars are draggable; a 3px grey drop
  indicator snaps to buffer midpoints and hides on a no-op move. Reorder
  writes `worker_queue` via `POST /api/tasks/reorder/`. No cross-lane drag.
- **Job focus**: clicking a chip toggles `focusedJobIds`, dimming
  non-focused jobs' bars. Chips show PM initials, a dashed outline + `quote`
  badge when `pre_approval`, grey diagonal bars + hold-reason hover when
  `on_hold`.
- **Clickable bars** open `TaskQuickCard` — task identity, live-blep banner,
  embedded `TaskActions`, reassign via `AssignModal`, and a link to the full
  task. For `can_manage_time` managers it also offers on-behalf
  "Start/Stop for «worker»" (gated server-side; see
  `jobs-and-tasks.md` §4.5/§5.2).

---

## 6. Future work

- **Holiday list** (shop-wide non-working dates layered on the envelope).
- **Effective-dated / alternating-week envelopes** — editing an envelope
  reflows from now; history is blep-driven and doesn't care.
- **Axis widening cap** — only if rule 2 (§3) proves too generous live.
- **Mid-stream estimate adjustment** — bump `est_worker_time` on a running
  task without restarting tracking (the algorithm already handles changed
  estimates; only the UI is missing).
- **User-pickable job colors** (currently admin-editable only).
- **Cross-lane drag (reassignment)** and **pin-to-specific-time drag**.
- **"+N more" off-horizon indicator** when a queue extends past the horizon.
- **Per-worker task buffers** — `schedule_task_buffer_minutes`
  deliberately stays a single shop-wide value for now.

Decided against (2026-07-05 hold-flag design): surfacing change-order
state on a held job's schedule chip. The hold-reason hover is the
signal; CO state lives on the job page.

---

## 7. Activity page (sibling service)

`apps.activity` is a second model-less, service-only app (same shape as
`apps.schedule` / `apps.search`). `ActivityService` (`apps/activity/services.py`)
builds the `#/activity` dashboard payload — who's currently on shift (with their
running blep), plus recent completed bleps and recent job / PO / invoice
transition events. It's read-only over existing models; the HTTP layer is
`apps/api/activity/views.py` serving `GET /api/activity/` (`IsAuthenticated`).

Unlike the schedule's *forward* horizon, the Activity page uses a single
*backward* look-back window, the `activity_recent_days` Configuration key
(integer ≥ 1, default 5; see `data-constraints.md` §1.1). `load_recent_days()`
reads it (read-only, never writes a default back), clamps to ≥ 1, and falls
back to 5 when missing/unparseable. The settings API rejects non-int and `< 1`.
Completed bleps reuse `BlepSerializer` so their shape matches `/api/bleps/`.
