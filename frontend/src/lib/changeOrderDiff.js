// Pure derivations for the change-order deliverables diff editor, extracted
// from the old ChangeOrderDetailPage route (2026-07-19) so it's unit-testable
// and CODeliverablesSection stays thin.
//
// The line-item diff editor (buildMergedRows/lineDiffTotals) was retired
// 2026-08-09 — COEditView now reads the server-composed amended agreement
// (apps.estimates.agreement.compose_amended_agreement) directly instead of
// re-deriving a diff client-side.

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
