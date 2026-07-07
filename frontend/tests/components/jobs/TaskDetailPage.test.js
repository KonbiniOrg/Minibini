import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), patch: vi.fn(), post: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
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

describe('TaskDetailPage entered-qty add field', () => {
  const enteredQty = {
    scheme_algorithm: 'entered_qty', scheme_name: 'Press',
    scheme_unit_label: 'pcs', actual_qty: '9.00', status: 'in_progress',
  };

  beforeEach(() => {
    api.post.mockReset();
    api.post.mockResolvedValue({ actual_qty: '14.00' });
  });

  it('shows the running total with units', async () => {
    mockApi(enteredQty);
    const { findByText, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findByText('Task: Mill');
    expect(getByText(/Actual so far/)).toBeInTheDocument();
    expect(getByText(/9.00 pcs/)).toBeInTheDocument();
  });

  it('posts a signed add and clears the input', async () => {
    mockApi(enteredQty);
    const { findByText, getByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findByText('Task: Mill');
    const input = getByRole('spinbutton', { name: /add/i });
    await fireEvent.input(input, { target: { value: '-2' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/tasks/7/actual-qty/add/', { actual_qty: -2 });
    });
    await waitFor(() => expect(input.value).toBe(''));
  });

  it('never saves on blur — adds are not idempotent', async () => {
    mockApi(enteredQty);
    const { findByText, getByRole } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findByText('Task: Mill');
    const input = getByRole('spinbutton', { name: /add/i });
    await fireEvent.input(input, { target: { value: '5' } });
    await fireEvent.blur(input);
    const addCalls = api.post.mock.calls.filter(([url]) => url.includes('actual-qty/add'));
    expect(addCalls).toHaveLength(0);
  });

  it('rejects a zero delta without posting', async () => {
    mockApi(enteredQty);
    const { findByText, getByRole, getByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findByText('Task: Mill');
    await fireEvent.input(getByRole('spinbutton', { name: /add/i }), { target: { value: '0' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(getByText(/non-zero/i)).toBeInTheDocument();
    const addCalls = api.post.mock.calls.filter(([url]) => url.includes('actual-qty/add'));
    expect(addCalls).toHaveLength(0);
  });
});

describe('TaskDetailPage prompt modals vs background refetch', () => {
  it('keeps an open prompt modal through a blep-change broadcast (no page blank)', async () => {
    // Real blepActivity store (not mocked): a broadcast (e.g. a band stop
    // finishing elsewhere) makes the page refetch. That refetch must NOT
    // blank the page ("Loading…") and remount TaskActions — that would
    // destroy any open prompt modal. Regression caught by driving the
    // real app; invariants documented in jobs-tasks-and-worksheets §10.1a.
    mockApi({ scheme_algorithm: 'entered_qty', scheme_name: 'Press',
              scheme_unit_label: 'pcs', actual_qty: '9.00',
              status: 'in_progress' });
    api.post.mockReset();
    api.post.mockResolvedValue({ needs_actual_qty: true,
                                 unit_label: 'pcs', current_qty: '9.00' });
    const { findByText, getByRole, findByRole, queryByText } = render(TaskDetailPage, {
      props: { params: { id: 3, taskId: 7 } },
    });
    await findByText('Task: Mill');
    await fireEvent.click(getByRole('button', { name: 'Complete' }));
    await findByRole('heading', { name: 'Settle up quantity' });
    const { notifyBlepChanged } = await import('@/stores/blepActivity.js');
    await notifyBlepChanged();
    await new Promise((r) => setTimeout(r, 100));
    expect(queryByText('Loading…')).toBeNull();
    expect(getByRole('heading', { name: 'Settle up quantity' })).toBeInTheDocument();
  });
});

describe('TaskDetailPage toolbar Start Work', () => {
  it('starts work from the toolbar button (relocated next to edit task)', async () => {
    mockApi({ status: 'pending' });
    api.post.mockReset();
    api.post.mockResolvedValue({ status: 'ok', blep_id: 1 });
    const { findByText, getByRole } = render(TaskDetailPage, {
      props: { params: { id: 3, taskId: 7 } },
    });
    await findByText('Task: Mill');
    await fireEvent.click(getByRole('button', { name: 'Start Work' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/7/start-work/', {});
  });

  it('shows no start/stop controls while the user bleps this task — the band is the stop surface', async () => {
    const { currentBlep } = await import('@/stores/currentBlep.js');
    currentBlep.set({
      id: 9, task: { id: 7, name: 'Mill' },
      start_time: new Date(Date.now() - 30 * 60000).toISOString(),
      blep_minimum_minutes: 1,
    });
    mockApi({ status: 'in_progress' });
    const { findByText, queryByRole } = render(TaskDetailPage, {
      props: { params: { id: 3, taskId: 7 } },
    });
    await findByText('Task: Mill');
    expect(queryByRole('button', { name: 'Start Work' })).toBeNull();
    expect(queryByRole('button', { name: 'Stop Work' })).toBeNull();
    currentBlep.set(null);
  });
});

describe('TaskDetailPage does not refetch in a loop', () => {
  it('fetch count stabilizes after load', async () => {
    // Regression: loadTask read `task` ($state) synchronously inside the
    // mount $effect, making the effect depend on `task` — which loadTask
    // itself reassigns → infinite refetch loop at network speed. The
    // mock stops answering after 20 task fetches so a looping page
    // fails the count assertion instead of starving the test runner.
    mockApi({ can_manage: true });
    const inner = api.get.getMockImplementation();
    let taskFetches = 0;
    api.get.mockImplementation((url) => {
      if (url === '/api/tasks/7/') {
        taskFetches += 1;
        if (taskFetches > 20) return new Promise(() => {});
      }
      return inner(url);
    });
    const { findByText } = render(TaskDetailPage, { props: { params: { id: 3, taskId: 7 } } });
    await findByText('Task: Mill');
    await new Promise((r) => setTimeout(r, 250));
    expect(taskFetches).toBeLessThan(5);
  });
});
