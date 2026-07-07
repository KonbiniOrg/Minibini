import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/stores/currentBlep.js', async () => {
  const { writable } = await import('svelte/store');
  return { currentBlep: writable(null) };
});
vi.mock('@/stores/blepActivity.js', () => ({ notifyBlepChanged: vi.fn() }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));
vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));

import { currentBlep } from '@/stores/currentBlep.js';
import { api } from '@/lib/api.js';
import CurrentBlepBand from '@/components/CurrentBlepBand.svelte';

beforeEach(() => {
  api.post.mockReset();
  api.post.mockResolvedValue({});
  currentBlep.set(null);
  sessionStorage.clear();
});

describe('CurrentBlepBand', () => {
  it('renders nothing when no blep is running', () => {
    const { queryByText } = render(CurrentBlepBand);
    expect(queryByText(/Working on/)).toBeNull();
  });

  it('offers Stop once past the minimum', async () => {
    currentBlep.set({ task: { id: 5, name: 'Cut' }, start_time: new Date(Date.now() - 120000).toISOString(), blep_minimum_minutes: 1 });
    const { getByText, getByRole } = render(CurrentBlepBand);
    expect(getByText(/Cut/)).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'Stop' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/stop-work/', {});
  });

  it('offers Cancel while under the minimum', async () => {
    currentBlep.set({ task: { id: 5, name: 'Cut' }, start_time: new Date().toISOString(), blep_minimum_minutes: 1 });
    const { getByRole } = render(CurrentBlepBand);
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/cancel-work/', {});
  });
});

// The timer contract (LATER: minute-flooring artifact): a just-started blep
// counts seconds from ZERO at the moment of the click — never from the
// minute-floored server start_time (which would read ~47s immediately).
// When the displayed count reaches 5:00 it switches to minutes-only,
// realigned to the floored start_time (the short fifth minute is invisible).
// A blep first seen already >75s old skips the seconds phase entirely.
describe('CurrentBlepBand timer', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // The user clicks Start at 12:03:47; the server floors to 12:03:00.
    vi.setSystemTime(new Date('2026-07-04T12:03:47Z'));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  const blep = (startIso, id = 9) => ({
    id,
    task: { id: 5, name: 'Cut' },
    start_time: startIso,
    blep_minimum_minutes: 1,
  });

  it('counts seconds from zero at click time, not from the floored start', async () => {
    currentBlep.set(blep('2026-07-04T12:03:00Z'));
    const { getByText } = render(CurrentBlepBand);
    getByText('(0m 0s)');
    await vi.advanceTimersByTimeAsync(65000);
    getByText('(1m 5s)');
  });

  it('switches to minutes-only from the floored start at displayed 5:00', async () => {
    currentBlep.set(blep('2026-07-04T12:03:00Z'));
    const { getByText, queryByText } = render(CurrentBlepBand);
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000); // displayed count hits 5:00
    // Floored elapsed is 5m47s → "5m", seconds gone.
    getByText('(5m)');
    expect(queryByText(/\ds\)/)).toBeNull();
    await vi.advanceTimersByTimeAsync(13000); // 12:09:00 — floored elapsed 6m
    getByText('(6m)');
  });

  it('survives a reload in the same tab without restarting at zero', async () => {
    currentBlep.set(blep('2026-07-04T12:03:00Z'));
    const first = render(CurrentBlepBand);
    await vi.advanceTimersByTimeAsync(90000);
    first.getByText('(1m 30s)');
    first.unmount();
    // Same tab remount (sessionStorage kept): the click-zero is remembered.
    const second = render(CurrentBlepBand);
    second.getByText('(1m 30s)');
  });

  it('skips the seconds phase for a blep first seen already old', () => {
    // Fresh tab, blep started 10 minutes ago: no click-zero to count from —
    // minutes-only immediately, never a mid-minute seconds artifact.
    currentBlep.set(blep('2026-07-04T11:53:00Z', 7));
    const { getByText } = render(CurrentBlepBand);
    getByText('(10m)');
  });

  it('shows hours once elapsed passes an hour', () => {
    currentBlep.set(blep('2026-07-04T10:53:00Z', 7));
    const { getByText } = render(CurrentBlepBand);
    getByText('(1h 10m)');
  });
});
