# TaskMapping Gaps and Future Work

**Date:** 2025-01-31
**Status:** Notes for future implementation

---

## Background

TaskMapping defines how tasks translate to line items when generating estimates from worksheets. The model exists and is used by `EstimateGenerationService`, but has significant gaps.

## Gap 1: `output_line_item_type` Not Wired Up - FIXED

**Status:** ✅ Fixed on 2025-02-01

**Problem:** TaskMapping has an `output_line_item_type` field but it wasn't used when creating line items.

**Fix applied:** Updated `EstimateGenerationService` to copy `output_line_item_type` from TaskMapping to generated EstimateLineItems in all methods:
- `_process_direct_items()`
- `_process_service_bundles()`
- `_create_product_line_item()`
- `_create_combined_product_line_item()`

**Test:** `tests/test_estimate_generation_line_item_type.py`

---

## Gap 1a: Edge Cases for LineItemType in Bundles - FIXED

**Status:** ✅ Fixed on 2025-02-02

**Problem:** The current fix takes the first `output_line_item_type` found in bundled tasks. There are edge cases to handle:

### 1. Different types in a bundle ✅
**Scenario:** User tries to create a bundle where tasks have different `output_line_item_type` values (e.g., mixing Service and Material tasks).

**Solution implemented:** `ProductBundlingRuleForm.clean()` validates that if TaskMappings for the same `product_type` have conflicting `output_line_item_type` values, the user must specify an explicit `output_line_item_type` on the bundling rule.

**Test:** `tests/test_bundling_rule_views.py::TestBundlingRuleConflictingTypesValidation`

### 2. Tasks without templates or mappings ✅
**Scenario:** A task has no template or the template has no mapping, resulting in `line_item_type=None`.

**Solution implemented:** `EstimateGenerationService._get_default_line_item_type()` returns a default LineItemType (SVC, DIR, or first active type). All 4 line item creation methods use this fallback.

**Test:** `tests/test_estimate_generation_line_item_type.py::test_task_without_mapping_gets_default_line_item_type`

### 3. ProductBundlingRule has its own line_item_type ✅
**Scenario:** Need a way for users to explicitly set the output type for a bundle, overriding the component tasks.

**Solution implemented:** Added `output_line_item_type` field to `ProductBundlingRule`. When set, it overrides the component tasks' types in `_create_product_line_item()` and `_create_combined_product_line_item()`.

**Migration:** `apps/jobs/migrations/0022_add_output_line_item_type_to_bundling_rule.py`

**Test:** `tests/test_estimate_generation_line_item_type.py::test_bundling_rule_output_line_item_type_overrides_task_mapping`

---

## Gap 2: No CRUD for TaskMappings - PLAN WRITTEN

**Status:** 📝 Implementation plan written: `docs/plans/2025-02-01-task-mapping-crud.md`

**Problem:** TaskMappings can only be created/modified by editing fixture JSON files. There's no UI to manage them.

**Current state:**
- Only a list view exists: `/task-mappings/` (`task_mapping_list`)
- No create, edit, or delete views
- No admin registration
- All TaskMappings come from fixtures (`webserver_test_data.json`, `unit_test_data.json`, etc.)

**Why this matters:** TaskMappings define critical business logic:
- `step_type` - what the task represents (product, component, labor, material, overhead)
- `mapping_strategy` - how to translate to line items (direct, bundle_to_product, bundle_to_service, exclude)
- `line_item_name` / `line_item_description` - what appears on estimates
- `output_line_item_type` - determines taxability of generated line items

These will need adjustment as the business evolves. Requiring fixture edits and data reloads is not sustainable.

**Fix needed:** Add full CRUD views for TaskMapping, similar to LineItemType CRUD:
- List view (exists)
- Detail view
- Create view
- Edit view
- Soft delete via `is_active` flag (would need to add this field)

---

## Gap 3: Template Placeholders Create Code/Data Coupling

**Status:** ⚠️ Design issue - needs resolution

**Date identified:** 2025-02-02

**Problem:** `BundlingRule.line_item_template` stores Python format strings like `"Custom {product_type} - {bundle_identifier}"`. The code then does:

```python
description = rule.line_item_template.format(
    product_type=product_type.title(),
    bundle_identifier=bundle_identifier
)
```

This creates fragile coupling between database content and code variable names. If a variable is renamed in code, all database records break with a `KeyError`.

**Example of breakage:** When `product_identifier` was renamed to `bundle_identifier`, existing `BundlingRule` records with `{product_identifier}` in their templates caused estimate generation to fail.

**Possible solutions:**
1. **Eliminate templates entirely** - Use fixed description patterns based on rule configuration
2. **Validate on save** - Form/model validates that only known placeholders are used
3. **Abstract placeholder mapping** - Use generic placeholders like `{1}`, `{2}` mapped to values
4. **Graceful error handling** - Catch KeyError and show meaningful error instead of crashing

**Decision needed:** Whether templates are worth the flexibility vs. the maintenance burden.

---

## Gap 4: TaskInstanceMapping Not Created for Manually-Added Tasks

**Status:** ⚠️ Needs implementation

**Date identified:** 2025-02-02

**Problem:** When tasks are added to a worksheet manually via the UI (using `task_add_from_template` view), no `TaskInstanceMapping` record is created. This causes issues when generating estimates:

1. User adds tasks from TaskTemplates that have `mapping_strategy='bundle'`
2. Tasks are created but have no `TaskInstanceMapping`
3. `EstimateGenerationService._categorize_tasks()` auto-generates an identifier: `f"_auto_{product_type}"` (e.g., `_auto_cabinet`)
4. This ugly internal identifier leaks into customer-facing line item descriptions like "Custom Cabinet - _auto_cabinet"

**Root cause:** `TaskInstanceMapping` records are only created by `WorkOrderTemplate.generate_tasks()`, not by the manual task-add UI flow.

**Fix needed:** When adding a task from a template that has `mapping_strategy='bundle'`, the UI should:
1. Prompt for or auto-generate a meaningful `bundle_identifier`
2. Create a `TaskInstanceMapping` record linking the task to that identifier

**Workaround:** Change `BundlingRule.line_item_template` to not include `{bundle_identifier}` (e.g., just `"Custom {product_type}"`), but this loses the ability to distinguish multiple product instances.

---

## Related Files

- Model: `apps/jobs/models.py` (TaskMapping class, line ~452)
- Service: `apps/jobs/services.py` (EstimateGenerationService)
- Tests: `tests/test_task_mapping_line_item_type.py`
- Fixtures: `fixtures/webserver_test_data.json`, `fixtures/unit_test_data.json`

## Priority

**Updated 2025-02-02:**
- ✅ Gap 1 (output_line_item_type) - Fixed
- ✅ Gap 1a (edge cases) - Fixed (all 3 items complete)
- ✅ Gap 2 (CRUD) - Implemented (TaskMapping + BundlingRule CRUD)
- ⚠️ Gap 3 (template placeholders) - Design issue, needs decision
- ⚠️ Gap 4 (TaskInstanceMapping for manual tasks) - Needs implementation
