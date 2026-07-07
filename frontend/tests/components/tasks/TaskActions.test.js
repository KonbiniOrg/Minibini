import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { post: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));
vi.mock('@/stores/blepActivity.js', () => ({ notifyBlepChanged: vi.fn() }));

import { get } from 'svelte/store';
import { api } from '@/lib/api.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import TaskActions from '@/components/tasks/TaskActions.svelte';

beforeEach(() => {
  api.post.mockReset();
  api.post.mockResolvedValue({});
  clearMessage();
});

describe('TaskActions', () => {
  it('starts work on a pending task', async () => {
    const { getByRole } = render(TaskActions, { props: { task: { task_id: 5, status: 'pending' }, user: { id: 1 } } });
    await fireEvent.click(getByRole('button', { name: 'Start Work' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/start-work/', {});
  });

  it('completes a task', async () => {
    const { getByRole } = render(TaskActions, { props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 } } });
    await fireEvent.click(getByRole('button', { name: 'Complete' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/complete/', {});
  });

  it('blocks a task with a reason from the prompt', async () => {
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('waiting on parts');
    const { getByRole } = render(TaskActions, { props: { task: { task_id: 5, status: 'pending' }, user: { id: 1 } } });
    await fireEvent.click(getByRole('button', { name: 'Block' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/block/', { reason: 'waiting on parts' });
    promptSpy.mockRestore();
  });

  it('unblocks a blocked task', async () => {
    const { getByRole } = render(TaskActions, { props: { task: { task_id: 5, status: 'blocked' }, user: { id: 1 } } });
    await fireEvent.click(getByRole('button', { name: 'Unblock' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/unblock/', {});
  });

  it('hides Cancel for a non-manager even on a cancel-eligible status', () => {
    // Cancel is manager/PM-only now (per-object can_manage). Without it, the
    // Cancel button is not rendered even though 'blocked' is cancel-eligible.
    const { queryByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'blocked' }, user: { id: 1 }, userPermissions: [], canManage: false },
    });
    expect(queryByRole('button', { name: 'Cancel' })).toBeNull();
  });

  it('shows and fires Cancel when canManage is true', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { getByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'blocked' }, user: { id: 1 }, userPermissions: [], canManage: true },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/cancel/', {});
    confirmSpy.mockRestore();
  });

  it('raises the global error overlay when an action fails', async () => {
    api.post.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 400,
      data: { detail: 'Task is already complete.' },
    }));
    const { getByRole, container } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'pending' }, user: { id: 1 } },
    });
    await fireEvent.click(getByRole('button', { name: 'Start Work' }));
    await vi.waitFor(() => {
      expect(get(overlayMessage)).toEqual({ kind: 'error', text: 'Task is already complete.' });
    });
    // No component-local error line anymore.
    expect(container.querySelector('.error')).toBeNull();
  });
});

// An over-minimum own session on this task, so Stop Work renders.
const activeBlep = () => ({
  start_time: new Date(Date.now() - 30 * 60000).toISOString(),
  blep_minimum_minutes: 1,
});

describe('TaskActions — stop-work session prompt', () => {
  it('opens the session modal on prompt_actual_qty and posts the add', async () => {
    api.post.mockImplementation((url) => {
      if (url.endsWith('/stop-work/')) {
        return Promise.resolve({ status: 'ok', prompt_actual_qty: true,
                                 unit_label: 'pcs', current_qty: '9' });
      }
      return Promise.resolve({});
    });
    const { getByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 },
               activeBlepOnThisTask: activeBlep() },
    });
    await fireEvent.click(getByRole('button', { name: 'Stop Work' }));
    const input = getByRole('spinbutton');
    await fireEvent.input(input, { target: { value: '5' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/actual-qty/add/',
                                          { actual_qty: 5 });
  });

  it('does not open a modal when stop has no prompt fields', async () => {
    api.post.mockResolvedValue({ status: 'ok' });
    const { getByRole, queryByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 },
               activeBlepOnThisTask: activeBlep() },
    });
    await fireEvent.click(getByRole('button', { name: 'Stop Work' }));
    expect(queryByRole('spinbutton')).toBeNull();
  });

  it('checkbox turns the submit into a single complete with add_qty', async () => {
    api.post.mockImplementation((url) => {
      if (url.endsWith('/stop-work/')) {
        return Promise.resolve({ status: 'ok', prompt_actual_qty: true,
                                 unit_label: 'pcs', current_qty: '9' });
      }
      return Promise.resolve({ status: 'complete' });
    });
    const { getByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 },
               activeBlepOnThisTask: activeBlep() },
    });
    await fireEvent.click(getByRole('button', { name: 'Stop Work' }));
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '5' } });
    await fireEvent.click(getByRole('checkbox'));
    await fireEvent.click(getByRole('button', { name: 'Add & complete' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/complete/',
                                          { add_qty: 5 });
    const addCalls = api.post.mock.calls.filter(
      ([url]) => url.includes('actual-qty/add'));
    expect(addCalls).toHaveLength(0);
  });

  it('keeps the modal open with the error when the checkbox complete fails', async () => {
    api.post.mockImplementation((url) => {
      if (url.endsWith('/stop-work/')) {
        return Promise.resolve({ status: 'ok', prompt_actual_qty: true,
                                 unit_label: 'pcs', current_qty: '9' });
      }
      if (url.endsWith('/complete/')) {
        return Promise.reject(Object.assign(new Error('fail'), {
          status: 400, data: { detail: 'Cannot complete: unconsumed materials.' },
        }));
      }
      return Promise.resolve({});
    });
    const { getByRole, getByText } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 },
               activeBlepOnThisTask: activeBlep() },
    });
    await fireEvent.click(getByRole('button', { name: 'Stop Work' }));
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '5' } });
    await fireEvent.click(getByRole('checkbox'));
    await fireEvent.click(getByRole('button', { name: 'Add & complete' }));
    await vi.waitFor(() => {
      expect(getByText(/unconsumed materials/)).toBeInTheDocument();
    });
    // Still open — the typed value is not lost.
    expect(getByRole('spinbutton')).toBeInTheDocument();
  });
});

describe('TaskActions — settle-up completion', () => {
  it('opens the settle-up modal with the running total and completes with the increment', async () => {
    api.post.mockResolvedValueOnce({ needs_actual_qty: true,
                                     unit_label: 'pcs', current_qty: '9' });
    const { getByRole, getByText } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 } },
    });
    await fireEvent.click(getByRole('button', { name: 'Complete' }));
    expect(getByText(/Entered so far/)).toBeInTheDocument();
    api.post.mockResolvedValueOnce({ status: 'complete' });
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '5' } });
    await fireEvent.click(getByRole('button', { name: 'Complete task' }));
    expect(api.post).toHaveBeenLastCalledWith('/api/tasks/5/complete/',
                                              { add_qty: 5 });
  });
});

describe('TaskActions — prior-session prompt on start', () => {
  const priorConflict = {
    conflict: 'prior_session_qty',
    prior_task: { task_id: 7, name: 'Cut panels' },
    unit_label: 'pcs', current_qty: '9',
  };

  it('settles the prior session then re-posts start with the flag', async () => {
    api.post.mockImplementation((url, body) => {
      if (url.endsWith('/5/start-work/') && !body?.prior_qty_handled) {
        return Promise.resolve(priorConflict);
      }
      return Promise.resolve({ status: 'ok', blep_id: 1 });
    });
    const { getByRole, getByText } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'pending' }, user: { id: 1 } },
    });
    await fireEvent.click(getByRole('button', { name: 'Start Work' }));
    expect(getByText(/Cut panels/)).toBeInTheDocument();
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '4' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    await vi.waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/tasks/7/actual-qty/add/',
                                            { actual_qty: 4 });
      expect(api.post).toHaveBeenCalledWith('/api/tasks/5/start-work/',
                                            { prior_qty_handled: true });
    });
  });

  it('empty submit skips the add and just proceeds', async () => {
    api.post.mockImplementation((url, body) => {
      if (url.endsWith('/5/start-work/') && !body?.prior_qty_handled) {
        return Promise.resolve(priorConflict);
      }
      return Promise.resolve({ status: 'ok', blep_id: 1 });
    });
    const { getByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'pending' }, user: { id: 1 } },
    });
    await fireEvent.click(getByRole('button', { name: 'Start Work' }));
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    await vi.waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/tasks/5/start-work/',
                                            { prior_qty_handled: true });
    });
    const addCalls = api.post.mock.calls.filter(
      ([url]) => url.includes('actual-qty/add'));
    expect(addCalls).toHaveLength(0);
  });

  it('Cancel aborts the start entirely', async () => {
    api.post.mockResolvedValue(priorConflict);
    const { getByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'pending' }, user: { id: 1 } },
    });
    await fireEvent.click(getByRole('button', { name: 'Start Work' }));
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    const flagged = api.post.mock.calls.filter(
      ([, body]) => body?.prior_qty_handled);
    expect(flagged).toHaveLength(0);
  });
});
