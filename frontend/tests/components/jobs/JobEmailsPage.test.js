import { describe, it, expect, beforeEach } from 'vitest';
import { render, within, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import JobEmailsPage from '@/routes/jobs/JobEmailsPage.svelte';

const job = { job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress', contact: null };

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/emails/?job=3') {
      return Promise.resolve({
        results: [
          {
            email_record_id: 9,
            direction: 'inbound',
            display_address: 'a@b.com',
            created_at: '2026-01-01T00:00:00Z',
            temp_email: { subject: 'Hello there' },
          },
        ],
      });
    }
    if (url.includes('/jobs/3/')) return Promise.resolve(job);
    return Promise.resolve(null);
  });
});

describe('JobEmailsPage', () => {
  it('loads the job and renders the shell (header + nav rail) plus the full-width email panel', async () => {
    const { findByText, container } = render(JobEmailsPage, { props: { params: { jobId: '3' } } });
    expect(await findByText(/JOB #3/)).toBeInTheDocument();
    expect(container.querySelector('.job-nav-rail')).toBeInTheDocument();
    // The job context band (expanded by default) hosts its own EmailPanel too,
    // so scope this assertion to the page's own full-width panel.
    await waitFor(() => {
      const pageBody = container.querySelector('.page-body');
      expect(pageBody && within(pageBody).queryByText('Hello there')).toBeTruthy();
    });
    expect(api.get).toHaveBeenCalledWith('/api/emails/?job=3');
  });

  it('shows an error message when the job fetch fails', async () => {
    api.get.mockRejectedValue(new Error('boom'));
    const { findByText } = render(JobEmailsPage, { props: { params: { jobId: '3' } } });
    expect(await findByText('boom')).toBeInTheDocument();
  });
});
