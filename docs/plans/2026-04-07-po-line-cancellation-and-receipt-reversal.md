# PO Line Item Cancellation & Receipt Reversal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PO line item `cancelled` boolean with `qty_cancelled` field, add receipt reversal, and update PO status transitions to support these operations.

**Architecture:** Two service operations (`cancel_line_item` refactored, `reverse_receipt` new) on `PurchaseOrderReceivingService`. Model gains `qty_cancelled` field, loses `cancelled` boolean. PO status transitions expanded to allow auto-cancellation of POs where all items are cancelled with nothing received, and reversal from `RECEIVED_IN_FULL` back to earlier states.

**Tech Stack:** Django 5.2+, Django REST Framework, MySQL, Svelte 5

**Design spec:** `docs/designs/2026-04-07-po-line-cancellation-and-receipt-reversal.md`

---

### Task 1: Migration — add `qty_cancelled`, remove `cancelled`

**Files:**
- Modify: `apps/purchasing/models.py:355-386`
- Create: new migration via `makemigrations`

- [ ] **Step 1: Update the model**

In `apps/purchasing/models.py`, in the `PurchaseOrderLineItem` class, replace the `cancelled` field:

```python
# Remove this line:
cancelled = models.BooleanField(default=False)

# Add this line (in the same position among the receiving fields):
qty_cancelled = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
```

- [ ] **Step 2: Create migrations**

Run:
```bash
python manage.py makemigrations purchasing
```

Expected: Migration created that adds `qty_cancelled` and removes `cancelled`.

**Note:** If the database has existing rows with `cancelled=True`, a data migration is needed. Since this is pre-production, the schema migration alone is sufficient — any seeded data can be re-seeded.

- [ ] **Step 3: Commit**

```bash
git add apps/purchasing/models.py apps/purchasing/migrations/
git commit -m "feat: replace cancelled boolean with qty_cancelled on PO line items"
```

---

### Task 2: Expand PO status transitions

The model's `clean()` method defines valid transitions. We need:
- `RECEIVED_IN_FULL → PARTLY_RECEIVED` (receipt reversal brings PO back)
- `RECEIVED_IN_FULL → ISSUED` (receipt reversal when ALL items reversed to 0)

Note: `PARTLY_RECEIVED → CANCELLED` is NOT needed. If a PO is partly received, goods have been received — the PO can't be fully cancelled. The auto-cancel only fires when all items are cancelled with nothing received, meaning the PO is still in ISSUED status.

**Files:**
- Test: `tests/test_po_receiving.py`
- Modify: `apps/purchasing/models.py:61-68`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_po_receiving.py`:

```python
class POStatusTransitionTest(POReceivingTestBase):

    def test_received_in_full_to_partly_received_allowed(self):
        """PO can go back to partly_received after receipt reversal."""
        po = self._make_issued_po()
        po.status = PurchaseOrder.STATUS_PARTLY_RECEIVED
        po.save()
        po.status = PurchaseOrder.STATUS_RECEIVED_IN_FULL
        po.save()
        po.status = PurchaseOrder.STATUS_PARTLY_RECEIVED
        po.full_clean()  # Should not raise

    def test_received_in_full_to_issued_allowed(self):
        """PO can go back to issued after all receipts reversed."""
        po = self._make_issued_po()
        po.status = PurchaseOrder.STATUS_PARTLY_RECEIVED
        po.save()
        po.status = PurchaseOrder.STATUS_RECEIVED_IN_FULL
        po.save()
        po.status = PurchaseOrder.STATUS_ISSUED
        po.full_clean()  # Should not raise

    def test_partly_received_to_cancelled_not_allowed(self):
        """PO cannot go from partly_received to cancelled directly."""
        po = self._make_issued_po()
        po.status = PurchaseOrder.STATUS_PARTLY_RECEIVED
        po.save()
        po.status = PurchaseOrder.STATUS_CANCELLED
        with self.assertRaises(ValidationError):
            po.full_clean()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_po_receiving.POStatusTransitionTest -v 2`
Expected: FAIL — `ValidationError` on the `RECEIVED_IN_FULL` transitions (currently terminal); the `PARTLY_RECEIVED → CANCELLED` test should pass already (it's already disallowed).

- [ ] **Step 3: Update the valid transitions**

In `apps/purchasing/models.py`, update the `VALID_TRANSITIONS` dict inside `PurchaseOrder.clean()`:

```python
VALID_TRANSITIONS = {
    PurchaseOrder.STATUS_DRAFT: [PurchaseOrder.STATUS_ISSUED],
    PurchaseOrder.STATUS_ISSUED: [PurchaseOrder.STATUS_PARTLY_RECEIVED, PurchaseOrder.STATUS_RECEIVED_IN_FULL, PurchaseOrder.STATUS_CANCELLED],
    PurchaseOrder.STATUS_PARTLY_RECEIVED: [PurchaseOrder.STATUS_RECEIVED_IN_FULL],
    PurchaseOrder.STATUS_RECEIVED_IN_FULL: [PurchaseOrder.STATUS_PARTLY_RECEIVED, PurchaseOrder.STATUS_ISSUED],
    PurchaseOrder.STATUS_CANCELLED: [],  # Terminal state
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_po_receiving.POStatusTransitionTest -v 2`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `python manage.py test -v 2`
Expected: All pass. (Some existing tests that reference `li.cancelled` will fail — that's expected and addressed in Task 3.)

- [ ] **Step 6: Commit**

```bash
git add apps/purchasing/models.py tests/test_po_receiving.py
git commit -m "feat: expand PO status transitions for receipt reversal"
```

---

### Task 3: Refactor `cancel_line_item`, `cancel_po`, and `_update_po_status`

**Files:**
- Test: `tests/test_po_receiving.py` (update `CancelLineItemTest`)
- Test: `tests/test_purchasing_services.py` (update `cancel_po` test)
- Modify: `apps/purchasing/services.py` (PurchaseOrderService.cancel_po, PurchaseOrderReceivingService.cancel_line_item, _update_po_status)

- [ ] **Step 1: Rewrite the cancel line item tests**

Replace the entire `CancelLineItemTest` class in `tests/test_po_receiving.py`:

```python
class CancelLineItemTest(POReceivingTestBase):

    def test_cancel_unreceived_line_item(self):
        """Cancel a line with 0 received — qty_cancelled should equal qty."""
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': li.pk, 'note': 'Vendor out of stock'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        li.refresh_from_db()
        self.assertEqual(li.qty_cancelled, li.qty)

    def test_cancel_partially_received_line_item(self):
        """Cancel remaining on a partially received line."""
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        li.qty_received = Decimal('3.00')
        li.save()
        po.status = PurchaseOrder.STATUS_PARTLY_RECEIVED
        po.save()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': li.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        li.refresh_from_db()
        self.assertEqual(li.qty_cancelled, Decimal('7.00'))
        self.assertEqual(li.qty_received + li.qty_cancelled, li.qty)

    def test_cancel_line_creates_history(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': li.pk, 'note': 'Vendor out of stock'},
            format='json',
        )
        entry = HistoryEntry.objects.filter(
            object_type='purchaseorder', object_id=po.pk,
            entry_type='action',
        ).first()
        self.assertIsNotNone(entry)
        self.assertIn('cancelled', entry.changes.get('_action', '').lower())
        self.assertEqual(entry.text, 'Vendor out of stock')

    def test_cancel_already_done_line_rejected(self):
        """Cannot cancel a line where qty_received + qty_cancelled == qty."""
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        li.qty_cancelled = li.qty
        li.save()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': li.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_cancel_fully_received_rejected(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        li.qty_received = li.qty
        li.save()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': li.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_cancel_all_unreceived_lines_marks_received_if_others_done(self):
        """If the only outstanding line is cancelled, PO becomes received_in_full."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        # Receive first item fully
        items[0].qty_received = items[0].qty
        items[0].save()
        # Cancel second item
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_RECEIVED_IN_FULL)

    def test_cancel_all_lines_no_receipts_cancels_po(self):
        """If all lines are fully cancelled with nothing received, PO auto-cancels via cancel_po."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        # Cancel first item
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[0].pk},
            format='json',
        )
        # Cancel second item — should trigger auto-cancel of PO
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_CANCELLED)
        # Verify cancel_po set qty_cancelled on ALL line items
        for li in PurchaseOrderLineItem.objects.filter(purchase_order=po):
            self.assertEqual(li.qty_cancelled, li.qty)


class POStatusAutoTransitionTest(POReceivingTestBase):
    """Comprehensive tests for PO status auto-transitions across multi-line scenarios."""

    def test_receive_one_cancel_other_gives_received_in_full(self):
        """2 items: receive one fully, cancel the other → RECEIVED_IN_FULL."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        # Receive first item fully
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': items[0].pk, 'qty_received': float(items[0].qty)}]},
            format='json',
        )
        # Cancel second item
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_RECEIVED_IN_FULL)

    def test_receive_one_cancel_other_then_reverse_gives_issued(self):
        """2 items: receive one, cancel other → RECEIVED_IN_FULL. Reverse receipt → ISSUED."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        # Receive first, cancel second
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': items[0].pk, 'qty_received': float(items[0].qty)}]},
            format='json',
        )
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        # Reverse the received item
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': items[0].pk},
            format='json',
        )
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_ISSUED)

    def test_partial_receive_cancel_other_gives_partly_received(self):
        """2 items: receive one partially, cancel the other → PARTLY_RECEIVED."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        # Partial receive first item
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': items[0].pk, 'qty_received': 3}]},
            format='json',
        )
        # Cancel second item
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_PARTLY_RECEIVED)

    def test_partial_receive_cancel_other_then_reverse_gives_issued(self):
        """2 items: partial receive one, cancel other → PARTLY_RECEIVED. Reverse → ISSUED."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        # Partial receive, cancel other
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': items[0].pk, 'qty_received': 3}]},
            format='json',
        )
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        # Reverse the partial receipt
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': items[0].pk},
            format='json',
        )
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_ISSUED)

    def test_cancel_both_lines_cancels_po_with_line_items_set(self):
        """2 items: cancel both → CANCELLED. All line items have qty_cancelled == qty."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[0].pk},
            format='json',
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_CANCELLED)
        for li in PurchaseOrderLineItem.objects.filter(purchase_order=po):
            self.assertEqual(li.qty_cancelled, li.qty)

    def test_receive_all_then_reverse_one_gives_partly_received(self):
        """Receive all → RECEIVED_IN_FULL. Reverse one → PARTLY_RECEIVED."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        self.client.post(f'/api/purchase-orders/{po.po_id}/receive-all/')
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': items[0].pk},
            format='json',
        )
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_PARTLY_RECEIVED)

    def test_receive_all_then_reverse_all_gives_issued(self):
        """Receive all → RECEIVED_IN_FULL. Reverse both → ISSUED."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        self.client.post(f'/api/purchase-orders/{po.po_id}/receive-all/')
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': items[0].pk},
            format='json',
        )
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': items[1].pk},
            format='json',
        )
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_ISSUED)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_po_receiving.CancelLineItemTest tests.test_po_receiving.POStatusAutoTransitionTest -v 2`
Expected: FAIL — `cancelled` field no longer exists, and service still uses old logic.

- [ ] **Step 3: Update `cancel_po` to also set `qty_cancelled` on all line items**

In `apps/purchasing/services.py`, update `PurchaseOrderService.cancel_po`:

```python
@staticmethod
def cancel_po(pk):
    """Cancel an issued PO and mark all line items as cancelled."""
    try:
        po = PurchaseOrder.objects.get(pk=pk)
    except PurchaseOrder.DoesNotExist:
        raise NotFoundError(f'PurchaseOrder {pk} not found')
    if po.status != PurchaseOrder.STATUS_ISSUED:
        raise ValidationError(
            f'Cannot cancel PO {po.po_number}. Only issued POs can be cancelled.'
        )
    with transaction.atomic():
        po.status = PurchaseOrder.STATUS_CANCELLED
        po.full_clean()
        po.save()
        # Set qty_cancelled on all line items
        for li in PurchaseOrderLineItem.objects.filter(purchase_order=po):
            li.qty_cancelled = li.qty - li.qty_received
            li.save(update_fields=['qty_cancelled'])
    return po
```

- [ ] **Step 4: Rewrite `cancel_line_item` and `_update_po_status`**

In `apps/purchasing/services.py`, replace `cancel_line_item` and `_update_po_status` in `PurchaseOrderReceivingService`:

```python
@staticmethod
def cancel_line_item(po, line_item_id, user, note=''):
    """Cancel remaining quantity on a line item."""
    from apps.core.models import HistoryEntry

    if po.status not in (
        PurchaseOrder.STATUS_ISSUED,
        PurchaseOrder.STATUS_PARTLY_RECEIVED,
    ):
        raise ValidationError(
            f'Cannot cancel line items on a PO in status "{po.status}".'
        )

    with transaction.atomic():
        li = PurchaseOrderLineItem.objects.select_for_update().get(
            pk=line_item_id, purchase_order=po,
        )
        if li.qty_received + li.qty_cancelled >= li.qty:
            raise ValidationError(
                f'Line item #{li.line_number} has no outstanding quantity to cancel.'
            )

        qty_to_cancel = li.qty - li.qty_received - li.qty_cancelled
        li.qty_cancelled = li.qty - li.qty_received
        li.save(update_fields=['qty_cancelled'])

        HistoryEntry.objects.create(
            entry_type='action',
            object_type='purchaseorder',
            object_id=po.pk,
            user=user,
            changes={'_action': f'Line #{li.line_number} cancelled ({qty_to_cancel} remaining): {li.description}'},
            text=note,
        )

        PurchaseOrderReceivingService._update_po_status(po)

    return po

@staticmethod
def _update_po_status(po):
    """Recalculate PO status based on line item receipt state."""
    all_items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
    if not all_items:
        return

    all_done = all(li.qty_received + li.qty_cancelled == li.qty for li in all_items)
    any_received = any(li.qty_received > 0 for li in all_items)

    if all_done and any_received:
        if po.status != PurchaseOrder.STATUS_RECEIVED_IN_FULL:
            po.status = PurchaseOrder.STATUS_RECEIVED_IN_FULL
            po.full_clean()
            po.save()
    elif all_done and not any_received:
        # Everything cancelled, nothing received — delegate to cancel_po
        # which handles status change AND sets qty_cancelled on all line items
        if po.status != PurchaseOrder.STATUS_CANCELLED:
            PurchaseOrderService.cancel_po(po.pk)
            po.refresh_from_db()
    elif any_received:
        if po.status != PurchaseOrder.STATUS_PARTLY_RECEIVED:
            po.status = PurchaseOrder.STATUS_PARTLY_RECEIVED
            po.full_clean()
            po.save()
    else:
        # Nothing received, not all done — back to issued
        if po.status not in (PurchaseOrder.STATUS_ISSUED, PurchaseOrder.STATUS_DRAFT):
            po.status = PurchaseOrder.STATUS_ISSUED
            po.full_clean()
            po.save()
```

- [ ] **Step 5: Update `receive_items` to check `qty_cancelled` instead of `cancelled`**

In `apps/purchasing/services.py`, in the `receive_items` method, replace the cancelled check (around line 222-225):

```python
# Replace:
if li.cancelled:
    raise ValidationError(
        f'Line item #{li.line_number} is cancelled.'
    )

# With:
if li.qty_received + li.qty_cancelled >= li.qty:
    raise ValidationError(
        f'Line item #{li.line_number} has no outstanding quantity to receive.'
    )
```

- [ ] **Step 6: Update `receive_all` to use `qty_cancelled` instead of `cancelled=False`**

In `apps/purchasing/services.py`, in the `receive_all` method, replace the queryset filter (around line 278-283):

```python
# Replace:
line_items = PurchaseOrderLineItem.objects.filter(
    purchase_order=po, cancelled=False,
)
items = []
for li in line_items:
    remaining = li.qty - li.qty_received
    if remaining > 0:

# With:
line_items = PurchaseOrderLineItem.objects.filter(purchase_order=po)
items = []
for li in line_items:
    remaining = li.qty - li.qty_received - li.qty_cancelled
    if remaining > 0:
```

- [ ] **Step 7: Run cancel and auto-transition tests to verify they pass**

Run: `python manage.py test tests.test_po_receiving.CancelLineItemTest tests.test_po_receiving.POStatusAutoTransitionTest -v 2`
Expected: PASS

- [ ] **Step 8: Update `cancel_po` test in test_purchasing_services.py**

Update the existing `cancel_po` test to verify that line items get `qty_cancelled` set:

```python
def test_cancel_po(self):
    po = self._create_issued_po()
    cancelled = PurchaseOrderService.cancel_po(po.pk)
    self.assertEqual(cancelled.status, PurchaseOrder.STATUS_CANCELLED)
    # Verify all line items have qty_cancelled set
    for li in PurchaseOrderLineItem.objects.filter(purchase_order=po):
        self.assertEqual(li.qty_cancelled, li.qty)
```

- [ ] **Step 9: Update remaining receive tests that reference `cancelled`**

In `tests/test_po_receiving.py`, update `test_receive_cancelled_line_rejected` in `ReceiveItemsTest`:

```python
def test_receive_done_line_rejected(self):
    po = self._make_issued_po()
    li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
    li.qty_cancelled = li.qty
    li.save()
    response = self.client.post(
        f'/api/purchase-orders/{po.po_id}/receive/',
        {'items': [{'line_item_id': li.pk, 'qty_received': 5}]},
        format='json',
    )
    self.assertEqual(response.status_code, 400)
```

Update `SerializerReceivingFieldsTest.test_line_items_include_receiving_fields`:

```python
def test_line_items_include_receiving_fields(self):
    po = self._make_issued_po()
    response = self.client.get(f'/api/purchase-orders/{po.po_id}/')
    li = response.data['line_items'][0]
    self.assertIn('qty_received', li)
    self.assertIn('received_date', li)
    self.assertIn('qty_cancelled', li)
    self.assertIn('receipt_note', li)
    self.assertIn('received_by_name', li)
```

- [ ] **Step 10: Run full receiving test suite**

Run: `python manage.py test tests.test_po_receiving -v 2`
Expected: All pass.

- [ ] **Step 11: Commit**

```bash
git add apps/purchasing/services.py tests/test_po_receiving.py tests/test_purchasing_services.py
git commit -m "feat: refactor cancel_line_item to use qty_cancelled, route auto-cancel through cancel_po"
```

---

### Task 4: Add `reverse_receipt` service method

**Files:**
- Test: `tests/test_po_receiving.py`
- Modify: `apps/purchasing/services.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_po_receiving.py`:

```python
class ReverseReceiptTest(POReceivingTestBase):

    def test_reverse_receipt_resets_qty(self):
        """Reversing a receipt resets qty_received to 0."""
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        # Receive some
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li.pk, 'qty_received': 5}]},
            format='json',
        )
        li.refresh_from_db()
        self.assertEqual(li.qty_received, Decimal('5.00'))
        # Reverse
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': li.pk, 'note': 'Entered in error'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        li.refresh_from_db()
        self.assertEqual(li.qty_received, Decimal('0.00'))
        self.assertIsNone(li.received_by)
        self.assertIsNone(li.received_date)
        self.assertEqual(li.receipt_note, '')

    def test_reverse_receipt_updates_inventory(self):
        """Reversing a receipt decrements qty_on_hand and creates adjustment."""
        po = self._make_issued_po(with_pli=True)
        pli = PriceListItem.objects.get(code='TEST-PLI-RECV')
        li = PurchaseOrderLineItem.objects.filter(
            purchase_order=po, price_list_item=pli,
        ).first()
        # Receive
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li.pk, 'qty_received': 7}]},
            format='json',
        )
        pli.refresh_from_db()
        self.assertEqual(pli.qty_on_hand, Decimal('7.00'))
        # Reverse
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': li.pk},
            format='json',
        )
        pli.refresh_from_db()
        self.assertEqual(pli.qty_on_hand, Decimal('0.00'))
        # Check adjustment
        adjustments = InventoryAdjustment.objects.filter(price_list_item=pli)
        self.assertEqual(adjustments.count(), 2)
        reversal = adjustments.order_by('-pk').first()
        self.assertEqual(reversal.quantity_change, Decimal('-7.00'))
        self.assertIn('Reversed', reversal.reason)

    def test_reverse_receipt_clears_qty_cancelled(self):
        """If a line was partially received then cancelled, reversing clears both."""
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        # Receive 5 of 10
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li.pk, 'qty_received': 5}]},
            format='json',
        )
        # Cancel remaining 5
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/cancel-line-item/',
            {'line_item_id': li.pk},
            format='json',
        )
        li.refresh_from_db()
        self.assertEqual(li.qty_cancelled, Decimal('5.00'))
        # Reverse the receipt — should reset both
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': li.pk},
            format='json',
        )
        li.refresh_from_db()
        self.assertEqual(li.qty_received, Decimal('0.00'))
        self.assertEqual(li.qty_cancelled, Decimal('0.00'))

    def test_reverse_receipt_creates_history(self):
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li.pk, 'qty_received': 5}]},
            format='json',
        )
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': li.pk, 'note': 'Wrong item scanned'},
            format='json',
        )
        entries = HistoryEntry.objects.filter(
            object_type='purchaseorder', object_id=po.pk,
            entry_type='action',
        ).order_by('-pk')
        reversal_entry = entries.first()
        self.assertIn('reversed', reversal_entry.changes.get('_action', '').lower())
        self.assertEqual(reversal_entry.text, 'Wrong item scanned')

    def test_reverse_receipt_no_qty_received_rejected(self):
        """Cannot reverse a line with 0 received."""
        po = self._make_issued_po()
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': li.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_reverse_receipt_updates_po_status(self):
        """Reversing the only received line should change PO back from partly_received."""
        po = self._make_issued_po(num_items=1)
        li = PurchaseOrderLineItem.objects.filter(purchase_order=po).first()
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive/',
            {'items': [{'line_item_id': li.pk, 'qty_received': 5}]},
            format='json',
        )
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_PARTLY_RECEIVED)
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': li.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_ISSUED)

    def test_reverse_on_fully_received_po(self):
        """Can reverse a receipt on a RECEIVED_IN_FULL PO."""
        po = self._make_issued_po(num_items=2)
        items = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        self.client.post(
            f'/api/purchase-orders/{po.po_id}/receive-all/',
        )
        po.refresh_from_db()
        self.assertEqual(po.status, PurchaseOrder.STATUS_RECEIVED_IN_FULL)
        # Reverse one line
        response = self.client.post(
            f'/api/purchase-orders/{po.po_id}/reverse-receipt/',
            {'line_item_id': items[0].pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], PurchaseOrder.STATUS_PARTLY_RECEIVED)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_po_receiving.ReverseReceiptTest -v 2`
Expected: FAIL — no `reverse-receipt` endpoint exists.

- [ ] **Step 3: Implement `reverse_receipt` in services.py**

Add to `PurchaseOrderReceivingService` in `apps/purchasing/services.py`, after the `cancel_line_item` method:

```python
@staticmethod
def reverse_receipt(po, line_item_id, user, note=''):
    """Reverse all received quantity on a line item (data correction)."""
    from apps.core.models import HistoryEntry
    from apps.inventory.models import InventoryAdjustment
    from django.utils import timezone

    if po.status not in (
        PurchaseOrder.STATUS_ISSUED,
        PurchaseOrder.STATUS_PARTLY_RECEIVED,
        PurchaseOrder.STATUS_RECEIVED_IN_FULL,
    ):
        raise ValidationError(
            f'Cannot reverse receipts on a PO in status "{po.status}".'
        )

    with transaction.atomic():
        li = PurchaseOrderLineItem.objects.select_for_update().get(
            pk=line_item_id, purchase_order=po,
        )
        if li.qty_received <= 0:
            raise ValidationError(
                f'Line item #{li.line_number} has no received quantity to reverse.'
            )

        reversed_qty = li.qty_received

        # Reverse inventory
        if li.price_list_item and li.price_list_item.is_inventoried:
            li.price_list_item.qty_on_hand -= reversed_qty
            li.price_list_item.save(update_fields=['qty_on_hand'])
            InventoryAdjustment.objects.create(
                price_list_item=li.price_list_item,
                quantity_change=-reversed_qty,
                reason=f'Reversed receipt on {po.po_number}',
            )

        # Reset line item
        li.qty_received = Decimal('0.00')
        li.qty_cancelled = Decimal('0.00')
        li.received_by = None
        li.received_date = None
        li.receipt_note = ''
        li.save(update_fields=[
            'qty_received', 'qty_cancelled',
            'received_by', 'received_date', 'receipt_note',
        ])

        HistoryEntry.objects.create(
            entry_type='action',
            object_type='purchaseorder',
            object_id=po.pk,
            user=user,
            changes={'_action': f'Line #{li.line_number} receipt reversed ({reversed_qty}): {li.description}'},
            text=note,
        )

        PurchaseOrderReceivingService._update_po_status(po)

    return po
```

- [ ] **Step 4: Run tests to verify they still fail (no endpoint yet)**

Run: `python manage.py test tests.test_po_receiving.ReverseReceiptTest -v 2`
Expected: FAIL — 404 on `/reverse-receipt/` endpoint.

- [ ] **Step 5: Commit service method**

```bash
git add apps/purchasing/services.py tests/test_po_receiving.py
git commit -m "feat: add reverse_receipt service method with tests"
```

---

### Task 5: Add `reverse-receipt` API endpoint

**Files:**
- Modify: `apps/api/purchasing/views.py`

- [ ] **Step 1: Add the endpoint to PurchaseOrderViewSet**

In `apps/api/purchasing/views.py`, add `reverse_receipt` to `get_permissions` and add the action method.

Update `get_permissions` — add `'reverse_receipt'` to the `IsAuthenticated`-only list:

```python
if self.action in (
    'list', 'retrieve', 'history', 'notes', 'send_defaults',
    'receive', 'receive_all', 'receipts', 'cancel_line_item',
    'reverse_receipt',
):
    return [IsAuthenticated()]
```

Add the action method after the `cancel_line_item` method:

```python
@action(detail=True, methods=['post'], url_path='reverse-receipt', url_name='reverse-receipt')
def reverse_receipt(self, request, pk=None):
    """Reverse all received quantity on a line item."""
    po = self.get_object()
    line_item_id = request.data.get('line_item_id')
    note = request.data.get('note', '')
    if not line_item_id:
        return Response(
            {'line_item_id': ['This field is required.']},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        po = PurchaseOrderReceivingService.reverse_receipt(
            po, line_item_id, request.user, note=note,
        )
    except Exception as e:
        return Response(
            {'detail': str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    serializer = self.get_serializer(po)
    return Response(serializer.data)
```

- [ ] **Step 2: Run reverse receipt tests**

Run: `python manage.py test tests.test_po_receiving.ReverseReceiptTest -v 2`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/api/purchasing/views.py
git commit -m "feat: add reverse-receipt API endpoint"
```

---

### Task 6: Update serializer

**Files:**
- Modify: `apps/api/purchasing/serializers.py:18-40`

- [ ] **Step 1: Update POLineItemSerializer**

In `apps/api/purchasing/serializers.py`, replace `'cancelled'` with `'qty_cancelled'` in both `fields` and `read_only_fields`:

```python
class POLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    received_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderLineItem
        fields = [
            'line_item_id', 'line_number', 'task', 'price_list_item',
            'qty', 'units', 'description', 'price', 'job',
            'accounting_category', 'taxable_override', 'tax_rate_override',
            'qty_received', 'received_by', 'received_by_name',
            'received_date', 'receipt_note', 'qty_cancelled',
        ]
        read_only_fields = [
            'line_item_id', 'qty_received', 'received_by', 'received_by_name',
            'received_date', 'receipt_note', 'qty_cancelled',
        ]

    def get_received_by_name(self, obj):
        if obj.received_by:
            return obj.received_by.get_full_name() or obj.received_by.username
        return None
```

- [ ] **Step 2: Run serializer tests**

Run: `python manage.py test tests.test_po_receiving.SerializerReceivingFieldsTest -v 2`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add apps/api/purchasing/serializers.py
git commit -m "feat: update POLineItemSerializer — replace cancelled with qty_cancelled"
```

---

### Task 7: Update Svelte frontend

**Files:**
- Modify: `frontend/src/components/purchaseorders/PurchaseOrderDetail.svelte`
- Modify: `frontend/src/components/purchaseorders/ReceiveItemsForm.svelte`
- Modify: `frontend/src/routes/purchaseorders/PurchaseOrderDetailPage.svelte`

- [ ] **Step 1: Update PurchaseOrderDetail.svelte**

In `frontend/src/components/purchaseorders/PurchaseOrderDetail.svelte`, replace all `li.cancelled` references with the derived check. The line item is "done" when `qty_received + qty_cancelled == qty`, and "fully cancelled" when `qty_cancelled == qty`.

Replace the line item row rendering (around lines 183-229):

```svelte
      <tr class:cancelled-row={Number(li.qty_cancelled) >= Number(li.qty)}>
            <td>{li.line_number}</td>
            <td>{li.description}</td>
            <td class="text-right">{li.qty}</td>
            <td>{li.units || ''}</td>
            <td class="text-right">${Number(li.price).toFixed(2)}</td>
            <td class="text-right">${(Number(li.qty) * Number(li.price)).toFixed(2)}</td>
            {#if showReceived}
              <td class="text-right">
                {#if Number(li.qty_cancelled) >= Number(li.qty)}
                  —
                {:else if Number(li.qty_received) > 0}
                  {li.qty_received}
                  {#if Number(li.qty_cancelled) > 0}
                    <br><small>({li.qty_cancelled} cancelled)</small>
                  {/if}
                  {#if li.received_date}
                    <br><small>{formatDate(li.received_date)}</small>
                  {/if}
                {:else}
                  0
                {/if}
              </td>
              <td>
                {#if Number(li.qty_received) + Number(li.qty_cancelled) >= Number(li.qty) && Number(li.qty_cancelled) >= Number(li.qty)}
                  <span class="line-status cancelled">Cancelled</span>
                {:else if Number(li.qty_received) + Number(li.qty_cancelled) >= Number(li.qty)}
                  <span class="line-status received">Received</span>
                {:else if Number(li.qty_received) > 0}
                  <span class="line-status partial">Partial</span>
                {:else}
                  <span class="line-status pending">Pending</span>
                {/if}
              </td>
            {/if}
            {#if canManageFinancials && po.status === 'draft'}
              <td>
                <button onclick={() => startEdit(li)}>Edit</button>
                <button onclick={() => moveUp(i)} disabled={i === 0}>&#9650;</button>
                <button onclick={() => moveDown(i)} disabled={i === lineItems.length - 1}>&#9660;</button>
                <button onclick={() => onDeleteLineItem(li)}>Delete</button>
              </td>
            {/if}
            {#if canReceive}
              <td>
                {#if Number(li.qty_received) + Number(li.qty_cancelled) < Number(li.qty)}
                  <button onclick={() => handleCancelLine(li)}>Cancel Line</button>
                {/if}
                {#if Number(li.qty_received) > 0}
                  <button onclick={() => handleReverseLine(li)}>Reverse Receipt</button>
                {/if}
              </td>
            {/if}
          </tr>
```

Also update the CSS — rename `.cancelled-row` is fine as-is since it's still used.

- [ ] **Step 2: Update ReceiveItemsForm.svelte**

In `frontend/src/components/purchaseorders/ReceiveItemsForm.svelte`, update the filter on line 10:

```svelte
let receivableItems = $derived(
    lineItems.filter(li => Number(li.qty_received) + Number(li.qty_cancelled) < Number(li.qty))
);
```

- [ ] **Step 3: Update PurchaseOrderDetailPage.svelte**

In `frontend/src/routes/purchaseorders/PurchaseOrderDetailPage.svelte`, add a `handleReverseReceipt` function after `handleCancelLineItem`:

```javascript
async function handleReverseReceipt(lineItemId, note) {
    busy = true;
    error = null;
    success = null;
    try {
      await api.post(`/api/purchase-orders/${po.po_id}/reverse-receipt/`, {
        line_item_id: lineItemId,
        note,
      });
      success = 'Receipt reversed.';
      await reload();
    } catch (e) {
      error = e.data?.detail || e.message;
    } finally {
      busy = false;
    }
  }
```

Pass `handleReverseLine` as a prop to `PurchaseOrderDetail`:

Check how `handleCancelLine` is wired — it likely uses `onCancelLine` prop. Wire `handleReverseLine` the same way via an `onReverseLine` prop. In the detail page where `PurchaseOrderDetail` is rendered, add the prop:

```svelte
onReverseLine={(li) => handleReverseReceipt(li.line_item_id)}
```

And in `PurchaseOrderDetail.svelte`, accept the prop:

```svelte
const {
    ...,
    onReverseLine,
} = $props();

function handleReverseLine(li) {
    onReverseLine(li);
}
```

- [ ] **Step 4: Test manually**

Start both servers (`python manage.py runserver` and `cd frontend && npm run dev`). Navigate to an issued PO with line items. Verify:
- Cancel Line button appears for lines with outstanding quantity
- Reverse Receipt button appears for lines with received quantity
- Both operations work and update the display

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/purchaseorders/PurchaseOrderDetail.svelte frontend/src/components/purchaseorders/ReceiveItemsForm.svelte frontend/src/routes/purchaseorders/PurchaseOrderDetailPage.svelte
git commit -m "feat: update Svelte frontend for qty_cancelled and reverse receipt"
```

---

### Task 8: Full regression test

- [ ] **Step 1: Run the full test suite**

Run: `python manage.py test -v 2`
Expected: All pass.

- [ ] **Step 2: Grep for any remaining references to the old `cancelled` boolean on PO line items**

Run:
```bash
grep -rn '\.cancelled' apps/purchasing/ apps/api/purchasing/ tests/test_po_receiving.py frontend/src/components/purchaseorders/ frontend/src/routes/purchaseorders/ --include='*.py' --include='*.svelte' --include='*.js'
```

Expected: No references to `.cancelled` on PO line items. (Bill `cancelled_date` references are unrelated and expected.)

- [ ] **Step 3: Fix any remaining references found in Step 2**

- [ ] **Step 4: Run full test suite again if fixes were made**

Run: `python manage.py test -v 2`

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix: clean up remaining references to old cancelled boolean"
```
