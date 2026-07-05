from rest_framework import serializers


# Fields editable on PLI-linked Material.
PLI_LINKED_PRICING_ALLOWED = {'unit_cost', 'sell_price', 'propagate_to_pli'}

# Fields editable on freeform (no PLI) Material.
FREEFORM_ALLOWED = {
    'description', 'units', 'unit_cost', 'sell_price', 'accounting_category',
    'propagate_to_pli',
}


def material_qty_on_hand(obj):
    """Canonical 'stock on hand' string for a Material row, shared by the
    inventory-app and tasks-app MaterialSerializers so the value can't drift.

    - a consumed material reports 0 (its stock is already drawn down)
    - a PO-backed material reports the PO line's received qty
    - an inventory-item-backed material reports the item's real QOH (NOT the
      material's required quantity), so the overview's needs-more/order check
      sees a genuine shortfall. Earmark-aware availability is separate
      (qty_available).
    - a freeform (no item, no PO) material reports 0
    """
    from apps.inventory.models import Material
    if obj.consumption_state == Material.CONSUMPTION_STATE_CONSUMED:
        return '0'
    if obj.po_line_item_id:
        return str(obj.po_line_item.qty_received)
    if obj.inventory_item_id:
        return str(obj.inventory_item.qty_on_hand)
    return '0'


def material_qty_on_order(obj):
    """Outstanding (un-received, un-cancelled) qty on the Material's linked PO
    line, as a string. Shared by both MaterialSerializers; materialStatus.js
    requires a live outstanding balance before it shows the Ordered pill —
    a fully received PO is history, not this row's incoming supply.
    """
    from decimal import Decimal
    pol = material_po_line_item(obj)
    if pol is None:
        return '0'
    outstanding = pol.qty - pol.qty_received - pol.qty_cancelled
    return str(max(outstanding, Decimal('0')))


def material_po_line_item(obj):
    """Returns the PurchaseOrderLineItem behind a Material if it has one, else
    None. Shared by the inventory-app and tasks-app MaterialSerializers so the
    po_id/po_number/po_status derivations can't drift.
    """
    if obj.po_line_item_id and obj.po_line_item:
        return obj.po_line_item
    return None


def enforce_pli_linked_allowlist(instance, validated_data, allowed):
    """Raise serializers.ValidationError if validated_data has any field
    outside `allowed` while the instance is PLI-linked.

    `allowed` is a set of field names. Use PLI_LINKED_PRICING_ALLOWED for
    Material.
    """
    if instance.inventory_item_id is None:
        return
    disallowed = set(validated_data.keys()) - allowed
    if disallowed:
        raise serializers.ValidationError({
            'detail': (
                'PLI-linked materials are immutable except for pricing; '
                'delete and re-add as freeform to change other fields. '
                f'Disallowed fields: {sorted(disallowed)}'
            )
        })
