import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), put: vi.fn(), patch: vi.fn(), post: vi.fn() },
}));

import { api } from '@/lib/api.js';
import { user as currentUser } from '@/stores/auth.js';
import UserDetailPage from '@/routes/users/UserDetailPage.svelte';

const TARGET = {
  id: 7, username: 'worker7', email: 'w7@example.com',
  first_name: 'Wanda', last_name: 'Seven',
  is_active: true, permissions: [], schedule_envelope: null,
};

beforeEach(() => {
  api.get.mockReset();
  api.put.mockReset();
  // The page also mounts UserReimbursementPanel, which fetches lists —
  // answer the user-detail URL with the target and everything else empty.
  api.get.mockImplementation((url) =>
    Promise.resolve(url === '/api/users/7/' ? { ...TARGET } : [])
  );
  api.put.mockResolvedValue({ ...TARGET });
  currentUser.set({ id: 1, permissions: ['can_manage_config'] });
});

describe('UserDetailPage schedule envelope section', () => {
  it('renders the section with the shop-default placeholder for a null envelope', async () => {
    const { findByText } = render(UserDetailPage, { props: { params: { id: '7' } } });
    expect(await findByText('Schedule envelope')).toBeInTheDocument();
    expect(await findByText(/Using the shop schedule/)).toBeInTheDocument();
  });

  it('customizes and saves via the admin schedule-envelope route', async () => {
    api.put.mockResolvedValue({
      ...TARGET,
      schedule_envelope: { mon: [['08:00', '17:00']] },
    });
    const { findByText, getByRole } = render(UserDetailPage, {
      props: { params: { id: '7' } },
    });
    await fireEvent.click(await findByText('Customize'));
    await fireEvent.click(getByRole('button', { name: 'Save schedule' }));
    expect(api.put).toHaveBeenCalledWith('/api/users/7/schedule-envelope/', {
      schedule_envelope: expect.objectContaining({ mon: [['08:00', '17:00']] }),
    });
    expect(await findByText('Schedule saved.')).toBeInTheDocument();
  });

  it('surfaces envelope validation errors', async () => {
    api.put.mockRejectedValue({
      data: { schedule_envelope: ['mon: intervals must not overlap'] },
    });
    const { findByText, getByRole } = render(UserDetailPage, {
      props: { params: { id: '7' } },
    });
    await fireEvent.click(await findByText('Customize'));
    await fireEvent.click(getByRole('button', { name: 'Save schedule' }));
    expect(await findByText(/must not overlap/)).toBeInTheDocument();
  });
});

describe('UserDetailPage work sessions section', () => {
  it('lists the target user\'s sessions, scoped and without the worker column', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/users/7/') return Promise.resolve({ ...TARGET });
      if (url.startsWith('/api/bleps/')) {
        return Promise.resolve({ count: 1, results: [{
          blep_id: 1, user: 7, user_name: 'Wanda Seven',
          task: 4, task_name: 'Cut', job_id: 3, job_number: 'JOB-3', job_name: 'W',
          start_time: '2026-03-01T14:00:00', end_time: '2026-03-01T15:00:00',
        }] });
      }
      return Promise.resolve([]);
    });
    const { findByText, getByRole, queryByText } = render(UserDetailPage, {
      props: { params: { id: 7 } },
    });
    expect(await findByText('Cut')).toBeInTheDocument();
    expect(getByRole('heading', { name: 'Work Sessions' })).toBeInTheDocument();
    // Scoped to this user; single-user surface suppresses the worker column.
    const blepCall = api.get.mock.calls.find(([u]) => u.startsWith('/api/bleps/'));
    expect(blepCall[0]).toContain('user=7');
    expect(queryByText('Worker')).toBeNull();
  });
});
