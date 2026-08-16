import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, within, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Something went wrong.',
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
    total: '0.00',
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
    if (estimate && url === `/api/estimates/${estimate.estimate_id}/source-pool/`) {
      return Promise.resolve({ atoms: [] });
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
    if (url.includes('source-pool')) return Promise.resolve({ atoms: [] });
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

    await findByText(/Estimate: EST-7-\d/);
    const links = Array.from(container.querySelectorAll('.doc-subnav a'));
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute('href', '#/jobs/9/estimate/7');
    expect(links[0]).toHaveTextContent('EST-7-1');
    expect(links[1]).toHaveAttribute('href', '#/jobs/9/estimate/8');
    expect(links[1]).toHaveTextContent('EST-7-2');
    expect(links[1]).toHaveClass('active');
    expect(links[0]).not.toHaveClass('active');
  });

  it('loads accounting categories from the unfiltered endpoint (no exclude_fallback param)', async () => {
    user.set({ permissions: [] });
    const v1 = makeEstimate({ estimate_id: 7, version: 1, status: 'superseded' });
    const v2 = makeEstimate({ estimate_id: 8, version: 2, status: 'draft' });
    mockApi(v2, { versions: [v1, v2] });

    render(EstimatePanel, { props: { job: JOB, estimateId: 8 } });

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/api/accounting-categories/?page_size=100');
    });
  });

  it('appends change orders after estimate versions, linking to /change-orders/:id', async () => {
    user.set({ permissions: [] });
    const v1 = makeEstimate({ estimate_id: 7, version: 1, status: 'accepted' });
    const co = { change_order_id: 3, change_order_number: 'CO-3', status: 'open', estimate: 7 };
    mockApi(v1, { versions: [v1], changeOrders: [co] });

    const { findByText, container } = render(EstimatePanel, {
      props: { job: JOB, estimateId: 7 },
    });

    await findByText(/Estimate: EST-7-\d/);
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

  it('offers Unexpire on an expired estimate to a can_manage_jobs holder and reloads in place', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    const est = makeEstimate({ estimate_id: 7, status: 'expired', can_manage: false });
    mockApi(est, { versions: [est] });
    api.post.mockResolvedValue({ estimate_id: 7, status: 'open' });
    const onJobChange = vi.fn();
    const { findByRole } = render(EstimatePanel, {
      props: { job: JOB, estimateId: 7, onJobChange },
    });
    const btn = await findByRole('button', { name: /unexpire/i });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const getCalls = api.get.mock.calls.length;
    await fireEvent.click(btn);
    expect(api.post).toHaveBeenCalledWith('/api/estimates/7/unexpire/');
    // In-place reload, not a hash navigation: no new job/estimate to jump to.
    await vi.waitFor(() => expect(api.get.mock.calls.length).toBeGreaterThan(getCalls));
    await vi.waitFor(() => expect(onJobChange).toHaveBeenCalled());
  });

  it('offers Unexpire to a can_manage_financials holder (no can_manage_jobs)', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const est = makeEstimate({ estimate_id: 7, status: 'expired', can_manage: false });
    mockApi(est, { versions: [est] });
    const { findByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    expect(await findByRole('button', { name: /unexpire/i })).toBeInTheDocument();
  });

  it('hides Unexpire without can_manage_jobs or can_manage_financials, even as the job PM (can_manage true)', async () => {
    // Unlike every other action here, Unexpire is NOT PM-scoped.
    user.set({ permissions: [] });
    const est = makeEstimate({ estimate_id: 7, status: 'expired', can_manage: true });
    mockApi(est, { versions: [est] });
    const { findByText, queryByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText(/Estimate: EST-7-\d/);
    expect(queryByRole('button', { name: /unexpire/i })).toBeNull();
  });

  it('does not offer Unexpire on a non-expired estimate', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    const est = makeEstimate({ estimate_id: 7, status: 'open' });
    mockApi(est, { versions: [est] });
    const { findByText, queryByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText(/Estimate: EST-7-\d/);
    expect(queryByRole('button', { name: /unexpire/i })).toBeNull();
  });

  it('hides Create Change Order while the job is not held (API would refuse)', async () => {
    // CO drafting happens inside a hold episode; the button only shows when
    // the click can actually succeed.
    user.set({ permissions: [] });
    const est = makeEstimate({ estimate_id: 7, status: 'accepted' });
    mockApi(est, { versions: [est] });
    const { findByText, queryByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText(/Estimate: EST-7-\d/);
    expect(queryByRole('button', { name: /create change order/i })).toBeNull();
  });

  it('offers Create Change Order on an accepted estimate (held job) and posts it', async () => {
    user.set({ permissions: [] });
    const est = makeEstimate({ estimate_id: 7, status: 'accepted' });
    mockApi(est, { versions: [est] });
    api.post.mockResolvedValue({ change_order_id: 42 });
    const { findByRole } = render(EstimatePanel, { props: { job: { ...JOB, on_hold: true }, estimateId: 7 } });
    const btn = await findByRole('button', { name: /create change order/i });
    await fireEvent.click(btn);
    expect(api.post).toHaveBeenCalledWith('/api/change-orders/', { job: 9 });
  });

  it('does not offer Create Change Order on a non-accepted estimate', async () => {
    user.set({ permissions: [] });
    const est = makeEstimate({ estimate_id: 7, status: 'open' });
    mockApi(est, { versions: [est] });
    const { findByText, queryByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText(/Estimate: EST-7-\d/);
    expect(queryByRole('button', { name: /create change order/i })).toBeNull();
  });

  it('hides Create Change Order once the job already has a change order', async () => {
    // The FIRST CO is created from the accepted estimate; every further CO
    // chains off the previous one via the CO page's seed-new flow.
    user.set({ permissions: [] });
    const est = makeEstimate({ estimate_id: 7, status: 'accepted' });
    mockApi(est, {
      versions: [est],
      changeOrders: [{ change_order_id: 3, change_order_number: 'CO-3', status: 'draft' }],
    });
    const { findByText, queryByRole } = render(EstimatePanel, { props: { job: { ...JOB, on_hold: true }, estimateId: 7 } });
    await findByText(/Estimate: EST-7-\d/);
    expect(queryByRole('button', { name: /create change order/i })).toBeNull();
  });
});

describe('EstimatePanel status pill job refresh', () => {
  it('pings onJobChange after a successful transition (acceptance drives job status)', async () => {
    // Accepting an estimate approves the job (rejecting can reject it) — the
    // host's job header must refresh without a manual page reload, same as
    // ChangeOrderPanel does on CO acceptance.
    user.set({ permissions: [] });
    const est = makeEstimate({ estimate_id: 7, status: 'open' });
    mockApi(est, { versions: [est] });
    api.patch.mockResolvedValue({});
    const onJobChange = vi.fn();
    const { findByRole } = render(EstimatePanel, {
      props: { job: JOB, estimateId: 7, onJobChange },
    });
    await fireEvent.change(await findByRole('combobox'), { target: { value: 'accepted' } });
    await vi.waitFor(() => expect(onJobChange).toHaveBeenCalled());
  });
});

describe('EstimatePanel status pill in-flight guard', () => {
  it('ignores a second change while the first PATCH is in flight', async () => {
    user.set({ permissions: [] });
    const est = makeEstimate({ estimate_id: 7, status: 'open' });
    mockApi(est, { versions: [est] });
    let resolvePatch;
    api.patch.mockImplementation(
      () => new Promise((resolve) => { resolvePatch = resolve; }));
    const { findByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    const select = await findByRole('combobox');
    await fireEvent.change(select, { target: { value: 'accepted' } });
    expect(select.disabled).toBe(true);
    // A stray second change before the first PATCH settles must not fire.
    await fireEvent.change(select, { target: { value: 'rejected' } });
    expect(api.patch).toHaveBeenCalledTimes(1);
    resolvePatch({});
  });
});

describe('EstimatePanel empty state', () => {
  it('shows a can_manage-gated Start Estimate button when a quoting-phase job has no estimates', async () => {
    user.set({ permissions: [] });
    mockApi(null, { versions: [] });
    const { findByRole } = render(EstimatePanel, {
      props: { job: { ...JOB, status: 'draft', can_manage: true }, estimateId: null },
    });
    expect(await findByRole('button', { name: /start estimate/i })).toBeInTheDocument();
  });

  it('shows a plain message (no button) when the job has no estimates and no can_manage', async () => {
    user.set({ permissions: [] });
    mockApi(null, { versions: [] });
    const { findByText, queryByRole } = render(EstimatePanel, {
      props: { job: { ...JOB, status: 'draft', can_manage: false }, estimateId: null },
    });
    expect(await findByText('No estimates yet.')).toBeInTheDocument();
    expect(queryByRole('button', { name: /start estimate/i })).not.toBeInTheDocument();
  });

  it('hides Start Estimate on a job past the quoting phase and explains why', async () => {
    // A hand-approved estimate-less job is past estimating — the backend
    // refuses the create, so the button would be a guaranteed error.
    user.set({ permissions: [] });
    mockApi(null, { versions: [] });
    const { findByText, queryByRole } = render(EstimatePanel, {
      props: { job: { ...JOB, status: 'approved', can_manage: true }, estimateId: null },
    });
    expect(await findByText(/past the estimating phase/i)).toBeInTheDocument();
    expect(queryByRole('button', { name: /start estimate/i })).not.toBeInTheDocument();
  });

  it('Start Estimate posts and navigates to the job-scoped estimate URL', async () => {
    user.set({ permissions: [] });
    mockApi(null, { versions: [] });
    api.post.mockResolvedValue({ estimate_id: 42 });
    const { findByRole } = render(EstimatePanel, {
      props: { job: { ...JOB, status: 'draft', can_manage: true }, estimateId: null },
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
  it('shows the dash-joined number-version in the title (field table is gone)', async () => {
    user.set({ permissions: [] });
    mockApi(makeEstimate({ estimate_number: 'EST-7', version: 2 }));
    const { container, findByText, queryByText } = render(EstimatePanel, {
      props: { job: JOB, estimateId: 7 },
    });
    await findByText('Created');
    expect(container.textContent).toContain('EST-7-2');
    // the two-column field table is retired — chips carry the dates
    expect(queryByText('Estimate Number')).toBeNull();
    expect(queryByText('Version')).toBeNull();
  });
});

describe('EstimatePanel mode bar labels', () => {
  it('offers Edit / Customer / Reorder — no wizard-era wording', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft' }));

    const { findByText, queryByText } = render(EstimatePanel, {
      props: { job: JOB, estimateId: 7 },
    });

    await findByText('Line Items');
    expect(await findByText('Edit view')).toBeInTheDocument();
    expect(await findByText('Customer view')).toBeInTheDocument();
    expect(await findByText('Reorder view')).toBeInTheDocument();
    expect(queryByText('Show Tasks & Materials')).toBeNull();
    expect(queryByText('Reconcile')).toBeNull();
    expect(queryByText('Plan')).toBeNull();
    expect(queryByText('Worksheet')).toBeNull();
  });

  it('relabels Edit to Detail and drops Reorder when the estimate is not editable (sent)', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'open' }));

    const { findByText, queryByText } = render(EstimatePanel, {
      props: { job: JOB, estimateId: 7 },
    });

    await findByText('Line Items');
    expect(await findByText('Detail view')).toBeInTheDocument();
    expect(await findByText('Customer view')).toBeInTheDocument();
    expect(queryByText('Edit view')).toBeNull();
    expect(queryByText('Reorder view')).toBeNull();
  });
});

describe('EstimatePanel line-item actions', () => {
  it('shows Edit/Remove buttons on line items of a draft estimate', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [
      { line_item_id: 1, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
        price: '5', accounting_category: null, sources: [], backing: 'hand', backing_total: null },
    ] }));
    const { findByText, container } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Cut');
    // The mode bar also has an "Edit" label — scope to the line-items table
    // itself to avoid that ambiguity.
    const table = within(container.querySelector('table.line-items-table'));
    expect(table.queryByText('Edit')).not.toBeNull();
    expect(table.queryByText('Remove')).not.toBeNull();
  });

  it('hides Edit/Remove when the estimate is not editable (sent)', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'open', line_items: [
      { line_item_id: 1, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
        price: '5', accounting_category: null, sources: [], backing: 'hand', backing_total: null },
    ] }));
    const { findByText, container } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Cut');
    const table = within(container.querySelector('table.line-items-table'));
    expect(table.queryByText('Edit')).toBeNull();
    expect(table.queryByText('Remove')).toBeNull();
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

  it('Remove on a line calls the line-item DELETE endpoint (single-phase, no confirm)', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [
      { line_item_id: 42, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
        price: '5', accounting_category: null, sources: [], backing: 'hand', backing_total: null },
    ] }));
    api.delete.mockResolvedValue({ message: 'Line item deleted.' });
    const { findByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    const removeBtn = await findByText('Remove');
    await fireEvent.click(removeBtn);
    expect(api.delete).toHaveBeenCalledWith('/api/estimates/7/line-items/42/');
  });

  it('never renders the word "delete" anywhere in the edit view', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [
      { line_item_id: 1, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
        price: '5', accounting_category: null, sources: [], backing: 'hand', backing_total: null },
    ] }));
    const { findByText, queryByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Cut');
    expect(queryByText(/delete/i)).toBeNull();
  });
});

describe('EstimatePanel mode bar', () => {
  beforeEach(() => { localStorage.clear(); });

  const LINE = {
    line_item_id: 1, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
    price: '5', accounting_category: null, sources: [], backing: 'hand', backing_total: null,
  };

  it('switches between Edit / Customer / Reorder views in place and persists the choice per docId', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ estimate_id: 7, can_manage: true, status: 'draft', line_items: [LINE], total: '10.00' }));
    const { container, findByText, queryByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Cut');

    const modeBar = () => container.querySelector('.doc-mode-bar');
    await fireEvent.click(within(modeBar()).getByRole('button', { name: 'Customer view' }));
    expect(await findByText('Estimate EST-7-1')).toBeInTheDocument();
    expect(queryByText('Add line')).toBeNull();
    expect(getJobWs(9).modes['est:7']).toBe('customer');

    await fireEvent.click(within(modeBar()).getByRole('button', { name: 'Reorder view' }));
    expect(container.querySelectorAll('.doc-reorder-arrows').length).toBeGreaterThan(0);
    expect(getJobWs(9).modes['est:7']).toBe('reorder');

    await fireEvent.click(within(modeBar()).getByRole('button', { name: 'Edit view' }));
    expect(await findByText('Add line')).toBeInTheDocument();
    expect(getJobWs(9).modes['est:7']).toBe('edit');
  });

  it('normalizes a remembered "reconcile" (old wizard toggle) to Edit mode', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    rememberMode(9, 'est:7', 'reconcile');
    mockApi(makeEstimate({ estimate_id: 7, can_manage: true, status: 'draft', line_items: [LINE] }));
    const { container, findByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Add line');
    const modeBar = container.querySelector('.doc-mode-bar');
    expect(within(modeBar).getByRole('button', { name: 'Edit view' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('normalizes a remembered "lines" (old two-mode panel) to Edit mode', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    rememberMode(9, 'est:7', 'lines');
    mockApi(makeEstimate({ estimate_id: 7, can_manage: true, status: 'draft', line_items: [LINE] }));
    const { container, findByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Add line');
    const modeBar = container.querySelector('.doc-mode-bar');
    expect(within(modeBar).getByRole('button', { name: 'Edit view' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('does NOT restore from an INVOICE with the same numeric id (namespaced keys)', async () => {
    // Regression guard carried over from the old reconcile-toggle memory:
    // modes are namespaced (est:/inv:) so an invoice's remembered mode
    // never bleeds into an estimate with the same numeric id.
    user.set({ permissions: ['can_manage_jobs'] });
    rememberMode(9, 'inv:7', 'reorder');
    mockApi(makeEstimate({ estimate_id: 7, can_manage: true, status: 'draft', line_items: [LINE] }));
    const { container, findByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Add line');
    const modeBar = container.querySelector('.doc-mode-bar');
    expect(within(modeBar).getByRole('button', { name: 'Edit view' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('falls back to Detail when "reorder" was remembered but the estimate is no longer editable', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    rememberMode(9, 'est:7', 'reorder');
    mockApi(makeEstimate({ estimate_id: 7, can_manage: true, status: 'open', line_items: [LINE] }));
    const { container, findByText, queryByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Cut');
    expect(queryByText('Add line')).toBeNull(); // not editable — the mode shows as Detail
    const modeBar = container.querySelector('.doc-mode-bar');
    expect(within(modeBar).getByRole('button', { name: 'Detail view' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(modeBar).queryByRole('button', { name: 'Reorder view' })).toBeNull();
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
      adjustment_service: ADJ_SERVICE.rate_scheme_id, target_categories: [],
      sources: [], backing: 'adjustment', backing_total: null,
    };
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [adjLine] }));
    const { findByText, queryByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Line Items');
    expect(queryByRole('button', { name: /recalculate/i })).not.toBeInTheDocument();
  });
});

describe('EstimatePanel create-line-from-selected integration (silent refresh)', () => {
  // Regression coverage for the bug a code review caught: EstimateEditView's
  // create-line -> edit-modal handoff only "worked" in EstimateEditView's own
  // unit test because that test's onChanged mock does nothing. Wired through
  // the real EstimatePanel, the old (non-silent) refresh flipped docLoading
  // synchronously, which tore down and remounted EstimateEditView — resetting
  // modalOpen before the user ever saw the naming modal. This test exercises
  // the full tick -> Create line -> modal-visible path against the real panel.
  it('tick a pool atom, "Create line" survives the refresh (no full-panel reload) and opens the edit modal', async () => {
    user.set({ permissions: ['can_manage_jobs'] });

    const LINE = {
      line_item_id: 1, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
      price: '5', accounting_category: 3, sources: [], backing: 'hand', backing_total: null,
    };
    const POOL_ATOM = {
      type: 'task', id: 41, description: 'Sand edges', qty: '1', rate: '30.00',
      amount: '30.00', units: 'hour', category_id: null, state: 'available',
      claiming_line_item_id: null, claiming_line_number: null,
      claiming_estimate_id: null, claiming_estimate_number: null,
    };
    const NEW_LINE = {
      line_item_id: 99, line_number: 2, description: '', qty: '1', units: 'hour',
      price: '30.00', accounting_category: null, sources: [], backing: 'planned_work', backing_total: '30.00',
    };

    // Mutable so the mocked GET reflects the server-side effect of the POST
    // below — this is what lets the test actually exercise "look the created
    // line up in the refreshed lineItems", not just fall back to the raw
    // POST response.
    let currentLineItems = [LINE];
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url === '/api/estimates/7/') {
        return Promise.resolve(makeEstimate({ can_manage: true, status: 'draft', line_items: currentLineItems }));
      }
      if (url === '/api/estimates/7/source-pool/') return Promise.resolve({ atoms: [POOL_ATOM] });
      if (url.startsWith('/api/estimates/?job=')) return Promise.resolve({ results: [makeEstimate()] });
      if (url.startsWith('/api/change-orders/?job=')) return Promise.resolve({ results: [] });
      if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [] });
      if (url.startsWith('/api/settings/')) return Promise.resolve({});
      return Promise.resolve({});
    });
    api.post.mockImplementation((url) => {
      if (url === '/api/estimates/7/line-items-from-atoms/') {
        currentLineItems = [...currentLineItems, NEW_LINE];
        return Promise.resolve({ ...NEW_LINE });
      }
      return Promise.resolve({});
    });

    const { findByText, findByRole, container } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Cut');

    const checkbox = container.querySelector('input[type="checkbox"]');
    await fireEvent.click(checkbox);
    const createBtn = await findByText(/create line/i);
    await fireEvent.click(createBtn);

    const dialog = await findByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText('Edit Line Item')).toBeInTheDocument();

    // The panel must never have blanked to the full "Loading…" state, and
    // the edit view (Add line, etc.) must still be there behind the modal —
    // proof EstimateEditView was never torn down mid-gesture.
    expect(container.textContent).not.toContain('Loading...');
    expect(container.textContent).toContain('Add line');
  });
});

describe('EstimatePanel canMint (Task 7)', () => {
  const UNANSWERED_LINE = {
    line_item_id: 1, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
    price: '5', accounting_category: 3, is_material: false, inventory_item: null,
    service_item: null, adjustment_service: null, sources: [], work_declined: false,
    backing: 'hand', backing_total: null,
  };

  it('offers "Generate work…" / "No work needed" on an accepted estimate for a can_manage_jobs holder', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'accepted', line_items: [UNANSWERED_LINE] }));
    const { findByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    expect(await findByRole('button', { name: 'Generate work…' })).toBeInTheDocument();
    expect(await findByRole('button', { name: 'No work needed' })).toBeInTheDocument();
  });

  it('hides mint affordances on a draft estimate even for a can_manage_jobs holder', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'draft', line_items: [UNANSWERED_LINE] }));
    const { findByText, queryByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Cut');
    expect(queryByRole('button', { name: 'Generate work…' })).toBeNull();
  });

  it('hides mint affordances on an accepted estimate without can_manage_jobs (not this job\'s PM)', async () => {
    user.set({ permissions: [] });
    mockApi(makeEstimate({ can_manage: false, status: 'accepted', line_items: [UNANSWERED_LINE] }));
    const { findByText, queryByRole } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    await findByText('Cut');
    expect(queryByRole('button', { name: 'Generate work…' })).toBeNull();
  });

  it('shows the checklist banner on an accepted estimate with an unanswered line', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'accepted', line_items: [UNANSWERED_LINE] }));
    const { findByText } = render(EstimatePanel, { props: { job: JOB, estimateId: 7 } });
    expect(await findByText(
      '1 line(s) need a work decision — the job starts automatically when all are answered.'
    )).toBeInTheDocument();
  });

  it('"No work needed" PATCHes work_declined and pings onJobChange (auto-release may have fired)', async () => {
    user.set({ permissions: ['can_manage_jobs'] });
    mockApi(makeEstimate({ can_manage: true, status: 'accepted', line_items: [UNANSWERED_LINE] }));
    api.patch.mockResolvedValue({});
    const onJobChange = vi.fn();
    const { findByRole } = render(EstimatePanel, {
      props: { job: JOB, estimateId: 7, onJobChange },
    });
    await fireEvent.click(await findByRole('button', { name: 'No work needed' }));
    expect(api.patch).toHaveBeenCalledWith('/api/estimates/7/line-items/1/', { work_declined: true });
    await waitFor(() => expect(onJobChange).toHaveBeenCalled());
  });
});

describe('EstimatePanel Make Deliverable refresh chain', () => {
  it('POSTs make-deliverable and fires onJobChange so the deliverables band reloads', async () => {
    const estimate = makeEstimate({
      line_items: [{
        line_item_id: 31, line_number: 1, description: 'Chairs', qty: '3',
        units: 'ea', price: '500.00', accounting_category: 3, sources: [],
        backing: 'hand', linked_deliverables: [],
      }],
    });
    mockApi(estimate);
    api.post = vi.fn().mockResolvedValue({ id: 9 });
    const onJobChange = vi.fn();
    const { findByRole } = render(EstimatePanel, {
      props: { job: JOB, estimateId: 7, onJobChange },
    });
    const btn = await findByRole('button', { name: 'Make Deliverable' });
    await fireEvent.click(btn);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        '/api/estimates/7/line-items/31/make-deliverable/');
      expect(onJobChange).toHaveBeenCalled();
    });
  });
});
