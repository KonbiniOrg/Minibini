import { describe, it, expect } from 'vitest';
import { taskActivity } from '@/lib/taskActivity.js';

describe('taskActivity', () => {
  it('returns null for a missing task', () => {
    expect(taskActivity(null)).toBeNull();
    expect(taskActivity(undefined)).toBeNull();
  });

  it('treats an active blep as "Working", overriding status', () => {
    const a = taskActivity({ has_active_blep: true, status: 'blocked' });
    expect(a).toMatchObject({ key: 'working', label: 'Working', pulse: true });
  });

  it('maps each lifecycle status to its label', () => {
    expect(taskActivity({ status: 'blocked' }).label).toBe('Blocked');
    expect(taskActivity({ status: 'pending' }).label).toBe('Unstarted');
    expect(taskActivity({ status: 'in_progress' }).label).toBe('Ongoing');
    expect(taskActivity({ status: 'complete' }).label).toBe('Complete');
    expect(taskActivity({ status: 'cancelled' }).label).toBe('Cancelled');
  });

  it('does not pulse for non-working states', () => {
    expect(taskActivity({ status: 'in_progress' }).pulse).toBe(false);
  });

  it('returns null for an unknown status', () => {
    expect(taskActivity({ status: 'banana' })).toBeNull();
  });
});
