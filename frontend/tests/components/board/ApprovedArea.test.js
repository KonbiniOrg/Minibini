import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));

import { api } from '@/lib/api.js';
import ApprovedArea from '@/components/board/ApprovedArea.svelte';

function data(taskOverrides) {
  return {
    jobs: [],
    workers: [{ user: { id: 1, name: 'Sam', initials: 'S' }, tasks: [] }],
    unassigned: [{ task_id: 10, name: 'Cut', status: 'pending', job_id: 3, ...taskOverrides }],
    available_workers: [],
  };
}

async function dropOnWorkerColumn(container) {
  const col = container.querySelector('.worker-tasks');
  await fireEvent.dragOver(col, { dataTransfer: {}, clientY: 0 });
  await fireEvent.drop(col, { dataTransfer: { getData: () => '10' } });
}

beforeEach(() => {
  api.post.mockReset();
  api.post.mockResolvedValue({});
});

describe('ApprovedArea', () => {
  it('prompts for worker time when assigning a task that has none', async () => {
    const { container, getByRole } = render(ApprovedArea, {
      props: { data: data({ est_worker_time: null }), canManage: true },
    });
    await dropOnWorkerColumn(container);
    // gatekeeper opens the duration prompt instead of assigning
    expect(getByRole('button', { name: 'Assign' })).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('assigns directly when the task already has an estimate', async () => {
    const { container } = render(ApprovedArea, {
      props: { data: data({ est_worker_time: 'PT1H' }), canManage: true },
    });
    await dropOnWorkerColumn(container);
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith('/api/tasks/10/assign/', expect.objectContaining({ assignee: 1 })),
    );
  });
});
