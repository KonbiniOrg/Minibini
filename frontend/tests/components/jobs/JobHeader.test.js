import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { patch: vi.fn(), post: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));

import { get } from 'svelte/store';
import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import JobHeader from '@/components/jobs/JobHeader.svelte';

const job = { job_id: 5, job_number: 'JOB-5', name: 'Widget', status: 'in_progress', can_manage: true };

beforeEach(() => {
  api.patch.mockReset();
  api.patch.mockResolvedValue({});
  api.post.mockReset();
  api.post.mockResolvedValue({});
  user.set({ permissions: ['can_manage_jobs'] });
  clearMessage();
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
    await fireEvent.click(getByRole('button', { name: 'Put on hold' }));
    // no immediate call — the reason form appears
    expect(api.post).not.toHaveBeenCalled();
    await fireEvent.input(getByLabelText(/Reason for hold/), { target: { value: 'broken jig' } });
    await fireEvent.click(getByRole('button', { name: 'Confirm Hold' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/hold/', { reason: 'broken jig' });
  });

  it('no longer offers On Hold in the status select', () => {
    const { getByRole } = render(JobHeader, { props: { job } });
    const options = [...getByRole('combobox').options].map((o) => o.value);
    expect(options).not.toContain('on_hold');
  });

  it('shows the hold badge + reason and releases via the release action', async () => {
    const onStatusChange = vi.fn();
    const heldJob = { ...job, on_hold: true, hold_reason: 'waiting on CO' };
    const { getByRole, getByText } = render(JobHeader, { props: { job: heldJob, onStatusChange } });
    expect(getByText('On Hold')).toBeInTheDocument();
    expect(getByText('waiting on CO')).toBeInTheDocument();
    await fireEvent.click(getByRole('button', { name: 'Release hold' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/release/', {});
  });

  it('hides the Put on hold button for pre-approval and held jobs', () => {
    const draftJob = { ...job, status: 'draft' };
    const { queryByRole, rerender } = render(JobHeader, { props: { job: draftJob } });
    expect(queryByRole('button', { name: 'Put on hold' })).toBeNull();
  });

  it('releases an approved job to the floor without prompting (reversible via on-hold)', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm');
    const onStatusChange = vi.fn();
    const approvedJob = { ...job, status: 'approved' };
    const { getByRole } = render(JobHeader, { props: { job: approvedJob, onStatusChange } });
    await fireEvent.click(getByRole('button', { name: 'Release to floor' }));
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/5/', { status: 'in_progress' });
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('raises the global error overlay when a direct status change fails', async () => {
    api.patch.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 400,
      data: { detail: 'Invalid transition.' },
    }));
    const { getByRole } = render(JobHeader, { props: { job } });
    await fireEvent.change(getByRole('combobox'), { target: { value: 'work_complete' } });
    await vi.waitFor(() => {
      expect(get(overlayMessage)).toEqual({ kind: 'error', text: 'Invalid transition.' });
    });
  });

  it('shows a hold failure in the hold form message, not the overlay', async () => {
    api.post.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 400,
      data: { detail: 'Hold not allowed right now.' },
    }));
    const { getByRole, getByLabelText, findByRole } = render(JobHeader, { props: { job } });
    await fireEvent.click(getByRole('button', { name: 'Put on hold' }));
    await fireEvent.input(getByLabelText(/Reason for hold/), { target: { value: 'broken jig' } });
    await fireEvent.click(getByRole('button', { name: 'Confirm Hold' }));
    const msg = await findByRole('alert');
    expect(msg.textContent).toContain('Hold not allowed right now.');
    expect(get(overlayMessage)).toBeNull();
  });

  it('shows a read-only badge when the job is not manageable', () => {
    user.set({ permissions: [] });
    const readOnlyJob = { ...job, can_manage: false };
    const { getByText, queryByRole } = render(JobHeader, { props: { job: readOnlyJob } });
    expect(getByText('In Progress')).toBeInTheDocument();
    expect(queryByRole('combobox')).toBeNull();
  });

  describe('financial rollups', () => {
    it('renders the four amounts as currency', () => {
      const finJob = {
        ...job,
        estimated_amount: '1000.00',
        spent_amount: '250.00',
        invoiced_amount: '400.00',
        profit_amount: '150.00',
      };
      const { getByText } = render(JobHeader, { props: { job: finJob } });
      expect(getByText('$1,000.00')).toBeInTheDocument();
      expect(getByText('$250.00')).toBeInTheDocument();
      expect(getByText('$400.00')).toBeInTheDocument();
      expect(getByText('$150.00')).toBeInTheDocument();
      // The repurposed header no longer has a Billable column.
      expect(getByText('Profit')).toBeInTheDocument();
    });

    it('falls back to a dash when amounts are absent (e.g. list payloads)', () => {
      const { getAllByText } = render(JobHeader, { props: { job } });
      // All four cells show the placeholder.
      expect(getAllByText('$—').length).toBe(4);
    });

    it('shows a negative profit (unbilled work) with its own styling', () => {
      const finJob = { ...job, profit_amount: '-50.00' };
      const { getByText } = render(JobHeader, { props: { job: finJob } });
      expect(getByText('-$50.00')).toBeInTheDocument();
    });
  });
});

describe('JobHeader project manager', () => {
  it('links the PM name to the PM-filtered job list', () => {
    const pmJob = { ...job, project_manager: 3, project_manager_name: 'Carol Cole' };
    const { getByRole } = render(JobHeader, { props: { job: pmJob } });
    const link = getByRole('link', { name: 'Carol Cole' });
    expect(link).toHaveAttribute('href', '#/jobs?pm=3');
  });

  it('renders no PM link when unassigned', () => {
    const { queryByText } = render(JobHeader, { props: { job } });
    expect(queryByText(/Project manager/i)).toBeNull();
  });
});

describe('JobHeader per-job can_manage gating', () => {
  it('shows edit affordances + status dropdown when job.can_manage is true even without the global atom', () => {
    user.set({ permissions: [] }); // no can_manage_jobs atom
    const pmJob = { ...job, can_manage: true };
    const { getByText, getByRole } = render(JobHeader, { props: { job: pmJob } });
    expect(getByText('edit')).toBeInTheDocument();
    expect(getByRole('combobox')).toBeInTheDocument();
  });

  it('hides edit affordances + status dropdown when job.can_manage is false even with the global atom', () => {
    user.set({ permissions: ['can_manage_jobs'] });
    const lockedJob = { ...job, can_manage: false };
    const { queryByText, queryByRole } = render(JobHeader, { props: { job: lockedJob } });
    expect(queryByText('edit')).toBeNull();
    expect(queryByRole('combobox')).toBeNull();
  });

  it('shows Release to floor for an approved job when job.can_manage is true', () => {
    user.set({ permissions: [] });
    const approvedPmJob = { ...job, status: 'approved', can_manage: true };
    const { getByRole } = render(JobHeader, { props: { job: approvedPmJob } });
    expect(getByRole('button', { name: 'Release to floor' })).toBeInTheDocument();
  });
});
