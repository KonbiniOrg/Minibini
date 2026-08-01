/**
 * Whole-document navigations, behind one-line helpers.
 *
 * Hash navigation is done inline everywhere else (`push()`, or assigning
 * `window.location.hash`) because jsdom handles it natively. A genuine reload
 * is different: `window.location.reload` is unforgeable, so tests can neither
 * spy on it nor let it run. Routing it through here keeps it mockable.
 */
export function reloadPage() {
  window.location.reload();
}
