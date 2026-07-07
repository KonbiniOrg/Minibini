# Entered-qty: per-session adds on blep stop + confirm-or-correct completion

> **Status: spec, approved direction (2026-07-06).** Implementation lands
> on `feature/hand-actuals`. Brainstorm decisions recorded below; the
> deliberately deferred richer design (per-blep provenance) is documented
> in `docs/designs/estimates-and-prices.md` §16 so it isn't lost.

## What changes, in one paragraph

Today `Task.actual_qty` (the billable quantity for `ENTERED_QTY` rate
schemes) is entered exactly once — via the completion modal, or the
"Actual qty" field on TaskDetailPage — and every write **replaces** the
value. This spec makes accumulation the norm, with three entry moments:
(1) when a worker explicitly stops their own blep on an `ENTERED_QTY`
task, the SPA prompts for "how many did this session produce?" and the
entry **adds** to the running total; (2) the TaskDetailPage field is
reworked from a set-the-value editor into a running-total display plus
an **add** input (usable mid-blep, so a worker can log counts during a
session without stopping); (3) task completion becomes a
**settle-up** step: the modal always appears for `ENTERED_QTY` tasks,
shows the accumulated total, and asks "any more to add?" — the user
enters a final increment (possibly zero), never does arithmetic on a
total; (4) the stop prompt carries
a **"this completes the task"** checkbox, so the common "last session,
here's the count, done" moment is one gesture; (5) the same session
prompt **fronts the other two explicit gestures** that would otherwise
silently close an entered-qty session — starting a blep on another task,
and clocking out — settling the old session before the gesture proceeds.
Every entry surface shows the expected units, sourced from the task's
`RateScheme.unit_label`.

## Decisions already made (do not re-litigate during implementation)

1. **Single accumulator, no provenance.** `Task.actual_qty` stays the one
   Decimal field. No `entered_qty` column on Blep, no JSON entry log.
   Per-session entries are best-effort contributions to the total; they
   are not individually reviewable or editable afterward. (Extension path
   if this proves insufficient: estimates-and-prices.md §16.)
2. **Completion is the authoritative settle-up.** Many blep-close paths
   cannot prompt (see "Paths that never prompt" below) and that is
   accepted: missed prompts only make the completion prefill less
   accurate, never corrupt data. The final number is confirmed by a human
   at completion, which is the moment invoicing cares about
   (`compute_amount` only runs on complete tasks).
3. **Stop always succeeds; the prompt is after the fact and skippable.**
   The blep closes regardless. Cancelling the session-qty modal is a
   legitimate "this session produced nothing / I'll settle up later".
4. **Every write is an add — there is no replace anywhere.** The
   TaskDetailPage field becomes an add surface (see Frontend) — the old
   set/replace field and its `PATCH actual-qty` endpoint are retired.
   Completion asks "any more to add?" and applies the final increment
   server-side under the same lock, so the user never re-types or does
   arithmetic on a total, and a teammate's concurrent add is never
   clobbered. Corrections at any point are negative adds.
5. **Adds are not idempotent, so no implicit saves — anywhere.** Every
   add is committed by an explicit action (the modal's submit, the
   field's Add button / Enter-on-input). Never on blur, never debounced,
   never retried automatically by the client on timeout (a retry could
   double-count; the user re-reads the displayed total and decides).
6. **Units are always shown.** The user must know what they're counting:
   every entry surface displays the scheme's `unit_label` (already
   exposed to the SPA as `scheme_unit_label` on the task serializer and
   as `unit_label` in the prompt payloads).

## Backend

### Service: `TaskLifecycleService.add_actual_qty(task_pk, qty)`

New method in `apps/jobs/services.py`, alongside `set_actual_qty` (which
keeps its replace semantics for the direct-edit endpoint):

```python
@staticmethod
def add_actual_qty(task_pk, qty):
    with transaction.atomic():
        task = Task.objects.select_for_update().get(pk=task_pk)
        # Complete/cancelled tasks are settled; late adds would clobber
        # the confirmed total.
        if task.status in (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED):
            raise ValidationError('Task is already settled.')
        if task.rate_scheme.algorithm != RateScheme.ENTERED_QTY:
            raise ValidationError('Task is not billed by entered quantity.')
        qty = Decimal(str(qty))          # InvalidOperation → field error
        if qty == 0:
            raise ValidationError({'actual_qty': ['Must not be zero.']})
        new_total = (task.actual_qty or Decimal('0')) + qty
        if new_total < 0:
            raise ValidationError({'actual_qty': [
                'Cannot reduce the total below zero.']})
        task.actual_qty = new_total
        task.save(update_fields=['actual_qty'])
        return task
```

The delta is **signed**: negative adds are the mid-work correction path
(fat-fingered 50 instead of 5 → add −45), validated so the total never
goes below zero. The stop-session modal constrains its input to > 0
client-side (a session can't produce negative pieces); the TaskDetailPage
field accepts either sign.

`select_for_update` is the concurrency answer: two workers on the same
task ('join') stopping near-simultaneously must not lose an add. Do NOT
use `QuerySet.update(actual_qty=F(...) + qty)` — locking + `save()`
matches the `complete_task` pattern and respects `full_clean()`.

`set_actual_qty` and its `PATCH /api/tasks/{id}/actual-qty/` endpoint are
**retired** — their only caller was the TaskDetailPage set-field, which
this spec reworks into an add field. Remove the service method, the
viewset action, and their tests.

### Service: `complete_task` — settle up with a final increment

`complete_task`'s `actual_qty` parameter (replace semantics) is
**replaced by `add_qty`** (signed increment, `None` = not provided).
The `ENTERED_QTY` guard (`apps/jobs/services.py:1210`) changes from
"raise only when nothing is on record" to "raise whenever the caller
didn't pass `add_qty`", and the write becomes an add under the
already-held lock:

```python
if task.rate_scheme.algorithm == RateScheme.ENTERED_QTY:
    if add_qty is None:
        raise TaskActualQtyRequired(task.rate_scheme.unit_label, task.actual_qty)
    final = (task.actual_qty or Decimal('0')) + add_qty
    if final <= 0:
        raise ValidationError({'add_qty': [
            'Final quantity must be greater than 0.']})
    task.actual_qty = final          # written with the status update
```

`TaskActualQtyRequired` gains a `current_qty` attribute (the accumulated
total, may be `None`). `add_qty` of zero is legal — "nothing more to
add" — provided the accumulated total is already positive; a negative
`add_qty` is a last-moment correction.

**Complete-while-blepping walkthrough (entered-qty):** the guard fires
*before* `_close_open(task=task)`, so the prompting round-trip leaves
the blep running; it closes only when the re-post with `add_qty`
actually completes the task. The user enters just what isn't recorded
yet ("made 5 this session → enter 5") — the server adds it to the
running total. Stop and Complete are symmetric: both ask for the
increment since the last entry, and no surface ever asks the user to
compute a total.

**This is a behavior change:** an `ENTERED_QTY` task whose qty was
already on record used to complete silently; it now always round-trips
through the prompt. That's the point (confirm-or-correct), but existing
tests that complete such tasks without passing `actual_qty` will start
failing and need updating to pass the qty explicitly.

### API

- `POST /api/tasks/{id}/stop-work/` (`apps/api/tasks/views.py`):
  when the stop actually closed a blep, the target is the requesting
  user themselves (no `on_behalf_of`), and the task's scheme is
  `ENTERED_QTY`, the response gains prompt fields:

  ```json
  {"status": "ok", "prompt_actual_qty": true,
   "unit_label": "pcs", "current_qty": "9.00"}
  ```

  On-behalf stops never include the prompt fields — the manager stopping
  a forgotten timer doesn't know the count; the completion settle-up
  catches it. `cancel-work` (under-the-minimum oops path) never prompts.

- New action `POST /api/tasks/{id}/actual-qty/add/` (url_path
  `actual-qty/add` on the existing viewset), body `{"actual_qty": "5"}`
  (signed decimal), `IsAuthenticated` (same openness as the retired
  PATCH — any worker on the task can contribute). Delegates to
  `add_actual_qty`; returns `{"actual_qty": "14.00"}` (the new total) so
  the caller can render the updated running total without a refetch.
  Validation errors surface in contract shape via the central handler.

- `POST /api/tasks/{id}/complete/`: the body's `actual_qty` param is
  replaced by `add_qty` (signed decimal increment). The
  `needs_actual_qty` response gains `current_qty` (string or null) so
  the modal can display the running total:

  ```json
  {"needs_actual_qty": true, "unit_label": "pcs", "current_qty": "14.00"}
  ```

- `PATCH /api/tasks/{id}/actual-qty/` is removed (see above). No
  endpoint writes a total anymore — every write path is an increment.

- `POST /api/tasks/{id}/start-work/` and `POST /api/shifts/clock-out`:
  gain the `prior_session_qty` conflict response and the
  `prior_qty_handled` body flag (see "Rolled-in prompt paths").

### Paths that never prompt (by design — restating decision 2)

Own explicit gestures — stop, start-on-another-task, clock-out — all
prompt (the first via the stop response, the latter two via
`prior_session_qty`). What remains silent:

- `complete_task` closing **teammates'** open bleps on the task.
- **On-behalf** gestures: a manager stopping a worker's timer, starting
  work for them, or clocking them out.
- Admin-forced closes (`close_open_for_user`, e.g. user deactivation).
- Takeover resolving the displaced worker's blep.
- `create_historical` (after-the-fact time entry).

None of these need code changes. The completion prompt is the backstop.

## Frontend

### `ActualQtyModal.svelte` grows two modes

- `mode: 'complete'`: title "Settle up quantity", copy "Entered so far:
  **14 pcs**. Any more to add?", input **empty** (empty = 0, "nothing
  more"), signed (negative = last-moment correction), submit button
  "Complete task". The final total (`current_qty` + input) is shown
  live; client-side, block submit when it isn't > 0 (the server
  enforces the same).
- `mode: 'session'`: title "Quantity this session", empty input, copy
  "How many **pcs** did this session produce? (Cancel to skip — you can
  settle the total when the task is completed.)", submit "Add". Requires
  > 0 (client-side; the shared endpoint accepts signed deltas but a
  session can't produce negative pieces); Cancel simply closes (the blep
  is already stopped). Carries a **"This completes the task"** checkbox
  — see the next section. Both modes always name the unit
  (`unit_label` from the prompt payload).

### Stop-and-complete in one gesture

Stopping and completing are one gesture approached from two ends
(Complete-while-blepping already closes the blep), so the session modal
offers the other direction: a **"This completes the task"** checkbox.
While checked, the modal shows the predicted final total live —
"Final quantity will be **14 pcs**" (stop response's `current_qty` +
the input) — and the submit button reads "Add & complete".

Submit with the checkbox checked is **one call**: `POST complete` with
`add_qty` set to the input (empty input → `0` — "this session produced
nothing, but the task is done"). The server applies the increment and
completes atomically under the row lock, so a teammate's concurrent add
is simply included in the final total — there is no
predicted-vs-actual mismatch to guard against, and no separate
`actual-qty/add` call in this path.

If `complete` fails (pending materials, job on hold, status guard): the
blep is already closed and nothing else has been written — the typed
increment is NOT lost silently: the modal stays open showing the error
(via `triageError`), and the user can uncheck the checkbox and submit
as a plain add (which posts `actual-qty/add`), or cancel.

Scope note: the checkbox lives on the session-qty modal, so it exists
only for `ENTERED_QTY` own-stops — the only stop path that already has
a UI moment. Elapsed-time tasks keep today's gesture (the Complete
button, which closes the open blep and runs the `needs_time_logged`
flow); giving their bare stop a modal just to host a checkbox is new
surface area this spec doesn't take on.

### Rolled-in prompt paths: switching tasks and clocking out

Two more explicit gestures silently close an open blep today: starting
work on a different task (`start_work` closes your open blep on any
task before creating the new one) and explicitly clocking out
(`POST /api/shifts/clock-out` → `ShiftService.clock_out`). Both get the
session prompt rolled in, following the conflict-dict pattern
`start_work` already uses for `active_worker`:

**Backend.** When the gesture is the user's own (`target ==
request.user`), the request carries no `prior_qty_handled` flag, and
the target has an open blep on an `ENTERED_QTY` task (for start-work: a
*different* task than the one being started), the endpoint mutates
nothing and returns:

```json
{"conflict": "prior_session_qty",
 "prior_task": {"task_id": 7, "name": "Cut panels"},
 "unit_label": "pcs", "current_qty": "9.00"}
```

The client resolves the prompt (below) and re-posts the original
request with `prior_qty_handled: true`; the re-post then closes the old
blep exactly as today (same timing/flooring semantics — the flag only
suppresses the prompt). Rules:

- **Own gestures only.** On-behalf starts and on-behalf clock-outs
  (manager acting for a worker) never prompt — the actor doesn't know
  the count; completion settle-up catches it.
- **Prompt ordering (start-work):** `prior_session_qty` is evaluated
  before the `active_worker` conflict on the *new* task, so the old
  session is settled first; join/takeover resolution happens on the
  re-post. `action` re-posts must carry `prior_qty_handled` too.
- **Elapsed-time open bleps** stay silent-close (nothing to ask).
- **Races are benign:** if the world changed between prompt and re-post
  (teammate completed the prior task → the add is rejected; blep
  already closed elsewhere → re-post closes nothing), errors surface
  through normal venues and no state is corrupted.

**Frontend.** The session modal opens with the prior task named in the
copy ("Your open session on **Cut panels** — how many pcs did it
produce?") and keeps the completes-task checkbox. Semantics specific to
this context:

- **Cancel aborts the gesture** — no entry, no new blep / no clock-out;
  the old session keeps running. (Unlike the stop flow, nothing has
  happened yet.)
- **Empty input + submit = skip the entry** and proceed (re-post with
  the flag). This is the "just switch, I'll settle later" path.
- Qty entered, checkbox off: `POST actual-qty/add` on the prior task,
  then re-post the original gesture with the flag.
- Checkbox on: `POST complete` on the prior task with `add_qty` (this
  closes the old blep), then re-post the original gesture (flag
  included regardless; harmless).

Since the payload and resolution are identical across callers, factor
the resolve-then-retry logic into one shared component/helper rather
than four copies.

### Wiring points (all three stop-work callers)

- `TaskActions.svelte`: `stopWork` inspects the response; on
  `prompt_actual_qty` opens the modal in `session` mode; submit posts
  `actual-qty/add`, then `onChanged()` (no `notifyBlepChanged` — the
  blep already changed and was notified when the stop returned). With
  the completes-task checkbox checked, post the single
  `complete`+`add_qty` call, then `onChanged()`. `completeTask` passes
  `resp.current_qty` through to the modal.
- `CurrentBlepBand.svelte` (the global band): same response handling,
  including the checkbox path; the modal renders inside the band
  component so it works on any page.
- `TaskQuickCard.svelte` (schedule, on-behalf stop/start): no changes —
  the server never prompts for on-behalf gestures.
- **Start-work callers** (`TaskActions`, home's `AssignedTaskList`, and
  the `StartWorkConflictModal` re-posts — which must carry
  `prior_qty_handled`) and **`ClockBand`** (clock-out): route the
  `prior_session_qty` conflict through the shared resolve-then-retry
  handling from "Rolled-in prompt paths".

### TaskDetailPage: the set-field becomes a running-total + add field

Today (`TaskDetailPage.svelte` ~lines 45–48, 124–135, 363–373) the
"Actual {unit}s" row prefills an input with `task.actual_qty` and a Save
button PATCHes the replacement value. Rework it to:

- **Display the running total read-only**, with units:
  "Actual so far: **14 pcs**" (`task.actual_qty ?? 0` +
  `task.scheme_unit_label`). The unit label is load-bearing — the user
  must know what units the scheme expects before typing a number.
- **Beside it, an empty delta input** (labeled "Add (pcs)", signed) and
  an explicit **Add** button; Enter in the input also submits (both are
  deliberate actions — fine). On success: post to `actual-qty/add`, show
  the returned new total, clear the input, brief "added" flash (reuse
  the existing `saved-flash` pattern). Errors render in the existing
  field-error slot via `triageError`.
- **No implicit saves** (decision 5): nothing on blur, no auto-retry.
  The current code is already explicit-save; preserve that property
  through the rework.
- Visible only for `entered_qty` schemes and non-terminal task statuses
  (matching the service guard). Explicitly usable while the user has an
  open blep on the task — logging counts mid-session without stopping is
  the point of this surface.

## Tests (TDD order)

Backend (`tests/`):
1. `add_actual_qty`: adds from null start; adds onto existing; negative
   delta subtracts; rejects zero, a delta that would take the total
   below zero, non-decimal, wrong scheme, complete/cancelled task.
2. Concurrency shape: two sequential adds sum (true parallelism isn't
   testable in TestCase; the lock is verified by reading the code path —
   keep the test honest about what it covers).
3. `complete_task`: raises `TaskActualQtyRequired` (with `current_qty`)
   for `ENTERED_QTY` whenever `add_qty` is absent, even when qty already
   recorded; `add_qty=0` completes when the accumulated total is
   positive; positive/negative increments apply onto the total; rejects
   when accumulated + `add_qty` ≤ 0.
4. API: stop-work prompt fields present for own-stop on `ENTERED_QTY`
   task, absent for elapsed-time tasks, absent for on-behalf stops,
   absent when no blep was open; `actual-qty/add` endpoint happy path
   (both signs) + error shapes; `complete` accepts `add_qty` and its
   prompt response carries `current_qty`; `PATCH actual-qty` is gone
   (404/405).
5. `prior_session_qty`: `start_work` returns the conflict for an own
   start with an open entered-qty blep on another task; not for
   elapsed-time priors, on-behalf starts, same-task, or when
   `prior_qty_handled` is passed; evaluated before `active_worker`
   (re-post with both flags resolves). `clock_out`: same matrix; the
   flag re-post closes blep + shift as today.
6. Sweep existing tests that complete `ENTERED_QTY` tasks relying on the
   old "silent when already recorded" behavior or passing `actual_qty`
   (switch to `add_qty`), tests of the removed `set_actual_qty`/PATCH
   endpoint, and any start-work/clock-out tests that assume silent
   close of an entered-qty session.

Frontend (`frontend/tests/`, Vitest — run `npm run test:run`):
7. `ActualQtyModal`: both modes (copy, running-total display, live
   final total, validation incl. final-must-be-positive, Cancel, unit
   label rendering); session mode's completes-task checkbox
   (submit label change, empty-input-allowed when checked); prior-task
   name in copy for the switch/clock-out context.
8. `TaskActions`: stop → session modal → add posted; checkbox checked →
   single complete posted with `add_qty` (empty input → 0); complete
   failure keeps the modal open with the error and the typed value;
   Complete button → settle-up modal (running total shown, live final
   total) → complete posted with the increment; Start Work →
   `prior_session_qty` conflict → modal → add + re-post with flag /
   empty-submit skips the add / Cancel aborts (no re-post).
9. `CurrentBlepBand`: stop → session modal appears and posts (incl.
   checkbox chain).
10. `TaskDetailPage`: running total + unit rendered; Add posts the
    delta and renders the returned total; signed input accepted; no
    write on blur.
11. `ClockBand`: clock-out → `prior_session_qty` conflict → modal →
    resolve → clock-out re-posted with flag; Cancel leaves the shift
    (and session) open.
12. `StartWorkConflictModal`: re-posts carry `prior_qty_handled`.

## Doc updates in the implementing session

- `docs/designs/estimates-and-prices.md` §4.2 (actual_qty semantics —
  accumulator + settle-at-completion), §16 (trim the future-work bullet
  to just the not-built extension).
- `docs/designs/jobs-tasks-and-worksheets.md`: Task field table
  (`actual_qty` row), stop-work flow, completion flow.

## Explicitly out of scope (related, tracked elsewhere)

- **Job-level `work-complete` process** — untouched by this feature set
  (separate pending issue, likely blocking on in-progress tasks). Today
  that action only moves job status and never completes tasks, which is
  what makes the always-prompt completion flow safe. If it ever grows
  bulk task completion, it must refuse on unsettled `ENTERED_QTY` tasks
  rather than invent quantities.
- Per-blep `entered_qty` provenance — the deferred richer design
  (estimates-and-prices.md §16).
- A stop modal (and completes-task checkbox) for **elapsed-time** tasks
  — see the scope note in "Stop-and-complete in one gesture".
