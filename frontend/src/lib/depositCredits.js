// Unapplied deposit credits — client-side re-derivation, in EXACT parity
// with the backend's "Deposit credits" pool group
// (InvoiceWizardService.get_source_pool, apps/invoicing/services.py):
//
//   - CANDIDATE: a deposit line (is_deposit === true, from
//     InvoiceLineItemSerializer.get_is_deposit / accounting_category.is_deposit)
//     on a PAID invoice — you can't deduct money you don't hold.
//   - APPLIED (excluded): any line, on any invoice belonging to the SAME
//     job, whose status is NOT 'cancelled', carries a source with
//     source_type 'deposit' and source_pk === the candidate's
//     line_item_id. A claim from a cancelled invoice doesn't count — this
//     mirrors the backend's `claimed_sources` query, which excludes
//     Invoice.STATUS_CANCELLED.
//
// Both callers (InvoicePanel's draft-panel notice, InvoiceSendPage's
// send-time confirm) already have the job-scoped `invoices` array loaded
// via GET /api/invoices/?job=<id> with no ?summary= param — every entry is
// the full InvoiceSerializer (nested line_items with is_deposit, nested
// sources with source_type/source_pk), so no extra fetch is needed here.
// One function, used by both, so the two surfaces cannot drift apart.
export function unappliedDepositCredits(invoices) {
  const list = invoices || [];

  const candidates = [];
  for (const inv of list) {
    if (inv.status !== 'paid') continue;
    for (const li of inv.line_items || []) {
      if (li.is_deposit) candidates.push({ lineItem: li, invoice: inv });
    }
  }
  if (candidates.length === 0) return [];

  const appliedIds = new Set();
  for (const inv of list) {
    if (inv.status === 'cancelled') continue;
    for (const li of inv.line_items || []) {
      for (const src of li.sources || []) {
        if (src.source_type === 'deposit') appliedIds.add(src.source_pk);
      }
    }
  }

  return candidates.filter((c) => !appliedIds.has(c.lineItem.line_item_id));
}
