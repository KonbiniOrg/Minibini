// Item-level shortfall (spec: catalog-area-ui): what you'd have to buy so
// every commitment on this item is covered. Item-level on purpose — per-row
// arithmetic understates when several jobs earmark the same item.
export function stockShortfall(row) {
  const earmarked = Number(row.qty_earmarked_total ?? row.qty_earmarked);
  const s = earmarked - Number(row.qty_on_hand) - Number(row.qty_on_order);
  return s > 0 ? String(s) : '0';
}
