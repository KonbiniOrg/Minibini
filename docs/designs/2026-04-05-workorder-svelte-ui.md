# WorkOrder Detail Page + Task Materials + Subtasks — Svelte SPA

## Date: 2026-04-05

## Status

Design approved in brainstorm.

## Problem

The Svelte SPA links to `#/work-orders/{id}` from the job detail page, but
no page exists there. Task detail pages exist but show only bleps — no
materials, no subtasks. Workers need to see and manage materials and
subtasks on work order tasks, and managers need an overview of the full
work order with pricing.

## Goals

1. Build a WorkOrder detail page at `#/work-orders/:id` showing all Tasks
   with their Materials and Subtasks in a tree view, with pricing totals.
2. Add Material CRUD and Subtask display/creation to the existing Task
   detail page.
3. Wire existing service methods to new API endpoints for WO-side Material
   CRUD, subtask creation, task reordering, and add-from-template.
4. All task/material/subtask operations are `IsAuthenticated` (any worker).
   WO status transitions remain `can_manage_jobs`.

## Non-goals

- WO creation flows (done in Plan 2).
- Earmark lifecycle (done in Plan 3).
- Drag-and-drop reordering. Up/down arrows only.
- Inline editing. Modal-based only.
- PlanTask/worksheet UI (done in worksheet sub-project).

## API Endpoints

### Already existing

- `GET /api/work-orders/{id}/` — WO detail with nested `tasks`
- `GET/POST /api/work-orders/{id}/tasks/` — list/create Tasks
- `PATCH/DELETE /api/work-orders/{id}/tasks/{task_id}/` — update/delete
- `GET /api/tasks/{id}/` — standalone Task detail (TaskDetailSerializer)
- `POST /api/tasks/{id}/complete/` etc. — lifecycle actions
- `GET /api/task-templates/` — for template picker

### New endpoints

**Material CRUD on Tasks:**

- `GET /api/tasks/{id}/materials/` — list Materials for a Task
- `POST /api/tasks/{id}/materials/` — create Material
- `PATCH /api/tasks/{id}/materials/{mid}/` — update Material
- `DELETE /api/tasks/{id}/materials/{mid}/` — delete Material

Implementation: add material actions to `TaskViewSet` in
`apps/api/tasks/views.py`. Uses `InventoryService` for CRUD (needs new
WO-side material service methods — `create_material`, `update_material`,
`delete_material` targeting `Material` model, parallel to the existing
`create_plan_material` etc.).

Permissions: `IsAuthenticated` for all operations (workers record actuals).

**Subtask CRUD on Tasks:**

- `GET /api/tasks/{id}/subtasks/` — list child Tasks (where
  `parent_task=id`)
- `POST /api/tasks/{id}/subtasks/` — create child Task (auto-sets
  `parent_task` and `work_order` from parent)

Implementation: add subtask actions to `TaskViewSet`.

Permissions: `IsAuthenticated`.

**Reorder Tasks on WorkOrder:**

- `POST /api/work-orders/{id}/reorder/` — body:
  `{task_id, direction: "up"|"down"}`. Swaps sort_order with the
  adjacent task.

Implementation: add `reorder` action to `WorkOrderViewSet`.

Permissions: `IsAuthenticated`.

**Add Task from Template to WorkOrder:**

- `POST /api/work-orders/{id}/add-from-template/` — body:
  `{task_template_id, est_qty}`. Creates a Task on the WO from a
  TaskTemplate.

Implementation: add `add_from_template` action to `WorkOrderViewSet`.
Calls `TaskTemplate.generate_task(work_order, est_qty)`.

Permissions: `IsAuthenticated`.

## Svelte Components

### `WorkOrderDetailPage.svelte`

Route page at `#/work-orders/:id`. Responsible for:

- Fetching WO data via `GET /api/work-orders/{id}/`
- Fetching task templates for the "add from template" flow
- Fetching accounting categories for material modals
- Rendering header: WO ID, status badge, template name, link back to job
- Status action buttons (complete/block/reopen) — gated to `can_manage_jobs`
- Rendering `TaskTree` component with the WO's tasks
- "Add Task" and "Add from Template" buttons
- Reorder handlers calling the reorder API
- Modal state management for TaskModal, MaterialModal, SubtaskModal
- Pricing total footer

### `TaskTree.svelte` (shared/reusable)

Renders a list of Tasks as a tree with Materials and Subtasks. This
component is used on both the WO detail page (full task list) and the
Task detail page (subtasks of a single task).

Props: `tasks` (array), `readonly`, `showStatus` (default true),
`showAssignee` (default true), event callbacks for all actions.

**Layout:**

- **Task row:** name (linked to task detail), assignee, status pill,
  units, qty, rate, total
  - **Material sub-rows:** indented under task. Description, qty,
    unit cost, sell price, total. Edit/delete buttons.
  - **Subtask sub-rows:** indented under task. Same columns as task row.
    - **Subtask material sub-rows:** further indented.

**Columns:** Name | Assignee | Status | Units | Qty | Rate/Unit Cost |
Sell Price | Total | Actions

Task total: `est_qty * rate`. Material total: `quantity * sell_price`.
Task rate displays in the Sell Price column (same convention as worksheet
table). Grand total in footer.

**Action buttons** (visible when `!readonly`):
- Task row: edit, delete, add-material, add-subtask, up/down arrows
- Material row: edit, delete
- Subtask row: edit, delete, add-material (links to subtask detail for
  further subtask nesting if needed, but creation is flat — no nesting
  beyond one level in the UI)

### `TaskModal.svelte`

Modal for creating or editing a WO Task. Three modes:

- **Create freeform:** name, description, units (UnitsSelect), rate,
  est_qty, accounting_category. POST to
  `/api/work-orders/{id}/tasks/`.
- **Create from template:** template picker dropdown + est_qty. POST to
  `/api/work-orders/{id}/add-from-template/`.
- **Edit:** same fields as freeform, pre-populated. PATCH to
  `/api/work-orders/{id}/tasks/{task_id}/`.

Toggle between freeform/template at top of modal when creating.

### `MaterialModal.svelte`

Modal for creating or editing a WO Material. Same shape as
`PlanMaterialModal`:

- `price_list_item` — optional, via `PriceListItemPicker`
- `description` — disabled when PLI selected
- `quantity`
- `unit_cost` — disabled when PLI selected
- `sell_price` — disabled when PLI selected
- `accounting_category`

API: POST to `/api/tasks/{id}/materials/`, PATCH to
`/api/tasks/{id}/materials/{mid}/`.

### `SubtaskModal.svelte`

Simple modal for creating a child task. Fields: name, description, units,
rate, est_qty. POST to `/api/tasks/{id}/subtasks/`. The parent_task and
work_order are set automatically by the API.

### Updated `TaskDetailPage.svelte`

The existing page gets three additions between the task info table and
the blep list:

1. **Materials section:** Material rows for this task, with add/edit/delete.
   Uses `MaterialModal`.
2. **Subtasks section:** Rendered via `TaskTree` component, scoped to this
   task's children. Includes their materials. "Add Subtask" button opens
   `SubtaskModal`.
3. Both sections fetch data via the new API endpoints.

The existing blep list and task actions remain unchanged.

### Reused from worksheet sub-project

- `PriceListItemPicker.svelte` — as-is
- Field-level error display pattern in modals
- Modal structure and styling conventions

## Permissions

| Operation | Permission |
|---|---|
| View WO detail, task detail | `IsAuthenticated` |
| Add/edit/delete tasks on WO | `IsAuthenticated` |
| Add/edit/delete materials on tasks | `IsAuthenticated` |
| Add/edit/delete subtasks | `IsAuthenticated` |
| Reorder tasks on WO | `IsAuthenticated` |
| WO status transitions (complete/block/reopen) | `can_manage_jobs` |

Workers can manage their own task content. Only managers can change WO
status.

## Routing

Add to `App.svelte` routes:

```
'/work-orders/:id': WorkOrderDetailPage,
```

The existing `#/work-orders/{id}` link in `JobDetail.svelte` will start
working once this page exists. Task detail pages remain at
`#/jobs/:jobId/tasks/:taskId`.

## Service Layer

WO-side Material CRUD methods need to be added to `InventoryService` (or
the existing `create_material`/`update_material`/`delete_material` wrappers
need to be updated to target `Material` instead of `PlanMaterial`). These
are the WO-side equivalents of the plan material methods:

- `InventoryService.create_wo_material(task_pk, **kwargs)` — creates
  Material on a Task
- `InventoryService.update_wo_material(pk, **kwargs)` — updates Material
- `InventoryService.delete_wo_material(pk)` — deletes Material

These methods do NOT trigger earmark or inventory changes on their own.
Inventory consumption happens via `consume_material` during task lifecycle
transitions (existing behavior, unchanged).

## What This Enables

After this sub-project:

- Users can view and manage WorkOrders in the SPA with full task trees
  including materials and subtasks.
- Workers can add materials and subtasks to their assigned tasks.
- The job detail page's "View Full Work Order" link works.
- Task detail pages show the complete picture: task info, materials,
  subtasks, and bleps.
- The Django HTML work order views become legacy.

## Related

- `docs/designs/2026-04-05-worksheet-svelte-ui.md` — worksheet sub-project
  (parallel structure, completed)
- `docs/designs/2026-04-05-task-split-and-worksheet-to-workorder.md` —
  model split spec
- `docs/designs/2026-03-15-task-lifecycle-design.md` — task lifecycle
