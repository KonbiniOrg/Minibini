# apps/estimates/line_kind_backfill.py
#
# HISTORICAL MIGRATION HELPER — invoked by data migration
# estimates/0046_backfill_freeform_kind, which runs between 0045 (adds
# `freeform_kind` to EstimateLineItem/ChangeOrderLineItem) and 0047 (removes
# `is_material` from both). The `EstimateLineItem`/`ChangeOrderLineItem` args
# `backfill_estimate_line_item_kind`/`backfill_change_order_line_item_kind`
# take are HISTORICAL models (via apps.get_model), frozen at that exact point
# in schema history — always call those with historical models, never the
# live ones (by the time this task's migrations finish, the live models no
# longer have `is_material` at all).
#
# DO NOT sweep this file's field names (`is_material`, `freeform_kind`,
# `inventory_item_id`, `service_item_id`, `adjustment_service_id`) forward
# when a later phase touches them again — a blanket rename once broke
# `migrate` on a fresh database the same way (see
# apps/jobs/flat_fee_reframe.py's header): the historical model at THIS
# migration's position in history only has the fields as they existed then,
# regardless of what the live model looks like today.
#
# `compute_freeform_kind` is a pure function over scalar field values (not
# model instances), so it — unlike the two iterate/update wrappers below — is
# safe to unit test directly against the live schema forever: it has no
# dependency on `is_material` still existing as a column.
KIND_MATERIAL = 'material'
KIND_FEE = 'fee'


def compute_freeform_kind(*, inventory_item_id, service_item_id,
                           adjustment_service_id, is_material):
    """Mapping rule shared by EstimateLineItem and ChangeOrderLineItem.

    A line already resolved by an atom/service/adjustment descriptor is not a
    bare freeform line, so it maps to NULL regardless of is_material — the
    marker was never meaningful there. A bare line's historical is_material
    boolean maps onto the new three-value kind, preserving the historical
    bare-line default: True -> material, False -> fee (a bare non-material
    line has always crystallized to a Fee at acceptance).

    ChangeOrderLineItem has no adjustment_service field; callers pass
    adjustment_service_id=None for it, which is a no-op here.
    """
    if (inventory_item_id is not None
            or service_item_id is not None
            or adjustment_service_id is not None):
        return None
    return KIND_MATERIAL if is_material else KIND_FEE


def backfill_estimate_line_item_kind(EstimateLineItem):
    """Iterate + per-row update() (no custom save() side effects exist for
    freeform_kind on this historical model). Returns the row count touched."""
    updated = 0
    for li in EstimateLineItem.objects.iterator():
        kind = compute_freeform_kind(
            inventory_item_id=li.inventory_item_id,
            service_item_id=li.service_item_id,
            adjustment_service_id=li.adjustment_service_id,
            is_material=li.is_material,
        )
        EstimateLineItem.objects.filter(pk=li.pk).update(freeform_kind=kind)
        updated += 1
    return updated


def backfill_change_order_line_item_kind(ChangeOrderLineItem):
    """CO twin of backfill_estimate_line_item_kind — no adjustment_service
    field on this model, so that predicate is always None."""
    updated = 0
    for li in ChangeOrderLineItem.objects.iterator():
        kind = compute_freeform_kind(
            inventory_item_id=li.inventory_item_id,
            service_item_id=li.service_item_id,
            adjustment_service_id=None,
            is_material=li.is_material,
        )
        ChangeOrderLineItem.objects.filter(pk=li.pk).update(freeform_kind=kind)
        updated += 1
    return updated
