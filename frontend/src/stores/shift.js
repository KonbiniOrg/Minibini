import { writable } from 'svelte/store';
import { api } from '../lib/api.js';

export const currentShift = writable(null);   // open shift object or null
export const shiftActivityVersion = writable(0);

export async function refreshCurrentShift() {
  try {
    const data = await api.get('/api/shifts/active/');
    currentShift.set(data.shift);
  } catch {
    currentShift.set(null);
  }
}

export async function notifyShiftChanged() {
  await refreshCurrentShift();
  shiftActivityVersion.update((n) => n + 1);
}
