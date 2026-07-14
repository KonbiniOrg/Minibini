// Gating rules for job-level actions shared by route pages.

// "Mark Work Complete" only makes sense while work can actually be underway:
// pre-approval (draft/submitted) there is no work to complete, a held job
// blocks all status changes server-side, and work_complete/terminal statuses
// are already past it. Takes the job object so the on_hold flag is honored.
export function canMarkWorkComplete(job) {
  if (!job || job.on_hold) return false;
  return job.status === 'approved' || job.status === 'in_progress';
}
