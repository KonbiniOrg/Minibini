// QBO import API wrappers. One shared snapshot server-side; per-area
// dismissal is sticky (a pull from one area never reopens another's panel).
import { api } from './api.js';

export const qboImportApi = {
  pull: (area) => api.post('/api/qbo/import/pull/', { area }),
  suggestions: (area) => api.get(`/api/qbo/import/suggestions/${area}/`),
  dismiss: (area) => api.post('/api/qbo/import/dismiss/', { area }),
  commitCategories: (rows) => api.post('/api/qbo/import/commit/categories/', { rows }),
  commitSchemes: (rows) => api.post('/api/qbo/import/commit/schemes/', { rows }),
  commitCatalog: (rows) => api.post('/api/qbo/import/commit/catalog/', { rows }),
  commitContacts: (payload) => api.post('/api/qbo/import/commit/contacts/', payload),
  commitTerms: (rows) => api.post('/api/qbo/import/commit/terms/', { rows }),
};

export function formatPullTime(iso) {
  if (!iso) return 'never';
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString();
}
