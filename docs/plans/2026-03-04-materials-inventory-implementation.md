# Materials & Inventory Implementation Plan

## Context

Currently tasks handle both labor and materials, making the mapping to estimate/invoice line items awkward. This plan separates them: Tasks = labor, Materials = physical stuff consumed by a task. It also adds inventory earmarking, automatic QOH updates, and moves the PO-level job FK to line items.

Based on the design doc at `docs/2026-03-04-materials-and-inventory-design.md` and user decisions on open questions.

## Key Decisions Made

- **PO job FK**: Remove from PurchaseOrder, add to PurchaseOrderLineItem (line-item level only)
- **Consumption trigger**: Material consumed at **task start** (QOH decreases). At **task completion**, user confirms actual quantity; difference returned to stock.
- **Earmarking**: On **job approval** (estimate accepted), with user confirmation step
- **Material model location**: `apps/jobs/` (primary relationship is to Task)
- **Earmark model location**: `apps/inventory/` (about inventory state)
- **Material always requires a Task**: Pass-through items (no labor) get a zero-rate task. No dual-FK pattern on Material.
- **Material sources**: Can link to an InventoryItem (stocked), a PriceListItem (regularly purchased but not stocked), or neither (true one-off). Auto-fills description/cost/price from whichever source is linked.
- **Pass-through task auto-completion**: PO receipt auto-completes labor-free tasks when all their materials are received. Ad-hoc purchases (no PO) are completed manually.
- **Materials visibility**: Worksheet and work order views aggregate materials across all their tasks. No direct FK from Material to worksheet/work order — derived through the task relationship.

---

## Phase 1: Material Model

**Goal:** Add `Material` model to `apps/jobs/`, basic CRUD, worksheet versioning support.

### Model (`apps/jobs/models.py`)
```
Material:
  material_id    (AutoField, PK)
  task           (FK to Task, CASCADE, related_name='materials')
  inventory_item (FK to inventory.InventoryItem, SET_NULL, nullable)
  price_list_item (FK to invoicing.PriceListItem, SET_NULL, nullable)
  description    (CharField 255)
  quantity       (DecimalField 10.2)
  unit_cost      (DecimalField 10.2)
  sell_price     (DecimalField 10.2)
  Properties: total_cost (qty * unit_cost), total_sell (qty * sell_price)
  clean(): cannot have both inventory_item AND price_list_item
  save(): auto-fill description/unit_cost/sell_price from inventory_item or price_list_item if linked and fields are empty
```

### Changes
- `apps/jobs/models.py` — add Material class
- `apps/jobs/views.py` — add material_add, material_edit, material_delete views
- `apps/jobs/urls.py` — material URL patterns
- `apps/jobs/models.py` line ~365 — update `EstWorksheet.create_new_version()` to copy materials when copying tasks
- Templates for material add/edit, update task detail to show materials
- Update worksheet detail and work order detail templates to show aggregated materials list across all tasks

### Tests (`tests/test_material.py`)
- CRUD operations
- Auto-fill from inventory item (description, unit_cost, sell_price)
- Auto-fill from price list item (description, purchase_price, selling_price)
- Cannot have both inventory_item and price_list_item (validation error)
- Cascade on task delete, SET_NULL on inventory item or price list item delete
- Worksheet versioning copies materials

### Migration
- `apps/jobs/migrations/0034_material.py`

---

## Phase 2: Estimate Generation with Materials

**Goal:** `EstimateGenerationService` produces both labor and material line items.

### Design
- Direct-mapped tasks with labor (rate > 0): labor line item + N material line items
- Direct-mapped tasks without labor (rate is 0/null, pass-through): material line items only, no labor line item
- Bundled tasks: bundle line item includes material costs summed into the bundle price
- Excluded tasks: materials also excluded
- Material line items get a "MAT" LineItemType

### Changes
- `apps/jobs/models.py` — add optional `material` FK to EstimateLineItem (nullable, for traceability)
- `apps/jobs/services.py` — update `EstimateGenerationService`:
  - `_create_direct_line_item()` — skip if task has no rate (pass-through task)
  - Add `_create_material_line_item()` for each material on direct tasks
  - `_create_bundle_line_item()` adds material `total_sell` to bundle price
  - `generate_estimate_from_worksheet()` collects materials from non-excluded tasks

### Tests (extend `tests/test_instance_level_estimate_generation.py`)
- Direct task with materials → labor + material line items
- Pass-through task (no rate) with materials → material line items only, no labor line item
- Bundle with materials → material costs included in bundle price
- Excluded task materials also excluded
- Backward compatibility (no materials = same behavior as before)

### Migration
- `apps/jobs/migrations/0035_estimatelineitem_material.py`

### Fixture
- Add a "MAT" LineItemType to `fixtures/unit_test_data.json`

---

## Phase 3: PO Line Item Job FK Migration

**Goal:** Move job FK from PurchaseOrder to PurchaseOrderLineItem. Add inventory_item FK to PurchaseOrderLineItem.

### Migration sequence (3 steps)
1. `0011_add_line_item_job_and_inventory.py` — add `job` FK and `inventory_item` FK to PurchaseOrderLineItem
2. `0012_copy_po_job_to_line_items.py` — data migration: copy PO.job to all its line items
3. `0013_remove_po_job.py` — remove `job` FK from PurchaseOrder

### Changes
- `apps/purchasing/models.py` — add job + inventory_item to PurchaseOrderLineItem, remove job from PurchaseOrder
- `apps/purchasing/views.py` — update views that reference PO.job (purchase_order_create_for_job, purchase_order_detail)
- Templates — update PO detail to show per-line-item jobs

### Tests (`tests/test_po_line_item_job.py`)
- Line items with different jobs on same PO
- Derive PO's associated jobs from line items
- Update existing purchasing tests that reference PO.job

---

## Phase 4: Earmark Model & Inventory Availability

**Goal:** Track inventory reservations per job. Show availability breakdown.

### Models (`apps/inventory/models.py`)
```
Earmark:
  earmark_id     (AutoField, PK)
  inventory_item (FK to InventoryItem, CASCADE)
  job            (FK to jobs.Job, CASCADE)
  quantity       (DecimalField 10.2)
  created_date   (DateTimeField, auto_now_add)
  notes          (TextField, blank)
  Meta: unique_together = [inventory_item, job]

InventoryAdjustment:
  adjustment_id  (AutoField, PK)
  inventory_item (FK to InventoryItem, CASCADE)
  quantity_change (DecimalField 10.2)
  reason         (TextField, blank)
  created_date   (DateTimeField, auto_now_add)
```

Add properties to InventoryItem:
- `qty_earmarked` — sum of earmarks
- `qty_available` — qty_on_hand - qty_earmarked

### Changes
- `apps/inventory/models.py` — add Earmark, InventoryAdjustment, properties on InventoryItem
- `apps/inventory/views.py` — availability view, manual adjustment view
- `apps/inventory/urls.py` — new URLs

### Tests (`tests/test_earmark.py`)
- Earmark CRUD, unique constraint, cascade behavior
- qty_earmarked and qty_available properties
- Availability view

### Migrations
- `apps/inventory/migrations/0003_earmark.py`
- `apps/inventory/migrations/0004_inventoryadjustment.py`

---

## Phase 5: QOH Automatic Updates

**Goal:** Wire automatic inventory changes to PO receipt, material consumption, and task completion.

### Service (`apps/inventory/services.py` — new file)
```
InventoryService:
  receive_po_line_item(po_line_item)
    — increase QOH for inventory-linked line items
    — create earmark if line item has a job
    — auto-complete labor-free tasks if all their materials are received

  consume_material(material)
    — decrease QOH, increase qty_sold (at task start)
    — reduce/clear earmark for the material's job

  complete_task_adjustment(material, actual_qty)
    — return excess to stock if actual < estimated
    — consume additional if actual > estimated

  manual_adjustment(inventory_item, quantity_change, reason)
    — adjust QOH, create InventoryAdjustment record
    — negative adjustments track as waste
```

### Auto-completion of pass-through tasks
When a PO is received and `receive_po_line_item` runs:
1. For each received material linked to an inventory item, check its parent task
2. If the task has no rate (labor-free / pass-through) and all of its materials are now received, auto-complete the task
3. This may in turn trigger work order completion if all tasks are done

### Signal integration
- `apps/purchasing/signals.py` (new) — on PO status → received, call receive_po_line_item for each line item
- Task start hooks call consume_material
- Task completion hooks call complete_task_adjustment

### Tests (`tests/test_inventory_qoh.py`)
- PO receipt increases QOH, creates earmarks for job-linked line items
- PO receipt auto-completes labor-free tasks when all materials received
- PO receipt does NOT auto-complete tasks that have labor (rate > 0)
- Material consumption decreases QOH, clears earmarks
- Task completion adjustment returns excess or consumes more
- Manual adjustment with audit record

---

## Phase 6: Earmarking Flow on Job Approval

**Goal:** When estimate is accepted, prompt user to earmark inventory.

### Service (`apps/inventory/services.py`)
```
EarmarkService:
  get_earmark_preview(job)
    — find all materials referencing inventory items on the job's accepted estimate
    — aggregate by inventory item
    — return needed qty, available qty, shortfall for each

  create_earmarks_for_job(job, earmark_data)
    — create/update Earmark records from user-confirmed data
```

### View
- After estimate acceptance, redirect to earmark confirmation page
- Shows preview: item, needed, available, shortfall
- User adjusts quantities and confirms
- Creates earmarks, returns to job detail

### Tests (`tests/test_earmark_flow.py`)
- Preview aggregation, shortfall calculation
- Earmark creation from confirmed data
- Confirmation view GET/POST

---

## Phase Ordering & Dependencies

```
Phase 1 (Material model) — no dependencies, can start immediately
Phase 2 (Estimate generation) — depends on Phase 1
Phase 3 (PO job FK) — independent of 1 & 2, can be done in parallel
Phase 4 (Earmark model) — independent of 1-3
Phase 5 (QOH automation) — depends on Phase 1, 3, and 4
Phase 6 (Earmark flow) — depends on Phase 4 and 5
```

Phases 1, 3, and 4 can be developed in parallel. Phase 2 follows 1. Phase 5 follows all of 1/3/4. Phase 6 is last.

## Verification

After each phase:
1. Run `python manage.py makemigrations` — verify expected migrations created
2. Run `python manage.py test` — all tests pass (new and existing)
3. Manual verification via dev server for view changes
