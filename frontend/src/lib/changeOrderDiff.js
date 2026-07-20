// Pure derivations for the change-order diff editors, extracted from the old
// ChangeOrderDetailPage route (2026-07-19) so they are unit-testable and the
// panel/section components stay thin.
//
// NOTE: the backend's compose_change_order_diff (apps/estimates) is a Python
// re-implementation of buildMergedRows — keep the two in lockstep until/unless
// the shop view reads the server composer (see LATER: estimate↔CO
// consolidation).

/**
 * Merged line-item diff: estimateLines ⊕ CO line items.
 *
 * Ordering is intentional and fixed — no reordering allowed:
 *   1. Estimate lines in line_number order; each replacement appears directly
 *      above its struck replacee at the same line_number position.
 *   2. Added (new) lines appended after all estimate lines, sorted by their
 *      own line_number.
 *
 * Each merged row has:
 *   kind:        'unchanged' | 'changed' | 'removed' | 'added' | 'changed-orig'
 *   lineNumber:  display line number
 *   description, qty, units, price, total: display values
 *   coItem:      the backing CO line item (for edit/delete/undo) — null for
 *                unchanged/changed-orig
 *   estLine:     the backing estimate line (null for 'added')
 */
export function buildMergedRows(estimateLines, coLineItems) {
  const coItems = (coLineItems || []).slice()
    .sort((a, b) => (a.line_number ?? 0) - (b.line_number ?? 0));
  const estLines = (estimateLines || []).slice()
    .sort((a, b) => a.line_number - b.line_number);

  // Build lookup: estimate line_item_id → CO item targeting it
  const replaceByCOTarget = new Map(); // target_line_item id → CO 'replace' item
  const removeByCOTarget = new Map();  // target_line_item id → CO 'remove' item
  const addItems = [];

  for (const ci of coItems) {
    if (ci.action === 'replace' && ci.target_line_item) {
      replaceByCOTarget.set(ci.target_line_item, ci);
    } else if (ci.action === 'remove' && ci.target_line_item) {
      removeByCOTarget.set(ci.target_line_item, ci);
    } else if (ci.action === 'add') {
      addItems.push(ci);
    }
  }

  const rows = [];

  for (const el of estLines) {
    const replaceCI = replaceByCOTarget.get(el.line_item_id);
    const removeCI = removeByCOTarget.get(el.line_item_id);

    if (replaceCI) {
      // changed: new value row (amber) + struck original row
      rows.push({
        kind: 'changed',
        lineNumber: el.line_number,
        description: replaceCI.description,
        qty: replaceCI.qty,
        units: replaceCI.units,
        price: replaceCI.price,
        total: Number(replaceCI.qty || 0) * Number(replaceCI.price || 0),
        coItem: replaceCI,
        estLine: el,
      });
      rows.push({
        kind: 'changed-orig',
        lineNumber: el.line_number,
        description: el.description,
        qty: el.qty,
        units: el.units,
        price: el.price,
        total: Number(el.qty || 0) * Number(el.price || 0),
        coItem: null,
        estLine: el,
      });
    } else if (removeCI) {
      // removed: struck alone, with Undo
      rows.push({
        kind: 'removed',
        lineNumber: el.line_number,
        description: el.description,
        qty: el.qty,
        units: el.units,
        price: el.price,
        total: Number(el.qty || 0) * Number(el.price || 0),
        coItem: removeCI,
        estLine: el,
      });
    } else {
      // unchanged
      rows.push({
        kind: 'unchanged',
        lineNumber: el.line_number,
        description: el.description,
        qty: el.qty,
        units: el.units,
        price: el.price,
        total: Number(el.qty || 0) * Number(el.price || 0),
        coItem: null,
        estLine: el,
      });
    }
  }

  // Appended added rows (sorted by their line_number)
  for (const ci of addItems) {
    rows.push({
      kind: 'added',
      lineNumber: ci.line_number,
      description: ci.description,
      qty: ci.qty,
      units: ci.units,
      price: ci.price,
      total: Number(ci.qty || 0) * Number(ci.price || 0),
      coItem: ci,
      estLine: null,
    });
  }

  return rows;
}

/** Footer totals for the line-item diff. */
export function lineDiffTotals(estimateLines, mergedRows) {
  const estimateTotal = (estimateLines || []).reduce(
    (s, el) => s + Number(el.qty || 0) * Number(el.price || 0), 0);
  const proposedTotal = (mergedRows || [])
    .filter((r) => r.kind === 'unchanged' || r.kind === 'changed' || r.kind === 'added')
    .reduce((s, r) => s + r.total, 0);
  return { estimateTotal, proposedTotal, diffTotal: proposedTotal - estimateTotal };
}

/**
 * Deliverables diff: live deliverables vs the CO's baseline snapshot.
 *
 * Each row has:
 *   kind:        'unchanged' | 'changed' | 'changed-orig' | 'removed' | 'added'
 *   live:        the live Deliverable object (null for removed/changed-orig)
 *   baseline:    the DeliverableSnapshot baseline row (null for added)
 *   anchored:    boolean — live deliverable has qty_picked_up > 0 or qty_prepped > 0
 *   description, qty, units: display values
 */
export function buildDeliverableRows(liveDeliverables, baseline) {
  const live = (liveDeliverables || []).slice()
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
  const base = (baseline || []).slice()
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));

  // Map: live deliverable id → live deliverable object
  const liveById = new Map(live.map((d) => [d.id, d]));
  // Set of live ids that are referenced by any baseline row
  const baselinedLiveIds = new Set(base.map((b) => b.source_deliverable).filter(Boolean));

  const rows = [];

  for (const snap of base) {
    const liveRow = snap.source_deliverable ? liveById.get(snap.source_deliverable) : null;
    if (!liveRow) {
      // source was deleted → removed
      rows.push({
        kind: 'removed',
        live: null,
        baseline: snap,
        anchored: false,
        description: snap.description,
        qty: snap.qty_ordered,
        units: snap.units,
      });
    } else {
      const anchored = Number(liveRow.qty_picked_up ?? 0) > 0
        || Number(liveRow.qty_prepped ?? 0) > 0;
      const changed =
        liveRow.description !== snap.description ||
        String(Number(liveRow.qty_ordered)) !== String(Number(snap.qty_ordered)) ||
        liveRow.units !== snap.units;
      if (changed) {
        // changed: new-value row (amber) + struck original row beneath
        rows.push({
          kind: 'changed',
          live: liveRow,
          baseline: snap,
          anchored,
          description: liveRow.description,
          qty: liveRow.qty_ordered,
          units: liveRow.units,
        });
        rows.push({
          kind: 'changed-orig',
          live: null,
          baseline: snap,
          anchored: false,
          description: snap.description,
          qty: snap.qty_ordered,
          units: snap.units,
        });
      } else {
        rows.push({
          kind: 'unchanged',
          live: liveRow,
          baseline: snap,
          anchored,
          description: liveRow.description,
          qty: liveRow.qty_ordered,
          units: liveRow.units,
        });
      }
    }
  }

  // Added: live deliverables not referenced by any baseline row
  for (const d of live) {
    if (!baselinedLiveIds.has(d.id)) {
      const anchored = Number(d.qty_picked_up ?? 0) > 0 || Number(d.qty_prepped ?? 0) > 0;
      rows.push({
        kind: 'added',
        live: d,
        baseline: null,
        anchored,
        description: d.description,
        qty: d.qty_ordered,
        units: d.units,
      });
    }
  }

  return rows;
}
