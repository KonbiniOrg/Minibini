import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import TaskDetailPage from '@/routes/jobs/TaskDetailPage.svelte';

// The fetched task carries can_manage = "atom-holder OR this job's PM". The page
// gates its edit-task / assign affordances on task.can_manage alone (not the
// global atom). These tests set the global atom to false (worker) to prove the
// per-object flag is what drives the affordances.
function mockApi(taskOverrides = {}) {
  const task = {
    task_id: 7, name: 'Mill', status: 'pending', job: { id: 3 },
    assignee_name: null, est_qty: '2', effective_rate: '25', scheme_unit_label: 'hr',
    ...taskOverrides,
  };
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/tasks/7/')) {
      if (url.includes('/materials')) return Promise.resolve([]);
      if (url.includes('/subtasks')) return Promise.resolve([]);
      return Promise.resolve(task);
    }
    if (url.startsWith('/api/jobs/3/')) return Promise.resolve({ job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress' });
    if (url.startsWith('/api/bleps/')) return Promise.resolve([]);
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve([]);
    if (url.startsWith('/api/service-items/')) return Promise.resolve([]);
    if (url.startsWith('/api/contacts/')) return Promise.resolve({});
    return Promise.resolve([]);
  });
}

beforeEach(() => {
  // Worker (no atom): proves gating is driven by task.can_manage, not the atom.
  user.set({ id: 99, permissions: [] });
});

describe('TaskDetailPage per-job can_manage', () => {
  it('shows edit/assign affordances when task.can_manage is true (atom absent)', async () => {
    mockApi({ can_manage: true });
    const { getByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await waitFor(() => expect(getByRole('button', { name: /edit task/i })).toBeInTheDocument());
    expect(getByRole('button', { name: 'assign' })).toBeInTheDocument();
  });

  it('shows edit task even when task.can_manage is false (edit is open to all)', async () => {
    mockApi({ can_manage: false });
    const { findByText, getByRole, queryByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findByText('Task: Mill');
    // edit task is now open to any authenticated user
    expect(getByRole('button', { name: /edit task/i })).toBeInTheDocument();
    // assign remains manager/PM-only
    expect(queryByRole('button', { name: 'assign' })).toBeNull();
  });
});
