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
  it('shows the "Show Tasks & Materials" wizard link without a worksheet guard', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft' }));

    const { findByText, queryByText } = render(EstimateDetailPage, {
      props: { params: { id: '7' } },
    });

    // Wizard link is always present for an editable estimate (no worksheet guard)
    expect(await findByText('Show Tasks & Materials')).toBeInTheDocument();
    // No stale "Plan" row or old labels
    expect(queryByText('Plan')).not.toBeInTheDocument();
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

  it('does NOT show out-of-sync warning on a non-draft (open) estimate', async () => {
    // Out-of-sync is only meaningful on a draft estimate — once sent/accepted/superseded
    // the line can no longer be edited via the wizard, so flagging it is misleading.
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'open', line_items: [line(true)] }));
    const { findByText, queryByText } = render(EstimateDetailPage, { props: { params: { id: '7' } } });
    await findByText('Cut');
    expect(queryByText(/out of sync/)).toBeNull();
  });

  it('does NOT show out-of-sync warning for a hand-line (no atom sources)', async () => {
    // Hand-entered lines have no sources — nothing to be out of sync with.
    user.set({ permissions: ['can_manage_jobs'] });
    const handLine = {
      line_item_id: 2, line_number: 1, description: 'Hand entry', qty: '1', units: 'each',
      price: '999', accounting_category: null, sources: [],
    };
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [handLine] }));
    const { findByText, queryByText } = render(EstimateDetailPage, { props: { params: { id: '7' } } });
    await findByText('Hand entry');
    expect(queryByText(/out of sync/)).toBeNull();
  });
});

describe('EstimateDetailPage line-item actions', () => {
  it('shows Edit/Delete buttons on line items of a draft estimate', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [
      { line_item_id: 1, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
        price: '5', accounting_category: null, sources: [] },
    ] }));
    const { findByText, queryByText } = render(EstimateDetailPage, { props: { params: { id: '7' } } });
    await findByText('Cut');
    expect(queryByText('Edit')).not.toBeNull();
    expect(queryByText('Delete')).not.toBeNull();
  });

  it('hides Edit/Delete when the estimate is not editable (sent)', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'open', line_items: [
      { line_item_id: 1, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
        price: '5', accounting_category: null, sources: [] },
    ] }));
    const { findByText, queryByText } = render(EstimateDetailPage, { props: { params: { id: '7' } } });
    await findByText('Cut');
    expect(queryByText('Edit')).toBeNull();
    expect(queryByText('Delete')).toBeNull();
  });

  it('shows an Add Line Item button on a draft estimate', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [] }));
    const { findByText } = render(EstimateDetailPage, { props: { params: { id: '7' } } });
    expect(await findByText('Add Line Item')).toBeInTheDocument();
  });

  it('hides Add Line Item when the estimate is not editable (sent)', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'open', line_items: [] }));
    const { findByText, queryByText } = render(EstimateDetailPage, { props: { params: { id: '7' } } });
    await findByText(/Estimate:/);
    expect(queryByText('Add Line Item')).toBeNull();
  });

  it('Delete on a line calls the line-item delete endpoint', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [
      { line_item_id: 42, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
        price: '5', accounting_category: null, sources: [] },
    ] }));
    api.delete.mockResolvedValue({ message: 'deleted' });
    const { findByText } = render(EstimateDetailPage, { props: { params: { id: '7' } } });
    const deleteBtn = await findByText('Delete');
    deleteBtn.click();
    expect(api.delete).toHaveBeenCalledWith('/api/estimates/7/line-items/42/');
  });
});
