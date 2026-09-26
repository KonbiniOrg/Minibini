// Pure derivations for the agreement-backing "reference" small-text shown
// under an invoice line's description (InvoiceEditView) — extracted out of
// the component (same reasoning as changeOrderDiff.js) so coShortLabel and
// estReferenceText are unit-testable without mounting the whole component.

import { fmtMoney } from './taskTotals.js';

// "EST-2026-0004-CO1" -> "CO-1" — derives the short label from the trailing
// "-CO<n>" suffix minted by ChangeOrder.save() (apps/estimates/models.py).
// Falls back to the full number when the suffix isn't there (a change_order
// number this code doesn't recognize the shape of), and to '' for a
// null/undefined input so callers never have to guard first.
export function coShortLabel(changeOrderNumber) {
  if (!changeOrderNumber) return '';
  const match = /-CO(\d+)$/.exec(changeOrderNumber);
  return match ? `CO-${match[1]}` : changeOrderNumber;
}

function lineAmount(li) {
  return Number(li.qty || 0) * Number(li.price || 0);
}

// The invoice line's agreement-backing reference, rendered as small text
// under its description:
//
//   - CO-origin (agreement_ref.kind === 'change_order'): pure provenance —
//     "{coShortLabel} line {co_line_number}" (spec §9.3 "CO-N line M"),
//     which document + line this line was seeded from. No value comparison:
//     unlike an estimate-backed line, a CO-origin line's whole point is
//     that it's freshly amended, so "what it used to say" isn't the
//     interesting fact here.
//   - estimate-origin: unchanged — "est was $X · +$Δ", comparing the
//     estimate's stored amount against what the line is actually backed by
//     right now (actuals when claimed work exists, else the line's own
//     current amount). The "· +$Δ" clause is suppressed entirely when Δ is
//     exactly zero: fmtMoney(0) renders as '-' (its "no amount" sentinel,
//     used everywhere else in this app), so showing the clause at Δ=0 would
//     render the nonsense "· +-" instead of just quietly having nothing to
//     report.
export function estReferenceText(li) {
  const ref = li.agreement_ref;
  if (!ref) return '';
  if (ref.kind === 'change_order') {
    return `${coShortLabel(ref.co_number)} line ${ref.co_line_number}`;
  }
  const estAmount = Number(ref.est_amount);
  const current = li.actuals_total != null ? Number(li.actuals_total) : lineAmount(li);
  const delta = current - estAmount;
  let text = `est was ${fmtMoney(estAmount)}`;
  if (delta !== 0) {
    const sign = delta > 0 ? '+' : '';
    text += ` · ${sign}${fmtMoney(delta)}`;
  }
  return text;
}
