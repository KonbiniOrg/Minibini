import { writable } from 'svelte/store';
import { api } from '../lib/api.js';

export const schedule = writable(null);

// task_id currently being dragged, or null. Set by TaskBar on dragstart,
// cleared on dragend. Read by WorkerLane so the drop-position indicator
// can exclude the dragged task from the queue (otherwise the indicator
// would snap to gaps adjacent to the bar's original spot).
export const draggingTaskId = writable(null);

let refreshTimer = null;
let currentDays = null;
let currentOffset = 0;

export async function loadSchedule(days) {
  if (days !== undefined) currentDays = days;
  try {
    const params = new URLSearchParams();
    if (currentDays != null) params.set('days', currentDays);
    if (currentOffset) params.set('offset', currentOffset);
    const qs = params.toString();
    const data = await api.get(`/api/schedule/${qs ? '?' + qs : ''}`);
    schedule.set(data);
  } catch (err) {
    console.error('Failed to load schedule', err);
  }
}

// Scroll the window by working days. `delta` shifts relative to the
// current offset; passing 0 with absolute=true resets to today.
export function scrollDays(delta) {
  currentOffset += delta;
  return loadSchedule();
}

export function resetToToday() {
  currentOffset = 0;
  return loadSchedule();
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
