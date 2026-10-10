import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() }, errorMessage: (e, fallback) => e?.message || fallback }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));
vi.mock('@/stores/blepActivity.js', async () => {
  const { writable } = await import('svelte/store');
  return { blepActivityVersion: writable(0), notifyBlepChanged: vi.fn() };
});

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import UserListPage from '@/routes/users/UserListPage.svelte';
import { viewMode } from '@/stores/viewMode.js';

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

describe('UserListPage users tab — DataTable', () => {
  const headersOf = (t) => Array.from(t.querySelectorAll('thead th')).map((th) => th.textContent.trim());
  const ALL = ['Username', 'Name', 'Email', 'Permissions', 'Status', 'Actions'];
  it('renders the six user columns in both densities with data-col', async () => {
    user.set({ id: 1, permissions: ['can_manage_config'] });
    api.get.mockImplementation((url) => Promise.resolve(url.startsWith('/api/users/')
      ? [{ id: 2, username: 'wanda', first_name: 'Wanda', last_name: 'W', email: 'w@x.com', permissions: ['can_manage_time'], is_active: false }]
      : []));
    viewMode.set('lite');
    const { findByText, container } = render(UserListPage);
    await findByText('wanda');
    const table = container.querySelector('table.data-table');
    expect(headersOf(table)).toEqual(ALL);
    expect(table.querySelector('td[data-col="status"]').textContent.trim()).toBe('Deactivated');
    expect(table.querySelector('td[data-col="permissions"]').textContent.trim()).toBe('time');
    expect(table.querySelector('td[data-col="actions"] a')).toHaveAttribute('href', '/users/2');
    viewMode.set('full');
    const { findByText: f2, container: c2 } = render(UserListPage);
    await f2('wanda');
    expect(headersOf(c2.querySelector('table.data-table'))).toEqual(ALL);
  });
});
