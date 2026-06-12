import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));
vi.mock('@/stores/blepActivity.js', () => ({ notifyBlepChanged: vi.fn() }));

import { api } from '@/lib/api.js';
import TaskActions from '@/components/tasks/TaskActions.svelte';

beforeEach(() => {
  api.post.mockReset();
  api.post.mockResolvedValue({});
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
});
