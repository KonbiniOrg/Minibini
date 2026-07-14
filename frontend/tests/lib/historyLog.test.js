import { describe, it, expect } from 'vitest';
import {
  statusVerb, milestoneRows, groupRowsByDay, dayLabel, timeLabel,
} from '@/lib/historyLog.js';

function entry(over = {}) {
  return {
    id: 1, entry_type: 'audit', object_type: 'task', object_id: 7,
    username: 'rae', timestamp: '2026-01-05T09:00:00',
    changes: null, text: '',
    source_label: 'Task: Cutting', source_link: '#/jobs/5/tasks/7',
    ...over,
  };
}

describe('statusVerb', () => {
  it('maps every status through the verb table, not just the surprising ones', () => {
    expect(statusVerb('estimate', 'open')).toBe('sent');
    expect(statusVerb('changeorder', 'open')).toBe('sent');
    expect(statusVerb('invoice', 'partly-paid')).toBe('partly paid');
    expect(statusVerb('invoice', 'paid')).toBe('paid');
    expect(statusVerb('task', 'in_progress')).toBe('started');
    expect(statusVerb('task', 'pending')).toBe('reopened');
    expect(statusVerb('job', 'work_complete')).toBe('work completed');
    expect(statusVerb('job', 'draft')).toBe('reverted to draft');
    expect(statusVerb('shipment', 'picked_up')).toBe('picked up');
    expect(statusVerb('material', 'consumed')).toBe('consumed');
  });

  it('humanizes unknown statuses instead of dropping them', () => {
    expect(statusVerb('job', 'some_new_status')).toBe('some new status');
  });
});

describe('milestoneRows', () => {
  it('turns creations into created/added rows by object type', () => {
    const rows = milestoneRows([
      entry({ id: 1, object_type: 'job', changes: { _created: true }, source_label: 'Job J' }),
      entry({ id: 2, object_type: 'estimate', changes: { _created: true }, source_label: 'Estimate E1' }),
      entry({ id: 3, object_type: 'task', changes: { _created: true } }),
      entry({ id: 4, object_type: 'material', changes: { _created: true }, source_label: 'Material: plywood' }),
    ]);
    expect(rows.map((r) => r.text)).toEqual(['created', 'created', 'added', 'added']);
  });

  it('turns status diffs into verb rows carrying actor, label, link, and time', () => {
    const rows = milestoneRows([
      entry({ changes: { status: { old: 'pending', new: 'complete' } } }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      text: 'completed', actor: 'rae',
      label: 'Task: Cutting', link: '#/jobs/5/tasks/7',
    });
    expect(rows[0].when).toEqual(new Date('2026-01-05T09:00:00'));
  });

  it('prefers the richer _action text when it accompanies a status diff', () => {
    const rows = milestoneRows([
      entry({
        object_type: 'estimate',
        changes: { status: { old: 'open', new: 'expired' }, _action: 'Auto-expired (valid 30 days)' },
      }),
    ]);
    expect(rows[0].text).toBe('Auto-expired (valid 30 days)');
  });

  it('rows consumption_state transitions', () => {
    const rows = milestoneRows([
      entry({ object_type: 'material', changes: { consumption_state: { old: 'pending', new: 'consumed' } } }),
    ]);
    expect(rows[0].text).toBe('consumed');
  });

  it('skips field edits and standalone actions', () => {
    const rows = milestoneRows([
      entry({ id: 1, changes: { name: { old: 'a', new: 'b' } } }),
      entry({ id: 3, entry_type: 'action', changes: { _action: 'PO emailed to x@y.z' } }),
    ]);
    expect(rows).toEqual([]);
  });

  it('turns notes into flagged rows carrying their text', () => {
    const rows = milestoneRows([
      entry({ id: 2, entry_type: 'note', changes: null, text: 'Customer called',
        object_type: 'job', object_id: 5, source_label: 'Job JOB-2025-0005', source_link: '#/jobs/5' }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      text: 'Customer called', note: true, actor: 'rae', label: 'Job JOB-2025-0005',
    });
  });

  it('nulls the actor for system entries', () => {
    const rows = milestoneRows([entry({ username: null, changes: { _created: true } })]);
    expect(rows[0].actor).toBeNull();
  });
});

describe('milestoneRows dedup (audit/action twins)', () => {
  it('drops the audit row when an action twin shares object + new status within 60s', () => {
    const rows = milestoneRows([
      entry({
        id: 1, object_type: 'estimate', object_id: 3, timestamp: '2026-01-05T09:00:00',
        changes: { status: { old: 'open', new: 'accepted' } },
      }),
      entry({
        id: 2, object_type: 'estimate', object_id: 3, timestamp: '2026-01-05T09:00:01',
        changes: { status: { old: 'open', new: 'accepted' }, _action: 'Accepted via customer link' },
      }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].text).toBe('Accepted via customer link');
  });

  it('keeps an audit status row with no action twin', () => {
    const rows = milestoneRows([
      entry({ object_type: 'estimate', object_id: 3, changes: { status: { old: 'open', new: 'accepted' } } }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].text).toBe('accepted');
  });

  it('keeps both when the audit/action pair is more than 60s apart', () => {
    const rows = milestoneRows([
      entry({
        id: 1, object_type: 'estimate', object_id: 3, timestamp: '2026-01-05T09:00:00',
        changes: { status: { old: 'open', new: 'accepted' } },
      }),
      entry({
        id: 2, object_type: 'estimate', object_id: 3, timestamp: '2026-01-05T09:05:00',
        changes: { status: { old: 'open', new: 'accepted' }, _action: 'Accepted via customer link' },
      }),
    ]);
    expect(rows).toHaveLength(2);
  });

  it('keeps both when the audit/action pair have different object_ids', () => {
    const rows = milestoneRows([
      entry({
        id: 1, object_type: 'estimate', object_id: 3, timestamp: '2026-01-05T09:00:00',
        changes: { status: { old: 'open', new: 'accepted' } },
      }),
      entry({
        id: 2, object_type: 'estimate', object_id: 4, timestamp: '2026-01-05T09:00:01',
        changes: { status: { old: 'open', new: 'accepted' }, _action: 'Accepted via customer link' },
      }),
    ]);
    expect(rows).toHaveLength(2);
  });
});

describe('dayLabel', () => {
  const today = new Date('2026-07-13T12:00:00');

  it('renders weekday, month, day', () => {
    expect(dayLabel(new Date('2026-01-05T09:00:00'), today)).toBe('Monday, January 5');
  });

  it('appends the year when it is not the current year', () => {
    expect(dayLabel(new Date('2025-12-30T09:00:00'), today)).toBe('Tuesday, December 30 2025');
  });
});

describe('timeLabel', () => {
  it('formats a 12-hour clock time', () => {
    expect(timeLabel(new Date('2026-01-05T14:05:00'))).toBe('2:05 PM');
    expect(timeLabel(new Date('2026-01-05T00:30:00'))).toBe('12:30 AM');
  });
});

describe('groupRowsByDay', () => {
  const today = new Date('2026-07-13T12:00:00');

  it('splits newest-first rows on local calendar-day boundaries', () => {
    const rows = milestoneRows([
      entry({ id: 3, timestamp: '2026-01-06T09:30:00', changes: { _created: true } }),
      entry({ id: 2, timestamp: '2026-01-05T14:00:00', changes: { _created: true } }),
      entry({ id: 1, timestamp: '2026-01-05T09:00:00', changes: { _created: true } }),
    ]);
    const days = groupRowsByDay(rows, today);
    expect(days.map((d) => d.label)).toEqual(['Tuesday, January 6', 'Monday, January 5']);
    expect(days[0].rows).toHaveLength(1);
    expect(days[1].rows).toHaveLength(2);
  });
});
