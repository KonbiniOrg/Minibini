// Material-derived helpers shared by route pages.

// Default order quantity for the "order this material" flow: the outstanding
// shortfall (needed − stock on hand, mirroring consume's raw-QOH check — the
// number that actually unblocks work), falling back to the full planned
// quantity when nothing is short (the user still asked to order).
export function orderPrefillQty(material) {
  const needed = Number(material.quantity) || 0;
  const onHand = Number(material.qty_on_hand) || 0;
  const shortfall = Math.max(needed - onHand, 0);
  return shortfall > 0 ? String(shortfall) : material.quantity;
}
