import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';

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

function mockApi(worksheet, extraGetImpl) {
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
    if (extraGetImpl) return extraGetImpl(url);
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

    expect(await findByText('Add from Price List')).toBeInTheDocument();
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

describe('WorksheetDetailPage two-action add surface', () => {
  it('shows two add actions: Template and Price List (not Manual Task / Material)', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeWorksheet({ can_manage: true, editable: true }));

    render(WorksheetDetailPage, { props: { params: { id: '5' } } });

    expect(await screen.findByRole('button', { name: /add from price list/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add from template/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add manual task/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^add material$/i })).not.toBeInTheDocument();
  });

  it('opening Price List, typing a query, and choosing a service opens the task form seeded with the service name', async () => {
    const SERVICE = {
      service_item_id: 1, name: 'CNC Cutting', algorithm: 'ELAPSED_TIME',
      rate: '90.00', unit_label: 'hr', modifiers: [], description: '',
    };
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeWorksheet({ can_manage: true, editable: true }), (url) => {
      if (url.includes('service-items')) return Promise.resolve({ results: [SERVICE], count: 1 });
      if (url.includes('inventory')) return Promise.resolve({ results: [], count: 0 });
      return Promise.resolve({});
    });

    render(WorksheetDetailPage, { props: { params: { id: '5' } } });

    // Open the picker
    await fireEvent.click(await screen.findByRole('button', { name: /add from price list/i }));
    // New picker shows nothing until you type — type a query first
    const searchInput = await screen.findByPlaceholderText(/search/i);
    await fireEvent.input(searchInput, { target: { value: 'CNC' } });
    // Wait for the result to appear (findByText waits past the 250ms debounce)
    const row = await screen.findByRole('button', { name: /CNC Cutting/ });
    // Pick the row via mouseDown (SearchPicker listens on mousedown)
    await fireEvent.mouseDown(row);
    // The WorkItemForm should now be open showing the service as a header
    expect(await screen.findByText(/Service:/)).toBeInTheDocument();
    expect(screen.getByText(/CNC Cutting/)).toBeInTheDocument();
  });
});
