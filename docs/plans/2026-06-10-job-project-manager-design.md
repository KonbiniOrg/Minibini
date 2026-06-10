# Job Project Manager — Design

**Date:** 2026-06-10
**Status:** Approved, pending implementation plan

## Summary

Add an informational **project manager** to `Job`: a nullable FK to `User`. It carries
no business-logic side effects — it exists to record and display who owns a job, and to
support finding all jobs a given person manages. The only real work is plumbing the field
through the several places a Job is displayed.

## Scope

### In
- `Job.project_manager` FK to `User`.
- PM surfaced on: job detail header, job edit page, the board/schedule job chip, and the
  job list.
- PM name renders as a **link** to a filtered job list showing that person's managed jobs.
- A `?project_manager=<id>` filter on the jobs list endpoint, consumed by the SPA job list
  via `#/jobs?pm=<id>`.

### Out (explicitly, YAGNI)
- PM is **not** a searchable field in cross-entity search.
- **No** board-level PM filter control (the linked filtered list is the only filter path
  for now).
- **No** changes to legacy Django HTML views.
- **Not** shown on any customer-facing / print / PDF / email representation (PM is internal).
- **Not** added to job-as-reference displays on estimates, invoices, POs, tasks, etc.
- **Not** added to the full `JobCard` (the board Pipeline card and the chip hover-popup card)
  — PM lives on the chip itself, the detail header, and the list. Can be added to `JobCard`
  later if desired.

## Data model

```python
# apps/jobs/models.py — Job
project_manager = models.ForeignKey(
    'core.User',                 # same style as Task.assignee
    null=True, blank=True,
    on_delete=models.SET_NULL,
    related_name='managed_jobs',
)
```

- Informational only: no signals, no service side effects, no status interactions.
- No new permission atom. Reading/writing the field rides on existing job permissions
  (`can_manage_jobs` for edit; `IsAuthenticated` for read, same as the rest of the job).
- `on_delete=SET_NULL`: deactivating/removing a user must not cascade-delete jobs.
- A migration will be generated (`makemigrations`); the human applies it.

## Backend plumbing

| Touch point | Change |
|---|---|
| `apps/api/jobs/serializers.py` → `JobSerializer` | Add `project_manager` (writable PK) and `project_manager_name` (read-only display string). |
| Board job payload (whatever endpoint/serializer feeds `JobBoardPage` columns) | Add `project_manager_name` so the in-progress chips can render initials. |
| `apps/schedule/services.py` → `ScheduleService` jobs_payload | Add `project_manager_name` so schedule chips render initials. |
| Jobs list endpoint (`JobViewSet`) | Support `?project_manager=<id>` filter. |

Candidate-user source for the edit dropdown: the existing `/api/auth/users/` endpoint
(all active users) — reused as-is, same list used for assignee dropdowns. No PM-specific
permission narrowing.

`project_manager_name` is the display name; **initials are derived in the frontend** from it
(no separate initials field on the API).

## Frontend display surfaces

### 1. Board in-progress + Schedule top line — the chip
- File: `frontend/src/components/board/JobChipStrip.svelte` (shared by `ApprovedArea`
  on the board and `SchedulePage` on the schedule — one edit covers both).
- Render the PM **initials** in the chip's **top-right corner**, opposite the job number
  (top-left), in **black** (the job number stays grey).
- The chip's top line becomes a two-item row: job number left, initials right.
- Initials derived in-component from `project_manager_name`: first letter of the **first**
  word + first letter of the **last** word, uppercased (e.g. "Rachel McConnell" → "RM";
  "Mary Jane Watson" → "MW"). A single-word name yields one letter. No initials when there's
  no PM.
- `JobCard.svelte` (the hover-popup card) is left unchanged.

### 2. Job detail header
- File: `frontend/src/components/jobs/JobHeader.svelte`.
- Show the PM's name; the name is a **link** to `#/jobs?pm=<project_manager_id>`.
- Needs `project_manager` (id) + `project_manager_name` from `JobSerializer`.

### 3. Job edit
- File: `frontend/src/routes/jobs/JobEditPage.svelte`.
- Add a `<select>` (a "Project Manager" field, with a blank/none option) populated from
  `/api/auth/users/`, bound to a `projectManager` state seeded from `job.project_manager`,
  and included in the PATCH payload as `project_manager`.

### 4. Job list + filtered list
- Files: `frontend/src/routes/jobs/JobListPage.svelte`, `frontend/src/components/jobs/JobList.svelte`.
- Add a PM column; the PM name links to `#/jobs?pm=<id>`.
- The same page, when loaded with `?pm=<id>`, passes `project_manager=<id>` to the list
  endpoint and retitles to "Jobs managed by <Name>".

## Link behavior

PM name (header and list) → `#/jobs?pm=<project_manager_id>` → the job list filtered to that
manager's jobs. This is the single filtering mechanism in scope.

## Testing

- Backend: model field + migration; `JobSerializer` exposes `project_manager` /
  `project_manager_name`; jobs list honors `?project_manager=<id>`; schedule payload includes
  `project_manager_name`. TDD per project convention; tests use the separate test DB.
- Frontend (Vitest): chip renders black initials top-right derived from `project_manager_name`
  (and renders none when PM is absent); edit page submits `project_manager`; list/header PM
  links target `#/jobs?pm=<id>`; filtered list passes the param and retitles.

## Docs to update on completion

- `docs/designs/jobs-tasks-and-worksheets.md` — Job fields, job detail/header, board chips.
- `docs/designs/schedule.md` — schedule chip payload now includes `project_manager_name`.
- `docs/designs/data-constraints.md` — `Job.project_manager` field constraint row.
