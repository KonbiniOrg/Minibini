import { writable } from 'svelte/store';
import { api } from '../lib/api.js';

// Holds the user's currently-open Blep, or null if not clocked in.
// Shape matches GET /api/bleps/current/:
//   { id, start_time, task, job } | null
export const currentBlep = writable(null);

export async function refreshCurrentBlep() {
  try {
    const data = await api.get('/api/bleps/current/');
    currentBlep.set(data);
  } catch {
    // On error, leave the store unchanged. The band will continue to
    // show whatever it had; a later refresh will heal.
  }
}
