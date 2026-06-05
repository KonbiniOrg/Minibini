import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('@/stores/shift.js', async () => {
  const { writable } = await import('svelte/store');
  return { shiftActivityVersion: writable(0) };
});

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import MyShiftsList from '@/components/home/MyShiftsList.svelte';

beforeEach(() => {
  api.get.mockReset();
  user.set({ id: 2, permissions: [] });
});

describe('MyShiftsList', () => {
  it('shows the empty state', async () => {
    api.get.mockResolvedValue({ results: [] });
    const { findByText } = render(MyShiftsList);
    expect(await findByText('No recent shifts.')).toBeInTheDocument();
  });

  it('lists recent shifts', async () => {
    api.get.mockResolvedValue({ results: [{ shift_id: 1, start_time: '2026-03-01T08:00:00', end_time: '2026-03-01T16:00:00' }] });
    const { findByText } = render(MyShiftsList);
    expect(await findByText('8h 0m')).toBeInTheDocument();
  });
});
