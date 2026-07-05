import { describe, it, expect } from 'vitest';
import { canMarkWorkComplete } from '@/lib/jobActions.js';

describe('canMarkWorkComplete', () => {
  it('allows approved and in_progress jobs', () => {
    expect(canMarkWorkComplete('approved')).toBe(true);
    expect(canMarkWorkComplete('in_progress')).toBe(true);
  });

  it('hides on pre-approval jobs (draft, submitted)', () => {
    expect(canMarkWorkComplete('draft')).toBe(false);
    expect(canMarkWorkComplete('submitted')).toBe(false);
  });

  it('hides on on_hold, work_complete and terminal statuses', () => {
    for (const s of ['on_hold', 'work_complete', 'completed', 'cancelled', 'rejected']) {
      expect(canMarkWorkComplete(s)).toBe(false);
    }
  });
});
