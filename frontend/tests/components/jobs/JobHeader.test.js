import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, within } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { patch: vi.fn(), post: vi.fn(), get: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));
vi.mock('svelte-spa-router', () => ({ push: vi.fn() }));

import { get } from 'svelte/store';
import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import JobHeader from '@/components/jobs/JobHeader.svelte';

const job = { job_id: 5, job_number: 'JOB-5', name: 'Widget', status: 'in_progress', can_manage: true };

function optionValues(select) {
  return [...select.options].map((o) => o.value);
}

function optionLabels(select) {
  return [...select.options].map((o) => o.textContent.trim());
}

beforeEach(() => {
  api.patch.mockReset();
  api.patch.mockResolvedValue({});
  api.post.mockReset();
  api.post.mockResolvedValue({});
  api.get.mockReset();
  api.get.mockResolvedValue([]);
  user.set({ permissions: ['can_manage_jobs'] });
  clearMessage();
});

describe('JobHeader status pill', () => {
  it('patches a direct status change', async () => {
    const onStatusChange = vi.fn();
    const { getByRole } = render(JobHeader, { props: { job, onStatusChange } });
    await fireEvent.change(getByRole('combobox'), { target: { value: 'work_complete' } });
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/5/', { status: 'work_complete' });
  });

  it('offers Hold as a trigger that opens the reason modal instead of patching', async () => {
    const { getByRole, getByLabelText } = render(JobHeader, { props: { job } });
    await fireEvent.change(getByRole('combobox'), { target: { value: '__hold' } });
    // no status patch, no hold call yet — the reason modal appears
    expect(api.patch).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
    await fireEvent.input(getByLabelText(/Reason for hold/), { target: { value: 'broken jig' } });
    await fireEvent.click(getByRole('button', { name: 'Confirm Hold' }));
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/hold/', { reason: 'broken jig' });
  });

  it('snaps the pill back to the current status while the hold modal is open', async () => {
    const { getByRole } = render(JobHeader, { props: { job } });
    const select = getByRole('combobox');
    await fireEvent.change(select, { target: { value: '__hold' } });
    expect(select.value).toBe('in_progress');
  });

  it('labels the approved→in_progress transition "Release to floor" and patches it directly', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm');
    const approvedJob = { ...job, status: 'approved' };
    const { getByRole } = render(JobHeader, { props: { job: approvedJob } });
    const select = getByRole('combobox');
    expect(optionLabels(select)).toContain('Release to floor');
    await fireEvent.change(select, { target: { value: 'in_progress' } });
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/5/', { status: 'in_progress' });
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('does not offer Hold for pre-approval jobs', () => {
    const draftJob = { ...job, status: 'draft' };
    const { getByRole } = render(JobHeader, { props: { job: draftJob } });
    expect(optionValues(getByRole('combobox'))).not.toContain('__hold');
  });

  it('shows HOLD (not the true status) plus the reason when held, and releases via the pill', async () => {
    const heldJob = { ...job, on_hold: true, hold_reason: 'waiting on CO' };
    const { getByRole, getByText, queryByText } = render(JobHeader, { props: { job: heldJob } });
    const select = getByRole('combobox');
    expect(select.selectedOptions[0].textContent.trim()).toBe('HOLD');
    expect(queryByText('In Progress')).toBeNull();
    expect(getByText(/waiting on CO/)).toBeInTheDocument();
    expect(optionValues(select)).toEqual(expect.arrayContaining(['__release_hold', 'cancelled']));
    await fireEvent.change(select, { target: { value: '__release_hold' } });
    expect(api.post).toHaveBeenCalledWith('/api/jobs/5/release/', {});
    expect(api.patch).not.toHaveBeenCalled();
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

  it('shows a hold failure in the modal form message, not the overlay', async () => {
    api.post.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 400,
      data: { detail: 'Hold not allowed right now.' },
    }));
    const { getByRole, getByLabelText, findByRole } = render(JobHeader, { props: { job } });
    await fireEvent.change(getByRole('combobox'), { target: { value: '__hold' } });
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

  it('shows a read-only HOLD badge when a held job is not manageable', () => {
    user.set({ permissions: [] });
    const heldJob = { ...job, on_hold: true, hold_reason: 'waiting', can_manage: false };
    const { getByText, queryByText } = render(JobHeader, { props: { job: heldJob } });
    expect(getByText('HOLD')).toBeInTheDocument();
    expect(queryByText('In Progress')).toBeNull();
  });
});

describe('JobHeader direct-approval gate (has_estimates)', () => {
  it('hides Approved on a submitted job that has estimates', () => {
    const submitted = { ...job, status: 'submitted', has_estimates: true };
    const { getByRole } = render(JobHeader, { props: { job: submitted } });
    const values = optionValues(getByRole('combobox'));
    expect(values).not.toContain('approved');
    expect(values).toContain('rejected');
  });

  it('offers Approved on a submitted estimate-less job', () => {
    const submitted = { ...job, status: 'submitted', has_estimates: false };
    const { getByRole } = render(JobHeader, { props: { job: submitted } });
    expect(optionValues(getByRole('combobox'))).toContain('approved');
  });
});

describe('JobHeader in-flight transition guard', () => {
  it('ignores a second change while the first PATCH is in flight', async () => {
    let resolvePatch;
    api.patch.mockImplementation(
      () => new Promise((resolve) => { resolvePatch = resolve; }));
    const submitted = { ...job, status: 'submitted', has_estimates: false };
    const { getByRole } = render(JobHeader, { props: { job: submitted } });
    const select = getByRole('combobox');
    await fireEvent.change(select, { target: { value: 'approved' } });
    // A stray second change (double-click / re-fired event) before the first
    // PATCH settles must not fire a second transition.
    await fireEvent.change(select, { target: { value: 'rejected' } });
    expect(api.patch).toHaveBeenCalledTimes(1);
    resolvePatch({});
  });

  it('disables the select while a transition is in flight', async () => {
    let resolvePatch;
    api.patch.mockImplementation(
      () => new Promise((resolve) => { resolvePatch = resolve; }));
    const { getByRole } = render(JobHeader, { props: { job } });
    const select = getByRole('combobox');
    await fireEvent.change(select, { target: { value: 'work_complete' } });
    expect(select.disabled).toBe(true);
    resolvePatch({});
    await vi.waitFor(() => expect(select.disabled).toBe(false));
  });
});

describe('JobHeader Edit/Duplicate', () => {
  it('offers Edit and Duplicate buttons when manageable, and no History link or Actions menu', () => {
    const { getByRole, queryByRole } = render(JobHeader, { props: { job } });
    expect(getByRole('button', { name: 'Edit' })).toBeInTheDocument();
    expect(getByRole('button', { name: /Duplicate/ })).toBeInTheDocument();
    expect(queryByRole('button', { name: 'Actions' })).toBeNull();
    expect(queryByRole('link', { name: 'History' })).toBeNull();
  });

  it('hides Edit/Duplicate when not manageable', () => {
    user.set({ permissions: [] });
    const readOnlyJob = { ...job, can_manage: false };
    const { queryByRole } = render(JobHeader, { props: { job: readOnlyJob } });
    expect(queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(queryByRole('button', { name: /Duplicate/ })).toBeNull();
  });

  it('opens the edit dialog, prefilled with the job name, when Edit is clicked', async () => {
    const { getByRole, findByRole } = render(JobHeader, { props: { job } });
    await fireEvent.click(getByRole('button', { name: 'Edit' }));
    const dialog = await findByRole('dialog', { name: 'Edit job' });
    expect(within(dialog).getByLabelText(/Name/i).value).toBe('Widget');
  });

  it('opens the duplicate dialog when Duplicate… is clicked', async () => {
    const { getByRole, findByRole } = render(JobHeader, { props: { job } });
    await fireEvent.click(getByRole('button', { name: /Duplicate/ }));
    const dialog = await findByRole('dialog', { name: 'Duplicate job' });
    expect(within(dialog).getByText(/Duplicate JOB-5/)).toBeInTheDocument();
  });
});

describe('JobHeader facts line (dates + PO + PM)', () => {
  it('shows started and due dates', () => {
    const datedJob = { ...job, start_date: '2026-05-12', due_date: '2026-06-30' };
    const { getByText } = render(JobHeader, { props: { job: datedJob } });
    expect(getByText(/Started/)).toBeInTheDocument();
    expect(getByText(/Due/)).toBeInTheDocument();
  });

  it('shows the completed date for closed jobs', () => {
    const closedJob = {
      ...job, status: 'completed',
      start_date: '2026-05-12', completed_date: '2026-07-01',
    };
    const { getByText } = render(JobHeader, { props: { job: closedJob } });
    expect(getByText(/Started/)).toBeInTheDocument();
    expect(getByText(/Completed \d/)).toBeInTheDocument();
  });
});

describe('JobHeader financial rollups', () => {
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

describe('JobHeader project manager', () => {
  it('links the PM name to the PM-filtered job list', () => {
    const pmJob = { ...job, project_manager: 3, project_manager_name: 'Carol Cole' };
    const { getByRole } = render(JobHeader, { props: { job: pmJob } });
    const link = getByRole('link', { name: 'Carol Cole' });
    expect(link).toHaveAttribute('href', '#/jobs?pm=3');
  });

  it('renders no PM segment when unassigned', () => {
    const { queryByText } = render(JobHeader, { props: { job } });
    expect(queryByText(/PM:/)).toBeNull();
  });
});

describe('JobHeader per-job can_manage gating', () => {
  it('shows edit affordances + status dropdown when job.can_manage is true even without the global atom', () => {
    user.set({ permissions: [] }); // no can_manage_jobs atom
    const pmJob = { ...job, can_manage: true };
    const { getByRole } = render(JobHeader, { props: { job: pmJob } });
    expect(getByRole('combobox')).toBeInTheDocument();
    expect(getByRole('button', { name: 'Edit' })).toBeInTheDocument();
  });

  it('hides edit affordances + status dropdown when job.can_manage is false even with the global atom', () => {
    user.set({ permissions: ['can_manage_jobs'] });
    const lockedJob = { ...job, can_manage: false };
    const { queryByRole } = render(JobHeader, { props: { job: lockedJob } });
    expect(queryByRole('combobox')).toBeNull();
    expect(queryByRole('button', { name: 'Edit' })).toBeNull();
  });

  it('offers Release to floor in the pill for an approved job when job.can_manage is true', () => {
    user.set({ permissions: [] });
    const approvedPmJob = { ...job, status: 'approved', can_manage: true };
    const { getByRole } = render(JobHeader, { props: { job: approvedPmJob } });
    expect(optionLabels(getByRole('combobox'))).toContain('Release to floor');
  });
});
