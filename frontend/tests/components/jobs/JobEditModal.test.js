import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), patch: vi.fn() },
}));

import { api } from '@/lib/api.js';
import JobEditModal from '@/components/jobs/JobEditModal.svelte';

const JOB = {
  job_id: 7, job_number: 'JOB-7', name: 'Widget', description: '',
  customer_po_number: '', due_date: null, project_manager: null,
  can_manage: true,
};

beforeEach(() => {
  api.patch.mockReset();
  api.patch.mockResolvedValue({});
  api.get.mockReset();
  api.get.mockResolvedValue([
    { id: 1, username: 'alice', name: 'Alice Anderson' },
    { id: 2, username: 'bob', name: 'Bob Brown' },
  ]);
});

describe('JobEditModal', () => {
  it('prefills from the job prop when opened', async () => {
    const { getByLabelText } = render(JobEditModal, { props: { job: JOB, open: true } });
    const nameInput = await waitFor(() => getByLabelText(/Name/i));
    expect(nameInput.value).toBe('Widget');
  });

  it('lists active users and patches the chosen project_manager', async () => {
    const { getByLabelText } = render(JobEditModal, { props: { job: JOB, open: true } });
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
    const { getByLabelText } = render(JobEditModal, {
      props: { job: { ...JOB, project_manager: 1 }, open: true },
    });
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

  it('calls onSaved on a successful save', async () => {
    const onSaved = vi.fn();
    const { getByLabelText } = render(JobEditModal, { props: { job: JOB, open: true, onSaved } });
    const nameInput = await waitFor(() => getByLabelText(/Name/i));
    await fireEvent.submit(nameInput.closest('form'));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it('renders field validation errors under inputs and non_field_errors in the footer', async () => {
    api.patch.mockRejectedValue({
      status: 400,
      data: { name: ['Ensure this field has no more than 50 characters.'], non_field_errors: ['Bad combination.'] },
    });
    const { getByLabelText, findByText } = render(JobEditModal, { props: { job: JOB, open: true } });
    const nameInput = await waitFor(() => getByLabelText(/Name/i));
    await fireEvent.submit(nameInput.closest('form'));
    expect(await findByText('Ensure this field has no more than 50 characters.')).toBeInTheDocument();
    const footer = await findByText('Bad combination.');
    expect(footer.closest('[role="alert"]')).not.toBeNull();
  });

  it('does not fetch the user list when the job is not manageable', async () => {
    render(JobEditModal, { props: { job: { ...JOB, can_manage: false }, open: true } });
    await waitFor(() => {
      expect(api.get).not.toHaveBeenCalled();
    });
  });

  it('re-prefills from a new job when reopened', async () => {
    const { getByLabelText, rerender } = render(JobEditModal, { props: { job: JOB, open: true } });
    await waitFor(() => getByLabelText(/Name/i));
    await rerender({ job: JOB, open: false });
    const otherJob = { ...JOB, job_id: 8, job_number: 'JOB-8', name: 'Gadget' };
    await rerender({ job: otherJob, open: true });
    await waitFor(() => expect(getByLabelText(/Name/i).value).toBe('Gadget'));
  });
});
