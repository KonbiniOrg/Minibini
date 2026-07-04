import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock('svelte-spa-router', () => ({
  link: () => {},
  push: vi.fn(),
}));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import ChangeOrderDetailPage from '@/routes/change-orders/ChangeOrderDetailPage.svelte';

function makeCO(overrides = {}) {
  return {
    change_order_id: 3,
    change_order_number: 'CO-3',
    job: 9,
    status: 'draft',
    can_manage: true,
    line_items: [],
    ...overrides,
  };
}

function mockApi(co) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === `/api/change-orders/${co.change_order_id}/`) {
      return Promise.resolve({ ...co });
    }
    if (url.startsWith('/api/change-orders/') && url.includes('deliverables-baseline')) {
      return Promise.resolve({ baseline: [] });
    }
    if (url.startsWith('/api/change-orders/')) {
      // sibling COs list (?job=)
      return Promise.resolve({ results: [] });
    }
    if (url.startsWith('/api/jobs/') && url.includes('/deliverables/')) {
      return Promise.resolve([]);
    }
    if (url.startsWith('/api/jobs/')) {
      return Promise.resolve({ job_id: co.job, job_number: 'JOB-9', name: 'Job', contact: null });
    }
    if (url.startsWith('/api/estimates/')) {
      return Promise.resolve({ results: [] });
    }
    return Promise.resolve({});
  });
}

beforeEach(() => {
  api.post?.mockReset?.();
  api.patch?.mockReset?.();
  api.delete?.mockReset?.();
});

describe('ChangeOrderDetailPage per-object can_manage gating', () => {
  it('shows edit affordances for a PM (can_manage true) without the global atom', async () => {
    user.set({ permissions: [] }); // no can_manage_jobs atom
    mockApi(makeCO({ can_manage: true, status: 'draft' }));

    const { findByText } = render(ChangeOrderDetailPage, {
      props: { params: { id: '3' } },
    });

    expect(await findByText('+ New line')).toBeInTheDocument();
    expect(await findByText('+ New deliverable')).toBeInTheDocument();
  });

  it('hides edit affordances when can_manage is false even with the global atom', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeCO({ can_manage: false, status: 'draft' }));

    const { findByText, queryByText } = render(ChangeOrderDetailPage, {
      props: { params: { id: '3' } },
    });

    // page renders (Line items heading) once load completes
    await findByText('Line items');
    expect(queryByText('+ New line')).not.toBeInTheDocument();
    expect(queryByText('+ New deliverable')).not.toBeInTheDocument();
  });
});

describe('ChangeOrderDetailPage add-line flow', () => {
  it('"+ New line" opens the unified picker (service/inventory/freeform), not the CO modal', async () => {
    user.set({ permissions: [] });
    mockApi(makeCO({ can_manage: true, status: 'draft' }));

    const { findByText, queryByText } = render(ChangeOrderDetailPage, {
      props: { params: { id: '3' } },
    });

    await fireEvent.click(await findByText('+ New line'));
    // The PriceListPicker's freeform footer is visible…
    expect(await findByText('Is this a material?')).toBeInTheDocument();
    // …and the legacy action-select modal did not open.
    expect(queryByText('Add Change Order Line')).not.toBeInTheDocument();
  });
});
