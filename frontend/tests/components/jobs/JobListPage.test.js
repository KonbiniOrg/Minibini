import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, fireEvent } from '@testing-library/svelte';

const qs = await vi.hoisted(async () => {
  const { writable } = await import('svelte/store');
  return writable('');
});
vi.mock('svelte-spa-router', () => ({ push: vi.fn(), querystring: qs }));
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() }, errorMessage: (e, fallback) => e?.message || fallback }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import JobListPage from '@/routes/jobs/JobListPage.svelte';

beforeEach(() => {
  api.get.mockReset();
  user.set({ id: 1, permissions: ['can_manage_jobs'] });
});

describe('JobListPage PM filter', () => {
  it('passes project_manager to the API and retitles when ?pm is set', async () => {
    qs.set('pm=4');
    api.get.mockResolvedValue({
      count: 1,
      results: [{ job_id: 1, job_number: 'JOB-1', name: 'Alpha', status: 'draft', project_manager: 4, project_manager_name: 'Dana Doe' }],
    });
    const { getByText } = render(JobListPage, { props: {} });
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(expect.stringContaining('project_manager=4'));
    });
    await waitFor(() => expect(getByText(/Jobs managed by Dana Doe/)).toBeInTheDocument());
  });

  it('uses the plain title and no PM param without ?pm', async () => {
    qs.set('');
    api.get.mockResolvedValue({ count: 0, results: [] });
    const { getByText } = render(JobListPage, { props: {} });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(api.get.mock.calls[0][0]).not.toContain('project_manager');
    expect(getByText(/^Jobs \(/)).toBeInTheDocument();
  });
});

describe('JobListPage New Job (JobCreateModal host)', () => {
  it('New Job is a button that opens the modal', async () => {
    qs.set('');
    api.get.mockResolvedValue({ count: 0, results: [] });
    const { findByRole, queryByRole } = render(JobListPage, { props: {} });
    expect(queryByRole('link', { name: 'New Job' })).toBeNull();
    await fireEvent.click(await findByRole('button', { name: 'New Job' }));
    expect(await findByRole('dialog', { name: 'New job' })).toBeInTheDocument();
  });
});
