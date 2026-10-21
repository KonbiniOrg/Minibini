// One home for the Job status groupings the SPA branches on, so a new
// terminal status (archived, 2026-10) is closed everywhere at once.
export const PRE_APPROVAL_JOB_STATUSES = new Set(['draft', 'submitted']);
export const CLOSED_JOB_STATUSES = new Set(['completed', 'rejected', 'cancelled', 'archived']);
export const WORK_FROZEN_JOB_STATUSES = new Set([...CLOSED_JOB_STATUSES, 'work_complete']);

export const isPreApprovalJob = (status) => PRE_APPROVAL_JOB_STATUSES.has(status);
export const isClosedJob = (status) => CLOSED_JOB_STATUSES.has(status);
export const isWorkFrozenJob = (status) => WORK_FROZEN_JOB_STATUSES.has(status);

export const JOB_STATUS_LABELS = {
  draft: 'Draft',
  submitted: 'Submitted',
  approved: 'Approved',
  in_progress: 'In Progress',
  work_complete: 'Work Complete',
  rejected: 'Rejected',
  completed: 'Completed',
  cancelled: 'Cancelled',
  archived: 'Archived',
};
export const jobStatusLabel = (status) => JOB_STATUS_LABELS[status] ?? status;
