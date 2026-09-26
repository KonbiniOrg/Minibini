import { describe, it, expect } from 'vitest';
import { buildDeliverableRows } from '@/lib/changeOrderDiff.js';

// Semantics pinned from the ChangeOrderDetailPage derivations these were
// extracted from (2026-07-19). buildMergedRows/lineDiffTotals (the line-item
// diff) were retired 2026-08-09 when COEditView moved to the server-composed
// amended agreement — this file now only covers the deliverables diff.

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
