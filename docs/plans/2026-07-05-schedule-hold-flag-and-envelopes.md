# Schedule work package: on-hold flag, work-driven surfaces, weekly envelopes

> **Status: spec, approved direction (2026-07-05).** Supersedes and retires
> `2026-06-29-schedule-pre-approval-work-followon.md` — its open questions are
> decided here. Implementation lands on `feature/schedule-again`.

Three connected pieces, built in phase order:

- **Phase 0 — `on_hold` becomes a flag**, not a status. Done first, across the
  whole codebase, because everything after it reads job status.
- **Phase 1 — work-driven surfaces**: assigned pre-approval work appears on the
  board's In Progress area, the schedule chip strip, and the worker lanes,
  visibly flagged; held jobs keep their surface.
- **Phase 2/3 — weekly envelopes**: the configurable work week and per-worker
  working hours/breaks, as one concept (shop default + per-worker override),
  with three editing surfaces.

Decisions recorded (from the retired doc's open questions):

1. **Pre-approval work on the board:** yes — via the shared In Progress set,
   only when a task is *already assigned and still planned*. The review meeting
   covers both areas: Pipeline answers "does this quote need work-ahead tasks?";
   In Progress reviews work that exists. No toggle.
2. **On-hold board placement:** a held job keeps its surface (the flag model
   makes this automatic — the underlying status never changes). It never
   promotes. Chip/card treatment: diagonal bars; `hold_reason` in hover text.
3. **On-hold variety display (CO state on the chip):** dropped. The hold reason
   hover is the signal; CO state lives on the job page.

---

## Phase 0 — `on_hold` is a flag, not a status

**Model.** Remove `Job.STATUS_ON_HOLD` from `JOB_STATUS_CHOICES` and from the
transition table. Add `Job.on_hold = BooleanField(default=False)`.
`hold_reason` stays as-is (required to hold, cleared on release). A held job
keeps its true status underneath — that status is what board/schedule/guards
read, with `on_hold` as an orthogonal overlay.

**Semantics (behavior-preserving except where noted):**

- **Hold** is allowed when `status in {approved, in_progress}` and not already
  held; requires a reason. **Release** clears the flag and reason; blocked
  while the job has an open or draft change order (today's on_hold exit guard,
  re-expressed).
- **While held:** task/material/fee mutations, blepping, and task status
  changes stay rejected (`_assert_job_not_on_hold` and the blep guard now check
  the flag). Job status transitions are blocked except **cancel** (today:
  on_hold → cancelled). Completing, releasing to floor, etc. require release
  first.
- **Change orders:** CO creation still requires the job to be held. CO
  **accept clears the hold** (then crystallizes, as today). ⚠ Behavior change:
  a job held from `in_progress` resumes `in_progress` directly on acceptance —
  today it lands in `approved` and needs a second release-to-floor. The old
  "accepted-awaiting-release" state becomes simply "not held anymore".
  Reject/expire still snapshot and leave the job held.
- **Cancel-while-held** clears the flag as part of the transition (a cancelled
  job is not "held"); reactivation from cancelled restores `in_progress`
  un-held, as today.

**API.** The jobs viewset gains explicit actions — `POST /api/jobs/{id}/hold`
(requires `reason`) and `POST /api/jobs/{id}/release` — with the same
permission as other job status actions (`CanManageJobOrPM`). `status: 'on_hold'`
stops being a valid PATCH/transition value. Serializers expose `on_hold` and
`hold_reason`.

**Sweep.** `grep -rn "on_hold\|ON_HOLD"` — the flag touches (at minimum):
`apps/jobs/models.py`, `apps/jobs/services.py` (guards, update_status, board
pipeline sets, loose-material release), `apps/estimates/change_order_service.py`,
`apps/deliverables/services.py`, `apps/api/portal/change_order_views.py`,
`apps/schedule/services.py`, the four SPA files (`JobDetail`, `JobHeader`,
`JobTaskListPage`, `TaskDetailPage`) plus board components, ~20 test modules,
fixtures, and the nealsdata generator (it emits held jobs for CO scenarios —
emit `status` + `on_hold`/`hold_reason` instead; run
`tests.test_neals_builders`). Migration: schema change + best-effort data
migration mapping any `status='on_hold'` row to `status='approved',
on_hold=True` (dev data is regenerable; test/CI DBs are fresh). Run the suite
**without `--keepdb`** after the migration lands.

**Board placement falls out:** Pipeline = `draft/submitted/approved` (held or
not, held shown with hold treatment); In Progress column = `in_progress` jobs
including held ones (diagonal-bars treatment). No `held_from_status` field
needed.

---

## Phase 1 — work-driven surfaces

**One shared set, extended.** `BoardService.in_progress_column_jobs()` becomes:

> all `in_progress` jobs (held or not), **plus** pre-approval jobs
> (`draft`/`submitted`, not held) having ≥ 1 task that is assigned **and**
> planned (`pending`/`in_progress`) — ordered by `due_date` as today.

Both the board's In Progress area and the schedule chip strip keep reading this
one helper, so the two surfaces cannot drift. Each job in the payload carries
`pre_approval` (status is draft/submitted) and `on_hold` flags.

- The **pre-approval trigger is self-limiting**: assignment is deliberate, and
  the job drops off both surfaces the moment its assigned tasks complete (its
  history bars remain in the lanes — bars are self-describing, same precedent
  as `work_complete` jobs). `approved` jobs stay excluded, preserving the
  existing rule that release-to-floor is the gate for forecasting approved work.
- On the **board**, a pre-approval job with assigned work appears in *both*
  areas: its Pipeline card is unchanged (it is still a quote to manage); its
  In Progress appearance is a work card with unmistakable pre-approval
  treatment — default: dashed accent border + a "quote" badge (visuals
  adjustable once seen live).
- **Schedule filters**: the three `job__status=IN_PROGRESS` filters in
  `ScheduleService` (worker set, planned set in `_build_lane`) broaden to the
  same definition: planned/forecast work = assigned planned tasks on
  (`in_progress` ∪ pre-approval) jobs, excluding held jobs. Bars gain a
  `pre_approval` flag rendered distinctly by `TaskBar`.
- **On-hold history renders.** The two `.exclude(job__status=ON_HOLD)` filters
  are removed — past work happened and shows as `actual` bars. A held job emits
  no forecasts (exactly like blocked tasks: actuals yes, forecast no). Its chip
  appears (with hold treatment) iff it's in the In Progress set.

---

## Phase 2 — weekly envelopes

**One concept.** A *weekly envelope* is 7 days, each an ordered list of
non-overlapping `[start, end)` intervals. Empty list = day off; one interval =
today's continuous workday; gaps = breaks (lunches are not a special case, and
scheduled breaks are entirely optional). Canonical JSON:

```json
{"mon": [["08:00", "12:00"], ["12:30", "17:00"]],
 "tue": [["08:00", "17:00"]], "wed": [["08:00", "17:00"]],
 "thu": [["08:00", "17:00"]], "fri": [["08:00", "17:00"]],
 "sat": [], "sun": []}
```

All seven keys required. Validation (shared server-side): `HH:MM` strings,
`start < end`, strictly increasing across each day's boundaries (no overlap,
no zero-length, no touching intervals — merge instead).

**Storage & resolution.**

- Shop default: one Configuration key **`schedule_week_envelope`**, lazily
  seeded on first read with Mon–Fri `08:00–17:00`, weekend off (today's
  defaults). The keys **`schedule_workday_start` / `schedule_workday_end` are
  deleted outright** — from `CONFIG_DEFAULTS`, the settings API validation
  (`apps/api/templates_config/views.py`), `ScheduleSettings.svelte`, tests, and
  `data-constraints.md` §1.1. No back-compat shim (preproduction).
  `schedule_task_buffer_minutes` and `schedule_horizon_days` are unchanged.
- Per-worker override: `User.schedule_envelope` (nullable JSONField); `null` =
  "uses shop default". Resolution rule, the only rule: **a worker uses their
  own envelope if set, else the shop's.**

**Calendar arithmetic generalizes.** `DayShape(start, end, buffer)` is replaced
by an envelope type in `calendar_arithmetic.py`; `next_workable_moment`,
`add_work_time`, `segments_for`, `work_minutes_between`, `is_working_day`,
`shift_working_days` walk per-day interval lists instead of one block.
`task_buffer_minutes` travels separately (it stays global). The hardcoded
Mon–Fri `is_working_day` disappears — a working day is a day with intervals.

**Cascade & rendering rules:**

- The forecast cascade runs **per worker with that worker's envelope**; cursor
  semantics, `MIN_FORECAST`, and buffer behavior are unchanged.
- **Forecast bars split at envelope gaps** using the existing
  `continues_left/right` zigzag mechanism (same as overnight splits).
- **Actual bars are never clipped or split by envelope gaps** — logged work
  draws over a shaded break. Actuals split only at day boundaries. The
  envelope is where work is *planned*, not a claim about where it happened.
- **Day columns and `offset` scrolling step by the shop envelope's calendar**
  (deterministic for everyone). A day column renders full-width if the shop
  *or any displayed worker* works it (a Saturday worker gets a real Saturday
  column); thin non-working strip otherwise.
- **The page time axis** spans the union of displayed workers' envelope hours
  across the visible days, further widened by the existing off-hours blep rule
  (floor/ceil to the hour, midnight guards unchanged). Each lane shades its
  *own* off-envelope regions — margins and gaps — so a 7–3 worker and a 9–5
  worker read correctly side by side.
- `_elapsed_worktime` (remaining-estimate math) uses the worker's envelope,
  matching today's config-shape behavior.

**API payload changes** (`GET /api/schedule/`):

- `day_shape` becomes a page-level `axis` (`start`, `end`, `task_buffer_minutes`).
- Each worker lane gains `envelope`: the resolved per-visible-day interval
  lists (concrete datetimes), driving the lane's shading.
- Bars gain `pre_approval` (Phase 1).
- `days[].is_working` follows the day-column rule above.

---

## Phase 3 — envelope editing (one component, three surfaces)

One Svelte **envelope editor** component: seven day rows; per day an interval
list with add/remove; explicit "day off" state; for user envelopes a
"using shop default" state with an explicit override/reset control. Saves are
explicit (Save button — never blur-only).

| Surface | Who | Route |
|---|---|---|
| Settings → Schedule | `can_manage_config` | existing `/api/settings/` mechanism (shop key, validated) |
| Home → Time section (bottom) | any authenticated user, self only | `PUT /api/auth/me/schedule-envelope` (body: envelope JSON or `null` to reset) |
| Users → user profile page | `can_manage_time` **or** `can_manage_config` | `PUT /api/users/{id}/schedule-envelope` |

The user-admin viewset stays `can_manage_config` for everything else; the
dedicated envelope endpoint carries the wider (time-or-config) gate so time
managers can plan schedules without full user-admin power. Validation errors
follow the standard contract (`{'schedule_envelope': ['msg']}`), rendered via
`triageError`.

---

## Phase 4 — nealsdata + docs

- `nealsdata/converter/build.py` `build_configuration` emits
  `schedule_week_envelope` matching the generator's synthetic workday
  (Mon–Fri `09:00–17:00`, per `_WORKDAY_START`/`_WORKDAY_END`), in the same
  manner as its other Configuration rows. (The on_hold emission fix belongs to
  Phase 0.) Any converter change runs `tests.test_neals_builders`.
- Docs updated in-session at the end: `docs/designs/schedule.md` (rewrite §2,
  §3, §6 to the envelope + work-driven model), `jobs-tasks-and-worksheets.md`
  (lifecycle: on_hold flag; board sets), `estimates-and-prices.md` /
  CO references (hold flag), `data-constraints.md` §1.1 (config keys) and Job
  field constraints, `users-and-permissions.md` (envelope endpoints).
- The superseded 2026-06-29 follow-on doc is deleted alongside this spec's
  commit; this spec itself is deleted from `docs/plans/` when the work
  completes.

---

## Testing

TDD throughout; backend suite runs fresh (no `--keepdb`) after each migration.

- **Phase 0:** rewrite `test_job_on_hold`, `test_api_on_hold_guards`,
  `test_blep_job_status_guard`, the CO suites, `test_board_service`,
  `test_api_jobs` to the flag model; the CO accept test asserts the underlying
  status resumes (including the in_progress auto-resume change).
- **Phase 1:** board/strip: pre-approval job with an assigned planned task is
  in the set (flagged), drops out when the task completes; held in_progress job
  stays in the set flagged `on_hold`. Schedule: pre-approval bar flagged; held
  job emits actuals but no forecasts; unassigned pre-approval task emits
  nothing.
- **Phase 2:** `test_calendar_arithmetic` extends to gaps/day-off/split-shift
  cases (cursor lands after a gap; `add_work_time` spans gaps; `segments_for`
  splits at gaps; day-off skipped like today's weekend). Service tests: two
  workers with different envelopes cascade independently; axis is the union;
  actual through a gap stays whole; Saturday worker produces a working Saturday
  column. Settings/serializer validation tests for the envelope JSON.
- **Frontend (Vitest):** envelope editor (add/remove/day-off/reset,
  validation display), lane gap shading, `TaskBar` pre-approval treatment, chip
  hold treatment, board card flags.

## Out of scope (unchanged Future Work)

Holiday lists; effective-dated / alternating-week envelopes (editing an
envelope reflows from now — history is blep-driven and doesn't care);
per-worker buffers; cross-lane drag; pin-to-time; user-pickable job colors;
mid-stream estimate adjustment UI.
