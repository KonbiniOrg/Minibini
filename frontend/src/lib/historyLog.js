// Milestone-log derivation for the Job History page's Summary tab: filters
// the serialized history feed down to creations + status transitions and
// groups them into day buckets. Pure functions — no API calls, no Svelte.
// Spec: docs/plans/2026-07-13-job-history-summary-log.md

const DOW = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December'];

// Full verb table keyed `${object_type}:${status}` — every status mapped
// explicitly (even identity mappings) so either side can change without
// surprising the other. Unknown statuses fall back to the humanized raw
// value; a missing mapping must never drop a row.
const VERBS = {
  'job:draft': 'reverted to draft',
  'job:submitted': 'submitted',
  'job:approved': 'approved',
  'job:in_progress': 'started',
  'job:work_complete': 'work completed',
  'job:rejected': 'rejected',
  'job:completed': 'completed',
  'job:cancelled': 'cancelled',
  'task:pending': 'reopened',
  'task:in_progress': 'started',
  'task:blocked': 'blocked',
  'task:complete': 'completed',
  'task:cancelled': 'cancelled',
  'estimate:draft': 'reverted to draft',
  'estimate:open': 'sent',
  'estimate:accepted': 'accepted',
  'estimate:rejected': 'rejected',
  'estimate:expired': 'expired',
  'estimate:superseded': 'superseded',
  'changeorder:draft': 'reverted to draft',
  'changeorder:open': 'sent',
  'changeorder:accepted': 'accepted',
  'changeorder:rejected': 'rejected',
  'changeorder:expired': 'expired',
  'changeorder:superseded': 'superseded',
  'invoice:draft': 'reverted to draft',
  'invoice:open': 'sent',
  'invoice:partly-paid': 'partly paid',
  'invoice:paid': 'paid',
  'invoice:defaulted': 'defaulted',
  'invoice:cancelled': 'cancelled',
  'invoice:superseded': 'superseded',
  'material:pending': 'reset to pending',
  'material:consumed': 'consumed',
  'material:released': 'released',
  'shipment:prepared': 'prepared',
  'shipment:picked_up': 'picked up',
};

// Object types whose creation reads "created"; the rest read "added".
const CREATED_TYPES = new Set(['job', 'estimate', 'changeorder', 'invoice']);

export function statusVerb(objectType, status) {
  return VERBS[`${objectType}:${status}`] ?? String(status).replace(/_/g, ' ');
}

// One log row per creation or status transition; null for everything else
// (field edits, notes, standalone actions).
function milestoneRow(entry) {
  const c = entry.changes || {};
  const base = {
    id: entry.id,
    when: new Date(entry.timestamp),
    actor: entry.username || null,
    label: entry.source_label || entry.object_type,
    link: entry.source_link || null,
  };
  if (c._created) {
    return { ...base, text: CREATED_TYPES.has(entry.object_type) ? 'created' : 'added' };
  }
  const status = c.status?.new ?? c.consumption_state?.new;
  if (status != null) {
    return { ...base, text: c._action || statusVerb(entry.object_type, status) };
  }
  return null;
}

const statusOf = (e) => e.changes?.status?.new ?? e.changes?.consumption_state?.new;

// Live backend flows sometimes record one status transition as two entries:
// an automatic audit entry (status diff, no `_action`) plus a service-written
// action entry for the same object carrying the same status diff and
// `changes._action`. Drop the audit-flavored row when an action-flavored
// twin exists for the same object and new status within a 60s window — the
// action row (richer text) wins. Creation rows and action rows themselves
// are never dropped; two audit rows with no action twin both survive.
export function milestoneRows(entries) {
  const pairs = (entries || [])
    .map((entry) => ({ entry, row: milestoneRow(entry) }))
    .filter((p) => p.row);

  const actionTwins = pairs.filter((p) => {
    const c = p.entry.changes || {};
    return !c._created && statusOf(p.entry) != null && c._action;
  });

  return pairs
    .filter((p) => {
      const c = p.entry.changes || {};
      const isAuditStatus = !c._created && statusOf(p.entry) != null && !c._action;
      if (!isAuditStatus) return true;
      return !actionTwins.some((t) => (
        t.entry.object_type === p.entry.object_type
        && t.entry.object_id === p.entry.object_id
        && statusOf(t.entry) === statusOf(p.entry)
        && Math.abs(new Date(t.entry.timestamp) - new Date(p.entry.timestamp)) <= 60000
      ));
    })
    .map((p) => p.row);
}

export function dayLabel(d, today = new Date()) {
  const year = d.getFullYear() === today.getFullYear() ? '' : ` ${d.getFullYear()}`;
  return `${DOW[d.getDay()]}, ${MONTHS[d.getMonth()]} ${d.getDate()}${year}`;
}

export function timeLabel(d) {
  let h = d.getHours();
  const ampm = h >= 12 ? 'PM' : 'AM';
  h = h % 12 || 12;
  return `${h}:${String(d.getMinutes()).padStart(2, '0')} ${ampm}`;
}

// rows (already newest-first) -> [{ key, label, rows }] split on local
// calendar day.
export function groupRowsByDay(rows, today = new Date()) {
  const out = [];
  for (const row of rows) {
    const d = row.when;
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    const last = out[out.length - 1];
    if (last && last.key === key) last.rows.push(row);
    else out.push({ key, label: dayLabel(d, today), rows: [row] });
  }
  return out;
}
