import { describe, it, expect, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));

import { api } from '@/lib/api.js';
import JobHistoryPage from '@/routes/jobs/JobHistoryPage.svelte';

const JOB = { job_id: 5, job_number: 'JOB-2025-0005', name: 'Test' };

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/jobs/5/') return Promise.resolve(JOB);
    if (url.includes('/emails/')) return Promise.resolve({ results: [] });
    if (url.startsWith('/api/jobs/5/history/')) return Promise.resolve({ results: [
      { id: 1, entry_type: 'note', object_type: 'job', object_id: 5,
        username: 'admin', timestamp: '2026-01-03T10:00:00Z', text: 'Customer called',
        changes: null, source_label: 'Job JOB-2025-0005', source_link: '#/jobs/5' },
    ] });
    return Promise.resolve({ results: [] });
  });
});

describe('JobHistoryPage', () => {
  it('loads the job and renders the shell (header + nav rail) plus the history section', async () => {
    const { findByText, findByRole, container } = render(JobHistoryPage, { props: { params: { id: '5' } } });
    expect(await findByText(/JOB #2025-0005/)).toBeInTheDocument();
    expect(container.querySelector('.job-nav-rail')).toBeInTheDocument();
    await findByRole('heading', { name: 'History' });
    expect(await findByText('Customer called')).toBeInTheDocument();
  });

  it('resolves the job id from either the canonical jobId param or the legacy id param', async () => {
    const { findByText } = render(JobHistoryPage, { props: { params: { jobId: '5' } } });
    expect(await findByText(/JOB #2025-0005/)).toBeInTheDocument();
  });

  it('shows an error message when the job fetch fails', async () => {
    api.get.mockRejectedValue(new Error('boom'));
    const { findByText } = render(JobHistoryPage, { props: { params: { id: '5' } } });
    expect(await findByText('boom')).toBeInTheDocument();
  });
});
