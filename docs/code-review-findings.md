# Code Review Findings (2026-03-08)

Three parallel code-reviewer agents audited the full codebase for unused methods, test coverage gaps, and duplicate patterns.

---

## 1. Unused Methods (31 findings)

### Critical
- ~~Stale `save()` overrides on `JobCreateForm`, `PurchaseOrderForm`, `BillForm`~~ DONE
- ~~Merge `LineItemTaskService` into `TaskService`~~ DONE

### Important
- ~~Delete deprecated `PurchaseOrderLineItemForm`~~ DONE
- ~~Delete unused `InvoiceForm`~~ DONE
- ~~Delete `EstimateForm` + dead import~~ DONE
- ~~Delete `EmailService.link_email_to_job` (duplicates `associate_with_job`)~~ DONE
- ~~`NumberGenerationService.reset_counter`~~ DONE (deleted)
- ~~`TaskService.create_line_item_from_task`~~ DONE (deleted — stale duplicate of `EstimateGenerationService._create_direct_line_item`)
- `PriceListItem.can_be_deleted` — KEPT (will be needed for PLI deletion feature)

### Suggestions
- 19 test-only methods (forward-looking service methods not yet wired to views) — mark with TODO comments or leave as-is

---

## 2. Test Coverage Gaps

### Critical
- ~~`InventoryService` QOH methods (`receive_po_line_item`, `consume_material`, `complete_task_adjustment`, `manual_adjustment`)~~ DONE (26 tests)
- `NumberGenerationService.generate_next_number` error paths + `reset_counter` — no isolated tests
- ~~`WorkOrderService.create_from_estimate`, `create_from_template`, `create_direct`~~ DONE (22 tests in `test_jobs_services.py`)
- ~~`LineItemTaskService` entire class~~ DONE (merged into TaskService; covered by `test_lineitem_task_generation.py`)

### Important
- ~~`create_job_from_email` view~~ DONE (9 tests in `test_create_job_from_email.py`)
- `LineItemService.get_line_items_for_container`, `calculate_total` — no tests
- `work_order_list`, `work_order_detail`, `task_list`, `task_detail` views — no tests
- `invoice_list`, `invoice_detail` views — no tests
- `purchase_order_edit`, `purchase_order_cancel`, `bill_create` views — no tests
- `EstimateService.create_direct` — no test
- `SearchService.apply_date_and_price_filters` edge cases
- `EmailService` pure-DB methods (`cleanup_old_temp_emails`, `link_email_to_job`)

### Minor
- `Contact.phone`, `Contact.address` properties
- `user_list`, `user_detail`, `settings_view` views
- `inventory_list` view

---

## 3. Duplicate/Parallel Patterns (15 findings)

### Critical
1. **Status Form duplication** — 4 near-identical forms (`WorkOrderStatusForm`, `PurchaseOrderStatusForm`, `BillStatusForm`, `EstimateStatusForm`) -> extract `BaseStatusForm` (~100 lines, low risk)

### Important
2. **CRUD service method duplication** — "fetch by PK, setattr, full_clean, save" repeated ~15 times -> extract `CRUDMixin` (~200 lines, low-med risk)
3. **Reorder view duplication** — 6 identical `@require_POST` reorder views -> helper function (~60 lines, low risk)
4. **Delete line item view duplication** — 3 identical delete views (~40 lines, low risk)
5. **Reorder/delete service method duplication** — 8 methods all checking draft status then delegating to `LineItemService` (~80 lines, low risk)
6. **Model status transition duplication** — 4 models with near-identical `clean()`/`save()` for status validation, immutable dates, transition dates. Also double DB fetch (~200 lines, medium risk)
7. **`add_line_item_from_pli` duplication** — 3 nearly identical methods (~50 lines, low risk)

### Suggestions
8. ~~Deprecated `PurchaseOrderLineItemForm`~~ DONE
9. Manual line item form duplication (`ManualLineItemForm` / `POManualLineItemForm`)
10. Negative-value validators -> use `MinValueValidator(0)`
11. Delete/detail/add views, bundle creation, worksheet copy patterns
