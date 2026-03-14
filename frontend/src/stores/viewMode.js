import { writable } from 'svelte/store';

const STORAGE_KEY = 'minibini_view_mode';
const stored = localStorage.getItem(STORAGE_KEY) || 'lite';

export const viewMode = writable(stored);

viewMode.subscribe((value) => {
  localStorage.setItem(STORAGE_KEY, value);
});

export function toggleViewMode() {
  viewMode.update((current) => (current === 'full' ? 'lite' : 'full'));
}
