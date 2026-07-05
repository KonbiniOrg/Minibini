import { writable } from 'svelte/store';

/**
 * The global message overlay (red error / green success box, fixed, centered
 * — the ONE venue for messages that don't belong to a form: non-form action
 * failures, infrastructure errors, and page-level success acknowledgements).
 * Rendered once by MessageOverlay.svelte in App.svelte; pages never carry
 * their own overlay markup.
 */
export const overlayMessage = writable(null); // { kind: 'error'|'success', text, link? }

export function showError(text) {
  overlayMessage.set({ kind: 'error', text });
}

// link (optional): { href, label } — rendered as a navigation link after the
// text (e.g. "Added to <PO-2026-0007>"); clicking it dismisses the overlay.
export function showSuccess(text, link = null) {
  overlayMessage.set(link
    ? { kind: 'success', text, link }
    : { kind: 'success', text });
}

export function clearMessage() {
  overlayMessage.set(null);
}
