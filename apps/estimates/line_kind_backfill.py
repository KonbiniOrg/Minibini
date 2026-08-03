# apps/estimates/line_kind_backfill.py
#
# HISTORICAL MIGRATION HELPER — invoked by data migration
# estimates/0046_backfill_freeform_kind, which runs between 0045 (adds
# `freeform_kind` to EstimateLineItem/ChangeOrderLineItem) and 0047 (removes
# `is_material` from both). The `EstimateLineItem`/`ChangeOrderLineItem` (and
# `EstimateLineItemSource`/`ChangeOrderLineItemSource`) args
# `backfill_estimate_line_item_kind`/`backfill_change_order_line_item_kind`
# take are HISTORICAL models (via apps.get_model), frozen at that exact point
# in schema history — always call those with historical models, never the
# live ones (by the time this task's migrations finish, the live models no
# longer have `is_material` at all). The source models are unaffected by
# this migration's own schema changes (EstimateLineItemSource has existed
# since 0012, ChangeOrderLineItemSource since 0041, both long before 0046),
# so their historical shape at this position is identical to live — passed
# as historical models anyway, for consistency with the two line-item
# models and so `apps.get_model` stays the single source of truth for what
# "at this migration" means.
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
# dependency on `is_material` still existing as a column. It stays FK-only
# (inventory_item/service_item/adjustment_service) on purpose — it doesn't
# know about EstimateLineItemSource/ChangeOrderLineItemSource rows at all.
# The source exemption (below) lives in the two wrappers instead, which
# already depend on the ORM/historical models and lose nothing by also
# querying the source tables; compute_freeform_kind keeps its
# DB-independent, forever-unit-testable shape.
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


def backfill_estimate_line_item_kind(EstimateLineItem, EstimateLineItemSource):
    """Iterate + per-row update() (no custom save() side effects exist for
    freeform_kind on this historical model). Returns the row count touched.

    A line already claimed by an EstimateLineItemSource row (the wizard's
    add_atoms_to_new_line_item path composes a line purely from existing
    Task/Material/Fee atoms, with none of the three descriptor FKs set) is
    not a bare freeform line either — same as a catalog/service/adjustment
    line — so it must map to NULL regardless of is_material.
    compute_freeform_kind doesn't know about source rows (see module
    header), so that exemption is applied here before falling through to
    it. One upfront query collects every claimed pk (not per-row) to avoid
    N+1 across the full-table iteration."""
    updated = 0
    sourced_pks = set(
        EstimateLineItemSource.objects.values_list('estimate_line_item_id', flat=True)
    )
    for li in EstimateLineItem.objects.iterator():
        if li.pk in sourced_pks:
            kind = None
        else:
            kind = compute_freeform_kind(
                inventory_item_id=li.inventory_item_id,
                service_item_id=li.service_item_id,
                adjustment_service_id=li.adjustment_service_id,
                is_material=li.is_material,
            )
        EstimateLineItem.objects.filter(pk=li.pk).update(freeform_kind=kind)
        updated += 1
    return updated


def backfill_change_order_line_item_kind(ChangeOrderLineItem, ChangeOrderLineItemSource):
    """CO twin of backfill_estimate_line_item_kind — no adjustment_service
    field on this model, so that predicate is always None. Same source-row
    exemption, against ChangeOrderLineItemSource instead."""
    updated = 0
    sourced_pks = set(
        ChangeOrderLineItemSource.objects.values_list('change_order_line_item_id', flat=True)
    )
    for li in ChangeOrderLineItem.objects.iterator():
        if li.pk in sourced_pks:
            kind = None
        else:
            kind = compute_freeform_kind(
                inventory_item_id=li.inventory_item_id,
                service_item_id=li.service_item_id,
                adjustment_service_id=None,
                is_material=li.is_material,
            )
        ChangeOrderLineItem.objects.filter(pk=li.pk).update(freeform_kind=kind)
        updated += 1
    return updated
