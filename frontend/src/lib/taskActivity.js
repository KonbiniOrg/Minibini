// The canonical task-state label for overview/list surfaces. "Working" (an open
// blep exists right now) overrides the lifecycle status; otherwise the status
// maps to a friendly label. Single source of truth so the board, schedule, home,
// task tree, and task detail all read identically.
//
// Note: pending and in_progress remain distinct in the data model (the
// pending→in_progress transition is what consumes materials) — they just both
// read as plain words here: "Unstarted" vs "Ongoing". The only real-time signal
// that stands out is "Working".
//
// Returns { key, label, color, pulse }, or null for an unknown status.
export function taskActivity(task) {
  if (!task) return null;
  if (task.has_active_blep) {
    return { key: 'working', label: 'Working', color: '#16a34a', pulse: true };
  }
  switch (task.status) {
    case 'blocked':     return { key: 'blocked',   label: 'Blocked',   color: '#dc2626', pulse: false };
    case 'pending':     return { key: 'unstarted', label: 'Unstarted', color: '#94a3b8', pulse: false };
    case 'in_progress': return { key: 'ongoing',   label: 'Ongoing',   color: '#2563eb', pulse: false };
    case 'complete':    return { key: 'complete',  label: 'Complete',  color: '#047857', pulse: false };
    case 'cancelled':   return { key: 'cancelled', label: 'Cancelled', color: '#9ca3af', pulse: false };
    default:            return null;
  }
}
