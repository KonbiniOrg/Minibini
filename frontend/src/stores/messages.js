import { writable } from 'svelte/store';

/**
 * The global message overlay (red error / green success box, fixed, centered
 * — the ONE venue for messages that don't belong to a form: non-form action
 * failures, infrastructure errors, and page-level success acknowledgements).
 * Rendered once by MessageOverlay.svelte in App.svelte; pages never carry
 * their own overlay markup.
 */
export const overlayMessage = writable(null); // { kind: 'error'|'success', text }

export function showError(text) {
  overlayMessage.set({ kind: 'error', text });
}

export function showSuccess(text) {
  overlayMessage.set({ kind: 'success', text });
}

export function clearMessage() {
  overlayMessage.set(null);
}
