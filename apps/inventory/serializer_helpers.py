from rest_framework import serializers


# Fields editable on PLI-linked Material / PlanMaterial.
PLI_LINKED_PRICING_ALLOWED = {'unit_cost', 'sell_price', 'propagate_to_pli'}

# Fields editable on freeform (no PLI) Material / PlanMaterial.
FREEFORM_ALLOWED = {
    'description', 'units', 'unit_cost', 'sell_price', 'accounting_category',
    'propagate_to_pli',
}

# PlanMaterial freeform allowlist — same as Material's plus 'quantity'.
# PlanMaterial has no Restock/Draw-more state-machine ops (no inventory
# accounting), so quantity must be PATCH-editable after create.
PLAN_MATERIAL_FREEFORM_ALLOWED = FREEFORM_ALLOWED | {'quantity'}


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


def enforce_pli_linked_allowlist(instance, validated_data, allowed):
    """Raise serializers.ValidationError if validated_data has any field
    outside `allowed` while the instance is PLI-linked.

    `allowed` is a set of field names. Use PLI_LINKED_PRICING_ALLOWED for
    Material/PlanMaterial.
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
