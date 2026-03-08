# Service-Mediated Saves — Fixup List

Items discovered during the service refactor that need to be addressed separately.

## Model/DB Changes

- [x] **PriceListItem.code** needs a `unique=True` constraint at the model/DB level (currently only enforced in forms) — migration created

## Test Changes

- (none)

## Investigate

- [x] **`EstimateService.create_from_work_order`** — deleted (reverse workflow, not needed)
- [x] **`LineItemService` does its own status validation** — moved `validate_modification` out of LineItemService into calling domain services (EstimateService, PurchaseOrderService, BillService, InvoiceService), matching BundlingService's pattern. Also added `EstimateService.reorder_line_item`, `EstimateService.delete_line_item`, and `InvoiceService.delete_line_item`.
- [x] **`BundlingService` method parity with `LineItemService`** — no action needed; sort_order gaps are harmless for bundles, unlike line_number gaps for line items
- [x] **`TaskService.reorder_tasks`** — now delegates to `BundlingService.reorder_container_items` instead of inline swap logic
- [x] **Worksheet bundling within-bundle sort_order** — already correct; BundlingService uses additive sort_order for both worksheets and templates
