// Shared builder for the estimate/change-order version subnav (DocSubnav
// items), used by both the estimate panel and the change-order page so the two
// stay in lockstep. Estimate versions come first (oldest→newest), then the
// job's change orders. `currentKey` marks the active document as 'est-<id>' or
// 'co-<id>'.

// Estimates read "amended" (not "accepted") once an accepted CO has amended
// them — server-derived as EstimateSerializer.is_amended; the stored status
// stays "accepted".
export function estimateDisplayStatus(est) {
  return est?.is_amended ? 'amended' : est?.status;
}

// A change order reads "amended" when a later accepted CO exists on the same
// job (ordered by change_order_id).
export function changeOrderDisplayStatus(co, allCosForJob) {
  if (co?.status === 'accepted' && (allCosForJob || []).some(
    (other) => other.change_order_id > co.change_order_id && other.status === 'accepted',
  )) {
    return 'amended';
  }
  return co?.status;
}

export function buildEstimateDocItems({ estimates = [], changeOrders = [], jobId, currentKey = null }) {
  const sortedEstimates = [...estimates].sort((a, b) => a.version - b.version);
  const sortedChangeOrders = [...changeOrders].sort((a, b) => {
    if (a.change_order_number && b.change_order_number) {
      return a.change_order_number.localeCompare(b.change_order_number);
    }
    return (a.change_order_id ?? 0) - (b.change_order_id ?? 0);
  });
  return [
    ...sortedEstimates.map((e) => {
      const key = `est-${e.estimate_id}`;
      return {
        id: key,
        // Full document identity, like the CO/invoice pills: an estimate's
        // full form is `{estimate_number}-{version}` (the facts-table /
        // estimates-and-prices.md display convention) — not a bare `v2`.
        label: e.estimate_number
          ? `${e.estimate_number}-${e.version}` : `v${e.version}`,
        status: estimateDisplayStatus(e),
        href: `#/jobs/${jobId}/estimate/${e.estimate_id}`,
        current: key === currentKey,
      };
    }),
    ...sortedChangeOrders.map((co) => {
      const key = `co-${co.change_order_id}`;
      return {
        id: key,
        label: co.change_order_number || `CO #${co.change_order_id}`,
        status: changeOrderDisplayStatus(co, changeOrders),
        href: `#/jobs/${jobId}/change-order/${co.change_order_id}`,
        current: key === currentKey,
      };
    }),
  ];
}
