# Task View and Blep Editing — Design

**Date:** 2026-04-04
**Status:** Draft, pending review
**Branch:** `feature/bleps`

## Goal

Give workers a real task detail page where they can see their work, drive the
task lifecycle, and manage their time entries (Bleps). Give managers the same
page with extra controls for editing anyone's time.

The currently-stub `frontend/src/routes/jobs/TaskDetailPage.svelte` becomes a
full page. A "Recent Time" section is added to the home page so workers can
find recent bleps to edit. The backend gains a top-level `BlepViewSet` and a
`BlepService`, and `TaskLifecycleService` is refactored to delegate all blep
writes to `BlepService` (eliminating inline `Blep.objects.create/.update`
calls from several lifecycle methods).

## Scope

**In scope:**
- Svelte task detail page with header, core info, action row, work sessions,
  subtasks list.
- Lifecycle actions (Start Work, Stop Work, Complete, Block, Unblock, Cancel)
  gated by status and permissions.
- Start-work multi-worker conflict modal (Join / Take over).
- Blep edit, delete, and historical create — scoped to the task view and the
  home page's Recent Time section.
- Two-level permission model: own bleps within 24 h vs. anyone's bleps with
  `can_manage_time`.
- Home page "Recent Time" list (last 7 days of user's own bleps), above the
  Expenses section.
- `BlepService` extraction + `TaskLifecycleService` refactor.
- New top-level `BlepViewSet` at `/api/bleps/`, eliminating the existing
  `GET /api/tasks/{id}/bleps/` action.

**Out of scope (Later):**
- Reassigning a blep to a different task.
- Reassigning a blep to a different user.
- Real "Request edit" flow — the button is a stub alert for this cycle.
- Pay-period-aware editable window — replaced by a simple rolling 24 h rule.
- Real-time updates to blep lists without refresh.
- Overlap detection surfaced as inline UI feedback beyond a 400 response.

## UI

### Routes

- **`/jobs/:jobId/tasks/:taskId`** — already registered in `App.svelte:38`
  pointing at a stub. This design fleshes it out.

No new routes. `/time` and similar were considered and rejected.

### Components

- **`frontend/src/routes/jobs/TaskDetailPage.svelte`** (replaces the stub)
  - On mount: `GET /api/tasks/{id}/` for the task (new retrieve endpoint,
    see API section) and `GET /api/bleps/?task={id}` for the blep list.
  - Composes: header, core info, `<TaskActions>`, `<BlepList>`, subtasks.
  - Owns a `refreshBleps()` callback passed to children.

- **`frontend/src/components/tasks/TaskActions.svelte`**
  - Props: `task`, `currentUser`, `userPermissions`, `activeBlep` (the user's
    currently-open blep if it belongs to *this* task, else null).
  - Renders the status-appropriate button set (see Action Visibility table).
  - Emits action events; the parent handles API calls and refresh.
  - On Start Work, the parent inspects the response; if it contains a
    `conflict` key, it opens `<StartWorkConflictModal>`.

- **`frontend/src/components/tasks/BlepList.svelte`**
  - Props: `bleps`, `currentUser`, `userPermissions`, `taskId`, `onRefresh`.
  - Table: worker, start, end (or "Active" badge), elapsed, actions.
  - Edit / Delete buttons per row, gated by `isBlepEditable(blep, user, perms)`.
  - "Add Entry" button at the bottom, available to any authenticated user
    (who will default to creating their own blep).
  - Opens `<BlepEditModal>` for Edit and Add.

- **`frontend/src/components/tasks/BlepEditModal.svelte`**
  - Modes: `create` (blank form, task_id known) and `edit` (prefilled from
    existing blep).
  - Fields: `start_time`, `end_time` (datetime-local inputs). A `user` field
    is hidden unless the caller has `can_manage_time`, in which case it's a
    dropdown of users.
  - On save: `POST /api/bleps/` (create) or `PATCH /api/bleps/{id}/` (edit).
  - On delete (edit only): `DELETE /api/bleps/{id}/` after a confirm step.
  - Calls `onRefresh()` on success.

- **`frontend/src/components/tasks/StartWorkConflictModal.svelte`**
  - Shown when `POST /api/tasks/{id}/start-work/` returns
    `{conflict: 'active_worker', worker, blep_id, started_at, options}`.
  - Displays the other worker's name and how long they've been active.
  - Buttons: **Join** (re-POST with `{action: 'join'}`), **Take over**
    (re-POST with `{action: 'takeover'}`), **Cancel** (close modal).

- **`frontend/src/components/home/RecentTimeList.svelte`** (new, home page,
  above Expenses)
  - Fetches `GET /api/bleps/?user=me&since=<7 days ago>` on mount (rolling
    7-day window, computed as `now - 7*24h`).
  - Same row layout as `<BlepList>`. For each row:
    - If editable (own blep, within 24 h): Edit / Delete buttons.
    - Else: **Request Edit** button — stub for this cycle (shows
      "Not implemented yet" alert).
  - Reuses `<BlepEditModal>` for edits.

### Action row visibility

Worker = any authenticated user. Manager = user with `can_manage_jobs`.

| Status | Worker sees | Manager additionally sees |
|---|---|---|
| pending | Start Work, Complete, Block | Cancel |
| in_progress, user is active worker | Stop Work, Complete, Block | Cancel |
| in_progress, user is not the active worker | Start Work (may prompt join/takeover), Complete, Block | Cancel |
| blocked | Unblock | Cancel |
| complete | *(read-only)* | *(read-only)* |
| cancelled | *(read-only)* | *(read-only)* |

Worker access to Complete / Block / Unblock is intentional: workers discover
these conditions, they should be able to signal them. Cancel is a scope
decision and stays manager-only.

### Permission data from the API

The Svelte `auth` store needs the current user's permission atoms (at least
`can_manage_jobs`, `can_manage_time`) to render button states correctly.
If `/api/auth/me/` does not already return these, this design adds them as
a small amendment.

## API

### New: top-level `BlepViewSet`

`apps/api/bleps/` — new module. Registered as
`router.register(r'bleps', BlepViewSet, basename='blep')`.

| Method + URL | Purpose | Permission |
|---|---|---|
| `GET /api/bleps/` | List bleps with optional filters. `?user=me` or `?user=<id>`; `?task=<id>`; `?since=<iso>`. Filters combine (AND). Paginated. | `IsAuthenticated` |
| `GET /api/bleps/{id}/` | Retrieve one blep. | `IsAuthenticated` |
| `POST /api/bleps/` | Create historical blep. Body: `{task, start_time, end_time, user?}`. `user` defaults to requesting user. | `IsAuthenticated` + rules below |
| `PATCH /api/bleps/{id}/` | Edit. | `IsAuthenticated` + rules below |
| `DELETE /api/bleps/{id}/` | Delete. | `IsAuthenticated` + rules below |

**Edit / delete / historical-create rules** (enforced in `BlepService`, not in
the serializer):

- Writing a blep for yourself (`user == request.user`):
  - If the blep's `start_time` is within the last 24 h (rolling, computed at
    request time): **allowed**.
  - Else: requires `can_manage_time`.
- Writing a blep for another user:
  - Requires `can_manage_time`.

Failures return HTTP 403 with a `detail` message. Validation failures
(overlap, end_before_start, worksheet task) return HTTP 400.

### Removed

- **`GET /api/tasks/{task_id}/bleps/`** — the `bleps` action on `TaskViewSet`
  is deleted. All blep listing goes through `GET /api/bleps/?task=<id>`.
  One URL, one code path.

### Modified

- **`TaskViewSet`** — add retrieve support so `GET /api/tasks/{id}/` returns
  the task + nested work_order + job references needed by the detail page.
  Either switch base class to include retrieve, or add an explicit retrieve
  method. A `TaskSerializer` lives in `apps/api/tasks/serializers.py` (new).
- **`BlepSerializer`** — moved from `apps/api/work_orders/serializers.py` to
  `apps/api/bleps/serializers.py`. `work_orders/serializers.py` updates its
  imports.

### Unchanged

- `POST /api/tasks/{id}/start-work/` — live-timer start, handles
  pending→in_progress promotion and multi-worker conflict.
- `POST /api/tasks/{id}/stop-work/` — live-timer stop.
- All other task lifecycle actions (complete, block, unblock, cancel).

## Service layer

### `BlepService` (new)

`apps/jobs/services/blep_service.py`.

**Primitives** (no validation; trusted callers only — used by
`TaskLifecycleService`):

- `_create(task, user, start_time, end_time=None)` — returns the new Blep.
- `_close_open(user=None, task=None, now=None)` — closes open bleps matching
  the given filters (at least one must be provided). Used in three ways:
  - `_close_open(user=u)` before `start_work` creates a new blep (enforces
    "one open blep per user across all tasks").
  - `_close_open(user=u, task=t)` for `stop_work` (close this user's open
    blep on this task).
  - `_close_open(task=t)` when a task transitions to complete, blocked, or
    cancelled (close every worker's open blep on this task).

**Public methods** (validated; used by the API):

- `create_historical(actor, task, start_time, end_time, target_user=None)`
  - `target_user` defaults to `actor`.
  - If `target_user != actor`: requires `actor.has_perm('core.can_manage_time')`.
  - Rejects worksheet tasks (task must have a `work_order`).
  - Rejects overlap with any existing blep of `target_user` (see Validation).
  - Applies the same 24 h rule to the `start_time` for non-manager actors
    (you cannot create a historical blep older than 24 h without
    `can_manage_time`).
- `update(blep, actor, **fields)` — allowed fields: `start_time`, `end_time`.
  - Enforces ownership + 24 h window OR `can_manage_time`.
  - Rejects overlap after applying the change.
- `delete(blep, actor)` — same ownership / window / manager rule.

`BlepService` raises `ValidationError` for data problems and a distinct
`PermissionError`-style exception (e.g., `BlepPermissionError`) for
authorization failures, which the viewset translates to 400 and 403
respectively.

### `TaskLifecycleService` refactor

No behavior change. Purely replacing inline blep writes with `BlepService`
calls:

- `start_work` — after status checks, call
  `BlepService._close_open(user=user)` then `BlepService._create(task, user)`.
- `stop_work` — call `BlepService._close_open(user=user, task=task)`.
- `complete_task`, `block_task`, `cancel_task` — replace inline
  `Blep.objects.filter(task=task, end_time__isnull=True).update(...)` with
  `BlepService._close_open(task=task)`.

Material consumption in `start_work` stays in `TaskLifecycleService` — it's
a task-state side effect, not a blep concern.

This refactor ships as its own commit ahead of the feature work, so the
existing `tests/test_task_lifecycle.py` suite validates the extraction
before any new behavior is added.

## Permissions model

Existing atoms (per `CLAUDE.md`):
- `can_manage_jobs` — already gates task edit/delete, job writes, etc.
- `can_manage_time` — already described as "Edit/delete anyone's time
  entries (shifts + bleps)". This design is the first real use of it.

**Task view actions** (TaskViewSet):
- Start Work, Stop Work, Complete, Block, Unblock, Cancel — all
  `IsAuthenticated`. This was set earlier in the branch.
- Retrieve (`GET /api/tasks/{id}/`) — `IsAuthenticated`.

**Blep endpoints** (BlepViewSet):
- List (`GET /api/bleps/`) — `IsAuthenticated`. All authenticated users can
  read all bleps (transparency on the team's work).
- Retrieve — `IsAuthenticated`.
- Create, update, delete — `IsAuthenticated` at the viewset level; the
  service layer applies the ownership + 24 h rule and the
  `can_manage_time` bypass.

**Manager-only affordances in the UI:**
- Cancel action on tasks (requires `can_manage_jobs`).
- Editing / deleting other users' bleps (requires `can_manage_time`).
- Editing / deleting own bleps older than 24 h (requires `can_manage_time`).
- Setting a non-self `user` when creating a historical blep (requires
  `can_manage_time`).

## Validation rules

All enforced in `BlepService`:

1. **End after start.** If `end_time` is set, it must be `>= start_time`.
2. **No overlap per user.** The target user must not have any existing blep
   whose `[start_time, end_time)` interval intersects the new or updated
   blep's interval. Open bleps (end_time IS NULL) are treated as
   `[start_time, now)` for this comparison. Two *different* users may have
   overlapping bleps on the same task — multi-worker collaboration is
   explicitly allowed.
3. **Work-order scope.** A blep's task must have a `work_order`. Worksheet
   tasks cannot have bleps.
4. **24 h rolling window** for non-manager actors:
   - On create: `now - start_time < 24h`.
   - On update: the blep's *current* `start_time` must be within 24 h of
     `now` before the update is allowed.
   - On delete: same as update.

## Testing strategy

**New test modules:**
- `tests/test_blep_service.py` — covers primitives and public methods.
  Includes: overlap rejection, end-before-start rejection, worksheet-task
  rejection, 24 h window (create/update/delete), manager bypass, cross-user
  create requires `can_manage_time`, deleting/editing another user's blep
  rejected without `can_manage_time`.
- `tests/test_api_bleps.py` — REST-layer integration. `GET /api/bleps/`
  with each filter (`user`, `task`, `since`) and combinations; retrieve;
  POST/PATCH/DELETE happy paths and permission-denied paths; 403 vs 400
  distinction.

**Updated existing tests:**
- `tests/test_task_lifecycle.py` — should pass unchanged after the
  `TaskLifecycleService` → `BlepService` delegation. Any diff here indicates
  a behavior regression in the refactor.
- `tests/test_task_lifecycle_api.py` — remove `test_bleps_list` (the
  endpoint it tests is being removed).
- `tests/test_atom_api_permissions.py` — add blep endpoints to the
  permission-list tests.

**Svelte tests:** component tests are out of scope for this cycle. Manual
verification against the dev stack is the acceptance gate.

## Data model

No model changes. `Blep` already has `user`, `task`, `start_time`,
`end_time` fields and the correct FKs (`on_delete=PROTECT` to preserve
audit trail). No migration needed.

## Open defaults

The spec sets these defaults. If any are wrong, flag before implementation:

- `GET /api/bleps/` with no filters returns all bleps (paginated).
  Alternative: require at least one filter.
- `POST /api/bleps/` with no `user` field defaults the blep's user to the
  requesting user.
- Manager deletes and edits don't send notifications (no notification
  infrastructure exists).
- `BlepSerializer` includes nested `task` and `job` references so the
  Recent Time list can render without extra fetches.
- The "Request Edit" button is a stub alert. No backend wiring.
