import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/stores/shift.js', async () => {
  const { writable } = await import('svelte/store');
  return { currentShift: writable(null), refreshCurrentShift: vi.fn(), notifyShiftChanged: vi.fn() };
});
vi.mock('@/stores/blepActivity.js', () => ({ notifyBlepChanged: vi.fn() }));
vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));

import { currentShift } from '@/stores/shift.js';
import { api } from '@/lib/api.js';
import ClockBand from '@/components/home/ClockBand.svelte';

beforeEach(() => {
  api.post.mockReset();
  api.post.mockResolvedValue({});
  currentShift.set(null);
});

describe('ClockBand', () => {
  it('clocks in when off the clock', async () => {
    const { getByRole } = render(ClockBand);
    await fireEvent.click(getByRole('button', { name: 'Clock In' }));
    expect(api.post).toHaveBeenCalledWith('/api/shifts/clock-in/', {});
  });

  it('clocks out when on the clock', async () => {
    currentShift.set({ start_time: new Date().toISOString() });
    const { getByRole } = render(ClockBand);
    await fireEvent.click(getByRole('button', { name: 'Clock Out' }));
    expect(api.post).toHaveBeenCalledWith('/api/shifts/clock-out/', {});
  });
});
