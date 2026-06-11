import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import JobTaskListPage from '@/routes/jobs/JobTaskListPage.svelte';

// The fetched job carries can_manage = "atom-holder OR this job's PM". The page
// toolbar gates "Mark Work Complete" on job.can_manage alone (not the global
// atom), while "Add Manual Task" is open to any authenticated user. These tests
// set the global atom to false (worker) to prove the per-object flag is what
// drives the manager affordance, and that add-task ignores permissions entirely.
function mockApi(jobOverrides = {}) {
  const job = {
    job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress',
    contact: null, materials: [], tasks: [],
    ...jobOverrides,
  };
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/jobs/3/')) return Promise.resolve(job);
    if (url.startsWith('/api/task-templates/')) return Promise.resolve([]);
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve([]);
    if (url.startsWith('/api/contacts/')) return Promise.resolve({});
    return Promise.resolve([]);
  });
}

beforeEach(() => {
  // Worker (no atom): proves gating is driven by job.can_manage, not the atom.
  user.set({ id: 99, permissions: [] });
});

describe('JobTaskListPage per-job can_manage', () => {
  it('shows Add Manual Task even when atom off and can_manage false (add is open to all)', async () => {
    mockApi({ can_manage: false });
    const { getByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await waitFor(() => expect(getByRole('button', { name: /add manual task/i })).toBeInTheDocument());
  });

  it('shows Mark Work Complete when can_manage is true (atom off)', async () => {
    mockApi({ can_manage: true });
    const { getByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    await waitFor(() => expect(getByRole('button', { name: /mark work complete/i })).toBeInTheDocument());
  });

  it('hides Mark Work Complete when can_manage is false (atom off)', async () => {
    mockApi({ can_manage: false });
    const { findByRole, queryByRole } = render(JobTaskListPage, { props: { params: { id: 3 } } });
    // wait for the toolbar to render (add manual task always shows)
    await findByRole('button', { name: /add manual task/i });
    expect(queryByRole('button', { name: /mark work complete/i })).toBeNull();
  });
});
