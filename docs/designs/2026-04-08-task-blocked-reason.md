# Task Blocked Reason

## Problem

When a task is blocked, other users have no way to see why. The frontend prompts for a reason but the API endpoint discards it. The reason needs to be stored on the task and visible on the board and task detail page.

## Design

### Model

Add `blocked_reason` (TextField, blank=True, default='') to Task. This is current state, not history — it holds the reason for the current blockage. Cleared when the task leaves blocked status.

### Service Layer

`TaskLifecycleService.block_task(task_pk, reason='')` accepts a reason parameter and stores it on the task.

The following methods clear `blocked_reason` when transitioning out of blocked:
- `unblock_task` (blocked -> in_progress)
- `complete_task` (can transition from blocked -> complete)
- `cancel_task` (can transition from blocked -> cancelled)

### API

`TaskViewSet.block()` extracts `reason` from `request.data` and passes it to the service. The reason is optional.

### Frontend

- **TaskCard** (board): When task is blocked and has a `blocked_reason`, show it as small text on the card.
- **TaskDetailPage**: Show `blocked_reason` in the task info when the task is blocked.
- **TaskActions**: No change needed — already prompts for reason and sends it.

### Not In Scope

- `@history` decorator on Task (separate effort — requires converting `.update()` calls to `.save()` throughout TaskLifecycleService)
- History panel on task detail page
- Block reasons on WorkOrders
