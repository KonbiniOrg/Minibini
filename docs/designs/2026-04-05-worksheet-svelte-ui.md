# Worksheet Detail Page — Svelte SPA

## Date: 2026-04-05

## Status

Design approved in brainstorm.

## Problem

The Svelte SPA links to `#/worksheets/{id}` from the job detail page, but no
page exists there. Worksheet management (PlanTasks, PlanBundles, PlanMaterials)
currently lives in Django HTML views only. The SPA needs a worksheet detail
page with full task/bundle/material management and pricing visibility.

## Goals

1. Build a worksheet detail page at `#/worksheets/:id` showing all PlanTasks,
   PlanBundles, and PlanMaterials with pricing totals.
2. Wire the existing `WorksheetService` and `InventoryService` methods to new
   API endpoints for operations not yet exposed (PlanMaterial CRUD, reordering,
   add-from-template).
3. Support task creation (freeform and from template), bundle management, and
   material management via modal-based editing.
4. Gate all editing to draft worksheets + `can_manage_jobs` permission.
5. Extract a reusable `PriceListItemPicker` component for use in the future
   WO materials UI.

## Non-goals

- WorkOrder detail page (sub-project A).
- Task subtasks / hierarchy UI (sub-project A).
- Material management on WO Tasks (sub-project A).
- Inline/spreadsheet-style editing. Modal editing only for this pass.
- Drag-and-drop reordering. Up/down arrows only.

## API Endpoints

### Already existing (from Plan 1 + Plan 2)

These require no changes:

- `GET /api/est-worksheets/{id}/` — worksheet detail with nested `tasks` and
  `bundles` (via `EstWorksheetSerializer`)
- `GET/POST /api/est-worksheets/{id}/tasks/` — list/create PlanTasks
- `PATCH/DELETE /api/est-worksheets/{id}/tasks/{task_id}/` — update/delete
- `GET/POST /api/est-worksheets/{id}/bundles/` — list/create PlanBundles
- `PATCH/DELETE /api/est-worksheets/{id}/bundles/{bundle_id}/` — update/delete
- `POST /api/est-worksheets/{id}/bundles/{bundle_id}/add-tasks` — assign
- `POST /api/est-worksheets/{id}/bundles/{bundle_id}/remove-tasks` — unassign
- `POST /api/est-worksheets/{id}/generate-estimate` — generate estimate
- `GET /api/plan-tasks/{id}/` — standalone PlanTask detail with materials

### New endpoints

**PlanMaterial CRUD** — nested under PlanTask:

- `GET /api/plan-tasks/{id}/materials/` — list PlanMaterials for a PlanTask
- `POST /api/plan-tasks/{id}/materials/` — create PlanMaterial
- `PATCH /api/plan-tasks/{id}/materials/{mid}/` — update PlanMaterial
- `DELETE /api/plan-tasks/{id}/materials/{mid}/` — delete PlanMaterial

Implementation: add a `PlanMaterialMixin` to `PlanTaskViewSet` (or inline the
actions). Uses `InventoryService.create_plan_material`,
`update_plan_material`, `delete_plan_material`.

Permissions: `GET` requires `IsAuthenticated`. `POST/PATCH/DELETE` requires
`IsAuthenticated` + `CanManageJobs`.

**Reorder actions** — on EstWorksheetViewSet:

- `POST /api/est-worksheets/{id}/reorder/` — body: `{item_type: "task"|"bundle", item_id, direction: "up"|"down"}`. Calls `WorksheetService.reorder_items`.
- `POST /api/est-worksheets/{id}/reorder-in-bundle/` — body: `{task_id, direction: "up"|"down"}`. Calls `WorksheetService.reorder_in_bundle`.

Permissions: `IsAuthenticated` + `CanManageJobs`.

**Add task from template** — on EstWorksheetViewSet:

- `POST /api/est-worksheets/{id}/add-from-template/` — body: `{task_template_id, est_qty}`. Calls `WorksheetService.add_task_from_template`. Returns the created PlanTask.

Permissions: `IsAuthenticated` + `CanManageJobs`.

## Svelte Components

### `WorksheetDetailPage.svelte`

Route page at `#/worksheets/:id`. Responsible for:

- Fetching worksheet data via `GET /api/est-worksheets/{id}/`
- Fetching task templates for the "add from template" flow via
  `GET /api/task-templates/`
- Rendering the header: worksheet version, status badge, link back to
  job (`#/jobs/{job_id}`), "Generate Estimate" button (draft/final only)
- Rendering the `WorksheetTaskTable` component
- Holding modal open/close state for all modals
- Providing a `reload()` function that re-fetches after any mutation

### `WorksheetTaskTable.svelte`

The main table display. Props: worksheet data (tasks, bundles), readonly
flag, event callbacks.

**Layout:**

The table merges PlanTasks and PlanBundles into a single ordered list using
`sort_order`. Each entry is one of:

- **Unbundled task row:** name, units, qty, rate, line total
  (`est_qty * rate`). Action buttons: edit, delete, add material,
  up/down, move-to-bundle dropdown.
- **Bundle header row:** name, accounting category, bundle total (sum of
  its task line totals + material totals). Action buttons: edit, delete,
  up/down.
  - **Bundled task rows:** indented under the bundle header. Same columns
    as unbundled tasks minus the move-to-bundle dropdown; instead has a
    "remove from bundle" action. Up/down reorders within the bundle.
- **Material sub-rows:** beneath their parent task (whether bundled or
  not). Visually distinct — indented, lighter styling. Columns:
  description, qty, unit cost, sell price, line total
  (`quantity * sell_price`). Action buttons: edit, delete.

**Footer row:** grand total across all tasks and materials.

**Sorting logic:** builds a flat display list by iterating the worksheet's
tasks and bundles. Unbundled tasks (those with `bundle == null`) and bundles
are sorted together by `sort_order`. Bundled tasks are nested under their
bundle, sorted by their own `sort_order`.

### `PlanTaskModal.svelte`

Modal for creating or editing a PlanTask. Three modes:

- **Create freeform:** fields — name, description, units (UnitsSelect),
  rate, est_qty, accounting_category. Submits `POST .../tasks/`.
- **Create from template:** template picker (dropdown of task templates),
  est_qty. Submits `POST .../add-from-template/`.
- **Edit:** same fields as freeform, pre-populated. Submits
  `PATCH .../tasks/{id}/`.

Toggling between freeform and template creation via a tab or radio at the
top of the modal.

### `PlanBundleModal.svelte`

Modal for creating or editing a PlanBundle. Fields: name, description,
accounting_category. Submits `POST .../bundles/` or `PATCH .../bundles/{id}/`.

### `PlanMaterialModal.svelte`

Modal for creating or editing a PlanMaterial. Fields:

- `price_list_item` — optional, via `PriceListItemPicker` (searchable)
- `description` — free text (auto-filled from PLI if selected)
- `quantity`
- `unit_cost` (auto-filled from PLI `purchase_price`)
- `sell_price` (auto-filled from PLI `selling_price`)
- `accounting_category` — optional dropdown

Auto-fill behavior: when a PLI is selected, copy the PLI's description,
purchase_price (→ unit_cost), and selling_price (→ sell_price) into the
form fields and **disable those fields** (greyed out, not editable). The
PLI is the source of truth for those values. If the user sets the picker
back to "none", the fields are re-enabled and editable (cleared to
defaults so the user fills them in manually). This makes the distinction
between PLI-linked and freeform materials visually unambiguous.

Submits `POST /api/plan-tasks/{id}/materials/` or
`PATCH /api/plan-tasks/{id}/materials/{mid}/`.

### `PriceListItemPicker.svelte` (shared/reusable)

A searchable dropdown for selecting a PriceListItem. Fetches from
`GET /api/price-list-items/?search={query}` with debounced input. Displays
code + description in the dropdown. Emits the selected PLI object (or null
for "none / freeform").

This component will be reused in sub-project A for WO-side materials.

**Scaling note:** The picker loads the entire PLI catalog on first focus
and filters client-side. This is fine for catalogs up to a few hundred
items (the expected size). If the catalog grows very large (1000+), this
should switch to server-side search by adding `SearchFilter` to
`PriceListItemViewSet` and using `?search=query` with debounced input.

## Permissions

All mutations (create, edit, delete, reorder, add-from-template, generate
estimate) require:

- Worksheet must be in `draft` status (API returns 400 otherwise)
- User must have `can_manage_jobs` permission (API returns 403 otherwise)

Read access (viewing the page, fetching data) requires `IsAuthenticated`
only — any logged-in user can view a worksheet.

The SPA checks `$user.permissions.includes('can_manage_jobs')` to
conditionally render action buttons, matching the existing pattern in
`JobDetail.svelte`.

## Routing

Add to `App.svelte` routes:

```
'/worksheets/:id': WorksheetDetailPage,
```

The existing `#/worksheets/{id}` links in `JobDetail.svelte` will start
working once this page exists.

## Pricing Display

- **Task line total:** `est_qty * rate` (may be null if rate or qty is
  unset; display as `—`)
- **Material line total:** `quantity * sell_price`
- **Bundle total:** sum of all task line totals + all material line totals
  within the bundle
- **Grand total:** sum of all task line totals + all material line totals
  across the entire worksheet

All prices displayed as currency with 2 decimal places.

## What This Enables

After this sub-project:

- Users can fully manage worksheets in the SPA: create tasks (freeform or
  from templates), organize into bundles, add materials with optional PLI
  linkage, reorder, and see the full pricing picture before generating an
  estimate.
- The Django HTML worksheet views become legacy — they still work but are
  no longer the primary UI.
- Sub-project A (WorkOrder detail + Task materials + subtasks) can reuse
  `PriceListItemPicker` and follow the modal patterns established here.

## Related

- `docs/designs/2026-04-05-task-split-and-worksheet-to-workorder.md` —
  model split spec (PlanTask, PlanBundle, PlanMaterial)
- `docs/designs/2026-03-06-material-pli-lifecycle.md` — material lifecycle
- `docs/plans/2026-04-05-materials-in-svelte-and-workorders.md` — parent
  project starter doc
