import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));
vi.mock('@/stores/blepActivity.js', () => ({ notifyBlepChanged: vi.fn() }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}), push: vi.fn() }));

import { api } from '@/lib/api.js';
import { push } from 'svelte-spa-router';
import AssignedTaskList from '@/components/home/AssignedTaskList.svelte';

const t = (id, name) => ({ id, name, job: { id: 3, job_number: 'JOB-3', name: 'W' }, status: 'pending' });

beforeEach(() => {
  api.post.mockReset();
  push.mockReset();
  api.post.mockResolvedValue({});
});

describe('AssignedTaskList', () => {
  it('shows the empty state', () => {
    const { getByText } = render(AssignedTaskList, { props: { tasks: [] } });
    expect(getByText('No assigned tasks.')).toBeInTheDocument();
  });

  it('starts work and navigates to the task', async () => {
    const { getByRole } = render(AssignedTaskList, { props: { tasks: [t(5, 'Cut')] } });
    await fireEvent.click(getByRole('button', { name: 'Start Work' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/start-work/', {});
    expect(push).toHaveBeenCalledWith('/jobs/3/tasks/5');
  });

  it('reorders optimistically and persists the new order', async () => {
    const { getAllByRole } = render(AssignedTaskList, { props: { tasks: [t(1, 'A'), t(2, 'B')] } });
    await fireEvent.click(getAllByRole('button', { name: 'Down' })[0]);
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
    const { getByRole, getByText } = render(AssignedTaskList, { props: { tasks: [t(5, 'Cut')] } });
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
    const { getByRole } = render(AssignedTaskList, { props: { tasks: [t(5, 'Cut')] } });
    await fireEvent.click(getByRole('button', { name: 'Start Work' }));
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(push).not.toHaveBeenCalled();
    const flagged = api.post.mock.calls.filter(([, body]) => body?.prior_qty_handled);
    expect(flagged).toHaveLength(0);
  });
});
