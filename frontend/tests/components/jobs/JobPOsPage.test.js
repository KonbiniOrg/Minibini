import { describe, it, expect, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import JobPOsPage from '@/routes/jobs/JobPOsPage.svelte';

const job = { job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress', contact: null };

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.includes('/purchase-orders/')) return Promise.resolve({ results: [] });
    if (url.includes('/emails/')) return Promise.resolve({ results: [] });
    if (url.includes('/jobs/3/')) return Promise.resolve(job);
    return Promise.resolve(null);
  });
});

describe('JobPOsPage', () => {
  it('loads the job and renders the shell (header + nav rail) plus the PO panel', async () => {
    const { findByText, container } = render(JobPOsPage, { props: { params: { jobId: '3' } } });
    expect(await findByText(/JOB #3/)).toBeInTheDocument();
    expect(container.querySelector('.job-nav-rail')).toBeInTheDocument();
    expect(await findByText('No purchase orders touch this job yet.')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/purchase-orders/?job=3');
  });

  it('shows an error message when the job fetch fails', async () => {
    api.get.mockRejectedValue(new Error('boom'));
    const { findByText } = render(JobPOsPage, { props: { params: { jobId: '3' } } });
    expect(await findByText('boom')).toBeInTheDocument();
  });
});
