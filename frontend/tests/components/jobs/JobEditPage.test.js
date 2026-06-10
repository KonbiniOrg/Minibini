import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), patch: vi.fn() },
}));
vi.mock('svelte-spa-router', () => ({ push: vi.fn() }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import JobEditPage from '@/routes/jobs/JobEditPage.svelte';

const JOB = {
  job_id: 7, job_number: 'JOB-7', name: 'Widget', description: '',
  customer_po_number: '', due_date: null, project_manager: null,
};

beforeEach(() => {
  user.set({ permissions: ['can_manage_jobs'] });
  api.patch.mockReset();
  api.patch.mockResolvedValue({});
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/jobs/')) return Promise.resolve({ ...JOB });
    if (url === '/api/auth/users/') return Promise.resolve([
      { id: 1, username: 'alice', name: 'Alice Anderson' },
      { id: 2, username: 'bob', name: 'Bob Brown' },
    ]);
    return Promise.resolve({});
  });
});

describe('JobEditPage project manager', () => {
  it('lists active users and patches the chosen project_manager', async () => {
    const { getByLabelText } = render(JobEditPage, { props: { params: { id: '7' } } });
    const select = await waitFor(() => getByLabelText(/Project Manager/i));
    await fireEvent.change(select, { target: { value: '2' } });
    await fireEvent.submit(select.closest('form'));
    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        '/api/jobs/7/',
        expect.objectContaining({ project_manager: 2 }),
      );
    });
  });

  it('sends null project_manager when blank is chosen', async () => {
    api.get.mockImplementationOnce(() => Promise.resolve({ ...JOB, project_manager: 1 }));
    const { getByLabelText } = render(JobEditPage, { props: { params: { id: '7' } } });
    const select = await waitFor(() => getByLabelText(/Project Manager/i));
    await fireEvent.change(select, { target: { value: '' } });
    await fireEvent.submit(select.closest('form'));
    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        '/api/jobs/7/',
        expect.objectContaining({ project_manager: null }),
      );
    });
  });
});
