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
  can_manage: true,
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

  it('renders the edit form for a PM when job.can_manage is true without the global atom', async () => {
    user.set({ permissions: [] }); // project manager lacks the can_manage_jobs atom
    const { getByLabelText } = render(JobEditPage, { props: { params: { id: '7' } } });
    const nameInput = await waitFor(() => getByLabelText(/Name/i));
    expect(nameInput).toBeInTheDocument();
    // PM may reassign the PM field on their own job
    expect(getByLabelText(/Project Manager/i)).toBeInTheDocument();
  });

  it('renders field validation errors under inputs and non_field_errors in the footer', async () => {
    api.patch.mockRejectedValue({
      status: 400,
      data: { name: ['Ensure this field has no more than 50 characters.'], non_field_errors: ['Bad combination.'] },
    });
    const { getByLabelText, findByText } = render(JobEditPage, { props: { params: { id: '7' } } });
    const nameInput = await waitFor(() => getByLabelText(/Name/i));
    await fireEvent.submit(nameInput.closest('form'));
    expect(await findByText('Ensure this field has no more than 50 characters.')).toBeInTheDocument();
    const footer = await findByText('Bad combination.');
    expect(footer.closest('[role="alert"]')).not.toBeNull();
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
