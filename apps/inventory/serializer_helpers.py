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

# TemplateMaterial allowlists: PLI-linked only allows quantity + sort_order
# (no pricing carve-out — templates are catalog config, not cost capture).
TEMPLATE_PLI_LINKED_ALLOWED = {'quantity', 'sort_order'}
TEMPLATE_FREEFORM_ALLOWED = {
    'description', 'units', 'quantity', 'unit_cost', 'sell_price',
    'accounting_category', 'sort_order',
}


def enforce_pli_linked_allowlist(instance, validated_data, allowed):
    """Raise serializers.ValidationError if validated_data has any field
    outside `allowed` while the instance is PLI-linked.

    `allowed` is a set of field names. Use PLI_LINKED_PRICING_ALLOWED for
    Material/PlanMaterial; pass TEMPLATE_PLI_LINKED_ALLOWED for TemplateMaterial.
    """
    if instance.price_list_item_id is None:
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
