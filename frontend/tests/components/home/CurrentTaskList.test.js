import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));
vi.mock('@/stores/blepActivity.js', () => ({ notifyBlepChanged: vi.fn() }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}), push: vi.fn() }));

import { api } from '@/lib/api.js';
import { push } from 'svelte-spa-router';
import CurrentTaskList from '@/components/home/CurrentTaskList.svelte';

const t = (id, name, extra = {}) => ({
  id, name, job: { id: 3, job_number: 'JOB-3', name: 'W' },
  status: 'pending', assigned_to_me: true, ...extra,
});

beforeEach(() => {
  api.post.mockReset();
  push.mockReset();
  api.post.mockResolvedValue({});
});

describe('CurrentTaskList', () => {
  it('shows the empty state', () => {
    const { getByText } = render(CurrentTaskList, { props: { tasks: [] } });
    expect(getByText('No current tasks.')).toBeInTheDocument();
  });

  it('starts work and navigates to the task', async () => {
    const { getByRole } = render(CurrentTaskList, { props: { tasks: [t(5, 'Cut')] } });
    await fireEvent.click(getByRole('button', { name: 'Start Work' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/start-work/', {});
    expect(push).toHaveBeenCalledWith('/jobs/3/tasks/5');
  });

  it('reorders my own tasks optimistically and persists only my task ids', async () => {
    const { getAllByRole } = render(CurrentTaskList, { props: { tasks: [t(1, 'A'), t(2, 'B')] } });
    await fireEvent.click(getAllByRole('button', { name: 'Down' })[0]);
    expect(api.post).toHaveBeenCalledWith('/api/tasks/reorder/', { task_ids: [2, 1] });
  });

  it('omits reorder buttons for tasks assigned to other workers', () => {
    const { getAllByRole, queryAllByRole } = render(CurrentTaskList, {
      props: { tasks: [t(1, 'Mine'), t(2, 'Theirs', { assigned_to_me: false })] },
    });
    // One row is mine (Up+Down), the other has none.
    expect(getAllByRole('button', { name: 'Up' })).toHaveLength(1);
    expect(getAllByRole('button', { name: 'Down' })).toHaveLength(1);
    // Start Work is offered on both rows regardless of ownership.
    expect(queryAllByRole('button', { name: 'Start Work' })).toHaveLength(2);
  });

  it('reorder of my tasks ignores the trailing other-worker rows', async () => {
    const { getAllByRole } = render(CurrentTaskList, {
      props: { tasks: [t(1, 'A'), t(2, 'B'), t(9, 'Theirs', { assigned_to_me: false })] },
    });
    await fireEvent.click(getAllByRole('button', { name: 'Down' })[0]);
    // Only the two mine ids are sent, in their new order — 9 is excluded.
    expect(api.post).toHaveBeenCalledWith('/api/tasks/reorder/', { task_ids: [2, 1] });
  });

  it('settles a prior entered-qty session before starting', async () => {
    api.post.mockImplementation((url, body) => {
      if (url === '/api/tasks/5/start-work/' && !body?.prior_qty_handled) {
        return Promise.resolve({
          conflict: 'prior_session_qty',
          prior_task: { task_id: 7, name: 'Cut panels' },
          unit_label: 'pcs', current_qty: '9',
        });
      }
      return Promise.resolve({ status: 'ok', blep_id: 1 });
    });
    const { getByRole, getByText } = render(CurrentTaskList, { props: { tasks: [t(5, 'Cut')] } });
    await fireEvent.click(getByRole('button', { name: 'Start Work' }));
    expect(getByText(/Cut panels/)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    await fireEvent.input(getByRole('spinbutton'), { target: { value: '4' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    await vi.waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/tasks/7/actual-qty/add/', { actual_qty: 4 });
      expect(api.post).toHaveBeenCalledWith('/api/tasks/5/start-work/', { prior_qty_handled: true });
      expect(push).toHaveBeenCalledWith('/jobs/3/tasks/5');
    });
  });

  it('cancelling the prior-session prompt aborts the start', async () => {
    api.post.mockResolvedValue({
      conflict: 'prior_session_qty',
      prior_task: { task_id: 7, name: 'Cut panels' },
      unit_label: 'pcs', current_qty: null,
    });
    const { getByRole } = render(CurrentTaskList, { props: { tasks: [t(5, 'Cut')] } });
    await fireEvent.click(getByRole('button', { name: 'Start Work' }));
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(push).not.toHaveBeenCalled();
    const flagged = api.post.mock.calls.filter(([, body]) => body?.prior_qty_handled);
    expect(flagged).toHaveLength(0);
  });
});
