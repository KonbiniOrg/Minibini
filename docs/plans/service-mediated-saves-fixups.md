# Service-Mediated Saves — Fixup List

Items discovered during the service refactor that need to be addressed separately.

## Model/DB Changes

- [ ] **PriceListItem.code** needs a `unique=True` constraint at the model/DB level (currently only enforced in forms)

## Test Changes

- (none yet)

## Investigate

- [ ] **`EstimateService.create_from_work_order`** — creates an Estimate from a WorkOrder, which is the opposite direction from the intended workflow (Job → Estimate → WorkOrder). Needs investigation.
- [ ] **`LineItemService` does its own status validation** — with the layered service pattern (domain service → shared service), status checks should arguably live in the domain service (e.g. `PurchaseOrderService`), not in `LineItemService` itself. Revisit whether `LineItemService` should drop `validate_modification` and let callers handle it, matching how `BundlingService` delegates status checks to its callers.
- [ ] **`BundlingService` method parity with `LineItemService`** — LineItemService has delete-with-renumber and get-items-for-container; BundlingService may need equivalents (delete task + re-sequence sort_order, query all items for a container).
