import { writable } from 'svelte/store';
import { api } from '../lib/api.js';

export const schedule = writable(null);

let refreshTimer = null;
let currentDays = null;

export async function loadSchedule(days) {
  if (days !== undefined) currentDays = days;
  try {
    const qs = currentDays != null ? `?days=${encodeURIComponent(currentDays)}` : '';
    const data = await api.get(`/api/schedule/${qs}`);
    schedule.set(data);
  } catch (err) {
    console.error('Failed to load schedule', err);
  }
}

export function startAutoRefresh(intervalMs = 5 * 60 * 1000) {
  stopAutoRefresh();
  refreshTimer = setInterval(loadSchedule, intervalMs);
}

export function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
}

export async function reorderTasksInLane(workerId, newOrderedTaskIds) {
  await api.post('/api/tasks/reorder/', { task_ids: newOrderedTaskIds });
  await loadSchedule();
}
