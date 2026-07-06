// One derived display status per material row (spec §UI surface). Pure —
// computed from serializer fields; no new backend state machine. Precedence:
// released/consumed (terminal) win; then provisional (no inventory item →
// needs-pricing); then covered stock (on-hand) BEFORE the procurement states,
// so a material the shelf already covers always reads "On Hand" regardless of
// how it was going to be sourced; then customer-supplied shortfall, then a
// linked PO, else plain "needed".
const short = (m) => Number(m.qty_on_hand) < Number(m.quantity);

export function materialStatus(m) {
  if (m.consumption_state === 'released') return { key: 'released', label: 'Released' };
  if (m.consumption_state === 'consumed') return { key: 'consumed', label: 'Used' };
  if (!m.inventory_item) return { key: 'needs-pricing', label: 'Needs pricing' };
  if (!short(m)) return { key: 'on-hand', label: 'On Hand' };
  if (m.cost_source === 'customer_supplied')
    return { key: 'awaiting-customer', label: 'Awaiting customer' };
  // Ordered only while the linked PO line still has an outstanding balance —
  // a fully received (or cancelled-remainder) PO is history, not this row's
  // incoming supply, so a short row degrades to Needed instead of pointing
  // at a concluded PO.
  if (m.po_line_item_id && Number(m.qty_on_order) > 0)
    return { key: 'ordered', label: `Ordered — ${m.po_number || 'PO'}` };
  return { key: 'needed', label: 'Needed' };
}

// Cost is a placeholder pulled from estimate markup, not a confirmed figure —
// flag it (a small ⚠) so it can't be mistaken for a real vendor/receipt cost.
// Coexists with any pending-phase status.
export function costUnconfirmed(m) {
  return m.cost_source === 'estimated';
}
