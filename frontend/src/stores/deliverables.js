import { writable } from 'svelte/store';

// One funnel for every deliverable mutation the SPA makes (the band's edit
// modal, the change order's deliverables section, Make Deliverable on an
// estimate line, removing a line together with its deliverable). Bumped on
// success so every view holding a copy of a job's deliverables refetches:
// the estimate / change-order send gates, the context band's list, the CO
// panel's live list. Same shape as blepActivity.js / shift.js. Cross-client
// changes are out of scope (the server guards remain the backstop).
export const deliverablesVersion = writable(0);

export function notifyDeliverablesChanged() {
  deliverablesVersion.update((n) => n + 1);
}
