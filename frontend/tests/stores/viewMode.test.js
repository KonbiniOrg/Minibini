import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { viewMode, toggleViewMode } from '@/stores/viewMode.js';

describe('viewMode store', () => {
  beforeEach(() => {
    viewMode.set('lite'); // normalize between tests
  });

  it('toggles lite -> full -> lite', () => {
    expect(get(viewMode)).toBe('lite');
    toggleViewMode();
    expect(get(viewMode)).toBe('full');
    toggleViewMode();
    expect(get(viewMode)).toBe('lite');
  });

  it('persists the current value to localStorage', () => {
    toggleViewMode();
    expect(localStorage.getItem('minibini_view_mode')).toBe('full');
  });
});
