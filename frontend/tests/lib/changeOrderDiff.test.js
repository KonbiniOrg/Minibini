import { describe, it, expect } from 'vitest';
import {
  buildMergedRows,
  lineDiffTotals,
  buildDeliverableRows,
} from '@/lib/changeOrderDiff.js';

// Semantics pinned from the ChangeOrderDetailPage derivations these were
// extracted from (2026-07-19). The backend's compose_change_order_diff is a
// Python re-implementation of buildMergedRows — keep them in lockstep.

const EST_LINES = [
  { line_item_id: 1, line_number: 1, description: 'Frame', qty: 2, units: 'ea', price: '100.00' },
  { line_item_id: 2, line_number: 2, description: 'Panel', qty: 4, units: 'ea', price: '50.00' },
  { line_item_id: 3, line_number: 3, description: 'Finish', qty: 1, units: 'ea', price: '80.00' },
];

describe('buildMergedRows', () => {
  it('returns unchanged rows for estimate lines with no CO items', () => {
    const rows = buildMergedRows(EST_LINES, []);
    expect(rows.map((r) => r.kind)).toEqual(['unchanged', 'unchanged', 'unchanged']);
    expect(rows[0].total).toBe(200);
    expect(rows[0].estLine).toBe(EST_LINES[0]);
    expect(rows[0].coItem).toBeNull();
  });

  it('renders a replace as changed + struck original at the target position', () => {
    const replace = {
      line_item_id: 10, action: 'replace', target_line_item: 2,
      description: 'Panel XL', qty: 4, units: 'ea', price: '60.00', line_number: 1,
    };
    const rows = buildMergedRows(EST_LINES, [replace]);
    expect(rows.map((r) => r.kind)).toEqual(
      ['unchanged', 'changed', 'changed-orig', 'unchanged']);
    expect(rows[1].description).toBe('Panel XL');
    expect(rows[1].coItem).toBe(replace);
    expect(rows[2].description).toBe('Panel');
    expect(rows[2].coItem).toBeNull();
    // both rows keep the estimate line's display number
    expect(rows[1].lineNumber).toBe(2);
    expect(rows[2].lineNumber).toBe(2);
  });

  it('renders a remove as a struck row carrying the CO item for undo', () => {
    const remove = { line_item_id: 11, action: 'remove', target_line_item: 1, line_number: 1 };
    const rows = buildMergedRows(EST_LINES, [remove]);
    expect(rows[0].kind).toBe('removed');
    expect(rows[0].coItem).toBe(remove);
    expect(rows[0].description).toBe('Frame');
  });

  it('appends added lines after all estimate lines, sorted by their own line_number', () => {
    const adds = [
      { line_item_id: 13, action: 'add', description: 'Rush', qty: 1, units: 'ea', price: '25.00', line_number: 2 },
      { line_item_id: 12, action: 'add', description: 'Crating', qty: 1, units: 'ea', price: '40.00', line_number: 1 },
    ];
    const rows = buildMergedRows(EST_LINES, adds);
    expect(rows.slice(3).map((r) => r.description)).toEqual(['Crating', 'Rush']);
    expect(rows[3].kind).toBe('added');
    expect(rows[3].estLine).toBeNull();
  });

  // task-owned-money Phase 3 Task 6: freeform_kind carries through onto
  // every row (matching the estimate tables' kind badge — LineItemTable.svelte).
  it('carries freeform_kind from the estimate line onto an unchanged row', () => {
    const lines = [{ ...EST_LINES[0], freeform_kind: 'work' }];
    const rows = buildMergedRows(lines, []);
    expect(rows[0].freeform_kind).toBe('work');
  });

  it('carries freeform_kind from the CO item onto changed/added rows, and from the estimate line onto changed-orig', () => {
    const replace = {
      line_item_id: 10, action: 'replace', target_line_item: 2,
      description: 'Panel XL', qty: 4, units: 'ea', price: '60.00', line_number: 1,
      freeform_kind: 'material',
    };
    const lines = EST_LINES.map((l) => (l.line_item_id === 2 ? { ...l, freeform_kind: 'fee' } : l));
    const rows = buildMergedRows(lines, [replace]);
    expect(rows[1].kind).toBe('changed');
    expect(rows[1].freeform_kind).toBe('material');
    expect(rows[2].kind).toBe('changed-orig');
    expect(rows[2].freeform_kind).toBe('fee');
  });

  it('carries freeform_kind onto a removed row from the estimate line', () => {
    const remove = { line_item_id: 11, action: 'remove', target_line_item: 1, line_number: 1 };
    const lines = EST_LINES.map((l) => (l.line_item_id === 1 ? { ...l, freeform_kind: 'fee' } : l));
    const rows = buildMergedRows(lines, [remove]);
    expect(rows[0].freeform_kind).toBe('fee');
  });

  it('defaults freeform_kind to null when the line carries none (catalog/service lines)', () => {
    const rows = buildMergedRows(EST_LINES, []);
    expect(rows[0].freeform_kind).toBeNull();
  });
});

describe('lineDiffTotals', () => {
  it('computes estimate, proposed, and diff totals from the merged rows', () => {
    const replace = {
      line_item_id: 10, action: 'replace', target_line_item: 2,
      description: 'Panel XL', qty: 4, units: 'ea', price: '60.00', line_number: 1,
    };
    const add = { line_item_id: 12, action: 'add', description: 'Crating', qty: 1, units: 'ea', price: '40.00', line_number: 1 };
    const rows = buildMergedRows(EST_LINES, [replace, add]);
    const t = lineDiffTotals(EST_LINES, rows);
    expect(t.estimateTotal).toBe(480);        // 200 + 200 + 80
    expect(t.proposedTotal).toBe(560);        // 200 + 240 + 80 + 40
    expect(t.diffTotal).toBe(80);
  });
});

describe('buildDeliverableRows', () => {
  const BASE = [
    { id: 101, source_deliverable: 21, description: 'Cabinet', qty_ordered: '2', units: 'ea', sort_order: 1 },
    { id: 102, source_deliverable: 22, description: 'Shelf', qty_ordered: '4', units: 'ea', sort_order: 2 },
  ];

  it('classifies unchanged / changed(+orig) / removed / added, with anchoring', () => {
    const live = [
      // unchanged, anchored (picked up)
      { id: 21, description: 'Cabinet', qty_ordered: '2', units: 'ea', qty_picked_up: '1', qty_prepped: '0', sort_order: 1 },
      // changed (qty 4 → 6)
      { id: 22, description: 'Shelf', qty_ordered: '6', units: 'ea', qty_picked_up: '0', qty_prepped: '0', sort_order: 2 },
      // added (not in baseline)
      { id: 23, description: 'Drawer', qty_ordered: '3', units: 'ea', qty_picked_up: '0', qty_prepped: '0', sort_order: 3 },
    ];
    const rows = buildDeliverableRows(live, BASE);
    expect(rows.map((r) => r.kind)).toEqual(
      ['unchanged', 'changed', 'changed-orig', 'added']);
    expect(rows[0].anchored).toBe(true);
    expect(rows[1].qty).toBe('6');
    expect(rows[2].qty).toBe('4');   // struck original shows baseline values
    expect(rows[3].live.id).toBe(23);
  });

  it('reports a baseline row whose live source is gone as removed', () => {
    const rows = buildDeliverableRows([], BASE);
    expect(rows.map((r) => r.kind)).toEqual(['removed', 'removed']);
    expect(rows[0].baseline).toBe(BASE[0]);
    expect(rows[0].live).toBeNull();
  });

  it('treats numerically-equal qty strings as unchanged', () => {
    const live = [
      { id: 21, description: 'Cabinet', qty_ordered: '2.00', units: 'ea', qty_picked_up: '0', qty_prepped: '0', sort_order: 1 },
    ];
    const rows = buildDeliverableRows(live, [BASE[0]]);
    expect(rows[0].kind).toBe('unchanged');
  });
});
