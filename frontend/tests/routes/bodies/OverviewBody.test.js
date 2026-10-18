import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  errorMessage: (e, fallback) => e?.message || fallback,
}));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import OverviewBody from '@/routes/jobs/bodies/OverviewBody.svelte';

const job = {
  job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress',
  contact: null, can_manage: true, materials: [], tasks: [],
};

const overviewFetches = () => api.get.mock.calls.filter(([url]) => url === '/api/jobs/3/overview/');

beforeEach(() => {
  user.set({ permissions: ['can_manage_jobs'] });
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/jobs/3/overview/') return Promise.resolve({ due: null, spend: {}, work: {} });
    if (url.includes('/deliverables/')) return Promise.resolve([]);
    return Promise.resolve({ results: [] });
  });
});

describe('OverviewBody refresh chain', () => {
  it('reloads the block aggregates when the workspace hands back a refetched job', async () => {
    // onJobChange → JobWorkspace refetches the job → a NEW job object arrives
    // as the prop (same id). The six blocks are built from the aggregate
    // endpoints, so they must refetch too — as JobDetailPage.loadJob did.
    const { findByText, rerender } = render(OverviewBody, { props: { job } });
    await findByText('Scope');
    expect(overviewFetches()).toHaveLength(1);

    await rerender({ job: { ...job, status: 'work_complete' } });

    await waitFor(() => expect(overviewFetches()).toHaveLength(2));
  });

  it('keeps the blocks on screen while the refetch is in flight (no Loading flash)', async () => {
    const { findByText, queryByText, rerender } = render(OverviewBody, { props: { job } });
    await findByText('Scope');

    api.get.mockImplementation(() => new Promise(() => {}));
    await rerender({ job: { ...job } });

    expect(queryByText('Scope')).toBeInTheDocument();
    expect(queryByText('Loading...')).not.toBeInTheDocument();
  });
});
