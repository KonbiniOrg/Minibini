// Seed finder for the contact/business detail specs: a business with at
// least two contacts whose jobs include both an open and a closed one, so
// the Contacts table, Set as default, and "show N completed" all have
// something to exercise. Found by SHAPE (docs/designs/e2e-testing.md §3);
// callers skip with a named seed gap when it returns null.
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

export const CLOSED_JOB = new Set(['completed', 'rejected', 'cancelled', 'archived']);

export async function findCustomerBusiness() {
  const api = await apiAs(personas.finjobs);
  try {
    const byBusiness = new Map();
    for (const page of [1, 2, 3]) {
      let data;
      try { data = await api.get(`/api/contacts/?page_size=100&page=${page}`); } catch { break; }
      for (const c of data.results || []) {
        const b = c.business?.business_id;
        if (!b) continue;
        byBusiness.set(b, (byBusiness.get(b) || 0) + 1);
      }
      if (!data.next) break;
    }
    const candidates = [...byBusiness.entries()].filter(([, n]) => n >= 2).map(([id]) => id);
    for (const id of candidates) {
      const business = await api.get(`/api/businesses/${id}/`);
      const jobs = business.jobs || [];
      const closed = jobs.filter((j) => CLOSED_JOB.has(j.status));
      if (closed.length >= 1 && closed.length < jobs.length && (business.contacts || []).length >= 2) {
        return business;
      }
    }
    return null;
  } finally {
    await api.dispose();
  }
}
