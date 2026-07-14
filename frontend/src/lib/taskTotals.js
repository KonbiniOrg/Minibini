// Row-math + formatting shared by the task-tree row fragments (TaskRow,
// MaterialRow) and TaskTree's grand-total footer — one source of truth so
// a row's displayed total and the table's sum can't diverge.

export function fmtMoney(n) {
  return n ? `$${Number(n).toFixed(2)}` : '-';
}

export function fmtWorkerTime(value) {
  // Server returns DurationField as either "HH:MM:SS" / "DD HH:MM:SS"
  // or ISO 8601 ("PT1H30M"). Render as "Hh Mm" or "Mm" for compactness.
  if (!value) return '-';
  const str = String(value);
  const iso = str.match(/^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/);
  if (iso) {
    const days = parseInt(iso[1] || '0', 10);
    const h = parseInt(iso[2] || '0', 10) + days * 24;
    const m = parseInt(iso[3] || '0', 10);
    if (h && m) return `${h}h ${m}m`;
    if (h) return `${h}h`;
    if (m) return `${m}m`;
    return '-';
  }
  const hms = str.match(/^(?:(\d+) )?(\d+):(\d+):(\d+)/);
  if (hms) {
    const days = parseInt(hms[1] || '0', 10);
    const h = parseInt(hms[2], 10) + days * 24;
    const m = parseInt(hms[3], 10);
    if (h && m) return `${h}h ${m}m`;
    if (h) return `${h}h`;
    if (m) return `${m}m`;
    return '-';
  }
  return str;
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
  // ELAPSED_TIME → hours from bleps. ENTERED_QTY → worker-entered qty.
  // Unset/other → no actual to display.
  if (task.scheme_algorithm === 'elapsed_time') {
    const h = Number(task.actual_hours) || 0;
    return h > 0 ? h : null;
  }
  if (task.scheme_algorithm === 'entered_qty') {
    return task.actual_qty != null && task.actual_qty !== '' ? task.actual_qty : null;
  }
  return null;
}

export function materialTotal(mat) {
  const qty = Number(mat.quantity) || 0;
  const price = Number(mat.sell_price) || 0;
  return qty * price;
}

export function feeTotal(fee) {
  return (Number(fee.quantity) || 0) * (Number(fee.unit_rate) || 0);
}
