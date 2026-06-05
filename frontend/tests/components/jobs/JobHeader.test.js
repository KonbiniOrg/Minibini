import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import JobHeader from '@/components/jobs/JobHeader.svelte';

const job = { job_id: 5, job_number: 'JOB-5', name: 'Widget', status: 'in_progress' };

beforeEach(() => {
  api.patch.mockReset();
  api.patch.mockResolvedValue({});
  user.set({ permissions: ['can_manage_jobs'] });
});

describe('JobHeader', () => {
  it('patches a direct status change', async () => {
    const onStatusChange = vi.fn();
    const { getByRole } = render(JobHeader, { props: { job, onStatusChange } });
    await fireEvent.change(getByRole('combobox'), { target: { value: 'work_complete' } });
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/5/', { status: 'work_complete' });
  });

  it('requires a reason when putting a job on hold', async () => {
    const { getByRole, getByLabelText } = render(JobHeader, { props: { job } });
    await fireEvent.change(getByRole('combobox'), { target: { value: 'on_hold' } });
    // no immediate patch — the reason form appears
    expect(api.patch).not.toHaveBeenCalled();
    await fireEvent.input(getByLabelText(/Reason for hold/), { target: { value: 'broken jig' } });
    await fireEvent.click(getByRole('button', { name: 'Confirm Hold' }));
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/5/', { status: 'on_hold', hold_reason: 'broken jig' });
  });

  it('shows a read-only badge without the jobs permission', () => {
    user.set({ permissions: [] });
    const { getByText, queryByRole } = render(JobHeader, { props: { job } });
    expect(getByText('In Progress')).toBeInTheDocument();
    expect(queryByRole('combobox')).toBeNull();
  });
});
