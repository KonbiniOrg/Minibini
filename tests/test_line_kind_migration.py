from django.test import TestCase

from apps.estimates.line_kind_backfill import compute_freeform_kind


class ComputeFreeformKindTest(TestCase):
    """Direct unit tests of the freeform_kind mapping rule used by the
    estimates/0046 data migration (backfilling pre-existing EstimateLineItem
    and ChangeOrderLineItem rows off the retired `is_material` boolean).

    Mapping rule: a line already resolved by an atom/service/adjustment
    descriptor is never a bare freeform line, so it maps to NULL regardless
    of is_material. A bare line's historical boolean maps onto the new
    three-value kind, preserving the historical bare-line default
    (unmarked -> Fee)."""

    def test_catalog_line_maps_to_null(self):
        # inventory_item present -> not a bare line, regardless of is_material.
        self.assertIsNone(compute_freeform_kind(
            inventory_item_id=1, service_item_id=None,
            adjustment_service_id=None, is_material=True))
        self.assertIsNone(compute_freeform_kind(
            inventory_item_id=1, service_item_id=None,
            adjustment_service_id=None, is_material=False))

    def test_service_line_maps_to_null(self):
        # service_item present -> not a bare line.
        self.assertIsNone(compute_freeform_kind(
            inventory_item_id=None, service_item_id=7,
            adjustment_service_id=None, is_material=True))
        self.assertIsNone(compute_freeform_kind(
            inventory_item_id=None, service_item_id=7,
            adjustment_service_id=None, is_material=False))

    def test_adjustment_line_maps_to_null(self):
        # adjustment_service present (estimate-side only) -> not a bare line.
        self.assertIsNone(compute_freeform_kind(
            inventory_item_id=None, service_item_id=None,
            adjustment_service_id=3, is_material=False))
        self.assertIsNone(compute_freeform_kind(
            inventory_item_id=None, service_item_id=None,
            adjustment_service_id=3, is_material=True))

    def test_bare_material_line_maps_to_material(self):
        self.assertEqual(compute_freeform_kind(
            inventory_item_id=None, service_item_id=None,
            adjustment_service_id=None, is_material=True), 'material')

    def test_bare_non_material_line_maps_to_fee(self):
        # Preserves the historical bare -> Fee default (is_material=False).
        self.assertEqual(compute_freeform_kind(
            inventory_item_id=None, service_item_id=None,
            adjustment_service_id=None, is_material=False), 'fee')
