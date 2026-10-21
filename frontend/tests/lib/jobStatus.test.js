import { describe, it, expect } from 'vitest';
import {
  PRE_APPROVAL_JOB_STATUSES, CLOSED_JOB_STATUSES, WORK_FROZEN_JOB_STATUSES,
  isPreApprovalJob, isClosedJob, isWorkFrozenJob, jobStatusLabel,
} from '@/lib/jobStatus.js';

describe('jobStatus', () => {
  it('has the exact group memberships', () => {
    expect([...PRE_APPROVAL_JOB_STATUSES].sort()).toEqual(['draft', 'submitted']);
    expect([...CLOSED_JOB_STATUSES].sort()).toEqual(['archived', 'cancelled', 'completed', 'rejected']);
    expect([...WORK_FROZEN_JOB_STATUSES].sort()).toEqual(
      ['archived', 'cancelled', 'completed', 'rejected', 'work_complete']);
  });
  it('treats archived as closed and work-frozen, not pre-approval', () => {
    expect(isClosedJob('archived')).toBe(true);
    expect(isWorkFrozenJob('archived')).toBe(true);
    expect(isPreApprovalJob('archived')).toBe(false);
    expect(isClosedJob('work_complete')).toBe(false);
  });
  it('labels statuses, passing unknown ones through', () => {
    expect(jobStatusLabel('archived')).toBe('Archived');
    expect(jobStatusLabel('xyz')).toBe('xyz');
  });
});
