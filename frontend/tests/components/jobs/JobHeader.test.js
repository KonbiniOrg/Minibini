import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import JobHeader from '@/components/jobs/JobHeader.svelte';

const job = { job_id: 5, job_number: 'JOB-5', name: 'Widget', status: 'in_progress', can_manage: true };

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

  it('releases an approved job to the floor without prompting (reversible via on-hold)', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm');
    const onStatusChange = vi.fn();
    const approvedJob = { ...job, status: 'approved', tasks: [{ task_id: 1 }] };
    const { getByRole } = render(JobHeader, { props: { job: approvedJob, onStatusChange } });
    await fireEvent.click(getByRole('button', { name: 'Release to floor' }));
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/5/', { status: 'in_progress' });
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('disables Release to floor when the approved job has no tasks', () => {
    const approvedNoTasks = { ...job, status: 'approved', tasks: [] };
    const { getByRole } = render(JobHeader, { props: { job: approvedNoTasks } });
    expect(getByRole('button', { name: 'Release to floor' })).toBeDisabled();
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
