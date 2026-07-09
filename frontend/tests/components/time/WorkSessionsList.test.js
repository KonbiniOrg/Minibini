import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));
vi.mock('@/stores/blepActivity.js', async () => {
  const { writable } = await import('svelte/store');
  return { blepActivityVersion: writable(0), notifyBlepChanged: vi.fn() };
});

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import WorkSessionsList from '@/components/time/WorkSessionsList.svelte';

const row = (id, over = {}) => ({
  blep_id: id, user: 2, user_name: 'Wanda',
  task: 4, task_name: 'Cut', job_id: 3, job_number: 'JOB-3', job_name: 'W',
  start_time: '2026-03-01T14:00:00', end_time: '2026-03-01T15:00:00',
  ...over,
});

beforeEach(() => {
  api.get.mockReset();
  user.set({ id: 1, permissions: [] });
});

describe('WorkSessionsList', () => {
  it('lists sessions with the worker column when showWorker is set', async () => {
    api.get.mockResolvedValue({ count: 1, results: [row(1)] });
    const { findByText, getByText } = render(WorkSessionsList, {
      props: { showWorker: true },
    });
    expect(await findByText('Cut')).toBeInTheDocument();
    expect(getByText('Wanda')).toBeInTheDocument();
    expect(getByText('Worker')).toBeInTheDocument();
  });

  it('suppresses the worker column by default (single-user surfaces)', async () => {
    api.get.mockResolvedValue({ count: 1, results: [row(1)] });
    const { findByText, queryByText } = render(WorkSessionsList);
    await findByText('Cut');
    expect(queryByText('Worker')).toBeNull();
  });

  it('scopes the fetch to the given user', async () => {
    api.get.mockResolvedValue({ count: 0, results: [] });
    render(WorkSessionsList, { props: { userId: 7 } });
    await waitFor(() => {
      expect(api.get.mock.calls[0][0]).toContain('user=7');
    });
  });

  it('pages recent-first through the pager', async () => {
    api.get.mockResolvedValue({ count: 60, results: [row(1)] });
    const { findByText, getByRole, queryByRole } = render(WorkSessionsList, {
      props: { showWorker: true },
    });
    await findByText('Cut');
    expect(api.get.mock.calls[0][0]).toContain('page=1');
    // Page 1: no Previous.
    expect(queryByRole('button', { name: 'Previous' })).toBeNull();
    await fireEvent.click(getByRole('button', { name: 'Next' }));
    await waitFor(() => {
      expect(api.get.mock.calls.some(([u]) => u.includes('page=2'))).toBe(true);
    });
    expect(getByRole('button', { name: 'Previous' })).toBeInTheDocument();
  });

  it('hides the pager when paginate is off (home surface)', async () => {
    api.get.mockResolvedValue({ count: 60, results: [row(1)] });
    const { findByText, queryByRole } = render(WorkSessionsList, {
      props: { paginate: false },
    });
    await findByText('Cut');
    expect(queryByRole('button', { name: 'Next' })).toBeNull();
  });

  it('offers Edit on anyone\'s row to a can_manage_time manager', async () => {
    user.set({ id: 1, permissions: ['can_manage_time'] });
    api.get.mockResolvedValue({ count: 1, results: [row(1)] });
    const { findByRole } = render(WorkSessionsList, {
      props: { showWorker: true },
    });
    expect(await findByRole('button', { name: 'Edit' })).toBeInTheDocument();
  });

  it('offers Request Edit only on the user\'s own aged rows', async () => {
    user.set({ id: 2, permissions: [] });
    api.get.mockResolvedValue({
      count: 2,
      results: [
        row(1, { user: 2 }),          // own, old → Request Edit
        row(2, { user: 9, user_name: 'Other' }),  // someone else's → nothing
      ],
    });
    const { findAllByRole, queryAllByRole } = render(WorkSessionsList, {
      props: { showWorker: true },
    });
    const requests = await findAllByRole('button', { name: 'Request Edit' });
    expect(requests).toHaveLength(1);
    expect(queryAllByRole('button', { name: 'Edit' })).toHaveLength(0);
  });

  it('shows the empty state', async () => {
    api.get.mockResolvedValue({ count: 0, results: [] });
    const { findByText } = render(WorkSessionsList, {
      props: { emptyText: 'No work sessions.' },
    });
    expect(await findByText('No work sessions.')).toBeInTheDocument();
  });
});
