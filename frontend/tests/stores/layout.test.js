import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';

// The store reads window.matchMedia lazily (on first subscribe), so each test
// installs its own fake before importing a fresh copy of the module.
let listeners;
let mq;

function installMatchMedia({ matches }) {
  listeners = [];
  mq = {
    matches,
    media: '(max-width: 720px)',
    addEventListener: (type, fn) => { if (type === 'change') listeners.push(fn); },
    removeEventListener: (type, fn) => { listeners = listeners.filter((l) => l !== fn); },
  };
  window.matchMedia = vi.fn(() => mq);
}

function fireChange(matches) {
  mq.matches = matches;
  for (const fn of listeners) fn({ matches });
}

const originalMatchMedia = window.matchMedia;

beforeEach(() => { vi.resetModules(); });
afterEach(() => { window.matchMedia = originalMatchMedia; });

describe('layout store', () => {
  it('exports the phone breakpoint constant', async () => {
    installMatchMedia({ matches: false });
    const { PHONE_MAX_WIDTH } = await import('@/stores/layout.js');
    expect(PHONE_MAX_WIDTH).toBe(720);
  });

  it('is desktop when the phone media query does not match', async () => {
    installMatchMedia({ matches: false });
    const { layout } = await import('@/stores/layout.js');
    expect(get(layout)).toBe('desktop');
    expect(window.matchMedia).toHaveBeenCalledWith('(max-width: 720px)');
  });

  it('is phone when the phone media query matches', async () => {
    installMatchMedia({ matches: true });
    const { layout } = await import('@/stores/layout.js');
    expect(get(layout)).toBe('phone');
  });

  it('follows change events in both directions while subscribed', async () => {
    installMatchMedia({ matches: false });
    const { layout } = await import('@/stores/layout.js');
    const seen = [];
    const unsubscribe = layout.subscribe((v) => seen.push(v));
    fireChange(true);
    fireChange(false);
    unsubscribe();
    expect(seen).toEqual(['desktop', 'phone', 'desktop']);
  });

  it('removes its listener when the last subscriber leaves', async () => {
    installMatchMedia({ matches: false });
    const { layout } = await import('@/stores/layout.js');
    const unsubscribe = layout.subscribe(() => {});
    expect(listeners).toHaveLength(1);
    unsubscribe();
    expect(listeners).toHaveLength(0);
  });

  it('stays desktop when matchMedia is unavailable', async () => {
    window.matchMedia = undefined;
    const { layout } = await import('@/stores/layout.js');
    expect(() => get(layout)).not.toThrow();
    expect(get(layout)).toBe('desktop');
  });
});
