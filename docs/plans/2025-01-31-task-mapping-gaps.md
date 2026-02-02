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

## Gap 1a: Edge Cases for LineItemType in Bundles

**Status:** Not yet implemented - notes for future work

**Problem:** The current fix takes the first `output_line_item_type` found in bundled tasks. There are edge cases to handle:

### 1. Different types in a bundle
**Scenario:** User tries to create a bundle where tasks have different `output_line_item_type` values (e.g., mixing Service and Material tasks).

**Solution:** When a bundle mapping is being created, if any of the component tasks have different types, stop and ask the user to resolve the conflict.

### 2. Tasks without templates or mappings
**Scenario:** A task has no template or the template has no mapping, resulting in `line_item_type=None`.

**Solution:** The default should be "Direct" (or a configurable default), not None. All line items need a type - without one, we can't determine taxability, and tax authorities will have opinions about that.

### 3. ProductBundlingRule could have its own line_item_type
**Scenario:** Need a way for users to explicitly set the output type for a bundle, overriding the component tasks.

**Solution:** Add `output_line_item_type` field to `ProductBundlingRule`. This could also be the mechanism to implement #1 - when a user is trying to bundle incompatible types, they must explicitly choose the output type on the bundling rule.

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

## Related Files

- Model: `apps/jobs/models.py` (TaskMapping class, line ~452)
- Service: `apps/jobs/services.py` (EstimateGenerationService)
- Tests: `tests/test_task_mapping_line_item_type.py`
- Fixtures: `fixtures/webserver_test_data.json`, `fixtures/unit_test_data.json`

## Priority

**Updated 2025-02-01:**
- ✅ Gap 1 (output_line_item_type) - Fixed
- 📝 Gap 2 (CRUD) - Plan written, ready to implement
- ⏳ Gap 1a (edge cases) - Future work, lower priority
