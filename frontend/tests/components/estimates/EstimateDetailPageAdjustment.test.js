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
import EstimateDetailPage from '@/routes/estimates/EstimateDetailPage.svelte';

const ADJ_SERVICE = { service_price_id: 1, name: 'Rush', algorithm: 'percentage', rate: '15.00' };

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
    if (url.includes('service-prices')) return Promise.resolve({ results: [ADJ_SERVICE] });
    return Promise.resolve({});
  });
  api.post.mockResolvedValue({ line_item_id: 99 });
}

beforeEach(() => {
  api.post?.mockReset?.();
  api.patch?.mockReset?.();
  api.delete?.mockReset?.();
  user.set({ permissions: [] });
});

describe('EstimateDetailPage adjustment affordances', () => {
  it('shows "Add adjustment" button on a draft estimate with can_manage', async () => {
    mockApi(makeEstimate({ can_manage: true, status: 'draft' }));
    const { findByText } = render(EstimateDetailPage, {
      props: { params: { id: '7' } },
    });
    expect(await findByText('Add Adjustment')).toBeInTheDocument();
  });

  it('does NOT show "Add adjustment" on a non-draft estimate', async () => {
    mockApi(makeEstimate({ can_manage: true, status: 'open' }));
    const { findByText, queryByText } = render(EstimateDetailPage, {
      props: { params: { id: '7' } },
    });
    await findByText('Line Items');
    expect(queryByText('Add Adjustment')).not.toBeInTheDocument();
  });

  it('does NOT show "Add adjustment" when can_manage is false', async () => {
    mockApi(makeEstimate({ can_manage: false, status: 'draft' }));
    const { findByText, queryByText } = render(EstimateDetailPage, {
      props: { params: { id: '7' } },
    });
    await findByText('Line Items');
    expect(queryByText('Add Adjustment')).not.toBeInTheDocument();
  });

  it('opens AdjustmentModal when "Add adjustment" is clicked', async () => {
    mockApi(makeEstimate({ can_manage: true, status: 'draft' }));
    const { findByText, findByRole } = render(EstimateDetailPage, {
      props: { params: { id: '7' } },
    });
    await fireEvent.click(await findByText('Add Adjustment'));
    // Modal should appear
    expect(await findByRole('dialog')).toBeInTheDocument();
  });

  it('shows Recalculate button on a draft adjustment line', async () => {
    const adjLine = {
      line_item_id: 99, line_number: 1, description: 'Rush 15%',
      qty: 1, price: '10.00', units: 'none', accounting_category: null,
      adjustment_service: ADJ_SERVICE, target_categories: [],
      sources: [],
    };
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [adjLine] }));
    const { findByRole } = render(EstimateDetailPage, {
      props: { params: { id: '7' } },
    });
    expect(await findByRole('button', { name: /recalculate/i })).toBeInTheDocument();
  });

  it('does NOT show Recalculate button on non-draft even when can_manage', async () => {
    const adjLine = {
      line_item_id: 99, line_number: 1, description: 'Rush 15%',
      qty: 1, price: '10.00', units: 'none', accounting_category: null,
      adjustment_service: ADJ_SERVICE, target_categories: [],
      sources: [],
    };
    mockApi(makeEstimate({ can_manage: true, status: 'open', line_items: [adjLine] }));
    const { findByText, queryByRole } = render(EstimateDetailPage, {
      props: { params: { id: '7' } },
    });
    await findByText('Line Items');
    expect(queryByRole('button', { name: /recalculate/i })).not.toBeInTheDocument();
  });

  it('POSTs to recalculate endpoint when Recalculate is clicked', async () => {
    const adjLine = {
      line_item_id: 99, line_number: 1, description: 'Rush 15%',
      qty: 1, price: '10.00', units: 'none', accounting_category: null,
      adjustment_service: ADJ_SERVICE, target_categories: [],
      sources: [],
    };
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [adjLine] }));
    const { findByRole } = render(EstimateDetailPage, {
      props: { params: { id: '7' } },
    });
    await fireEvent.click(await findByRole('button', { name: /recalculate/i }));
    expect(api.post).toHaveBeenCalledWith('/api/estimates/7/line-items/99/recalculate/');
  });
});
