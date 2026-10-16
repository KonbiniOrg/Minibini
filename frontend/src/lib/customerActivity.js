// Pure rules for the contact/business detail pages (contacts UI redesign,
// 2026-10-10 — docs/designs/contacts-and-businesses.md → Frontend → Detail
// pages). Components render what these return and never re-decide:
//   - which rows a section hides behind "show N completed / paid / closed"
//   - the toggle's label, the human status label
//   - section ordering (populated first, canonical order within)
//   - the Delete-offered rule the banner follows (Deactivate/Reactivate always shown)
//   - the banner's facts line and the contact page's sibling list

const CLOSED_JOB = new Set(['completed', 'rejected', 'cancelled']);
const CLOSED_INVOICE = new Set(['paid', 'cancelled', 'superseded']);
const CLOSED_PO = new Set(['received_in_full', 'cancelled']);

export const isClosedJob = (row) => CLOSED_JOB.has(row.status);
export const isClosedInvoice = (row) => CLOSED_INVOICE.has(row.status);
export const isClosedPO = (row) => CLOSED_PO.has(row.status);

export function splitRows(rows, isClosed) {
  const open = [];
  const closed = [];
  for (const row of rows || []) (isClosed(row) ? closed : open).push(row);
  return { open, closed };
}

// "show 3 completed" / "hide 3 completed"; null when there is nothing to show.
export function showLabel(count, word, expanded) {
  if (!count) return null;
  return `${expanded ? 'hide' : 'show'} ${count} ${word}`;
}

// Human label for any status slug: snake_case or kebab-case → Sentence case.
export function statusLabel(status) {
  if (!status) return '';
  const words = String(status).replace(/[-_]+/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// Sections carry { key, total }. Populated sections keep their given order;
// empty ones sink to the end (they render as a collapsed one-liner).
export function orderSections(sections) {
  const populated = sections.filter((s) => s.total > 0);
  const empty = sections.filter((s) => !(s.total > 0));
  return [...populated, ...empty];
}

// Mirrors ContactService's delete guards so the banner can offer Delete only
// when the server would accept it; otherwise only Deactivate is offered.
export function canDeleteBusiness({ jobs, poCount, contacts }) {
  return (jobs?.length ?? 0) === 0 && (poCount ?? 0) === 0 && (contacts?.length ?? 0) <= 1;
}

export function canDeleteContact({ jobs, hasBusiness, siblingCount }) {
  if ((jobs?.length ?? 0) > 0) return false;
  if (hasBusiness && (siblingCount ?? 0) === 0) return false;
  return true;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// ISO date "YYYY-MM-DD" → parts without timezone shifting (it's already a
// local calendar date from the server).
function parts(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
  return m ? { y: Number(m[1]), mo: Number(m[2]) - 1, d: Number(m[3]) } : null;
}
export function monthYear(iso) {
  const p = parts(iso);
  return p ? `${MONTHS[p.mo]} ${p.y}` : '';
}
export function shortDate(iso) {
  const p = parts(iso);
  return p ? `${MONTHS[p.mo]} ${p.d}, ${p.y}` : '';
}

// The banner's facts line. `kind` picks "Customer since" / "Contact since";
// `terms` (business pages) is appended when present. Null facts are omitted.
export function customerFacts(financials, { kind = 'business', terms = null } = {}) {
  if (!financials) return '';
  const since = kind === 'contact' ? 'Contact since' : 'Customer since';
  return [
    financials.first_job_date ? `${since} ${monthYear(financials.first_job_date)}` : null,
    financials.last_job_start ? `Last job started ${shortDate(financials.last_job_start)}` : null,
    terms || null,
  ].filter(Boolean).join(' · ');
}

// "Also here" on the contact page: the business's other contacts with their
// job counts, both read off the business detail payload (contacts[] and
// jobs[].contact) so no extra endpoint is needed.
export function siblingJobCounts(business, selfId) {
  if (!business?.contacts) return [];
  const counts = new Map();
  for (const job of business.jobs || []) counts.set(job.contact, (counts.get(job.contact) || 0) + 1);
  return business.contacts
    .filter((c) => c.contact_id !== selfId)
    .map((c) => ({ contact_id: c.contact_id, name: c.name, jobCount: counts.get(c.contact_id) || 0 }));
}
