# Schedule Work Package Implementation Plan — on-hold flag, work-driven surfaces, weekly envelopes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/plans/2026-07-05-schedule-hold-flag-and-envelopes.md` — read it first; it is the contract. This plan is the build order.

**Goal:** Job on-hold becomes an orthogonal boolean flag; the board/schedule surfaces become work-driven (assigned pre-approval work shows, flagged); the schedule gains a configurable work week + per-worker weekly envelopes with three editing surfaces.

**Architecture:** Phase 0 removes `STATUS_ON_HOLD` from the state machine codebase-wide (flag + `hold_reason` overlay any status). Phase 1 extends the one shared board/strip set and the schedule filters. Phase 2 replaces `DayShape` with a `WeekEnvelope` (7 days × interval lists) in the pure `calendar_arithmetic` layer, one Configuration JSON key + a nullable per-User JSONField. Phase 3 is one Svelte envelope editor mounted on three surfaces. Phase 4 is nealsdata + docs.

**Tech Stack:** Django 5.2 / DRF, MySQL, Svelte 5 (runes), Vitest.

## Global Constraints

- Branch: **`feature/schedule-again`** — all commits land here. Never merge/push/PR; stop when done and report.
- **Never write to the dev DB** (no `manage.py migrate`/`shell`/`loaddata`/ORM writes outside tests). `makemigrations` is fine; tests build their own DB.
- After any migration change, run the backend suite **fresh — no `--keepdb`**.
- **Never judge tests by a piped exit code.** Run unpiped, or write output to a file and read the `OK`/`FAILED` summary + `Ran N tests` line.
- Only ONE agent may run `python manage.py test` at a time.
- Error contract: services raise `ValidationError({'field': ['msg']})` for field problems, `ValidationError('sentence')` otherwise; never emit `{'error': ...}`. DELETE returns 200+JSON. Frontend errors go through `triageError`.
- Frontend tests: `cd frontend && npm run test:run` (never watch mode).
- No `QuerySet.update()`/`bulk_*` on models whose `save()` has side effects; iterate and `save()`.
- Status values via model constants, never string literals (except in migrations/fixtures/SPA).
- nealsdata converter changes must run `python manage.py test tests.test_neals_builders`.
- Backend schedule tests live in `apps/schedule/tests/`; cross-app tests in `tests/`.
- Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

## Phase 0 — `on_hold` becomes a flag

### Task 1: Job model — flag field, transitions, migration

**Files:**
- Modify: `apps/jobs/models.py` (~51–193)
- Create: `apps/jobs/migrations/0054_*.py` (via `makemigrations`, then edit in a data step)
- Test: `tests/test_job_on_hold.py` (rewrite)

**Interfaces:**
- Produces: `Job.on_hold: BooleanField(default=False)`; `STATUS_ON_HOLD` constant and choice **deleted** (stragglers fail loudly); `VALID_TRANSITIONS` rows: `APPROVED → [IN_PROGRESS, CANCELLED]`, `IN_PROGRESS → [WORK_COMPLETE, CANCELLED]`, no ON_HOLD row; `Job.save()` clears `hold_reason` when `on_hold` flips True→False.

- [ ] **Step 1: Rewrite `tests/test_job_on_hold.py` as failing tests** for the flag model (model layer only; service semantics arrive in Task 2 — keep this file to what the model owns):

```python
class JobOnHoldFlagModelTests(BaseTestCase):
    def test_on_hold_defaults_false(self):
        job = self._make_job(status=Job.STATUS_APPROVED)
        self.assertFalse(job.on_hold)

    def test_status_on_hold_constant_gone(self):
        self.assertFalse(hasattr(Job, 'STATUS_ON_HOLD'))

    def test_on_hold_string_not_a_valid_status(self):
        job = self._make_job(status=Job.STATUS_APPROVED)
        job.status = 'on_hold'
        with self.assertRaises(ValidationError):
            job.save()

    def test_hold_reason_cleared_when_flag_drops(self):
        job = self._make_job(status=Job.STATUS_IN_PROGRESS)
        job.on_hold = True
        job.hold_reason = 'waiting on CO'
        job.save()
        job.on_hold = False
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.hold_reason, '')

    def test_held_job_keeps_underlying_status(self):
        job = self._make_job(status=Job.STATUS_IN_PROGRESS)
        job.on_hold = True
        job.hold_reason = 'x'
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)
        self.assertTrue(job.on_hold)
```

Use the existing file's job-construction helpers (read it before deleting; it currently tests approved→on_hold transitions etc. — those cases die with the status).

- [ ] **Step 2: Run to verify failure** — `python manage.py test tests.test_job_on_hold` → FAIL (no `on_hold` field).
- [ ] **Step 3: Implement.** In `apps/jobs/models.py`: delete `STATUS_ON_HOLD` (line ~55) and its choices entry (~66); add `on_hold = models.BooleanField(default=False)` next to `hold_reason` (~81); edit `VALID_TRANSITIONS` (~105–115): `APPROVED: [IN_PROGRESS, CANCELLED]`, `IN_PROGRESS: [WORK_COMPLETE, CANCELLED]`, delete the ON_HOLD row. In `save()` replace the leaving-on_hold clear (~181–184) with a flag-flip clear (the method already loads the old instance for `old_status`; capture `old.on_hold` the same way):

```python
if old is not None and old.on_hold and not self.on_hold:
    self.hold_reason = ''
```

- [ ] **Step 4: `python manage.py makemigrations jobs`** then append a data step to the generated migration (order: AddField `on_hold` → RunPython → AlterField `status`):

```python
def held_status_to_flag(apps, schema_editor):
    Job = apps.get_model('jobs', 'Job')
    for job in Job.objects.filter(status='on_hold'):
        job.status = 'approved'
        job.on_hold = True
        job.save(update_fields=['status', 'on_hold'])
```

(with `migrations.RunPython(held_status_to_flag, migrations.RunPython.noop)`).

- [ ] **Step 5: Run** `python manage.py test tests.test_job_on_hold` → PASS. (The wider suite is red until Task 5 — expected; do NOT chase it here.)
- [ ] **Step 6: Commit** `feat(jobs): on_hold becomes a flag — model + migration`.

### Task 2: JobService — hold/release, guards, board sub-status

**Files:**
- Modify: `apps/jobs/services.py` (guards ~109–130, `update_job` ~465–519, pipeline sets ~1486–1568, `compute_sub_status` ~1879–1893)
- Modify: `apps/schedule/services.py` (~150–158, ~397, ~406 — mechanical flag swap only in this task)
- Test: `tests/test_job_on_hold.py` (extend), `tests/test_job_pause_cancel_guard.py`, `tests/test_blep_job_status_guard.py`, `tests/test_on_hold_task_material_guard.py`, `tests/test_board_service.py` (update)

**Interfaces:**
- Produces: `JobService.hold_job(pk, reason) -> Job` — allowed iff `status in {APPROVED, IN_PROGRESS}`, not already held, non-blank reason, no open blep; sets flag+reason. `JobService.release_job(pk) -> Job` — requires held; raises while a DRAFT/OPEN ChangeOrder exists; clears flag (save clears reason). `update_job` raises `ValidationError('Job is on hold — release it before changing its status.')` for any status change while held **except** → CANCELLED (which runs the CO guard, then clears the flag as part of the transition). `_assert_job_not_on_hold` / `_assert_job_allows_blep` check `job.on_hold` (the blep guard gets an explicit `if job.on_hold: raise` — the allow-lists no longer cover it by omission).

- [ ] **Step 1: Write failing tests.** In `tests/test_job_on_hold.py` add a `JobHoldReleaseServiceTests` class: hold sets flag+reason and preserves status (from both approved and in_progress); hold rejected on draft/submitted/work_complete, on already-held, on blank reason, with an open blep; release clears flag+reason; release blocked while a DRAFT or OPEN CO exists (reuse the CO factory pattern from `tests/test_change_order_lifecycle.py`); `update_job(status=...)` on a held job → ValidationError, except cancel: cancel-on-held succeeds without live CO (job ends `cancelled`, `on_hold=False`) and raises with one. Update `test_job_pause_cancel_guard.py` (hold-with-open-blep moves to `hold_job`; cancel half unchanged), `test_blep_job_status_guard.py` (held in_progress job: start-work and create_historical both rejected with an on-hold message; the status allow-list cases keep passing minus the on_hold row), `test_on_hold_task_material_guard.py` (setup holds via `JobService.hold_job`), `test_board_service.py` (held-from-approved job appears in Pipeline with sub_status `'on-hold'`; held in_progress job appears in the In Progress column with sub_status `'on-hold'` — this is new, spec Decision 2).
- [ ] **Step 2: Run those five modules** → FAIL (no `hold_job`).
- [ ] **Step 3: Implement** in `apps/jobs/services.py`:

```python
@staticmethod
def hold_job(pk, reason):
    job = JobService.get_job(pk)
    if job.on_hold:
        raise ValidationError('Job is already on hold.')
    if job.status not in (Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS):
        raise ValidationError('Only an approved or in-progress job can be put on hold.')
    if not (reason or '').strip():
        raise ValidationError({'reason': ['A hold reason is required.']})
    if Blep.objects.filter(task__job=job, end_time__isnull=True).exists():
        raise ValidationError('Cannot pause the job while a worker has an open time entry.')
    job.on_hold = True
    job.hold_reason = reason.strip()
    job.save()
    return job

@staticmethod
def release_job(pk):
    job = JobService.get_job(pk)
    if not job.on_hold:
        raise ValidationError('Job is not on hold.')
    JobService._assert_no_live_change_order(job)
    job.on_hold = False
    job.save()
    return job
```

Extract the exit guard (~487–495) into `_assert_no_live_change_order(job)` and call it from `release_job` and from the cancel-while-held path. In `update_job`: drop the ON_HOLD halves of the pause guard (~480–485) and the old exit guard; add the while-held gate (status change + held + target ≠ CANCELLED → raise; target == CANCELLED → `_assert_no_live_change_order(job)` then set `on_hold=False` alongside the status). `_assert_job_not_on_hold` (~120–130): condition becomes `if job.on_hold:` (message unchanged). `_assert_job_allows_blep` (~109–117): add `if job.on_hold: raise ValidationError(f'Cannot {action}: the job is on hold.')` before the allow-list check; remove any on_hold mention from the lists. Board: pipeline filters (~1486–1489, ~1565–1568) drop the ON_HOLD member; `compute_sub_status` (~1879–1893): replace the status check with `if job.on_hold: return 'on-hold'` as the first branch. Schedule (`apps/schedule/services.py`): the three `.exclude(job__status=Job.STATUS_ON_HOLD)` → `.exclude(job__on_hold=True)`, and the two forecast/worker filters `job__status=Job.STATUS_IN_PROGRESS` gain `, job__on_hold=False` (behavior-preserving; Phase 1 revisits).

- [ ] **Step 4: Run the five modules + `apps.schedule.tests`** → PASS.
- [ ] **Step 5: Commit** `feat(jobs): hold/release service semantics for the on_hold flag`.

### Task 3: Change orders, portal, deliverables to the flag

**Files:**
- Modify: `apps/estimates/change_order_service.py` (~43–46, ~172–210), `apps/api/portal/change_order_views.py` (~32–40), `apps/deliverables/services.py` (~304–318), comments in `apps/estimates/co_acceptance.py` (~5–6, 60–61)
- Test: `tests/test_change_order_lifecycle.py`, `tests/test_change_order_request_changes.py`, `tests/test_portal_change_orders.py`, `tests/test_shipment_service.py`, plus the `_advance_job_to_on_hold` helpers in `tests/test_change_order_{api,send_api,deliverable_diff}.py`, `tests/test_mark_change_orders_expired.py`, `tests/test_estimate_is_amended.py`, `tests/test_change_order_acceptance.py`, `tests/test_change_order_pdf.py`, `tests/test_change_order_email.py`

**Interfaces:**
- Consumes: `JobService.hold_job` (Task 2).
- Produces: CO create guard reads `job.on_hold`; **accept clears the flag directly** (status stays whatever it was — the ⚠ behavior change: a job held from `in_progress` resumes `in_progress`); reject/expire/request-changes leave the job held; portal `_is_actionable` reads `co.job.on_hold`; shipment-create guard reads the flag.

- [ ] **Step 1: Update the test helpers first** — every `_advance_job_to_on_hold(job)` becomes advance-to-approved (or in_progress where the test says so) + `JobService.hold_job(job.pk, 'CO editing')`. Then write/adjust the failing assertions: create requires held; accept ends with `job.on_hold is False` and **status unchanged** (add a new case: held `in_progress` job + accept → still `in_progress`, un-held — the history entry payload becomes `{'on_hold': {'old': True, 'new': False}}`); reject/expire/request-changes leave `on_hold=True`; portal actionability keys off the flag; `test_create_blocked_when_job_is_on_hold` holds via the service.
- [ ] **Step 2: Run the CO/portal/shipment modules** → FAIL.
- [ ] **Step 3: Implement.** `create` (~43–46): `if not job.on_hold: raise ValidationError('A change order can only be created while the job is on hold.')`. `_handle_accepted` (~186–210): replace the `update_job(status=APPROVED)` call (~193–195) with a direct clear inside the existing transaction —

```python
job.refresh_from_db()
was_held = job.on_hold
if was_held:
    job.on_hold = False
    job.save()   # save() clears hold_reason
```

— keep the ordering comment (crystallization must run after the un-hold so `_assert_job_not_on_hold` passes); update the HistoryEntry `changes` payload to `{'on_hold': {'old': was_held, 'new': False}, '_action': 'Change order accepted'}`. Portal `_is_actionable` (~40): `co.job.on_hold`. Deliverables `_assert_job_not_on_hold` (~304–308): flag check. Fix the stale comments in `co_acceptance.py`.

- [ ] **Step 4: Run those modules** → PASS.
- [ ] **Step 5: Commit** `feat(estimates): change-order machinery reads the on_hold flag; accept clears it`.

### Task 4: API — hold/release actions + serializer exposure

**Files:**
- Modify: `apps/api/jobs/views.py` (~105–115), `apps/api/jobs/serializers.py` (~51–75)
- Test: `tests/test_api_jobs.py` (update on_hold PATCH cases → new actions), `tests/test_api_on_hold_guards.py` (setup via hold action)

**Interfaces:**
- Consumes: `JobService.hold_job/release_job`, `StatusTransitionMixin.status_actions` (auto-registers `POST /api/jobs/{id}/hold/` and `/release/`, writes the reason HistoryEntry).
- Produces: `JobSerializer` exposes `on_hold` + `hold_reason` (both read-only — writes only via the actions; this fixes the live gap where the SPA's `hold_reason` PATCH was silently dropped). `status: 'on_hold'` PATCH now 400s (invalid choice).

- [ ] **Step 1: Write failing tests** in `tests/test_api_jobs.py`: `POST /api/jobs/{id}/hold/` without reason → 400; with reason → 200, `on_hold=True`, `hold_reason` echoed in the response body, status unchanged; hold with open blep → 400; `POST .../release/` → 200, flag+reason cleared; release with live CO → 400; `PATCH {'status': 'on_hold'}` → 400; PATCH other fields on a held job still works, but `PATCH {'status': 'work_complete'}` on a held job → 400. Update `tests/test_api_on_hold_guards.py` setups to `POST .../hold/`.
- [ ] **Step 2: Run the two modules** → FAIL.
- [ ] **Step 3: Implement.** In `status_actions` (~105–115) add:

```python
'hold': {
    'service': lambda pk, reason=None: JobService.hold_job(pk, reason),
    'requires_reason': True,
},
'release': {
    'service': lambda pk, reason=None: JobService.release_job(pk),
},
```

In `JobSerializer`: add `'on_hold', 'hold_reason'` to `fields` and to `read_only_fields`. Check `JobSummarySerializer`/`JobSearchSerializer` — add `on_hold` where the board/search UI will need it (board payloads come from BoardService dicts; verify which serializer feeds the board and include the flag there).

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat(api): jobs hold/release actions; expose on_hold + hold_reason`.

### Task 5: Backend sweep — remaining tests, fixtures, full fresh run

**Files:**
- Modify: any remaining red tests/fixtures — `grep -rn "on_hold\|ON_HOLD" tests/ fixtures/ apps/` and clean every status-based use (`tests/test_api_schedule.py` `test_on_hold_job_task_worker_absent_from_schedule` becomes flag-based: held job's *forecast* absent — full history semantics change in Task 9, keep this minimal), `tests/test_api_history.py`, `tests/test_job_direct_tasks.py`, `tests/test_job_direct_materials.py`, inventory guard tests, etc.

- [ ] **Step 1:** Sweep and fix each reference (setup via `hold_job`/the hold action; assertions on `job.on_hold`).
- [ ] **Step 2:** Full fresh run: `python manage.py test 2>&1 | tee /tmp/claude-501/.../phase0.log` then **read the summary line** (`Ran N tests ... OK`). Migration changed → no `--keepdb`.
- [ ] **Step 3: Commit** `test: migrate on_hold status usage to the flag model`.

### Task 6: SPA — hold/release UI + flag reads

**Files:**
- Modify: `frontend/src/components/jobs/JobHeader.svelte` (~29–39, 66–93, 114, 168, 247), `frontend/src/components/jobs/JobDetail.svelte` (~529), `frontend/src/routes/jobs/TaskDetailPage.svelte` (~442), `frontend/src/routes/jobs/JobTaskListPage.svelte` (~514), `frontend/src/components/board/JobCard.svelte` (BORDER_COLORS ~4–16)
- Test: `frontend/tests/` — update affected suites; extend `JobCard.test.js`

**Interfaces:**
- Consumes: `POST /api/jobs/{id}/hold/` (`{reason}`), `POST /api/jobs/{id}/release/`; `job.on_hold` + `job.hold_reason` now present on job payloads; board `sub_status === 'on-hold'` still arrives (backend derives it from the flag).

- [ ] **Step 1: Write failing Vitest cases** (follow `ScheduleSettings.test.js` mock style): JobHeader shows a "Put on hold" button for approved/in_progress unheld jobs, which reveals the reason field and POSTs `/api/jobs/{id}/hold/` with `{reason}`; a held job shows the badge + reason + a "Release" button POSTing `.../release/`; the status `<select>` no longer offers On Hold. JobCard: `sub_status 'on-hold'` renders its border/banner treatment (extend the existing blocked-banner test pattern).
- [ ] **Step 2:** `cd frontend && npm run test:run` → new cases FAIL.
- [ ] **Step 3: Implement.** JobHeader: remove `on_hold` from `VALID_TRANSITIONS`/`STATUS_LABELS`; `confirmHold` → `api.post(`/api/jobs/${job.job_id}/hold/`, {reason: holdReason})`; add `releaseJob` → POST release; badge block keys off `job.on_hold` (independent of status); keep `.status-on_hold`-equivalent CSS as an `.on-hold` badge class. The three `job?.status === 'on_hold'` reads → `job?.on_hold`. JobCard: ensure `'on-hold'` has a BORDER_COLORS entry + a held banner mirroring the blocked one (grey, label "ON HOLD"). Reversibility: hold/release are exactly-undoable — **no confirm() dialogs**.
- [ ] **Step 4:** `npm run test:run` → PASS. **Step 5: Commit** `feat(spa): hold/release UI on the job header; flag-based on-hold reads`.

### Task 7: nealsdata — flag emission

**Files:**
- Modify: `nealsdata/converter/build.py` (~671 job fixture, ~2448 `_EARMARKED_JOB_STATUSES`)
- Test: `tests/test_neals_builders.py`

- [ ] **Step 1:** Job fixture emission adds `'on_hold': False` beside `'hold_reason': ''`; drop `'on_hold'` from `_EARMARKED_JOB_STATUSES` (held jobs stay earmarked via their real approved/in_progress status — orthogonal flag, no extra check needed). Update `test_neals_builders.py` expectations.
- [ ] **Step 2:** `python manage.py test tests.test_neals_builders` → PASS (read the summary line).
- [ ] **Step 3: Commit** `feat(nealsdata): emit on_hold flag on job fixtures`.

---

## Phase 1 — work-driven surfaces

### Task 8: BoardService — extended shared set + flags on payloads

**Files:**
- Modify: `apps/jobs/services.py` (`in_progress_column_jobs` ~1573–1595; the card-payload builder it feeds; `get_board_data`)
- Modify: `apps/schedule/services.py` (`jobs_payload` ~209–230)
- Test: `tests/test_board_service.py`, `apps/schedule/tests/test_schedule_service.py`

**Interfaces:**
- Produces: `in_progress_column_jobs()` = in_progress jobs (held or not) **plus** unheld draft/submitted jobs with ≥1 task where `assignee__isnull=False, status__in=[PENDING, IN_PROGRESS]`, distinct, `due_date` order. Board card dicts and the schedule `jobs_payload` both gain `'pre_approval': bool` (status in draft/submitted), `'on_hold': bool`, `'hold_reason': str`.

- [ ] **Step 1: Failing tests:** a draft job with an assigned pending task appears in the set flagged `pre_approval=True` (and STILL appears in the pipeline payload — both areas, spec §Phase 1); the same job drops out when the task completes; an unassigned draft job never enters; a held draft job never enters; a held in_progress job is in the set with `on_hold=True` + `hold_reason`; ordering stays due_date; schedule `jobs` payload carries the three new keys and the same membership (assert through `ScheduleService.get_schedule`).
- [ ] **Step 2:** Run both modules → FAIL.
- [ ] **Step 3: Implement:**

```python
qs = Job.objects.filter(
    Q(status=Job.STATUS_IN_PROGRESS)
    | Q(status__in=[Job.STATUS_DRAFT, Job.STATUS_SUBMITTED],
        on_hold=False,
        task__assignee__isnull=False,
        task__status__in=[Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS])
).distinct().order_by('due_date')
```

(then the existing UNPAID_SUB_STATUSES exclusion). Add the three keys wherever the helper's jobs are serialized (board card dicts + `jobs_payload`): `'pre_approval': j.status in (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED)`, `'on_hold': j.on_hold`, `'hold_reason': j.hold_reason`.

- [ ] **Step 4:** Run → PASS. **Step 5: Commit** `feat(board): shared In Progress set includes assigned pre-approval work; flags on payloads`.

### Task 9: ScheduleService — work-driven filters, on-hold history, pre_approval bars

**Files:**
- Modify: `apps/schedule/services.py` (worker set ~144–169, `_build_lane` planned/history sets ~387–406, `_build_bar` ~541–558)
- Test: `apps/schedule/tests/test_schedule_service.py`, `tests/test_api_schedule.py`

**Interfaces:**
- Produces: planned/forecast scope = assigned `pending/in_progress` tasks on unheld `in_progress ∪ draft ∪ submitted` jobs. History scope: **all** `.exclude(job__on_hold=True)` filters removed (held jobs' actuals render). Bars gain `'pre_approval': bool` from the task's job status.

- [ ] **Step 1: Failing tests:** assigned pending task on a draft job → forecast bar with `pre_approval=True` and its worker has a lane; unassigned pre-approval task → nothing; assigned task on an `approved` job → still no forecast (release gate preserved); held in_progress job: past bleps → `actual` bars present, no forecast bar, worker with only held work still gets a lane via the blep-history path; `test_on_hold_job_task_worker_absent_from_schedule` in `tests/test_api_schedule.py` is **replaced** by these semantics (history present, forecast absent). Extend `test_lane_bar_carries_job_number_and_name` for the `pre_approval` key.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement.** Both planned filters become `job__status__in=[Job.STATUS_IN_PROGRESS, Job.STATUS_DRAFT, Job.STATUS_SUBMITTED], job__on_hold=False`; delete the flag excludes on the two history paths and the completed-today worker query; `_build_bar` adds `'pre_approval': task.job.status in (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED)`.
- [ ] **Step 4:** Run + full schedule app tests → PASS. **Step 5: Commit** `feat(schedule): work-driven filters; held-job history renders; pre_approval on bars`.

### Task 10: SPA — pre-approval + on-hold treatments

**Files:**
- Modify: `frontend/src/components/schedule/TaskBar.svelte` (~22–23, 76–96 + CSS), `frontend/src/components/board/JobChipStrip.svelte` (~86–126 + CSS ~141–149), `frontend/src/components/board/JobCard.svelte`, `frontend/src/components/board/PipelineColumn.svelte` (pre-approval card treatment flows via JobCard)
- Test: `frontend/tests/components/schedule/TaskBar.test.js`, `frontend/tests/components/board/{JobChipStrip,JobCard}.test.js`

**Interfaces:**
- Consumes: `bar.pre_approval`, `job.pre_approval`, `job.on_hold`, `job.hold_reason` (Tasks 8–9).

- [ ] **Step 1: Failing Vitest cases** (use the existing `bar()` factory / class-assertion pattern): a `pre_approval` bar gets class `pre-approval`; a chip with `job.pre_approval` gets a dashed treatment class + "quote" badge; a chip with `job.on_hold` gets the diagonal treatment class and `hold_reason` in its `title`/hover popup; JobCard renders dashed border for pre_approval.
- [ ] **Step 2:** `npm run test:run` → FAIL.
- [ ] **Step 3: Implement.** TaskBar: `class:pre-approval={bar.pre_approval}` — CSS: dashed 2px accent outline + slightly desaturated fill (mirror how `.blocked` composes its ring at ~123). Chips: mirror the `blocked` diagonal `repeating-linear-gradient` (~141–149) for `on_hold` (grey), dashed `.chip-border` + small `quote` badge for `pre_approval`; hover title includes `hold_reason` when held. JobCard: dashed border when `job.pre_approval`; held banner already landed in Task 6.
- [ ] **Step 4:** PASS. **Step 5: Commit** `feat(spa): pre-approval and on-hold treatments on bars, chips, cards`.

---

## Phase 2 — weekly envelopes

### Task 11: `WeekEnvelope` + validation (pure layer)

**Files:**
- Modify: `apps/schedule/calendar_arithmetic.py`
- Test: `apps/schedule/tests/test_calendar_arithmetic.py` (new classes at top)

**Interfaces:**
- Produces (consumed by every later task — exact contract):

```python
DAY_KEYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')

@dataclass(frozen=True)
class WeekEnvelope:
    days: tuple  # 7-tuple indexed by date.weekday(); each a tuple of (time, time) pairs

    @classmethod
    def default(cls) -> 'WeekEnvelope'          # Mon–Fri (08:00,17:00), sat/sun ()
    @classmethod
    def from_json(cls, data: dict) -> 'WeekEnvelope'   # raises ValueError on invalid
    def to_json(self) -> dict                    # canonical {"mon": [["08:00","17:00"]], ...}
    def intervals_on(self, d: date) -> tuple     # self.days[d.weekday()]
    def is_working_day(self, d: date) -> bool    # bool(self.intervals_on(d))

def validate_week_envelope(data) -> list[str]    # [] when valid; message list otherwise
```

Validation rules (spec §Phase 2): dict with exactly the seven keys; each value a list of `["HH:MM","HH:MM"]` pairs; `HH:MM` zero-padded 00:00–23:59; `start < end`; strictly increasing across the day's boundaries (no overlap, no zero length, no touching — "merge instead" is the error hint). Pure `ValueError`/message-list layer — **no Django/DRF ValidationError imports** here.

- [ ] **Step 1: Failing tests** (`SimpleTestCase`, same file conventions): `default()` shape; `from_json` round-trips `to_json`; `validate_week_envelope` accepts the canonical example from the spec; rejects: missing key, extra key, `"8:00"` (unpadded), `"25:00"`, start==end, end<start, overlapping intervals, touching intervals (`[["08:00","12:00"],["12:00","17:00"]]`), non-list day, non-pair interval. `is_working_day` true given intervals, false on `()`.
- [ ] **Step 2:** Run `python manage.py test apps.schedule.tests.test_calendar_arithmetic` → FAIL.
- [ ] **Step 3: Implement** exactly the interface above (parse with a strict `re.fullmatch(r'([01]\d|2[0-3]):([0-5]\d)', s)`).
- [ ] **Step 4:** PASS. **Step 5: Commit** `feat(schedule): WeekEnvelope dataclass + validation`.

### Task 12: Generalize the arithmetic to envelopes

**Files:**
- Modify: `apps/schedule/calendar_arithmetic.py` (all functions), `apps/schedule/tests/test_calendar_arithmetic.py` (rewrite existing classes)

**Interfaces:**
- Produces (replacing the DayShape signatures — `DayShape`, `workday_start_on`, `workday_end_on` are **deleted**):

```python
def is_working_day(d: date, env: WeekEnvelope) -> bool
def shift_working_days(d: date, n: int, env: WeekEnvelope) -> date
def next_workable_moment(dt: datetime, env: WeekEnvelope) -> datetime
def add_work_time(start: datetime, work_duration: timedelta, env: WeekEnvelope) -> datetime
def segments_for(start: datetime, end: datetime, env: WeekEnvelope) -> list[(datetime, datetime)]
    # splits at gaps AND overnights/day-offs — forecast segmentation
def work_minutes_between(a: datetime, b: datetime, env: WeekEnvelope) -> int
def day_segments_clamped(start: datetime, end: datetime,
                         axis_start: time, axis_end: time) -> list[dict]
    # actuals: splits ONLY at local midnight, clamps each piece to the axis hours,
    # returns [{'start': dt, 'end': dt, 'clipped_left': bool, 'clipped_right': bool}];
    # a piece entirely outside the axis is dropped; if NOTHING survives, returns
    # one 1-minute sliver at the clamped start (visibility guarantee, replaces
    # the old degenerate fallback). Envelope-independent by design (spec: actuals
    # never split/clip at envelope gaps).
```

`task_buffer_minutes` leaves this module entirely (the service owns it).

- [ ] **Step 1: Rewrite the test file** — mechanical adaptation of every existing case (`DayShape.default()` → `WeekEnvelope.default()`, drop the lunch-era comments), plus new cases: an envelope with Mon lunch `[["08:00","12:00"],["12:30","17:00"]]`: `next_workable_moment(Mon 12:10)` → Mon 12:30; `add_work_time(Mon 11:00, 2h)` → Mon 13:30 (skips the gap); `segments_for(Mon 11:00 → Mon 13:30)` → two segments split at the gap; a `sat: [["09:00","13:00"]]` envelope makes Saturday working and `shift_working_days` counts it; a Wednesday-off envelope skips Wed like a weekend; `work_minutes_between` across a gap counts only interval time; `day_segments_clamped`: same-day within axis → one unclipped piece; spanning midnight → two pieces; a 22:00–23:30 blep against a 08:00–20:00 axis → one piece 22:00-start dropped ⇒ sliver rule; end-past-axis → `clipped_right=True` at the axis edge.
- [ ] **Step 2:** Run → FAIL. **Step 3: Implement** — the day-walk loops generalize from one `(wd_start, wd_end)` to iterating `intervals_on(d)`; keep the module pure and tz-consistent via the existing `_combine_local`.
- [ ] **Step 4:** Run the module → PASS. (`apps.schedule.tests.test_schedule_service` and the service are now BROKEN — that is expected; Task 14 fixes them. Do not commit a red suite: Tasks 12–14 may share one commit if needed, but prefer making Task 13+14 immediately after.) **Step 5: Commit together with Task 13 if the service import breaks, otherwise commit** `feat(schedule): calendar arithmetic over weekly envelopes`.

### Task 13: Config key swap — `schedule_week_envelope`

**Files:**
- Modify: `apps/schedule/services.py` (`CONFIG_DEFAULTS` ~26–31, `load_day_shape` ~48–59 → `load_shop_envelope` + `load_buffer_minutes`), `apps/api/templates_config/views.py` (`_validate_schedule_keys` ~168–208, writer loop ~261–262, GET ~213–216)
- Test: `tests/test_schedule_settings_validation.py` (rewrite)

**Interfaces:**
- Produces: `load_shop_envelope() -> WeekEnvelope` (reads `schedule_week_envelope`, lazily seeds `json.dumps(WeekEnvelope.default().to_json())`); `load_buffer_minutes() -> int`. Settings PATCH accepts `schedule_week_envelope` as a dict **or** JSON string, validates via `validate_week_envelope`, stores `json.dumps` of the parsed dict; GET returns the stored string (SPA parses). `schedule_workday_start`/`_end` are gone from `CONFIG_DEFAULTS`, the validator, and everywhere else (`grep -rn schedule_workday` must come back empty outside migrations/docs).

- [ ] **Step 1: Rewrite `tests/test_schedule_settings_validation.py`:** invalid JSON string → 400 `{'schedule_week_envelope': ...}`; overlapping intervals → 400; valid dict → 200 and `json.loads(Configuration.get(...).value)` round-trips; `schedule_workday_start` PATCH is now just an unknown passthrough key (assert it no longer triggers schedule validation); buffer/horizon validations unchanged; `test_non_schedule_keys_still_work` kept.
- [ ] **Step 2:** Run → FAIL. **Step 3: Implement** (validator branch + writer special-case `ConfigurationService.set(key, json.dumps(parsed))`).
- [ ] **Step 4:** Run module → PASS. **Step 5: Commit** `feat(settings): schedule_week_envelope replaces workday start/end keys`.

### Task 14: Per-worker resolution + service rewrite + payload

**Files:**
- Modify: `apps/core/models.py` (User ~9–30: add field), new migration `apps/core/migrations/0025_*.py`
- Modify: `apps/schedule/services.py` (`get_schedule`, `_extend_shape_for_window` → `_compute_axis`, `_build_lane`, `_emit_actual`, `_emit_forecast`, `_elapsed_worktime`)
- Test: `apps/schedule/tests/test_schedule_service.py`, `tests/test_api_schedule.py`

**Interfaces:**
- Produces: `User.schedule_envelope = models.JSONField(null=True, blank=True)` (null = shop default). `resolve_envelope(user, shop_env) -> WeekEnvelope` (module-level in `apps/schedule/services.py`; malformed stored JSON falls back to shop + logs a warning — never 500s the page). Payload changes (additive now, `day_shape` alias kept until Task 19):
  - `axis: {"start": "HH:MM", "end": "HH:MM", "task_buffer_minutes": int}` — page display axis.
  - `workers[i].envelope_by_day: [ [["HH:MM","HH:MM"], ...], ... ]` — parallel to `days[]`, that worker's resolved intervals per visible day (drives lane shading).
  - `days[].is_working` = shop works it **or** any displayed worker works it.
  - `day_shape` (legacy) mirrors `axis` values into the old keys (`workday_start`, `workday_end`, `config_workday_start/end` = axis values, `task_buffer_minutes`) so the SPA keeps rendering until Task 19 removes it.
- Cascade rules (spec §Phase 2): per-worker envelope drives `next_workable_moment`/`add_work_time`/`segments_for`/`work_minutes_between`; `shift_working_days`/offset stepping and the horizon-day walk use the **shop** envelope; axis = union of displayed workers' interval hours across visible days, widened by the blep rule (floor/ceil to hour, same-start-date-only, running-blep projection — port `_extend_shape_for_window`'s guards onto `(axis_start: time, axis_end: time)`); `_emit_actual` uses `day_segments_clamped(start, end, axis_start, axis_end)` and maps `clipped_*` onto the segment `continues_left/right` flags (OR-ed with the multi-segment position flags).

- [ ] **Step 1: Failing tests:** two workers, one on shop default (Mon–Fri 8–17), one with `sat [["09:00","13:00"]]` + weekday `7–15` envelope stored on the User: forecasts cascade at each worker's own hours (assert exact bar start/end); Saturday appears as a working day column; axis start `07:00`; `envelope_by_day` matches each worker per day; a blep through a worker's lunch gap emits ONE actual segment (no gap split); a forecast spanning the gap emits two segments with continuation flags; a 22:00–23:30 blep with a same-day end widens the axis to 24h-capped ceil (existing rule) while a midnight-crosser instead clips with `continues_right`; `_elapsed_worktime` counts only in-envelope minutes; API test asserts `axis` + `envelope_by_day` keys and that legacy `day_shape` still mirrors axis.
- [ ] **Step 2:** Run → FAIL. **Step 3: Implement** (field + `makemigrations core`; thread `(shop_env, buffer)` through; per-worker env resolved once per lane).
- [ ] **Step 4:** FULL fresh backend run (migration changed — no `--keepdb`); read the summary line. **Step 5: Commit** `feat(schedule): per-worker envelopes drive the cascade; union axis + per-lane payload`.

### Task 15: Envelope endpoints (self + admin)

**Files:**
- Modify: `apps/api/auth/views.py`, `apps/api/auth/urls.py`, `apps/api/auth/serializers.py` (UserSerializer ~22–30), `apps/api/users/views.py`, `apps/api/users/serializers.py` (UserDetailSerializer ~36–51)
- Test: create `tests/test_api_schedule_envelope.py`

**Interfaces:**
- Produces: `PUT /api/auth/me/schedule-envelope/` (`IsAuthenticated`; body `{"schedule_envelope": {...} | null}`; null resets to shop default; response = updated envelope value) — pattern-match `change_password_view`. `PUT /api/users/{id}/schedule-envelope/` — `@action(detail=True, methods=['put'], url_path='schedule-envelope')` on `UserViewSet`, permission `IsAuthenticated` + (`CanManageTime` | `CanManageConfig`) via a `get_permissions` branch on `self.action == 'schedule_envelope'` (the rest of the viewset stays CanManageConfig-only). Both validate via `validate_week_envelope` and raise `serializers.ValidationError({'schedule_envelope': msgs})`. `schedule_envelope` added to auth `UserSerializer` and `UserDetailSerializer` (read).

- [ ] **Step 1: Failing tests:** self PUT valid envelope → 200, persisted; PUT null → resets; invalid (overlap) → 400 contract shape; anonymous → 401/403. Admin route: `can_manage_time`-only user → 200 on another user; `can_manage_config`-only → 200; neither → 403; target's other fields untouched.
- [ ] **Step 2:** FAIL. **Step 3: Implement.** **Step 4:** PASS. **Step 5: Commit** `feat(api): schedule-envelope endpoints (self + time/config managers)`.

---

## Phase 3 — editing UI + schedule rendering

### Task 16: `EnvelopeEditor.svelte`

**Files:**
- Create: `frontend/src/components/schedule/EnvelopeEditor.svelte`
- Test: create `frontend/tests/components/schedule/EnvelopeEditor.test.js`

**Interfaces:**
- Produces a controlled component:

```js
// Props (Svelte 5 $props):
//   value        — envelope object or null (null = "using default")
//   defaultValue — envelope object rendered read-only while value === null (omit for the shop editor)
//   allowNull    — bool: show the "Use shop default" / "Customize" toggle (true on user surfaces)
//   onchange(newValueOrNull) — fired on every edit; the PARENT owns save
```

Seven day rows (Mon…Sun); each row: interval list as paired `<input type="time">` + per-interval remove ✕ + "add interval"; empty list renders "Day off". No client-side cross-validation beyond the inputs (server is authoritative; parent renders `errors.schedule_envelope`). No confirm dialogs; the parent's explicit Save commits (never blur).

- [ ] **Step 1: Failing Vitest** (render + interaction, `@testing-library/svelte` per existing suites): renders 7 rows from a value; add-interval on an empty day calls `onchange` with one `["08:00","17:00"]` pair (sane default); remove-interval empties to day-off; `allowNull` + `value:null` shows the read-only default and a Customize button which fires `onchange(deepCopy(defaultValue))`; "Use shop default" fires `onchange(null)`.
- [ ] **Step 2:** FAIL. **Step 3: Implement.** **Step 4:** PASS. **Step 5: Commit** `feat(spa): envelope editor component`.

### Task 17: Mount 1 — Settings → Schedule

**Files:**
- Modify: `frontend/src/components/settings/ScheduleSettings.svelte` (replace workday inputs ~54–64)
- Test: `frontend/tests/components/settings/ScheduleSettings.test.js`

- [ ] **Step 1: Failing tests:** load parses `schedule_week_envelope` JSON string from GET into the editor; Save PATCHes `{schedule_week_envelope: <object>, schedule_task_buffer_minutes, schedule_horizon_days, ...}` (no workday keys); a 400 `{schedule_week_envelope: 'msg'}` renders under the editor.
- [ ] **Step 2:** FAIL. **Step 3: Implement** (`<EnvelopeEditor value={envelope} onchange={...} />`, `JSON.parse` with fallback to the canonical default on missing/bad value). **Step 4:** PASS. **Step 5: Commit** `feat(spa): shop week envelope in Settings → Schedule`.

### Task 18: Mounts 2+3 — Home → Time (self) and user profile (managers)

**Files:**
- Create: `frontend/src/components/home/MyEnvelopeEditor.svelte` (wrapper: loads own value from `/api/auth/me/`, `PUT /api/auth/me/schedule-envelope/` on Save, `allowNull` with the shop default fetched from `/api/settings/`? — NO: settings is config-gated; instead the wrapper renders "using shop default" from `schedule_envelope === null` WITHOUT displaying the shop values, and the editor's `defaultValue` prop is omitted → shows a "Using the shop schedule" placeholder line)
- Modify: `frontend/src/routes/Home.svelte` (~65–69: append to the Time tab), `frontend/src/routes/users/UserDetailPage.svelte` (new `<h3>Schedule envelope</h3>` section, `envForm`/`saveEnvelope` per the `saveProfile` pattern, PUT `/api/users/{id}/schedule-envelope/`)
- Test: create `frontend/tests/components/home/MyEnvelopeEditor.test.js`; create `frontend/tests/components/users/UserDetailPage.test.js` covering just the new section (first test for that page — mock `/api/users/{id}/` GET)

- [ ] **Step 1: Failing tests:** MyEnvelopeEditor: null envelope shows the shop-default placeholder + Customize; Save PUTs the edited object; server 400 renders the message; Save with "Use shop default" PUTs null. UserDetailPage: section renders from `user.schedule_envelope`, Save PUTs to the admin route.
- [ ] **Step 2:** FAIL. **Step 3: Implement.** **Step 4:** PASS. **Step 5: Commit** `feat(spa): self + admin envelope editing surfaces`.

### Task 19: Schedule page — axis payload, per-lane shading, clipped zigzags

**Files:**
- Modify: `frontend/src/routes/schedule/SchedulePage.svelte` (`buildPanelLayout` ~110–235: axis from `s.axis`, delete page-level `offHoursBands`), `frontend/src/components/schedule/WorkerLane.svelte` (per-lane shading bands), `frontend/src/components/schedule/TaskBar.svelte` (no change expected — clipped segments arrive as `continues_*` flags it already zigzags)
- Modify: `apps/schedule/services.py` — **remove the legacy `day_shape` alias** (and its assertions in `tests/test_api_schedule.py`)
- Test: `frontend/tests/components/schedule/WorkerLane.test.js`, `TaskBar.test.js`; backend `tests/test_api_schedule.py`

**Interfaces:**
- Consumes: `axis`, `workers[i].envelope_by_day`, `days[].is_working` (Task 14).

- [ ] **Step 1: Failing Vitest:** WorkerLane with an `envelope_by_day` containing a lunch gap renders shading bands (a `.lane-offhours` div) before 08:00, over 12:00–12:30, and after 17:00 within each working panel (inject the same `timeToX` stub style as `TaskBar.test.js`); a worker with no Saturday intervals shades that whole panel in their lane while another lane doesn't. TaskBar: a segment with `continues_right: true` still zigzags (existing behavior — assert unchanged against a clipped-actual fixture).
- [ ] **Step 2:** FAIL. **Step 3: Implement.** SchedulePage: axis minutes from `s.axis.start/end`; move off-hours band computation into WorkerLane (per lane, from `envelope_by_day` inverted against the axis, positioned via `panelLayout.timeToX`; render behind the bars in `.track`). Remove `s.day_shape` reads; backend drops the alias; update the backend API test.
- [ ] **Step 4:** `npm run test:run` PASS + backend schedule modules PASS. **Step 5: Commit** `feat(spa): per-lane envelope shading; axis-driven layout`.

---

## Phase 4 — seed data, docs, final verification

### Task 20: nealsdata — envelope Configuration row

**Files:**
- Modify: `nealsdata/converter/build.py` (`build_configuration` ~134–175)
- Test: `tests/test_neals_builders.py`

- [ ] **Step 1:** Add to the `config` list (matching `_WORKDAY_START`/`_WORKDAY_END` = 09:00/17:00):

```python
('schedule_week_envelope', json.dumps({
    'mon': [['09:00', '17:00']], 'tue': [['09:00', '17:00']],
    'wed': [['09:00', '17:00']], 'thu': [['09:00', '17:00']],
    'fri': [['09:00', '17:00']], 'sat': [], 'sun': [],
})),
```

Update `test_neals_builders.py` expectations.
- [ ] **Step 2:** `python manage.py test tests.test_neals_builders` → read summary → PASS. **Step 3: Commit** `feat(nealsdata): seed schedule_week_envelope`.

### Task 21: Docs + final gate

**Files:**
- Modify: `docs/designs/schedule.md` (§2 config, §3 cascade, §5 frontend, §6 future work — envelope model, work-driven scope, axis rules 1–3, editing surfaces), `docs/designs/jobs-tasks-and-worksheets.md` (job lifecycle: on_hold flag + hold/release; board sets), `docs/designs/estimates-and-prices.md` + CO sections (flag), `docs/designs/data-constraints.md` (§1.1 config keys; Job field constraints: `on_hold`, `hold_reason`; User `schedule_envelope`), `docs/designs/users-and-permissions.md` (envelope endpoints + atoms)
- Delete: `docs/plans/2026-07-05-schedule-hold-flag-and-envelopes.md` + this plan (ONLY after the user signs off — leave both in place at handoff)

- [ ] **Step 1:** Update the five design docs to match implemented reality (write from the code, not this plan).
- [ ] **Step 2: Final gate:** full fresh backend suite (no `--keepdb`, unpiped or tee+grep the summary), `cd frontend && npm run test:run`, `npm run build` (catches Svelte strict-mode errors). All green.
- [ ] **Step 3: Commit** `docs: schedule + jobs design docs to the flag/envelope model`. Then STOP — report done; no merge/push/PR (user reviews in the browser).

---

## Self-review notes (already applied)

- Spec coverage: Decision 1 → Tasks 8–10; Decision 2 → Tasks 2, 6, 9; Decision 3 → recorded, no task (hover only, Task 10). Phase 0 → 1–7; Phase 1 → 8–10; Phase 2 → 11–15; Phase 3 → 16–19; Phase 4 → 20–21. CO auto-resume ⚠ → Task 3 test case. hold_reason serializer gap → Task 4. Blep-guard omission trap → Task 2. Axis rules 1–3 → Tasks 12 (`day_segments_clamped`), 14 (widening + clipping), 19 (rendering).
- Type consistency: `WeekEnvelope` interface fixed in Task 11 and consumed by name in 12–14; payload keys (`axis`, `envelope_by_day`, `pre_approval`, `on_hold`, `hold_reason`) identical across Tasks 8/9/14/19.
