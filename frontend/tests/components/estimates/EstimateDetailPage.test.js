import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock('svelte-spa-router', () => ({
  link: () => {},
  push: vi.fn(),
}));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import EstimateDetailPage from '@/routes/estimates/EstimateDetailPage.svelte';

function makeEstimate(overrides = {}) {
  return {
    estimate_id: 7,
    estimate_number: 'EST-7',
    job: 9,
    worksheet: null,
    version: 1,
    parent: null,
    status: 'draft',
    can_manage: true,
    is_amended: false,
    created_date: '2026-01-01T00:00:00Z',
    sent_date: null,
    expiration_date: null,
    closed_date: null,
    line_items: [],
    ...overrides,
  };
}

function mockApi(estimate) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === `/api/estimates/${estimate.estimate_id}/`) {
      return Promise.resolve({ ...estimate });
    }
    if (url.startsWith('/api/jobs/')) {
      return Promise.resolve({ job_id: estimate.job, job_number: 'JOB-9', name: 'Job', contact: null });
    }
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [] });
    return Promise.resolve({});
  });
}

beforeEach(() => {
  api.post?.mockReset?.();
  api.patch?.mockReset?.();
  api.delete?.mockReset?.();
});

describe('EstimateDetailPage per-object can_manage gating', () => {
  it('shows edit affordances for a PM (can_manage true) without the global atom', async () => {
    user.set({ permissions: [] }); // no can_manage_jobs atom
    mockApi(makeEstimate({ can_manage: true, status: 'draft' }));

    const { findByText } = render(EstimateDetailPage, {
      props: { params: { id: '7' } },
    });

    expect(await findByText('Add Adjustment')).toBeInTheDocument();
  });

  it('hides edit affordances when can_manage is false even with the global atom', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: false, status: 'draft' }));

    const { findByText, queryByText } = render(EstimateDetailPage, {
      props: { params: { id: '7' } },
    });

    // page renders (Line Items heading) once load completes
    await findByText('Line Items');
    expect(queryByText('Add Adjustment')).not.toBeInTheDocument();
  });
});

describe('EstimateDetailPage number/version display', () => {
  it('appends the version to the estimate number with a dash and drops the Version row', async () => {
    user.set({ permissions: [] });
    mockApi(makeEstimate({ estimate_number: 'EST-7', version: 2 }));
    const { container, findByText, queryByText } = render(EstimateDetailPage, {
      props: { params: { id: '7' } },
    });
    await findByText('Estimate Number');
    expect(container.textContent).toContain('EST-7-2');
    expect(queryByText('Version')).toBeNull();
  });
});

describe('EstimateDetailPage vocabulary labels', () => {
  it('labels the worksheet row "Plan" and the wizard link "Customize Client View"', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft', worksheet: 3 }));

    const { findByText, queryByText } = render(EstimateDetailPage, {
      props: { params: { id: '7' } },
    });

    // "Plan" label in the data table row
    expect(await findByText('Plan')).toBeInTheDocument();
    // Wizard link uses new label
    expect(await findByText('Customize Client View')).toBeInTheDocument();
    // Old labels gone
    expect(queryByText('Worksheet')).not.toBeInTheDocument();
    expect(queryByText('Show Worksheet')).not.toBeInTheDocument();
  });
});

describe('EstimateDetailPage out-of-sync indicator', () => {
  // Live check: line price vs the sum of its atoms' computed_amount.
  const line = (outOfSync) => ({
    line_item_id: 1, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
    price: outOfSync ? '10' : '5', accounting_category: null,
    sources: [{ source_id: 9, source_type: 'plan_task', source_pk: 4, description: 'atom', computed_amount: '10' }],
  });

  it('flags a line whose price no longer matches its atoms', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [line(true)] }));
    const { findByText } = render(EstimateDetailPage, { props: { params: { id: '7' } } });
    expect(await findByText(/out of sync with atoms/)).toBeInTheDocument();
  });

  it('does not flag a line that matches its atoms', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [line(false)] }));
    const { findByText, queryByText } = render(EstimateDetailPage, { props: { params: { id: '7' } } });
    await findByText('Cut');
    expect(queryByText(/out of sync/)).toBeNull();
  });
});
