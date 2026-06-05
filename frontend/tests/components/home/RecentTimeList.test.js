import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));
vi.mock('@/stores/blepActivity.js', async () => {
  const { writable } = await import('svelte/store');
  return { blepActivityVersion: writable(0), notifyBlepChanged: vi.fn() };
});

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import RecentTimeList from '@/components/home/RecentTimeList.svelte';

beforeEach(() => {
  api.get.mockReset();
  user.set({ id: 2, permissions: [] });
});

describe('RecentTimeList', () => {
  it('shows the empty state', async () => {
    api.get.mockResolvedValue({ results: [] });
    const { findByText } = render(RecentTimeList);
    expect(await findByText('No recent time entries.')).toBeInTheDocument();
  });

  it('lists recent bleps', async () => {
    api.get.mockResolvedValue({ results: [{ blep_id: 1, task_name: 'Cut', start_time: '2026-03-01T14:00:00', end_time: '2026-03-01T15:00:00' }] });
    const { findByText } = render(RecentTimeList);
    expect(await findByText('Cut')).toBeInTheDocument();
  });
});
