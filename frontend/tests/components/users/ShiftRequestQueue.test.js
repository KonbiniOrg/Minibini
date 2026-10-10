import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() }, errorMessage: (e, fallback) => e?.message || fallback }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import ShiftRequestQueue from '@/components/users/ShiftRequestQueue.svelte';
import { viewMode } from '@/stores/viewMode.js';

const SHIFT_REQ = {
  request_id: 1, requester_name: 'Sam', shift: 5, reason: 'fix start',
  requested_start: '2026-03-01T08:00:00', requested_end: null, created_at: '2026-01-01', conflicts: [],
};

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  user.set({ id: 9, permissions: ['can_manage_time'] });
  api.get.mockImplementation((url) => {
    if (url.includes('shift-change-requests')) return Promise.resolve({ results: [SHIFT_REQ] });
    return Promise.resolve({ results: [] }); // blep requests + any TimeEditModal load
  });
  api.post.mockResolvedValue({});
});

describe('ShiftRequestQueue', () => {
  it('loads and lists pending requests', async () => {
    const { findByText } = render(ShiftRequestQueue);
    expect(await findByText('Sam')).toBeInTheDocument();
  });

  it('approves a request via the endpoint', async () => {
    const { findByRole } = render(ShiftRequestQueue);
    await fireEvent.click(await findByRole('button', { name: 'Approve' }));
    expect(api.post).toHaveBeenCalledWith('/api/shift-change-requests/1/approve/');
  });

  it('shows the empty state when nothing is pending', async () => {
    api.get.mockResolvedValue({ results: [] });
    const { findByText } = render(ShiftRequestQueue);
    expect(await findByText('No pending requests.')).toBeInTheDocument();
  });
});

describe('ShiftRequestQueue — DataTable', () => {
  const headersOf = (t) => Array.from(t.querySelectorAll('thead th')).map((th) => th.textContent.trim());
  const ALL = ['Type', 'Worker', 'Record', 'Requested', 'Reason', 'Conflict', 'Actions'];
  it('renders the seven columns in both densities with data-col', async () => {
    viewMode.set('lite');
    const { findByText, container } = render(ShiftRequestQueue);
    await findByText('fix start');
    const table = container.querySelector('table.data-table');
    expect(headersOf(table)).toEqual(ALL);
    expect(table.querySelector('td[data-col="record"] button').textContent).toContain('Open shift');
    expect(table.querySelectorAll('td[data-col="actions"] button')).toHaveLength(2);
    viewMode.set('full');
    const { findByText: f2, container: c2 } = render(ShiftRequestQueue);
    await f2('fix start');
    expect(headersOf(c2.querySelector('table.data-table'))).toEqual(ALL);
  });
});
