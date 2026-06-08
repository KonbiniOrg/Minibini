import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import JobHistoryPage from '@/routes/jobs/JobHistoryPage.svelte';

const JOB = { job_id: 5, job_number: 'JOB-2025-0005', name: 'Test' };

describe('JobHistoryPage', () => {
  beforeEach(() => { api.get.mockReset(); api.post.mockReset(); });

  it('renders collated entries with source labels', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/jobs/5/') return Promise.resolve(JOB);
      if (url === '/api/jobs/5/history/') return Promise.resolve({ results: [
        { id: 1, entry_type: 'action', object_type: 'estimate', object_id: 9,
          username: 'admin', timestamp: '2026-01-02T10:00:00Z',
          changes: { _action: 'Sent to customer' },
          source_label: 'Estimate EST-2025-0001', source_link: null },
        { id: 2, entry_type: 'note', object_type: 'job', object_id: 5,
          username: 'admin', timestamp: '2026-01-03T10:00:00Z', text: 'Customer called',
          changes: null, source_label: 'Job JOB-2025-0005', source_link: '#/jobs/5' },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { findByText, getByText } = render(JobHistoryPage, { props: { params: { id: '5' } } });
    await findByText('History — Job JOB-2025-0005');
    expect(getByText('Estimate EST-2025-0001')).toBeInTheDocument();
    expect(getByText('Sent to customer')).toBeInTheDocument();
    expect(getByText('Customer called')).toBeInTheDocument();
  });

  it('posts a note then reloads', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/api/jobs/5/') return Promise.resolve(JOB);
      return Promise.resolve({ results: [] });
    });
    api.post.mockResolvedValue({});
    const { findByText, getByPlaceholderText, getByRole } =
      render(JobHistoryPage, { props: { params: { id: '5' } } });
    await findByText('History — Job JOB-2025-0005');
    await fireEvent.input(getByPlaceholderText('Add a note…'), { target: { value: 'Hello' } });
    await fireEvent.click(getByRole('button', { name: 'Add Note' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/notes/', { text: 'Hello' });
  });
});
