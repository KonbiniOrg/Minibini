# Follow-on: pre-approval work on the schedule

> **Status: NOT APPROVED — follow-on to the job-owns-atoms refactor.** Hold for review.
> The board side (does a quote-stage job's work belong on the in-progress surface?) is
> deliberately left open — the user is still deciding. Do **not** implement this until it's
> signed off. The main plan (`2026-06-29-job-owns-atoms-implementation-plan.md`) does **not**
> include schedule changes.

## The requirement

Once work can be done before estimate approval (a site visit, a customer meeting, material
research), that Task work needs to be **assignable** and **shown on the schedule**, and
**flagged there** so it's differentiable from approved-job work.

## Why it isn't in the main plan

`ScheduleService` (`apps/schedule/services.py`) currently hard-filters work to
`job__status=Job.STATUS_IN_PROGRESS` in three places — the worker set (~line 150) and the
planned/history selection in `_build_lane` (~388, ~404). So pre-approval jobs' tasks are
fully excluded today. Changing that is a self-contained schedule pass, and the board
question below needs a decision first.

## Recommended design (for discussion)

**Split the surfaces by the axis they represent.**

- **The schedule is a *work* surface** — "what is each worker doing / about to do." Drive it
  off *work* signals (assignee + a planned/in-progress task status, or bleps), and treat job
  status as a **flag, not a filter**. Broaden the three `job__status=IN_PROGRESS` filters to
  work-active statuses, and add `pre_approval = job.status in {DRAFT, SUBMITTED}` to the bar
  payload. A pre-approval bar renders with a distinct treatment on `SchedulePage` /
  `TaskBar`.
- **Clutter is self-limiting:** the schedule only shows *assigned/timed* work, so unassigned
  quote tasks never appear — only genuine pre-approval work someone chose to assign does,
  and it's flagged.
- **The board's in-progress *job* lane is a *job* surface** — recommended to leave it
  **unchanged**: a quote-stage job should not be promoted into the in-progress lane just
  because a site visit happened. The job is still a quote; its pre-approval work shows on the
  schedule and on the job's own card (in its actual lane), flagged.

## The open question (user deciding)

Whether — and how — the **in-progress board surface** should reflect pre-approval work,
given "the job is *not* in progress, but the work might be." Recommendation above is "work
shows on the schedule, flagged; the board's in-progress job-lane stays job-driven," but this
is the part to chew on before approving.

## Implementation sketch (once approved)

1. **Backend** — `apps/schedule/services.py`: broaden the three `job__status=IN_PROGRESS`
   filters to a work-active set that includes pre-approval statuses; derive and emit a
   `pre_approval` flag per bar from the task's job status. Confirm task **assignment** is
   permitted on pre-approval jobs (the assignment endpoint must not gate on job status).
   Tests in `tests/` for ScheduleService: a pre-approval job's assigned task produces a bar
   with `pre_approval=True`; an unassigned pre-approval task produces no bar.
2. **Frontend** — `frontend/src/routes/schedule/SchedulePage.svelte` +
   `frontend/src/components/schedule/TaskBar.svelte`: render the `pre_approval` flag
   distinctly (badge / hatch / muted accent — TBD with the user). Vitest coverage for the
   flagged bar.
3. **Board** — pending the open-question decision; likely no change.
4. **Docs** — update `docs/designs/schedule.md` to the work-driven framing.

## Absorbed LATER items (2026-07-04)

Moved from `docs/designs/LATER.md`: both are the same "does job status drive the surface, or does work?" axis as this plan's open board question — decide them together.

- **Should an on-hold job keep its place in the In Progress board area instead of dropping back to Pipeline?** — _added 2026-06-07_
  Currently putting a job on_hold moves it back to the Pipeline panel. But a job that was
  already being worked (approved / in_progress) and is paused for a change order is
  conceptually still "in the shop" — bouncing it to Pipeline loses its position and visual
  context, and it has to be re-found when work resumes. Consider keeping such a job in the
  In Progress area with an on-hold treatment (greyed/badged) so its place is preserved,
  while jobs that were never started stay in Pipeline. Interacts with the on-hold
  sub-status display above and the schedule's exclusion of on_hold jobs.
  _Done when:_ decided — either keep on_hold jobs in In Progress (implemented) or record why
  Pipeline is the right home.

- **Distinguish on-hold job varieties on the pipeline panel?** — _added 2026-05-27_
  An on-hold job shows a single "on-hold" sub-status. Consider surfacing whether it has a
  CO and the CO's state (none / draft / open / accepted-awaiting-release). May only matter
  while testing — decide if it's worth the extra signal.
  _Done when:_ decided (implemented or dropped).
