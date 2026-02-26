# Merge Review: 9c61d8a (Alim's merge of main into Search-Functions--Alim)

**Date of merge:** Wed Oct 29 22:44:39 2025
**Merge commit:** `9c61d8a` — "Merge remote-tracking branch 'origin/main' into Search-Functions--Alim"
**Parents:** `2460530` (branch) merged with `6232ed5` (main)
**Review date:** 2026-02-11

## What happened

Six commits from main were merged into Alim's feature branch. The merge resolved conflicts by keeping the branch's versions of files, which silently reverted several fixes and refactors that had been committed to main.

The reverted changes then propagated forward through `e6ba240` ("merging main into branch") into the current `feature/work-objects-from-templates` branch.

## Commits from main that were supposed to be incorporated

### 1. `2d86cbb` — "fixed bug where prices were getting multiplied 2x; fixed price_currency > price"
**Status: FULLY LOST (37 files reverted)**

This was the most significant loss. The commit:
- Renamed the `price_currency` field to `price` across the entire codebase (models, forms, views, templates, fixtures, tests)
- Fixed a double-multiplication bug in `EstimateGenerationService._create_direct_line_item()` where `price_currency` was set to `qty * rate` (a pre-multiplied total) but `BaseLineItem.total_amount` then computed `qty * price_currency` again, doubling the result
- Created three database migration files to rename the columns

What was lost:
- Field rename reverted in 57 files (still using `price_currency` today)
- Double-multiplication bug reintroduced (re-fixed on 2026-02-11 in `services.py`)
- Three migration files deleted:
  - `invoicing/migrations/..._rename_price_currency_invoicelineitem_price.py`
  - `jobs/migrations/..._rename_price_currency_estimatelineitem_price.py`
  - `purchasing/migrations/..._rename_price_currency_billlineitem_price_and_more.py`

**Action needed:** Re-do the `price_currency` -> `price` rename across the codebase and create new migrations.

### 2. `162ba66` — "split out some reused view parts into _include files"
**Status: PARTIALLY SURVIVED**

This commit extracted shared HTML into reusable partials:
- `templates/includes/_line_items_table.html` — exists but still references `price_currency`
- `templates/includes/_inline_status_form.html` — exists

However, not all detail templates were updated to use the shared partial. Currently only the purchasing templates (`bill_detail.html`, `purchase_order_detail.html`) include `_line_items_table.html`. The estimate and invoice detail templates may still have inline HTML instead of using the shared partial.

**Action needed:** Verify which templates use the partial vs inline HTML. Low priority — will be addressed when the `price_currency` rename is done.

### 3. `3f32d5f` — "Tasks shown in Job view; reusable _task_list.html"
**Status: SURVIVED**

The `templates/jobs/_task_list.html` partial exists and is in use. No issues found.

### 4. `ea05db0` — "refactored tests to use specific layered test files for easier readability"
**Status: REVERSED**

Main had split large fixture files into smaller, focused ones and removed old large fixtures. The merge put the old fixtures back:
- `fixtures/template_system_data.json` — deleted (was supposed to exist)
- `fixtures/webserver_test_data_old.json` — still exists (was supposed to be removed)
- Other fixture files reverted to their pre-split state

**Action needed:** Probably moot. Fixtures have been significantly restructured on the current feature branch since then. Review whether any of the old fixture files (`webserver_test_data_old.json`) can be deleted.

### 5. `6232ed5` — "tweak to task template display"
**Status: LIKELY LOST**

Added form handling code to `apps/jobs/forms.py`. This file was heavily modified by the branch, so the tweak was likely overwritten.

**Action needed:** Low priority. Review if relevant.

### 6. `12c1af6` — "merged from main"
A merge commit (no direct changes). Not relevant.

## Root cause

Alim's merge `9c61d8a` resolved conflicts by taking the branch side's version of files wholesale. The `price_currency` -> `price` rename touched many of the same files that Alim was working on (forms, views, models), creating merge conflicts that were resolved in favor of the branch's `price_currency` versions.

## Recommended actions

1. **High priority:** Re-do the `price_currency` -> `price` rename across the codebase with new migrations. The double-mult bug in `services.py` has already been re-fixed.
2. **Low priority:** Clean up stale fixture files (`webserver_test_data_old.json`).
3. **For the future:** When merging, review `git diff` of the merge result against each parent to ensure no changes are silently dropped.
