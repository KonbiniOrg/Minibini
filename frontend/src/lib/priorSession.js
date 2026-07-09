import { api } from './api.js';

// Shared resolve step for the `prior_session_qty` conflict: an own explicit
// gesture (starting another task, clocking out) found an open session on an
// ENTERED_QTY task and asked the SPA to settle it first.
//
// `qty` is the session count from ActualQtyModal (null = user skipped),
// `completesTask` is its "This completes the task" checkbox. After this
// resolves, the caller re-posts its original gesture with
// `prior_qty_handled: true`.
export function isPriorSessionConflict(resp) {
  return !!(resp && resp.conflict === 'prior_session_qty');
}

export async function settlePriorSession(conflict, qty, completesTask) {
  const priorId = conflict.prior_task.task_id;
  if (completesTask) {
    // One atomic add-and-complete; this also closes the old blep.
    await api.post(`/api/tasks/${priorId}/complete/`, { add_qty: qty ?? 0 });
  } else if (qty != null) {
    await api.post(`/api/tasks/${priorId}/actual-qty/add/`, { actual_qty: qty });
  }
  // qty null without completesTask: explicit skip — nothing to record.
}
