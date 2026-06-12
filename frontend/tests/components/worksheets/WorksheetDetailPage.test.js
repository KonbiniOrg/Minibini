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
import WorksheetDetailPage from '@/routes/worksheets/WorksheetDetailPage.svelte';

function makeWorksheet(overrides = {}) {
  return {
    est_worksheet_id: 5,
    job: 9,
    created_date: '2026-01-01T00:00:00Z',
    editable: true,
    deletable: true,
    can_manage: true,
    plan_tasks: [],
    ...overrides,
  };
}

function mockApi(worksheet) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === `/api/est-worksheets/${worksheet.est_worksheet_id}/`) {
      return Promise.resolve({ ...worksheet });
    }
    if (url.includes('/plan-materials/')) return Promise.resolve([]);
    if (url.startsWith('/api/jobs/')) {
      return Promise.resolve({ job_id: worksheet.job, job_number: 'JOB-9', name: 'Job', contact: null });
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

describe('WorksheetDetailPage per-object can_manage gating', () => {
  it('shows edit affordances for a PM (can_manage true) without the global atom', async () => {
    user.set({ permissions: [] }); // no can_manage_jobs atom
    mockApi(makeWorksheet({ can_manage: true, editable: true, deletable: true }));

    const { findByText, getByText } = render(WorksheetDetailPage, {
      props: { params: { id: '5' } },
    });

    expect(await findByText('Add Manual Task')).toBeInTheDocument();
    expect(getByText('Delete worksheet')).toBeInTheDocument();
  });

  it('hides edit affordances when can_manage is false even with the global atom', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeWorksheet({ can_manage: false, editable: true, deletable: true }));

    const { findByText, queryByText } = render(WorksheetDetailPage, {
      props: { params: { id: '5' } },
    });

    // frozen badge renders once load completes, confirming the page rendered
    await findByText('frozen');
    expect(queryByText('Add Manual Task')).not.toBeInTheDocument();
    expect(queryByText('Delete worksheet')).not.toBeInTheDocument();
  });
});
