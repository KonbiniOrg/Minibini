import { describe, it, expect, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import { api } from '@/lib/api.js';
import JobTaskListPage from '@/routes/jobs/JobTaskListPage.svelte';

const job = {
  job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress',
  contact: null, materials: [], tasks: [], fees: [], can_manage: false,
};

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.includes('/emails/')) return Promise.resolve({ results: [] });
    if (url.startsWith('/api/jobs/3/')) return Promise.resolve(job);
    if (url.startsWith('/api/service-items/')) return Promise.resolve([]);
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve([]);
    if (url.startsWith('/api/contacts/')) return Promise.resolve({});
    return Promise.resolve([]);
  });
});

describe('JobTaskListPage', () => {
  it('loads the job and renders the shell (header + nav rail) plus the tasks panel', async () => {
    const { findByText, findByRole, container } = render(JobTaskListPage, { props: { params: { jobId: '3' } } });
    expect(await findByText(/JOB #3/)).toBeInTheDocument();
    expect(container.querySelector('.job-nav-rail')).toBeInTheDocument();
    expect(await findByRole('button', { name: /add work/i })).toBeInTheDocument();
  });

  it('resolves the job id from either the canonical jobId param or the legacy id param', async () => {
    const { findByText } = render(JobTaskListPage, { props: { params: { id: '3' } } });
    expect(await findByText(/JOB #3/)).toBeInTheDocument();
  });

  it('shows an error message when the job fetch fails', async () => {
    api.get.mockRejectedValue(new Error('boom'));
    const { findByText } = render(JobTaskListPage, { props: { params: { jobId: '3' } } });
    expect(await findByText('boom')).toBeInTheDocument();
  });
});
