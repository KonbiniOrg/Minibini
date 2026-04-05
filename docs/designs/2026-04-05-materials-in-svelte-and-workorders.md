# Materials in Svelte + Materials on WorkOrders

## Date: 2026-04-05

## Status

**Starter doc — brainstorm in progress.** This captures the goals, the
context we've gathered, the scope decisions made so far, and the open
questions. It is not yet an implementable spec. Work on this was paused
to first resolve the worksheet → work order structural issues described
under "Known tensions" below.

## Goals

1. Move material management out of the legacy Django HTML views and into
   the Svelte SPA, alongside jobs/tasks/contacts.
2. Allow materials to be created, edited, and adjusted on **WorkOrder
   tasks**, not just on draft EstWorksheet tasks.
3. Give workers doing the actual work a way to:
   - Add a material that wasn't planned.
   - Adjust the quantity of a planned material up or down based on what
     was really used.
   - Delete a material that turned out not to be needed.
4. Provide a job-level view of all materials on a job as a flat list,
   separate from the task list.

## Why

The EstWorksheet is a pure planning document. Tasks on a worksheet
never have work done against them — no bleps, no time tracking, no
actual material consumption. `BlepService` already enforces this at
`apps/jobs/services/blep_service.py:101`.

The real work happens on WorkOrder tasks. That's where inventory is
actually drawn down and materials are actually consumed. But today, the
only UI for managing materials lives on worksheet tasks (gated to the
`draft` status) in Django HTML templates. The result:

- Jobs that skip the worksheet step (which is allowed and common for
  simple work) have **no way to track materials at all**.
- Workers who discover reality differs from the plan have no way to
  reflect that.
- The Svelte SPA, which is becoming the primary UI, has no materials
  story.

This project closes those gaps.

## Current State (as of 2026-04-05)

- **Model:** `apps.inventory.models.Material` — task-scoped, with optional
  FKs to `PriceListItem` and `AccountingCategory`. Does not inherit
  `BaseLineItem`. Has `total_cost` / `total_sell` properties.
  `apps/inventory/models.py:96-139`
- **Service:** `InventoryService.create_material / update_material /
  delete_material / consume_material / complete_task_adjustment` in
  `apps/inventory/services.py`.
- **UI:** Django HTML only — `material_add`, `material_edit`,
  `material_delete` in `apps/jobs/views.py:402-470`, gated to draft
  EstWorksheet tasks. Templates under `templates/jobs/material_*.html`.
- **API:** None. No `/api/materials/` endpoint. No Svelte component.
- **Lifecycle:** Already described in
  `docs/designs/2026-03-06-material-pli-lifecycle.md`:
  worksheet = sketch, WO = firm up, invoice = hard PLI gate. This
  project implements phases 3 and 4 of that lifecycle on the Svelte
  side.
- **Inventory coupling:** `Earmark` reserves PriceListItem quantity on
  estimate acceptance; `consume_material()` draws down QOH and the
  earmark when work happens.

## Scope Decision: Narrow (no Task model split)

We considered splitting `Task` into a "proto-Task" for planning
(worksheet) and a real `Task` for execution (WorkOrder). See the
"Alternative considered" section.

**Decision:** defer the split. This project works within the current
dual-FK `Task` shape. The worksheet-task-is-planning-only invariant is
already enforced where it matters most (bleps), and the current model
does support materials on WO tasks — the gate is in the views, not the
schema.

A separate future project can revisit the split after we've resolved
the worksheet → WorkOrder structural issues (see Known tensions).

## What this project will NOT do

- Split the Task model.
- Change the `consume_material` / earmark / QOH bookkeeping semantics.
  (Consumption rules already exist; we're exposing them, not
  redesigning them.)
- Change the invoicing hard gate on PLI linkage.
- Touch worksheet material UI beyond making sure it still works.
- Resolve the worksheet → WorkOrder structural disagreements. Those
  are prerequisite work, tracked separately.

## Known tensions — to be resolved before this work begins

Investigation turned up structural disagreements in how worksheets
become work orders. These affect this project because "the set of
materials on a WO task" depends on which path was used to create the
WO. They deserve their own design conversation and spec, which will
happen next on this branch before materials implementation resumes.

Summary of what was found:

- **Three distinct worksheet → WorkOrder paths exist**, and they produce
  structurally different WorkOrders from the same source:
  1. **Estimate-mediated** (`WorkOrderService.create_from_estimate` →
     `TaskService.create_from_line_item` →
     `_copy_worksheet_tasks`). Bundled tasks collapse into a single
     line item. Materials are detached into their own line items. Only
     one task is ever copied per call; the parent-relationship
     second-pass loop at `apps/jobs/services/__init__.py:227-233` is
     effectively dead code.
  2. **Direct copy** (`WorkOrderService.copy_from_worksheet` at
     `apps/jobs/services/__init__.py:124-177`). Preserves bundles,
     sort order, and materials attached to tasks. Silently drops
     `parent_task` — never sets it on the new task.
  3. **Template straight to WO** (`WorkOrderService.create_from_template`
     → `TaskTemplate.generate_task`). Recurses through
     `parent_template` and **does** preserve hierarchy. No materials.
- **Parent-task hierarchy is lost on paths 1 and 2** but preserved on
  path 3. Worksheet tasks can have subtasks; none of the worksheet-
  originated paths carry them through to the WorkOrder faithfully.
- **The proto-Task split should be reconsidered in this context**, not
  in the context of the materials project. Whether `Task` should be
  split depends partly on how we want to resolve the above — e.g., if
  "the canonical worksheet → WO conversion" becomes a single clean
  service, and if materials and hierarchy both want to be preserved,
  the case for a split becomes clearer or weaker.

These will be worked out before this project resumes. This doc will be
updated after those decisions are made.

## Open design questions (to answer when work resumes)

These were raised in the brainstorm but not yet decided:

1. **Consumption trigger.** When does adding a material on a WO task
   decrement inventory — immediately on create, on task start, on task
   complete? Today `consume_material` is called from task lifecycle
   transitions; we need to decide whether ad-hoc WO material additions
   follow the same rule or a different one.
2. **Earmarks for unplanned materials.** If a worker adds a PLI-linked
   material to a WO task that was never on the estimate, should an
   earmark be retroactively created? Or should consumption just bypass
   the earmark machinery in that case?
3. **Permission model.** Does adjusting a material on a WO task require
   `can_manage_jobs`, or should workers with just `IsAuthenticated` be
   able to record actuals on tasks they are assigned to? Analogous to
   how bleps work.
4. **Variance visibility.** When actual quantity differs from planned,
   do we surface the variance in the UI, or silently overwrite?
5. **UI placement.** Inline on the task card in the Svelte SPA? A
   separate tab? A modal? The job-level rollup view — where does it
   live in the nav?
6. **API shape.** Nested under tasks (`/api/tasks/{id}/materials/`),
   flat (`/api/materials/`), or both? The existing code uses nested
   mixins for task bundles; materials could follow the same pattern.
7. **Delete semantics on WO.** If a material has already been consumed
   (inventory drawn down), can it be deleted? Does delete reverse the
   consumption?

## Alternative considered: split Task into proto-Task and real Task

Briefly investigated. Summary of findings:

- **Size:** XL — realistic estimate 2–3 weeks.
- **Blast radius:** ~25–30 container-branching call sites, ~41 test
  files / ~285 test methods, `TaskBundle` has an identical dual-FK
  pattern that would also need splitting, three separate
  worksheet→WO conversion paths all want different semantics.
- **Payoff:** The "worksheet tasks never get worked on" invariant
  becomes type-enforced rather than runtime-enforced. Cleaner
  planned-vs-actual material story. Latent bugs in the copy paths
  become harder to write.
- **Conclusion:** worth doing, but not in service of the materials
  project. It should be its own design, and it should come *after*
  the worksheet→WO path inconsistencies are resolved so the split has
  clear target semantics.

## Related

- `docs/designs/2026-03-06-material-pli-lifecycle.md` — lifecycle phases
  (worksheet sketch → WO firm-up → invoice PLI gate). This project
  implements phases 3–4 in the Svelte SPA.
- `docs/designs/2026-03-07-model-inventory.md` — inventory model design.
- `docs/designs/2026-03-15-task-lifecycle-design.md` — task lifecycle,
  which `consume_material` hooks into.
