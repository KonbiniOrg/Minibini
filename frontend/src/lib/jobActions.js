// Gating rules for job-level actions shared by route pages.

// "Mark Work Complete" only makes sense while work can actually be underway:
// pre-approval (draft/submitted) there is no work to complete, on_hold blocks
// job actions, and work_complete/terminal statuses are already past it.
export function canMarkWorkComplete(status) {
  return status === 'approved' || status === 'in_progress';
}
