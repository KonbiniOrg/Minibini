import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import JobBoardPage from '@/routes/jobs/JobBoardPage.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue({ jobs: [], workers: [], unassigned: [], available_workers: [] });
  sessionStorage.clear();
  user.set({ username: 'rachel', permissions: ['can_manage_jobs'] });
});

describe('JobBoardPage New Job entry point', () => {
  it('offers a New Job link to the create form', async () => {
    const { getByRole } = render(JobBoardPage);
    await waitFor(() => {
      const link = getByRole('link', { name: 'New Job' });
      expect(link).toHaveAttribute('href', '#/jobs/new');
    });
  });

  it('hides New Job without can_manage_jobs', async () => {
    user.set({ username: 'sam', permissions: [] });
    const { queryByRole } = render(JobBoardPage);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(queryByRole('link', { name: 'New Job' })).toBeNull();
  });
});
