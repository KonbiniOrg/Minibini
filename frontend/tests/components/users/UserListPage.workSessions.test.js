import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));
vi.mock('@/stores/blepActivity.js', async () => {
  const { writable } = await import('svelte/store');
  return { blepActivityVersion: writable(0), notifyBlepChanged: vi.fn() };
});

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import UserListPage from '@/routes/users/UserListPage.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/bleps/')) {
      return Promise.resolve({ count: 1, results: [{
        blep_id: 1, user: 2, user_name: 'Wanda',
        task: 4, task_name: 'Cut', job_id: 3, job_number: 'JOB-3', job_name: 'W',
        start_time: '2026-03-01T14:00:00', end_time: '2026-03-01T15:00:00',
      }] });
    }
    return Promise.resolve([]);
  });
});

describe('UserListPage Work Sessions tab', () => {
  it('shows the tab to time/financial managers and lists everyone\'s sessions', async () => {
    user.set({ id: 1, permissions: ['can_manage_time'] });
    const { getByRole, findByText, getByText } = render(UserListPage);
    await fireEvent.click(getByRole('button', { name: 'Work Sessions' }));
    expect(await findByText('Cut')).toBeInTheDocument();
    // All-users surface: worker column present, unscoped fetch.
    expect(getByText('Wanda')).toBeInTheDocument();
    await waitFor(() => {
      const blepCall = api.get.mock.calls.find(([u]) => u.startsWith('/api/bleps/'));
      expect(blepCall[0]).not.toContain('user=');
    });
  });

  it('hides the tab from users without the time/financial atoms', async () => {
    user.set({ id: 1, permissions: ['can_manage_config'] });
    const { queryByRole } = render(UserListPage);
    expect(queryByRole('button', { name: 'Work Sessions' })).toBeNull();
  });
});
