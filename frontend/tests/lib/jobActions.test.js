import { describe, it, expect } from 'vitest';
import { canMarkWorkComplete } from '@/lib/jobActions.js';

describe('canMarkWorkComplete', () => {
  it('allows approved and in_progress jobs', () => {
    expect(canMarkWorkComplete({ status: 'approved' })).toBe(true);
    expect(canMarkWorkComplete({ status: 'in_progress' })).toBe(true);
  });

  it('hides on pre-approval jobs (draft, submitted)', () => {
    expect(canMarkWorkComplete({ status: 'draft' })).toBe(false);
    expect(canMarkWorkComplete({ status: 'submitted' })).toBe(false);
  });

  it('hides on work_complete and terminal statuses', () => {
    for (const s of ['work_complete', 'completed', 'cancelled', 'rejected']) {
      expect(canMarkWorkComplete({ status: s })).toBe(false);
    }
  });

  it('hides while the job is held, whatever the status', () => {
    expect(canMarkWorkComplete({ status: 'in_progress', on_hold: true })).toBe(false);
    expect(canMarkWorkComplete({ status: 'approved', on_hold: true })).toBe(false);
  });

  it('hides with no job at all', () => {
    expect(canMarkWorkComplete(null)).toBe(false);
  });
});
