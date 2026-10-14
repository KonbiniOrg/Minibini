// The Unpaid column's three groups, in column order. Colors are the card
// tab colors (UnpaidCard), so a section header reads as the tab of the
// cards beneath it — the same convention as PipelineColumn.
export const UNPAID_SECTIONS = [
  { key: 'needs-invoice',   label: 'Needs Invoice',    color: '#64748b' },
  { key: 'invoice-prepped', label: 'Invoice Drafted',  color: '#f59e0b' },
  { key: 'invoice-sent',    label: 'Awaiting Payment', color: '#3b82f6' },
];
const SECTION_KEYS = new Set(UNPAID_SECTIONS.map((s) => s.key));
const SECTION_COLORS = Object.fromEntries(UNPAID_SECTIONS.map((s) => [s.key, s.color]));

// Mirror of Invoice.UNPAID_STATUSES: sent, still owed.
const SENT_STATUSES = new Set(['open', 'partly-paid', 'defaulted']);

// Which section a card belongs to. A work_complete job's sub_status is
// already one of the three (BoardService._work_complete_sub_status); any
// other card in the lane — a held job ('on-hold' wins server-side), a
// cancelled job with a receivable (null), an in_progress job with a deposit
// or progress invoice ('work-ready' etc.) — is bucketed from its invoices
// by the same rule: any sent-and-owed invoice → Awaiting Payment, else any
// draft → Invoice Drafted, else Needs Invoice. Paid invoices (a settled
// deposit) deliberately fall through to Needs Invoice: the final invoice
// hasn't been started. Cancelled/superseded invoices are ignored.
export function unpaidSectionKey(job) {
  if (SECTION_KEYS.has(job.sub_status)) return job.sub_status;
  const invoices = job.invoices || [];
  if (invoices.some((i) => SENT_STATUSES.has(i.status))) return 'invoice-sent';
  if (invoices.some((i) => i.status === 'draft')) return 'invoice-prepped';
  return 'needs-invoice';
}

export function unpaidSectionColor(key) {
  return SECTION_COLORS[key] || '#94a3b8';
}
