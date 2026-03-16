# Task Lifecycle Design

**Date:** 2026-03-15
**Status:** Draft

## Overview

Tasks currently have no status field. Workers cannot start, stop, or complete tasks, and material consumption from inventory is never triggered despite the service methods existing. This design adds a task lifecycle that connects task status, time tracking (Bleps), and inventory consumption.

## Task Status Field

Add to the Task model:

```python
TASK_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('in_progress', 'In Progress'),
    ('blocked', 'Blocked'),
    ('complete', 'Complete'),
    ('cancelled', 'Cancelled'),
]
status = models.CharField(max_length=20, choices=TASK_STATUS_CHOICES, default='pending')
```

### Valid Transitions

```
pending → in_progress
pending → blocked
pending → complete
pending → cancelled
in_progress → blocked
in_progress → complete
in_progress → cancelled
blocked → in_progress
blocked → cancelled
```

No reopening of completed tasks. If rework is needed, create a new task — this preserves history.

## TaskLifecycleService

New service class in `apps/jobs/services.py`. All methods wrapped in `transaction.atomic()`. Approach: all side effects for a transition live in one service method — no signals.

### start_task(task_pk, user)

Transition: `pending → in_progress`

1. Validate task is `pending` and belongs to a WorkOrder (not a worksheet).
2. Validate the WorkOrder is not in `draft` status (must be at least `incomplete`).
3. Close any open Blep the user has on any task (enforces one active task per worker).
4. Set task status to `in_progress`.
5. Consume all associated Materials via `InventoryService.consume_material()`.
6. Create a Blep with `start_time=now()`, `user=user`.

No worker conflict check here — a `pending` task cannot have open Bleps. Conflicts only arise in `start_work` on `in_progress` tasks.

### complete_task(task_pk)

Transition: `pending → complete` or `in_progress → complete`

1. Validate task is `pending` or `in_progress`.
2. Close any open Bleps on this task (set `end_time=now()`).
3. Set task status to `complete`.
4. Check if all tasks on the WorkOrder are now `complete` or `cancelled`. If so, auto-complete the WorkOrder via `WorkOrderService.update_status()`.

Note: `pending → complete` supports retroactive Blep entry by managers (deferred feature). For now, the task is simply marked complete with no time records.

### block_task(task_pk)

Transition: `pending → blocked` or `in_progress → blocked`

1. Validate task is `pending` or `in_progress`.
2. Check for open Bleps on this task. If any exist, reject the request and return the active worker(s) info so the requester can coordinate offline.
3. Set task status to `blocked`.

### unblock_task(task_pk)

Transition: `blocked → in_progress`

1. Validate task is `blocked`.
2. Set task status to `in_progress`.
3. No Blep created — unblocking doesn't mean work resumes immediately.

### cancel_task(task_pk)

Transition: `pending → cancelled`, `in_progress → cancelled`, or `blocked → cancelled`

1. Validate task is `pending`, `in_progress`, or `blocked`.
2. Close any open Bleps on this task. (Unlike `block_task`, cancellation is a higher-authority action that overrides active work — workers are not given the option to continue.)
3. Set task status to `cancelled`.
4. Check if all tasks on the WorkOrder are now `complete` or `cancelled`. If so, auto-complete the WorkOrder.

### start_work(task_pk, user)

No status change. Task must be `in_progress`.

1. Validate task is `in_progress`.
2. Close any open Blep the user has on any task.
3. Check if another user has an open Blep on this task.
   - If yes: return conflict info (same pattern as `start_task`).
4. Create a Blep with `start_time=now()`, `user=user`.

### stop_work(task_pk, user)

No status change.

1. Find the user's open Blep on this task (a Blep with `end_time=null`).
2. Set `end_time=now()`.

## Worker Conflict Handling

When `start_work` detects another user has an open Blep on the same task, the response includes:

```json
{
    "conflict": "active_worker",
    "worker": {"user_id": 5, "name": "Ben Nakamura"},
    "blep_id": 42,
    "started_at": "2026-03-15T09:30:00Z",
    "options": ["join", "takeover"]
}
```

This is a 200 response — it's a normal business case, not an error. The client presents the options and re-calls the same endpoint with an `"action"` field:

- `"action": "join"` — create the new Blep alongside the existing worker's. Both workers are now active on the same task simultaneously.
- `"action": "takeover"` — close the other worker's open Blep (setting `end_time=now()`), then create the new Blep. The previous worker is effectively clocked out.

When `block_task` detects open Bleps, the response includes the same worker info but with no options — the requester must coordinate offline to get the worker to stop first.

## WorkOrder Auto-Completion

When a task is completed or cancelled, the service checks whether all tasks on the WorkOrder are in a terminal state (`complete` or `cancelled`). If so, the WorkOrder is automatically marked `complete` via `WorkOrderService.update_status()`, which preserves history tracking.

This means in normal workflow, manual WO completion is unnecessary — the last task drives it.

**Prerequisite:** `WorkOrderService.update_status()` currently has no transition validation — it accepts any status from any state. Before implementing auto-completion, add transition validation (either in the service or in `WorkOrder.clean()`) to prevent invalid transitions like `draft → complete`. This aligns with how `Job.clean()` already works.

## API Endpoints

Task lifecycle actions are nested actions on the existing `WorkOrderViewSet`, registered alongside the existing `TaskBundleMixin` routes. They are **not** `StatusTransitionMixin` entries — the mixin operates on the viewset's own model (WorkOrder), while these act on nested Task objects and need user context and conflict response handling.

Implementation: a dedicated `TaskLifecycleMixin` (similar to the existing `TaskBundleMixin`) with `@action` methods using explicit `url_path` patterns like `tasks/(?P<task_id>[0-9]+)/start`. These must not collide with the existing `TaskBundleMixin.task_detail` route which handles PATCH/DELETE at `tasks/(?P<task_id>[0-9]+)` — the trailing action segment keeps them distinct.

All lifecycle actions validate that the task belongs to a WorkOrder that is not in `draft` status. Use `select_for_update()` on the Task row within the transaction to prevent TOCTOU race conditions on concurrent operations (consistent with the existing `NumberGenerationService` pattern).

```
POST /api/work-orders/{pk}/tasks/{task_id}/start/
POST /api/work-orders/{pk}/tasks/{task_id}/complete/
POST /api/work-orders/{pk}/tasks/{task_id}/block/
POST /api/work-orders/{pk}/tasks/{task_id}/unblock/
POST /api/work-orders/{pk}/tasks/{task_id}/cancel/
POST /api/work-orders/{pk}/tasks/{task_id}/start-work/
POST /api/work-orders/{pk}/tasks/{task_id}/stop-work/
```

`start/` and `start-work/` use the authenticated user from the request. Both accept an optional `"action"` field (`"join"` or `"takeover"`) for resolving worker conflicts.

Read-only Blep listing:

```
GET /api/work-orders/{pk}/tasks/{task_id}/bleps/
```

Bleps are created and closed through lifecycle actions only — no direct Blep CRUD for now.

## Blep Behavior Summary

Bleps are individual work sessions. A task accumulates multiple Bleps over its lifetime as workers start and stop work.

- One worker can only have one open Blep at a time across all tasks.
- Starting work on a new task auto-closes the worker's previous open Blep.
- Multiple workers can have open Bleps on the same task simultaneously (the "join" option).

## Scope of Task Status

The status field lives on the Task model, which is used in both EstWorksheets (planning) and WorkOrders (execution). Lifecycle operations (`start_task`, `block_task`, etc.) are only valid on WorkOrder tasks. Worksheet tasks remain `pending` — they're planning artifacts that never get started or completed.

## Naming Convention

Task status uses `'complete'` (not `'completed'`), consistent with the WorkOrder model. The Job model uses `'completed'` — this divergence is intentional and already established in the codebase. Service methods raise `ValidationError` for invalid transitions, consistent with existing service patterns.

## Deferred Features

1. **Material reconciliation on task completion** — compare actual material usage to what was consumed at start. Requires material editing while task is `in_progress`. Worker edits quantities on Materials during the task; on completion, `InventoryService.complete_task_adjustment()` reconciles the difference.
2. **Block/unblock reasons with history** — capture why a task was blocked, support multiple block/unblock cycles with a persistent record.
3. **Retroactive Blep entry** — manager can add Bleps to completed tasks after the fact (supports the `pending → complete` path with time records).
4. **Manual WO completion by managers** — permission-gated override to complete a WO regardless of task states.
5. **Takeover notifications** — notify a worker when another worker closes their Blep via a takeover action. Requires a push notification system which does not yet exist.
6. **Parent/subtask lifecycle interactions** — the Task model supports hierarchy via `parent_task`. This design treats each task's lifecycle independently. Future work could auto-complete a parent when all subtasks are done, or prevent a parent from starting before subtasks are ready.
