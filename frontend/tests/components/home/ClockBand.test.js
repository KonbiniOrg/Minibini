import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/stores/shift.js', async () => {
  const { writable } = await import('svelte/store');
  return { currentShift: writable(null), refreshCurrentShift: vi.fn(), notifyShiftChanged: vi.fn() };
});
vi.mock('@/stores/blepActivity.js', () => ({ notifyBlepChanged: vi.fn() }));
vi.mock('@/lib/api.js', () => ({
  api: { post: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));

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

  it('settles an open entered-qty session before clocking out', async () => {
    currentShift.set({ start_time: new Date().toISOString() });
    api.post.mockImplementation((url, body) => {
      if (url === '/api/shifts/clock-out/' && !body?.prior_qty_handled) {
        return Promise.resolve({
          conflict: 'prior_session_qty',
          prior_task: { task_id: 7, name: 'Cut panels' },
          unit_label: 'pcs', current_qty: '9',
        });
      }
      return Promise.resolve({});
    });
    const { getByRole, getByText } = render(ClockBand);
    await fireEvent.click(getByRole('button', { name: 'Clock Out' }));
    expect(getByText(/Cut panels/)).toBeInTheDocument();
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '5' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    await vi.waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/tasks/7/actual-qty/add/', { actual_qty: 5 });
      expect(api.post).toHaveBeenCalledWith('/api/shifts/clock-out/', { prior_qty_handled: true });
    });
  });

  it('cancelling the prompt leaves the shift (and session) open', async () => {
    currentShift.set({ start_time: new Date().toISOString() });
    api.post.mockResolvedValue({
      conflict: 'prior_session_qty',
      prior_task: { task_id: 7, name: 'Cut panels' },
      unit_label: 'pcs', current_qty: null,
    });
    const { getByRole } = render(ClockBand);
    await fireEvent.click(getByRole('button', { name: 'Clock Out' }));
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    const flagged = api.post.mock.calls.filter(([, body]) => body?.prior_qty_handled);
    expect(flagged).toHaveLength(0);
  });
});
