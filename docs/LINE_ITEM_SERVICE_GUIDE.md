# LineItemService Usage Guide

**Date**: 2025-10-28

## Overview

The `LineItemService` in `apps.core.services` provides generalized line item management functionality that works across all line item container types (Estimate, Invoice, PurchaseOrder, Bill).

This service eliminates code duplication by providing a single implementation for common operations:
- **Deletion with renumbering**: Delete a line item and automatically renumber remaining items
- **Reordering**: Move line items up or down within their container
- **Validation**: Ensure containers are in 'draft' status before allowing modifications

## Why No Common Superclass Is Needed

The service uses **duck typing** and leverages the existing `BaseLineItem` infrastructure:

1. **All containers have a `status` field** - No inheritance needed
2. **All use `'draft'` as their editable status** - Consistent behavior
3. **BaseLineItem provides `get_parent_field_name()`** - Built-in introspection
4. **No database changes required** - Works with existing models

This approach avoids:
- Complex inheritance hierarchies
- Cross-app model dependencies (models are in different apps)
- Database migrations
- Tight coupling between models

## Service Methods

### Core Methods

#### `delete_line_item_with_renumber(line_item)`
Deletes a line item and renumbers remaining items sequentially.

**Parameters:**
- `line_item`: Instance of any BaseLineItem subclass

**Returns:**
- `tuple`: `(parent_container, deleted_line_number)`

**Raises:**
- `ValidationError`: If parent container is not in draft status

**Example:**
```python
from apps.core.services import LineItemService
from django.core.exceptions import ValidationError

try:
    parent, line_num = LineItemService.delete_line_item_with_renumber(line_item)
    messages.success(request, f'Line item {line_num} deleted successfully.')
except ValidationError as e:
    messages.error(request, str(e))
```

---

#### `reorder_line_item(line_item, direction)`
Reorders a line item by swapping line numbers with adjacent item.

**Parameters:**
- `line_item`: Instance of any BaseLineItem subclass
- `direction`: `'up'` or `'down'`

**Returns:**
- The parent container object

**Raises:**
- `ValidationError`: If modifications not allowed or invalid direction

**Example:**
```python
try:
    parent = LineItemService.reorder_line_item(line_item, 'up')
except ValidationError as e:
    messages.error(request, str(e))
```
**Note:**
No success message is required as the view refreshes and the user will immediately see the reordering.

---

### Helper Methods

#### `can_modify_line_items(container)`
Check if a container allows line item modifications.

**Parameters:**
- `container`: Any object with a `status` attribute

**Returns:**
- `bool`: True if container.status == 'draft'

---

#### `validate_modification(container)`
Validate container status and raise error if modifications not allowed.

**Parameters:**
- `container`: Any object with a `status` attribute

**Raises:**
- `ValidationError`: If container is not in draft status

---

#### `get_parent_container(line_item)`
Get the parent container for a line item.

**Parameters:**
- `line_item`: Instance of any BaseLineItem subclass

**Returns:**
- The parent container object (Estimate, Invoice, PurchaseOrder, Bill)

---

#### `calculate_total(line_items)`
Calculate total amount for a collection of line items.

**Parameters:**
- `line_items`: QuerySet or list of line items

**Returns:**
- `Decimal`: Total of all line item amounts

---

## Implementation Examples

### Example 1: Estimate Line Item Deletion (Already Implemented)

**Location**: `apps/jobs/views.py:703-722`

```python
def estimate_delete_line_item(request, estimate_id, line_item_id):
    """Delete a line item from an estimate and renumber remaining items"""
    from apps.core.services import LineItemService
    from django.core.exceptions import ValidationError

    estimate = get_object_or_404(Estimate, estimate_id=estimate_id)
    line_item = get_object_or_404(EstimateLineItem, line_item_id=line_item_id, estimate=estimate)

    if request.method == 'POST':
        try:
            # Use the service to delete and renumber
            parent_container, deleted_line_number = LineItemService.delete_line_item_with_renumber(line_item)
            messages.success(request, f'Line item deleted and remaining items renumbered.')
        except ValidationError as e:
            messages.error(request, str(e))

        return redirect('jobs:estimate_detail', estimate_id=estimate.estimate_id)

    # GET request - redirect back to detail
    return redirect('jobs:estimate_detail', estimate_id=estimate.estimate_id)
```

**Key points:**
- Service handles all validation automatically
- No need to check status manually
- Automatic renumbering included
- Clean exception handling

---

### Example 2: Estimate Line Item Reordering (Already Implemented)

**Location**: `apps/jobs/views.py:964-978`

```python
def estimate_reorder_line_item(request, estimate_id, line_item_id, direction):
    """Reorder line items within an Estimate by swapping line numbers."""
    from apps.core.services import LineItemService
    from django.core.exceptions import ValidationError

    estimate = get_object_or_404(Estimate, estimate_id=estimate_id)
    line_item = get_object_or_404(EstimateLineItem, line_item_id=line_item_id, estimate=estimate)

    try:
        # Use the service to reorder
        LineItemService.reorder_line_item(line_item, direction)
    except ValidationError as e:
        messages.error(request, str(e))

    return redirect('jobs:estimate_detail', estimate_id=estimate_id)
```

**Benefits:**
- 14 lines vs 36 lines (original implementation)
- No manual index calculation
- Consistent error messages across all line item types

---

### Example 3: Invoice Line Item Deletion (To Be Implemented)

**Location**: `apps/invoicing/views.py` (add this function)

```python
def invoice_delete_line_item(request, invoice_id, line_item_id):
    """Delete a line item from an invoice and renumber remaining items"""
    from apps.core.services import LineItemService
    from django.core.exceptions import ValidationError

    invoice = get_object_or_404(Invoice, invoice_id=invoice_id)
    line_item = get_object_or_404(InvoiceLineItem, line_item_id=line_item_id, invoice=invoice)

    if request.method == 'POST':
        try:
            parent_container, deleted_line_number = LineItemService.delete_line_item_with_renumber(line_item)
            messages.success(request, f'Line item deleted.')
        except ValidationError as e:
            messages.error(request, str(e))

        return redirect('invoicing:invoice_detail', invoice_id=invoice.invoice_id)

    return redirect('invoicing:invoice_detail', invoice_id=invoice.invoice_id)
```

**URL pattern**:
```python
# Add to apps/invoicing/urls.py
path('invoices/<int:invoice_id>/line-items/<int:line_item_id>/delete/',
     views.invoice_delete_line_item,
     name='invoice_delete_line_item'),
```

---

### Example 4: PurchaseOrder Line Item Deletion (To Be Implemented)

**Location**: `apps/purchasing/views.py` (add this function)

```python
def purchase_order_delete_line_item(request, po_id, line_item_id):
    """Delete a line item from a purchase order and renumber remaining items"""
    from apps.core.services import LineItemService
    from django.core.exceptions import ValidationError

    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)
    line_item = get_object_or_404(PurchaseOrderLineItem, line_item_id=line_item_id,
                                  purchase_order=purchase_order)

    if request.method == 'POST':
        try:
            parent_container, deleted_line_number = LineItemService.delete_line_item_with_renumber(line_item)
            messages.success(request, f'Line item deleted.')
        except ValidationError as e:
            messages.error(request, str(e))

        return redirect('purchasing:purchase_order_detail', po_id=po_id)

    return redirect('purchasing:purchase_order_detail', po_id=po_id)
```

**Refactor existing reordering** (already exists at `apps/purchasing/views.py:260-297`):

```python
def purchase_order_reorder_line_item(request, po_id, line_item_id, direction):
    """Reorder line items within a PurchaseOrder by swapping line numbers."""
    from apps.core.services import LineItemService
    from django.core.exceptions import ValidationError

    purchase_order = get_object_or_404(PurchaseOrder, po_id=po_id)
    line_item = get_object_or_404(PurchaseOrderLineItem, line_item_id=line_item_id,
                                  purchase_order=purchase_order)

    try:
        LineItemService.reorder_line_item(line_item, direction)
    except ValidationError as e:
        messages.error(request, str(e))

    return redirect('purchasing:purchase_order_detail', po_id=po_id)
```

---

### Example 5: Bill Line Item Operations (To Be Implemented)

**Location**: `apps/purchasing/views.py` (add these functions)

**Delete:**
```python
def bill_delete_line_item(request, bill_id, line_item_id):
    """Delete a line item from a bill and renumber remaining items"""
    from apps.core.services import LineItemService
    from django.core.exceptions import ValidationError

    bill = get_object_or_404(Bill, bill_id=bill_id)
    line_item = get_object_or_404(BillLineItem, line_item_id=line_item_id, bill=bill)

    if request.method == 'POST':
        try:
            parent_container, deleted_line_number = LineItemService.delete_line_item_with_renumber(line_item)
            messages.success(request, f'Line item deleted.')
        except ValidationError as e:
            messages.error(request, str(e))

        return redirect('purchasing:bill_detail', bill_id=bill_id)

    return redirect('purchasing:bill_detail', bill_id=bill_id)
```

**Refactor reordering** (already exists at `apps/purchasing/views.py:300-337`):
```python
def bill_reorder_line_item(request, bill_id, line_item_id, direction):
    """Reorder line items within a Bill by swapping line numbers."""
    from apps.core.services import LineItemService
    from django.core.exceptions import ValidationError

    bill = get_object_or_404(Bill, bill_id=bill_id)
    line_item = get_object_or_404(BillLineItem, line_item_id=line_item_id, bill=bill)

    try:
        LineItemService.reorder_line_item(line_item, direction)
    except ValidationError as e:
        messages.error(request, str(e))

    return redirect('purchasing:bill_detail', bill_id=bill_id)
```

---

## Refactoring Checklist

To convert existing line item views to use the service:

### For Deletion Views:
- [ ] Import `LineItemService` and `ValidationError`
- [ ] Replace manual status check with service call
- [ ] Replace deletion + renumbering logic with `delete_line_item_with_renumber()`
- [ ] Use try/except for ValidationError
- [ ] Remove manual line number reassignment loop

**Before (35+ lines):**
```python
# Manual status check
if container.status != 'draft':
    messages.error(request, '...')
    return redirect(...)

# Manual deletion
line_item.delete()

# Manual renumbering
remaining_items = LineItemModel.objects.filter(...).order_by(...)
for index, item in enumerate(remaining_items, start=1):
    if item.line_number != index:
        item.line_number = index
        item.save()
```

**After (8 lines):**
```python
try:
    parent, line_num = LineItemService.delete_line_item_with_renumber(line_item)
    messages.success(request, 'Line item deleted.')
except ValidationError as e:
    messages.error(request, str(e))
```

### For Reordering Views:
- [ ] Import `LineItemService` and `ValidationError`
- [ ] Replace manual status check with service call
- [ ] Replace swap logic with `reorder_line_item()`
- [ ] Use try/except for ValidationError
- [ ] Remove manual index calculation and swapping

**Before (38+ lines):**
```python
# Manual status check
if container.status != 'draft':
    messages.error(request, '...')
    return redirect(...)

# Manual list building and index finding
all_items = list(LineItemModel.objects.filter(...).order_by(...))
try:
    current_index = next(i for i, item in enumerate(all_items) if ...)
except StopIteration:
    messages.error(...)
    return redirect(...)

# Manual direction checking
if direction == 'up' and current_index > 0:
    swap_index = current_index - 1
elif direction == 'down' and current_index < len(all_items) - 1:
    swap_index = current_index + 1
else:
    messages.error(...)
    return redirect(...)

# Manual swapping
current_item = all_items[current_index]
swap_item = all_items[swap_index]
current_item.line_number, swap_item.line_number = swap_item.line_number, current_item.line_number
current_item.save()
swap_item.save()
```

**After (6 lines):**
```python
try:
    LineItemService.reorder_line_item(line_item, direction)
except ValidationError as e:
    messages.error(request, str(e))
```

---

## Benefits of Using LineItemService

### 1. Code Reduction
- **Deletion**: ~35 lines → ~8 lines (77% reduction)
- **Reordering**: ~38 lines → ~6 lines (84% reduction)

### 2. Consistency
- All line item types use identical validation logic
- Consistent error messages across the application
- Single source of truth for "what status allows modifications"

### 3. Maintainability
- Change validation logic in one place
- Add new line item types easily
- Clear separation of concerns (views handle HTTP, service handles business logic)

### 4. Testing
- Test service logic once, applies to all line item types
- Mock service for view testing
- Easier to write comprehensive unit tests

### 5. No Model Changes Required
- Works with existing BaseLineItem infrastructure
- No database migrations needed
- No cross-app dependencies

---

## Pattern Summary

The `LineItemService` demonstrates **composition over inheritance**:

1. **Duck typing**: If it has a `status` field and uses 'draft', it works
2. **Introspection**: Uses `get_parent_field_name()` from BaseLineItem
3. **Single responsibility**: Service handles line item logic, views handle HTTP
4. **DRY principle**: Write once, use everywhere

This pattern can be extended to other shared functionality across document types without requiring a common superclass or complex inheritance hierarchies.

---

## Migration Path

### Phase 1: Core Implementation ✅
- [x] Create `LineItemService` in `apps.core.services`
- [x] Refactor `estimate_delete_line_item` to use service
- [x] Refactor `estimate_reorder_line_item` to use service

### Phase 2: Extend to Other Types (Recommended)
- [ ] Refactor `purchase_order_reorder_line_item`
- [ ] Refactor `bill_reorder_line_item`
- [ ] Add `invoice_delete_line_item` with service
- [ ] Add `invoice_reorder_line_item` with service
- [ ] Add `purchase_order_delete_line_item` with service
- [ ] Add `bill_delete_line_item` with service

### Phase 3: Testing
- [ ] Add unit tests for `LineItemService`
- [ ] Add integration tests with each line item type
- [ ] Test error cases (non-draft status, invalid direction, etc.)

---

## Common Pitfalls to Avoid

### ❌ Don't: Check status manually before calling service
```python
# DON'T DO THIS - service already validates
if estimate.status != 'draft':
    messages.error(request, '...')
    return redirect(...)

LineItemService.delete_line_item_with_renumber(line_item)  # Will validate again
```

### ✅ Do: Let service handle validation
```python
# DO THIS - let service validate and handle errors
try:
    LineItemService.delete_line_item_with_renumber(line_item)
    messages.success(request, 'Line item deleted.')
except ValidationError as e:
    messages.error(request, str(e))
```

---

### ❌ Don't: Extract parent manually
```python
# DON'T DO THIS - service can find parent
parent_field = line_item.get_parent_field_name()
parent = getattr(line_item, parent_field)
```

### ✅ Do: Use service helper if needed
```python
# DO THIS - if you need parent for some reason
parent = LineItemService.get_parent_container(line_item)
```

---

### ❌ Don't: Forget to import ValidationError
```python
from apps.core.services import LineItemService

# This will crash if validation fails!
parent, num = LineItemService.delete_line_item_with_renumber(line_item)
```

### ✅ Do: Import and handle ValidationError
```python
from apps.core.services import LineItemService
from django.core.exceptions import ValidationError

try:
    parent, num = LineItemService.delete_line_item_with_renumber(line_item)
except ValidationError as e:
    messages.error(request, str(e))
```
