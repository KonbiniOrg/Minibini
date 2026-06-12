import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
vi.mock('svelte-spa-router', () => ({
  link: () => {},
  push: vi.fn(),
}));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import PlanTaskDetailPage from '@/routes/worksheets/PlanTaskDetailPage.svelte';

function makeTask(overrides = {}) {
  const { editable = true, ...rest } = overrides;
  return {
    plan_task_id: 3,
    name: 'Cut sheet',
    description: '',
    can_manage: true,
    est_worksheet: {
      est_worksheet_id: 5,
      editable,
      job: { id: 9 },
    },
    ...rest,
  };
}

function mockApi(task) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === `/api/plan-tasks/${task.plan_task_id}/`) return Promise.resolve({ ...task });
    if (url.includes('/materials/')) return Promise.resolve([]);
    if (url.startsWith('/api/jobs/')) {
      return Promise.resolve({ job_id: 9, job_number: 'JOB-9', name: 'Job', contact: null });
    }
    if (url.startsWith('/api/task-templates/')) return Promise.resolve({ results: [] });
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [] });
    return Promise.resolve({});
  });
}

beforeEach(() => {
  api.post?.mockReset?.();
  api.delete?.mockReset?.();
});

describe('PlanTaskDetailPage per-object can_manage gating', () => {
  it('shows edit affordances for a PM (can_manage true) without the global atom', async () => {
    user.set({ permissions: [] }); // no can_manage_jobs atom
    mockApi(makeTask({ can_manage: true, editable: true }));

    const { findByText } = render(PlanTaskDetailPage, {
      props: { params: { planTaskId: '3' } },
    });

    expect(await findByText('Edit Plan Task')).toBeInTheDocument();
    expect(await findByText('Add Material')).toBeInTheDocument();
  });

  it('hides edit affordances when can_manage is false even with the global atom', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeTask({ can_manage: false, editable: true }));

    const { findByText, queryByText } = render(PlanTaskDetailPage, {
      props: { params: { planTaskId: '3' } },
    });

    // title renders once load completes
    await findByText(/PlanTask:/);
    expect(queryByText('Edit Plan Task')).not.toBeInTheDocument();
    expect(queryByText('Add Material')).not.toBeInTheDocument();
  });
});
