import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => ({}) }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import CreateWorksheetPage from '@/routes/jobs/CreateWorksheetPage.svelte';

// Creating a worksheet on a job is manager/PM per-job. The fetched job carries
// can_manage = "atom-holder OR this job's PM". The page gates the form on
// job.can_manage alone (not the global atom). Global atom off (worker)
// throughout to prove the per-object flag drives it.
function mockApi(jobOverrides = {}) {
  const job = {
    job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress', contact: null,
    ...jobOverrides,
  };
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/jobs/3/')) return Promise.resolve(job);
    if (url.startsWith('/api/work-templates/')) return Promise.resolve([]);
    if (url.startsWith('/api/contacts/')) return Promise.resolve({});
    return Promise.resolve([]);
  });
}

beforeEach(() => {
  user.set({ id: 99, permissions: [] });
});

describe('CreateWorksheetPage per-job can_manage', () => {
  it('shows Create Worksheet form when can_manage is true (atom off)', async () => {
    mockApi({ can_manage: true });
    const { getByRole } = render(CreateWorksheetPage, { props: { params: { id: 3 } } });
    await waitFor(() => expect(getByRole('button', { name: /create worksheet/i })).toBeInTheDocument());
  });

  it('shows permission denied when can_manage is false (atom off)', async () => {
    mockApi({ can_manage: false });
    const { findByText, queryByRole } = render(CreateWorksheetPage, { props: { params: { id: 3 } } });
    await findByText(/do not have permission to create worksheets/i);
    expect(queryByRole('button', { name: /create worksheet/i })).toBeNull();
  });
});
