// Setup gate state — mirror of GET /api/setup/status/ (the single source
// of truth for greyed sidebar areas, floating callouts, and the Home Help
// setup checklist). Gates are live predicates server-side; refresh() after
// anything that could flip one (imports, settings saves).
import { writable, get } from 'svelte/store';
import { api } from '../lib/api.js';

export const setupStatus = writable({ areas: null, last_pull_at: null });

export async function refreshSetupStatus() {
  try {
    const data = await api.get('/api/setup/status/');
    setupStatus.set(data);
  } catch (_) {
    // Leave previous state; gates are UX, the API enforces the real rules.
  }
}

// True only when we KNOW the area is unavailable (unloaded store = allow).
export function areaUnavailable(area) {
  const s = get(setupStatus);
  return Boolean(s.areas && s.areas[area] && !s.areas[area].available);
}
