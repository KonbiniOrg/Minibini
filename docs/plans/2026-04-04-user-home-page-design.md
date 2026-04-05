# User Home Page — Design

Date: 2026-04-04
Status: Design (pre-implementation)

## Purpose

Replace the placeholder `Home.svelte` with a useful default landing page for authenticated users, and introduce a **global** in-progress Blep band that appears on every SPA page whenever the user is clocked in.

Primary audience is workers using phones in the field. The band must make it easy to stop the current Blep from anywhere in the app.

## Scope

### In scope

1. Global sticky **Current Blep Band** — rendered by `App.svelte` above the router outlet. Visible on every page when the user has an open Blep; hidden entirely otherwise.
2. **Home page** vertical stack:
   - Search box (input + button)
   - Assigned Tasks list (with Start Work / Up / Down per row)
   - Recent Jobs list
3. New **SPA Search route** (`#/search?q=...`) — minimal list of results from `/api/search/`.
4. **Stub** SPA Task Detail route (`#/jobs/:jobId/tasks/:taskId`) — placeholder only.
5. New backend endpoints: `GET /api/home/`, `GET /api/bleps/current/`.
6. Relax permission on existing `POST /api/tasks/reorder/` to `IsAuthenticated` (no ownership check).

### Out of scope

- Real `TaskDetailPage` content (stub only this pass).
- Polished Search results UX (grouping, filters, pagination).
- Cross-device Blep synchronization (polling, push, session invalidation).
- "Log out other devices on login elsewhere" behavior.
- User-configurable home page.
- Expenses, announcements, notifications, calendar widgets.
- Enforcing single-open-Blep-per-user server side. This is assumed to be handled by `TaskLifecycleService.start_work` per the existing intended design; if it isn't yet, fixing it is not part of this spec.

## Architecture

### Global Current Blep Band

- Lives in `App.svelte`, rendered above the router outlet.
- Backed by a new Svelte store `frontend/src/stores/currentBlep.js` holding `{ id, start_time, task, job, work_order } | null`.
- Data source: `GET /api/bleps/current/` returning the requesting user's most recent open Blep (`end_time IS NULL`, ordered by `start_time DESC`, limit 1), or `null`.
- `currentBlep.refresh()` is called:
  - Once in `App.svelte` after auth resolves
  - On every SPA route change
  - After any action that starts or stops a Blep
- `currentBlep.stop()` calls the existing stop-work endpoint using the task/work-order IDs already in the store, then refreshes.
- **No periodic polling.** A stale band across devices is an accepted trade-off for this iteration.
- Sticky via `position: sticky; top: 0;`. No placeholder when null — the band simply does not render.

### Home page

- `frontend/src/routes/Home.svelte` replaces the current placeholder.
- On mount, fetches `GET /api/home/` which returns `{ assigned_tasks, recent_jobs }`.
- Renders three children in a vertical stack:
  1. `SearchBox.svelte`
  2. `AssignedTaskList.svelte`
  3. `RecentJobsList.svelte`
- Loading state: `<p>Loading...</p>` (matches existing convention in `App.svelte:44`, `JobListPage`, `JobBoardPage`, `JobDetailPage`, `BusinessListPage`). Error state: plain error message.
- The current-blep band is **not** rendered by `Home.svelte` — it's global.

### Search

- `SearchBox.svelte`: a `<form>` containing one text input and a submit button. Submit navigates to `#/search?q=<encoded value>`. No fetch from the home page.
- `frontend/src/routes/Search.svelte`: reads `q` from the query string, fetches `/api/search/?q=...` on mount and whenever `q` changes, renders results as a plain list with links to each entity. Empty `q` → no fetch.
- No grouping, filters, or pagination — polish deferred.

### Task Detail (stub)

- New route `#/jobs/:jobId/tasks/:taskId` → `frontend/src/routes/jobs/TaskDetailPage.svelte`.
- Stub content: heading, task id, "Task detail — coming soon", and a link back to the job.
- Exists so Start Work has a real place to land and so a future spec can flesh it out without revisiting routing.

### Task reorder endpoint

- `POST /api/tasks/reorder/` (`apps/api/jobs/board_views.py::task_reorder_view`) permission relaxed from `[IsAuthenticated, CanManageJobs]` to `[IsAuthenticated]`. No ownership check. Any authenticated user may reorder any tasks. This trade-off is accepted for simplicity.

## Components

### Frontend

**`frontend/src/stores/currentBlep.js`** *(new)*
- `$state` holding the current blep object or `null`.
- `refresh()` — fetch `/api/bleps/current/`, update state.
- `stop()` — POST to stop-work endpoint for the current task/work-order, then refresh.

**`frontend/src/components/CurrentBlepBand.svelte`** *(new, global)*
- Subscribes to `currentBlep` store; renders nothing when `null`.
- When active: shows task description, job number + name (link to job), auto-ticking elapsed time (`setInterval` cleared on unmount), and a Stop button.
- `position: sticky; top: 0;` with a solid background so page content scrolls under it cleanly.
- On stop-work error, shows a plain inline error inside the band and leaves the blep visible.

**`frontend/src/routes/Home.svelte`** *(replaces placeholder)*
- Fetches `/api/home/` on mount.
- Renders `SearchBox`, `AssignedTaskList`, `RecentJobsList` in order.

**`frontend/src/components/home/SearchBox.svelte`** *(new)*
- `<form>` with one `<input type="text">` and a submit `<button>`.
- Submit navigates to `#/search?q=<encoded value>`.

**`frontend/src/components/home/AssignedTaskList.svelte`** *(new)*
- Takes `tasks` as a prop.
- Each row renders:
  - Task description
  - Plain-text status indicator (e.g. "blocked")
  - Job number + name (link to `#/jobs/:jobId`)
  - **Start Work** button
  - **Up** button (disabled on first row)
  - **Down** button (disabled on last row)
- Up/Down: swap adjacent rows in local state optimistically, then `POST /api/tasks/reorder/` with the full new ordering. On error, revert and show an inline error. Buttons disabled during the in-flight request.
- Start Work: `POST /api/work-orders/<wo_id>/tasks/<task_id>/start-work`, then `currentBlep.refresh()`, then navigate to `#/jobs/<job_id>/tasks/<task_id>`. On error, show inline error; no navigation.

**`frontend/src/components/home/RecentJobsList.svelte`** *(new)*
- Takes `jobs` as a prop.
- Plain list. Each item: job number + name as a link, plus a "last worked" timestamp.

**`frontend/src/routes/Search.svelte`** *(new)*
- Reads `q` from the query string.
- Fetches `/api/search/?q=...` on mount and when `q` changes.
- Renders a plain list with links to each result's entity page.

**`frontend/src/routes/jobs/TaskDetailPage.svelte`** *(new, stub)*
- Reads `jobId` and `taskId` from route params.
- Renders a heading, the task id, placeholder text, and a link back to the job. No API calls.

**`frontend/src/App.svelte`** *(modified)*
- Import and mount `<CurrentBlepBand />` above the router outlet.
- After auth resolves, call `currentBlep.refresh()`.
- Trigger `currentBlep.refresh()` on route change.
- Register new routes: `/search`, `/jobs/:jobId/tasks/:taskId`.

**`frontend/src/lib/api.js`** *(modified)*
- Add helpers matching existing naming conventions in that file:
  - `getHome()` → `GET /api/home/`
  - `getCurrentBlep()` → `GET /api/bleps/current/`
  - `stopWorkOnTask(workOrderId, taskId)` → `POST /api/work-orders/:woId/tasks/:taskId/stop-work`
  - `startWorkOnTask(workOrderId, taskId)` → `POST /api/work-orders/:woId/tasks/:taskId/start-work`
  - `reorderTasks(taskIds)` → `POST /api/tasks/reorder/`
  - `searchAll(q)` → `GET /api/search/?q=...`

### Backend

**`HomeService`** *(new, location TBD between `apps/core/services.py` and a dedicated module; chosen at plan time based on current file size)*
- `get_home_data(user) -> dict`
- Returns `{"assigned_tasks": [...], "recent_jobs": [...]}`.
- `assigned_tasks` query:
  - `assignee = user`
  - Task belongs to a `WorkOrder` (not an `EstWorksheet`) — i.e. the WorkOrder FK is set and the EstWorksheet FK is not.
  - Status excludes the "completed" terminal state (exact constant verified against `Task` model at implementation time).
  - Ordered by `worker_queue` ascending.
  - Includes both in-progress, blocked, and any other non-completed states.
- `recent_jobs` query:
  - Distinct `Job`s where the user has at least one `Blep`.
  - Ordered by most recent Blep `start_time` descending.
  - Limit 10.
  - Each item includes `job_number`, `name`, and the timestamp of the user's most recent Blep on that job.

**`home_view`** *(new, `apps/api/core/home_views.py`)*
- Function-based DRF view, `@permission_classes([IsAuthenticated])`.
- Thin wrapper that calls `HomeService.get_home_data(request.user)` and serializes the result.

**`current_blep_view`** *(new, location alongside existing blep code in `apps/api/jobs/`)*
- Function-based DRF view, `@permission_classes([IsAuthenticated])`.
- Returns `{ id, start_time, task: {id, description}, job: {id, job_number, name}, work_order: {id} }` for the user's most recent open Blep, or `null`.

**`task_reorder_view`** *(modified, `apps/api/jobs/board_views.py`)*
- Permissions change from `[IsAuthenticated, CanManageJobs]` to `[IsAuthenticated]`.
- Docstring updated to note that any authenticated user may reorder.

**URLs** *(modified, `apps/api/urls.py`)*
- Register `home/` → `home_view`
- Register `bleps/current/` → `current_blep_view`

**Serializers** *(new, in the appropriate `apps/api/*/serializers.py`)*
- Small serializers for `HomeAssignedTask`, `HomeRecentJob`, `CurrentBlep` — or reuse existing Task/Job/Blep serializers if they already project the needed fields compactly.

## Data flow

### Home page load
1. `App.svelte` resolves auth → mounts layout including `<CurrentBlepBand />`.
2. `currentBlep.refresh()` runs once.
3. Router mounts `Home.svelte`.
4. `Home.svelte` fetches `/api/home/`; shows `Loading...` until resolved.
5. On success, renders `SearchBox`, `AssignedTaskList`, `RecentJobsList`.

### Start Work (from a task row)
1. User taps Start Work on task T in work order W, job J.
2. Row posts to `/api/work-orders/W/tasks/T/start-work`.
3. On success: `currentBlep.refresh()`, then navigate to `#/jobs/J/tasks/T`.
4. On error: inline error on the row; no navigation.

### Stop Work (from the band)
1. User taps Stop in the band.
2. Band calls `currentBlep.stop()`, which posts to the stop-work endpoint for the current task/work-order.
3. On success: store sets current blep to `null`; band hides.
4. On error: inline error in the band; blep stays visible.

### Reorder (Up / Down)
1. User taps Up on row index `i` (`i > 0`).
2. Swap row `i` with row `i-1` in local state (optimistic).
3. Post full new ordering (array of visible assigned task IDs) to `/api/tasks/reorder/`.
4. On error: revert local swap; show inline error.
5. Buttons disabled while a reorder request is in flight.

### Search submit
1. User types, clicks button (or presses Enter).
2. Form navigates to `#/search?q=<encoded>`.
3. `Search.svelte` reads `q`, fetches `/api/search/?q=...`, renders plain list.

## Error handling

- Each widget owns its own error state; a failure in one does not break others.
- The band, being global, shows errors within itself without disturbing the page underneath.
- Network failures surface as plain inline text; no toasts, no modals (matches existing app conventions).

## Testing

### Backend
- `HomeService.get_home_data(user)`:
  - Only returns WorkOrder tasks, never EstWorksheet tasks.
  - Excludes completed tasks.
  - Includes blocked and in-progress tasks.
  - Orders by `worker_queue`.
  - Recent jobs: distinct, ordered by latest user-Blep timestamp, limited.
- `/api/home/`: returns correct shape, scoped to `request.user`, `IsAuthenticated` required.
- `/api/bleps/current/`: returns the user's most recent open Blep; returns `null` when none; scoped to `request.user`.
- `/api/tasks/reorder/`: callable by a regular authenticated user with no `CanManageJobs` (new test) — continues to work for managers (existing test).

### Frontend
- No Svelte test framework is currently wired up in the repo (to be verified at plan time). If absent, this spec does not add one; a manual QA checklist will be included in the implementation plan. If present, component tests for:
  - `AssignedTaskList` Up/Down disabling and reorder POST
  - Start Work click flow (mocked API)
  - `CurrentBlepBand` visibility based on store state
  - Stop flow

## Risks and open questions

- **Stale band across devices.** Accepted. A user clocking in on one device won't see the change on another until a navigation or explicit action triggers a refresh. May be revisited alongside a future session-management feature.
- **Reorder endpoint is world-writable among authenticated users.** Accepted for simplicity. Any authenticated user can rewrite any other user's queue. Not exposed in the UI beyond the home page's own queue, but the API itself does not enforce ownership.
- **`HomeService` location.** To be decided at implementation time based on current `apps/core/services.py` size. If that file is already doing a lot, a new module is preferred.
- **Exact field/status constants.** `worker_queue` (confirmed `apps/jobs/models.py:192`) and the completed-task status constant will be double-checked at implementation time against the current `Task` model to avoid drift.
- **Serializer reuse vs. new serializers.** Prefer reuse if compact; otherwise add small dedicated serializers. Decided at implementation time.

## Acceptance criteria

1. Logging in as a default-permission user lands on `Home.svelte`, which shows the three sections populated from `/api/home/`.
2. When the user has no open Blep, no band is visible on any page.
3. When the user has an open Blep, a sticky band appears at the top of **every** SPA page, showing task, job, and live elapsed time, with a working Stop button.
4. Tapping Start Work on an assigned task row starts a Blep, updates the band, and navigates to the stub task detail page.
5. Tapping Stop in the band ends the Blep and hides the band.
6. Up/Down buttons reorder the assigned-task list and persist via `/api/tasks/reorder/`. A worker without `CanManageJobs` can reorder successfully.
7. Tapping Search submits to `#/search?q=...` which renders a plain list of results from `/api/search/`.
8. The home page's assigned-task list excludes completed tasks but includes blocked tasks, and is ordered by `worker_queue`.
9. The recent-jobs list shows up to 10 jobs the user has had Bleps on, ordered by most recent Blep activity.
