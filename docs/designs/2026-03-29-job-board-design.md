# Job Board (Kanban Overview) Design

## Overview

A kanban-style board view for jobs, accessible from the Svelte SPA. Provides at-a-glance visibility into all current and recently-closed jobs, with a focus on the Approved column where active work happens. The primary use cases are **prioritizing work** and **assigning tasks to workers**.

## Layout

Three resizable columns with draggable vertical borders:

### Pipeline (left, narrow)
Combines Draft and Submitted jobs. Cards show job number, name, customer (clickable to contact detail), sub-status pill, and deadline. No task lists — these jobs don't have WorkOrders yet.

Sub-statuses derived from sub-object state:
- **Needs scoping** — no worksheet
- **Estimating** — worksheet in draft
- **Estimate ready** — worksheet finalized, estimate in draft
- **Awaiting response** — estimate is open, waiting on customer

### Approved (center, double-wide)
The main working area. Three zones stacked vertically:

**1. Job chip strip** (top, pinned)
Compact cards showing job number, name, and deadline. Customer and sub-status appear in a hover popover. Sorted by deadline (overdue first, then soonest). Color-coded with an accent stripe (8-color palette, recycled).

Sub-statuses for Approved jobs:
- **Needs work order** — no WorkOrder created
- **Work ready** — WorkOrder exists, no tasks started
- **In progress** — tasks are in progress
- **Blocked** — one or more tasks blocked
- **Invoice prepped** — WorkOrder complete, invoice auto-generated, needs review
- **Invoice sent** — invoice reviewed and sent

Hovering a job chip dims everything else in the Approved area and highlights that job's tasks across all worker columns and the unassigned pool. Tasks share the job's accent color via a left border stripe.

**2. Worker columns** (middle, resizable split with unassigned)
One column per worker who currently has tasks assigned. Each column has a header with avatar, name, and task count. Tasks within a column are ordered by `worker_queue` (see Data Model). A "+" button allows adding any active user as a new column.

Worker columns are derived — no flag on User. If all tasks are unassigned from a worker, the column can be removed. The column list is formed from users who have assigned tasks, plus any manually added via the "+" button.

**3. Unassigned pool** (bottom, resizable split with worker columns)
Grid layout of all tasks with no assignee, sorted by job deadline (overdue first). This is expected to be the largest area — workers typically have a day or two of assigned work, with the bulk of tasks sitting here.

A draggable horizontal divider separates the worker columns from the unassigned pool.

### Closed (right, narrow)
Combines Completed, Rejected, and Cancelled jobs. Cards show job number, name, customer, and a status pill distinguishing the terminal state. Jobs fall off after a configurable period (default: 2 weeks).

## Interactions

### Drag and drop
- Drag tasks from unassigned pool into a worker's column to assign
- Drag tasks between worker columns to reassign
- Drag tasks from a worker column back to unassigned to unassign
- Drag to reorder within a worker's column (updates `worker_queue`)

### Card click-through
- Clicking a job chip or job card navigates to the job detail page
- Clicking a customer name navigates to the contact detail page
- Clicking a task navigates to the job detail page (future: could scroll to task)

### Resizable borders
All column borders are draggable to resize:
- Left vertical: Pipeline vs Approved
- Right vertical: Approved vs Closed
- Horizontal (within Approved): Worker columns vs Unassigned pool

### Sorting
- **Pipeline**: by deadline (overdue first, soonest next, no-deadline at bottom)
- **Approved job chips**: by deadline (same rules)
- **Worker columns**: by `worker_queue` field
- **Unassigned pool**: by job deadline
- **Closed**: by closed date (most recent first), falls off after configurable retention

## Data Model Changes

### Task model additions

**`worker_queue`** — `PositiveIntegerField`, nullable, blank. The task's position within the assignee's queue on the board. Independent of `sort_order` (which is the position within the WorkOrder).

- Set when a task is dragged into a worker's column or reordered within it
- Nulled when a task is dragged back to unassigned or when assignee is cleared
- Integer renumbering within a worker's column on reorder (small lists, cheap operation)

No changes to `sort_order` — it remains the intra-WorkOrder ordering.

### Closed job retention

Uses an existing or new Configuration key (e.g., `board_closed_retention_days`, default `14`) to control how long terminal jobs appear on the board.

## Sub-status Derivation

Sub-statuses are computed, not stored. The API endpoint computes them from related object states:

```
For Draft/Submitted jobs:
  if no worksheet exists → needs-scoping
  if worksheet in draft → estimating
  if worksheet finalized and estimate in draft → estimate-ready
  if estimate is open → awaiting-response

For Approved jobs:
  if no WorkOrder exists → needs-work-order
  if WorkOrder exists, no tasks in_progress → work-ready
  if any task in_progress → in-progress
  if any task blocked → blocked (takes priority over in-progress)
  if WorkOrder complete, invoice exists but not sent → invoice-prepped
  if invoice sent → invoice-sent
```

## API

### Board endpoint

`GET /api/jobs/board/` — returns all data needed to render the board in a single request:

```json
{
  "pipeline": [/* jobs with sub_status, sorted by deadline */],
  "approved": {
    "jobs": [/* jobs with sub_status, accent_color, sorted by deadline */],
    "workers": [
      {
        "user": {"id": 1, "initials": "MR", "name": "Mike R."},
        "tasks": [/* tasks with job info, sorted by worker_queue */]
      }
    ],
    "unassigned": [/* tasks with job info, sorted by job deadline */]
  },
  "closed": [/* terminal jobs within retention period */]
}
```

### Task assignment/reorder endpoints

- `PATCH /api/tasks/{id}/` — update `assignee` and/or `worker_queue`
- `POST /api/tasks/reorder/` — bulk update `worker_queue` for a set of tasks (used after drag-reorder)

## Visual Design

### Color scheme
- **Pipeline column**: blue tint (`#f0f5ff`), blue accent (`#60a5fa`)
- **Approved column**: green tint (`#f0faf3`), green accent (`#4ade80`)
- **Closed column**: grey tint (`#f5f5f6`), grey accent (`#9ca3af`)
- **Column headers**: minimal — colored indicator bar, label, count. Bottom border accent.

### Job accent colors (8-color palette, recycled)
coral `#f97066`, amber `#f59e0b`, teal `#14b8a6`, violet `#8b5cf6`, sky `#38bdf8`, rose `#fb7185`, lime `#84cc16`, orange `#f97316`

### Task cards
- Left border stripe matches job accent color
- Status dot: grey (pending), blue+glow (in progress), red+glow (blocked)
- Blocked tasks on overdue jobs get a red-tinted background
- Task name (truncated), job label + deadline, status badge

### Sub-status pills
Each sub-status has a distinct background/text color combination for instant recognition. See mockups for specific values.

### Cards (Pipeline/Closed)
White cards with rounded corners, subtle shadow. Hover lifts with stronger shadow. Job number in monospace, name bold, customer as blue link, deadline with urgency coloring (red=overdue, amber=soon, grey=normal).

## Frontend Route

`/#/jobs/board` — new route in the Svelte SPA router.

The existing `/#/jobs` (list view) remains. The Board/Tasks/List toggle in the header allows switching between views.

## Permissions

Board is read-accessible to all authenticated users (same as job list). Task assignment and reordering require `can_manage_jobs`.

## Mockups

Interactive mockups from the brainstorming session are saved in `.superpowers/brainstorm/`. Key versions:
- `kanban-v13.html` — Option A: priority-grouped task grid with assignee filter pills
- `kanban-v15.html` — Option B (selected): worker columns with drag-and-drop assignment

## Out of Scope

- Task view (the second tab in the view toggle) — separate design
- Drag-and-drop to change job status (moving cards between Pipeline/Approved/Closed)
- Mobile/responsive layout
- Real-time updates (websockets) — page refresh or polling for now
- Inline task editing from the board
