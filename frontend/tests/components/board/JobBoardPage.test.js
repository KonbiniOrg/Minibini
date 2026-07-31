import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

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

  // It lives in each pillar's header rather than a page-level bar, so it
  // survives switching pillars — whichever one is expanded carries it.
  it.each(['Pipeline', 'Unpaid', 'Closed'])('keeps the link in the %s pillar header', async (label) => {
    const { container, getByRole } = render(JobBoardPage);
    // Default pillar is In Progress, whose header is .approved-header — so a
    // .column-header appearing proves the switch actually happened.
    await waitFor(() => expect(container.querySelector('.approved-header')).toBeTruthy());

    await fireEvent.click(getByRole('button', { name: new RegExp(`^${label}`) }));

    const header = await waitFor(() => {
      const h = container.querySelector('.column-header');
      expect(h).toBeTruthy();
      return h;
    });
    expect(header).toHaveTextContent(label);
    expect(header).toContainElement(getByRole('link', { name: 'New Job' }));
  });

  it('hides New Job without can_manage_jobs', async () => {
    user.set({ username: 'sam', permissions: [] });
    const { queryByRole } = render(JobBoardPage);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(queryByRole('link', { name: 'New Job' })).toBeNull();
  });
});
