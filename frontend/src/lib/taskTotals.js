// Row-math + formatting shared by the task-tree row fragments (TaskRow,
// MaterialRow) and TaskTree's grand-total footer — one source of truth so
// a row's displayed total and the table's sum can't diverge.

import { durationToHours } from './format.js';

export function fmtMoney(n) {
  return n ? `$${Number(n).toFixed(2)}` : '-';
}

export function fmtWorkerTime(value) {
  // Server returns DurationField as either "HH:MM:SS" / "DD HH:MM:SS"
  // or ISO 8601 ("PT1H30M"). Render as "Hh Mm" or "Mm" for compactness.
  const hours = durationToHours(value);
  if (hours === null) return '-';
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (h && m) return `${h}h ${m}m`;
  if (h) return `${h}h`;
  if (m) return `${m}m`;
  return '-';
}

export function taskTotalInfo(task) {
  // Prefer the live computed_charge (driven by actuals: bleps for elapsed_time,
  // actual_qty for entered_qty). When actuals are absent
  // the computed charge is 0 — fall back to est_qty * effective_rate as the
  // estimated total, marked so the UI can render it in grey.
  const actual = Number(task.computed_charge) || 0;
  if (actual > 0) return { value: actual, isEstimate: false };
  const est = (Number(task.est_qty) || 0) * (Number(task.effective_rate) || 0);
  if (est > 0) return { value: est, isEstimate: true };
  return { value: 0, isEstimate: false };
}

export function taskTotal(task) {
  return taskTotalInfo(task).value;
}

export function taskActual(task) {
  // Task-owned money (Phase 1): the task carries its own qty_source now
  // (was the RateScheme's scheme_algorithm echo, retired). elapsed_time →
  // hours from bleps. entered_qty → worker-entered qty. Unset/other → no
  // actual to display.
  if (task.qty_source === 'elapsed_time') {
    const h = Number(task.actual_hours) || 0;
    return h > 0 ? h : null;
  }
  if (task.qty_source === 'entered_qty') {
    return task.actual_qty != null && task.actual_qty !== '' ? task.actual_qty : null;
  }
  return null;
}

export function materialTotal(mat) {
  const qty = Number(mat.quantity) || 0;
  const price = Number(mat.sell_price) || 0;
  return qty * price;
}
