// The Unpaid column's groups, in column order, keyed by the server-computed
// `section` on each card (BoardService.unpaid_section). Colors are the card
// tab colors (UnpaidCard), so a section header reads as the tab of the cards
// beneath it — the same convention as PipelineColumn. The browser only maps
// keys to labels and colors; the rule lives in the backend.
export const UNPAID_SECTIONS = [
  { key: 'needs-invoice',   label: 'Needs Invoice',    color: '#64748b' },
  { key: 'invoice-prepped', label: 'Invoice Drafted',  color: '#f59e0b' },
  { key: 'invoice-sent',    label: 'Awaiting Payment', color: '#3b82f6' },
  { key: 'needs-pickup',    label: 'Needs Pickup',     color: '#7c3aed' },
];
const SECTION_COLORS = Object.fromEntries(UNPAID_SECTIONS.map((s) => [s.key, s.color]));

export function unpaidSectionColor(key) {
  return SECTION_COLORS[key] || '#94a3b8';
}
