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
import { getJobWs, rememberMode } from '@/stores/jobWorkspace.js';
import EstimatePanel from '@/components/estimates/EstimatePanel.svelte';

const JOB = { job_id: 9, job_number: 'JOB-9', name: 'Job', contact: null, can_manage: true };
const ADJ_SERVICE = { rate_scheme_id: 1, name: 'Rush', algorithm: 'percentage', rate: '15.00' };

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

function mockApi(estimate, { versions = null, changeOrders = [] } = {}) {
  const versionList = versions ?? (estimate ? [estimate] : []);
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (estimate && url === `/api/estimates/${estimate.estimate_id}/`) {
      return Promise.resolve({ ...estimate });
    }
    if (url.startsWith('/api/estimates/?job=')) {
      return Promise.resolve({ results: versionList });
    }
    if (url.startsWith('/api/change-orders/?job=')) {
      return Promise.resolve({ results: changeOrders });
    }
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [] });
    if (url.startsWith('/api/settings/')) return Promise.resolve({});
    if (url.includes('rate-schemes')) return Promise.resolve({ results: [ADJ_SERVICE] });
    return Promise.resolve({});
  });
}

beforeEach(() => {
  api.post?.mockReset?.();
  api.patch?.mockReset?.();
  api.delete?.mockReset?.();
});

describe('EstimatePanel version subnav', () => {
  it('renders one job-scoped link per version, active on the shown doc', async () => {
    user.set({ permissions: [] });
    const v1 = makeEstimate({ estimate_id: 7, version: 1, status: 'superseded' });
    const v2 = makeEstimate({ estimate_id: 8, version: 2, status: 'draft' });
    mockApi(v2, { versions: [v1, v2] });

    const { findByText, container } = render(EstimatePanel, {
      props: { job: JOB, estimateId: 8 },
    });

    await findByText('Estimate: EST-7');
    const links = Array.from(container.querySelectorAll('.doc-subnav a'));
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute('href', '#/jobs/9/estimate/7');
    expect(links[0]).toHaveTextContent('v1');
    expect(links[1]).toHaveAttribute('href', '#/jobs/9/estimate/8');
    expect(links[1]).toHaveTextContent('v2');
    expect(links[1]).toHaveClass('active');
    expect(links[0]).not.toHaveClass('active');
  });

  it('appends change orders after estimate versions, linking to /change-orders/:id', async () => {
    user.set({ permissions: [] });
    const v1 = makeEstimate({ estimate_id: 7, version: 1, status: 'accepted' });
    const co = { change_order_id: 3, change_order_number: 'CO-3', status: 'open', estimate: 7 };
    mockApi(v1, { versions: [v1], changeOrders: [co] });

    const { findByText, container } = render(EstimatePanel, {
      props: { job: JOB, estimateId: 7 },
    });

    await findByText('Estimate: EST-7');
    const links = Array.from(container.querySelectorAll('.doc-subnav a'));
    expect(links).toHaveLength(2);
    expect(links[1]).toHaveAttribute('href', '#/jobs/9/change-order/3');
    expect(links[1]).toHaveTextContent('CO-3');
  });
});

describe('EstimatePanel toolbar actions', () => {
  it('offers Revise on a submitted (open) estimate', async () => {
    user.set({ permissions: [] });
    const est = makeEstimate({ estimate_id: 7, status: 'open' });
    mockApi(est, { versions: [est] });
    const { findByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    expect(await findByRole('button', { name: /revise estimate/i })).toBeInTheDocument();
  });

  it('offers Create Change Order on an accepted estimate and posts it for the job', async () => {
    user.set({ permissions: [] });
    const est = makeEstimate({ estimate_id: 7, status: 'accepted' });
    mockApi(est, { versions: [est] });
    api.post.mockResolvedValue({ change_order_id: 42 });
    const { findByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    const btn = await findByRole('button', { name: /create change order/i });
    await fireEvent.click(btn);
    expect(api.post).toHaveBeenCalledWith('/api/change-orders/', { job: 9 });
  });

  it('does not offer Create Change Order on a non-accepted estimate', async () => {
    user.set({ permissions: [] });
    const est = makeEstimate({ estimate_id: 7, status: 'open' });
    mockApi(est, { versions: [est] });
    const { findByText, queryByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Estimate: EST-7');
    expect(queryByRole('button', { name: /create change order/i })).toBeNull();
  });
});

describe('EstimatePanel empty state', () => {
  it('shows a can_manage-gated Start Estimate button when the job has no estimates', async () => {
    user.set({ permissions: [] });
    mockApi(null, { versions: [] });
    const { findByRole } = render(EstimatePanel, {
      props: { job: { ...JOB, can_manage: true }, estimateId: null },
    });
    expect(await findByRole('button', { name: /start estimate/i })).toBeInTheDocument();
  });

  it('shows a plain message (no button) when the job has no estimates and no can_manage', async () => {
    user.set({ permissions: [] });
    mockApi(null, { versions: [] });
    const { findByText, queryByRole } = render(EstimatePanel, {
      props: { job: { ...JOB, can_manage: false }, estimateId: null },
    });
    expect(await findByText('No estimates yet.')).toBeInTheDocument();
    expect(queryByRole('button', { name: /start estimate/i })).not.toBeInTheDocument();
  });

  it('Start Estimate posts and navigates to the job-scoped estimate URL', async () => {
    user.set({ permissions: [] });
    mockApi(null, { versions: [] });
    api.post.mockResolvedValue({ estimate_id: 42 });
    const { findByRole } = render(EstimatePanel, {
      props: { job: { ...JOB, can_manage: true }, estimateId: null },
    });
    const btn = await findByRole('button', { name: /start estimate/i });
    await fireEvent.click(btn);
    expect(api.post).toHaveBeenCalledWith('/api/estimates/', { job: 9 });
  });
});

describe('EstimatePanel per-object can_manage gating', () => {
  it('shows edit affordances for a PM (can_manage true) without the global atom', async () => {
    user.set({ permissions: [] }); // no can_manage_jobs atom
    mockApi(makeEstimate({ can_manage: true, status: 'draft' }));

    const { findByText } = render(EstimatePanel, {
      props: { job: JOB, estimateId: 7 },
    });

    expect(await findByText('Add Adjustment')).toBeInTheDocument();
  });

  it('hides edit affordances when can_manage is false even with the global atom', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: false, status: 'draft' }));

    const { findByText, queryByText } = render(EstimatePanel, {
      props: { job: JOB, estimateId: 7 },
    });

    await findByText('Line Items');
    expect(queryByText('Add Adjustment')).not.toBeInTheDocument();
  });
});

describe('EstimatePanel number/version display', () => {
  it('appends the version to the estimate number with a dash and drops the Version row', async () => {
    user.set({ permissions: [] });
    mockApi(makeEstimate({ estimate_number: 'EST-7', version: 2 }));
    const { container, findByText, queryByText } = render(EstimatePanel, {
      props: { job: JOB, estimateId: 7 },
    });
    await findByText('Estimate Number');
    expect(container.textContent).toContain('EST-7-2');
    expect(queryByText('Version')).toBeNull();
  });
});

describe('EstimatePanel vocabulary labels', () => {
  it('shows the "Show Tasks & Materials" wizard link without a worksheet guard', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft' }));

    const { findByText, queryByText } = render(EstimatePanel, {
      props: { job: JOB, estimateId: 7 },
    });

    expect(await findByText('Show Tasks & Materials')).toBeInTheDocument();
    expect(queryByText('Plan')).not.toBeInTheDocument();
    expect(queryByText('Worksheet')).not.toBeInTheDocument();
    expect(queryByText('Show Worksheet')).not.toBeInTheDocument();
  });
});

describe('EstimatePanel out-of-sync indicator', () => {
  const line = (outOfSync) => ({
    line_item_id: 1, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
    price: outOfSync ? '10' : '5', accounting_category: null,
    sources: [{ source_id: 9, source_type: 'plan_task', source_pk: 4, description: 'atom', computed_amount: '10' }],
  });

  it('flags a line whose price no longer matches its atoms', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [line(true)] }));
    const { findByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    expect(await findByText(/out of sync with atoms/)).toBeInTheDocument();
  });

  it('does not flag a line that matches its atoms', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [line(false)] }));
    const { findByText, queryByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Cut');
    expect(queryByText(/out of sync/)).toBeNull();
  });

  it('does NOT show out-of-sync warning on a non-draft (open) estimate', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'open', line_items: [line(true)] }));
    const { findByText, queryByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Cut');
    expect(queryByText(/out of sync/)).toBeNull();
  });

  it('does NOT show out-of-sync warning for a hand-line (no atom sources)', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    const handLine = {
      line_item_id: 2, line_number: 1, description: 'Hand entry', qty: '1', units: 'each',
      price: '999', accounting_category: null, sources: [],
    };
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [handLine] }));
    const { findByText, queryByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Hand entry');
    expect(queryByText(/out of sync/)).toBeNull();
  });
});

describe('EstimatePanel line-item actions', () => {
  it('shows Edit/Delete buttons on line items of a draft estimate', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [
      { line_item_id: 1, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
        price: '5', accounting_category: null, sources: [] },
    ] }));
    const { findByText, queryByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
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
    const { findByText, queryByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Cut');
    expect(queryByText('Edit')).toBeNull();
    expect(queryByText('Delete')).toBeNull();
  });

  it('shows a single "Add line" button on a draft estimate', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [] }));
    const { findByText, queryByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    expect(await findByText('Add line')).toBeInTheDocument();
    expect(queryByText('Add Line Item')).toBeNull();
    expect(queryByText('Add from Service')).toBeNull();
  });

  it('hides the "Add line" button when the estimate is not editable (sent)', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'open', line_items: [] }));
    const { findByText, queryByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText(/Estimate:/);
    expect(queryByText('Add line')).toBeNull();
  });

  it('Delete on a line calls the line-item delete endpoint', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [
      { line_item_id: 42, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
        price: '5', accounting_category: null, sources: [] },
    ] }));
    api.delete.mockResolvedValue({ message: 'deleted' });
    const { findByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    const deleteBtn = await findByText('Delete');
    deleteBtn.click();
    expect(api.delete).toHaveBeenCalledWith('/api/estimates/7/line-items/42/');
  });
});

describe('EstimatePanel reconcile mode', () => {
  beforeEach(() => { localStorage.clear(); });

  function mockReconcile(estimate) {
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url === `/api/estimates/${estimate.estimate_id}/`) return Promise.resolve({ ...estimate });
      if (url === `/api/estimates/${estimate.estimate_id}/line-items/`) return Promise.resolve({ results: [] });
      if (url === `/api/estimates/${estimate.estimate_id}/source-pool/`) return Promise.resolve({ atoms: [] });
      if (url.startsWith('/api/estimates/?job=')) return Promise.resolve({ results: [estimate] });
      if (url.startsWith('/api/change-orders/?job=')) return Promise.resolve({ results: [] });
      if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [] });
      if (url.startsWith('/api/settings/')) return Promise.resolve({});
      return Promise.resolve({});
    });
  }

  it('flips to reconcile mode and persists the choice per docId', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockReconcile(makeEstimate({ estimate_id: 7, can_manage: true, status: 'draft' }));
    const { findByRole, findByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await fireEvent.click(await findByRole('button', { name: 'Reconcile' }));
    expect(await findByText('Source pool (job atoms)')).toBeInTheDocument();
    expect(getJobWs(9).modes['est:7']).toBe('reconcile');
    expect(await findByRole('button', { name: 'Back to lines' })).toBeInTheDocument();
  });

  it('restores reconcile mode on mount for a draft doc when remembered', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    rememberMode(9, 'est:7', 'reconcile');
    mockReconcile(makeEstimate({ estimate_id: 7, can_manage: true, status: 'draft' }));
    const { findByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    expect(await findByText('Source pool (job atoms)')).toBeInTheDocument();
  });

  it('does NOT restore reconcile from an INVOICE with the same numeric id (namespaced keys)', async () => {
    // Regression: modes were once keyed by bare docId, so invoice #7 in
    // reconcile bled into estimate #7 on the same job. Keys are namespaced
    // (est:/inv:) — the invoice memory must not open the estimate in reconcile.
    user.set({ permissions: ['can_manage_jobs'] });
    rememberMode(9, 'inv:7', 'reconcile');
    mockReconcile(makeEstimate({ estimate_id: 7, can_manage: true, status: 'draft' }));
    const { findByText, queryByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Line Items');
    expect(queryByText('Source pool (job atoms)')).toBeNull();
  });

  it('restores lines (not reconcile) for a SENT doc even when reconcile was remembered', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    rememberMode(9, 'est:7', 'reconcile');
    mockReconcile(makeEstimate({ estimate_id: 7, can_manage: true, status: 'open' }));
    const { findByText, queryByText, queryByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Line Items');
    expect(queryByText('Source pool (job atoms)')).toBeNull();
    expect(queryByRole('button', { name: 'Reconcile' })).toBeNull();
    expect(queryByRole('button', { name: 'Back to lines' })).toBeNull();
  });

  it('reloads the estimate when flipping back to lines', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockReconcile(makeEstimate({ estimate_id: 7, can_manage: true, status: 'draft' }));
    const { findByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await fireEvent.click(await findByRole('button', { name: 'Reconcile' }));
    await findByRole('button', { name: 'Back to lines' });
    const before = api.get.mock.calls.filter(([u]) => u === '/api/estimates/7/').length;
    await fireEvent.click(await findByRole('button', { name: 'Back to lines' }));
    expect(api.get.mock.calls.filter(([u]) => u === '/api/estimates/7/').length).toBeGreaterThan(before);
    expect(getJobWs(9).modes['est:7']).toBe('lines');
  });
});

describe('EstimatePanel adjustment affordances', () => {
  it('shows "Add adjustment" button on a draft estimate with can_manage', async () => {
    user.set({ permissions: [] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft' }));
    const { findByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    expect(await findByText('Add Adjustment')).toBeInTheDocument();
  });

  it('does NOT show "Add adjustment" on a non-draft estimate', async () => {
    user.set({ permissions: [] });
    mockApi(makeEstimate({ can_manage: true, status: 'open' }));
    const { findByText, queryByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Line Items');
    expect(queryByText('Add Adjustment')).not.toBeInTheDocument();
  });

  it('does NOT show "Add adjustment" when can_manage is false', async () => {
    user.set({ permissions: [] });
    mockApi(makeEstimate({ can_manage: false, status: 'draft' }));
    const { findByText, queryByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Line Items');
    expect(queryByText('Add Adjustment')).not.toBeInTheDocument();
  });

  it('opens AdjustmentModal when "Add adjustment" is clicked', async () => {
    user.set({ permissions: [] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft' }));
    const { findByText, findByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await fireEvent.click(await findByText('Add Adjustment'));
    expect(await findByRole('dialog')).toBeInTheDocument();
  });

  it('does NOT show a Recalculate button on a draft adjustment line (auto-recompute)', async () => {
    user.set({ permissions: [] });
    const adjLine = {
      line_item_id: 99, line_number: 1, description: 'Rush 15%',
      qty: 1, price: '10.00', units: 'none', accounting_category: null,
      adjustment_service: ADJ_SERVICE, target_categories: [],
      sources: [],
    };
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [adjLine] }));
    const { findByText, queryByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Line Items');
    expect(queryByRole('button', { name: /recalculate/i })).not.toBeInTheDocument();
  });
});
