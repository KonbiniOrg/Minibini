import { writable } from 'svelte/store';

// Bumped when something OUTSIDE the estimate panel changes an estimate's
// line items — today the job header's "Release to floor", whose confirmed
// call bulk-declines every unanswered checklist line (2026-10-18). The
// panel reloads its document only when the viewed estimate changes, so
// without this it kept offering "Generate work…" / "No work needed" on
// lines the server had already declined until a page refresh. Same shape
// as deliverables.js / blepActivity.js: every view holding a copy of the
// lines refetches on a bump. Same-client only (the server guards remain
// the backstop).
export const estimateLinesVersion = writable(0);

export function notifyEstimateLinesChanged() {
  estimateLinesVersion.update((n) => n + 1);
}
