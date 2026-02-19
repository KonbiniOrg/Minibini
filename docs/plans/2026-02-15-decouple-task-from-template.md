# Plan: Decouple Task from TaskTemplate — add line_item_type, remove template FK

## Context

Tasks should own all their data independently. We already moved `description` onto Task. The remaining runtime dependency is `task.template.line_item_type`, used during estimate generation for direct/unbundled tasks. (Bundled tasks use `bundle.line_item_type` — unaffected.)

**UX insight from brainstorming:** Users shouldn't have to think about `line_item_type` during task creation (they're in "planning work" mode). Instead, classify tasks at **estimate generation time**, when the user is already in billing headspace. The existing generate-estimate confirmation page is the natural place for this.

## Part 1: Add `line_item_type` to Task, remove `template` FK

### 1a. Add `line_item_type` FK to Task model
- **`apps/jobs/models.py`** — Add `line_item_type = ForeignKey('core.LineItemType', on_delete=PROTECT, null=True, blank=True)`
- Nullable: manual tasks and work order tasks may not have one
- Create migration

### 1b. Copy `line_item_type` at all task creation points (where template is available)
- **`models.py` `TaskTemplate.generate_task()`** — add `line_item_type=self.line_item_type`
- **`views.py` `task_add_from_template()`** — add `line_item_type=template.line_item_type`
- **`models.py` `EstWorksheet.create_new_version()`** — add `line_item_type=task.line_item_type`
- **`views.py` `estworksheet_revise()`** — add `line_item_type=task.line_item_type`
- **`services.py` `_copy_worksheet_tasks()`** — add `line_item_type=source_task.line_item_type`

### 1c. Update estimate generation to read `task.line_item_type` directly
- **`services.py` `create_line_item_from_task()`** (~line 285) — `task.template.line_item_type` → `task.line_item_type`
- **`services.py` `_create_direct_line_item()`** (~line 412) — `task.template.line_item_type` → `task.line_item_type`
- Keep existing fallback-to-default behavior for null `line_item_type`

### 1d. Remove `template` FK from Task
- **`models.py`** — delete the `template` field
- Remove all `template=...` kwargs at every creation point:
  - `TaskTemplate.generate_task()`, `_copy_worksheet_tasks()`, `_create_task_from_catalog_item()`, `_create_generic_task()`, `TaskService.create_from_template()`, `EstWorksheet.create_new_version()`, `estworksheet_revise()`, `task_add_from_template()`
- **`views.py` `estworksheet_generate_estimate()`** (~line 955) — remove `.select_related('template')`
- Create migration

### 1e. Update tests
- Remove all `task.template` assertions and `template=...` kwargs
- Add `task.line_item_type` assertions where appropriate
- **Files:** `test_lineitem_task_generation.py`, `test_template_workflows.py`, `test_worksheet_task_restrictions.py`, `test_crud_operations.py`, `test_workorder_from_estimate.py`, `test_comprehensive_models.py`

## Part 2: Line item type review at estimate generation

### 2a. Update generate-estimate confirmation page
- **`views.py` `estworksheet_generate_estimate()`** GET handler:
  - Query direct (unbundled, non-excluded) tasks missing `line_item_type`
  - Pass `untyped_tasks` and `line_item_types` queryset to template
- **`templates/jobs/estworksheet_generate_estimate.html`**:
  - If `untyped_tasks` exist, show a form section: "These tasks need a line item type before generating:"
  - Each untyped task gets a `<select>` dropdown for line_item_type
  - The "Generate Estimate Now" button is disabled/hidden until all tasks are typed
  - Already-typed tasks show their type in the review table (read-only)

### 2b. Handle the POST
- **`views.py` `estworksheet_generate_estimate()`** POST handler:
  - If POST includes `task_line_item_types`, save them to the tasks before generating
  - Then proceed with estimate generation as before

### 2c. Show line_item_type in task detail (read-only)
- **`templates/jobs/task_detail.html`** — add row showing `task.line_item_type` if set

## TDD Order

### Part 1 (field + FK removal):
1. RED: Tests that Task has `line_item_type`, copied from template, used in estimate generation
2. GREEN: Add field, migration, update creation points, update services
3. RED/GREEN: Remove `template` FK, clean up all references and tests
4. Full suite green

### Part 2 (estimate generation review):
1. RED: Test that generate-estimate page shows untyped tasks with dropdowns
2. RED: Test that POST with line_item_type assignments saves them and generates estimate
3. RED: Test that page blocks generation when untyped direct tasks exist
4. GREEN: Implement view changes and template updates
5. Full suite green

## Verification
```bash
python manage.py test
python manage.py makemigrations --check
```
