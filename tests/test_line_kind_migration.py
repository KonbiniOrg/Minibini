from django.test import TestCase

from apps.estimates.line_kind_backfill import (
    compute_freeform_kind,
    backfill_estimate_line_item_kind,
    backfill_change_order_line_item_kind,
)


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


class _FakeRow:
    """Stand-in for a historical EstimateLineItem/ChangeOrderLineItem row —
    just the plain attributes the wrapper functions read/write."""
    def __init__(self, pk, inventory_item_id=None, service_item_id=None,
                 adjustment_service_id=None, is_material=False,
                 freeform_kind=None):
        self.pk = pk
        self.inventory_item_id = inventory_item_id
        self.service_item_id = service_item_id
        self.adjustment_service_id = adjustment_service_id
        self.is_material = is_material
        self.freeform_kind = freeform_kind


class _FakeSourceRow:
    """Stand-in for a historical EstimateLineItemSource/
    ChangeOrderLineItemSource row — just the FK-id attribute the wrapper
    reads via values_list."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeFilterResult:
    def __init__(self, rows):
        self._rows = rows

    def update(self, **kwargs):
        for row in self._rows:
            for k, v in kwargs.items():
                setattr(row, k, v)
        return len(self._rows)


class _FakeManager:
    def __init__(self, rows):
        self._rows = rows

    def iterator(self):
        # Snapshot, matching QuerySet.iterator()'s "don't mutate while
        # iterating" contract.
        return iter(list(self._rows))

    def filter(self, pk):
        return _FakeFilterResult([r for r in self._rows if r.pk == pk])

    def values_list(self, field, flat=True):
        return [getattr(r, field) for r in self._rows]


class _FakeModel:
    """Duck-typed stand-in for a Django model class exposing only
    `.objects.iterator()/.filter(pk=...).update(...)/.values_list(...)` —
    the exact surface backfill_estimate_line_item_kind/
    backfill_change_order_line_item_kind call. Used instead of real
    historical models (via a migration-state MigrationExecutor rollback)
    because that would require running live schema DDL (AddField/
    RemoveField) against the shared MySQL test database mid-suite — DDL is
    not transactional under MySQL, so a mid-test rollback/forward of the
    `estimates` app's migrations has no clean way to guarantee the schema
    is restored before the next test runs, risking corrupting every test
    that runs afterward. This stand-in exercises the real, unmodified
    wrapper functions' actual logic (including the sourced-row exemption)
    with zero DB/schema risk."""
    def __init__(self, rows):
        self.objects = _FakeManager(rows)


class BackfillWrapperSourceExemptionTest(TestCase):
    """Tests for the source-row exemption added to the two iterate/update
    wrappers (backfill_estimate_line_item_kind/
    backfill_change_order_line_item_kind) on top of compute_freeform_kind's
    FK-only mapping. A line claimed by an EstimateLineItemSource/
    ChangeOrderLineItemSource row (the wizard's add_atoms_to_new_line_item
    path: no inventory_item/service_item/adjustment_service, atoms
    attached via the polymorphic source join instead) is not a bare
    freeform line — compute_freeform_kind alone would wrongly map it to
    'fee' (is_material defaults to False for such rows), violating the
    "freeform_kind non-null IFF bare freeform" invariant validate_data now
    enforces. The wrapper must special-case it to NULL instead."""

    def test_estimate_sourced_bare_line_backfills_to_null(self):
        row = _FakeRow(pk=1, is_material=False)  # bare, no FKs
        EstimateLineItem = _FakeModel([row])
        EstimateLineItemSource = _FakeModel([
            _FakeSourceRow(estimate_line_item_id=1),
        ])
        updated = backfill_estimate_line_item_kind(EstimateLineItem, EstimateLineItemSource)
        self.assertEqual(updated, 1)
        self.assertIsNone(row.freeform_kind)

    def test_estimate_unsourced_bare_line_still_uses_is_material(self):
        # Control: without a source row, the old is_material mapping holds.
        row = _FakeRow(pk=2, is_material=True)
        EstimateLineItem = _FakeModel([row])
        EstimateLineItemSource = _FakeModel([])
        backfill_estimate_line_item_kind(EstimateLineItem, EstimateLineItemSource)
        self.assertEqual(row.freeform_kind, 'material')

    def test_estimate_sourced_catalog_line_still_null(self):
        # A source row on a non-bare line is a no-op — already NULL either way.
        row = _FakeRow(pk=3, inventory_item_id=9, is_material=True)
        EstimateLineItem = _FakeModel([row])
        EstimateLineItemSource = _FakeModel([
            _FakeSourceRow(estimate_line_item_id=3),
        ])
        backfill_estimate_line_item_kind(EstimateLineItem, EstimateLineItemSource)
        self.assertIsNone(row.freeform_kind)

    def test_co_sourced_bare_line_backfills_to_null(self):
        row = _FakeRow(pk=1, is_material=False)
        ChangeOrderLineItem = _FakeModel([row])
        ChangeOrderLineItemSource = _FakeModel([
            _FakeSourceRow(change_order_line_item_id=1),
        ])
        updated = backfill_change_order_line_item_kind(
            ChangeOrderLineItem, ChangeOrderLineItemSource)
        self.assertEqual(updated, 1)
        self.assertIsNone(row.freeform_kind)

    def test_co_unsourced_bare_line_still_uses_is_material(self):
        row = _FakeRow(pk=2, is_material=False)
        ChangeOrderLineItem = _FakeModel([row])
        ChangeOrderLineItemSource = _FakeModel([])
        backfill_change_order_line_item_kind(
            ChangeOrderLineItem, ChangeOrderLineItemSource)
        self.assertEqual(row.freeform_kind, 'fee')
