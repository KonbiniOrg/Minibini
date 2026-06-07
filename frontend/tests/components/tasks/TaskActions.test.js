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

  it('lets any authenticated worker cancel a task (cancel is a worker lifecycle op)', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    // worker with no can_manage_jobs — backend cancel is IsAuthenticated by design
    const { getByRole } = render(TaskActions, {
      props: { task: { task_id: 5, status: 'blocked' }, user: { id: 1 }, userPermissions: [] },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(api.post).toHaveBeenCalledWith('/api/tasks/5/cancel/', {});
    confirmSpy.mockRestore();
  });
});
