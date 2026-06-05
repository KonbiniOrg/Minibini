import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('@/stores/shift.js', async () => {
  const { writable } = await import('svelte/store');
  return { shiftActivityVersion: writable(0) };
});
vi.mock('@/stores/blepActivity.js', async () => {
  const { writable } = await import('svelte/store');
  return { blepActivityVersion: writable(0) };
});

import { api } from '@/lib/api.js';
import MyChangeRequestsList from '@/components/home/MyChangeRequestsList.svelte';

beforeEach(() => {
  api.get.mockReset();
});

describe('MyChangeRequestsList', () => {
  it('shows the empty state', async () => {
    api.get.mockResolvedValue({ results: [] });
    const { findByText } = render(MyChangeRequestsList);
    expect(await findByText('No change requests.')).toBeInTheDocument();
  });

  it('lists merged shift and blep requests', async () => {
    api.get.mockImplementation((url) => {
      if (url.includes('shift-change-requests')) {
        return Promise.resolve({ results: [{ request_id: 1, requested_start: '2026-03-01T08:00:00', reason: 'fix shift', status: 'pending', created_at: '2026-01-01' }] });
      }
      return Promise.resolve({ results: [] });
    });
    const { findByText } = render(MyChangeRequestsList);
    expect(await findByText('fix shift')).toBeInTheDocument();
  });
});
