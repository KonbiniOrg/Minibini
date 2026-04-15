# Line Item Management Redesign

**Date:** 2026-04-07

## Problem

The API's `LineItemMixin` bypasses the service layer for line item create, update, and reorder operations. It calls `serializer.save()` directly, skipping business logic that the Django HTML views enforce through service methods.

This means the API path:
- Does not check parent document status (can add line items to non-draft documents)
- Does not populate fields from PriceListItem on create (description, units, price, category are lost)
- Does not wrap operations in explicit transactions
- Uses raw `QuerySet.update()` for reorder instead of the service method

Meanwhile, 10+ service methods (`add_line_item`, `add_line_item_from_pli`, `reorder_line_item`, `delete_line_item`) exist and are only called from the Django HTML views.

A safety net was added to `BaseLineItem.save()` (`_populate_from_pli`) to handle PLI field population at the model layer. This is the right place for default-value logic (the Material model does the same), but it doesn't address the missing status checks and service-layer validation.

## Affected Entities

All four line item types share this problem:

| Entity | Service Class | Mixin Serializer |
|---|---|---|
| EstimateLineItem | EstimateService | EstimateLineItemSerializer |
| InvoiceLineItem | InvoiceService | InvoiceLineItemSerializer |
| PurchaseOrderLineItem | PurchaseOrderService | POLineItemSerializer |
| BillLineItem | BillService | BillLineItemSerializer |

## Current State

### What the service methods do (HTML view path)

Each entity's service has methods like:

- `add_line_item(parent_pk, **kwargs)` — validates parent status is draft, creates item, calls `full_clean()` and `save()`
- `add_line_item_from_pli(parent_pk, pli_pk, qty)` — same as above, plus copies PLI fields into the line item
- `reorder_line_item(item_pk, direction)` — validates parent status, delegates to `LineItemService.reorder_line_item()`
- `delete_line_item(item_pk)` — validates parent status, delegates to `LineItemService.delete_line_item_with_renumber()`

### What the mixin does (API path)

| Operation | What happens | Service used? |
|---|---|---|
| POST (create) | `serializer.save(parent=obj)` | No |
| PATCH (update) | `serializer.save()` | No |
| DELETE | `LineItemService.delete_line_item_with_renumber()` | Yes |
| POST reorder | `QuerySet.update(line_number=...)` | No |

### What gets skipped

1. **Status validation** — can create/edit line items on issued, completed, or cancelled documents
2. **PLI population** — partially fixed by `BaseLineItem.save()._populate_from_pli()`, but this is a model-layer safety net, not a proper service call
3. **Transaction boundaries** — no explicit `transaction.atomic()` around multi-step operations
4. **Reorder validation** — no status check, no service method called

## Design

### Principle: the mixin handles HTTP plumbing, services handle business logic

The mixin's job is to provide a consistent set of nested REST endpoints across all document types. It should:
1. Parse the request
2. Call the appropriate service method
3. Serialize the result

It should **never** call `serializer.save()` for create or update.

### Approach: service-backed mixin

Each viewset already declares `line_item_serializer_class` and `line_item_parent_field`. Add a `line_item_service_class` attribute that points to the entity's service:

```python
class PurchaseOrderViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    line_item_serializer_class = POLineItemSerializer
    line_item_parent_field = 'purchase_order'
    line_item_service_class = PurchaseOrderService
```

The mixin uses this to dispatch operations:

```python
class LineItemMixin:

    @action(detail=True, methods=['get', 'post'], url_path='line-items')
    def line_items(self, request, pk=None):
        parent = self.get_object()
        if request.method == 'GET':
            items = self._get_line_items_qs(parent)
            serializer = self.line_item_serializer_class(items, many=True)
            return Response(serializer.data)

        # CREATE — delegate to service
        service = self.line_item_service_class
        data = request.data.copy()
        pli_id = data.get('price_list_item')
        qty = data.get('qty')

        if pli_id and not data.get('description'):
            # PLI-based create — let service populate fields
            item = service.add_line_item_from_pli(parent.pk, pli_id, qty)
        else:
            # Manual create
            item = service.add_line_item(parent.pk, **data)

        serializer = self.line_item_serializer_class(item)
        return Response(serializer.data, status=201)
```

### Service method contract

Each entity service must implement these methods. They already exist — this just formalizes the interface:

| Method | Signature | Responsibility |
|---|---|---|
| `add_line_item` | `(parent_pk, **kwargs)` | Validate status, create item, return item |
| `add_line_item_from_pli` | `(parent_pk, pli_pk, qty)` | Validate status, copy PLI fields, create item, return item |
| `update_line_item` | `(item_pk, **kwargs)` | Validate status, update fields, return item |
| `delete_line_item` | `(item_pk)` | Validate status, delete with renumber |
| `reorder_line_items` | `(parent_pk, item_ids)` | Validate status, reorder |

`update_line_item` is new — it doesn't exist in any service today because the HTML views don't support inline editing. It needs to be added.

### Status validation

Each service enforces its own rules about which statuses allow line item modifications. This is entity-specific:

- **Estimates:** draft only
- **Invoices:** draft only (or active? — to be confirmed)
- **Purchase Orders:** draft only
- **Bills:** draft only

### What stays in the model

`BaseLineItem.save()._populate_from_pli()` remains as a model-layer safety net. Even if the service populates PLI fields explicitly, the model ensures defaults are applied if someone creates a line item through a management command, shell, or test. This is the same pattern as `Material._populate_from_pli()`.

### What changes in the serializer

Serializers go back to being pure translation — no `create()` overrides, no business logic. They validate field types and constraints (DRF's job), but domain rules live in services.

### Reorder

The current mixin accepts an ordered list of `item_ids` and does a raw `QuerySet.update()`. The service method (`LineItemService.reorder_line_item`) only supports swapping two adjacent items. The mixin's approach (full reorder by position) is more flexible. 

Options:
- **A)** Add a `reorder_line_items(parent_pk, item_ids)` method to `LineItemService` that does the full reorder, with status validation delegated to the entity service
- **B)** Keep the adjacent-swap service method and have the mixin call it in a loop

**Recommendation: A.** The full-reorder approach is cleaner for drag-and-drop UIs and is what the mixin already does — it just needs to go through a service that validates status first.

### Error handling

Service methods raise `ValidationError` (for business rule violations) or `NotFoundError` (for missing objects). The mixin catches these and returns appropriate HTTP responses — same pattern as `StatusTransitionMixin`.

## Migration path

This is a refactor of internal plumbing — the API endpoints, URLs, request/response shapes, and frontend code don't change. The work is:

1. Add `update_line_item` to each entity's service class
2. Add `reorder_line_items` to `LineItemService` (full reorder with status validation callback)
3. Add `line_item_service_class` to the mixin interface
4. Rewrite the mixin's create/update/reorder actions to delegate to services
5. Declare `line_item_service_class` on each viewset
6. Tests to verify status checks are enforced on the API path

The Django HTML views and existing service methods are unchanged.

## Out of scope

- Changing the service method signatures
- Adding new API endpoints
- Frontend changes (the API contract doesn't change)
- Changing how `BaseLineItem.save()` works
