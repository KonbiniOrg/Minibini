import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, within } from '@testing-library/svelte';

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

  it('shows and fires Cancel on a cancel-eligible status (open to all workers, C2)', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { getByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'blocked' }, user: { id: 1 } },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/cancel/', {});
    confirmSpy.mockRestore();
  });

  it('hideStop still offers Start Work when no own session runs here', () => {
    const { getByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'pending' }, user: { id: 1 }, hideStop: true },
    });
    expect(getByRole('button', { name: 'Start Work' })).toBeInTheDocument();
  });

  it('hideStop renders neither Stop Work nor the under-minimum Cancel while own session runs', () => {
    const overMinimum = {
      start_time: new Date(Date.now() - 30 * 60000).toISOString(),
      blep_minimum_minutes: 1,
    };
    const { queryByRole } = render(TaskActions, {
      props: {
        task: { task_id: 5, status: 'in_progress' },
        user: { id: 1 },
        activeBlepOnThisTask: overMinimum,
        hideStop: true,
      },
    });
    expect(queryByRole('button', { name: 'Stop Work' })).toBeNull();
    // Start Work also absent — there's already an active session here.
    expect(queryByRole('button', { name: 'Start Work' })).toBeNull();

    const underMinimum = {
      start_time: new Date().toISOString(),
      blep_minimum_minutes: 60,
    };
    const { queryByRole: q2, container: c2 } = render(TaskActions, {
      props: {
        task: { task_id: 6, status: 'in_progress' },
        user: { id: 1 },
        activeBlepOnThisTask: underMinimum,
        hideStop: true,
      },
    });
    // The under-minimum blep-cancel (.cancel-work) is suppressed; the
    // task-level Cancel (open to all workers, C2) is a different control.
    expect(q2('button', { name: 'Stop Work' })).toBeNull();
    expect(c2.querySelector('.cancel-work')).toBeNull();
  });

  // Quantity structure (spec §9 rule 1, task-owned-money Phase 4 Task 4): a
  // parent task delegates start/blep to its children — start-work must
  // never render for it, regardless of status.
  it('hides Start Work on a parent task', () => {
    const { queryByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'pending' }, user: { id: 1 }, isParent: true },
    });
    expect(queryByRole('button', { name: 'Start Work' })).toBeNull();
  });

  it('still shows Block/Cancel on a parent task', () => {
    const { getByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'pending' }, user: { id: 1 }, isParent: true },
    });
    expect(getByRole('button', { name: 'Block' })).toBeInTheDocument();
    expect(getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
  });

  // Parent completion is OFFERED, not automatic — only once every child is
  // terminal (spec §9 rule 1). childrenReady defaults true (every
  // non-parent surface unaffected); a parent whose children aren't all
  // terminal yet hides Complete instead of letting it round-trip a
  // guaranteed 400 from the server.
  it('hides Complete on a parent task while children are not all terminal', () => {
    const { queryByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 }, isParent: true, childrenReady: false },
    });
    expect(queryByRole('button', { name: 'Complete' })).toBeNull();
  });

  it('shows Complete on a parent task once every child is terminal', () => {
    const { getByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 }, isParent: true, childrenReady: true },
    });
    expect(getByRole('button', { name: 'Complete' })).toBeInTheDocument();
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

describe('TaskActions — settle-first stop', () => {
  const stopConflict = {
    conflict: 'prior_session_qty',
    prior_task: { task_id: 5, name: 'Press parts' },
    unit_label: 'pcs', current_qty: '9',
  };

  it('opens the session modal on the conflict and settles in ONE flagged stop', async () => {
    api.post.mockImplementation((url, body) => {
      if (url.endsWith('/stop-work/') && !body?.prior_qty_handled) {
        return Promise.resolve(stopConflict);
      }
      return Promise.resolve({ status: 'ok' });
    });
    const { getByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 },
               activeBlepOnThisTask: activeBlep() },
    });
    await fireEvent.click(getByRole('button', { name: 'Stop Work' }));
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '5' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    await vi.waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/tasks/5/stop-work/',
                                            { prior_qty_handled: true, add_qty: 5 });
    });
    const addCalls = api.post.mock.calls.filter(
      ([url]) => url.includes('actual-qty/add'));
    expect(addCalls).toHaveLength(0);
  });

  it('empty submit skips the entry and just stops', async () => {
    api.post.mockImplementation((url, body) => {
      if (url.endsWith('/stop-work/') && !body?.prior_qty_handled) {
        return Promise.resolve(stopConflict);
      }
      return Promise.resolve({ status: 'ok' });
    });
    const { getByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 },
               activeBlepOnThisTask: activeBlep() },
    });
    await fireEvent.click(getByRole('button', { name: 'Stop Work' }));
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    await vi.waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/tasks/5/stop-work/',
                                            { prior_qty_handled: true });
    });
  });

  it('modal Cancel aborts the stop — the session keeps running', async () => {
    api.post.mockResolvedValue(stopConflict);
    const { getByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 },
               activeBlepOnThisTask: activeBlep() },
    });
    await fireEvent.click(getByRole('button', { name: 'Stop Work' }));
    await fireEvent.click(
      within(getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    const flagged = api.post.mock.calls.filter(
      ([, body]) => body?.prior_qty_handled);
    expect(flagged).toHaveLength(0);
  });

  it('does not open a modal when stop returns no conflict', async () => {
    api.post.mockResolvedValue({ status: 'ok' });
    const { getByRole, queryByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 },
               activeBlepOnThisTask: activeBlep() },
    });
    await fireEvent.click(getByRole('button', { name: 'Stop Work' }));
    expect(queryByRole('spinbutton')).toBeNull();
  });

  it('checkbox settles-and-completes in one atomic complete call', async () => {
    api.post.mockImplementation((url, body) => {
      if (url.endsWith('/stop-work/') && !body?.prior_qty_handled) {
        return Promise.resolve(stopConflict);
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
    // complete closes the blep server-side — no stop re-post needed.
    const flaggedStops = api.post.mock.calls.filter(
      ([url, body]) => url.endsWith('/stop-work/') && body?.prior_qty_handled);
    expect(flaggedStops).toHaveLength(0);
  });

  it('keeps the modal open with the error when the settle fails', async () => {
    api.post.mockImplementation((url, body) => {
      if (url.endsWith('/stop-work/') && !body?.prior_qty_handled) {
        return Promise.resolve(stopConflict);
      }
      return Promise.reject(Object.assign(new Error('fail'), {
        status: 400, data: { detail: 'Cannot reduce the total below zero.' },
      }));
    });
    const { getByRole, getByText } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 },
               activeBlepOnThisTask: activeBlep() },
    });
    await fireEvent.click(getByRole('button', { name: 'Stop Work' }));
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '5' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    await vi.waitFor(() => {
      expect(getByText(/below zero/)).toBeInTheDocument();
    });
    expect(getByRole('spinbutton')).toBeInTheDocument();
  });
});

describe('TaskActions — settle-first task cancel', () => {
  const cancelConflict = {
    conflict: 'prior_session_qty',
    prior_task: { task_id: 5, name: 'Press parts' },
    unit_label: 'pcs', current_qty: '9',
  };

  it('offers the session count before cancelling, then re-posts with the flag', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    api.post.mockImplementation((url, body) => {
      if (url.endsWith('/cancel/') && !body?.prior_qty_handled) {
        return Promise.resolve(cancelConflict);
      }
      return Promise.resolve({ status: 'cancelled' });
    });
    const { getByRole, getByText } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 },
               canManage: true },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(getByText(/Press parts/)).toBeInTheDocument();
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '5' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    await vi.waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/tasks/5/actual-qty/add/',
                                            { actual_qty: 5 });
      expect(api.post).toHaveBeenCalledWith('/api/tasks/5/cancel/',
                                            { prior_qty_handled: true });
    });
    window.confirm.mockRestore();
  });

  it('modal Cancel aborts the task-cancel entirely', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    api.post.mockResolvedValue(cancelConflict);
    const { getByRole, getAllByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 },
               canManage: true },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    // The modal's Cancel (the row's Cancel is behind the modal overlay).
    const cancels = getAllByRole('button', { name: 'Cancel' });
    await fireEvent.click(cancels[cancels.length - 1]);
    const flagged = api.post.mock.calls.filter(
      ([, body]) => body?.prior_qty_handled);
    expect(flagged).toHaveLength(0);
    window.confirm.mockRestore();
  });
});

describe('TaskActions — settle-first block', () => {
  const blockConflict = {
    conflict: 'prior_session_qty',
    prior_task: { task_id: 5, name: 'Press parts' },
    unit_label: 'pcs', current_qty: '9',
  };

  it('offers the session count before blocking, then re-posts with the flag and reason', async () => {
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('saw down');
    api.post.mockImplementation((url, body) => {
      if (url.endsWith('/block/') && !body?.prior_qty_handled) {
        return Promise.resolve(blockConflict);
      }
      return Promise.resolve({ status: 'blocked' });
    });
    const { getByRole, getByText } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 } },
    });
    await fireEvent.click(getByRole('button', { name: 'Block' }));
    expect(getByText(/Press parts/)).toBeInTheDocument();
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '5' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    await vi.waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/tasks/5/actual-qty/add/',
                                            { actual_qty: 5 });
      expect(api.post).toHaveBeenCalledWith('/api/tasks/5/block/',
                                            { reason: 'saw down', prior_qty_handled: true });
    });
    promptSpy.mockRestore();
  });

  it('modal Cancel aborts the block entirely', async () => {
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('saw down');
    api.post.mockResolvedValue(blockConflict);
    const { getByRole, getAllByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 } },
    });
    await fireEvent.click(getByRole('button', { name: 'Block' }));
    const cancels = getAllByRole('button', { name: 'Cancel' });
    await fireEvent.click(cancels[cancels.length - 1]);
    const flagged = api.post.mock.calls.filter(
      ([, body]) => body?.prior_qty_handled);
    expect(flagged).toHaveLength(0);
    promptSpy.mockRestore();
  });

  it('active_workers refusal raises the overlay naming the workers — never the start-work conflict modal', async () => {
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('saw down');
    api.post.mockResolvedValue({
      conflict: 'active_workers',
      workers: [{ user_id: 2, name: 'Dana Smith' }, { user_id: 3, name: 'Marcus' }],
    });
    const onConflict = vi.fn();
    const { getByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'in_progress' }, user: { id: 1 }, onConflict },
    });
    await fireEvent.click(getByRole('button', { name: 'Block' }));
    await vi.waitFor(() => {
      expect(get(overlayMessage)?.text).toMatch(/Dana Smith, Marcus/);
    });
    expect(get(overlayMessage)?.kind).toBe('error');
    // The join/takeover chooser is a start-work affordance — a block
    // refusal must never route there.
    expect(onConflict).not.toHaveBeenCalled();
    promptSpy.mockRestore();
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
    await fireEvent.click(
      within(getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    const flagged = api.post.mock.calls.filter(
      ([, body]) => body?.prior_qty_handled);
    expect(flagged).toHaveLength(0);
  });
});

describe('TaskActions cancel permissions (C2)', () => {
  it('offers task-cancel to non-managers', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { getByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'pending' }, user: { id: 1 }, canManage: false },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/cancel/', {});
    confirmSpy.mockRestore();
  });
});
