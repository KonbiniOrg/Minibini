import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import MaterialPicker from '@/components/expenses/MaterialPicker.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/jobs/?search=')) {
      return Promise.resolve({ results: [{ job_id: 1, job_number: 'JOB-1', name: 'Widget', status: 'in_progress' }] });
    }
    if (url === '/api/jobs/1/') return Promise.resolve({ job_id: 1, tasks: [{ task_id: 10, name: 'Cut' }] });
    if (url === '/api/tasks/10/materials/') {
      return Promise.resolve({ results: [{ material_id: 100, description: 'Steel', quantity: 5, units: 'kg' }] });
    }
    return Promise.resolve({ results: [] });
  });
});

describe('MaterialPicker', () => {
  it('searches jobs once the query is long enough', async () => {
    const { getByLabelText, findByText } = render(MaterialPicker);
    await fireEvent.input(getByLabelText('Job'), { target: { value: 'wid' } });
    expect(await findByText('JOB-1 — Widget')).toBeInTheDocument();
  });

  it('loads the job materials after picking a job', async () => {
    const { getByLabelText, findByText } = render(MaterialPicker);
    await fireEvent.input(getByLabelText('Job'), { target: { value: 'wid' } });
    await fireEvent.click(await findByText('JOB-1 — Widget'));
    expect(await findByText(/Steel/)).toBeInTheDocument();
  });

  it('queues a new material', async () => {
    const { getByLabelText, findByText } = render(MaterialPicker);
    await fireEvent.input(getByLabelText('Job'), { target: { value: 'wid' } });
    await fireEvent.click(await findByText('JOB-1 — Widget'));
    await fireEvent.click(await findByText('+ Add new material'));
    expect(await findByText(/New material/)).toBeInTheDocument();
  });
});
